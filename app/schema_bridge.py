"""Additive early-1.1 (schema 2) compatibility, without relabeling old rows.

The core remains schema 2 because the original 1.1 runtime accepts that layout.
Additional tables are versioned in schema_features, not by lowering user_version.
"""
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
CORE_TABLES = ('users','sessions','purchases','purchase_items','cart','favorites','rounds','rate_limits')


def statements(script):
    pending = ''
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ''
    # Trailing comments are not statements.
    if re.sub(r'--[^\n]*', '', pending).strip():
        raise RuntimeError('Incomplete repository SQL statement')


def canonical(sql):
    # Only compare known repository DDL, never modify sqlite_schema.
    return re.sub(r'\s+', '', (sql or '').lower().replace('if not exists','').replace('"','')).rstrip(';')


def objects(connection):
    return {row[0]:(row[1], canonical(row[2])) for row in connection.execute(
        "SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL")}


@lru_cache(maxsize=1)
def expected_objects():
    with closing(sqlite3.connect(':memory:')) as c:
        c.executescript((ROOT/'data/migrations/early11-core.sql').read_text())
        core = objects(c)
        c.executescript((ROOT/'data/migrations/early11-additions.sql').read_text())
        return core, objects(c)


def check_early(connection):
    """Check object definitions, not just the user-provided version integer."""
    if connection.execute('PRAGMA user_version').fetchone()[0] != 2:
        raise RuntimeError('The early-1.1 bridge requires core schema 2')
    core, allowed = expected_objects()
    actual = objects(connection)
    missing = sorted(set(core) - set(actual))
    changed = sorted(n for n in actual if n not in allowed or actual[n] != allowed[n])
    if missing or changed:
        raise RuntimeError('Unrecognized schema-2 layout; missing=' + ','.join(missing)
                           + '; changed/extra=' + ','.join(changed))
    if 'schema_features' in actual:
        expected = {'expanded_games':1, 'interactive_tables':1, 'early11_bridge':1}
        if any(name not in expected or revision != expected[name]
               for name,revision in connection.execute('SELECT name,revision FROM schema_features')):
            raise RuntimeError('Unrecognized schema feature revision')
    if connection.execute('PRAGMA foreign_key_check').fetchone():
        raise RuntimeError('Foreign key check failed; no bridge applied')
    if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise RuntimeError('SQLite quick_check failed; no bridge applied')


def migrate_early(connection):
    """Caller owns BEGIN IMMEDIATE/COMMIT; all additions roll back on failure."""
    check_early(connection)
    for sql in statements((ROOT/'data/migrations/early11-additions.sql').read_text()):
        connection.execute(sql)
    check_early(connection)
    if objects(connection) != expected_objects()[1]:
        raise RuntimeError('Bridge did not create the complete expected schema')
