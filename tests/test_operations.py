from contextlib import closing
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import io
import json
import sqlite3
import unittest
from app import db
from app.photos import allowed_url,fetch_photo,is_webp,import_photos,verify_photos,MAX_IMAGE_BYTES
from manage import backup_database
from scripts.deploy import read_env,write_env,validate_values

# Container-level signature fixture, not a publishable photograph.
# Photo import checks transport, length, WebP container signature and SHA-256;
# image composition/subject matter still needs a human review of the real sources.
PAYLOAD=b'WEBPVP8 '+(4).to_bytes(4,'little')+b'abcd'
BLOB=b'RIFF'+len(PAYLOAD).to_bytes(4,'little')+PAYLOAD
URL='https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?fm=webp'

class FakeResponse(io.BytesIO):
    def __init__(self,blob=BLOB,url=URL,kind='image/webp',status=200):
        super().__init__(blob);self.url=url;self.status=status;self.headers=Message()
        self.headers['Content-Type']=kind;self.headers['Content-Length']=str(len(blob))
    def geturl(self):return self.url
class FakeOpener:
    def __init__(self,**kwargs):self.kwargs=kwargs
    def open(self,*args,**kwargs):return FakeResponse(**self.kwargs)

class OperationsTests(unittest.TestCase):
    def test_photo_allowlist_blocks_unsafe_urls(self):
        self.assertTrue(allowed_url(URL))
        for url in ('http://images.unsplash.com/photo-1-a','file:///etc/passwd','https://images.unsplash.com.evil.invalid/photo-1-a',
                    'https://user@images.unsplash.com/photo-1-a','https://127.0.0.1/photo-1-a',
                    'https://images.unsplash.com:8080/photo-1-a','https://images.unsplash.com/../secret'):
            self.assertFalse(allowed_url(url),url)
            with self.assertRaises(ValueError):fetch_photo(url,FakeOpener())
    def test_photo_fetch_checks_type_size_redirect_and_signature(self):
        self.assertEqual(fetch_photo(URL,FakeOpener()),BLOB)
        for kwargs in ({'kind':'text/html'},{'blob':b'not a photo'},{'url':'https://evil.invalid/image.webp'},
                       {'blob':b'X'*(MAX_IMAGE_BYTES+1)},{'status':404},{'blob':BLOB[:-1]}):
            with self.assertRaises(ValueError):fetch_photo(URL,FakeOpener(**kwargs))
    def test_photo_import_reports_category_fallback_and_verifies_hashes(self):
        with TemporaryDirectory() as name:
            root=Path(name);(root/'data').mkdir()
            one=dict(url=URL,original=URL.split('?')[0],provider='Unsplash',license='https://unsplash.com/license',category='cars',description={})
            two=dict(one,url=URL.replace('1492144534655','1503376780353'))
            (root/'data/photos.json').write_text(json.dumps({'cars-1':one,'cars-2':two}))
            def fetch(url):
                if url!=URL:raise OSError('offline example')
                return BLOB
            with patch('app.photos.fetch_photo',side_effect=fetch),patch('app.photos.time.sleep'):
                report=import_photos(root)
            self.assertEqual(report['cars-2']['source_key'],'cars-1')
            self.assertEqual(verify_photos(root),2)
            (root/'app/static/photos/cars-1.webp').write_bytes(BLOB+b'bad')
            with self.assertRaises(RuntimeError):verify_photos(root)
    def test_photo_import_fails_when_a_category_has_no_photo(self):
        with TemporaryDirectory() as name:
            root=Path(name);(root/'data').mkdir()
            (root/'data/photos.json').write_text(json.dumps({'cars-1':dict(url=URL,category='cars')}))
            with patch('app.photos.fetch_photo',side_effect=OSError('offline')),patch('app.photos.time.sleep'):
                with self.assertRaises(RuntimeError):import_photos(root)
    def test_online_database_backup_integrity_and_no_overwrite(self):
        with TemporaryDirectory() as name:
            source=Path(name)/'db.sqlite3';target=Path(name)/'copy.sqlite3';db.initialize(source)
            with closing(db.connect(source)) as conn:conn.execute("INSERT INTO rate_limits VALUES('test',1,2)")
            backup_database(source,target)
            with closing(sqlite3.connect(target)) as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM rate_limits').fetchone()[0],1)
            self.assertEqual(target.stat().st_mode&0o777,0o600)
            with self.assertRaises(RuntimeError):backup_database(source,target)
            with self.assertRaises(RuntimeError):backup_database(source,source)
    def test_env_is_private_roundtrips_and_rejects_symlinks(self):
        with TemporaryDirectory() as name:
            path=Path(name)/'.env'
            values=dict(SECRET_KEY='a'*64,SITE_URL='https://dopamine.securityops.co',ALLOWED_HOSTS='dopamine.securityops.co',
                        PROXY_NETWORK='dopamine-proxy',CONTACT_EMAIL='admin@securityops.co')
            validate_values(values);write_env(path,values)
            self.assertEqual(read_env(path),values)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            link=Path(name)/'link';link.symlink_to(path)
            with self.assertRaises(RuntimeError):read_env(link)
            with self.assertRaises(RuntimeError):write_env(link,values)
    def test_env_rejects_insecure_public_settings(self):
        values=dict(SECRET_KEY='a'*64,SITE_URL='https://dopamine.securityops.co',ALLOWED_HOSTS='dopamine.securityops.co',
                    PROXY_NETWORK='dopamine-proxy',CONTACT_EMAIL='admin@securityops.co')
        for changes in ({'SECRET_KEY':'CHANGE'}, {'SITE_URL':'http://dopamine.securityops.co'},
                        {'ALLOWED_HOSTS':'*'}, {'PROXY_NETWORK':'not a network'}, {'CONTACT_EMAIL':'<script>'}):
            with self.assertRaises(RuntimeError):validate_values(dict(values,**changes))
