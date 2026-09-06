#!/usr/bin/env python3
"""Explicit operator commands. No public administration endpoint."""
import argparse
from contextlib import closing
from pathlib import Path
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent

def backup_database(source:Path,destination:Path):
    if not source.is_file(): raise RuntimeError('Source database does not exist')
    if source.resolve()==destination.resolve(): raise RuntimeError('Backup must not overwrite the active database')
    if destination.exists(): raise RuntimeError('Backup destination already exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(destination)) as target:
        src.backup(target)
        result=target.execute('PRAGMA integrity_check').fetchone()[0]
        if result!='ok': raise RuntimeError('Backup integrity check failed: '+result)
    destination.chmod(0o600)


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description='Dopamine maintenance commands')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    p=sub.add_parser('photos');p.add_argument('--strict-unique',action='store_true')
    sub.add_parser('verify-photos');sub.add_parser('cleanup');sub.add_parser('test')
    p=sub.add_parser('backup');p.add_argument('destination',nargs='?');p.add_argument('--stdout',action='store_true')
    p=sub.add_parser('serve-local');p.add_argument('--port',type=int,default=3236)
    args=parser.parse_args()
    if args.command=='photos':
        from app.real_photos import import_catalog
        import_catalog()
    elif args.command=='verify-photos':
        from app.real_photos import verify_photos
        print(json.dumps({'local_photo_slots':verify_photos(),'status':'ok'}))
    elif args.command=='test':
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py',top_level_dir=str(ROOT))
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    elif args.command=='serve-local':
        from socketserver import ThreadingMixIn
        from wsgiref.simple_server import WSGIServer,make_server
        from app import db
        from app.config import Config
        from app.web import App
        import secrets
        class ThreadedServer(ThreadingMixIn,WSGIServer): daemon_threads=True
        location=ROOT/'local-data/dopamine.sqlite3'
        db.initialize(location)
        config=Config(secret=os.environ.get('SECRET_KEY',secrets.token_urlsafe(48)),database=location,
                      site_url=f'http://127.0.0.1:{args.port}',allowed_hosts=(f'127.0.0.1:{args.port}',f'localhost:{args.port}'),
                      secure=False,require_local_photos=False)
        print(f'DEVELOPMENT ONLY: http://127.0.0.1:{args.port}; missing photos are explicitly marked.',flush=True)
        print('Set a stable SECRET_KEY to retain recovery-code validity between local restarts.',flush=True)
        with make_server('127.0.0.1',args.port,App(config),server_class=ThreadedServer) as httpd:
            httpd.serve_forever()
    else:
        from app.config import Config
        from app import db
        from app.security import now
        config=Config.from_env()
        if args.command=='init':
            db.initialize(config.database);print('Database initialized.')
        elif args.command=='cleanup':
            with closing(db.connect(config.database)) as connection:
                print(json.dumps(db.cleanup(connection,now(),config.idle_seconds)))
        elif args.command=='backup':
            if args.stdout:
                if args.destination: raise RuntimeError('Choose a path OR --stdout')
                with tempfile.TemporaryDirectory() as temp:
                    target=Path(temp)/'backup.sqlite3'
                    backup_database(config.database,target)
                    with target.open('rb') as file:shutil.copyfileobj(file,sys.stdout.buffer)
            elif args.destination:
                target=Path(args.destination)
                backup_database(config.database,target)
                print('Backup verified: '+str(target))
            else:raise RuntimeError('Provide a destination path or --stdout')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,RuntimeError,ValueError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr);sys.exit(1)
