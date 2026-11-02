"""Opt-in PostgreSQL fixtures. Only random mat_test_* schemas are removed."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from matter.storage import PostgreSQLStore, SQLiteStore


def dsn():
    value = os.environ.get("MATTER_TEST_POSTGRES_DSN")
    if not value:
        raise unittest.SkipTest("Set MATTER_TEST_POSTGRES_DSN for real PostgreSQL conformance.")
    try:
        import psycopg
    except ImportError:
        raise unittest.SkipTest("Install requirements-postgres-test.txt.") from None
    return value


def connect(target=None):
    import psycopg
    return psycopg.connect(target or dsn(), connect_timeout=5)


def schema_name():
    return "mat_test_" + uuid4().hex


def drop_schema(schema):
    from psycopg import sql
    if not schema.startswith("mat_test_"):
        raise AssertionError("Refusing to remove a schema outside the synthetic test prefix.")
    with connect() as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


class PostgresCase(unittest.TestCase):
    def setUp(self):
        dsn()
        self.schema = schema_name()
        self.addCleanup(drop_schema, self.schema)

    def store(self, scope="synthetic:storage", **kwargs):
        store = PostgreSQLStore(connect, schema=self.schema, scope_id=scope, **kwargs)
        self.addCleanup(store.close)
        return store


class _FixtureStore(PostgreSQLStore):
    """Test-only path alias so original scenarios can reopen the same ledger."""
    def __init__(self, path, *, schema, **kwargs):
        self.path = Path(path)
        super().__init__(connect, schema=schema, **kwargs)


def install_backend(case):
    """Run existing behavioral scenarios unchanged using their actual factory seams.

    Only test modules' imported SQLiteStore names are patched, never runtime
    imports or a live host. File/PRAGMA-specific scenarios are not selected.
    """
    dsn()
    schemas = {}
    used = []
    def factory(path, **kwargs):
        key = str(path)
        if key not in schemas:
            schemas[key] = schema_name()
        store = _FixtureStore(path, schema=schemas[key], **kwargs)
        used.append(store)
        return store
    def cleanup():
        for schema in schemas.values():
            drop_schema(schema)
    case.addCleanup(cleanup)
    case.addCleanup(lambda: case.assertTrue(used, "The reused scenario never opened PostgreSQL."))
    reference_backend = SQLiteStore
    for name, module in list(sys.modules.items()):
        if (name != __name__ and (name.startswith("integration.") or name.endswith("_helpers"))
                and getattr(module, "SQLiteStore", None) is reference_backend):
            replacement = patch.object(module, "SQLiteStore", factory)
            replacement.start()
            case.addCleanup(replacement.stop)


def reuse_cases(loader, module, class_name, *, exclude=(), include=None):
    base = getattr(module, class_name)
    def setUp(self):
        install_backend(self)
        base.setUp(self)
    adapted = type("PostgreSQL" + class_name, (base,), {"setUp": setUp, "__module__": __name__})
    names = loader.getTestCaseNames(base)
    if include is not None:
        missing = set(include) - set(names)
        if missing:
            raise AssertionError("Missing shared conformance cases: " + repr(missing))
        names = [n for n in names if n in include]
    return unittest.TestSuite(adapted(n) for n in names if n not in exclude)
