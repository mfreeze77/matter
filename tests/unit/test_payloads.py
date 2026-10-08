"""Exact original-byte storage tests using only synthetic local payloads."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from matter import payloads
from matter.payloads import FilePayloadStore, PayloadRead
from matter.storage import StorageError


def content_for(data: bytes) -> dict:
    return {
        "digest": hashlib.sha256(data).hexdigest(),
        "locator": {"kind": "whole_artifact", "uri": "https://example.invalid/synthetic"},
        "media_type": "application/octet-stream",
        "availability": {
            "status": "available",
            "checked_at": {"state": "unknown", "reason": "not_observed"},
        },
        "byte_length": len(data),
    }


class FilePayloadStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "payloads"
        self.store = FilePayloadStore(self.root, scope_id="synthetic:payloads")

    def blob(self, digest: str) -> Path:
        matches = list(self.root.glob(f"*/{digest}"))
        self.assertEqual(1, len(matches))
        return matches[0]

    def assert_error(self, code: str, operation, *args) -> StorageError:
        with self.assertRaises(StorageError) as caught:
            operation(*args)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_preserves_non_utf8_bytes_empty_payloads_and_normalization_differences(self) -> None:
        samples = (b"\xff\xfe\x00\x80\r\n", b"", "é".encode(), "e\u0301".encode())
        digests = []
        for data in samples:
            with self.subTest(data=data):
                reference = content_for(data)
                digest = self.store.put(data)
                digests.append(digest)
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
                self.assertEqual(PayloadRead("available", digest, data, None), self.store.read(reference))
                self.assertEqual(data, self.blob(digest).read_bytes())
        self.assertEqual(4, len(set(digests)))

    def test_repeated_put_and_reopen_keep_same_blob_and_private_permissions(self) -> None:
        data = b"synthetic source bytes\n"
        digest = self.store.put(data)
        blob = self.blob(digest)
        before = blob.stat()
        for _ in range(3):
            self.assertEqual(digest, self.store.put(data))
        reopened = FilePayloadStore(self.root, scope_id=self.store.scope_id)
        self.assertEqual(data, reopened.read(content_for(data)).data)
        self.assertEqual(digest, reopened.put(data))
        after = blob.stat()
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
        self.assertEqual([blob], list(blob.parent.iterdir()))
        if os.name != "nt":
            self.assertEqual(0o600, stat.S_IMODE(after.st_mode))
            self.assertEqual(0o700, stat.S_IMODE(blob.parent.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(self.root.stat().st_mode))

    def test_missing_payload_is_explicit_and_locator_file_is_not_followed(self) -> None:
        data = b"bytes outside the payload store"
        external = self.parent / "external.bin"
        external.write_bytes(data)
        reference = content_for(data)
        reference["locator"]["uri"] = external.as_uri()
        before = deepcopy(reference)
        result = self.store.read(reference)
        self.assertEqual("unavailable", result.status)
        self.assertEqual(reference["digest"], result.digest)
        self.assertIsNone(result.data)
        self.assertTrue(result.reason)
        self.assertFalse(self.root.exists())
        self.assertEqual(before, reference)

    def test_unavailable_and_withheld_never_open_existing_or_missing_blob(self) -> None:
        data = b"a private synthetic artifact"
        digest = self.store.put(data)
        self.blob(digest).write_bytes(b"corrupt bytes must not be opened for withheld content")
        for status in ("unavailable", "withheld"):
            with self.subTest(status=status):
                reference = content_for(data)
                reference["availability"].update(status=status, reason="synthetic declared absence")
                with patch.object(FilePayloadStore, "_read_blob", side_effect=AssertionError("opened")):
                    result = self.store.read(reference)
                    absent_store = FilePayloadStore(self.parent / "missing-parent" / "store",
                                                   scope_id="other:scope")
                    self.assertEqual(result, absent_store.read(reference))
                self.assertEqual(PayloadRead(status, digest, None, "synthetic declared absence"), result)

    def test_scope_separation_uses_hashes_even_for_path_like_scope_ids(self) -> None:
        data = b"same bytes in two authorized scopes"
        first = FilePayloadStore(self.root, scope_id="../../opaque:é")
        second = FilePayloadStore(self.root, scope_id="../different:é")
        digest = first.put(data)
        self.assertEqual("unavailable", second.read(content_for(data)).status)
        self.assertEqual(digest, second.put(data))
        directories = list(self.root.iterdir())
        self.assertEqual(2, len(directories))
        for directory in directories:
            self.assertRegex(directory.name, r"^[0-9a-f]{64}$")
            self.assertEqual(self.root, directory.parent)
            self.assertEqual(data, (directory / digest).read_bytes())
        self.assertEqual(2, len({(directory / digest).stat().st_ino for directory in directories}))
        self.assertEqual(data, first.read(content_for(data)).data)
        self.assertEqual(data, second.read(content_for(data)).data)

    def test_digest_corruption_is_evidence_invalid_and_put_never_repairs_it(self) -> None:
        original = b"original"
        digest = self.store.put(original)
        blob = self.blob(digest)
        corrupt = b"changed!"  # Same length, so digest validation is exercised.
        self.assertEqual(len(original), len(corrupt))
        blob.write_bytes(corrupt)
        self.assert_error("E_EVIDENCE_INVALID", self.store.read, content_for(original))
        self.assert_error("E_EVIDENCE_INVALID", self.store.put, original)
        self.assertEqual(corrupt, blob.read_bytes())
        self.assertEqual([blob], list(blob.parent.iterdir()))

    def test_optional_declared_length_is_checked_without_mutating_bytes(self) -> None:
        data = b"length matters"
        digest = self.store.put(data)
        reference = content_for(data)
        reference["byte_length"] += 1
        self.assert_error("E_EVIDENCE_INVALID", self.store.read, reference)
        self.assertEqual(data, self.blob(digest).read_bytes())
        del reference["byte_length"]
        self.assertEqual(data, self.store.read(reference).data)

    def test_invalid_reference_and_nonbytes_inputs_fail_before_blob_access(self) -> None:
        reference = content_for(b"x")
        invalid = []
        for key, value in (("digest", "../../escape"), ("byte_length", True),
                           ("byte_length", 1.0), ("byte_length", -1), ("extra", "unknown")):
            changed = deepcopy(reference)
            changed[key] = value
            invalid.append(changed)
        missing_reason = deepcopy(reference)
        missing_reason["availability"]["status"] = "withheld"
        invalid.append(missing_reason)
        inconsistent = deepcopy(reference)
        inconsistent["locator"] = {"kind": "unavailable", "reason": "no source locator"}
        invalid.append(inconsistent)
        with patch.object(FilePayloadStore, "_read_blob", side_effect=AssertionError("opened")):
            for value in invalid:
                with self.subTest(value=value):
                    self.assert_error("E_SCHEMA_INVALID", self.store.read, value)
        for value in ("text", bytearray(b"bytes"), memoryview(b"bytes"), None):
            with self.subTest(type=type(value)):
                self.assert_error("E_SCHEMA_INVALID", self.store.put, value)
        self.assertFalse(self.root.exists())

    def test_scope_and_payload_read_are_immutable_values(self) -> None:
        self.assertEqual("synthetic:payloads", self.store.scope_id)
        with self.assertRaises(AttributeError):
            self.store.scope_id = "different"
        result = self.store.read(content_for(b"missing"))
        with self.assertRaises(FrozenInstanceError):
            result.status = "available"
        for invalid in ("", "scope with spaces", "scope\n", "bad\ud800"):
            with self.subTest(scope=repr(invalid)):
                self.assert_error("E_SCHEMA_INVALID", lambda: FilePayloadStore(self.root, scope_id=invalid))

    def test_content_calendar_is_validated_before_reading_or_honoring_unavailability(self) -> None:
        for status in ("available", "unavailable", "withheld"):
            with self.subTest(status=status):
                reference = content_for(b"synthetic")
                reference["availability"] = {
                    "status": status,
                    "reason": "synthetic reason",
                    "checked_at": {
                        "state": "known", "value": "2026-02-30T00:00:00Z",
                        "precision": "second",
                    },
                }
                with patch.object(FilePayloadStore, "_read_blob", side_effect=AssertionError("opened")):
                    self.assert_error("E_SCHEMA_INVALID", self.store.read, reference)

    def test_concurrent_publishers_verify_winner_and_leave_one_complete_blob(self) -> None:
        data = b"concurrent original bytes" * 1024
        digest = hashlib.sha256(data).hexdigest()
        barrier = threading.Barrier(4)
        real_link = os.link

        def publish(source, destination):
            barrier.wait(timeout=5)
            return real_link(source, destination)

        with patch.object(payloads.os, "link", side_effect=publish):
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(self.store.put, data) for _ in range(4)]
                results = [future.result(timeout=10) for future in futures]
        self.assertEqual([digest] * 4, results)
        blob = self.blob(digest)
        self.assertEqual([blob], list(blob.parent.iterdir()))
        self.assertEqual(data, self.store.read(content_for(data)).data)

    def test_publish_race_never_overwrites_a_conflicting_blob(self) -> None:
        data = b"original"
        corrupt = b"changed!"

        def conflict(source, destination):
            Path(destination).write_bytes(corrupt)
            raise FileExistsError("synthetic publication race")

        with patch.object(payloads.os, "link", side_effect=conflict):
            self.assert_error("E_EVIDENCE_INVALID", self.store.put, data)
        blob = self.blob(hashlib.sha256(data).hexdigest())
        self.assertEqual(corrupt, blob.read_bytes())
        self.assertEqual([blob], list(blob.parent.iterdir()))

    def test_failed_file_sync_does_not_publish_or_leave_partial_staging_bytes(self) -> None:
        data = b"never committed payload"
        real_fsync = os.fsync

        def fail_file_sync(descriptor):
            if stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError("private-source-path must not escape")
            return real_fsync(descriptor)

        with patch.object(payloads.os, "fsync", side_effect=fail_file_sync):
            error = self.assert_error("E_STORAGE_UNAVAILABLE", self.store.put, data)
        self.assertNotIn("private-source-path", str(error))
        self.assertEqual("unavailable", self.store.read(content_for(data)).status)
        self.assertEqual([], [path for path in self.root.rglob("*") if path.is_file()])

    def test_failed_directory_sync_keeps_published_blob_and_retry_verifies_it(self) -> None:
        data = b"published before directory sync failed"
        real_sync = payloads._fsync_directory

        def fail_scope_sync(path):
            if path.parent == self.root:
                raise OSError("synthetic directory synchronization failure")
            return real_sync(path)

        with patch.object(payloads, "_fsync_directory", side_effect=fail_scope_sync):
            self.assert_error("E_STORAGE_UNAVAILABLE", self.store.put, data)
        blob = self.blob(hashlib.sha256(data).hexdigest())
        inode = blob.stat().st_ino
        self.assertEqual(data, blob.read_bytes())
        self.assertEqual(blob.name, self.store.put(data))
        self.assertEqual(inode, blob.stat().st_ino)

    def test_read_io_failure_is_explicit_and_does_not_expose_path_details(self) -> None:
        data = b"stored before simulated I/O failure"
        self.store.put(data)
        with patch.object(payloads.os, "open", side_effect=PermissionError("secret local location")):
            error = self.assert_error("E_STORAGE_UNAVAILABLE", self.store.read, content_for(data))
        self.assertNotIn("secret local location", str(error))
        self.assertTrue(error.retriable)

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlinks are unavailable on this platform.")
    def test_symlink_blob_cannot_supply_bytes_and_is_never_replaced(self) -> None:
        data = b"external bytes at an untrusted blob link"
        digest = self.store.put(data)
        blob = self.blob(digest)
        blob.unlink()
        external = self.parent / "external.bin"
        external.write_bytes(data)
        blob.symlink_to(external)
        self.assert_error("E_EVIDENCE_INVALID", self.store.read, content_for(data))
        self.assert_error("E_EVIDENCE_INVALID", self.store.put, data)
        self.assertTrue(blob.is_symlink())
        self.assertEqual(data, external.read_bytes())

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlinks are unavailable on this platform.")
    def test_scope_directory_cannot_alias_another_scope(self) -> None:
        data = b"scoped original bytes"
        digest = self.store.put(data)
        scope = self.blob(digest).parent
        self.blob(digest).unlink()
        scope.rmdir()
        external = self.parent / "external-scope"
        external.mkdir()
        scope.symlink_to(external, target_is_directory=True)
        self.assert_error("E_STORAGE_UNAVAILABLE", self.store.read, content_for(data))
        self.assert_error("E_STORAGE_UNAVAILABLE", self.store.put, data)
        self.assertEqual([], list(external.iterdir()))


if __name__ == "__main__":
    unittest.main()
