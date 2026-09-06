"""Release 1.1 regressions. No production credentials, network services or accounts."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import sqlite3
import unittest
from app import catalog, db, security
from app.config import Config, ROOT, LANGUAGES
from app.games import GAMES, EXTRA_GAMES, OPTIONS, result_for
from app.money import money, infinity, currency
from app.web import App, Request, safe_next
from tests.helpers import Client

PASSWORD = 'Dopamine-Upgrade!Test-2026'

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'test.sqlite3'; db.initialize(self.path)
        self.config = Config(secret='release-test-secret-only-'*4, database=self.path,
            site_url='http://localhost', allowed_hosts=('localhost',), secure=False,
            require_local_photos=False, testing=True)
        self.app = App(self.config); self.client = Client(self.app)
    def scalar(self, sql, params=()):
        with closing(db.connect(self.path)) as c: return c.execute(sql, params).fetchone()[0]
    def signup(self, client=None, name='upgrade_user', lang='pt-br'):
        client=client or self.client
        page=client.get('/signup?lang='+lang)
        r=client.submit(page,'/signup',nickname=name,password=PASSWORD,adult='yes')
        self.assertEqual(r.status,200,r.text)
        return r
    def clear_rates(self):
        with closing(db.connect(self.path)) as c:c.execute('DELETE FROM rate_limits')
    def play(self, game, **fields):
        page=self.client.get('/casino/'+game)
        r=self.client.submit(page,'/casino/'+game,stake='500',**fields)
        self.assertEqual(r.status,303,r.text)
        return r

    def test_registration_headers_keep_origin_and_zero_javascript(self):
        r=self.client.get('/signup')
        self.assertEqual(r.header('Referrer-Policy'),'same-origin')
        self.assertIn("script-src 'none'",r.header('Content-Security-Policy'))
        self.assertEqual(r.header('X-Dopamine-Version'),'1.2.0')
        self.assertIn('no-store',r.header('Cache-Control'))
        self.assertNotIn('<script',r.text)

    def test_signup_all_four_languages_preserves_language(self):
        for n,lang in enumerate(LANGUAGES):
            c=Client(self.app,ip=f'203.0.113.{50+n}')
            self.signup(c,'language_'+str(n),lang)
            self.assertEqual(self.scalar('SELECT language FROM users WHERE nickname=?',('language_'+str(n),)),lang)
            self.assertIn(currency(lang).symbol,c.get('/profile').text)

    def test_null_origin_stays_rejected_without_creating_user(self):
        p=self.client.get('/signup');f=dict(p.form('/signup'),nickname='null_origin',password=PASSWORD,adult='yes')
        r=self.client.post('/signup',f,headers={'HTTP_ORIGIN':'null'})
        self.assertEqual(r.status,403);self.assertEqual(self.scalar('SELECT COUNT(*) FROM users'),0)
        self.assertIn('role="alert"',r.text);self.assertIn('value="null_origin"',r.text)
        self.assertNotIn(PASSWORD,r.text)
        # A fresh same-origin form works without clearing CSRF checks.
        r=self.client.submit(self.client.get('/signup'),'/signup',nickname='null_origin',password=PASSWORD,adult='yes')
        self.assertEqual(r.status,200)

    def test_cross_origin_and_sibling_origin_rejected(self):
        p=self.client.get('/signup');f=dict(p.form('/signup'),nickname='foreign_test',password=PASSWORD,adult='yes')
        for origin in ('http://localhost.attacker.test','https://localhost','http://sub.localhost','file://localhost','http://localhost/','http://localhost:81'):
            with self.subTest(origin=origin):
                self.assertEqual(self.client.post('/signup',f,headers={'HTTP_ORIGIN':origin}).status,403)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM users'),0)

    def test_fetch_metadata_cross_site_denied_even_with_valid_token(self):
        p=self.client.get('/signup');f=dict(p.form('/signup'),nickname='fetch_test',password=PASSWORD,adult='yes')
        for site in ('cross-site','same-site'):
            self.assertEqual(self.client.post('/signup',f,headers={'HTTP_SEC_FETCH_SITE':site}).status,403)
        self.assertEqual(self.client.post('/signup',f,headers={'HTTP_SEC_FETCH_SITE':'same-origin'}).status,200)

    def test_default_port_and_hostname_case_origin_normalization(self):
        self.assertTrue(security.same_origin('http://LOCALHOST:80','http://localhost'))
        self.assertTrue(security.same_origin('https://example.test:443','https://example.test'))
        for bad in ('null','','https://example.test:444','https://example.test:0','https://user@example.test','https://example.test/','https://example.test?x=1','https://example.test\n','https://example.test#x'):
            self.assertFalse(security.same_origin(bad,'https://example.test'),bad)

    def test_expired_session_fresh_error_form_no_silent_post_replay(self):
        p=self.client.get('/signup');f=dict(p.form('/signup'),nickname='expired_test',password=PASSWORD,adult='yes')
        self.client.cookies.clear()
        r=self.client.post('/signup',f)
        self.assertEqual(r.status,403);self.assertNotEqual(r.form('/signup')['csrf'],f['csrf'])
        self.assertNotIn(PASSWORD,r.text);self.assertEqual(self.scalar('SELECT COUNT(*) FROM users'),0)
        self.assertEqual(self.client.submit(r,'/signup',nickname='expired_test',password=PASSWORD,adult='yes').status,200)

    def test_signup_validation_retains_nickname_not_secret(self):
        p=self.client.get('/signup?lang=en')
        r=self.client.submit(p,'/signup',nickname='valid_name',password='123',adult='yes')
        self.assertEqual(r.status,400);self.assertIn('value="valid_name"',r.text)
        self.assertIn('value="en"',r.text);self.assertNotIn('value="123"',r.text)
        self.assertIn('maxlength="128"',r.text)
        self.assertEqual(self.client.submit(r,'/signup',nickname='valid_name',password=PASSWORD,adult='yes').status,200)

    def test_error_values_escaped_and_recovery_not_echoed(self):
        p=self.client.get('/recover')
        r=self.client.submit(p,'/recover',nickname='"><svg/onload=1>',password=PASSWORD,recovery_code='sensitive-recovery-material')
        self.assertEqual(r.status,400)
        self.assertNotIn('<svg/onload=1>',r.text);self.assertNotIn('sensitive-recovery-material',r.text)
        self.assertNotIn(PASSWORD,r.text)

    def test_signup_session_failure_is_atomic(self):
        p=self.client.get('/signup')
        with patch.object(Request,'rotate',side_effect=sqlite3.OperationalError('simulated session failure')):
            with self.assertLogs('dopamine',level='ERROR'):
                r=self.client.submit(p,'/signup',nickname='atomic_test',password=PASSWORD,adult='yes')
        self.assertEqual(r.status,503);self.assertEqual(self.scalar('SELECT COUNT(*) FROM users'),0)

    def test_secure_proxy_signup_with_host_cookie(self):
        cfg=replace(self.config,secure=True,site_url='https://dopamine.securityops.co',allowed_hosts=('dopamine.securityops.co',),proxy_cidrs=('172.18.0.2/32',))
        c=Client(App(cfg),ip='172.18.0.2')
        headers={'HTTP_HOST':'dopamine.securityops.co','HTTP_X_FORWARDED_PROTO':'https','HTTP_X_REAL_IP':'203.0.113.90','HTTP_ORIGIN':'https://dopamine.securityops.co'}
        p=c.get('/signup',headers=headers)
        cookie=p.header('Set-Cookie')
        for piece in ('__Host-dopamine=','Secure','HttpOnly','SameSite=Lax','Path=/'):self.assertIn(piece,cookie)
        f=dict(p.form('/signup'),nickname='proxy_signup',password=PASSWORD,adult='yes')
        self.assertEqual(c.post('/signup',f,headers=headers).status,200)
        self.assertEqual(c.get('/profile',headers=headers).status,200)

    def test_currency_formatting_and_type_rejection(self):
        expected={'pt-br':'R$ 1.234.567,00','en':'US$ 1,234,567.00','zh':'CN¥ 1,234,567.00','ja':'JP¥ 1,234,567'}
        for lang,value in expected.items():
            self.assertEqual(money(1234567,lang),value)
            self.assertEqual(infinity(lang),currency(lang).symbol+' ∞')
        for invalid in (True,1.2,'100',None):
            with self.assertRaises(TypeError):money(invalid)
        self.assertEqual(money(0),'R$ 0,00');self.assertEqual(money(-5),'−R$ 5,00')
        self.assertEqual(currency('unknown').code,'BRL')

    def test_about_explains_display_only_currency_in_every_language(self):
        for lang in LANGUAGES:
            r=self.client.get('/about?lang='+lang)
            self.assertEqual(r.status,200)
            self.assertIn('id="currency"',r.text)
            for code in ('BRL','USD','CNY','JPY'):self.assertIn(code,r.text)

    def test_historical_prices_not_converted_when_language_changes(self):
        self.signup()
        p=self.client.get('/product/real-porsche-911')
        r=self.client.submit(p,'/buy/real-porsche-911',quantity='2')
        expected=catalog.PRODUCTS['real-porsche-911']['credits']
        for lang in LANGUAGES:
            receipt=self.client.get(r.location+'?lang='+lang)
            self.assertEqual(receipt.status,200)
            self.assertIn(money(expected*2,lang),receipt.text)
        self.assertEqual(self.scalar('SELECT unit_credits FROM purchase_items'),expected)

    def test_all_existing_product_ids_and_prices_preserved(self):
        old=json.loads((ROOT/'tests/fixtures/catalog-v1.json').read_text())
        self.assertEqual(len(old),128)
        for pid,value in old.items():self.assertEqual(catalog.LEGACY[pid]['credits'],value,pid)
        self.assertGreaterEqual(len(catalog.PRODUCTS),400)
        self.assertEqual(len({p['photo'] for p in catalog.PRODUCTS.values()}),len(catalog.PRODUCTS))

    def test_all_ten_games_and_rounds_render_in_four_languages(self):
        self.signup()
        for game in GAMES:
            for lang in LANGUAGES:
                r=self.client.get('/casino/'+game+'?lang='+lang)
                self.assertEqual(r.status,200,r.text)
                self.assertIn(money(100,lang),r.text);self.assertNotIn('<script',r.text)
            r=self.play(game)
            for lang in LANGUAGES:
                result=self.client.get(r.location+'?lang='+lang)
                self.assertEqual(result.status,200,result.text)
                self.assertIn('game-result',result.text)
                self.assertIn(money(100,lang),result.text)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM all_rounds'),10)
        self.assertEqual(self.scalar('SELECT SUM(bonus) FROM all_rounds'),1000)

    def test_every_offered_choice_has_scripted_result(self):
        for game in GAMES:
            if game=='keno':continue
            for option in OPTIONS[game]:
                r=result_for(game,{'choice':option.value})
                self.assertTrue(r['scripted']);self.assertEqual(r['choice'],option.value)
            with self.assertRaises(ValueError):result_for(game,{'choice':'<svg>'})
        self.assertEqual(result_for('dice',{'choice':'10'})['values'],[5,5])
        self.assertEqual(result_for('blackjack',{'choice':'hit'})['total'],21)
        self.assertEqual(result_for('baccarat',{'choice':'tie'})['player'],9)

    def test_keno_requires_three_distinct_bounded_numbers(self):
        self.assertEqual(result_for('keno',{'n1':'12','n2':'8','n3':'1'})['values'],[1,8,12])
        for vals in ({'n1':'1','n2':'1','n3':'2'},{'n1':'13'},{'n2':'-1'},{'n3':'<svg>'}):
            with self.assertRaises(ValueError):result_for('keno',vals)
        self.signup();p=self.client.get('/casino/keno')
        r=self.client.submit(p,'/casino/keno',stake='100',n1='1',n2='1',n3='2')
        self.assertEqual(r.status,400);self.assertEqual(self.scalar('SELECT COUNT(*) FROM all_rounds'),0)

    def test_new_game_replay_same_result_not_second_bonus(self):
        self.signup();p=self.client.get('/casino/blackjack');f=dict(p.form('/casino/blackjack'),choice='hit',stake='1000')
        a=self.client.post('/casino/blackjack',f);b=self.client.post('/casino/blackjack',f)
        self.assertEqual(a.status,303);self.assertEqual(a.location,b.location)
        self.assertEqual(self.scalar('SELECT SUM(bonus) FROM extra_rounds'),100)
        self.assertEqual(json.loads(self.scalar('SELECT result_json FROM extra_rounds'))['choice'],'hit')

    def test_concurrent_new_game_posts_credit_once(self):
        self.signup();p=self.client.get('/casino/treasure');f=dict(p.form('/casino/treasure'),stake='500',choice='2')
        clients=[Client(self.app,cookies=self.client.cookies) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda c:c.post('/casino/treasure',f),clients))
        self.assertTrue(all(r.status==303 for r in results))
        self.assertEqual(len({r.location for r in results}),1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM extra_rounds'),1)

    def test_client_cannot_set_bonus_result_or_access_other_account(self):
        self.signup();r=self.play('bingo',bonus='99999999',result_json='{"scripted":false}')
        self.assertEqual(self.scalar('SELECT bonus FROM extra_rounds'),100)
        self.assertTrue(json.loads(self.scalar('SELECT result_json FROM extra_rounds'))['scripted'])
        other=Client(self.app,ip='203.0.113.99');self.signup(other,'other_reader')
        self.assertEqual(other.get(r.location).status,404)

    def test_pause_blocks_every_new_game_and_stale_form(self):
        self.signup();p=self.client.get('/casino/keno');stale=p.form('/casino/keno')
        profile=self.client.get('/profile');r=self.client.submit(profile,'/casino/pause',days='1')
        self.assertEqual(r.status,303)
        for game in EXTRA_GAMES:self.assertEqual(self.client.get('/casino/'+game).status,403)
        self.assertEqual(self.client.post('/casino/keno',dict(stale,stake='100')).status,403)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM all_rounds'),0)

    def test_new_games_require_login_and_safe_local_redirect(self):
        for game in EXTRA_GAMES:
            p='/casino/'+game
            self.assertEqual(self.client.get(p).status,303)
            self.assertEqual(safe_next(p),p)
        self.assertEqual(safe_next('//attacker.test/casino/plinko'),'/shop')
        self.assertEqual(self.client.get('/casino/not-a-game').status,404)

    def test_export_and_delete_cover_new_rounds(self):
        self.signup();self.play('plinko')
        p=self.client.get('/profile');r=self.client.submit(p,'/profile/export',current_password=PASSWORD)
        self.assertEqual(r.status,200);data=json.loads(r.text)
        self.assertEqual(len(data['rounds']),1);self.assertEqual(data['rounds'][0]['game'],'plinko')
        self.assertTrue(data['amounts_are_symbolic_units']);self.assertEqual(data['display_currency'],'BRL')
        self.assertNotIn(PASSWORD,r.text);self.assertNotIn('password_hash',r.text)
        r=self.client.submit(p,'/profile/delete',current_password=PASSWORD,confirm='yes')
        self.assertEqual(r.status,303);self.assertEqual(self.scalar('SELECT COUNT(*) FROM extra_rounds'),0)

    def test_schema_upgrade_is_additive_repeatable_and_legacy_compatible(self):
        old=Path(self.temp.name)/'old.sqlite3'
        schema=(ROOT/'tests/fixtures/schema-v1.sql').read_text()
        with closing(db.connect(old)) as c:
            c.executescript(schema)
            c.execute("INSERT INTO users(id,nickname,nickname_key,password_hash,recovery_hash,adult_confirmed,created_at) VALUES(1,'old_user','old_user','original-hash','original-recovery',1,1)")
            c.execute("INSERT INTO rounds(id,user_id,game,request_key,stake,bonus,created_at) VALUES('original',1,'cards','key',100,100,1)")
        db.initialize(old);db.initialize(old)
        with closing(db.connect(old)) as c:
            self.assertEqual(c.execute('SELECT password_hash FROM users').fetchone()[0],'original-hash')
            self.assertEqual(c.execute('SELECT result_json FROM rounds').fetchone()[0],'{}')
            c.execute("INSERT INTO extra_rounds(id,user_id,game,request_key,stake,bonus,created_at) VALUES('new',1,'keno','key2',100,100,2)")
            # v1's startup accepts core version 1 and replays its original DDL.
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],1)
            c.executescript(schema)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM rounds').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM all_rounds').fetchone()[0],2)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_migration_failure_rolls_back_partial_ddl(self):
        old=Path(self.temp.name)/'old.sqlite3'
        with closing(db.connect(old)) as c:c.executescript((ROOT/'tests/fixtures/schema-v1.sql').read_text())
        fake=Path(self.temp.name)/'broken';(fake/'data').mkdir(parents=True)
        (fake/'data/schema.sql').write_text('CREATE TABLE partial(x); THIS IS INVALID;')
        with patch('app.db.ROOT',fake):
            with self.assertRaises(sqlite3.Error):db.initialize(old)
        with closing(db.connect(old)) as c:
            self.assertNotIn('result_json',[x[1] for x in c.execute('PRAGMA table_info(rounds)')])
            self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchone())

    def test_default_black_background_and_cache_busting(self):
        css=(ROOT/'app/static/style.css').read_text()
        self.assertIn('--bg:#000000',css.replace(' ',''))
        r=self.client.get('/shop')
        self.assertIn('v=1.2.0',r.text)
        self.assertIn('content="#000000"',r.text)

    def test_language_switch_keeps_receipt_and_round_paths(self):
        for kind in ('receipt','round'):
            p='/'+kind+'/'+'a'*32
            self.assertEqual(safe_next(p),p)
            reply=self.client.get('/language?lang=en&next='+p)
            self.assertEqual(reply.location,p)

    def test_origin_port_zero_never_equals_default(self):
        self.assertFalse(security.same_origin('http://localhost:0','http://localhost'))
        self.assertFalse(security.same_origin('https://localhost:0','https://localhost'))
