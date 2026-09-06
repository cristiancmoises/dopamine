"""Small, auditable security primitives; passwords are never encrypted or logged."""
import hashlib
import hmac
import ipaddress
import re
import secrets
import time
import unicodedata
from urllib.parse import urlsplit
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from .db import atomic

PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16, type=Type.ID)
# A constant dummy hash equalizes expensive work for missing users. No usable account uses it.
DUMMY_HASH = PH.hash(secrets.token_urlsafe(32))
COMMON = {"123456789012", "password12345", "password123456", "1234567890123456", "qwertyuiop123", "abcdefghijkl", "senha12345678"}

def now(): return int(time.time())
def token(): return secrets.token_urlsafe(32)
def digest(value): return hashlib.sha256(value.encode("utf-8")).hexdigest()
def keyed(secret, namespace, value):
    return hmac.new(secret.encode(), (namespace+":"+value).encode(), hashlib.sha256).hexdigest()
def verify(stored, password):
    if not isinstance(password,str) or len(password)>128:
        return False
    try: return PH.verify(stored or DUMMY_HASH, password)
    except (VerificationError, InvalidHashError): return False

def clean_nickname(value):
    value = unicodedata.normalize("NFKC", value.strip())
    if not 3<=len(value)<=24 or not all(c.isalnum() or c in "_-" for c in value):
        raise ValueError("nickname_invalid")
    return value, value.casefold()

def password_error(value):
    if not 12 <= len(value) <= 128 or value.casefold() in COMMON or len(set(value)) < 4:
        return "password_invalid"
    return None

def trusted_ip(address, cidrs):
    try: return any(ipaddress.ip_address(address) in ipaddress.ip_network(c.strip(),strict=False) for c in cidrs)
    except ValueError: return False

def client_ip(env, config):
    peer = env.get("REMOTE_ADDR", "unknown")
    # NPM must overwrite X-Real-IP with $remote_addr. Do NOT trust arbitrary forwarded headers.
    forwarded=env.get("HTTP_X_REAL_IP", "")
    if trusted_ip(peer,config.proxy_cidrs) and forwarded:
        try: return str(ipaddress.ip_address(forwarded.strip()))
        except ValueError: pass
    return peer

def secure_request(env, config):
    if env.get("wsgi.url_scheme")=="https": return True
    return trusted_ip(env.get("REMOTE_ADDR",""),config.proxy_cidrs) and env.get("HTTP_X_FORWARDED_PROTO","").lower()=="https"

def allowed_rate(db, config, kind, identity, limit, window):
    timestamp=now(); bucket=timestamp//window
    key=keyed(config.secret,"rate",f"{kind}:{identity}:{bucket}")
    with atomic(db):
        db.execute("INSERT INTO rate_limits(key,count,expires_at) VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1",(key,(bucket+2)*window))
        count=db.execute("SELECT count FROM rate_limits WHERE key=?",(key,)).fetchone()[0]
    return count <= limit

def new_session(db, config, user_id=None):
    raw=token(); timestamp=now()
    row={"token_hash":digest(raw),"csrf":token(),"user_id":user_id,"created_at":timestamp,"touched_at":timestamp,"expires_at":timestamp+config.session_seconds}
    db.execute("INSERT INTO sessions VALUES(:token_hash,:csrf,:user_id,:created_at,:touched_at,:expires_at)",row)
    return raw,row

def action_token(config, session, action):
    payload=f"{now()}.{secrets.token_hex(12)}"
    sig=keyed(config.secret,"action",session["token_hash"]+":"+action+":"+payload)
    return f"{payload}.{sig}"

def valid_action(config, session, action, value):
    if not isinstance(value,str) or not re.fullmatch(r"[0-9]{1,12}\.[a-f0-9]{24}\.[a-f0-9]{64}", value): return False
    parts=value.split(".")
    if len(parts)!=3: return False
    try:
        if not -10 <= now()-int(parts[0]) <= 3600: return False
    except ValueError: return False
    expected=keyed(config.secret,"action",session["token_hash"]+":"+action+":"+".".join(parts[:2]))
    return hmac.compare_digest(expected, parts[2])


def same_origin(value, expected):
    """Canonical origin comparison; reject null, credentials and URL suffixes."""
    def canonical(raw):
        if not isinstance(raw, str) or any(c.isspace() or ord(c) < 32 for c in raw):
            return None
        try:
            parsed = urlsplit(raw)
            if (parsed.scheme not in ("https", "http") or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path or parsed.query or parsed.fragment):
                return None
            return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        except ValueError:
            return None
    actual = canonical(value)
    return actual is not None and actual == canonical(expected)
