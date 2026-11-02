"""Checksummed PostgreSQL DDL and catalog verification (MAT-092).

The backend owns the transaction and schema lock. The expected catalog was
captured from this packaged DDL using synthetic databases, not host data.
Every operation verifies the manifest, constraints, indexes and trigger bodies.
Full record and journal verification is a separate explicit restore check.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
import json
import re

from ...canonical import source_digest
from ..base import StorageError

SCHEMA_VERSION = 1
MIGRATION_NAME = "001_initial.sql"


@lru_cache(maxsize=1)
def migration():
    data = files(__package__).joinpath(MIGRATION_NAME).read_bytes()
    return data.decode("utf-8"), source_digest(data)


def catalog(connection, schema):
    """Return schema-relative definitions with no runtime OIDs or host data."""
    queries = {
        "relations": "SELECT c.relname, c.relkind, c.relpersistence, c.relrowsecurity, c.relforcerowsecurity "
                     "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                     "WHERE n.nspname=%s ORDER BY c.relname",
        "columns": "SELECT c.relname, a.attname, a.atttypid::regtype::text, a.attnotnull, "
                   "coalesce(coll.collname,''), a.attgenerated, a.attidentity, coalesce(pg_get_expr(d.adbin,d.adrelid),'') "
                   "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
                   "JOIN pg_namespace n ON n.oid=c.relnamespace "
                   "LEFT JOIN pg_collation coll ON coll.oid=a.attcollation "
                   "LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
                   "WHERE n.nspname=%s AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped "
                   "ORDER BY c.relname,a.attnum",
        "constraints": "SELECT c.relname,k.conname,k.contype,k.condeferrable,k.condeferred,k.convalidated, "
                       "pg_get_constraintdef(k.oid) FROM pg_constraint k "
                       "JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                       "WHERE n.nspname=%s ORDER BY c.relname,k.conname",
        "indexes": "SELECT c.relname,i.relname,x.indisunique,x.indisvalid,pg_get_indexdef(i.oid) "
                   "FROM pg_index x JOIN pg_class c ON c.oid=x.indrelid "
                   "JOIN pg_class i ON i.oid=x.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE n.nspname=%s ORDER BY c.relname,i.relname",
        "triggers": "SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) "
                    "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=%s AND NOT t.tgisinternal ORDER BY c.relname,t.tgname",
        "foreign_key_triggers": "SELECT c.relname,k.conname,t.tgenabled,t.tgtype,pn.nspname,p.proname, "
                                "t.tgdeferrable,t.tginitdeferred FROM pg_trigger t "
                                "JOIN pg_constraint k ON k.oid=t.tgconstraint "
                                "JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                                "JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace pn ON pn.oid=p.pronamespace "
                                "WHERE n.nspname=%s AND t.tgisinternal AND k.contype='f' "
                                "ORDER BY c.relname,k.conname,t.tgtype,p.proname",
        "functions": "SELECT p.proname,l.lanname,p.provolatile,p.prosecdef,p.proisstrict,p.proparallel,p.prorettype::regtype::text, "
                     "p.proargtypes::text,p.proconfig,p.prosrc FROM pg_proc p "
                     "JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang "
                     "WHERE n.nspname=%s ORDER BY p.proname",
    }
    from psycopg.rows import tuple_row
    with connection.cursor(row_factory=tuple_row) as cursor:
        result = {}
        for name, query in queries.items():
            cursor.execute(query, (schema,))
            result[name] = cursor.fetchall()
    # Normalize qualified identifiers and exact search_path settings only.
    # Packaged function bodies are schema-independent and compared verbatim:
    # a schema named "type" must not rewrite the literal "cannot change type.".
    qualified = re.compile(r'(?<![A-Za-z0-9_$"])(?:"' + re.escape(schema) + r'"|' + re.escape(schema) + r')\.')
    def normalize(value):
        if isinstance(value, str):
            value = qualified.sub("@schema@.", value)
            for name in (schema, '"' + schema + '"'):
                if value == "search_path=" + name + ", pg_temp":
                    return "search_path=@schema@, pg_temp"
                if value == "search_path=pg_catalog, " + name + ", pg_temp":
                    return "search_path=pg_catalog, @schema@, pg_temp"
            return value
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        return value
    return {name: [normalize(row[:-1]) + [row[-1]] if name == "functions" else normalize(row)
                   for row in rows] for name, rows in result.items()}



@lru_cache(maxsize=1)
def expected_catalog():
    return json.loads(files(__package__).joinpath("001_objects.json").read_text())


def check_database(connection, schema):
    from psycopg.rows import tuple_row
    actual = catalog(connection, schema)
    expected = expected_catalog()
    # Inspect catalog metadata before reading a purported manifest. A view,
    # RLS policy or unexpected manifest type must not execute host code here.
    for section in ("relations", "columns", "constraints"):
        if [r for r in actual[section] if r[0] == "schema_migrations"] != [
                r for r in expected[section] if r[0] == "schema_migrations"]:
            raise StorageError("E_SCHEMA_INVALID", "Not an intact Matter migration manifest.")
    with connection.cursor(row_factory=tuple_row) as cursor:
        cursor.execute("SELECT to_regclass(%s)", (schema + ".schema_migrations",))
        if cursor.fetchone()[0] is None:
            raise StorageError("E_SCHEMA_INVALID", "Not an initialized Matter PostgreSQL schema.")
        cursor.execute("SELECT version,name,checksum,applied_at FROM schema_migrations ORDER BY version LIMIT 2")
        rows = cursor.fetchall()
    if any(row[0] > SCHEMA_VERSION for row in rows):
        raise StorageError("E_VERSION_UNSUPPORTED", "The Matter schema requires a newer SDK.")
    if len(rows) != 1 or rows[0][:3] != (SCHEMA_VERSION, MIGRATION_NAME, migration()[1]):
        raise StorageError("E_STORAGE_UNAVAILABLE", "The Matter migration ledger is damaged.")
    try:
        stamp = datetime.fromisoformat(rows[0][3].replace("Z", "+00:00"))
        if not rows[0][3].endswith("Z") or stamp.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise StorageError("E_STORAGE_UNAVAILABLE", "The Matter migration timestamp is invalid.") from None
    if actual != expected:
        raise StorageError("E_STORAGE_UNAVAILABLE", "The Matter schema definitions are damaged or unsupported.")


def migrate(connection, schema, fault_hook):
    """Called only under the backend's schema advisory lock and transaction."""
    from psycopg import sql
    from psycopg.rows import tuple_row
    with connection.cursor(row_factory=tuple_row) as cursor:
        cursor.execute("SELECT oid FROM pg_namespace WHERE nspname=%s", (schema,))
        if cursor.fetchone() is None:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute("SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                       "WHERE n.nspname=%s LIMIT 1", (schema,))
        existing = cursor.fetchone()
        if existing is None:
            # The SQL is a trusted packaged resource, with no interpolated values.
            # Omit pg_catalog so built-ins are implicitly searched FIRST while
            # this schema remains the DDL creation target (and pg_temp last).
            cursor.execute(sql.SQL("SET LOCAL search_path = {}, pg_temp").format(sql.Identifier(schema)))
            cursor.execute(migration()[0], prepare=False)
            cursor.execute(sql.SQL("SET LOCAL search_path = pg_catalog, {}, pg_temp").format(sql.Identifier(schema)))
            fault_hook("migration:1:ddl")
            cursor.execute("INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(%s,%s,%s,%s)",
                           (SCHEMA_VERSION, MIGRATION_NAME, migration()[1],
                            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")))
            fault_hook("migration:1:ledger")
        check_database(connection, schema)
