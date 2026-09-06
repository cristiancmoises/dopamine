#!/usr/bin/env python3
"""Verified online SQLite backup. Retention applies only to files created here."""
import argparse
from datetime import datetime,timezone
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description='Backup consistente; padrão de retenção: 14 dias.')
    parser.add_argument('--directory',type=Path,default=ROOT/'backups')
    parser.add_argument('--retention-days',type=int,default=14)
    args=parser.parse_args()
    if not 1<=args.retention_days<=365:raise RuntimeError('Retenção deve estar entre 1 e 365 dias; atualize a política de privacidade se mudar.')
    os.umask(0o077)
    destination=args.directory.resolve();destination.mkdir(parents=True,exist_ok=True);destination.chmod(0o700)
    name='dopamine-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'.sqlite3'
    final=destination/name;temporary=destination/(name+'.partial')
    args_cmd=['docker','compose','--project-name','dopamine','--file',str(ROOT/'compose.yaml'),
              '--env-file',str(ROOT/'.env'),'exec','-T','web','python','manage.py','backup','--stdout']
    try:
        with temporary.open('xb') as stream:
            result=subprocess.run(args_cmd,cwd=ROOT,stdout=stream,check=False)
            stream.flush();os.fsync(stream.fileno())
        if result.returncode:raise RuntimeError('O comando de backup no container falhou.')
        connection=sqlite3.connect(temporary.as_uri()+'?mode=ro',uri=True)
        try:
            if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Integridade do backup não confirmada.')
        finally:connection.close()
        temporary.chmod(0o600);temporary.replace(final)
    finally:
        if temporary.exists():temporary.unlink()
    cutoff=time.time()-args.retention_days*86400
    for old in destination.iterdir():
        if old.is_file() and not old.is_symlink() and re.fullmatch(r'dopamine-\d{8}T\d{6}\.\d{6}Z\.sqlite3',old.name) and old.stat().st_mtime<cutoff:
            old.unlink()
    print('Backup verificado: '+str(final))
    print('Não é criptografado. Proteja/encripte a cópia externa e preserve .env separadamente.')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (RuntimeError,OSError,sqlite3.Error) as exc:
        print('ERRO: '+str(exc),file=sys.stderr);sys.exit(1)
