"""Real early-1.1 runtime fixtures, schema preservation and application compatibility."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from app import db, catalog
from app.config import ROOT,Config,LANGUAGES
from app.schema_bridge import objects,check_early
from app.web import App
from scripts.bridge_rehearsal import fingerprint,rehearse
from tests.helpers import Client

SECRET='only-a-disposable-bridge-test-secret-'*3
PASSWORD='Bridge-Laboratory-Password!2026'

SEED=r'''
import json,sys
from pathlib import Path
from app import db,catalog
from app.config import Config
from app.web import App
from app.games import GAMES
from tests.helpers import Client
p=Path(sys.argv[1]);db.initialize(p)
cfg=Config(secret=sys.argv[2],database=p,site_url='http://localhost',allowed_hosts=('localhost',),secure=False,require_local_photos=False,testing=True)
c=Client(App(cfg));s=c.submit(c.get('/signup'),'/signup',nickname='bridge_original',password=sys.argv[3],adult='yes')
assert s.status==200,s.status
ids=list(catalog.PRODUCTS);receipts=[]
for pid in (ids[0],ids[-1]):
 r=c.submit(c.get('/product/'+pid),'/buy/'+pid,quantity='2');assert r.status==303;receipts.append(r.location)
rounds=[]
for game in GAMES:
 r=c.submit(c.get('/casino/'+game),'/casino/'+game,stake='500',choice='1',card='1');assert r.status==303,(game,r.status)
 rounds.append(r.location)
print(json.dumps({'cookies':c.cookies,'rounds':rounds,'receipts':receipts,'catalog':catalog.PRODUCTS}))
'''


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=TemporaryDirectory();cls.addClassCleanup(cls.folder.cleanup)
        cls.root=Path(cls.folder.name)
        fixture=ROOT/'tests/fixtures/early11-source.tar.gz'
        if hashlib.sha256(fixture.read_bytes()).hexdigest()!='c52967c53247d3556daad5684d75714cdd790199b41a9a659896212ff0b5a073':
            raise RuntimeError('Unexpected historical fixture')
        with tarfile.open(fixture) as t:t.extractall(cls.root/'early',filter='data')
        cls.early=cls.root/'early/dopamine-1.1.0'
        cls.seed=cls.root/'seed.sqlite3'
        r=subprocess.run([sys.executable,'-B','-c',SEED,str(cls.seed),SECRET,PASSWORD],cwd=cls.early,text=True,capture_output=True,timeout=40)
        if r.returncode:raise AssertionError(r.stderr)
        cls.meta=json.loads(r.stdout)

    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'test.sqlite3';shutil.copy2(self.seed,self.path)
        self.config=Config(secret=SECRET,database=self.path,site_url='http://localhost',allowed_hosts=('localhost',),secure=False,require_local_photos=False,testing=True)

    def client(self):
        return Client(App(self.config),cookies=self.meta['cookies'])

    def snapshot(self):
        with closing(db.connect(self.path)) as c:return fingerprint(c),objects(c)

    def test_additive_migration_preserves_every_existing_value_and_core_definition(self):
        before,defs=self.snapshot();db.initialize(self.path);db.initialize(self.path)
        after,newdefs=self.snapshot()
        self.assertTrue(all(after[k]==v for k,v in before.items()))
        self.assertTrue(all(newdefs[k]==v for k,v in defs.items()))
        with closing(db.connect(self.path)) as c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM all_rounds').fetchone()[0],9)
            self.assertEqual(c.execute('SELECT revision FROM schema_features WHERE name="early11_bridge"').fetchone()[0],1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_rehearsal_reports_preservation_and_repeatability(self):
        r=rehearse(self.path)
        self.assertEqual(r['user_version'],2);self.assertTrue(r['existing_rows_unchanged'])
        self.assertTrue(r['existing_objects_unchanged']);self.assertEqual(r['repeated_initialization'],'ok')

    def test_every_original_result_and_receipt_renders_all_languages(self):
        db.initialize(self.path);client=self.client()
        for path in self.meta['rounds']+self.meta['receipts']:
            for lang in LANGUAGES:
                r=client.get(path+'?lang='+lang)
                self.assertEqual(r.status,200,(path,lang,r.text))
        with closing(db.connect(self.path)) as c:
            for row in c.execute('SELECT id,result_json FROM rounds'):
                result=json.loads(row['result_json']);page=client.get('/round/'+row['id'])
                for tile in result['tiles']:self.assertIn(str(tile),page.text)

    def test_all_512_old_products_keep_their_own_historical_names_and_amounts(self):
        self.assertEqual(len(self.meta['catalog']),512)
        for pid,product in self.meta['catalog'].items():
            self.assertEqual(catalog.LEGACY[pid]['credits'],product['credits'])
            for lang in LANGUAGES:
                self.assertEqual(catalog.historical(pid,lang)['name'],product['name'])
                self.assertTrue(catalog.historical(pid,lang)['legacy'])

    def test_original_login_password_and_sessions_still_work(self):
        db.initialize(self.path)
        self.assertEqual(self.client().get('/profile').status,200)
        fresh=Client(App(self.config),ip='203.0.113.122')
        r=fresh.submit(fresh.get('/login'),'/login',nickname='bridge_original',password=PASSWORD)
        self.assertEqual(r.status,303,r.text);self.assertEqual(fresh.get('/profile').status,200)

    def test_export_keeps_old_json_and_all_games_without_secrets(self):
        db.initialize(self.path);c=self.client()
        r=c.submit(c.get('/profile'),'/profile/export',current_password=PASSWORD)
        self.assertEqual(r.status,200,r.text)
        payload=json.loads(r.text)
        self.assertEqual(len(payload['rounds']),9)
        self.assertIn('roulette',{row['game'] for row in payload['rounds']})
        self.assertNotIn('password_hash',r.text);self.assertNotIn('recovery_hash',r.text)
        with closing(db.connect(self.path)) as con:
            originals={row['id']:row['result_json'] for row in con.execute('SELECT * FROM rounds')}
        self.assertTrue(all(row['result_json']==originals[row['id']] for row in payload['rounds']))

    def test_unknown_schema2_does_not_pass_just_because_version_matches(self):
        with closing(db.connect(self.path)) as c:c.execute('CREATE TABLE unexpected_payload(x)')
        before=self.snapshot()
        with self.assertRaisesRegex(RuntimeError,'Unrecognized schema-2'):db.initialize(self.path)
        self.assertEqual(before,self.snapshot())

    def test_missing_core_table_is_rejected(self):
        with closing(db.connect(self.path)) as c:c.execute('DROP TABLE favorites')
        before=self.snapshot()
        with self.assertRaisesRegex(RuntimeError,'Unrecognized schema-2'):db.initialize(self.path)
        self.assertEqual(before,self.snapshot())

    def test_arbitrary_empty_version2_rejected(self):
        p=Path(self.temp.name)/'empty.sqlite3'
        with closing(db.connect(p)) as c:c.execute('PRAGMA user_version=2')
        with self.assertRaisesRegex(RuntimeError,'Unrecognized schema-2'):db.initialize(p)
        with closing(db.connect(p)) as c:self.assertEqual(objects(c),{})

    def test_future_feature_revision_rejected(self):
        db.initialize(self.path)
        with closing(db.connect(self.path)) as c:c.execute("UPDATE schema_features SET revision=99 WHERE name='early11_bridge'")
        before=self.snapshot()
        with self.assertRaisesRegex(RuntimeError,'feature revision'):db.initialize(self.path)
        self.assertEqual(before,self.snapshot())

    def test_partial_additions_rolled_back_on_failure(self):
        before=self.snapshot()
        def broken(script):
            yield 'CREATE TABLE partial_bridge(x);'
            yield 'THIS IS INVALID SQL;'
        with patch('app.schema_bridge.statements',broken):
            with self.assertRaises(sqlite3.Error):db.initialize(self.path)
        self.assertEqual(before,self.snapshot())

    def test_foreign_key_problem_blocks_migration_without_repairing_data(self):
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('PRAGMA foreign_keys=OFF')
            c.execute("INSERT INTO favorites VALUES(9999,'unknown')");c.commit()
        before=self.snapshot()
        with self.assertRaisesRegex(RuntimeError,'Foreign key'):db.initialize(self.path)
        self.assertEqual(before,self.snapshot())

    def test_real_old_runtime_restarts_and_writes_after_new_tables_are_added(self):
        db.initialize(self.path)
        # Keep an extra table record and an interactive record that the old runtime ignores.
        with closing(db.connect(self.path)) as c:
            c.execute("INSERT INTO extra_rounds VALUES('future-demo',1,'bingo','future-key',100,100,1,'{}')")
        before=self.snapshot()[0]
        code=r'''
import sys,json
from pathlib import Path
from app import db
from app.config import Config
from app.web import App
from tests.helpers import Client
p=Path(sys.argv[1]);db.initialize(p)
a=App(Config(secret=sys.argv[2],database=p,site_url='http://localhost',allowed_hosts=('localhost',),secure=False,require_local_photos=False,testing=True))
c=Client(a,cookies=json.loads(sys.argv[3]));assert c.get('/collection').status==200
r=c.submit(c.get('/casino/roulette'),'/casino/roulette',stake='100',choice='2');assert r.status==303
assert c.get(r.location).status==200
print('OLD_RUNTIME_WRITE_OK')
'''
        r=subprocess.run([sys.executable,'-B','-c',code,str(self.path),SECRET,json.dumps(self.meta['cookies'])],cwd=self.early,text=True,capture_output=True,timeout=30)
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('OLD_RUNTIME_WRITE_OK',r.stdout)
        db.initialize(self.path);db.initialize(self.path)
        with closing(db.connect(self.path)) as c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM rounds').fetchone()[0],10)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM all_rounds').fetchone()[0],11)
        after=self.snapshot()[0]
        for table in ('users','purchases','purchase_items','extra_rounds'):
            self.assertEqual(before[table],after[table])

    def test_delete_account_cascades_to_old_and_new_history(self):
        db.initialize(self.path);c=self.client()
        with closing(db.connect(self.path)) as conn:conn.execute("INSERT INTO extra_rounds VALUES('future-demo',1,'bingo','future-key',100,100,1,'{}')")
        r=c.submit(c.get('/profile'),'/profile/delete',current_password=PASSWORD,confirm='yes')
        self.assertEqual(r.status,303,r.text)
        with closing(db.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM all_rounds').fetchone()[0],0)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_maintenance_gate_blocks_valid_post_without_creating_account(self):
        db.initialize(self.path);c=Client(App(self.config),ip='203.0.113.122')
        form=c.get('/signup');(self.path.parent/'.dopamine-upgrading').write_text('test marker')
        r=c.submit(form,'/signup',nickname='new_during_update',password=PASSWORD,adult='yes')
        self.assertEqual(r.status,503,r.text);self.assertEqual(r.header('X-Dopamine-Maintenance'),'active')
        with closing(db.connect(self.path)) as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)

    def test_recorded_tiles_are_escaped(self):
        db.initialize(self.path)
        with closing(db.connect(self.path)) as c:
            rid=c.execute('SELECT id FROM rounds LIMIT 1').fetchone()[0]
            c.execute('UPDATE rounds SET result_json=? WHERE id=?',(json.dumps({'schema':1,'tiles':['<script>alert(1)</script>']}),rid))
        page=self.client().get('/round/'+rid)
        self.assertEqual(page.status,200,page.text);self.assertIn('&lt;script&gt;',page.text);self.assertNotIn('<script>alert',page.text)

    def test_concurrent_initialization_is_idempotent(self):
        from concurrent.futures import ThreadPoolExecutor
        before=self.snapshot()[0]
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(db.initialize,[self.path]*3))
        after=self.snapshot()[0]
        self.assertTrue(all(after[k]==v for k,v in before.items()))
        with closing(db.connect(self.path)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM schema_features WHERE name='early11_bridge'").fetchone()[0],1)
