from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
import os

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = {"pt-br": "Português", "en": "English", "zh": "中文", "ja": "日本語"}

@dataclass(frozen=True)
class Config:
    secret: str
    database: Path
    site_url: str = "https://dopamine.securityops.co"
    allowed_hosts: tuple[str, ...] = ("dopamine.securityops.co",)
    proxy_cidrs: tuple[str, ...] = ()
    secure: bool = True
    require_local_photos: bool = True
    testing: bool = False
    session_seconds: int = 43200
    idle_seconds: int = 3600
    @property
    def cookie_name(self):
        return "__Host-dopamine" if self.secure else "dopamine_local"
    @classmethod
    def from_env(cls):
        secret = os.environ.get("SECRET_KEY", "")
        if len(secret) < 48 or secret.startswith("CHANGE"):
            raise RuntimeError("SECRET_KEY must be a random secret of at least 48 characters. Run scripts/deploy.fish.")
        site = os.environ.get("SITE_URL", "https://dopamine.securityops.co").rstrip("/")
        parsed = urlsplit(site)
        secure = os.environ.get("SECURE_COOKIES", "true").lower() == "true"
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.path or parsed.query or parsed.fragment:
            raise RuntimeError("SITE_URL must be an origin, without a path or credentials.")
        if secure and parsed.scheme != "https":
            raise RuntimeError("Secure mode requires an HTTPS SITE_URL.")
        hosts = tuple(x.strip().lower() for x in os.environ.get("ALLOWED_HOSTS", parsed.netloc).split(",") if x.strip())
        if not hosts or any(not h or any(c in h for c in '/\\@#? \t\r\n') or '*' in h for h in hosts):
            raise RuntimeError("ALLOWED_HOSTS must contain exact hostnames (and optional ports), no wildcards.")
        return cls(secret=secret, database=Path(os.environ.get("DATABASE_PATH", "/data/dopamine.sqlite3")),
                   site_url=site, allowed_hosts=hosts,
                   proxy_cidrs=tuple(filter(None, os.environ.get("TRUSTED_PROXY_CIDRS", "").split(","))),
                   secure=secure, require_local_photos=os.environ.get("REQUIRE_LOCAL_PHOTOS", "true").lower()=="true")
