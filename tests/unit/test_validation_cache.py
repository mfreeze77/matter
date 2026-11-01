"""Cached structure must not become cached integrity or current authority."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from matter._validation import InvalidValue, ValidationCache
from matter.canonical import CanonicalError, canonical_bytes
from matter.contracts import ContractError, validate_record
from matter.storage import SQLiteStore, StorageError
from integration.helpers import SCOPE, create_command, create_matter


def json_load_fixture():
    import json
    return json.loads((Path(__file__).resolve().parents[1] / "fixtures/contracts/records/matter.json").read_text())


class ValidationCacheTests(unittest.TestCase):
    def test_identical_content_reuses_only_success_and_returns_detached_values(self):
        cache = ValidationCache()
        validator = SimpleNamespace(is_valid=Mock(wraps=Draft202012Validator({"type": "object", "required": ["x"]}).is_valid))
        raw = canonical_bytes({"x": [1]})
        first = cache.checked(raw, validator, "1")
        first["x"].append(2)
        self.assertEqual(cache.checked(raw, validator, "1"), {"x": [1]})
        self.assertEqual(validator.is_valid.call_count, 1)
        self.assertEqual(len(cache._entries), 1)
        for _ in range(2):
            with self.assertRaises(InvalidValue):
                cache.checked(b"{}", validator, "1")
        self.assertEqual(len(cache._entries), 1)

    def test_validator_registry_and_schema_version_are_separate_boundaries(self):
        cache = ValidationCache()
        permissive = Draft202012Validator({"type": "integer"})
        strict = Draft202012Validator({"type": "string"})
        self.assertEqual(cache.checked(b"1", permissive, "1"), 1)
        with self.assertRaises(InvalidValue):
            cache.checked(b"1", strict, "1")
        cache.checked(b"1", permissive, "2")
        self.assertEqual(len(cache._entries), 2)

    def test_digest_collision_still_compares_exact_content(self):
        class Collision:
            def digest(self):
                return b"same"
        cache = ValidationCache()
        validator = Draft202012Validator({"const": {"x": 1}})
        with patch("matter._validation.sha256", return_value=Collision()):
            cache.checked(b'{"x":1}', validator, "1")
            with self.assertRaises(InvalidValue):
                cache.checked(b'{"x":2}', validator, "1")

    def test_bytes_and_entry_count_are_bounded_and_large_values_still_validate(self):
        cache = ValidationCache(max_entries=2, max_bytes=4)
        validator = Draft202012Validator({"type": "string"})
        for raw in (b'"a"', b'"b"', b'"long"'):
            self.assertIsInstance(cache.checked(raw, validator, "1"), str)
            self.assertLessEqual(cache._bytes, 4)
            self.assertLessEqual(len(cache._entries), 2)

    def test_changed_same_identity_and_noncanonical_types_do_not_hit(self):
        value = json_load_fixture()
        validate_record(value)
        changed = deepcopy(value)
        changed["body"].pop("domain_kind")
        with self.assertRaises(ContractError):
            validate_record(changed)
        changed = deepcopy(value)
        changed["revision"] = 1.0
        with self.assertRaises(ContractError):
            validate_record(changed)

    def test_strict_decode_resource_failure_stays_a_safe_contract_error_on_warm_input(self):
        value = json_load_fixture()
        validate_record(value)
        with patch("matter._validation.loads", side_effect=CanonicalError("JSON nesting exceeds implementation capacity")):
            with self.assertRaises(ContractError) as refused:
                validate_record(value)
        self.assertEqual(refused.exception.code, "E_SCHEMA_INVALID")

    def test_warm_storage_read_still_detects_changed_bytes_with_old_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "store.sqlite"
            with SQLiteStore(path, scope_id=SCOPE) as store:
                result = store.execute(create_command("seed", "subject"), create_matter)
                ref = result["body"]["matter"]
                stored = store.get(ref)
                stored["body"]["title"] = "Tampered but schema-valid"
                with sqlite3.connect(path) as db:
                    # Simulate external corruption, bypassing append-only SQL guards.
                    trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='versions_no_update'").fetchone()[0]
                    db.execute("DROP TRIGGER versions_no_update")
                    db.execute("UPDATE versions SET content=? WHERE id=?", (canonical_bytes(stored), stored["id"]))
                    db.execute(trigger)
                with self.assertRaises(StorageError) as refused:
                    store.get(ref)
                self.assertEqual(refused.exception.code, "E_STORAGE_UNAVAILABLE")
                self.assertIn("Stored snapshot integrity", refused.exception.detail)
