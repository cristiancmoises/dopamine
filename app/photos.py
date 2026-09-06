"""Build-time only photo importer. Browsers never contact the image provider.

The manifest is repository-controlled, not input from an HTTP endpoint. Redirects
are restricted to the same HTTPS host. Existing files are reused only with a
matching resolved manifest and SHA-256, never on the basis of their filename alone.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import time
from .config import ROOT

MAX_IMAGE_BYTES = 2 * 1024 * 1024


def allowed_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        return bool(p.scheme == 'https' and p.hostname == 'images.unsplash.com'
                    and p.port in (None,443) and not p.username and not p.password
                    and not p.fragment and re.fullmatch(r'/photo-[0-9]+-[a-f0-9]+', p.path))
    except (TypeError, ValueError):
        return False


class RestrictedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError('Rejected image redirect outside the HTTPS allowlist')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def is_webp(blob: bytes) -> bool:
    return (20 <= len(blob) <= MAX_IMAGE_BYTES and blob[:4] == b'RIFF'
            and blob[8:12] == b'WEBP' and blob[12:16] in (b'VP8 ',b'VP8L',b'VP8X')
            and int.from_bytes(blob[4:8],'little') + 8 == len(blob))


def fetch_photo(url: str, opener=None) -> bytes:
    if not allowed_url(url):
        raise ValueError('Only allowlisted Unsplash HTTPS photo URLs may be imported')
    request = Request(url, headers={'User-Agent':'Dopamine-Fictional-Catalog/1.0',
                                  'Accept':'image/webp', 'Accept-Encoding':'identity'})
    opener = opener or build_opener(RestrictedRedirect())
    with opener.open(request, timeout=25) as response:
        if not allowed_url(response.geturl()) or response.status != 200:
            raise ValueError('Unexpected image response')
        content_type = response.headers.get_content_type()
        if content_type != 'image/webp':
            raise ValueError(f'Expected WebP, received {content_type}')
        content_length = response.headers.get('Content-Length')
        if content_length and int(content_length) > MAX_IMAGE_BYTES:
            raise ValueError('Image exceeds size limit')
        data = response.read(MAX_IMAGE_BYTES + 1)
    if not is_webp(data):
        raise ValueError('Invalid, truncated or oversized WebP image')
    return data


def atomic_write(path: Path, data: bytes):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o644)
    temporary.replace(path)


def import_photos(root: Path = ROOT, strict_unique=False):
    definitions = json.loads((root/'data/photos.json').read_text())
    output = root/'app/static/photos'
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o755)  # Build runs with umask 077; runtime UID must be able to read photos.
    resolved_path = root/'data/photos-resolved.json'
    old = json.loads(resolved_path.read_text()) if resolved_path.is_file() else {}
    resolved, failures = {}, {}

    def one(key, photo):
        if not re.fullmatch(r'[a-z]+-[12]',key) or not allowed_url(photo['url']):
            raise ValueError('Invalid repository photo manifest')
        path = output/f'{key}.webp'
        saved = old.get(key)
        if saved and path.is_file():
            blob = path.read_bytes()
            if is_webp(blob) and saved.get('requested_url')==photo['url'] and hashlib.sha256(blob).hexdigest()==saved.get('sha256'):
                if not strict_unique or saved.get('source_key')==key:
                    return key,saved
        error = None
        for attempt in range(3):
            try:
                blob = fetch_photo(photo['url'])
                atomic_write(path,blob)
                return key,dict(photo, source_key=key, requested_url=photo['url'],
                    sha256=hashlib.sha256(blob).hexdigest(), bytes=len(blob),
                    imported_at=datetime.now(timezone.utc).isoformat())
            except Exception as exc:
                error = exc
                if attempt < 2: time.sleep(1 + attempt)
        raise RuntimeError(f'{key}: {error}') from error

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(one,key,photo):key for key,photo in definitions.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                key,entry = future.result()
                resolved[key]=entry
                print(f'PHOTO OK: {key}', flush=True)
            except Exception as exc:
                failures[key]=str(exc)
                print(f'PHOTO RETRY EXHAUSTED: {key}: {exc}', flush=True)
    # An unavailable reference may use the other reference from its own category.
    # This is explicit in the manifest/credits and never replaces a photo with art.
    if not strict_unique:
        for key in list(failures):
            candidates=[k for k,v in resolved.items() if v['category']==definitions[key]['category']]
            if candidates:
                source=sorted(candidates)[0]
                blob=(output/f'{source}.webp').read_bytes()
                atomic_write(output/f'{key}.webp',blob)
                resolved[key]=dict(resolved[source], requested_url=definitions[key]['url'],
                    fallback_reason=failures[key])
                del failures[key]
                print(f'PHOTO CATEGORY FALLBACK: {key} <- {resolved[source]["source_key"]}',flush=True)
    atomic_write(resolved_path,json.dumps(resolved,ensure_ascii=False,indent=2).encode())
    if failures:
        raise RuntimeError('Photo import incomplete. Nothing may be published without photos. '
                           'Restore network access or replace these repository references: '+', '.join(sorted(failures)))
    verify_photos(root)
    print(f'PHOTOS VERIFIED: {len(resolved)} local slots; '
          f'{len({v["sha256"] for v in resolved.values()})} distinct downloaded images.')
    return resolved


def verify_photos(root: Path = ROOT):
    definitions=json.loads((root/'data/photos.json').read_text())
    resolved_file=root/'data/photos-resolved.json'
    if not resolved_file.is_file():
        raise RuntimeError('Resolved photo manifest absent; run python manage.py photos')
    resolved=json.loads(resolved_file.read_text())
    for key,definition in definitions.items():
        entry=resolved.get(key)
        path=root/'app/static/photos'/f'{key}.webp'
        if not entry or not path.is_file(): raise RuntimeError(f'Missing local photo: {key}')
        data=path.read_bytes()
        if not is_webp(data) or hashlib.sha256(data).hexdigest()!=entry.get('sha256'):
            raise RuntimeError(f'Photo integrity check failed: {key}')
        if entry.get('category')!=definition['category'] or not allowed_url(entry.get('url','')):
            raise RuntimeError(f'Photo provenance check failed: {key}')
    return len(definitions)
