from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlencode
import json
import re
import sqlite3
import unittest
from app import catalog,db,security
from app.config import Config,LANGUAGES
from app.i18n import S,text
from app.web import App,safe_next
from tests.helpers import Client

PASSWORD='CyanNebula!River-2026'
OTHER_PASSWORD='VelvetOrbit!Ocean-2042'

class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'dopamine.sqlite3';db.initialize(self.path)
        self.config=Config(secret='unit-test-secret-not-a-deploy-key-'*3,database=self.path,site_url='http://localhost',
            allowed_hosts=('localhost',),secure=False,require_local_photos=False,testing=True)
        self.app=App(self.config);self.client=Client(self.app)
    def count(self,table):
        with closing(db.connect(self.path)) as conn:return conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def scalar(self,sql,params=()):
        with closing(db.connect(self.path)) as conn:return conn.execute(sql,params).fetchone()[0]
    def signup(self,client=None,nickname='berkeley_test'):
        client=client or self.client
        page=client.get('/signup')
        response=client.submit(page,'/signup',nickname=nickname,password=PASSWORD,adult='yes')
        self.assertEqual(response.status,200,response.text)
        recovery=re.search(r'id="recovery-code"><code>([^<]+)<',response.text)
        self.assertIsNotNone(recovery,response.text)
        return recovery.group(1)
    def login(self,client=None,nickname='berkeley_test',password=PASSWORD):
        client=client or self.client
        response=client.submit(client.get('/login'),'/login',nickname=nickname,password=password)
        self.assertEqual(response.status,303,response.text)
        return response
    def buy(self,client=None,pid='real-porsche-911',quantity='1'):
        client=client or self.client
        page=client.get('/product/'+pid)
        response=client.submit(page,'/buy/'+pid,quantity=quantity)
        self.assertEqual(response.status,303,response.text)
        return response

    def test_catalog_and_every_translation_complete(self):
        self.assertEqual(catalog.validate(),len(catalog.PRODUCTS))
        self.assertEqual(len(catalog.CATEGORIES),len(catalog.DATA['categories']))
        self.assertEqual(len(catalog.PHOTOS),len(catalog.PRODUCTS) if catalog.PHOTOS else 0)
        for key,entry in S.items():
            self.assertEqual(len(entry),4,key)
            self.assertTrue(all(isinstance(v,str) and v.strip() for v in entry),key)
        for category in catalog.CATEGORIES.values():self.assertEqual(set(category['label']),set(LANGUAGES))
        for lang in LANGUAGES:
            self.assertEqual(len(catalog.select(lang)),len(catalog.PRODUCTS))
            for item in catalog.select(lang):self.assertTrue(item['image'].startswith('/static/photos/'))

    def test_public_pages_in_four_languages_no_javascript(self):
        paths=('/shop','/casino','/science','/about','/privacy','/login','/signup','/recover','/product/real-porsche-911')
        for lang in LANGUAGES:
            for path in paths:
                with self.subTest(lang=lang,path=path):
                    response=self.client.get(path+'?lang='+lang)
                    self.assertEqual(response.status,200,response.text)
                    self.assertNotIn('<script',response.text.lower())
                    self.assertNotRegex(response.text,r'\son[a-z]+\s*=')
                    self.assertIn("script-src 'none'",response.header('Content-Security-Policy'))
                    self.assertIn('no-store',response.header('Cache-Control'))
                    self.assertIn('∞',response.text)
        self.assertEqual(self.client.get('/shop').status,200)

    def test_every_product_page_all_languages(self):
        for lang in LANGUAGES:
            for pid in catalog.PRODUCTS:
                response=self.client.get('/product/'+pid+'?lang='+lang)
                self.assertEqual(response.status,200,(lang,pid,response.text))
                self.assertIn(__import__('markupsafe').escape(catalog.PRODUCTS[pid]['name']),response.text)

    def test_public_reading_does_not_create_sessions(self):
        for path in ('/shop','/casino','/about','/science','/privacy'):
            self.assertIsNone(self.client.get(path).header('Set-Cookie'))
        self.assertEqual(self.count('sessions'),0)

    def test_signup_hashes_and_recovery_only_once(self):
        recovery=self.signup()
        with closing(db.connect(self.path)) as conn:user=dict(conn.execute('SELECT * FROM users').fetchone())
        self.assertTrue(user['password_hash'].startswith('$argon2id$'))
        self.assertNotIn(PASSWORD,user['password_hash'])
        self.assertNotEqual(recovery,user['recovery_hash'])
        self.assertTrue(security.verify(user['password_hash'],PASSWORD))
        self.assertNotIn(recovery,self.client.get('/profile').text)
        self.assertEqual(self.client.get('/profile').status,200)

    def test_adult_declaration_and_strong_password_required(self):
        page=self.client.get('/signup')
        self.assertEqual(self.client.submit(page,'/signup',nickname='valid_user',password=PASSWORD).status,400)
        self.assertEqual(self.client.submit(page,'/signup',nickname='valid_user',password='short',adult='yes').status,400)
        self.assertEqual(self.count('users'),0)

    def test_unicode_nickname_and_normalized_uniqueness(self):
        self.signup(nickname='星空ひかり')
        other=Client(self.app,ip='203.0.113.41');self.signup(other,'CyanName')
        third=Client(self.app,ip='203.0.113.42')
        response=third.submit(third.get('/signup'),'/signup',nickname='ＣｙａｎＮａｍｅ',password=PASSWORD,adult='yes')
        self.assertEqual(response.status,409)
        self.assertEqual(self.count('users'),2)

    def test_login_rotates_session_logout_is_post_only(self):
        self.signup();old=self.client.cookies[self.config.cookie_name]
        self.assertEqual(self.client.get('/logout').status,405)
        response=self.client.submit(self.client.get('/profile'),'/logout')
        self.assertEqual(response.status,303)
        self.assertNotEqual(old,self.client.cookies[self.config.cookie_name])
        stale=Client(self.app,cookies={self.config.cookie_name:old})
        self.assertEqual(stale.get('/profile').status,303)
        anonymous=self.client.cookies[self.config.cookie_name]
        self.login();self.assertNotEqual(anonymous,self.client.cookies[self.config.cookie_name])

    def test_csrf_missing_wrong_unicode_and_foreign_origin_rejected(self):
        self.signup();page=self.client.get('/product/real-porsche-911');form=page.form('/buy/real-porsche-911')
        for csrf in ('','invalid','日本語','a'*100):
            self.assertEqual(self.client.post('/buy/real-porsche-911',dict(form,csrf=csrf,quantity='1')).status,403)
        self.assertEqual(self.client.post('/buy/real-porsche-911',dict(form,quantity='1'),headers={'HTTP_ORIGIN':'https://evil.invalid'}).status,403)
        self.assertEqual(self.count('purchases'),0)

    def test_originless_valid_csrf_works(self):
        self.signup();form=self.client.get('/product/real-porsche-911').form('/buy/real-porsche-911')
        self.assertEqual(self.client.post('/buy/real-porsche-911',dict(form,quantity='1'),headers={'HTTP_ORIGIN':None}).status,303)

    def test_malformed_or_cross_action_key_rejected(self):
        self.signup();form=self.client.get('/product/real-porsche-911').form('/buy/real-porsche-911')
        for key in ('日本語','1.a.語','0.'+'a'*24+'.'+'b'*64):
            self.assertEqual(self.client.post('/buy/real-porsche-911',dict(form,action_key=key,quantity='1')).status,403)
        self.assertEqual(self.client.post('/buy/real-nikon-d850',dict(form,quantity='1')).status,403)
        self.assertEqual(self.count('purchases'),0)

    def test_buy_uses_server_price_and_infinite_balance(self):
        self.signup();form=self.client.get('/product/real-fallingwater').form('/buy/real-fallingwater')
        result=self.client.post('/buy/real-fallingwater',dict(form,quantity='99',credits='1',price='-99999',balance='0'))
        self.assertEqual(result.status,303)
        self.assertEqual(self.scalar('SELECT unit_credits FROM purchase_items'),catalog.PRODUCTS['real-fallingwater']['credits'])
        self.assertEqual(self.scalar('SELECT quantity FROM purchase_items'),99)
        self.assertIn('∞',self.client.get(result.location).text)
        self.buy(pid='real-fallingwater',quantity='99')
        self.assertEqual(self.count('purchases'),2)

    def test_quantity_validation_and_idempotency(self):
        self.signup();form=self.client.get('/product/real-porsche-911').form('/buy/real-porsche-911')
        for quantity in ('0','100','-1','1.2','1e9','NaN','9'*20):
            self.assertEqual(self.client.post('/buy/real-porsche-911',dict(form,quantity=quantity)).status,400)
        first=self.client.post('/buy/real-porsche-911',dict(form,quantity='2'))
        second=self.client.post('/buy/real-porsche-911',dict(form,quantity='2'))
        self.assertEqual(first.location,second.location)
        self.assertEqual(self.count('purchases'),1)

    def test_add_entire_catalog_checkout_and_replay(self):
        self.signup();page=self.client.get('/shop')
        response=self.client.submit(page,'/catalog/all')
        self.assertEqual(response.status,303)
        self.assertEqual(self.count('cart'),len(catalog.PRODUCTS))
        form=self.client.get('/cart').form('/checkout')
        first=self.client.post('/checkout',form);second=self.client.post('/checkout',form)
        self.assertEqual(first.status,303)
        self.assertEqual(first.location,second.location)
        self.assertEqual(self.count('cart'),0)
        self.assertEqual(self.count('purchase_items'),len(catalog.PRODUCTS))
        self.assertEqual(self.count('purchases'),1)
        self.assertEqual(self.client.get(first.location).status,200)

    def test_concurrent_checkout_creates_one_order(self):
        self.signup();page=self.client.get('/product/real-porsche-911')
        self.client.post('/bag/real-porsche-911',dict(page.form('/buy/real-porsche-911'),quantity='2'))
        form=self.client.get('/cart').form('/checkout')
        cookies=dict(self.client.cookies)
        def request(_):return Client(self.app,cookies=cookies).post('/checkout',form)
        with ThreadPoolExecutor(max_workers=4) as pool:responses=list(pool.map(request,range(4)))
        self.assertTrue(all(r.status==303 for r in responses))
        self.assertEqual(len({r.location for r in responses}),1)
        self.assertEqual(self.count('purchases'),1)
        self.assertEqual(self.count('cart'),0)

    def test_favorites_and_cart_are_account_bound(self):
        self.signup();page=self.client.get('/product/real-porsche-911')
        self.assertEqual(self.client.submit(page,'/favorite/real-porsche-911').status,303)
        self.assertEqual(self.count('favorites'),1)
        self.client.post('/bag/real-porsche-911',dict(page.form('/buy/real-porsche-911'),quantity='3'))
        other=Client(self.app,ip='203.0.113.51');self.signup(other,'other_user')
        self.assertIn('0',other.get('/cart').text)
        other.submit(other.get('/profile'),'/profile',display_name='',country='',bio='',language='pt-br')
        self.assertEqual(self.scalar('SELECT quantity FROM cart'),3)

    def test_receipts_and_rounds_cannot_be_read_by_other_account(self):
        self.signup();order=self.buy()
        play=self.client.submit(self.client.get('/casino/prism'),'/casino/prism',stake='100')
        other=Client(self.app,ip='203.0.113.50');self.signup(other,'other_user')
        self.assertEqual(other.get(order.location).status,404)
        self.assertEqual(other.get(play.location).status,404)
        self.assertEqual(self.client.get(order.location).status,200)

    def test_every_game_and_card_always_returns_fixed_bonus(self):
        self.signup()
        for game in ('prism','orbit','cards'):
            for choice,stake in ((1,100),(2,500),(3,1000)):
                page=self.client.get('/casino/'+game)
                response=self.client.submit(page,'/casino/'+game,stake=str(stake),card=str(choice))
                self.assertEqual(response.status,303,response.text)
                self.assertEqual(self.client.get(response.location).status,200)
        self.assertEqual(self.count('rounds'),9)
        self.assertEqual(self.scalar('SELECT SUM(bonus) FROM rounds'),900)
        self.assertEqual(self.scalar('SELECT MIN(bonus) FROM rounds'),100)

    def test_casino_replay_and_bad_stakes(self):
        self.signup();form=self.client.get('/casino/cards').form('/casino/cards')
        for stake in ('101','0','500.0','-100','2000'):
            self.assertEqual(self.client.post('/casino/cards',dict(form,stake=stake)).status,400)
        one=self.client.post('/casino/cards',dict(form,stake='500',card='2'))
        two=self.client.post('/casino/cards',dict(form,stake='500',card='2'))
        self.assertEqual(one.location,two.location)
        self.assertEqual(self.count('rounds'),1)
        self.assertEqual(self.scalar('SELECT stake FROM rounds'),500)

    def test_self_exclusion_cannot_be_shortened_and_blocks_old_form(self):
        self.signup();oldform=self.client.get('/casino/prism').form('/casino/prism')
        page=self.client.get('/profile')
        self.client.submit(page,'/casino/pause',days='7')
        until=self.scalar('SELECT excluded_until FROM users')
        self.client.submit(page,'/casino/pause',days='1')
        self.assertEqual(until,self.scalar('SELECT excluded_until FROM users'))
        self.assertEqual(self.client.get('/casino/prism').status,403)
        self.assertEqual(self.client.post('/casino/prism',dict(oldform,stake='100')).status,403)
        self.assertEqual(self.count('rounds'),0)
        self.buy()

    def test_profile_escaping_language_and_hide_casino(self):
        self.signup();payload='<script>alert(1)</script>'
        response=self.client.submit(self.client.get('/profile'),'/profile',display_name=payload,country='',bio=payload,
                                    language='ja',reduced_motion='yes',casino_hidden='yes')
        self.assertEqual(response.status,303)
        page=self.client.get('/profile')
        self.assertIn('&lt;script&gt;',page.text)
        self.assertNotIn(payload,page.text)
        self.assertIn('lang="ja"',page.text)
        self.assertIn('class="reduced-motion"',page.text)
        self.assertEqual(self.client.get('/casino/cards').status,403)
        self.assertNotIn('href="/casino"',page.text)

    def test_password_change_revokes_other_sessions(self):
        self.signup();other=Client(self.app,ip='203.0.113.41');self.login(other)
        response=self.client.submit(self.client.get('/profile'),'/profile/password',current_password=PASSWORD,new_password=OTHER_PASSWORD)
        self.assertEqual(response.status,303)
        self.assertEqual(other.get('/profile').status,303)
        self.assertEqual(self.client.get('/profile').status,200)
        self.assertFalse(security.verify(self.scalar('SELECT password_hash FROM users'),PASSWORD))

    def test_recovery_rotates_code_and_revokes_sessions(self):
        recovery=self.signup();other=Client(self.app,ip='203.0.113.42')
        response=other.submit(other.get('/recover'),'/recover',nickname='berkeley_test',recovery_code=recovery,password=OTHER_PASSWORD)
        self.assertEqual(response.status,200,response.text)
        fresh=re.search(r'id="recovery-code"><code>([^<]+)<',response.text).group(1)
        self.assertNotEqual(recovery,fresh)
        self.assertEqual(self.client.get('/profile').status,303)
        third=Client(self.app,ip='203.0.113.43')
        old=third.submit(third.get('/recover'),'/recover',nickname='berkeley_test',recovery_code=recovery,password=PASSWORD)
        self.assertEqual(old.status,400)
        newest=third.submit(third.get('/recover'),'/recover',nickname='berkeley_test',recovery_code=fresh,password=PASSWORD)
        self.assertEqual(newest.status,200)

    def test_export_reauth_and_no_credentials(self):
        recovery=self.signup();self.buy()
        page=self.client.get('/profile')
        self.assertEqual(self.client.submit(page,'/profile/export',current_password='wrong').status,400)
        response=self.client.submit(page,'/profile/export',current_password=PASSWORD)
        self.assertEqual(response.status,200)
        data=json.loads(response.body)
        self.assertTrue(data['fictional'])
        self.assertEqual(len(data['purchases']),1)
        for secret in ('password_hash','recovery_hash','token_hash',recovery,PASSWORD):self.assertNotIn(secret,response.text)
        self.assertEqual(response.header('Content-Disposition'),'attachment; filename="dopamine-my-data.json"')

    def test_account_delete_cascades(self):
        self.signup();self.buy();self.client.submit(self.client.get('/casino/prism'),'/casino/prism',stake='100')
        page=self.client.get('/profile')
        self.assertEqual(self.client.submit(page,'/profile/delete',current_password=PASSWORD).status,400)
        response=self.client.submit(page,'/profile/delete',current_password=PASSWORD,confirm='yes')
        self.assertEqual(response.status,303)
        for table in ('users','sessions','purchases','purchase_items','rounds','cart','favorites'):self.assertEqual(self.count(table),0,table)

    def test_rate_limit_shared_and_atomic(self):
        def increment(_):
            with closing(db.connect(self.path)) as conn:
                return security.allowed_rate(conn,self.config,'test','same-identity',5,900)
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(increment,range(20)))
        self.assertEqual(sum(results),5)
        self.assertEqual(self.scalar('SELECT count FROM rate_limits'),20)

    def test_auth_rate_limit(self):
        page=self.client.get('/login');form=page.form('/login')
        for i in range(11):response=self.client.post('/login',dict(form,nickname='nonexistent',password='x'*129))
        self.assertEqual(response.status,429)
        self.assertTrue(response.header('Retry-After'))

    def test_session_expiry_and_cleanup(self):
        self.signup()
        with closing(db.connect(self.path)) as conn:
            conn.execute('UPDATE sessions SET touched_at=?',(security.now()-4000,))
            conn.execute("INSERT INTO rate_limits VALUES('expired',1,1)")
            removed=db.cleanup(conn,security.now())
        self.assertEqual(removed['sessions_removed'],1)
        self.assertEqual(self.client.get('/profile').status,303)

    def test_host_methods_static_paths_and_body_limits(self):
        self.assertEqual(self.client.get('/shop',headers={'HTTP_HOST':'evil.invalid'}).status,400)
        self.assertEqual(self.client.get('/does-not-exist').status,404)
        self.assertEqual(self.client.get('/static/../config.py').status,404)
        self.assertEqual(self.client.request('/shop','PUT').status,405)
        self.assertEqual(self.client.post('/robots.txt').status,405)
        self.assertEqual(self.client.post('/login',raw=b'x'*17000).status,413)
        self.assertEqual(self.client.post('/login',raw=b'{}',content_type='application/json').status,415)
        self.assertEqual(self.client.post('/login',raw=b'csrf=a&csrf=b').status,400)
        css=self.client.get('/static/style.css')
        self.assertEqual(css.status,200)
        self.assertEqual(css.header('Content-Type'),'text/css; charset=utf-8')
        self.assertIsNone(css.header('Set-Cookie'))
        head=self.client.request('/shop','HEAD');self.assertEqual(head.status,200);self.assertEqual(head.body,b'')

    def test_https_proxy_trust_and_cookie_attributes(self):
        config=replace(self.config,secure=True,site_url='https://localhost',proxy_cidrs=('172.30.0.2/32',))
        app=App(config)
        untrusted=Client(app,ip='198.51.100.99')
        response=untrusted.get('/shop',headers={'HTTP_X_FORWARDED_PROTO':'https'})
        self.assertEqual(response.status,308)
        proxy=Client(app,ip='172.30.0.2')
        response=proxy.get('/signup',headers={'HTTP_X_FORWARDED_PROTO':'https','HTTP_X_REAL_IP':'203.0.113.3'})
        self.assertEqual(response.status,200,response.text)
        cookie=response.header('Set-Cookie')
        for required in ('__Host-dopamine=','HttpOnly','Secure','SameSite=Lax','Path=/'):self.assertIn(required,cookie)
        self.assertNotIn('Domain=',cookie)
        self.assertIn('max-age=31536000',response.header('Strict-Transport-Security'))
        self.assertEqual(security.client_ip({'REMOTE_ADDR':'198.51.100.1','HTTP_X_REAL_IP':'1.2.3.4'},config),'198.51.100.1')
        self.assertEqual(security.client_ip({'REMOTE_ADDR':'172.30.0.2','HTTP_X_REAL_IP':'1.2.3.4'},config),'1.2.3.4')

    def test_safe_redirect_targets_and_language_switch(self):
        for value in ('https://evil.invalid','//evil.invalid/shop','/\\evil.invalid','http://[broken','/shop%0d%0aX:Evil'):
            self.assertEqual(safe_next(value),'/shop')
        response=self.client.get('/language?'+urlencode({'lang':'zh','next':'/casino'}))
        self.assertEqual(response.location,'/casino')
        self.assertIn('lang="zh-Hans"',self.client.get('/shop').text)

    def test_production_requires_downloaded_photos(self):
        # The source archive deliberately has references, not fabricated photo binaries.
        with patch('app.real_photos.verify_photos',side_effect=RuntimeError('Photos missing')):
            with self.assertRaises(RuntimeError):App(replace(self.config,require_local_photos=True))

    def test_login_cannot_resurrect_session_after_concurrent_password_reset(self):
        self.signup()
        self.client.submit(self.client.get('/profile'),'/logout')
        page=self.client.get('/login')
        replacement=security.PH.hash(OTHER_PASSWORD)
        original=security.verify
        def verify_and_reset(stored,password):
            result=original(stored,password)
            if result:
                with closing(db.connect(self.path)) as conn:
                    conn.execute('UPDATE users SET password_hash=?',(replacement,))
                    conn.execute('DELETE FROM sessions WHERE user_id IS NOT NULL')
            return result
        with patch('app.security.verify',side_effect=verify_and_reset):
            response=self.client.submit(page,'/login',nickname='berkeley_test',password=PASSWORD)
        self.assertEqual(response.status,400)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sessions WHERE user_id IS NOT NULL'),0)

    def test_account_pages_in_all_languages(self):
        self.signup();self.buy()
        for lang in LANGUAGES:
            for path in ('/profile','/collection','/cart','/casino/prism','/casino/orbit','/casino/cards'):
                response=self.client.get(path+'?lang='+lang)
                self.assertEqual(response.status,200,(lang,path,response.text))
                self.assertNotIn('<script',response.text)
