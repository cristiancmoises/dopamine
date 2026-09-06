from dataclasses import dataclass
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from urllib.parse import urlencode,urlsplit
from wsgiref.util import setup_testing_defaults
import io

class Forms(HTMLParser):
    def __init__(self,html):
        super().__init__(convert_charrefs=True);self.forms=[];self.current=None;self.feed(html)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form':self.current={'action':a.get('action',''),'inputs':{}}
        elif tag=='input' and self.current is not None:
            if a.get('name') and a.get('type')=='hidden':self.current['inputs'][a['name']]=a.get('value','')
    def handle_endtag(self,tag):
        if tag=='form' and self.current is not None:self.forms.append(self.current);self.current=None

@dataclass
class Result:
    status:int
    headers:list
    body:bytes
    @property
    def text(self):return self.body.decode('utf-8')
    @property
    def location(self):return self.header('Location')
    def header(self,key):return next((v for k,v in self.headers if k.lower()==key.lower()),None)
    def form(self,action):
        for form in Forms(self.text).forms:
            if form['action']==action:return dict(form['inputs'])
        raise AssertionError('Form not found: '+action)

class Client:
    def __init__(self,app,ip='203.0.113.40',cookies=None):
        self.app=app;self.cookies=dict(cookies or {});self.ip=ip;self.last=None
    def request(self,path,method='GET',data=None,headers=None,raw=None,content_type=None):
        e={};setup_testing_defaults(e)
        parsed=urlsplit(path)
        e.update(PATH_INFO=parsed.path,QUERY_STRING=parsed.query,REQUEST_METHOD=method,
                 HTTP_HOST='localhost',REMOTE_ADDR=self.ip,SERVER_NAME='localhost',SERVER_PORT='80')
        if self.cookies:e['HTTP_COOKIE']='; '.join(k+'='+v for k,v in self.cookies.items())
        if method=='POST':
            body=raw if raw is not None else urlencode(data or {}).encode()
            e.update(CONTENT_TYPE=content_type or 'application/x-www-form-urlencoded',
                     CONTENT_LENGTH=str(len(body)),HTTP_ORIGIN='http://localhost')
            e['wsgi.input']=io.BytesIO(body)
        for key,value in (headers or {}).items():
            if value is None:e.pop(key,None)
            else:e[key]=value
        captured=[]
        stream=self.app(e,lambda status,hs:captured.append((int(status.split()[0]),hs)))
        try:body=b''.join(stream)
        finally:
            if hasattr(stream,'close'):stream.close()
        status,hs=captured[0]
        for name,value in hs:
            if name.lower()=='set-cookie':
                cookie=SimpleCookie();cookie.load(value)
                for key,m in cookie.items():
                    if m['max-age']=='0':self.cookies.pop(key,None)
                    else:self.cookies[key]=m.value
        self.last=Result(status,hs,body)
        return self.last
    def get(self,path,**kwargs):return self.request(path,**kwargs)
    def post(self,path,data=None,**kwargs):return self.request(path,'POST',data,**kwargs)
    def submit(self,page,action,**values):
        form=page.form(action);form.update(values)
        return self.post(action,form)
