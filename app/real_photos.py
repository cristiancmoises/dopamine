"""Build-time Wikimedia catalog; no runtime image proxy and no category fallback.

Candidates are not inventory. A candidate enters catalog-live.json only after an
exact article, model/name evidence, an allowed Commons license, a valid decoded
image and uniqueness checks pass. Metadata matching is not a human visual audit.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, unquote, quote
from urllib.request import Request, HTTPRedirectHandler, build_opener
import hashlib
import os
import shutil
import json
import re
import time
import unicodedata
import warnings
from PIL import Image, ImageOps
from .config import ROOT

API_HOSTS = {'en.wikipedia.org', 'commons.wikimedia.org'}
USER_AGENT = 'DopamineCatalog/1.2 (fictional educational collection; admin@securityops.co)'
MAX_BYTES = 6 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 16_000_000
LICENSES = {
    **{f'cc-by-{v}': f'https://creativecommons.org/licenses/by/{v}/' for v in ('1.0','2.0','2.5','3.0','4.0')},
    **{f'cc-by-sa-{v}': f'https://creativecommons.org/licenses/by-sa/{v}/' for v in ('1.0','2.0','2.5','3.0','4.0')},
    'cc0': 'https://creativecommons.org/publicdomain/zero/1.0/',
    'pd': 'https://creativecommons.org/publicdomain/mark/1.0/',
}

class CatalogError(RuntimeError): pass
class PlainText(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.parts=[]
    def handle_data(self,data): self.parts.append(data)

def plain(value):
    parser=PlainText(); parser.feed(str(value)[:50000]); return ' '.join(' '.join(parser.parts).split())[:4000]

def normal(value):
    value=unicodedata.normalize('NFKD',value).casefold().replace('α','alpha')
    return re.sub(r'[^a-z0-9]+',' ',''.join(c for c in value if not unicodedata.combining(c))).strip()

def sha(data): return hashlib.sha256(data).hexdigest()

def allowed_url(url, api=False):
    try:
        p=urlsplit(url)
        if p.scheme!='https' or p.port not in (None,443) or p.username or p.password or p.fragment:return False
        if api:return p.hostname in API_HOSTS and p.path=='/w/api.php'
        return p.hostname in {'upload.wikimedia.org','thumb.wikimedia.org'} and p.path.startswith('/wikipedia/commons/') and p.path.lower().endswith(('.jpg','.jpeg','.png','.webp'))
    except (TypeError,ValueError):return False

class RestrictedRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        api=urlsplit(req.full_url).hostname in API_HOSTS
        if not allowed_url(newurl,api):raise CatalogError('Redirect outside approved Wikimedia hosts')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url,api=False):
    if not allowed_url(url,api):raise CatalogError('Non-allowlisted source URL')
    for attempt in range(3):
        try:
            req=Request(url,headers={'User-Agent':USER_AGENT,'Accept-Encoding':'identity'})
            with build_opener(RestrictedRedirect()).open(req,timeout=25) as r:
                if r.status!=200 or not allowed_url(r.geturl(),api):raise CatalogError('Unexpected source response')
                length=r.headers.get('Content-Length')
                if length and int(length)>MAX_BYTES:raise CatalogError('Source exceeds byte limit')
                data=r.read(MAX_BYTES+1)
                if len(data)>MAX_BYTES:raise CatalogError('Source exceeds byte limit')
                if api and r.headers.get_content_type() not in {'application/json','text/javascript'}:raise CatalogError('Expected JSON metadata')
                if not api and r.headers.get_content_type() not in {'image/jpeg','image/png','image/webp'}:raise CatalogError('Expected raster image')
                return data
        except HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==2:raise CatalogError(f'Source HTTP {exc.code}') from exc
            wait=exc.headers.get('Retry-After','')
            time.sleep(min(60,int(wait)) if wait.isdigit() else 2**(attempt+1))
        except (URLError,TimeoutError) as exc:
            if attempt==2:raise CatalogError('Source network unavailable') from exc
            time.sleep(2**attempt)
    raise CatalogError('Source request failed')

def api(host,**params):
    params.update(action='query',format='json',formatversion=2,maxlag=5)
    try:result=json.loads(fetch('https://'+host+'/w/api.php?'+urlencode(params),api=True))
    except (ValueError,UnicodeDecodeError) as exc:raise CatalogError('Invalid metadata JSON') from exc
    if not isinstance(result,dict):raise CatalogError('Invalid metadata object')
    if 'error' in result:raise CatalogError('Metadata API error')
    query=result.get('query',{})
    if not isinstance(query,dict) or not isinstance(query.get('pages',[]),list):raise CatalogError('Invalid metadata query')
    return query

def licence(meta):
    values={k:plain(v.get('value','')) for k,v in meta.items()}
    raw=values.get('License','').lower()
    label=values.get('LicenseShortName','')
    if raw not in LICENSES:
        raw=label.lower().replace(' ','-')
    if 'public domain' in label.lower() or raw.startswith('pd-'):raw='pd'
    if raw=='cc-zero' or raw.startswith('cc0'):raw='cc0'
    if raw not in LICENSES:raise CatalogError('No approved reusable license')
    artist=values.get('Artist','').strip()
    if raw not in ('pd','cc0') and not artist:raise CatalogError('Missing required artist attribution')
    return {'license_id':raw,'license_name':label or raw,'license_url':LICENSES[raw],
            'artist':artist or values.get('Credit','') or 'Public-domain work',
            'credit':values.get('Credit',''),'description_text':values.get('ImageDescription','')}

def identity_evidence(product, page, info):
    if normal(page.get('title',''))!=normal(product['article']):raise CatalogError('Article title does not match candidate')
    if 'missing' in page or 'disambiguation' in page.get('pageprops',{}):raise CatalogError('Missing/ambiguous article')
    title=page.get('pageimage','')
    if not title or title.lower().endswith(('.svg','.gif','.pdf')):raise CatalogError('No photographic lead image')
    qid=page.get('pageprops',{}).get('wikibase_item','')
    if not re.fullmatch(r'Q[1-9][0-9]*',qid):raise CatalogError('No stable Wikidata identity')
    meta=info.get('extmetadata',{})
    description=plain(meta.get('ImageDescription',{}).get('value',''))
    evidence=normal(title+' '+description)
    # Match the actual named subject, not merely a category or a photo keyword.
    subject=re.sub(r'\([^)]*\)','',product['name'])
    tokens=[s for s in normal(subject).split() if s not in {'the','a','of','and','series'}]
    compact=evidence.replace(' ','')
    if not tokens or any(t not in evidence.split() and (len(t)<3 or t not in compact) for t in tokens):
        raise CatalogError('Filename/description does not substantiate named model')
    if re.search(r'\b(logo|logotype|rendering|renders|mockup|blueprint)\b',normal(title)):
        raise CatalogError('Logo/render/blueprint rejected')
    return {'article_id':page['pageid'],'wikidata':qid,'commons_file':title,
            'identity_method':'exact article + lead image + model tokens in file metadata',
            'subject_evidence':description[:1500] or title,
            'article_revision':page.get('lastrevid')}

def fingerprints(image):
    canonical=image.convert('RGB').resize((64,64),Image.Resampling.LANCZOS)
    pixel_hash=sha(canonical.tobytes())
    gray=image.convert('L').resize((9,8),Image.Resampling.LANCZOS)
    pix=list(gray.get_flattened_data()); bits=0
    for y in range(8):
        for x in range(8):bits=(bits<<1)|int(pix[y*9+x]>pix[y*9+x+1])
    return pixel_hash,f'{bits:016x}'

def process_image(blob):
    if not blob or len(blob)>MAX_BYTES:raise CatalogError('Invalid image byte count')
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        try:
            with Image.open(BytesIO(blob)) as image:
                if image.format not in {'JPEG','PNG','WEBP'} or getattr(image,'n_frames',1)!=1:raise CatalogError('Only static raster photos are accepted')
                if min(image.size)<240 or max(image.size)>12000:raise CatalogError('Photo dimensions are unsuitable')
                image.load(); image=ImageOps.exif_transpose(image).convert('RGB')
                image.thumbnail((960,960),Image.Resampling.LANCZOS)
                out=BytesIO();image.save(out,format='WEBP',quality=84,method=5)
                data=out.getvalue()
            # Fingerprint encoded pixels: runtime verification must reproduce these.
            with Image.open(BytesIO(data)) as encoded:
                pixel,dhash=fingerprints(encoded)
                return data,{'width':encoded.width,'height':encoded.height,'pixel_sha256':pixel,'dhash':dhash,'sha256':sha(data)}
        except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
            raise CatalogError('Image decoding failed') from exc

def duplicate(entry, previous):
    for other in previous:
        if any(entry[k]==other[k] for k in ('wikidata','commons_file','source_sha1','sha256','pixel_sha256')):return True
        if (int(entry['dhash'],16)^int(other['dhash'],16)).bit_count()<=5:return True
    return False

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('wb') as f:f.write(data);f.flush();__import__('os').fsync(f.fileno())
    temp.chmod(0o644);temp.replace(path)

def write_json(path,data):atomic(path,(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())

def round_robin_candidates(definitions):
    # Small categories must get a fair chance before the publication cap is hit.
    from itertools import zip_longest
    categories=[c['id'] for c in definitions['categories']]
    groups={key:[] for key in categories}
    for product in definitions['products']:
        if product['category'] not in groups:raise CatalogError('Unknown candidate category')
        groups[product['category']].append(product)
    return [p for row in zip_longest(*(groups[key] for key in categories)) for p in row if p is not None]

def import_catalog(root=ROOT):
    definitions=json.loads((root/'data/catalog.json').read_text())
    minimum=definitions['minimum_verified'];maximum=definitions['maximum_products']
    if minimum<400 or maximum<minimum:raise CatalogError('Refusing a reduced publication floor')
    output=root/'app/static/photos'; output.mkdir(parents=True,exist_ok=True);output.chmod(0o755)
    cache_root=Path(os.environ.get('DOPAMINE_CATALOG_CACHE',str(root/'data/catalog-cache')))
    if cache_root.is_symlink():raise CatalogError('Unsafe catalog cache')
    cache_root.mkdir(parents=True,exist_ok=True)
    (cache_root/'photos').mkdir(exist_ok=True)
    ready_path=root/'data/catalog-live.json'
    if ready_path.exists():
        verify_photos(root); print('Existing real catalog verified; no network needed.',flush=True)
        return json.loads(ready_path.read_text())
    accepted=[];records={};rejects=[];network_errors=0
    cache_file=cache_root/'metadata.json'
    cache=json.loads(cache_file.read_text()) if cache_file.is_file() else {}
    candidates=round_robin_candidates(definitions)
    if any(not re.fullmatch(r'real-[a-z0-9-]+',p['id']) or p['photo']!=p['id'] for p in candidates):raise CatalogError('Invalid candidate identifier')
    for offset in range(0,len(candidates),20):
        group=candidates[offset:offset+20]
        try:
            result=api('en.wikipedia.org',titles='|'.join(x['article'] for x in group),prop='pageimages|pageprops|info',piprop='name',pilicense='free')
            pages={normal(p.get('title','')):p for p in result.get('pages',[])}
            titles=['File:'+p['pageimage'] for p in pages.values() if p.get('pageimage')]
            images=api('commons.wikimedia.org',titles='|'.join(titles),prop='imageinfo',iiprop='url|sha1|size|extmetadata',iiurlwidth=960) if titles else {}
            infos={p['title'][5:].replace('_',' '):p.get('imageinfo',[{}])[0] for p in images.get('pages',[]) if p.get('imageinfo')}
            network_errors=0
        except CatalogError as exc:
            network_errors+=1
            rejects.extend({'id':x['id'],'reason':str(exc)} for x in group)
            print(f'METADATA BLOCK {offset//20+1} FAILED: {exc}',flush=True)
            if network_errors>=3:break
            continue
        tasks=[]
        for product in group:
            try:
                page=pages.get(normal(product['article']),{})
                info=infos.get(page.get('pageimage','').replace('_',' '),{})
                ident=identity_evidence(product,page,info)
                rights=licence(info.get('extmetadata',{}))
                url=info.get('thumburl','')
                if not allowed_url(url):raise CatalogError('No approved raster thumbnail URL')
                if not re.fullmatch(r'[a-f0-9]{40}',info.get('sha1','')):raise CatalogError('Missing source fingerprint')
                record=dict(ident,**rights,url=url,original=info['descriptionurl'],source_sha1=info['sha1'],
                    provider='Wikimedia Commons',category=product['category'],requested_url=url,
                    description={l:product['name'] for l in ('pt-br','en','zh','ja')},
                    changes='Resized to at most 960 px; converted to WebP; metadata removed. Original image license retained.')
                if not record['original'].startswith('https://commons.wikimedia.org/wiki/File:'):raise CatalogError('Missing Commons description page')
                tasks.append((product,record))
            except CatalogError as exc:rejects.append({'id':product['id'],'reason':str(exc)})
        def download(task):
            product,entry=task
            saved=cache.get(product['id'])
            path=cache_root/'photos'/(product['photo']+'.webp')
            if saved and saved.get('source_sha1')==entry['source_sha1'] and path.is_file() and sha(path.read_bytes())==saved.get('sha256'):
                fresh=dict(saved);fresh.update(entry)
                return product,fresh,path.read_bytes()
            blob=fetch(entry['url']);data,fp=process_image(blob)
            entry.update(fp,imported_at=datetime.now(timezone.utc).isoformat(),bytes=len(data))
            return product,entry,data
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[(task,pool.submit(download,task)) for task in tasks]
            for task,future in futures:
                product=task[0]
                try:
                    product,entry,data=future.result()
                    if duplicate(entry,records.values()):raise CatalogError('Repeated item, repeated photo, or visually similar image rejected')
                    if len(accepted)>=maximum:continue
                    atomic(output/(product['photo']+'.webp'),data)
                    atomic(cache_root/'photos'/(product['photo']+'.webp'),data)
                    cache[product['id']]=entry;records[product['photo']]=entry
                    accepted.append(dict(product,verified=True,source='https://en.wikipedia.org/?curid='+str(entry['article_id'])))
                    print(f'PHOTO {len(accepted):03d}: {product["name"]} [{entry["license_id"]}]',flush=True)
                except (CatalogError,OSError,ValueError) as exc:rejects.append({'id':product['id'],'reason':str(exc)})
        write_json(cache_file,cache)
        if len(accepted)>=maximum:break
        time.sleep(1)
    report={'candidate_count':len(candidates),'accepted_count':len(accepted),'required_minimum':minimum,
            'maximum':maximum,'rejections':rejects,'review':'Automated source/identity/license/byte/pixel/near-duplicate checks; not a human visual audit.',
            'created_at':datetime.now(timezone.utc).isoformat()}
    write_json(root/'data/catalog-import-report.json',report)
    write_json(cache_root/'last-import-report.json',report)
    if len(accepted)<minimum:
        raise CatalogError(f'Only {len(accepted)} verified unique items; {minimum} required. Existing application is not replaced. Review catalog-import-report.json; never substitute generic photos.')
    used={p['category'] for p in accepted}
    live=dict(definitions,products=accepted,categories=[c for c in definitions['categories'] if c['id'] in used])
    # The build output contains only this publication's selected photos.
    for path in output.glob('*.webp'):
        if path.stem not in records:path.unlink()
    write_json(root/'data/photos-resolved.json',records)
    write_json(ready_path,live)
    verify_photos(root)
    print(f'CATALOG VERIFIED: {len(accepted)} distinct models, {len(records)} distinct local pictures.',flush=True)
    return live

def verify_photos(root=ROOT):
    ready=root/'data/catalog-live.json';resolved=root/'data/photos-resolved.json'
    if not ready.is_file() or not resolved.is_file():raise CatalogError('Real catalog not imported. Run python manage.py photos.')
    live=json.loads(ready.read_text()); photos=json.loads(resolved.read_text())
    definitions=json.loads((root/'data/catalog.json').read_text())
    if len(live['products'])<max(400,definitions['minimum_verified']):raise CatalogError('Verified catalog is below publication floor')
    seeds={p['id']:p for p in definitions['products']}
    ids=set();names=set();prior=[]
    if len(live['products'])!=len(photos):raise CatalogError('Photo/product cardinality mismatch')
    if {p.stem for p in (root/'app/static/photos').glob('*.webp')}!=set(photos):raise CatalogError('Unreferenced/missing picture in publication')
    for p in live['products']:
        pid=p['id'];entry=photos.get(p['photo'],{});seed=seeds.get(pid)
        if not seed or p['name']!=seed['name'] or p['category']!=seed['category'] or p['credits']!=seed['credits'] or not p.get('verified'):raise CatalogError('Unrecognized or unverified inventory item')
        if pid in ids or normal(p['name']) in names or p['photo']!=pid:raise CatalogError('Duplicate item/name/photo slot')
        ids.add(pid);names.add(normal(p['name']))
        if entry.get('license_id') not in LICENSES or entry.get('license_url')!=LICENSES[entry['license_id']] or not allowed_url(entry.get('url','')):raise CatalogError('Invalid photo provenance')
        path=root/'app/static/photos'/(pid+'.webp')
        if path.is_symlink() or not path.is_file():raise CatalogError('Missing or unsafe local image')
        data=path.read_bytes()
        if sha(data)!=entry.get('sha256'):raise CatalogError('Photo content hash mismatch')
        with Image.open(BytesIO(data)) as image:
            if image.format!='WEBP' or max(image.size)>960 or min(image.size)<1:raise CatalogError('Invalid optimized picture')
            pixel,dhash=fingerprints(image)
        if pixel!=entry.get('pixel_sha256') or dhash!=entry.get('dhash'):raise CatalogError('Pixel fingerprint mismatch')
        if duplicate(entry,prior):raise CatalogError('Duplicate model or photograph')
        prior.append(entry)
    return len(ids)
