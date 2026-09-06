#!/usr/bin/env python3
"""Optional real TLS/Nginx/HTTP integration, using isolated temporary listeners.

This is NOT a browser test, Docker test, Gunicorn test, or a test of the operator's
NPM installation. Requires local nginx and openssl executables; changes no system
configuration and leaves no accounts outside a disposable SQLite database.
"""
from contextlib import closing
from http.cookies import SimpleCookie
import http.client
import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
from urllib.parse import urlencode
from wsgiref.simple_server import make_server
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app import db
from app.config import Config,LANGUAGES
from app.games import GAMES
from app.money import money
from app.web import App
from tests.helpers import Result
from tests.test_http import ThreadedServer,QuietHandler


def main():
    for binary in ('nginx','openssl'):
        if not shutil.which(binary):raise SystemExit(binary+' is required for this optional test.')
    requests=0;checks=[]
    with TemporaryDirectory(prefix='dopamine-proxy-qa-') as directory:
        root=Path(directory);path=root/'database.sqlite3';db.initialize(path)
        backend=make_server('127.0.0.1',0,lambda e,s:[],server_class=ThreadedServer,handler_class=QuietHandler)
        with closing(socket.socket()) as s:s.bind(('127.0.0.1',0));front_port=s.getsockname()[1]
        origin='https://127.0.0.1:'+str(front_port)
        backend.set_app(App(Config(secret='local-TLS-integration-only-'*4,database=path,site_url=origin,
            allowed_hosts=('127.0.0.1:'+str(front_port),),proxy_cidrs=('127.0.0.1/32',),
            secure=True,require_local_photos=False,testing=True)))
        thread=threading.Thread(target=backend.serve_forever,daemon=True);thread.start()
        cert=root/'cert.pem';key=root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN=localhost',
            '-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        config=root/'nginx.conf'
        config.write_text(f'''worker_processes 1;
pid {root}/nginx.pid;
error_log {root}/error.log;
events {{ worker_connections 64; }}
http {{ access_log off; client_body_temp_path {root}/body; proxy_temp_path {root}/proxy;
server {{ listen 127.0.0.1:{front_port} ssl; server_name localhost;
ssl_certificate {cert}; ssl_certificate_key {key};
location / {{ proxy_pass http://127.0.0.1:{backend.server_port};
proxy_set_header Host $http_host; proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme; proxy_set_header X-Forwarded-For $remote_addr;
}} }} }}''')
        nginx=subprocess.Popen(['nginx','-p',str(root)+'/', '-c',str(config),'-g','daemon off;'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        context=ssl.create_default_context(cafile=str(cert))
        def request(endpoint,cookies,source,data=None,explicit_origin=None):
            nonlocal requests
            conn=http.client.HTTPSConnection('127.0.0.1',front_port,context=context,timeout=10,source_address=(source,0))
            headers={'Cookie':'; '.join(k+'='+v for k,v in cookies.items())}
            if data is not None:
                headers.update({'Origin':explicit_origin or origin,'Content-Type':'application/x-www-form-urlencoded','Sec-Fetch-Site':'same-origin'})
                conn.request('POST',endpoint,urlencode(data).encode(),headers)
            else:conn.request('GET',endpoint,headers=headers)
            response=conn.getresponse();result=Result(response.status,response.getheaders(),response.read());conn.close();requests+=1
            for k,v in result.headers:
                if k.lower()=='set-cookie':
                    jar=SimpleCookie();jar.load(v)
                    for name,morsel in jar.items():cookies[name]=morsel.value
            assert result.header('X-Dopamine-Version')=='1.1.0'
            assert result.header('Referrer-Policy')=='same-origin'
            return result
        try:
            for _ in range(50):
                if nginx.poll() is not None:raise RuntimeError('Temporary nginx failed: '+nginx.stderr.read().decode())
                try:
                    with socket.create_connection(('127.0.0.1',front_port),timeout=.1):break
                except OSError:time.sleep(.05)
            for i,lang in enumerate(LANGUAGES):
                source=f'127.0.0.{20+i}';cookies={}
                page=request('/signup?lang='+lang,cookies,source)
                assert page.status==200
                cookie=page.header('Set-Cookie')
                assert all(x in cookie for x in ('__Host-dopamine=','Secure','HttpOnly','SameSite=Lax'))
                form=dict(page.form('/signup'),nickname='tls_account_'+str(i),password='TLS-Signup!2026-Local',adult='yes')
                assert request('/signup',cookies,source,form,'null').status==403
                assert request('/signup',cookies,source,form,'https://attacker.invalid').status==403
                registered=request('/signup',cookies,source,form);assert registered.status==200,registered.text
                assert request('/profile',cookies,source).status==200
                p=request('/product/cars-new-01?lang='+lang,cookies,source)
                purchase=request('/buy/cars-new-01',cookies,source,dict(p.form('/buy/cars-new-01'),quantity='2'))
                assert purchase.status==303
                assert request(purchase.location+'?lang='+lang,cookies,source).status==200
                for game in GAMES:
                    p=request('/casino/'+game+'?lang='+lang,cookies,source)
                    assert p.status==200
                    form=dict(p.form('/casino/'+game),stake='500')
                    reply=request('/casino/'+game,cookies,source,form);assert reply.status==303,reply.text
                    outcome=request(reply.location+'?lang='+lang,cookies,source)
                    assert outcome.status==200,outcome.text
                    assert money(100,lang) in outcome.text
                checks.append({'language':lang,'registration':'passed','null_and_foreign_origin':'rejected',
                    'secure_cookie':'passed','purchase':'passed','games':len(GAMES),'TLS_validation':'enabled'})
            with closing(db.connect(path)) as c:
                assert c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==4
                assert c.execute('SELECT COUNT(*) FROM purchases').fetchone()[0]==4
                assert c.execute('SELECT COUNT(*) FROM all_rounds').fetchone()[0]==40
                assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        finally:
            nginx.terminate()
            try:nginx.wait(timeout=5)
            except subprocess.TimeoutExpired:nginx.kill();nginx.wait()
            nginx.stderr.close();backend.shutdown();backend.server_close();thread.join(timeout=5)
    report={'status':'passed','http_requests':requests,'TLS':'temporary locally trusted certificate with hostname verification',
        'proxy':'isolated local Nginx, not Docker/NPM','backend':'WSGI reference server, not Gunicorn','browser':False,'cases':checks}
    (ROOT/'docs/proxy-integration-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
