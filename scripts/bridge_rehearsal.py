#!/usr/bin/env python3
"""Rehearse the bridge on an explicitly supplied disposable SQLite copy."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db
from app.schema_bridge import check_early, objects


def fingerprint(c):
    """Compare rows including secrets in memory; never print their hashes/values."""
    result = {}
    for table, in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        quote = lambda value: '"' + value.replace('"', '""') + '"'
        cols = list(c.execute('PRAGMA table_info('+quote(table)+')'))
        names = [r[1] for r in cols]
        pk = [r[1] for r in sorted(cols, key=lambda r:r[5]) if r[5]] or names
        h = hashlib.sha256();count = 0
        h.update(json.dumps(names).encode())
        sql='SELECT '+','.join(map(quote,names))+' FROM '+quote(table)+' ORDER BY '+','.join(map(quote,pk))
        for row in c.execute(sql):
            # Preserve byte/text distinctions, NULLs, integers, order and every value.
            data=[('blob',v.hex()) if isinstance(v,bytes) else (type(v).__name__,v) for v in row]
            h.update(json.dumps(data,ensure_ascii=True,separators=(',',':')).encode()+b'\n');count+=1
        result[table]=(count,h.hexdigest())
    return result


def rehearse(path):
    if path.is_symlink() or not path.is_file():raise RuntimeError('A regular disposable database copy is required')
    with closing(db.connect(path)) as c:
        check_early(c);before=fingerprint(c);before_objects=objects(c)
    db.initialize(path);db.initialize(path)
    with closing(db.connect(path)) as c:
        check_early(c);after=fingerprint(c);after_objects=objects(c)
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Integrity check failed')
        if any(before[t]!=after.get(t) for t in before if t!='schema_features'):
            raise RuntimeError('Existing rows changed during rehearsal')
        if any(after_objects.get(n)!=v for n,v in before_objects.items()):
            raise RuntimeError('Existing object definition changed during rehearsal')
        if c.execute('PRAGMA user_version').fetchone()[0]!=2:raise RuntimeError('Core version changed')
        features=dict(c.execute('SELECT name,revision FROM schema_features'))
        if features.get('early11_bridge')!=1 or features.get('interactive_tables')!=1:
            raise RuntimeError('Missing bridge features')
    return {'status':'ok','user_version':2,'existing_rows_unchanged':True,
            'existing_objects_unchanged':True,'repeated_initialization':'ok'}


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: bridge_rehearsal.py DISPOSABLE_COPY')
    print(json.dumps(rehearse(Path(sys.argv[1]))))
