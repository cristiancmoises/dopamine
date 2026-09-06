"""SQLite transactions and explicit migrations, including the early 1.1 branch."""
from contextlib import contextmanager, closing
from pathlib import Path
import sqlite3
from .config import ROOT
from .schema_bridge import statements, migrate_early


def connect(path: Path):
    db = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=15000')
    return db


def initialize(path: Path):
    if path.is_symlink():
        raise RuntimeError('Database path must not be a symlink')
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1, 2):
            raise RuntimeError(f'Unsupported schema version {version}; no migration performed')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
        with atomic(db):
            # Re-read under the writer lock; concurrent startup cannot migrate twice.
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version == 2:
                migrate_early(db)
            elif version in (0, 1):
                columns = {row[1] for row in db.execute('PRAGMA table_info(rounds)')}
                if columns and 'result_json' not in columns:
                    db.execute("ALTER TABLE rounds ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}'")
                for sql in statements((ROOT/'data/schema.sql').read_text()):
                    db.execute(sql)
            else:
                raise RuntimeError('Schema version changed during startup; refusing migration')
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise RuntimeError('Foreign key validation failed')
    path.chmod(0o600)


@contextmanager
def atomic(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield db
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def cleanup(db, now, idle_seconds=3600):
    with atomic(db):
        a=db.execute('DELETE FROM sessions WHERE expires_at<=? OR touched_at<=?',(now,now-idle_seconds)).rowcount
        b=db.execute('DELETE FROM rate_limits WHERE expires_at<=?',(now,)).rowcount
    return {'sessions_removed':a, 'rate_limits_removed':b}
