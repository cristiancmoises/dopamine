#!/usr/bin/env python3
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Config
from app import db
from app.real_photos import verify_photos
from app.security import now
from contextlib import closing

def main():
    os.umask(0o077)
    config=Config.from_env()
    if not config.secure or not config.require_local_photos:
        raise RuntimeError('Production entrypoint requires HTTPS cookies and verified local photos. Use manage.py serve-local only for development.')
    if not config.proxy_cidrs:
        raise RuntimeError('TRUSTED_PROXY_CIDRS is empty. Run scripts/deploy.fish to resolve the NPM peer.')
    import ipaddress
    for value in config.proxy_cidrs:
        network=ipaddress.ip_network(value.strip(),strict=True)
        if network.prefixlen!=network.max_prefixlen:
            raise RuntimeError('Trust only exact NPM addresses (/32 IPv4 or /128 IPv6), not entire networks.')
    verify_photos()
    db.initialize(config.database)
    with closing(db.connect(config.database)) as connection:db.cleanup(connection,now(),config.idle_seconds)
    os.execv(sys.executable,[sys.executable,'-m','gunicorn','--config','/app/gunicorn.conf.py','app.web:create_app()'])

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('STARTUP REFUSED: '+str(exc),file=sys.stderr);sys.exit(1)
