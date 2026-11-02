"""The same payload contract exercised on files and synthetic host PostgreSQL."""
from pathlib import Path
import tempfile
import unittest

from matter.canonical import canonical_bytes, source_digest
from matter.payloads import FilePayloadStore
from matter.storage import StorageError
from integration.host_payload_fixture import HostPayloadFixture
from integration.postgres_helpers import PostgresCase, connect
from payload_contract import PayloadContract, content


class FilePayloadConformance(PayloadContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name) / "payloads"
        self.payloads = FilePayloadStore(root, scope_id="synthetic:payloads")
        self.foreign = FilePayloadStore(root, scope_id="synthetic:foreign")


class HostPayloadConformance(PayloadContract, PostgresCase):
    def setUp(self):
        super().setUp()
        HostPayloadFixture.initialize(connect, self.schema)
        self.payloads = HostPayloadFixture(connect, self.schema, "synthetic:payloads")
        self.foreign = HostPayloadFixture(connect, self.schema, "synthetic:foreign")

    def test_packet_hash_lookup_reconstructs_bytes_instead_of_using_identity_hash(self):
        identity, material = {"id": "packet-1"}, {"text": "synthetic exact evidence", "n": 7}
        data, digest = self.payloads.register_packet("packet-1", identity, material)
        identity_hash = source_digest(canonical_bytes(identity))
        self.assertNotEqual(digest, identity_hash)
        by_identity = {**content(data), "digest": identity_hash}
        refused = self.payloads.read(by_identity)
        self.assertEqual((refused.status, refused.data), ("unavailable", None))
        self.assertEqual(self.payloads.put(data), digest)
        self.assertEqual(self.payloads.read(content(data)).data, canonical_bytes(material))
        # Distinct packet identities can share exact material; no hash substitution.
        second, same = self.payloads.register_packet("packet-2", {"id": "packet-2"}, material)
        self.assertEqual(same, digest)
        self.assertEqual(self.payloads.read(content(second)).data, data)
        self.assertEqual(self.foreign.read(content(data)).status, "unavailable")
        self.payloads.allow = False
        self.assertEqual(self.payloads.read(content(data)).status, "withheld")

    def test_changed_or_missing_packet_cannot_be_repaired_by_a_put(self):
        data, digest = self.payloads.register_packet("packet", {"id": "packet"}, {"text": "original"})
        with connect() as conn:
            conn.execute(self.payloads._query("UPDATE {}.packets SET exact_material=%s"),
                         (canonical_bytes({"text": "changed"}),))
        for call in (lambda: self.payloads.read(content(data)), lambda: self.payloads.put(data)):
            with self.assertRaises(StorageError) as error:
                call()
            self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")
        with connect() as conn:
            conn.execute(self.payloads._query("DELETE FROM {}.packets"))
        self.assertEqual(self.payloads.read(content(data)).status, "unavailable")

    def test_interrupted_publication_and_exact_raw_response_recovery(self):
        for stage in ("before_commit", "after_commit"):
            data = ("raw model response " + stage).encode()
            def fault(at):
                if at == stage:
                    raise StorageError("E_STORAGE_UNAVAILABLE")
            self.payloads.fault = fault
            with self.assertRaises(StorageError):
                self.payloads.put(data)
            self.payloads.fault = None
            self.assertEqual(self.payloads.read(content(data)).status,
                             "unavailable" if stage == "before_commit" else "available")
            self.assertEqual(self.payloads.put(data), source_digest(data))
            reopened = HostPayloadFixture(connect, self.schema, self.payloads.scope_id)
            self.assertEqual(reopened.read(content(data)).data, data)
