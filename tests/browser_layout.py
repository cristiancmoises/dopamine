#!/usr/bin/env python3
"""Offline layout-only QA, for sandboxes that block browser loopback networking.

Renders the actual server-produced HTML and project CSS in a JavaScript-disabled
browser without an HTTP transport. This does NOT validate TLS, Gunicorn or the
Docker network. Full HTTP flows have a separate optional browser_smoke.py test.
"""
import argparse
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import db
from app.config import Config
from app.web import App
from app.games import GAMES
from tests.helpers import Client

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--chromium',default='/usr/bin/chromium')
    parser.add_argument('--screenshots',type=Path)
    args=parser.parse_args()
    if args.screenshots:args.screenshots.mkdir(parents=True,exist_ok=True)
    from playwright.sync_api import sync_playwright
    report={'transport':'offline server-rendered HTML + identical project CSS',
            'javascript_enabled':False,'real_http_transport_tested':False,'layout_checks':[],
            'photo_binaries_present':len(list((ROOT/'app/static/photos').glob('*.webp')))}
    css=(ROOT/'app/static/style.css').read_text()
    with TemporaryDirectory() as temp:
        path=Path(temp)/'db.sqlite3';db.initialize(path)
        app=App(Config(secret='offline-layout-test-key'*4,database=path,site_url='http://localhost',
            allowed_hosts=('localhost',),secure=False,require_local_photos=False,testing=True))
        client=Client(app)
        registration=client.get('/signup')
        assert client.submit(registration,'/signup',nickname='layout_account',password='Layout-Only!2026-Test',adult='yes').status==200
        round_paths=[]
        for game in GAMES:
            reply=client.submit(client.get('/casino/'+game),'/casino/'+game,stake='100')
            assert reply.status==303
            round_paths.append(reply.location)
        # Auth pages must be checked as logged-out, protected pages as logged-in.
        anonymous=Client(app,ip='203.0.113.88')
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
            report['browser_version']=browser.version
            context=browser.new_context(java_script_enabled=False,reduced_motion='reduce')
            page=context.new_page()
            for width,height in ((1440,1000),(390,844),(360,800)):
                page.set_viewport_size({'width':width,'height':height})
                for lang in ('pt-br','en','zh','ja'):
                    for endpoint in ('/shop','/casino','/science','/about','/signup','/login','/recover','/product/real-fallingwater','/profile','/cart','/collection')+tuple('/casino/'+g for g in GAMES)+tuple(round_paths):
                        result=(anonymous if endpoint in {'/signup','/login','/recover'} else client).get(endpoint+'?lang='+lang)
                        assert result.status==200
                        html=re.sub(r'<link\b[^>]*>','',result.text)
                        html=html.replace('</head>','<style>'+css+'</style></head>')
                        page.set_content(html,wait_until='load')
                        dimensions=page.evaluate('({viewport:innerWidth,width:document.documentElement.scrollWidth})')
                        check=dict(path=endpoint,language=lang,viewport=width,content_width=dimensions['width'])
                        report['layout_checks'].append(check)
                        assert dimensions['width']<=width+1,check
                        assert page.locator('script').count()==0
                        background=page.evaluate('getComputedStyle(document.body).backgroundColor')
                        assert background=='rgb(0, 0, 0)',background
                        if args.screenshots and lang=='pt-br' and width in (1440,390) and endpoint in ('/shop','/casino','/casino/plinko','/signup'):
                            page.screenshot(path=str(args.screenshots/f'{endpoint[1:].replace(chr(47), chr(45))}-{width}.png'),full_page=False)
            # Native <details> controls and motion switch work without scripts.
            details=page.locator('details.language')
            details.locator('summary').click()
            assert details.get_attribute('open') is not None
            details.locator('summary').click()
            page.locator('label[for="motion-toggle"]').click()
            assert page.locator('#motion-toggle').is_checked()
            report['native_controls']='language details + animation checkbox passed'
            context.close();browser.close()
    report['status']='passed'
    (ROOT/'docs/browser-layout-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'status':report['status'],'layout_checks':len(report['layout_checks']),
                      'photo_binaries_present':report['photo_binaries_present'],'http_transport_tested':False}))
    return 0

if __name__=='__main__':raise SystemExit(main())
