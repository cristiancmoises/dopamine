"""Real loopback HTTP integration; independent of Playwright network policy."""
from contextlib import closing
from http.cookies import SimpleCookie
import http.client
from pathlib import Path
from socketserver import ThreadingMixIn
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.parse import urlencode
from wsgiref.simple_server import WSGIServer,WSGIRequestHandler,make_server
from wsgiref.validate import validator
from app import db
from app.config import Config
from app.web import App
from tests.helpers import Result

class ThreadedServer(ThreadingMixIn,WSGIServer):daemon_threads=True
class QuietHandler(WSGIRequestHandler):
    def log_message(self,*args):pass

class HttpIntegrationTests(unittest.TestCase):
    def test_real_http_signup_purchase_and_casino_with_wsgi_validation(self):
        with TemporaryDirectory() as name:
            path=Path(name)/'db.sqlite3';db.initialize(path)
            server=make_server('127.0.0.1',0,lambda e,s:[],server_class=ThreadedServer,handler_class=QuietHandler)
            port=server.server_port;origin=f'http://127.0.0.1:{port}'
            config=Config(secret='HTTP-integration-test-key-'*4,database=path,site_url=origin,
                allowed_hosts=(f'127.0.0.1:{port}',),secure=False,require_local_photos=False,testing=True)
            server.set_app(validator(App(config)))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            cookies={}
            def request(endpoint,data=None):
                conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
                headers={}
                if cookies:headers['Cookie']='; '.join(k+'='+v for k,v in cookies.items())
                if data is not None:
                    headers.update({'Content-Type':'application/x-www-form-urlencoded','Origin':origin})
                    conn.request('POST',endpoint,urlencode(data).encode(),headers)
                else:conn.request('GET',endpoint,headers=headers)
                response=conn.getresponse();result=Result(response.status,response.getheaders(),response.read());conn.close()
                for key,value in result.headers:
                    if key.lower()=='set-cookie':
                        parsed=SimpleCookie();parsed.load(value)
                        for n,m in parsed.items():cookies[n]=m.value
                return result
            try:
                form=request('/signup').form('/signup')
                result=request('/signup',dict(form,nickname='http_qa',password='HttpCyan!Nebula-2026',adult='yes'))
                self.assertEqual(result.status,200)
                form=request('/product/real-porsche-911').form('/buy/real-porsche-911')
                result=request('/buy/real-porsche-911',dict(form,quantity='2'))
                self.assertEqual(result.status,303)
                self.assertEqual(request(result.location).status,200)
                form=request('/casino/cards').form('/casino/cards')
                result=request('/casino/cards',dict(form,stake='500',card='3'))
                self.assertEqual(result.status,303)
                self.assertEqual(request(result.location).status,200)
                with closing(db.connect(path)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM purchases').fetchone()[0],1)
                    self.assertEqual(connection.execute('SELECT SUM(bonus) FROM rounds').fetchone()[0],100)
                css=request('/static/style.css')
                self.assertEqual(css.status,200)
                self.assertEqual(css.header('Content-Type'),'text/css; charset=utf-8')
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
