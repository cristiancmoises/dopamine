"""Practice-table, import-integrity and browser-script regression contracts.

All generated image fixtures below are synthetic TEST DATA, never catalog photos.
"""
from contextlib import closing
from dataclasses import replace
from io import BytesIO
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import json
import random
import unittest
from PIL import Image
from app import tables, real_photos as photos, catalog, db, security
from app.config import Config,ROOT,LANGUAGES
from app.web import App
from tests.helpers import Client

class Sequence:
    def __init__(self,*values):self.values=iter(values)
    def randrange(self,*_):return next(self.values)
    def randint(self,*_):return next(self.values)
    def sample(self,*_):return [1,2,3,4,5,6,7,8,9,10]

def card(rank,suit='♠'):return {'rank':str(rank),'suit':suit}
def shoe(*ranks):return [card(x) for x in reversed(ranks)]

class TableEngineTests(unittest.TestCase):
    def test_roulette_all_pockets_and_edge(self):
        self.assertEqual(set(tables.WHEEL),set(range(37)))
        returns=[]
        for n in range(37):
            s=tables.start('roulette',100,{'choice':'red'},Sequence(n))
            self.assertEqual(s['pocket'],n);self.assertEqual(s['wheel_index'],tables.WHEEL.index(n))
            self.assertEqual(s['table_return'],200 if n in tables.RED else 0)
            self.assertEqual(s['demo_bonus'],100);self.assertEqual(s['demo_refund'],100)
            returns.append(s['table_return'])
        self.assertEqual(sum(returns),3600)
        self.assertEqual(tables.start('roulette',100,{'choice':'number','number':'0'},Sequence(0))['table_return'],3600)
    def test_blackjack_aces_soft_seventeen(self):
        self.assertEqual(tables.hand_value([card('A'),card('6')]),(17,True))
        self.assertEqual(tables.hand_value([card('A'),card('A'),card('9')]),(21,True))
        self.assertEqual(tables.hand_value([card('A'),card('A'),card('9'),card('9')]),(20,False))
        with patch.object(tables,'deck',return_value=shoe(10,'A',8,6,2)):
            s=tables.start('blackjack',100,{})
        result=tables.move(s,'stand');self.assertEqual(result['table_return'],200)
        self.assertEqual(len(result['dealer']),2)
    def test_blackjack_naturals_and_push(self):
        for ranks,expected in [(['A',9,'K',7],250),(['A','A','K','K'],100),([9,'A',7,'K'],0)]:
            with patch.object(tables,'deck',return_value=shoe(*ranks)):s=tables.start('blackjack',100,{})
            self.assertTrue(s['completed']);self.assertEqual(s['table_return'],expected)
    def test_blackjack_hit_double_bust_and_illegal_move(self):
        with patch.object(tables,'deck',return_value=shoe(5,10,6,7,'K')):s=tables.start('blackjack',100,{})
        r=tables.move(s,'double');self.assertEqual(r['stake'],200);self.assertEqual(r['table_return'],400)
        self.assertEqual(s['stake'],100) # no accidental in-place mutation
        with self.assertRaises(tables.InvalidMove):tables.move(r,'hit')
        with patch.object(tables,'deck',return_value=shoe(10,10,9,7,5)):s=tables.start('blackjack',100,{})
        self.assertEqual(tables.move(s,'hit')['outcome'],'loss')
    def test_blackjack_private_deck_and_hole_never_public(self):
        with patch.object(tables,'deck',return_value=shoe(6,10,5,7,2)):s=tables.start('blackjack',100,{})
        p=tables.public(s);self.assertNotIn('deck',p);self.assertEqual(p['dealer'][1],{'rank':'?','suit':''})
        self.assertEqual(p['dealer_total'],'?');self.assertEqual(s['dealer'][1]['rank'],'7')
    def test_baccarat_naturals_payout_commission_and_tie(self):
        for ranks,choice,winner,expected in [([4,3,5,4],'player','player',200),([3,4,4,5],'banker','banker',195),([4,5,5,4],'tie','tie',900),([4,5,5,4],'player','tie',100)]:
            with patch.object(tables,'deck',return_value=shoe(*ranks)):s=tables.start('baccarat',100,{'choice':choice})
            self.assertEqual(s['winner'],winner);self.assertEqual(s['table_return'],expected)
            self.assertEqual(len(s['player']),2);self.assertEqual(len(s['banker']),2)
    def test_baccarat_third_card_rules_exhaustive(self):
        # Player starts at 0, draws each possible third-card value. Banker 0..7.
        for bank in range(8):
            for third in range(10):
                with patch.object(tables,'deck',return_value=shoe('K','K','K',bank or 'K',third or 'K',1)):
                    s=tables.start('baccarat',100,{'choice':'banker'})
                expected=bank<=2 or bank==3 and third!=8 or bank==4 and third in range(2,8) or bank==5 and third in range(4,8) or bank==6 and third in (6,7)
                self.assertEqual(len(s['banker']),3 if expected else 2,(bank,third))
    def test_slots_exhaustive_paytable(self):
        total=0;outcomes=set()
        for reel in product(range(6),repeat=3):
            s=tables.start('slots',100,{},Sequence(*reel));total+=s['table_return'];outcomes.add(s['outcome'])
        self.assertEqual(total,20500);self.assertEqual(outcomes,{'win','loss','push'})
    def test_dice_exhaustive(self):
        for choice,mult in [('under',2),('over',2),('seven',5)]:
            total=0
            for a,b in product(range(1,7),repeat=2):total+=tables.start('dice',100,{'choice':choice},Sequence(a,b))['table_return']
            self.assertEqual(total,3000)
    def test_keno_validation_and_no_repeated_draws(self):
        form={'pick'+str(i):str(i) for i in range(1,6)}
        s=tables.start('keno',100,form,Sequence());self.assertEqual(s['table_return'],5000)
        self.assertEqual(len(set(s['drawn'])),10)
        for bad in ('1','0','41','nan','2.0'):
            with self.assertRaises(tables.InvalidMove):tables.start('keno',100,dict(form,pick5=bad),Sequence())
    def test_plinko_paths_correspond_to_bin_and_payout(self):
        for steps in product(range(2),repeat=8):
            s=tables.start('plinko',100,{},Sequence(*steps))
            self.assertEqual(s['slot'],sum(steps));self.assertEqual(s['table_return'],int(100*tables.PLINKO_MULTIPLIERS[sum(steps)]))
    def test_invalid_stakes_and_choices(self):
        for stake in (-100,0,True,100.0,999,100000):
            with self.assertRaises(tables.InvalidMove):tables.start('slots',stake,{})
        for game in ('roulette','baccarat','dice'):
            with self.assertRaises(tables.InvalidMove):tables.start(game,100,{'choice':'<script>'})
    def test_random_results_are_not_forced_wins(self):
        results=[tables.start('roulette',100,{'choice':'red'},random.Random(n))['outcome'] for n in range(100)]
        self.assertIn('loss',results);self.assertIn('win',results)

class LiveWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db.sqlite3';db.initialize(self.path)
        self.cfg=Config(secret='test-only-never-deploy-'*4,database=self.path,site_url='http://localhost',allowed_hosts=('localhost',),secure=False,require_local_photos=False,testing=True)
        self.app=App(self.cfg);self.client=Client(self.app)
        r=self.client.submit(self.client.get('/signup'),'/signup',nickname='practice_test',password='Private-Test!Password-2026',adult='yes')
        self.assertEqual(r.status,200)
    def count(self):
        with closing(db.connect(self.path)) as c:return c.execute('SELECT COUNT(*) FROM interactive_rounds').fetchone()[0]
    def start(self,game,client=None,**overrides):
        c=client or self.client;url='/play/'+game
        page=c.get(url+'?new=1');self.assertEqual(page.status,200,page.text)
        f=page.form(url);f.update(stake='100',choice={'roulette':'red','dice':'over','baccarat':'player'}.get(game,''),**{'pick'+str(i):str(i) for i in range(1,6)})
        f.update(overrides)
        response=c.post(url,f);self.assertEqual(response.status,303,response.text)
        return response,f
    def test_every_table_localized_and_nonjs_form(self):
        for game in tables.TABLES:
            for lang in LANGUAGES:
                p=self.client.get('/play/'+game+'?new=1&lang='+lang)
                self.assertEqual(p.status,200,p.text);self.assertIn('data-live-form',p.text)
                self.assertIn('integrity="sha384-',p.text);self.assertIn("script-src 'self'",p.header('Content-Security-Policy'))
            with closing(db.connect(self.path)) as c:c.execute('DELETE FROM rate_limits')
            res,_=self.start(game)
            for lang in LANGUAGES:self.assertEqual(self.client.get(res.location+'?lang='+lang).status,200)
    def test_replayed_start_does_not_generate_another_result(self):
        r,f=self.start('roulette')
        again=self.client.post('/play/roulette',dict(f,number='36',table_return='1000000'))
        self.assertEqual(r.location,again.location);self.assertEqual(self.count(),1)
        self.assertEqual(self.client.get(r.location).text,self.client.get(r.location).text) # completed forms have no action nonce
    def test_json_enhancement_returns_only_public_fragment(self):
        p=self.client.get('/play/blackjack?new=1');f=dict(p.form('/play/blackjack'),stake='100')
        with patch.object(tables,'deck',return_value=shoe(6,10,5,7,2)):
            r=self.client.post('/play/blackjack',f,headers={'HTTP_ACCEPT':'application/json'})
        self.assertEqual(r.status,200,r.text);value=json.loads(r.body)
        self.assertIn('id="practice-table"',value['html']);self.assertNotIn('"deck"',r.text)
        self.assertIn('card-back',value['html']);self.assertNotIn('<script',value['html'])
    def test_blackjack_revision_replay_and_concurrent_move(self):
        with patch.object(tables,'deck',return_value=shoe(4,10,5,7,2,3,4)):
            res,_=self.start('blackjack')
        page=self.client.get(res.location);form=page.form(res.location)
        r=self.client.post(res.location,dict(form,move='hit'));self.assertEqual(r.status,303)
        self.assertEqual(self.client.post(res.location,dict(form,move='hit')).status,303)
        # A second tab has a different request nonce but the old revision.
        stale=dict(form,action_key=page.form(res.location)['action_key'])
        page2=self.client.get(res.location);fresh=page2.form(res.location)
        stale['action_key']=fresh['action_key'];self.assertEqual(self.client.post(res.location,dict(stale,move='hit')).status,409)
        with closing(db.connect(self.path)) as c:
            row=c.execute('SELECT * FROM interactive_rounds').fetchone()
            self.assertEqual(row['revision'],1);self.assertEqual(len(json.loads(row['state_json'])['player']),3)
        def submit(_):return Client(self.app,cookies=self.client.cookies).post(res.location,dict(fresh,move='stand')).status
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(list(pool.map(submit,range(2))),[303,303])
        with closing(db.connect(self.path)) as c:self.assertEqual(c.execute('SELECT revision FROM interactive_rounds').fetchone()[0],2)
    def test_round_ownership_origin_and_result_input(self):
        res,form=self.start('roulette')
        p=self.client.get('/play/dice?new=1');f=dict(p.form('/play/dice'),stake='100',choice='over')
        self.assertEqual(self.client.post('/play/dice',f,headers={'HTTP_ORIGIN':'https://evil.invalid'}).status,403)
        self.assertEqual(self.client.post('/play/dice',dict(f,csrf='invalid')).status,403)
        anon=Client(self.app,ip='203.0.113.42');self.assertEqual(anon.get(res.location).status,303)
        x=anon.submit(anon.get('/signup'),'/signup',nickname='other_practice',password='Private-Test!Password-2026',adult='yes');self.assertEqual(x.status,200)
        self.assertEqual(anon.get(res.location).status,404)
        self.assertEqual(self.count(),1)
    def test_pause_blocks_new_and_existing_actions(self):
        with patch.object(tables,'deck',return_value=shoe(4,10,5,7,2)):res,_=self.start('blackjack')
        f=self.client.get(res.location).form(res.location)
        p=self.client.get('/profile');self.client.post('/casino/pause',dict(p.form('/profile'),days='1'))
        self.assertEqual(self.client.post(res.location,dict(f,move='hit')).status,403)
        self.assertEqual(self.client.get('/play/roulette').status,403)
    def test_active_hand_survives_refresh_and_new_start(self):
        with patch.object(tables,'deck',return_value=shoe(4,10,5,7,2)):res,_=self.start('blackjack')
        self.assertIn(res.location,self.client.get('/play/blackjack?new=1').text)
        self.assertEqual(self.count(),1)
        self.assertIn(res.location,self.client.get('/collection').text)
    def test_rate_limits_starts(self):
        for _ in range(12):self.start('slots')
        p=self.client.get('/play/slots?new=1')
        self.assertEqual(self.client.post('/play/slots',dict(p.form('/play/slots'),stake='100')).status,429)
    def test_deletion_cascades_interactive_rounds(self):
        self.start('slots');page=self.client.get('/profile')
        r=self.client.submit(page,'/profile/delete',current_password='Private-Test!Password-2026',confirm='yes')
        self.assertEqual(r.status,303);self.assertEqual(self.count(),0)
    def test_old_receipt_is_not_relabeled_as_a_real_model(self):
        with closing(db.connect(self.path)) as c:
            c.execute("INSERT INTO purchases(id,user_id,request_key,created_at) VALUES(?,1,'historic',1)",('a'*32,))
            c.execute("INSERT INTO purchase_items(purchase_id,product_id,quantity,unit_credits) VALUES(?,'cars-1-1',2,12345)",('a'*32,))
        response=self.client.get('/receipt/'+'a'*32)
        self.assertEqual(response.status,200);self.assertIn(catalog.LEGACY['cars-1-1']['name'],response.text)
        self.assertIn('24.690',response.text);self.assertNotIn('Porsche 911',response.text)
    def test_javascript_is_local_licensed_and_scoped(self):
        js=self.client.get('/static/tables.js');self.assertEqual(js.status,200)
        self.assertIn('@license magnet:',js.text);self.assertIn('@license-end',js.text)
        for bad in ('eval(', 'new Function(', '.innerHTML=', 'setInterval(', 'localStorage', 'document.cookie'):self.assertNotIn(bad,js.text)
        for page in ('/shop','/signup','/about','/casino'):
            r=self.client.get(page);self.assertNotIn('<script',r.text)
        r=self.client.get('/javascript');self.assertIn('id="jslicense-labels1"',r.text)
        self.assertIn('rel="jslicense"',r.text)

class PhotoPipelineTests(unittest.TestCase):
    def test_allowlist_blocks_ssrf_and_non_images(self):
        for value in ('http://upload.wikimedia.org/a.jpg','https://upload.wikimedia.org.evil.test/wikipedia/commons/a.jpg','https://127.0.0.1/a.jpg','https://upload.wikimedia.org@evil.test/a.jpg','https://upload.wikimedia.org:444/wikipedia/commons/a.jpg','https://upload.wikimedia.org/wikipedia/commons/x.svg','file:///etc/passwd'):
            self.assertFalse(photos.allowed_url(value),value)
        self.assertTrue(photos.allowed_url('https://upload.wikimedia.org/wikipedia/commons/a/a1/example.jpg'))
        self.assertTrue(photos.allowed_url('https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a1/example.jpg/960px-example.jpg'))
    def test_license_attribution_and_unknown_license_rejected(self):
        fields={'License':{'value':'cc-by-sa-4.0'},'LicenseShortName':{'value':'CC BY-SA 4.0'},'Artist':{'value':'<a href="x">Photographer</a>'}}
        r=photos.licence(fields);self.assertEqual(r['artist'],'Photographer')
        self.assertEqual(r['license_url'],'https://creativecommons.org/licenses/by-sa/4.0/')
        with self.assertRaises(photos.CatalogError):photos.licence({'License':{'value':'fair-use'}})
        with self.assertRaises(photos.CatalogError):photos.licence({k:v for k,v in fields.items() if k!='Artist'})
    def test_identity_rejects_wrong_model_and_generic_photo(self):
        p={'name':'Nikon D850','article':'Nikon D850'}
        page={'title':'Nikon D850','pageid':1,'pageimage':'20171009_D850_front.jpg','pageprops':{'wikibase_item':'Q123'}}
        info={'extmetadata':{'ImageDescription':{'value':'Nikon D850 camera, front view'}}}
        r=photos.identity_evidence(p,page,info);self.assertEqual(r['wikidata'],'Q123')
        with self.assertRaises(photos.CatalogError):photos.identity_evidence(p,dict(page,title='Nikon D810'),info)
        with self.assertRaises(photos.CatalogError):photos.identity_evidence(p,dict(page,pageimage='Camera.jpg'),{'extmetadata':{}})
    def test_decode_size_bounds_and_no_svg(self):
        for value in (b'<svg></svg>',b'',b'not an image'):
            with self.assertRaises(photos.CatalogError):photos.process_image(value)
        buf=BytesIO();Image.new('RGB',(20,20)).save(buf,format='PNG')
        with self.assertRaises(photos.CatalogError):photos.process_image(buf.getvalue())
        buf=BytesIO();Image.new('RGB',(480,320),(30,50,70)).save(buf,format='PNG')
        data,fp=photos.process_image(buf.getvalue());self.assertEqual(photos.sha(data),fp['sha256'])
        with Image.open(BytesIO(data)) as image:self.assertEqual(image.format,'WEBP');self.assertEqual(image.size,(480,320))
    def test_duplicate_models_files_pixels_and_perceptual_similarity(self):
        a={'wikidata':'Q1','commons_file':'a.jpg','source_sha1':'a'*40,'sha256':'1'*64,'pixel_sha256':'2'*64,'dhash':'0'*16}
        b={'wikidata':'Q2','commons_file':'b.jpg','source_sha1':'b'*40,'sha256':'3'*64,'pixel_sha256':'4'*64,'dhash':'f'*16}
        self.assertFalse(photos.duplicate(b,[a]))
        for key in ('wikidata','commons_file','source_sha1','sha256','pixel_sha256','dhash'):
            self.assertTrue(photos.duplicate(dict(b,**{key:a[key]}),[a]),key)
        self.assertTrue(photos.duplicate(dict(b,dhash='000000000000000f'),[a]))
    def test_missing_catalog_and_reduced_floor_fail_closed(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            with self.assertRaises(photos.CatalogError):photos.verify_photos(root)
            (root/'data/catalog.json').write_text(json.dumps({'minimum_verified':1,'maximum_products':4,'products':[]}))
            with self.assertRaises(photos.CatalogError):photos.import_catalog(root)
    def test_network_failure_never_publishes_fake_fallback(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            (root/'data/catalog.json').write_text(json.dumps(dict(catalog.SEEDS,products=catalog.SEEDS['products'][:60])))
            with patch.object(photos,'api',side_effect=photos.CatalogError('offline')),patch.object(photos.time,'sleep'):
                with self.assertRaises(photos.CatalogError):photos.import_catalog(root)
            self.assertFalse((root/'data/catalog-live.json').exists())
            self.assertEqual(json.loads((root/'data/catalog-import-report.json').read_text())['accepted_count'],0)
    def test_catalog_candidates_are_unique_and_not_preverified(self):
        self.assertGreaterEqual(len(catalog.SEEDS['products']),1000)
        self.assertEqual(len({p['id'] for p in catalog.SEEDS['products']}),len(catalog.SEEDS['products']))
        self.assertEqual(len({photos.normal(p['name']) for p in catalog.SEEDS['products']}),len(catalog.SEEDS['products']))
        self.assertFalse(any(p.get('verified') for p in catalog.SEEDS['products']))

    def test_metadata_json_invalid_shape_fails_closed(self):
        for blob in (b"[]",b"null",b"invalid-json",b'{"query":[]}',b'{"query":{"pages":42}}'):
            with patch.object(photos,'fetch',return_value=blob):
                with self.assertRaises(photos.CatalogError):photos.api('en.wikipedia.org',titles='Nikon D850')
    def test_normalized_commons_filename_cache_and_publication_floor(self):
        product=next(p for p in catalog.SEEDS['products'] if p['name']=='Nikon D850')
        page={'title':'Nikon D850','pageid':54656273,'lastrevid':1,'pageimage':'Nikon_D850_test.jpg','pageprops':{'wikibase_item':'Q37933342'}}
        metadata={'License':{'value':'cc-by-sa-4.0'},'LicenseShortName':{'value':'CC BY-SA 4.0'},'Artist':{'value':'Fixture author'},'ImageDescription':{'value':'Nikon D850 fixture metadata'}}
        info={'title':'File:Nikon D850 test.jpg','imageinfo':[{'thumburl':'https://upload.wikimedia.org/wikipedia/commons/a/a1/Nikon_D850_test.jpg','descriptionurl':'https://commons.wikimedia.org/wiki/File:Nikon_D850_test.jpg','sha1':'a'*40,'extmetadata':metadata}]}
        buf=BytesIO();Image.new('RGB',(480,320),(70,80,90)).save(buf,format='PNG')
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            (root/'data/catalog.json').write_text(json.dumps(dict(catalog.SEEDS,products=[product])))
            for repeat in range(2):
                metadata['Artist']['value']='Fixture author '+str(repeat)
                with patch.dict('os.environ',{'DOPAMINE_CATALOG_CACHE':str(root/'cache')}),patch.object(photos,'api',side_effect=[{'pages':[page]},{'pages':[info]}]),patch.object(photos,'fetch',return_value=buf.getvalue()) as fetch,patch.object(photos.time,'sleep'):
                    with self.assertRaises(photos.CatalogError):photos.import_catalog(root)
                report=json.loads((root/'data/catalog-import-report.json').read_text())
                self.assertEqual(report['accepted_count'],1)
                self.assertEqual(fetch.call_count,1 if repeat==0 else 0)
                cached=json.loads((root/'cache/metadata.json').read_text())[product['id']]
                self.assertEqual(cached['artist'],'Fixture author '+str(repeat))
                self.assertFalse((root/'data/catalog-live.json').exists())

    def test_category_interleaving_does_not_starve_small_categories(self):
        ordered=photos.round_robin_candidates(catalog.SEEDS)
        n=len(catalog.SEEDS['categories'])
        self.assertEqual(len(ordered),len(catalog.SEEDS['products']))
        self.assertEqual(len({p['category'] for p in ordered[:n]}),n)
        self.assertEqual({p['id'] for p in ordered},{p['id'] for p in catalog.SEEDS['products']})
