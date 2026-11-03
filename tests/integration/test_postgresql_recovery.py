"""Real dump/restore of synthetic ledger, host payloads, pressure and unknown wake.

Requires an explicitly named disposable matter-mat092-* Docker test container.
No backup script, deployment mount or host StateCivics code is created here.
"""
from copy import deepcopy
import os
import subprocess
from uuid import uuid4

from matter.access import AccessService
from matter.controls import ControlService
from matter.storage import PostgreSQLStore
from integration import test_assistant_review_memory as reviews
from integration import test_assessment_commit  # load fixture factory before adaptation
from integration.host_payload_fixture import HostPayloadFixture
from integration.helpers import create_command, create_matter, domain_value, projection_ref
from integration.postgres_helpers import PostgresCase, connect, dsn, install_backend
from payload_contract import content


class PostgreSQLRecoveryTests(PostgresCase):
    def test_short_and_quoted_schema_names_preserve_catalog_function_bodies(self):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        container = os.environ.get("MATTER_TEST_POSTGRES_CONTAINER", "")
        if not container.startswith("matter-mat092-"):
            self.skipTest("Set MATTER_TEST_POSTGRES_CONTAINER for the disposable schema-name database.")
        user = conninfo_to_dict(dsn()).get("user", "postgres")
        target = "mat_test_restore_" + uuid4().hex
        def run(*arguments):
            subprocess.run(["docker", "exec", container, *arguments], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        run("createdb", "-U", user, target)
        try:
            factory = lambda: psycopg.connect(make_conninfo(dsn(), dbname=target), connect_timeout=5)
            for schema in ("type", "e", "only", "select"):
                with self.subTest(schema=schema), PostgreSQLStore(factory, schema=schema, scope_id="synthetic:storage") as store:
                    result = store.execute(create_command("short-schema", "subject"), create_matter)
                    self.assertEqual(result["status"], "success", result)
                    self.assertEqual(store.get(result["body"]["matter"])["id"], "subject")
                    self.assertEqual(store.verify()["commands"], 1)
        finally:
            run("dropdb", "-U", user, "--force", target)

    def test_dump_restore_preserves_unknown_wake_pressure_and_exact_host_payloads(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        container = os.environ.get("MATTER_TEST_POSTGRES_CONTAINER", "")
        if not container.startswith("matter-mat092-"):
            self.skipTest("Set MATTER_TEST_POSTGRES_CONTAINER to the disposable matter-mat092-* container.")
        install_backend(self)
        fixture = reviews.ReviewTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        ledger = fixture.f.storage
        self.assertIsInstance(ledger, PostgreSQLStore)
        HostPayloadFixture.initialize(connect, self.schema)
        payloads = HostPayloadFixture(connect, self.schema, ledger.scope_id)
        evidence, _ = payloads.register_packet("synthetic-packet", {"id": "packet"}, {"text": "synthetic source"})
        response = b'{"synthetic":"raw model response"}'
        payloads.put(evidence); payloads.put(response)
        payload_reference = projection_ref("host-recovery-payloads", ledger.scope_id)
        def bind_payloads(tx):
            result = create_matter(tx)
            tx.put_projection(payload_reference, domain_value({"evidence": content(evidence), "response": content(response)}))
            return result
        bound = ledger.execute(create_command("bind-host-payloads", "payload-subject", scope_id=ledger.scope_id), bind_payloads)
        self.assertEqual(bound["status"], "success", bound)
        fixture.add()
        acquired, claim = fixture.service.claim(fixture.request, token=fixture.token,
                                                access_context=fixture.access_context)
        self.assertTrue(acquired)
        self.assertEqual(claim["value"]["value"]["phase"], "started")
        before = ledger.verify()
        def ledger_bytes(factory):
            with factory() as conn:
                # Include attribution metadata and materialized heads/watches,
                # not only canonical content and result bytes.
                return tuple(conn.execute(sql.SQL("SELECT * FROM {}.{} WHERE scope_id=%s ORDER BY " + order).format(
                    sql.Identifier(ledger.schema), sql.Identifier(table)), (ledger.scope_id,)).fetchall()
                    for table, order in (("versions", "namespace,id,version"), ("commands", "idempotency_key"),
                                         ("heads", "namespace,id"), ("watches", "watch_key,namespace,id")))
        before_bytes = ledger_bytes(connect)
        settings = conninfo_to_dict(dsn())
        user, source = settings.get("user", "postgres"), settings["dbname"]
        target = "mat_test_restore_" + uuid4().hex
        def run(*arguments, data=None):
            return subprocess.run(["docker", "exec", "-i", container, *arguments], input=data,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=60).stdout
        archive = run("pg_dump", "-U", user, "-d", source, "-Fc", "--schema=" + ledger.schema, "--schema=" + self.schema)
        self.assertLess(len(archive), 16 * 1024 * 1024, "Synthetic recovery artifact exceeded its 16 MiB budget.")
        run("createdb", "-U", user, target)
        try:
            run("pg_restore", "-U", user, "-d", target, "--exit-on-error", "--no-owner", data=archive)
            recovered_dsn = make_conninfo(dsn(), dbname=target)
            factory = lambda: psycopg.connect(recovered_dsn, connect_timeout=5)
            with PostgreSQLStore(factory, schema=ledger.schema, scope_id=ledger.scope_id, initialize=False) as restored:
                self.assertEqual(restored.verify(), before)
                self.assertEqual(ledger_bytes(factory), before_bytes)
                host = HostPayloadFixture(factory, self.schema, ledger.scope_id)
                refs = restored.get(payload_reference)["value"]["value"]
                self.assertEqual(host.read(refs["evidence"]).data, evidence)
                self.assertEqual(host.read(refs["response"]).data, response)
                controls = ControlService(restored, policy=fixture.f.controls.policy, clock=lambda: deepcopy(fixture.f.now))
                access = AccessService(policy=fixture.access.policy, controls=controls, current_read=restored.snapshot)
                fixture.service = fixture.make_service(restored, controls, access)
                self.assertEqual(fixture.pending(), fixture.request.value["contributions"])
                self.assertEqual(fixture.execute()["value"]["value"]["phase"], "started")
                self.assertEqual(fixture.calls, 0, "Restore must not authorize another assistant call.")
                with factory() as conn:
                    conn.execute(host._query("DELETE FROM {}.packets"))
                self.assertEqual(host.read(content(evidence)).status, "unavailable")
                self.assertEqual(fixture.pending(), fixture.request.value["contributions"])
        finally:
            run("dropdb", "-U", user, "--force", target)
