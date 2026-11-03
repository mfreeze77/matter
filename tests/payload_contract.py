"""Reusable exact-byte PayloadStore checks; adapters supply two scoped handles."""

from matter.canonical import source_digest
from matter.storage import StorageError


def content(data):
    return {"digest": source_digest(data), "byte_length": len(data), "media_type": "application/octet-stream",
            "locator": {"kind": "whole_artifact", "uri": "urn:synthetic:never-fetch"},
            "availability": {"status": "available", "checked_at": {"state": "known",
                "value": "2026-11-02T00:00:00Z", "precision": "second"}}}


class PayloadContract:
    """Use with unittest.TestCase and set self.payloads/self.foreign in setUp."""
    def test_exact_bytes_and_idempotent_publication(self):
        for data in (b"", b"\x00\xffraw-response", 'é/e\u0301/🐙'.encode()):
            self.assertEqual(self.payloads.put(data), source_digest(data))
            self.assertEqual(self.payloads.put(data), source_digest(data))
            read = self.payloads.read(content(data))
            self.assertEqual((read.status, read.data, read.reason), ("available", data, None))

    def test_scope_and_missing_bytes_are_not_successful_empty_evidence(self):
        data = b"scoped evidence"
        self.payloads.put(data)
        self.assertEqual(self.foreign.read(content(data)).status, "unavailable")
        missing = self.payloads.read(content(b"never stored"))
        self.assertEqual((missing.status, missing.data), ("unavailable", None))

    def test_declared_withholding_and_unavailability_prevent_byte_reads(self):
        data = b"withhold evidence"
        self.payloads.put(data)
        for status in ("withheld", "unavailable"):
            ref = content(data)
            ref["availability"].update(status=status, reason="Synthetic host decision.")
            result = self.payloads.read(ref)
            self.assertEqual((result.status, result.data), (status, None))

    def test_wrong_byte_length_and_invalid_inputs_are_refused(self):
        data = b"length-bound"
        self.payloads.put(data)
        ref = content(data); ref["byte_length"] += 1
        with self.assertRaises(StorageError) as error:
            self.payloads.read(ref)
        self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")
        with self.assertRaises(StorageError):
            self.payloads.put("not bytes")
