#!/usr/bin/env python3
"""Optional real-browser smoke test. Never loaded or served to visitors.

Requires Playwright + Chromium in the operator's test environment. The browser
has JavaScript disabled. DOM evaluation is test-driver introspection, not site JS.
No real accounts, passwords or database are retained after this test.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from socketserver import ThreadingMixIn
import sys
from tempfile import TemporaryDirectory
import threading
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIServer,WSGIRequestHandler,make_server
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import db
from app.config import Config
from app.web import App
from app.games import GAMES

class ThreadedServer(ThreadingMixIn,WSGIServer):daemon_threads=True
class QuietHandler(WSGIRequestHandler):
    def log_message(self,*args):pass


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--chromium',default='/usr/bin/chromium')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/browser-report.json')
    parser.add_argument('--screenshots',type=Path)
    args=parser.parse_args()
    from playwright.sync_api import sync_playwright
    report={'javascript_enabled':False,'photo_binaries_present':len(list((ROOT/'app/static/photos').glob('*.webp'))),
            'layout_checks':[],'flows':[],'external_requests':[],'console_errors':[]}
    if args.screenshots:args.screenshots.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory() as tmp:
        database=Path(tmp)/'test.sqlite3';db.initialize(database)
        server=make_server('127.0.0.1',0,lambda e,s:[],server_class=ThreadedServer,handler_class=QuietHandler)
        port=server.server_port;origin=f'http://127.0.0.1:{port}'
        config=Config(secret='browser-only-test-key-'*4,database=database,site_url=origin,
                      allowed_hosts=(f'127.0.0.1:{port}',),secure=False,require_local_photos=False,testing=True)
        server.set_app(App(config))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
                report['browser_version']=browser.version
                context=browser.new_context(java_script_enabled=False,reduced_motion='reduce')
                context.on('request',lambda r:report['external_requests'].append(r.url) if urlsplit(r.url).hostname!='127.0.0.1' else None)
                page=context.new_page()
                page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
                for width,height in ((1440,1000),(390,844)):
                    page.set_viewport_size({'width':width,'height':height})
                    for lang in ('pt-br','en','zh','ja'):
                        for path in ('/shop','/casino','/science','/about','/signup','/product/real-fallingwater'):
                            response=page.goto(origin+path+'?lang='+lang,wait_until='networkidle')
                            assert response.status==200,(lang,path,response.status)
                            dims=page.evaluate('({viewport:innerWidth,width:document.documentElement.scrollWidth})')
                            check={'path':path,'language':lang,'viewport':width,'content_width':dims['width']}
                            report['layout_checks'].append(check)
                            assert dims['width']<=width+1,check
                            assert page.locator('script').count()==0
                            if args.screenshots and lang=='pt-br' and path in ('/shop','/casino'):
                                page.screenshot(path=str(args.screenshots/f'{path[1:]}-{width}.png'),full_page=False)
                page.set_viewport_size({'width':1280,'height':900})
                page.goto(origin+'/signup?lang=pt-br')
                form=page.locator('form[action="/signup"]')
                form.locator('input[name="nickname"]').fill('browser_qa')
                form.locator('input[name="password"]').fill('CyanOrbit!Browser-2026')
                form.locator('input[name="adult"]').check()
                form.locator('button').click()
                page.wait_for_selector('#recovery-code')
                recovery=page.locator('#recovery-code code').inner_text()
                assert len(recovery)>=40
                report['flows'].append('signup and one-time recovery code')
                page.goto(origin+'/shop')
                page.locator('form[action="/catalog/all"] button').click()
                page.wait_for_url('**/cart?notice=bag_added')
                assert page.locator('form[action="/checkout"]').count()==1
                page.locator('form[action="/checkout"] button').click()
                page.wait_for_url('**/receipt/*')
                report['flows'].append('add all 384 items and complete checkout')
                page.goto(origin+'/collection')
                assert page.locator('a[href^="/receipt/"]').count()>=1
                report['flows'].append('persistent collection and receipt')
                for game in GAMES:
                    page.goto(origin+'/casino/'+game)
                    page.locator(f'form[action="/casino/{game}"] button').click()
                    page.wait_for_url('**/round/*')
                report['flows'].append('all ten fixed-bonus casino demonstrations')
                page.goto(origin+'/profile')
                form=page.locator('form[action="/profile"]')
                form.locator('input[name="display_name"]').fill('Browser QA')
                form.locator('select[name="language"]').select_option('zh')
                form.locator('input[name="reduced_motion"]').check()
                form.locator('button').click();page.wait_for_url('**/profile?notice=saved')
                assert page.locator('html').get_attribute('lang')=='zh-Hans'
                assert page.locator('body').get_attribute('class')=='reduced-motion'
                report['flows'].append('profile editing, Chinese preference, reduced motion')
                page.locator('form[action="/logout"] button').click()
                page.wait_for_url('**/shop')
                page.goto(origin+'/recover?lang=pt-br')
                form=page.locator('form[action="/recover"]')
                form.locator('input[name="nickname"]').fill('browser_qa')
                form.locator('input[name="recovery_code"]').fill(recovery)
                form.locator('input[name="password"]').fill('Updated!Browser-Cyan-2040')
                form.locator('button').click();page.wait_for_selector('#recovery-code')
                assert recovery!=page.locator('#recovery-code code').inner_text()
                report['flows'].append('logout and recovery-key password reset')
                page.goto(origin+'/profile')
                page.locator('form[action="/casino/pause"] button[value="1"]').click()
                page.wait_for_url('**/profile?notice=saved')
                response=page.goto(origin+'/casino/prism')
                assert response.status==403
                report['flows'].append('voluntary pause enforced by backend')
                assert not report['external_requests'],report['external_requests']
                assert not report['console_errors'],report['console_errors']
                context.close();browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)
    report['status']='passed'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'status':'passed','layout_checks':len(report['layout_checks']),'flows':len(report['flows']),
                      'photo_binaries_present':report['photo_binaries_present']}))
    return 0

if __name__=='__main__':raise SystemExit(main())
