"""Server-rendered WSGI application. No public payment, upload, scripting or admin endpoint.

All mutations require same-origin synchronizer CSRF tokens. Financial-looking
values are display-only fiction, and never accepted from request bodies.
"""
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import SimpleCookie, CookieError
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, unquote
import hashlib
import base64
import hmac
import json
import logging
import math
import os
import threading
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader, select_autoescape, StrictUndefined
from .config import Config, ROOT, LANGUAGES
from . import __version__
from . import catalog, content, db as database, security as sec
from .i18n import text
from .money import money, currency, infinity
from . import tables
from .games import GAMES, LEGACY_GAMES, OPTIONS, result_for

LOG=logging.getLogger('dopamine')
MAX_BODY=16384
GAME_PATTERN = '|'.join(GAMES)

class Fault(Exception):
    def __init__(self,status,key='bad_request'):
        self.status,self.key=status,key

@dataclass
class Response:
    body: object=b''
    status: int=200
    headers: list=field(default_factory=list)
    content_type: str='text/html; charset=utf-8'

def redirect(path): return Response(status=303,headers=[('Location',path)])
def integer(value,lo,hi):
    if not re.fullmatch(r'[0-9]{1,10}',str(value)):
        raise Fault(400)
    v=int(value)
    if not lo<=v<=hi: raise Fault(400)
    return v

def safe_next(value):
    # Redirect targets are local, known pages; no arbitrary URL forwarding.
    if not value or len(value)>300: return '/shop'
    try: parsed=urlsplit(value)
    except ValueError: return '/shop'
    path=parsed.path
    allowed={'/javascript','/shop','/cart','/collection','/profile','/casino','/science','/about','/privacy'}
    if re.fullmatch(r'/play/(?:roulette|blackjack|baccarat|slots|dice|keno|plinko)(?:/[a-f0-9]{32})?',path) or path in allowed or re.fullmatch(r'/product/[a-z0-9-]+',path) or re.fullmatch(r'/casino/(' + GAME_PATTERN + ')',path) or re.fullmatch(r'/(receipt|round)/[a-f0-9]{32}',path):
        if value.startswith('/') and not value.startswith('//') and not any(c in unquote(value) for c in '\\\r\n\x00') and not parsed.netloc:
            return path
    return '/shop'

def iso(value):
    return datetime.fromtimestamp(int(value),timezone.utc).strftime('%Y-%m-%d %H:%M')

def json_chunk(value): return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')

class Request:
    def __init__(self,app,env):
        self.app,self.env,self.config=app,env,app.config
        self.path=env.get('PATH_INFO','/')
        self.method=env.get('REQUEST_METHOD','GET').upper()
        self.form={};self.cookies_out=[];self.session=None;self.user=None
        self.lang='pt-br';self.db=None
        if len(env.get('QUERY_STRING',''))>2048: raise Fault(414)
        try:
            self.query={k:v[-1] for k,v in parse_qs(env.get('QUERY_STRING',''),keep_blank_values=True,max_num_fields=16).items()}
        except ValueError: raise Fault(400)
        if len(env.get('HTTP_COOKIE',''))>8192: raise Fault(400)
        cookie=SimpleCookie()
        try: cookie.load(env.get('HTTP_COOKIE',''))
        except CookieError: raise Fault(400)
        self.cookies={k:v.value for k,v in cookie.items()}
        self.lang=self.query.get('lang',self.cookies.get('dopamine_lang','pt-br'))
        if self.lang not in LANGUAGES: self.lang='pt-br'
        self.db=database.connect(self.config.database)
        self.ip=sec.client_ip(env,self.config)
        raw=self.cookies.get(self.config.cookie_name,'')
        if re.fullmatch(r'[A-Za-z0-9_-]{40,64}',raw):
            row=self.db.execute('SELECT * FROM sessions WHERE token_hash=?',(sec.digest(raw),)).fetchone()
            timestamp=sec.now()
            if row and row['expires_at']>timestamp and row['touched_at']>timestamp-self.config.idle_seconds:
                self.session=dict(row)
                if row['user_id']:
                    user=self.db.execute('SELECT * FROM users WHERE id=?',(row['user_id'],)).fetchone()
                    self.user=dict(user) if user else None
                if timestamp-row['touched_at']>300:
                    self.db.execute('UPDATE sessions SET touched_at=? WHERE token_hash=?',(timestamp,row['token_hash']))
            elif row:
                self.db.execute('DELETE FROM sessions WHERE token_hash=?',(row['token_hash'],))
        if self.user and 'lang' not in self.query and 'dopamine_lang' not in self.cookies:
            self.lang=self.user['language']

    def set_cookie(self,name,value,max_age=43200):
        c=SimpleCookie();c[name]=value
        c[name]['path']='/';c[name]['httponly']=True;c[name]['samesite']='Lax';c[name]['max-age']=str(max_age)
        if self.config.secure:c[name]['secure']=True
        self.cookies_out.append(('Set-Cookie',c[name].OutputString()))

    def ensure_session(self):
        if not self.session:
            self.rate('new-session',60,900)
            raw,self.session=sec.new_session(self.db,self.config)
            self.set_cookie(self.config.cookie_name,raw)
        return self.session

    def rotate(self,user_id=None):
        if self.session:self.db.execute('DELETE FROM sessions WHERE token_hash=?',(self.session['token_hash'],))
        raw,self.session=sec.new_session(self.db,self.config,user_id)
        self.set_cookie(self.config.cookie_name,raw)
        self.user=dict(self.db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()) if user_id else None

    def rate(self,kind,limit,window,identity=None):
        if not sec.allowed_rate(self.db,self.config,kind,identity or self.ip,limit,window):raise Fault(429,'rate_error')

    def read_form(self):
        if self.env.get('CONTENT_TYPE','').split(';')[0].lower()!='application/x-www-form-urlencoded':raise Fault(415)
        try:n=int(self.env.get('CONTENT_LENGTH',''))
        except (ValueError,TypeError):raise Fault(411)
        if n<0 or n>MAX_BODY:raise Fault(413)
        raw=self.env['wsgi.input'].read(n)
        if len(raw)!=n:raise Fault(400)
        try:
            pairs=parse_qs(raw.decode('utf-8'),keep_blank_values=True,max_num_fields=24,strict_parsing=True)
            if any(len(values)!=1 for values in pairs.values()):raise ValueError('duplicate form field')
            self.form={key:values[0] for key,values in pairs.items()}
            if self.path in {'/signup','/login','/recover'} and self.form.get('language') in LANGUAGES:
                self.lang=self.form['language']
        except (ValueError,UnicodeError):raise Fault(400)
        origin=self.env.get('HTTP_ORIGIN')
        # Form posts must keep their origin: responses use Referrer-Policy:
        # same-origin, not no-referrer (which can turn a valid Origin into null).
        # Never solve that compatibility problem by accepting arbitrary origins.
        if self.env.get('HTTP_SEC_FETCH_SITE') in {'cross-site', 'same-site'}:
            raise Fault(403,'csrf_error')
        if origin is not None and not sec.same_origin(origin,self.config.site_url):
            raise Fault(403,'csrf_error')
        supplied=self.form.get('csrf','')
        if not self.session or not re.fullmatch(r'[A-Za-z0-9_-]{43}',supplied) or not hmac.compare_digest(self.session['csrf'],supplied):raise Fault(403,'csrf_error')
        self.rate('post-global',180,60)

    def action(self,name):
        value=self.form.get('action_key','')
        if not self.session or not sec.valid_action(self.config,self.session,name,value):raise Fault(403,'csrf_error')
        return sec.digest(value)

class App:
    def __init__(self,config):
        self.config=config
        self._cleanup_lock=threading.Lock()
        self._next_cleanup=0
        catalog.validate()
        if not config.database.is_file():raise RuntimeError('Database missing. Run python manage.py init.')
        if config.require_local_photos:
            from .real_photos import verify_photos
            verify_photos()
        self.templates=Environment(loader=FileSystemLoader(ROOT/'app/templates'),autoescape=select_autoescape(['html','xml']),undefined=StrictUndefined)
        self.templates.filters['utc']=iso
        self.assets={}
        for path in (ROOT/'app/static').rglob('*'):
            if path.is_file() and path.suffix in {'.css','.js','.webp','.svg','.ico'}:
                body=path.read_bytes()
                suffix=path.suffix
                mime={'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.webp':'image/webp','.svg':'image/svg+xml','.ico':'image/x-icon'}[suffix]
                self.assets['/static/'+path.relative_to(ROOT/'app/static').as_posix()]=(path if suffix=='.webp' else body,mime,hashlib.sha256(body).hexdigest()[:24])
        js=(ROOT/'app/static/tables.js').read_bytes()
        self.js_integrity='sha384-'+base64.b64encode(hashlib.sha384(js).digest()).decode('ascii')

    def render(self,r,template,**values):
        t=lambda key:text(key,r.lang).replace('{bonus}',money(100,r.lang))
        fmt=lambda value:format(int(value),',').replace(',','.' if r.lang=='pt-br' else ',')
        def link(path,**query):
            filtered={k:v for k,v in query.items() if v not in ('',None)}
            return path+('?' + urlencode(filtered) if filtered else '')
        favorites=set();bag_count=0
        if r.user:
            favorites={row[0] for row in r.db.execute('SELECT product_id FROM favorites WHERE user_id=?',(r.user['id'],))}
            bag_count=r.db.execute('SELECT COALESCE(SUM(quantity),0) FROM cart WHERE user_id=?',(r.user['id'],)).fetchone()[0]
        common=dict(t=t,lang=r.lang,html_lang='zh-Hans' if r.lang=='zh' else r.lang,languages=LANGUAGES,
            user=r.user,csrf=r.session['csrf'] if r.session else '',path=r.path,fmt=fmt,link=link,
            categories=[{'id':c['id'],'label':c['label'][r.lang]} for c in catalog.CATEGORIES.values()],
            favorite_ids=favorites,bag_count=bag_count,version=__version__,title='Dopamine',active='shop',
            error='',notice='',contact=os.environ.get('CONTACT_EMAIL','admin@securityops.co'),
            action_key=lambda action:sec.action_token(self.config,r.ensure_session(),action),
            photo_ready=lambda key:(ROOT/'app/static/photos'/f'{key}.webp').is_file(),
            asset_version=__version__,total_products=len(catalog.PRODUCTS),
            money=lambda value:money(value,r.lang),currency=currency(r.lang),infinite_money=infinity(r.lang),
            interactive=False,table_games=tables.TABLES,js_integrity=self.js_integrity,game_options=OPTIONS,game_count=len(GAMES),nickname_value='',adult_checked=False)
        common.update(values)
        return Response(self.templates.get_template(template).render(**common).encode('utf-8'))

    def __call__(self,env,start_response):
        r=None
        try:
            path=env.get('PATH_INFO','/')
            method=env.get('REQUEST_METHOD','GET').upper()
            if method not in {'GET','HEAD','POST'}:raise Fault(405)
            host=env.get('HTTP_HOST','').lower()
            if host not in self.config.allowed_hosts:raise Fault(400)
            if not path.startswith('/') or any(x in path for x in ('\\','\x00','\r','\n')) or len(path)>512:raise Fault(400)
            if self.config.secure and path!='/healthz' and not sec.secure_request(env,self.config):
                if method=='POST':raise Fault(403,'csrf_error')
                response=Response(status=308,headers=[('Location',self.config.site_url+path)])
            elif path=='/healthz':
                if method not in {'GET','HEAD'}:raise Fault(405)
                db=database.connect(self.config.database)
                try:db.execute('SELECT 1').fetchone()
                finally:db.close()
                response=Response(b'{"status":"ok","service":"dopamine"}',content_type='application/json')
            elif path.startswith('/static/'):
                if method not in {'GET','HEAD'}:raise Fault(405)
                if path not in self.assets:raise Fault(404,'not_found')
                body,mime,tag=self.assets[path]
                hdr=[('Cache-Control','public, max-age=86400'),('ETag','"'+tag+'"')]
                if isinstance(body,Path):
                    hdr.append(('Content-Length',str(body.stat().st_size)))
                    def photo_chunks(photo=body):
                        with photo.open('rb') as stream:
                            for block in iter(lambda:stream.read(65536),b''):yield block
                    response=Response(photo_chunks(),headers=hdr,content_type=mime)
                else:response=Response(body,headers=hdr,content_type=mime)
            elif path=='/robots.txt':
                if method not in {'GET','HEAD'}:raise Fault(405)
                response=Response(b'User-agent: *\nDisallow: /profile\nDisallow: /collection\nDisallow: /receipt/\nDisallow: /round/\n',content_type='text/plain; charset=utf-8')
            else:
                r=Request.__new__(Request)
                Request.__init__(r,self,env)
                if sec.now()>=self._next_cleanup and self._cleanup_lock.acquire(blocking=False):
                    try:
                        if sec.now()>=self._next_cleanup:
                            database.cleanup(r.db,sec.now(),self.config.idle_seconds)
                            self._next_cleanup=sec.now()+600
                    finally:self._cleanup_lock.release()
                if method=='POST':r.read_form()
                response=self.dispatch(r)
        except Fault as exc:
            if r and r.db and hasattr(r,'ip'):
                if r.path in {'/signup','/login','/recover'} and exc.status in {400,403,409,429}:
                    # Reject the failed request, then offer a fresh form; do not replay POSTs.
                    if not r.session and exc.status != 429:
                        try:r.ensure_session()
                        except Fault:pass
                    response=self.render(r,'auth.html',title=text(r.path[1:],r.lang),
                        mode=r.path[1:],next_path=safe_next(r.form.get('next','/shop')),
                        error=text(exc.key,r.lang),nickname_value=r.form.get('nickname','')[:24],
                        adult_checked=r.form.get('adult')=='yes')
                else:
                    response=self.render(r,'error.html',title=text('error_title',r.lang),error=text(exc.key,r.lang),code=exc.status)
                response.status=exc.status
            else:
                response=Response(f'<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Dopamine</title><p>{exc.status} — Solicitação não concluída.</p><a href="/shop">Dopamine</a></html>'.encode(),exc.status)
            if exc.status==405:response.headers.append(('Allow','GET, HEAD, POST'))
            if exc.status==429:response.headers.append(('Retry-After','900'))
        except Exception:
            error_id=secrets.token_hex(6)
            # Never log request payloads, cookies, passwords or URLs with recovery material.
            LOG.exception('Unhandled application exception; reference=%s',error_id)
            response=Response(f'<!doctype html><meta charset="utf-8"><title>Dopamine</title><p>503 — Temporarily unavailable. Reference: {error_id}</p>'.encode(),503)
            response.headers.append(('Retry-After','30'))
        csp_script="'self'" if env.get('PATH_INFO','').startswith('/play/') else "'none'"
        headers=[('X-Dopamine-Version',__version__),('Content-Type',response.content_type),('X-Content-Type-Options','nosniff'),
            ('X-Frame-Options','DENY'),('Referrer-Policy','same-origin'),
            ('Permissions-Policy','camera=(), microphone=(), geolocation=(), payment=(), browsing-topics=()'),
            ('Content-Security-Policy',f"default-src 'none'; script-src {csp_script}; style-src 'self'; img-src 'self'; font-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; connect-src {csp_script}"),
            ('Cross-Origin-Opener-Policy','same-origin'),('Cross-Origin-Resource-Policy','same-origin')]
        if self.config.secure:headers.append(('Strict-Transport-Security','max-age=31536000'))
        if not any(k.lower()=='cache-control' for k,v in response.headers):headers.append(('Cache-Control','no-store, private'))
        headers.extend(response.headers)
        if r and hasattr(r,'cookies_out'):headers.extend(r.cookies_out)
        if isinstance(response.body,bytes):headers.append(('Content-Length',str(len(response.body))))
        try:start_response(f'{response.status} {HTTPStatus(response.status).phrase}',headers)
        except BaseException:
            if r and r.db:r.db.close()
            raise
        def chunks():
            try:
                if env.get('REQUEST_METHOD')=='HEAD':return
                if isinstance(response.body,bytes):yield response.body
                else:yield from response.body
            finally:
                if r and r.db:r.db.close()
        return chunks()

    def dispatch(self,r):
        p,m=r.path,r.method
        get=m in {'GET','HEAD'}
        if p=='/':return redirect('/shop')
        if p=='/language' and get:
            language=r.query.get('lang','pt-br')
            if language not in LANGUAGES:raise Fault(400)
            r.set_cookie('dopamine_lang',language,31536000)
            return redirect(safe_next(r.query.get('next','/shop')))
        if p in {'/login','/signup','/recover'}:return self.auth(r)
        if p=='/javascript' and get:return self.render(r,'javascript.html',title=text('js_source',r.lang),active='about')
        if p.startswith('/play/'):
            match=re.fullmatch(r'/play/('+ '|'.join(tables.TABLES)+r')(?:/([a-f0-9]{32}))?',p)
            if not match:raise Fault(404,'not_found')
            if not r.user:return redirect('/login?'+urlencode({'next':safe_next(p)}))
            return self.practice_table(r,match[1],match[2])
        if p=='/shop' and get:return self.shop(r)
        if p=='/science' and get:return self.render(r,'science.html',title=text('science',r.lang),active='science',papers=content.papers(r.lang))
        if p=='/about' and get:return self.render(r,'about.html',title=text('about',r.lang),active='about',photos=catalog.PHOTOS)
        if p=='/privacy' and get:return self.render(r,'privacy.html',title=text('privacy',r.lang),active='about',sections=content.privacy(r.lang))
        if p=='/casino' and get:return self.render(r,'casino.html',title=text('casino',r.lang),active='casino',games=GAMES)
        match=re.fullmatch(r'/product/([a-z0-9-]+)',p)
        if match and get:
            product=self.product(match[1],r.lang)
            return self.render(r,'product.html',product=product,title=product['name'],related=[x for x in catalog.select(r.lang,product['category']) if x['id']!=product['id']][:4])
        # Reject unknown routes before redirecting account-bound views to login.
        protected={'/logout','/profile','/profile/password','/profile/export','/profile/delete','/cart','/checkout','/catalog/all','/collection','/casino/pause'}
        pattern=r'/(?:buy|favorite|bag)/[a-z0-9-]+|/(?:receipt|round)/[a-f0-9]{32}|/casino/(?:'+GAME_PATTERN+')'
        if p not in protected and not re.fullmatch(pattern,p):raise Fault(404,'not_found')
        if get and (p in {'/logout','/checkout','/profile/export','/profile/delete','/profile/password','/catalog/all','/casino/pause'} or re.fullmatch(r'/(buy|favorite|bag)/[a-z0-9-]+',p)):raise Fault(405)
        if not r.user:return redirect('/login?'+urlencode({'next':safe_next(p)}))
        if p=='/logout' and m=='POST':
            r.rotate();return redirect('/shop')
        if p=='/profile':return self.profile(r)
        if p=='/profile/password' and m=='POST':return self.change_password(r)
        if p=='/profile/export' and m=='POST':return self.export(r)
        if p=='/profile/delete' and m=='POST':return self.delete_account(r)
        if p=='/cart':return self.cart(r)
        if p=='/checkout' and m=='POST':return self.checkout(r)
        if p=='/catalog/all' and m=='POST':
            r.action('catalog-all');r.rate('catalog-all',10,60,str(r.user['id']))
            with database.atomic(r.db):
                r.db.executemany('INSERT INTO cart(user_id,product_id,quantity) VALUES(?,?,1) ON CONFLICT(user_id,product_id) DO NOTHING',[(r.user['id'],pid) for pid in catalog.PRODUCTS])
            return redirect('/cart?notice=bag_added')
        match=re.fullmatch(r'/(buy|favorite|bag)/([a-z0-9-]+)',p)
        if match and m=='POST':return self.product_action(r,match[1],match[2])
        if p=='/collection' and get:return self.collection(r)
        match=re.fullmatch(r'/receipt/([a-f0-9]{32})',p)
        if match and get:return self.receipt(r,match[1])
        if p=='/casino/pause' and m=='POST':return self.pause(r)
        match=re.fullmatch(r'/casino/('+GAME_PATTERN+')',p)
        if match:return self.game(r,match[1])
        match=re.fullmatch(r'/round/([a-f0-9]{32})',p)
        if match and get:
            row=r.db.execute('SELECT * FROM all_rounds WHERE id=? AND user_id=?',(match[1],r.user['id'])).fetchone()
            if not row:raise Fault(404,'not_found')
            return self.render(r,'round.html',title=text('round_done',r.lang),active='casino',round=dict(row),result=json.loads(row['result_json']))
        if get and p in {'/logout','/checkout','/profile/export','/profile/delete','/profile/password','/catalog/all','/casino/pause'}:raise Fault(405)
        raise Fault(404,'not_found')

    def product(self,pid,lang):
        if pid not in catalog.PRODUCTS:raise Fault(404,'not_found')
        return catalog.localize(catalog.PRODUCTS[pid],lang)

    def auth(self,r):
        mode=r.path[1:]
        if r.method == 'POST' and r.form.get('language') in LANGUAGES:
            r.lang = r.form['language']
        r.ensure_session()
        nxt=safe_next(r.query.get('next',r.form.get('next','/shop')))
        if r.method in {'GET','HEAD'}:
            if r.user and mode in {'login','signup'}:return redirect(nxt)
            return self.render(r,'auth.html',title=text(mode,r.lang),mode=mode,next_path=nxt)
        r.rate('auth-ip',30,900)
        nickname_input=r.form.get('nickname','')
        try:nickname,key=sec.clean_nickname(nickname_input)
        except ValueError:
            if mode=='signup':raise Fault(400,'nickname_invalid')
            nickname,key='','__invalid__'
        r.rate('auth-name',10,900,key)
        password=r.form.get('password','')
        if mode=='signup':
            if r.form.get('adult')!='yes':raise Fault(400,'adult_required')
            if sec.password_error(password):raise Fault(400,'password_invalid')
            r.rate('signup',10,3600)
            recovery=sec.token()
            stored=sec.PH.hash(password)
            try:
                with database.atomic(r.db):
                    cursor=r.db.execute('INSERT INTO users(nickname,nickname_key,password_hash,recovery_hash,language,adult_confirmed,created_at) VALUES(?,?,?,?,?,1,?)',
                        (nickname,key,stored,sec.keyed(r.config.secret,'recovery',recovery),r.lang,sec.now()))
                    uid=cursor.lastrowid
                    r.rotate(uid)
            except sqlite3.IntegrityError:raise Fault(409,'nickname_taken')
            return self.render(r,'recovery_key.html',title=text('recovery_title',r.lang),recovery=recovery,next_path=nxt)
        user=r.db.execute('SELECT * FROM users WHERE nickname_key=?',(key,)).fetchone()
        if mode=='login':
            if not sec.verify(user['password_hash'] if user else None,password) or not user:raise Fault(400,'credentials_invalid')
            replacement=sec.PH.hash(password) if sec.PH.check_needs_rehash(user['password_hash']) else None
            with database.atomic(r.db):
                current=r.db.execute('SELECT password_hash FROM users WHERE id=?',(user['id'],)).fetchone()
                # A reset during the expensive hash verification must not resurrect a session.
                if not current or not hmac.compare_digest(current[0],user['password_hash']):raise Fault(400,'credentials_invalid')
                if replacement:r.db.execute('UPDATE users SET password_hash=? WHERE id=?',(replacement,user['id']))
                r.rotate(user['id'])
            return redirect(nxt)
        if mode=='recover':
            recovery=r.form.get('recovery_code','').strip()
            if len(recovery)>128:raise Fault(400,'recovery_invalid')
            valid=hmac.compare_digest(sec.keyed(r.config.secret,'recovery',recovery),user['recovery_hash'] if user else '0'*64)
            if not valid or not user:raise Fault(400,'recovery_invalid')
            if sec.password_error(password):raise Fault(400,'password_invalid')
            fresh=sec.token();newhash=sec.PH.hash(password)
            with database.atomic(r.db):
                current=r.db.execute('SELECT recovery_hash FROM users WHERE id=?',(user['id'],)).fetchone()
                if not current or not hmac.compare_digest(current[0],sec.keyed(r.config.secret,'recovery',recovery)):raise Fault(400,'recovery_invalid')
                r.db.execute('UPDATE users SET password_hash=?,recovery_hash=? WHERE id=?',(newhash,sec.keyed(r.config.secret,'recovery',fresh),user['id']))
                r.db.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
                r.rotate(user['id'])
            return self.render(r,'recovery_key.html',title=text('recovery_title',r.lang),recovery=fresh,next_path='/profile')
        raise Fault(404,'not_found')

    def shop(self,r):
        cat=r.query.get('category','');q=r.query.get('q','').strip();sort=r.query.get('sort','curated')
        if len(q)>100 or (cat and cat not in catalog.CATEGORIES):raise Fault(400)
        favs=None
        if r.query.get('favorites')=='1':
            if not r.user:return redirect('/login?next=/shop')
            favs={row[0] for row in r.db.execute('SELECT product_id FROM favorites WHERE user_id=?',(r.user['id'],))}
        results=catalog.select(r.lang,cat,q,sort,favs)
        page=integer(r.query.get('page','1'),1,100000);total_pages=max(1,math.ceil(len(results)/16));page=min(page,total_pages)
        return self.render(r,'shop.html',products=results[(page-1)*16:page*16],category=cat,q=q,sort=sort,
            page=page,total_pages=total_pages,total=len(results),favorite_mode=favs is not None,
            show_hero=not(cat or q or favs is not None) and page==1)

    def product_action(self,r,kind,pid):
        self.product(pid,r.lang);uid=r.user['id']
        r.rate('shopping',90,60,str(uid))
        if kind=='favorite':
            if r.form.get('mode')=='remove':r.db.execute('DELETE FROM favorites WHERE user_id=? AND product_id=?',(uid,pid))
            else:r.db.execute('INSERT OR IGNORE INTO favorites(user_id,product_id) VALUES(?,?)',(uid,pid))
            return redirect('/product/'+pid)
        quantity=integer(r.form.get('quantity','1'),1,99)
        if kind=='bag':
            # Replace quantity deliberately: retrying the same form cannot double it.
            r.db.execute('INSERT INTO cart(user_id,product_id,quantity) VALUES(?,?,?) ON CONFLICT(user_id,product_id) DO UPDATE SET quantity=excluded.quantity',(uid,pid,quantity))
            return redirect('/cart?notice=bag_added')
        if kind=='buy':
            key=r.action('buy:'+pid)
            oid=self.make_purchase(r,key,[(pid,quantity)])
            return redirect('/receipt/'+oid)
        raise Fault(404,'not_found')

    def cart_rows(self,r):
        result=[]
        for row in r.db.execute('SELECT product_id,quantity FROM cart WHERE user_id=? ORDER BY product_id',(r.user['id'],)):
            if row['product_id'] in catalog.PRODUCTS:
                p=self.product(row['product_id'],r.lang);p['quantity']=row['quantity'];p['subtotal']=p['credits']*row['quantity'];result.append(p)
        return result

    def cart(self,r):
        if r.method=='POST':
            pid=r.form.get('product_id','');self.product(pid,r.lang)
            if r.form.get('mode')=='remove':r.db.execute('DELETE FROM cart WHERE user_id=? AND product_id=?',(r.user['id'],pid))
            else:
                quantity=integer(r.form.get('quantity','1'),1,99)
                r.db.execute('UPDATE cart SET quantity=? WHERE user_id=? AND product_id=?',(quantity,r.user['id'],pid))
            return redirect('/cart')
        rows=self.cart_rows(r)
        return self.render(r,'cart.html',title=text('cart',r.lang),rows=rows,total=sum(x['subtotal'] for x in rows),
            notice=text('bag_added',r.lang) if r.query.get('notice')=='bag_added' else '')

    def make_purchase(self,r,key,items,clear_cart=False):
        with database.atomic(r.db):
            prior=r.db.execute('SELECT id FROM purchases WHERE user_id=? AND request_key=?',(r.user['id'],key)).fetchone()
            if prior:return prior['id']
            if clear_cart:items=[(row['product_id'],row['quantity']) for row in r.db.execute('SELECT * FROM cart WHERE user_id=?',(r.user['id'],))]
            items=[(pid,q) for pid,q in items if pid in catalog.PRODUCTS]
            if not items:raise Fault(400)
            oid=uuid.uuid4().hex
            r.db.execute('INSERT INTO purchases(id,user_id,request_key,created_at) VALUES(?,?,?,?)',(oid,r.user['id'],key,sec.now()))
            r.db.executemany('INSERT INTO purchase_items(purchase_id,product_id,quantity,unit_credits) VALUES(?,?,?,?)',
                [(oid,pid,q,catalog.PRODUCTS[pid]['credits']) for pid,q in items])
            if clear_cart:r.db.execute('DELETE FROM cart WHERE user_id=?',(r.user['id'],))
        return oid

    def checkout(self,r):
        key=r.action('checkout');r.rate('checkout',30,60,str(r.user['id']))
        return redirect('/receipt/'+self.make_purchase(r,key,[],True))

    def receipt(self,r,oid):
        order=r.db.execute('SELECT * FROM purchases WHERE id=? AND user_id=?',(oid,r.user['id'])).fetchone()
        if not order:raise Fault(404,'not_found')
        items=[]
        for row in r.db.execute('SELECT * FROM purchase_items WHERE purchase_id=?',(oid,)):
            p=catalog.historical(row['product_id'],r.lang)
            p.update(quantity=row['quantity'],credits=row['unit_credits'],subtotal=row['quantity']*row['unit_credits']);items.append(p)
        return self.render(r,'receipt.html',title=text('receipt',r.lang),order=dict(order),items=items,total=sum(x['subtotal'] for x in items))

    def collection(self,r):
        uid=r.user['id'];page=integer(r.query.get('page','1'),1,100000)
        count=r.db.execute('SELECT COUNT(*) FROM purchases WHERE user_id=?',(uid,)).fetchone()[0]
        pages=max(1,math.ceil(count/20));page=min(page,pages)
        orders=[dict(x) for x in r.db.execute('SELECT p.id,p.created_at,SUM(i.quantity) AS units,SUM(i.quantity*i.unit_credits) AS credits FROM purchases p JOIN purchase_items i ON i.purchase_id=p.id WHERE p.user_id=? GROUP BY p.id ORDER BY p.created_at DESC,p.id DESC LIMIT 20 OFFSET ?',(uid,(page-1)*20))]
        acquired=[]
        for row in r.db.execute('SELECT i.product_id,SUM(i.quantity) AS units FROM purchase_items i JOIN purchases p ON p.id=i.purchase_id WHERE p.user_id=? GROUP BY i.product_id ORDER BY MAX(p.created_at) DESC LIMIT 16',(uid,)):
            if row['product_id'] in catalog.PRODUCTS:
                p=self.product(row['product_id'],r.lang);p['units']=row['units'];acquired.append(p)
        rounds=[dict(x) for x in r.db.execute('SELECT * FROM all_rounds WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 20',(uid,))]
        live_rounds=[dict(x) for x in r.db.execute('SELECT id,game,created_at,completed FROM interactive_rounds WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 20',(uid,))]
        live_bonus=r.db.execute('SELECT COUNT(*)*100 FROM interactive_rounds WHERE user_id=? AND completed=1',(uid,)).fetchone()[0]
        bonus=r.db.execute('SELECT COALESCE(SUM(bonus),0) FROM all_rounds WHERE user_id=?',(uid,)).fetchone()[0]
        return self.render(r,'collection.html',title=text('collection',r.lang),active='collection',orders=orders,acquired=acquired,rounds=rounds,live_rounds=live_rounds,bonus=bonus+live_bonus,page=page,total_pages=pages)

    def profile(self,r):
        if r.method=='POST':
            fields={key:r.form.get(key,'').strip() for key in ('display_name','country','bio')}
            if len(fields['display_name'])>60 or len(fields['country'])>60 or len(fields['bio'])>280:raise Fault(400)
            if any('\x00' in v for v in fields.values()):raise Fault(400)
            lang=r.form.get('language','pt-br')
            if lang not in LANGUAGES:raise Fault(400)
            r.db.execute('UPDATE users SET display_name=?,country=?,bio=?,language=?,reduced_motion=?,casino_hidden=? WHERE id=?',
                (fields['display_name'],fields['country'],fields['bio'],lang,int(r.form.get('reduced_motion')=='yes'),int(r.form.get('casino_hidden')=='yes'),r.user['id']))
            r.set_cookie('dopamine_lang',lang,31536000)
            return redirect('/profile?notice=saved')
        return self.render(r,'profile.html',title=text('profile',r.lang),active='profile',notice=text('saved',r.lang) if r.query.get('notice')=='saved' else '')

    def reauth(self,r):
        r.rate('reauth',8,900,str(r.user['id']))
        current=r.db.execute('SELECT password_hash FROM users WHERE id=?',(r.user['id'],)).fetchone()
        if not sec.verify(current[0] if current else None,r.form.get('current_password','')) or not current:raise Fault(400,'credentials_invalid')
        return current[0]

    def change_password(self,r):
        verified=self.reauth(r);new=r.form.get('new_password','')
        if sec.password_error(new):raise Fault(400,'password_invalid')
        stored=sec.PH.hash(new)
        with database.atomic(r.db):
            current=r.db.execute('SELECT password_hash FROM users WHERE id=?',(r.user['id'],)).fetchone()
            if not current or not hmac.compare_digest(current[0],verified):raise Fault(400,'credentials_invalid')
            r.db.execute('UPDATE users SET password_hash=? WHERE id=?',(stored,r.user['id']))
            r.db.execute('DELETE FROM sessions WHERE user_id=?',(r.user['id'],))
            r.rotate(r.user['id'])
        return redirect('/profile?notice=saved')

    def export(self,r):
        self.reauth(r)
        public_keys=('id','nickname','display_name','bio','country','language','reduced_motion','casino_hidden','excluded_until','adult_confirmed','created_at')
        public={key:r.user[key] for key in public_keys}
        uid=r.user['id']
        # Stream row-by-row so years of account history need not fit in RAM.
        def generate():
            yield b'{"fictional":true,"amounts_are_symbolic_units":true,"display_currency":'+json_chunk(currency(r.lang).code)+b',"profile":'+json_chunk(public)
            queries={
                'purchases':('SELECT id,created_at FROM purchases WHERE user_id=?',(uid,)),
                'purchase_items':('SELECT i.purchase_id,i.product_id,i.quantity,i.unit_credits FROM purchase_items i JOIN purchases p ON p.id=i.purchase_id WHERE p.user_id=?',(uid,)),
                'favorites':('SELECT product_id FROM favorites WHERE user_id=?',(uid,)),
                'cart':('SELECT product_id,quantity FROM cart WHERE user_id=?',(uid,)),
                'rounds':('SELECT id,game,stake,bonus,created_at,result_json FROM all_rounds WHERE user_id=?',(uid,))}
            for key,(sql,args) in queries.items():
                yield b','+json_chunk(key)+b':['
                first=True
                for row in r.db.execute(sql,args):
                    if not first:yield b','
                    yield json_chunk(dict(row));first=False
                yield b']'
            yield b',"interactive_rounds":['
            first=True
            for row in r.db.execute('SELECT id,game,created_at,state_json FROM interactive_rounds WHERE user_id=? ORDER BY created_at,id',(uid,)):
                if not first:yield b','
                yield json_chunk({'id':row['id'],'game':row['game'],'created_at':row['created_at'],'state':tables.public(json.loads(row['state_json']))});first=False
            yield b']}'
        return Response(generate(),headers=[('Content-Disposition','attachment; filename="dopamine-my-data.json"')],content_type='application/json; charset=utf-8')

    def delete_account(self,r):
        self.reauth(r)
        if r.form.get('confirm')!='yes':raise Fault(400)
        with database.atomic(r.db):r.db.execute('DELETE FROM users WHERE id=?',(r.user['id'],))
        r.user=None;r.session=None
        r.set_cookie(r.config.cookie_name,'',0)
        return redirect('/shop')

    def blocked(self,r,user=None):
        u=user or r.user
        return bool(u and (u['casino_hidden'] or u['excluded_until']>sec.now()))

    def game(self,r,game):
        if self.blocked(r):raise Fault(403,'blocked')
        if r.method in {'GET','HEAD'}:return self.render(r,'game.html',title=text(game,r.lang),active='casino',game=game)
        key=r.action('game:'+game)
        stake=integer(r.form.get('stake','100'),100,1000)
        if stake not in (100,500,1000):raise Fault(400)
        try:result=result_for(game,r.form)
        except ValueError:raise Fault(400,'game_choice_invalid')
        table='rounds' if game in LEGACY_GAMES else 'extra_rounds'
        r.rate('casino-account',12,60,str(r.user['id']));r.rate('casino-ip',30,60)
        with database.atomic(r.db):
            # Re-read the block while holding the writer lock: a concurrent pause wins.
            current=r.db.execute('SELECT casino_hidden,excluded_until FROM users WHERE id=?',(r.user['id'],)).fetchone()
            if not current or self.blocked(r,current):raise Fault(403,'blocked')
            previous=r.db.execute('SELECT id FROM all_rounds WHERE user_id=? AND request_key=?',(r.user['id'],key)).fetchone()
            if previous:rid=previous['id']
            else:
                rid=uuid.uuid4().hex
                r.db.execute('INSERT INTO '+table+'(id,user_id,game,request_key,stake,bonus,created_at,result_json) VALUES(?,?,?,?,?,100,?,?)',
                    (rid,r.user['id'],game,key,stake,sec.now(),json.dumps(result,ensure_ascii=False,separators=(',',':'))))
        return redirect('/round/'+rid)

    def practice_table(self,r,game,rid=None):
        if self.blocked(r):raise Fault(403,'blocked')
        uid=r.user['id'];row=None
        if r.method=='POST':
            action=r.form.get('move','start')
            namespace='table:'+game+(':'+rid if rid else '')
            key=r.action(namespace)
            r.rate('table-account',40,60,str(uid));r.rate('table-ip',60,60)
            if rid is None:r.rate('table-start',12,60,str(uid))
            with database.atomic(r.db):
                current=r.db.execute('SELECT casino_hidden,excluded_until FROM users WHERE id=?',(uid,)).fetchone()
                if not current or self.blocked(r,current):raise Fault(403,'blocked')
                if rid:
                    row=r.db.execute('SELECT * FROM interactive_rounds WHERE id=? AND user_id=? AND game=?',(rid,uid,game)).fetchone()
                    if not row:raise Fault(404,'not_found')
                    replay=r.db.execute('SELECT 1 FROM interactive_actions WHERE round_id=? AND request_key=?',(rid,key)).fetchone()
                    if not replay:
                        revision=integer(r.form.get('revision',''),0,1000)
                        if revision!=row['revision']:raise Fault(409,'stale_round')
                        try:state=tables.move(json.loads(row['state_json']),action)
                        except tables.InvalidMove:raise Fault(400,'game_choice_invalid')
                        r.db.execute('UPDATE interactive_rounds SET state_json=?,revision=revision+1,completed=? WHERE id=?',(json.dumps(state,ensure_ascii=False),int(state['completed']),rid))
                        r.db.execute('INSERT INTO interactive_actions(round_id,request_key) VALUES(?,?)',(rid,key))
                else:
                    if action!='start':raise Fault(400)
                    previous=r.db.execute('SELECT id FROM interactive_rounds WHERE user_id=? AND request_key=?',(uid,key)).fetchone()
                    active=r.db.execute('SELECT id FROM interactive_rounds WHERE user_id=? AND game=? AND completed=0',(uid,game)).fetchone()
                    if previous or active:rid=(previous or active)['id']
                    else:
                        stake=integer(r.form.get('stake','100'),100,1000)
                        try:state=tables.start(game,stake,r.form)
                        except tables.InvalidMove:raise Fault(400,'game_choice_invalid')
                        rid=uuid.uuid4().hex
                        r.db.execute('INSERT INTO interactive_rounds(id,user_id,game,request_key,completed,state_json,created_at) VALUES(?,?,?,?,?,?,?)',(rid,uid,game,key,int(state['completed']),json.dumps(state,ensure_ascii=False),sec.now()))
            location='/play/'+game+'/'+rid
            if r.env.get('HTTP_ACCEPT')!='application/json':return redirect(location)
        if rid:
            row=r.db.execute('SELECT * FROM interactive_rounds WHERE id=? AND user_id=? AND game=?',(rid,uid,game)).fetchone()
            if not row:raise Fault(404,'not_found')
        else:
            row=r.db.execute('SELECT * FROM interactive_rounds WHERE user_id=? AND game=? AND completed=0 ORDER BY created_at DESC LIMIT 1',(uid,game)).fetchone()
            if not row and r.query.get('new')!='1':
                row=r.db.execute('SELECT * FROM interactive_rounds WHERE user_id=? AND game=? ORDER BY created_at DESC,id DESC LIMIT 1',(uid,game)).fetchone()
            if row:rid=row['id']
        state=tables.public(json.loads(row['state_json'])) if row else None
        values=dict(title=text('live_'+game,r.lang),active='casino',interactive=True,game=game,
                    state=state,round_id=rid or '',revision=row['revision'] if row else 0,wheel=tables.WHEEL,
                    post_url='/play/'+game+('/'+rid if rid else ''),numbers=range(1,41))
        if r.method=='POST' and r.env.get('HTTP_ACCEPT')=='application/json':
            fragment=self.render(r,'_table.html',**values)
            return Response(json_chunk({'html':fragment.body.decode(),'url':'/play/'+game+'/'+rid}),content_type='application/json; charset=utf-8')
        return self.render(r,'table.html',**values)

    def pause(self,r):
        days=integer(r.form.get('days','1'),1,7)
        if days not in (1,7):raise Fault(400)
        until=sec.now()+days*86400
        r.db.execute('UPDATE users SET excluded_until=MAX(excluded_until,?) WHERE id=?',(until,r.user['id']))
        return redirect('/profile?notice=saved')

_instance=None
_instance_lock=threading.Lock()
def application(environ,start_response):
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:_instance=App(Config.from_env())
    return _instance(environ,start_response)

def create_app():
    """Gunicorn factory: initialize assets before forking, never persist open DB handles."""
    return App(Config.from_env())
