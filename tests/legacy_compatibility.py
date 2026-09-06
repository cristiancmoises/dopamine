#!/usr/bin/env python3
"""Use an untouched earlier source checkout against a disposable v1.2 database.

No live data, Docker, DNS, TLS or production credentials are accessed.
"""
import argparse,json,subprocess,sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import db,catalog
from app.config import Config
from app.web import App
from tests.helpers import Client
SECRET='local-legacy-compatibility-key-'*4
PASSWORD='LegacyRollback!Test-2026'
CHILD=r'''
from pathlib import Path
import sys,json
from app import db,__version__
from app.config import Config
from app.web import App
from tests.helpers import Client
path=Path(sys.argv[1]);db.initialize(path)
c=Client(App(Config(secret='local-legacy-compatibility-key-'*4,database=path,site_url='http://localhost',allowed_hosts=('localhost',),secure=False,require_local_photos=False,testing=True)))
r=c.submit(c.get('/login'),'/login',nickname='rollback_test',password='LegacyRollback!Test-2026')
assert r.status==303,r.text
for endpoint in ('/profile','/collection',sys.argv[2]):
 response=c.get(endpoint);assert response.status==200,response.text
assert c.get(sys.argv[3]).status==404
r=c.submit(c.get('/product/cars-1-1'),'/buy/cars-1-1',quantity='1');assert r.status==303,r.text
print(json.dumps({'version':__version__,'old_receipt':r.location}))
'''
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--legacy-source',type=Path,required=True);parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
 legacy=args.legacy_source.resolve()
 if not (legacy/'app/web.py').is_file():raise SystemExit('An untouched earlier source directory is required.')
 with TemporaryDirectory() as tmp:
  path=Path(tmp)/'compat.sqlite3';db.initialize(path)
  c=Client(App(Config(secret=SECRET,database=path,site_url='http://localhost',allowed_hosts=('localhost',),secure=False,require_local_photos=False,testing=True)))
  r=c.submit(c.get('/signup'),'/signup',nickname='rollback_test',password=PASSWORD,adult='yes');assert r.status==200
  pid=catalog.SEEDS['products'][0]['id']
  purchase=c.submit(c.get('/product/'+pid),'/buy/'+pid,quantity='1');assert purchase.status==303
  game=c.submit(c.get('/play/roulette?new=1'),'/play/roulette',stake='100',choice='red');assert game.status==303
  child=subprocess.run([sys.executable,'-c',CHILD,str(path),purchase.location,game.location],cwd=legacy,check=True,timeout=30,capture_output=True,text=True)
  result=json.loads(child.stdout.strip());db.initialize(path);db.initialize(path)
  assert c.get(game.location).status==200
  historical=c.get(result['old_receipt']);assert historical.status==200
  assert catalog.historical('cars-1-1','pt-br')['name'] in historical.text
  with closing(db.connect(path)) as conn:
   assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]==1
   assert conn.execute('SELECT COUNT(*) FROM purchases').fetchone()[0]==2
   assert conn.execute('SELECT COUNT(*) FROM interactive_rounds').fetchone()[0]==1
   assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
   assert not conn.execute('PRAGMA foreign_key_check').fetchall()
 report={'status':'passed','legacy_version':result['version'],'scope':'untouched earlier source accessing an upgraded disposable SQLite database; not Docker','preserved':['password login','new-item receipt','historical fictional receipt','all purchases','interactive round after re-upgrade']}
 args.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()
