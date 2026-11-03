"""Real PostgreSQL contract, process, snapshot, migration and lease checks.

Opt in with MATTER_TEST_POSTGRES_DSN pointing to a disposable synthetic database.
No default host, service, credentials or production connection is discovered.
"""
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

from matter.canonical import canonical_bytes
from matter.storage import PostgreSQLStore, SQLiteStore, StorageError, entity_ref
from integration.helpers import (SCOPE, WATCH_KEY, create_command, create_matter,
                                 domain_value, mutation_command, projection_ref, rewrite_with_children)
from integration.postgres_helpers import PostgresCase, connect, dsn, drop_schema, reuse_cases, schema_name


def _child(target, schema, command, stage, gate, output):
    import psycopg
    def fault(at):
        if at == stage:
            os._exit(73)
    store = PostgreSQLStore(lambda: psycopg.connect(target, connect_timeout=5),
                            schema=schema, scope_id=SCOPE, fault_hook=fault, initialize=False)
    if gate is not None:
        gate.wait(timeout=15)
    handler = rewrite_with_children if "example:effects" in command.get("extensions", {}) else create_matter
    result = store.execute(command, handler)
    if output is not None:
        output.put(result)


def _migration_child(target, schema, stage):
    import psycopg
    def fault(at):
        if at == stage:
            os._exit(73)
    PostgreSQLStore(lambda: psycopg.connect(target, connect_timeout=5), schema=schema,
                    scope_id=SCOPE, fault_hook=fault)


class PostgreSQLTests(PostgresCase):
    def setUp(self):
        super().setUp()
        self.s = self.store()

    def assert_error(self, result, code):
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], code, result)

    def test_sqlite_and_postgresql_return_identical_public_results_and_domain_bytes(self):
        with tempfile.TemporaryDirectory() as directory, SQLiteStore(Path(directory) / "baseline.sqlite", scope_id=SCOPE) as sqlite:
            command = create_command("parity", "subject")
            a, b = sqlite.execute(command, create_matter), self.s.execute(command, create_matter)
            self.assertEqual(canonical_bytes(a), canonical_bytes(b))
            first = sqlite.get(a["body"]["matter"])
            self.assertEqual(canonical_bytes(first), canonical_bytes(self.s.get(b["body"]["matter"])))
            change = mutation_command("parity-change", first, label="updated", child_id="evidence", projection_id="watch")
            a, b = sqlite.execute(change, rewrite_with_children), self.s.execute(change, rewrite_with_children)
            self.assertEqual(canonical_bytes(a), canonical_bytes(b))
            self.assertEqual(sqlite.history(entity_ref(first)), self.s.history(entity_ref(first)))
            self.assertEqual(sqlite.watchers(WATCH_KEY), self.s.watchers(WATCH_KEY))
            left, right = sqlite.command_receipt(change["idempotency_key"]), self.s.command_receipt(change["idempotency_key"])
            self.assertEqual(left["command"], right["command"])
            self.assertEqual(left["receipt"]["body"]["details"], right["receipt"]["body"]["details"])
            self.assertNotEqual(left["receipt"]["provenance"]["producer"], right["receipt"]["provenance"]["producer"])

    def test_long_opaque_identity_fields_have_sqlite_parity(self):
        import random
        import string
        rng = random.Random(92)
        def long_key():
            return "a" + "".join(rng.choices(string.ascii_letters + string.digits, k=4000))
        scope, namespace, identity, command_id, key, watch = [long_key() for _ in range(6)]
        command = create_command(command_id, identity, scope_id=scope, key=key)
        command["body"]["matter"]["namespace"] = namespace
        projection = {"scope_id": scope, "namespace": namespace, "id": long_key(), "record_type": "matter:projection"}
        def handler(tx):
            result = create_matter(tx)
            tx.put_projection(projection, domain_value({"large_keys": True}), watch_keys=(watch,))
            return result
        postgres = self.store(scope=scope)
        with tempfile.TemporaryDirectory() as directory, SQLiteStore(Path(directory) / "baseline.sqlite", scope_id=scope) as sqlite:
            outputs = []
            for store in (sqlite, postgres):
                result = store.execute(command, handler)
                self.assertEqual(result["status"], "success", result)
                self.assertEqual(store.execute(command, lambda tx: self.fail("Exact retry ran twice.")), result)
                record = store.get(result["body"]["matter"])
                self.assertEqual(record["id"], identity)
                self.assertEqual(len(store.watchers(watch)), 1)
                self.assertEqual(store.history(entity_ref(record)), [record])
                self.assertEqual(store.receipt_for(entity_ref(record))["body"]["operation_id"], command_id)
                outputs.append((result, record, store.get(projection), store.command_receipt(key)["result"]))
            self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(postgres.verify()["commands"], 1)

    def test_restore_refuses_missing_or_reassigned_command_and_orphan_watch(self):
        from psycopg import sql
        cases = (
            "DELETE FROM {schema}.commands WHERE command_id='A'",
            "UPDATE {schema}.versions SET command_id='B' WHERE namespace='example' AND id='A'",
            "UPDATE {schema}.versions SET command_id='B' WHERE namespace='matter.storage' AND command_id='A'",
            "INSERT INTO {schema}.watches(scope_id,watch_key,namespace,id) VALUES ('synthetic:storage','orphan','example','absent')",
            "UPDATE {schema}.commands SET receipt_id='absent' WHERE command_id='A'",
        )
        for query in cases:
            with self.subTest(query=query):
                schema = schema_name()
                self.addCleanup(drop_schema, schema)
                with PostgreSQLStore(connect, schema=schema, scope_id=SCOPE) as store:
                    for identity in ('A', 'B'):
                        self.assertEqual(store.execute(create_command(identity, identity), create_matter)["status"], "success")
                    with connect() as conn:
                        conn.execute("SET LOCAL session_replication_role=replica")
                        cursor = conn.execute(sql.SQL(query).format(schema=sql.Identifier(schema)))
                        self.assertGreater(cursor.rowcount, 0)
                    with self.assertRaises(StorageError) as error:
                        store.verify()
                    self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")

    def test_stale_generated_keys_cannot_hide_rows_from_restore_verification(self):
        from psycopg import sql
        self.assertEqual(self.s.execute(create_command("stale-key", "subject"), create_matter)["status"], "success")
        with connect() as conn:
            original = conn.execute("SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname=%s AND p.proname='identity_key'", (self.schema,)).fetchone()[0]
            changed = original.replace("convert_to($1, 'UTF8')", "convert_to($1 || 'corrupt', 'UTF8')")
            self.assertNotEqual(original, changed)
            conn.execute(changed)
            conn.execute("SET LOCAL session_replication_role=replica")
            for table in ("versions", "commands", "heads", "watches"):
                conn.execute(sql.SQL("UPDATE {}.{} SET scope_id=scope_id").format(sql.Identifier(self.schema), sql.Identifier(table)))
            conn.execute(original)
            self.assertEqual(conn.execute(sql.SQL("SELECT count(*) FROM {}.versions WHERE scope_id=%s").format(
                sql.Identifier(self.schema)), (SCOPE,)).fetchone()[0], 2)
        with self.assertRaises(StorageError) as error:
            self.s.verify()
        self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")

    def test_unicode_identifiers_work_with_host_client_encoding_and_restore_it(self):
        connection = connect()
        self.addCleanup(connection.close)
        connection.autocommit = True
        connection.execute("SET client_encoding='LATIN1'")
        released = []
        def release(conn):
            self.assertEqual(conn.execute("SHOW client_encoding").fetchone(), ("LATIN1",))
            self.assertEqual(conn.info.transaction_status.name, "IDLE")
            released.append(True)
        with PostgreSQLStore(lambda: connection, release=release, schema=self.schema, scope_id=SCOPE) as store:
            command = create_command("unicode-🐙", "subject-🐙")
            result = store.execute(command, create_matter)
            self.assertEqual(result["status"], "success", result)
            self.assertEqual(store.get(result["body"]["matter"])["id"], "subject-🐙")
            self.assertEqual(store.verify()["commands"], 1)
        self.assertGreaterEqual(len(released), 4)

    def test_schema_operator_cannot_shadow_builtin_trigger_checks(self):
        from psycopg import sql
        helper = schema_name()
        self.addCleanup(drop_schema, helper)
        with connect() as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(helper)))
            conn.execute(sql.SQL("CREATE FUNCTION {}.shadow(text,text) RETURNS boolean LANGUAGE plpgsql "
                "AS $$BEGIN RAISE EXCEPTION 'shadow operator invoked'; END;$$").format(sql.Identifier(helper)))
            conn.execute(sql.SQL("CREATE OPERATOR {}.<> (LEFTARG=text, RIGHTARG=text, FUNCTION={}.shadow)").format(
                sql.Identifier(self.schema), sql.Identifier(helper)))
        result = self.s.execute(create_command("operator", "subject"), create_matter)
        self.assertEqual(result["status"], "success", result)
        original = self.s.get(result["body"]["matter"])
        change = mutation_command("operator-change", original, label="changed", child_id="child", projection_id="projection")
        self.assertEqual(self.s.execute(change, rewrite_with_children)["status"], "success")
        self.assertEqual(self.s.verify()["commands"], 2)

    def test_disabled_internal_foreign_key_checks_and_actions_are_refused(self):
        from psycopg import sql
        for function in ("RI_FKey_check_ins", "RI_FKey_noaction_del"):
            with self.subTest(function=function):
                with connect() as conn:
                    name = conn.execute("SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid "
                        "WHERE n.nspname=%s AND c.relname='versions' AND t.tgisinternal AND p.proname=%s "
                        "ORDER BY t.tgname LIMIT 1", (self.schema, function)).fetchone()[0]
                    conn.execute(sql.SQL("ALTER TABLE {}.versions DISABLE TRIGGER {}").format(
                        sql.Identifier(self.schema), sql.Identifier(name)))
                try:
                    with self.assertRaises(StorageError) as error:
                        self.store(initialize=False)
                    self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")
                    self.assert_error(self.s.execute(create_command("fk", "subject"), create_matter), "E_STORAGE_UNAVAILABLE")
                    with self.assertRaises(StorageError) as error:
                        self.s.verify()
                    self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")
                finally:
                    with connect() as conn:
                        conn.execute(sql.SQL("ALTER TABLE {}.versions ENABLE TRIGGER {}").format(
                            sql.Identifier(self.schema), sql.Identifier(name)))

    def test_snapshot_remains_consistent_while_writer_commits(self):
        command = create_command("seed", "subject")
        original_result = self.s.execute(command, create_matter)
        original = self.s.get(original_result["body"]["matter"])
        other = self.store()
        change = mutation_command("change", original, label="changed", child_id="child", projection_id="projection")
        with self.s.snapshot() as view:
            self.assertEqual(view.get(entity_ref(original)), original)
            result = other.execute(change, rewrite_with_children)
            self.assertEqual(result["status"], "success", result)
            self.assertEqual(view.get(entity_ref(original)), original)
            self.assertEqual(view.history(entity_ref(original)), [original])
        self.assertEqual(self.s.get(entity_ref(original))["revision"], 2)

    def test_snapshot_of_initially_empty_scope_does_not_gain_new_rows(self):
        other = self.store()
        command = create_command("later", "new")
        with self.s.snapshot() as view:
            self.assertEqual(view.watchers(WATCH_KEY), [])
            result = other.execute(command, create_matter)
            with self.assertRaises(StorageError) as error:
                view.get(result["body"]["matter"])
            self.assertEqual(error.exception.code, "E_NOT_FOUND")
        self.assertEqual(self.s.get(result["body"]["matter"])["id"], "new")

    def test_independent_processes_cannot_both_create_an_absent_identity(self):
        context = multiprocessing.get_context("spawn")
        gate, output = context.Barrier(2), context.Queue()
        children = [context.Process(target=_child, args=(dsn(), self.schema,
                    create_command("race-" + str(i), "same"), None, gate, output)) for i in range(2)]
        for child in children:
            child.start()
        for child in children:
            child.join(30)
            if child.is_alive():
                child.kill(); child.join()
                self.fail("PostgreSQL writer did not terminate.")
            self.assertEqual(child.exitcode, 0)
        results = [output.get(timeout=5) for _ in children]
        output.close(); output.join_thread()
        self.assertEqual(sum(r["status"] == "success" for r in results), 1, results)
        self.assertEqual([r["error"]["code"] for r in results if r["status"] == "failure"],
                         ["E_SOURCE_IDENTITY_CONFLICT"])
        self.assertEqual(self.s.verify()["commands"], 2)

    def test_negative_watch_read_waits_for_prior_writer_and_cannot_commit_stale_absence(self):
        from threading import Event
        entered, release = Event(), Event()
        writer = self.store()
        def seed(tx):
            result = create_matter(tx)
            tx.put_projection(projection_ref("watcher"), domain_value({"new": True}), watch_keys=(WATCH_KEY,))
            entered.set()
            if not release.wait(10):
                raise AssertionError("Test gate timed out.")
            return result
        observed = []
        def discover(tx):
            observed.extend(tx.watchers(WATCH_KEY))
            return create_matter(tx)
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(writer.execute, create_command("watch", "source"), seed)
            self.assertTrue(entered.wait(10))
            waiting_pid, connected = [], Event()
            def waiting_factory():
                connection = connect()
                waiting_pid.append(connection.info.backend_pid)
                connected.set()
                return connection
            self.s._factory = waiting_factory
            second = pool.submit(self.s.execute, create_command("discover", "derived"), discover)
            try:
                self.assertTrue(connected.wait(2), "Second writer did not connect.")
                import time
                deadline = time.monotonic() + 3
                with connect() as probe:
                    while not probe.execute("SELECT 1 FROM pg_locks WHERE pid=%s "
                            "AND locktype='advisory' AND NOT granted", (waiting_pid[0],)).fetchone():
                        if second.done() or time.monotonic() >= deadline:
                            self.fail("Second writer never waited on the scope lock.")
                        time.sleep(0.01)
            finally:
                release.set()
            self.assertEqual(first.result()["status"], "success")
            # A now-existing watcher needs its declared pin; it cannot look absent.
            self.assert_error(second.result(), "E_REVISION_CONFLICT")
        self.assertEqual(observed, [])
        self.assertEqual(len(self.s.watchers(WATCH_KEY)), 1)

    def test_independent_processes_cannot_both_mutate_one_expected_revision(self):
        seed = self.s.execute(create_command("seed", "subject"), create_matter)
        initial = self.s.get(seed["body"]["matter"])
        context = multiprocessing.get_context("spawn")
        gate, output = context.Barrier(2), context.Queue()
        commands = [mutation_command("change-" + str(i), initial, label=str(i),
                    child_id="child-" + str(i), projection_id="projection-" + str(i)) for i in range(2)]
        children = [context.Process(target=_child, args=(dsn(), self.schema, command, None, gate, output)) for command in commands]
        for child in children:
            child.start()
        for child in children:
            child.join(30)
            if child.is_alive():
                child.kill(); child.join(); self.fail("Concurrent writer timed out.")
            self.assertEqual(child.exitcode, 0)
        results = [output.get(timeout=5) for _ in children]
        output.close(); output.join_thread()
        self.assertEqual(sum(r["status"] == "success" for r in results), 1, results)
        self.assertEqual([r["error"]["code"] for r in results if r["status"] == "failure"], ["E_REVISION_CONFLICT"])
        self.assertEqual(self.s.get(entity_ref(initial))["revision"], 2)
        self.assertEqual(len(self.s.watchers(WATCH_KEY)), 1)
        self.assertEqual(self.s.verify()["commands"], 3)

    def test_bounded_scope_lock_failure_is_not_journaled_and_other_scope_progresses(self):
        short = self.store(timeout=0.02)
        for timeout in (0, 0.02):
            short._timeout = timeout
            blocker = self.s._open()
            try:
                self.s._start(blocker, write=True)
                self.s._lock(blocker, "scope", SCOPE)
                command = create_command("blocked-" + str(timeout), "blocked-" + str(timeout))
                self.assert_error(short.execute(command, create_matter), "E_STORAGE_UNAVAILABLE")
                with self.assertRaises(StorageError) as error:
                    self.s.command_receipt(command["idempotency_key"])
                self.assertEqual(error.exception.code, "E_NOT_FOUND")
                other = self.store(scope="synthetic:other")
                self.assertEqual(other.execute(create_command("free-" + str(timeout), "free-" + str(timeout),
                                 scope_id="synthetic:other"), create_matter)["status"], "success")
            finally:
                self.s._rollback(blocker); blocker.close()
            self.assertEqual(short.execute(command, create_matter)["status"], "success")

    def test_process_death_before_and_after_commit_preserves_exact_outcome(self):
        context = multiprocessing.get_context("spawn")
        for stage in ("before_receipt", "before_commit", "after_commit"):
            with self.subTest(stage=stage):
                command = create_command(stage, stage)
                child = context.Process(target=_child, args=(dsn(), self.schema, command, stage, None, None))
                child.start(); child.join(30)
                if child.is_alive():
                    child.kill(); child.join(); self.fail("Crash test did not terminate.")
                self.assertEqual(child.exitcode, 73)
                calls = []
                def handler(tx):
                    calls.append(True)
                    return create_matter(tx)
                if stage != "after_commit":
                    with self.assertRaises(StorageError) as error:
                        self.s.command_receipt(command["idempotency_key"])
                    self.assertEqual(error.exception.code, "E_NOT_FOUND")
                result = self.s.execute(command, handler)
                self.assertEqual(result["status"], "success", result)
                self.assertEqual(len(calls), 0 if stage == "after_commit" else 1)
                self.assertEqual(self.s.execute(command, handler), result)
                self.assertEqual(len(calls), 0 if stage == "after_commit" else 1)
        self.assertEqual(self.s.verify()["commands"], 3)

    def test_lost_commit_acknowledgment_returns_unknown_then_exact_retry(self):
        import psycopg
        def fault(stage):
            if stage == "after_commit":
                raise psycopg.OperationalError("synthetic secret not disclosed")
        writer = self.store(fault_hook=fault)
        command = create_command("uncertain", "subject")
        result = writer.execute(command, create_matter)
        self.assert_error(result, "E_STORAGE_UNAVAILABLE")
        self.assertNotIn("synthetic secret", repr(result))
        result = self.s.execute(command, lambda tx: self.fail("Committed handler ran twice."))
        self.assertEqual(result["status"], "success")

    def test_borrowed_active_transaction_is_rejected_untouched(self):
        with connect() as conn:
            conn.execute("CREATE TEMP TABLE uncommitted_host_work (value integer)")
            conn.execute("INSERT INTO uncommitted_host_work VALUES (42)")
            released = []
            with self.assertRaises(StorageError):
                PostgreSQLStore(lambda: conn, release=lambda c: released.append(c), schema=self.schema, scope_id=SCOPE)
            self.assertFalse(conn.closed)
            self.assertEqual(conn.info.transaction_status.name, "INTRANS")
            self.assertEqual(conn.execute("SELECT value FROM uncommitted_host_work").fetchone(), (42,))
            self.assertEqual(released, [])
            conn.rollback()

    def test_real_pool_leases_restore_connection_settings_and_release_on_failure(self):
        from psycopg_pool import ConnectionPool
        with ConnectionPool(dsn(), min_size=1, max_size=1, timeout=2) as pool:
            store = PostgreSQLStore(pool.getconn, release=pool.putconn, schema=self.schema, scope_id=SCOPE)
            command = create_command("pool", "pool")
            def fail(tx):
                create_matter(tx)
                raise RuntimeError("synthetic handler fault")
            with self.assertRaises(RuntimeError):
                store.execute(command, fail)
            with pool.connection() as conn:
                self.assertFalse(conn.autocommit)
                self.assertEqual(conn.info.transaction_status.name, "IDLE")
                self.assertNotIn(self.schema, conn.execute("SHOW search_path").fetchone()[0])
            self.assertEqual(store.execute(command, create_matter)["status"], "success")
            store.close()
            with pool.connection() as conn:
                self.assertEqual(conn.execute("SELECT 1").fetchone(), (1,))

    def test_nested_operation_cannot_commit_outer_work_or_escape_view_lifetime(self):
        retained = []
        def handler(tx):
            retained.append(tx)
            nested = self.s.execute(create_command("nested", "nested"), create_matter)
            self.assert_error(nested, "E_STORAGE_UNAVAILABLE")
            return create_matter(tx)
        self.assertEqual(self.s.execute(create_command("outer", "outer"), handler)["status"], "success")
        with self.assertRaises(StorageError):
            retained[0].get(entity_ref(create_command("nested", "nested")["body"]["matter"]))
        self.assertEqual(self.s.verify()["commands"], 1)

    def test_migration_rolls_back_ddl_and_never_relabels_foreign_schema(self):
        from psycopg import sql
        fresh = schema_name()
        self.addCleanup(drop_schema, fresh)
        def fault(stage):
            if stage == "migration:1:ddl":
                raise RuntimeError("migration interrupted")
        with self.assertRaises(RuntimeError):
            PostgreSQLStore(connect, schema=fresh, scope_id=SCOPE, fault_hook=fault)
        with connect() as conn:
            self.assertIsNone(conn.execute("SELECT oid FROM pg_namespace WHERE nspname=%s", (fresh,)).fetchone())
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(fresh)))
            conn.execute(sql.SQL("CREATE TABLE {}.foreign_data(value text)").format(sql.Identifier(fresh)))
            conn.execute(sql.SQL("INSERT INTO {}.foreign_data VALUES ('keep')").format(sql.Identifier(fresh)))
        with self.assertRaises(StorageError) as error:
            PostgreSQLStore(connect, schema=fresh, scope_id=SCOPE)
        self.assertEqual(error.exception.code, "E_SCHEMA_INVALID")
        with connect() as conn:
            self.assertEqual(conn.execute(sql.SQL("SELECT * FROM {}.foreign_data").format(sql.Identifier(fresh))).fetchall(), [("keep",)])

    def test_process_death_during_migration_leaves_no_partial_schema(self):
        context = multiprocessing.get_context("spawn")
        for stage in ("migration:1:ddl", "migration:before_commit"):
            fresh = schema_name()
            self.addCleanup(drop_schema, fresh)
            child = context.Process(target=_migration_child, args=(dsn(), fresh, stage))
            child.start(); child.join(30)
            if child.is_alive():
                child.kill(); child.join(); self.fail("Migration crash test did not terminate.")
            self.assertEqual(child.exitcode, 73)
            with connect() as conn:
                self.assertIsNone(conn.execute("SELECT oid FROM pg_namespace WHERE nspname=%s", (fresh,)).fetchone())
            with PostgreSQLStore(connect, schema=fresh, scope_id=SCOPE) as recovered:
                self.assertEqual(recovered.verify()["commands"], 0)

    def test_unknown_schema_version_and_trigger_damage_fail_closed(self):
        from psycopg import sql
        with connect() as conn:
            conn.execute(sql.SQL("UPDATE {}.schema_migrations SET version=2").format(sql.Identifier(self.schema)))
        with self.assertRaises(StorageError) as error:
            self.store()
        self.assertEqual(error.exception.code, "E_VERSION_UNSUPPORTED")
        with connect() as conn:
            conn.execute(sql.SQL("UPDATE {}.schema_migrations SET version=1").format(sql.Identifier(self.schema)))
            conn.execute(sql.SQL("ALTER TABLE {}.versions DISABLE TRIGGER versions_identity").format(sql.Identifier(self.schema)))
        self.assert_error(self.s.execute(create_command("damaged", "damaged"), create_matter), "E_STORAGE_UNAVAILABLE")

    def test_integrity_bypassing_session_settings_are_refused(self):
        def factory():
            conn = connect()
            conn.execute("SET session_replication_role=replica")
            conn.commit()
            return conn
        with self.assertRaises(StorageError) as error:
            PostgreSQLStore(factory, schema=self.schema, scope_id=SCOPE)
        self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")

    def test_missing_head_is_not_a_successful_restore(self):
        from psycopg import sql
        self.s.execute(create_command("head", "head"), create_matter)
        with connect() as conn:
            conn.execute(sql.SQL("DELETE FROM {}.heads WHERE namespace='example'").format(sql.Identifier(self.schema)))
        with self.assertRaises(StorageError):
            self.s.verify()

    def test_exact_bytes_and_full_verification_detect_corrupted_payload_record(self):
        from psycopg import sql
        command = create_command("bytes", "bytes", title="é / e\u0301 / 🐙")
        result = self.s.execute(command, create_matter)
        record = self.s.get(result["body"]["matter"])
        with connect() as conn:
            stored = conn.execute(sql.SQL("SELECT content FROM {}.versions WHERE namespace='example'").format(sql.Identifier(self.schema))).fetchone()[0]
            self.assertEqual(stored, canonical_bytes(record))
            conn.execute("SET LOCAL session_replication_role=replica")
            conn.execute(sql.SQL("UPDATE {}.versions SET content=%s WHERE namespace='example'").format(sql.Identifier(self.schema)),
                         (b'{}',))
        with self.assertRaises(StorageError) as error:
            self.s.verify()
        self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")


class PostgreSQLClaimRaceTests(PostgresCase):
    """Both host snapshots are admitted; the durable logical lens must exclude
    concurrent callbacks even across revision IDs and native matter IDs.
    """
    def setUp(self):
        super().setUp()
        from integration import test_assessment_commit, test_assistant_review_memory as reviews
        from integration.postgres_helpers import install_backend
        install_backend(self)
        self.first = reviews.ReviewTests("runTest")
        self.first.setUp()
        self.addCleanup(self.first.doCleanups)
        self.assertIsInstance(self.first.f.storage, PostgreSQLStore)

    def _race(self, variant):
        from concurrent.futures import wait, FIRST_COMPLETED
        from copy import copy, deepcopy
        from threading import Barrier, Event, Lock
        from matter.access import AccessService, HostAccessPolicy
        from matter.assistant_review import ReviewHost, pressure_ref
        from matter.contracts import ContractError
        from matter.controls import ControlService
        from matter.storage import pin
        first = self.first
        second = copy(first)
        second.f = copy(first.f)
        second.artifacts = dict(first.artifacts)
        second.serial = 1000  # distinct pressure command identities in one ledger
        second.lens = deepcopy(first.lens)
        if variant == "revision":
            second.lens["revision_id"] = "approved-2"
            second.source = second.artifact("evidence", "rev2-source", "source_fact", {"text": "synthetic new material"})
            second.assessment = second.artifact("judgment", "rev2-assessment", "jev_judgment", {}, citations=[second.source])
            second.control = second.artifact("control", "rev2-control", "host_control", {"current": "approved-2"})
        else:
            created = first.f.storage.execute(create_command("other-matter", "other-matter", scope_id=first.f.storage.scope_id), create_matter)
            self.assertEqual(created["status"], "success", created)
            second.f.subject = first.f.storage.get(created["body"]["matter"])
        store = PostgreSQLStore(connect, schema=first.f.storage.schema, scope_id=first.f.storage.scope_id, initialize=False)
        self.addCleanup(store.close)
        second.f.storage = store
        second.f.controls = ControlService(store, policy=first.f.controls.policy, clock=lambda: deepcopy(first.f.now))
        second.native = [pin(second.f.subject), pin(second.f.source)]
        second.access = AccessService(policy=HostAccessPolicy(scope_id=store.scope_id,
            audiences=[second.audience], providers=[{"reference": second.provider, "provider": "synthetic", "transport": "fixture"}],
            grants=[{"reference": r, "audiences": [second.audience], "providers": [second.provider]} for r in second.native]),
            controls=second.f.controls, current_read=store.snapshot)
        second.token = second.f.controls.capture(actor=second.f.actor, authority=entity_ref(second.f.authority),
            capability="assessment", targets=[entity_ref(r) for r in second.native])
        with store.snapshot() as view:
            second.access_context = second.access.capture(view, token=second.token, audience=second.audience,
                provider=second.provider, references=second.native)
        second.host = ReviewHost(binding=second.lens["host"], require_current=second.current,
            require_read=second.read, resolve=second.read_artifact)
        second.service = second.make_service(store, second.f.controls, second.access)
        second.request = second.req()
        first.add(); second.add()
        self.assertNotEqual(first.request.wake_id, second.request.wake_id)
        self.assertNotEqual(pressure_ref(store.scope_id, first.request), pressure_ref(store.scope_id, second.request))
        barrier, entered, release, guard = Barrier(2), Event(), Event(), Lock()
        calls = []
        original_actions = []
        for fixture in (first, second):
            original = fixture.service._action
            original_actions.append(original)
            def gated(action, request, _original=original, **kwargs):
                if action == "start":
                    barrier.wait(timeout=10)
                return _original(action, request, **kwargs)
            fixture.service._action = gated
        def run(fixture):
            def reviewer(value, wake_id):
                with guard:
                    calls.append(wake_id)
                entered.set()
                if not release.wait(10):
                    raise AssertionError("Synthetic callback gate timed out.")
                return fixture.result(fixture.request, status="unknown")
            try:
                return fixture.execute(reviewer=reviewer)
            except ContractError as error:
                return error.code
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(run, fixture) for fixture in (first, second)]
            try:
                self.assertTrue(entered.wait(10), "Neither request acquired a review claim.")
                done, _ = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
                self.assertEqual(len(done), 1, "The losing request did not refuse while the winning callback was in flight.")
                self.assertEqual(len(calls), 1, "Both logical-lens callbacks ran concurrently.")
                # A global control-sequence conflict can mask a broken lens key.
                # Retry with fresh pins while the first callback is still held:
                # only the shared durable logical-lens lock can refuse this start.
                index = futures.index(next(iter(done)))
                loser = (first, second)[index]
                loser.service._action = original_actions[index]
                with self.assertRaises(ContractError) as blocked:
                    loser.service.claim(loser.request, token=loser.token, access_context=loser.access_context)
                self.assertEqual(blocked.exception.code, "E_DELIVERY_UNKNOWN")
            finally:
                release.set()
            outcomes = [future.result(timeout=10) for future in futures]
        self.assertEqual(len(calls), 1, outcomes)
        self.assertEqual(sum(isinstance(row, dict) and row["value"]["value"]["phase"] == "unknown" for row in outcomes), 1, outcomes)
        for row in outcomes:
            if isinstance(row, str):
                self.assertIn(row, ("E_REVISION_CONFLICT", "E_DELIVERY_UNKNOWN", "E_IDEMPOTENCY_CONFLICT"))
        for fixture in (first, second):
            self.assertEqual(fixture.pending(), fixture.request.value["contributions"])
        store.verify()

    def test_concurrent_review_claims_across_lens_revisions_allow_one_callback(self):
        self._race("revision")

    def test_concurrent_review_claims_across_native_matters_allow_one_callback(self):
        self._race("matter")


def load_tests(loader, standard, pattern):
    from integration import (test_storage_transactions as transactions, test_storage_boundaries as boundaries,
                            test_storage_identity_lookup as identities, test_transaction_hook as hooks,
                            test_dependency_conflict_code as conflicts, test_control_storage as controls,
                            test_assistant_review_memory as reviews,
                            test_assessment_history_growth as history)
    suite = unittest.TestSuite([standard])
    suite.addTest(reuse_cases(loader, transactions, "StorageTransactionTests", exclude=(
        "test_consistent_snapshot_blocks_writer_commit_until_read_boundary_closes",
        "test_unavailable_database_queries_raise_errors_instead_of_empty_results",
        "test_busy_writer_returns_unavailable_and_exact_retry_can_commit")))
    suite.addTest(reuse_cases(loader, boundaries, "StorageBoundaryTests", exclude=(
        "test_removed_source_cannot_be_backed_up_as_an_empty_database",
        "test_invalid_timeouts_are_semantic_errors_and_zero_lock_wait_can_back_up",
        "test_foreign_table_resembling_internal_prefix_is_refused_before_journal_changes")))
    for module, name in ((identities, "StorageIdentityLookupTests"), (hooks, "TransactionHookTests"),
                         (conflicts, "DependencyConflictCodeTests"), (controls, "ControlStorageTests")):
        suite.addTest(reuse_cases(loader, module, name))
    suite.addTest(reuse_cases(loader, reviews, "ReviewTests", include=(
        "test_two_real_sqlite_handles_cannot_launch_the_same_wake_twice",
        "test_duplicate_routes_time_and_limits_do_not_rerun_after_restart",
        "test_claimed_crash_and_provider_exception_remain_unknown_never_retried",
        "test_exact_completion_and_pressure_retries_do_not_touch_new_arrivals",
        "test_overlapping_lens_wakes_wait_for_first_review_instead_of_concurrent_callbacks",
        "test_explicit_reconciliation_releases_unknown_without_clearing_pressure_or_rerunning",
        "test_reconciliation_retry_is_idempotent_and_new_revision_cannot_bypass_unknown",
        "test_multiple_matters_have_separate_pressure_under_one_objective_session_lock",
        "test_reconciliation_honors_active_correction_denial",
        "test_metadata_history_spans_native_revisions_with_present_snapshot_grants",
        "test_history_uses_reader_grants_not_the_writer_for_omitted_dependencies")))
    suite.addTest(reuse_cases(loader, history, "AssessmentHistoryGrowth"))
    return suite
