#!/usr/bin/env python3
"""Offline Chromium interaction QA using a real WSGI app behind a test bridge.

Browser-native HTTP is blocked in some authoring environments. This harness
uses production HTML/CSS/JS and actual SQLite-backed WSGI handlers, but injects
ONLY test transport/history/location objects around the unmodified JS source.
It is NOT a test of real HTTP, cookie transport, CSP enforcement, TLS or NPM.
No harness code is served by the application.
"""
import argparse,json,re,sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import db,tables
from app.config import Config
from app.web import App
from tests.helpers import Client
from tests.test_live import shoe

def main():
 from playwright.sync_api import sync_playwright
 parser=argparse.ArgumentParser();parser.add_argument('--report',type=Path,required=True);parser.add_argument('--screenshots',type=Path);parser.add_argument('--widths',type=int,nargs='+',default=[1440,390]);parser.add_argument('--languages',nargs='+',default=['pt-br','en','zh','ja']);parser.add_argument('--motion',action='store_true')
 args=parser.parse_args()
 if args.screenshots:args.screenshots.mkdir(parents=True,exist_ok=True)
 source=(ROOT/'app/static/tables.js').read_text();css=(ROOT/'app/static/style.css').read_text()
 results=[];events=[];errors=[]
 with TemporaryDirectory() as tmp:
  path=Path(tmp)/'db';db.initialize(path)
  app=App(Config(secret='offline-browser-test-secret-'*4,database=path,site_url='http://localhost',allowed_hosts=('localhost',),secure=False,require_local_photos=False,testing=True))
  c=Client(app);registration=c.get('/signup');assert c.submit(registration,'/signup',nickname='table_browser',password='Browser-Test!Password-2026',adult='yes').status==200
  def post(url,body):
   fields={k:v[0] for k,v in parse_qs(body,keep_blank_values=True).items()}
   if urlsplit(url).path=='/play/blackjack':
    with patch.object(tables,'deck',return_value=shoe(4,10,5,7,2,3,4)):r=c.post(url,fields,headers={'HTTP_ACCEPT':'application/json'})
   else:r=c.post(url,fields,headers={'HTTP_ACCEPT':'application/json'})
   events.append({'path':urlsplit(url).path,'status':r.status})
   return {'status':r.status,'headers':{k.lower():v for k,v in r.headers},'body':r.text}
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
   context=browser.new_context(reduced_motion='no-preference' if args.motion else 'reduce')
   for width in args.widths:
    for lang in args.languages:
     for game in tables.TABLES:
      with closing(db.connect(path)) as conn:conn.execute('DELETE FROM rate_limits')
      c.cookies['dopamine_lang']=lang
      page=context.new_page();page.set_viewport_size({'width':width,'height':900})
      page.on('pageerror',lambda error:errors.append(str(error)))
      endpoint='/play/'+game+'?new=1';response=c.get(endpoint);assert response.status==200
      html=re.sub(r'<script\b[^>]*>.*?</script>','',response.text,flags=re.S)
      html=re.sub(r'<link\b[^>]*>','',html)
      html=html.replace('</head>','<base href="http://localhost"><style>'+css+'</style></head>')
      page.set_content(html,wait_until='load');page.expose_function('__dopaminePost',post)
      before=page.evaluate('document.documentElement.scrollWidth');assert before<=width+1,(game,lang,width,before)
      script='''(function(location,history,fetch){\n'''+source+'''\n})({href:"http://localhost/",origin:"http://localhost"},{replaceState:function(_s,_t,url){window.__lastRoundURL=url;}},async function(url,options){const r=await window.__dopaminePost(String(url),options.body.toString());return {ok:r.status>=200&&r.status<300,status:r.status,headers:{get:k=>r.headers[k.toLowerCase()]||null},json:async()=>JSON.parse(r.body)};});'''
      page.add_script_tag(content=script)
      if game=='roulette':
       page.locator('[name=choice][value=number]').check();page.locator('select[name=number]').select_option('17')
      elif game=='keno':
       page.locator('button[data-pick="5"]').click();page.locator('button[data-pick="17"]').click()
       assert page.locator('[name=pick5]').input_value()=='17'
      page.locator('form[data-live-form] button[type=submit]').first.click()
      page.wait_for_function('!!window.__lastRoundURL',timeout=10000)
      page.wait_for_function('!document.querySelector("#practice-table").hasAttribute("aria-busy")',timeout=10000)
      if game=='blackjack':
       page.locator('button[name=move][value=hit]').click()
       page.wait_for_function('document.querySelector("input[name=revision]").value==="1"',timeout=10000)
       page.wait_for_function('!document.querySelector("#practice-table").hasAttribute("aria-busy")')
       page.locator('button[name=move][value=stand]').click()
       page.wait_for_selector('.round-ledger')
       page.wait_for_function('!document.querySelector("#practice-table").hasAttribute("aria-busy")')
      assert page.locator('.round-ledger').count()==1,(game,lang)
      assert page.locator('#table-message').inner_text()==''
      after=page.evaluate('document.documentElement.scrollWidth');assert after<=width+1,(game,lang,width,after)
      assert page.evaluate('getComputedStyle(document.body).backgroundColor')=='rgb(0, 0, 0)'
      results.append({'game':game,'language':lang,'width':width,'content_width':after,'result':page.locator('.round-status h2').inner_text()})
      if args.screenshots and lang=='en' and width in (1440,390):
       page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(args.screenshots/f'{game}-{width}.png'),full_page=True)
      print('FLOW OK',width,lang,game,flush=True)
      page.close()
   version=browser.version;browser.close()
 assert not errors,errors
 report={'transport':'offline Chromium with injected WSGI bridge; production HTML/CSS/JS; not browser-native HTTP','browser_version':version,'animations_enabled':args.motion,'flow_count':len(results),'wsgi_posts':len(events),'javascript_errors':errors,'checks':results,'requests':events}
 args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('BROWSER BRIDGE:',len(results),'flows;',len(events),'SQLite-backed POSTs; no JS errors.')
if __name__=='__main__':main()
