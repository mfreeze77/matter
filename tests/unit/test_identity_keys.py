"""Exact subject-key policy and binding integrity with synthetic identities."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import tempfile
import unittest
from uuid import UUID

from matter.contracts import validate_command
from matter.identity_keys import (
    INDEX_NAMESPACE, ExactIdentityPolicy, binding_value, identity_key_ref,
    new_matter_id, read_binding,
)
from matter.storage import SQLiteStore, StorageError, entity_ref, pin
from tests.integration.helpers import create_command


SCOPE = "synthetic:identity"
KEY = {"namespace": "example:subject", "value": "subject:1"}


def matter_ref(identity: str = "matter:1", *, scope_id: str = SCOPE) -> dict:
    return {"scope_id": scope_id, "namespace": "example", "record_type": "matter", "id": identity}


def projection() -> dict:
    return {
        "schema_version": "1.0", **identity_key_ref(SCOPE, KEY), "revision": 1,
        "creation_receipt": {
            "scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "receipt:1",
        },
        "value": binding_value(SCOPE, KEY, [matter_ref()]), "watch_keys": [],
    }


class _View:
    def __init__(self, value=None, error: StorageError | None = None) -> None:
        self.value, self.error = value, error
        self.references = []

    def lookup_identity(self, reference):
        self.references.append(deepcopy(reference))
        if self.error is not None:
            raise self.error
        return self.value

    def get(self, reference):
        raise AssertionError("Typed get can conceal an occupant of another record kind.")


class IdentityPolicyTests(unittest.TestCase):
    def assert_error(self, code: str, operation, *args) -> StorageError:
        with self.assertRaises(StorageError) as caught:
            operation(*args)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_new_matter_ids_are_independently_allocated_opaque_uuid4_values(self) -> None:
        identities = [new_matter_id() for _ in range(32)]
        self.assertEqual(32, len(set(identities)))
        for value in identities:
            self.assertEqual(value, str(UUID(value)))
            self.assertEqual(4, UUID(value).version)

    def test_policy_reference_binds_sorted_configuration_and_versioned_exact_rules(self) -> None:
        expected = {
            "algorithm": "matter.exact-subject-keys.v1",
            "identity": "continuing_subject", "normalization": "none",
            "key_namespaces": ["example:alternate", "example:subject"],
            "key_expansion": "forbidden", "key_rebinding": "forbidden",
        }
        policy = ExactIdentityPolicy(key_namespaces=["example:subject", "example:alternate"])
        encoded = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(b"matter-json-v1\0matter.identity-policy.v1\0" + encoded).hexdigest()
        self.assertEqual(expected, policy.definition)
        self.assertEqual({
            "namespace": "matter", "id": "exact-subject-keys", "version": "1.0", "digest": digest,
        }, policy.reference)
        reordered = ExactIdentityPolicy(key_namespaces=iter(reversed(policy.key_namespaces)))
        self.assertEqual(policy.reference, reordered.reference)
        different = ExactIdentityPolicy(key_namespaces=["example:subject"])
        self.assertNotEqual(policy.reference["digest"], different.reference["digest"])

    def test_policy_and_returned_configuration_are_detached_and_immutable(self) -> None:
        namespaces = ["example:subject"]
        policy = ExactIdentityPolicy(key_namespaces=namespaces)
        original = policy.reference
        namespaces.append("example:changed")
        definition = policy.definition
        definition["key_namespaces"].append("example:changed")
        definition["normalization"] = "casefold"
        detached_reference = policy.reference
        detached_reference["digest"] = "0" * 64
        self.assertEqual(("example:subject",), policy.key_namespaces)
        self.assertEqual(original, policy.reference)
        self.assertEqual("none", policy.definition["normalization"])
        with self.assertRaises(FrozenInstanceError):
            policy.key_namespaces = ("example:changed",)

    def test_policy_rejects_empty_duplicate_or_malformed_namespaces(self) -> None:
        invalid = (None, "example:subject", [], ["example:a", "example:a"],
                   [""], ["bad namespace"], ["example\n"], [7], ["é:subject"])
        for namespaces in invalid:
            with self.subTest(namespaces=namespaces):
                self.assert_error("E_SCHEMA_INVALID", lambda: ExactIdentityPolicy(key_namespaces=namespaces))

    def test_keys_preserve_order_case_unicode_and_caller_values(self) -> None:
        policy = ExactIdentityPolicy(key_namespaces=["example:subject", "Example:subject"])
        keys = [
            {"namespace": "example:subject", "value": "é"},
            {"namespace": "Example:subject", "value": "A"},
            {"namespace": "example:subject", "value": "e\u0301"},
            {"namespace": "example:subject", "value": "a"},
        ]
        result = policy.validate_keys(keys)
        self.assertEqual(keys, result)
        result[0]["value"] = "changed"
        self.assertEqual("é", keys[0]["value"])

    def test_key_shape_duplicates_and_namespace_policy_are_distinct_refusals(self) -> None:
        policy = ExactIdentityPolicy(key_namespaces=["example:subject"])
        invalid = ([], (KEY,), [KEY, deepcopy(KEY)], [None],
                   [{**KEY, "extra": "ignored?"}], [{**KEY, "value": " subject "}],
                   [{**KEY, "value": True}], [{**KEY, "value": "bad\ud800"}])
        for keys in invalid:
            with self.subTest(keys=repr(keys)):
                self.assert_error("E_SCHEMA_INVALID", policy.validate_keys, keys)
        error = self.assert_error("E_POLICY_INVALID", policy.validate_keys,
                                  [{"namespace": "run:local", "value": "private-run-token"}])
        self.assertNotIn("private-run-token", str(error))

    def test_declared_policy_reference_roundtrips_in_create_command(self) -> None:
        policy = ExactIdentityPolicy(key_namespaces=[KEY["namespace"]])
        command = create_command("declared-policy", "matter:declared", scope_id=SCOPE)
        command["body"]["identity_policy"] = policy.reference
        command["body"]["matter"]["body"]["identity_keys"] = policy.validate_keys([KEY])
        validated = validate_command(command)
        self.assertEqual(policy.reference, validated["body"]["identity_policy"])
        self.assertEqual([KEY], validated["body"]["matter"]["body"]["identity_keys"])


class IdentityBindingTests(unittest.TestCase):
    def assert_error(self, code: str, operation, *args) -> StorageError:
        with self.assertRaises(StorageError) as caught:
            operation(*args)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_key_addresses_bind_structured_scope_namespace_and_exact_value(self) -> None:
        cases = [
            (SCOPE, KEY),
            (SCOPE + ":other", KEY),
            (SCOPE, {**KEY, "namespace": "Example:subject"}),
            (SCOPE, {**KEY, "value": "Subject:1"}),
            (SCOPE, {**KEY, "value": "é"}),
            (SCOPE, {**KEY, "value": "e\u0301"}),
            ("a:b", {"namespace": "c", "value": "d"}),
            ("a", {"namespace": "b:c", "value": "d"}),
            (SCOPE, {**KEY, "value": "x/y:quoted\"\\😀"}),
        ]
        identities = []
        for scope, key in cases:
            reference = identity_key_ref(scope, key)
            identities.append(reference["id"])
            self.assertEqual(scope, reference["scope_id"])
            self.assertEqual(INDEX_NAMESPACE, reference["namespace"])
            self.assertEqual("matter:projection", reference["record_type"])
            encoded = json.dumps({"scope_id": scope, "key": key}, ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":")).encode()
            digest = hashlib.sha256(b"matter-json-v1\0matter.identity-key.v1\0" + encoded).hexdigest()
            self.assertEqual("key-" + digest, reference["id"])
        self.assertEqual(len(cases), len(set(identities)))

    def test_binding_descriptor_hashes_packaged_schema_and_preserves_bare_candidates(self) -> None:
        candidates = [matter_ref("matter:one"), matter_ref("matter:two")]
        value = binding_value(SCOPE, KEY, candidates)
        source = files("matter._schemas").joinpath("matter-identity-key.schema.json").read_bytes()
        self.assertEqual({
            "namespace": "matter", "id": "matter-identity-key", "version": "1.0",
            "digest": hashlib.sha256(source).hexdigest(),
        }, value["schema"])
        self.assertEqual({"scope_id": SCOPE, "key": KEY, "matters": candidates}, value["value"])
        self.assertTrue(all(set(reference) == {"scope_id", "namespace", "record_type", "id"}
                            for reference in value["value"]["matters"]))

    def test_binding_values_and_cached_schema_descriptor_are_detached(self) -> None:
        key = deepcopy(KEY)
        candidates = [matter_ref()]
        first = binding_value(SCOPE, key, candidates)
        expected = deepcopy(first)
        first["schema"]["digest"] = "0" * 64
        first["value"]["key"]["value"] = "changed"
        first["value"]["matters"][0]["id"] = "changed"
        self.assertEqual(KEY, key)
        self.assertEqual([matter_ref()], candidates)
        self.assertEqual(expected, binding_value(SCOPE, key, candidates))

    def test_binding_rejects_pins_wrong_types_duplicate_refs_and_foreign_scopes(self) -> None:
        invalid = ([], (matter_ref(),), [matter_ref(), matter_ref()],
                   [{**matter_ref(), "record_type": "observation"}],
                   [{**matter_ref(), "revision": 1}], [{**matter_ref(), "digest": "a" * 64}],
                   [{**matter_ref(), "extra": "unexpected"}], [None])
        for refs in invalid:
            with self.subTest(refs=refs):
                self.assert_error("E_SCHEMA_INVALID", binding_value, SCOPE, KEY, refs)
        self.assert_error("E_SCOPE_FORBIDDEN", binding_value, SCOPE, KEY,
                          [matter_ref(scope_id="synthetic:other")])

    def test_only_missing_identity_is_absence_and_other_lookup_errors_propagate(self) -> None:
        missing = _View(error=StorageError("E_NOT_FOUND"))
        self.assertIsNone(read_binding(missing, SCOPE, KEY))
        self.assertEqual([identity_key_ref(SCOPE, KEY)], missing.references)
        for code in ("E_STORAGE_UNAVAILABLE", "E_SCOPE_FORBIDDEN", "E_REVISION_CONFLICT"):
            with self.subTest(code=code):
                error = StorageError(code, retriable=True)
                caught = self.assert_error(code, read_binding, _View(error=error), SCOPE, KEY)
                self.assertIs(error, caught)

    def test_read_returns_detached_projection_and_retains_all_ambiguous_candidates(self) -> None:
        value = projection()
        value["value"] = binding_value(SCOPE, KEY, [matter_ref("one"), matter_ref("two")])
        view = _View(value)
        actual = read_binding(view, SCOPE, KEY)
        self.assertEqual(value, actual)
        self.assertEqual(2, len(actual["value"]["value"]["matters"]))
        actual["value"]["value"]["matters"][0]["id"] = "changed"
        self.assertEqual("one", value["value"]["value"]["matters"][0]["id"])

    def test_malformed_existing_binding_never_becomes_absence_or_partial_success(self) -> None:
        changes = [
            ("schema_version", "2.0"), ("record_type", "matter"),
            ("scope_id", "synthetic:other"), ("namespace", "example:wrong"),
            ("id", "wrong-identity"), ("revision", True), ("unexpected", "extra"),
            (("creation_receipt", "scope_id"), "synthetic:other"),
            (("value", "schema", "digest"), "f" * 64),
            (("value", "schema", "version"), "2.0"),
            (("value", "unexpected"), "extra"),
            (("value", "value", "unexpected"), "extra"),
            (("value", "value", "scope_id"), "synthetic:other"),
            (("value", "value", "key", "value"), "different-key"),
            (("value", "value", "matters"), []),
            (("value", "value", "matters"), [matter_ref(), matter_ref()]),
            (("value", "value", "matters"), [matter_ref(scope_id="synthetic:other")]),
            (("value", "value", "matters"), [{**matter_ref(), "record_type": "claim"}]),
            (("value", "value", "matters"), [{**matter_ref(), "revision": 1}]),
            (("value", "value"), {"scope_id": SCOPE, "key": KEY}),
        ]
        invalid = [None, [], {}, "not a projection"]
        for path, replacement in changes:
            value = projection()
            parts = (path,) if isinstance(path, str) else path
            target = value
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = replacement
            invalid.append(value)
        for index, value in enumerate(invalid):
            with self.subTest(case=index):
                self.assert_error("E_STORAGE_UNAVAILABLE", read_binding, _View(value), SCOPE, KEY)

    def test_invalid_requested_key_is_rejected_before_lookup(self) -> None:
        view = _View(projection())
        self.assert_error("E_SCHEMA_INVALID", read_binding, view, SCOPE, {**KEY, "value": " spaced "})
        self.assertEqual([], view.references)

    def test_sqlite_binding_keeps_bare_identity_across_matter_metadata_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with SQLiteStore(Path(temporary) / "matter.sqlite", scope_id=SCOPE) as store:
                command = create_command("create-indexed", "matter:1", scope_id=SCOPE)
                command["body"]["matter"]["body"]["identity_keys"] = [deepcopy(KEY)]

                def create(tx):
                    matter = tx.insert(tx.command["body"]["matter"])
                    tx.put_projection(identity_key_ref(SCOPE, KEY), binding_value(SCOPE, KEY, [entity_ref(matter)]))
                    return tx.success("created", {"matter": pin(matter)})

                self.assertEqual("success", store.execute(command, create)["status"])
                with store.snapshot() as view:
                    original = read_binding(view, SCOPE, KEY)
                matter = store.get(matter_ref())
                changed = create_command("edit-indexed", "matter:1", scope_id=SCOPE,
                                         expected_revisions=[pin(matter)])

                def edit(tx):
                    current = tx.get(matter_ref())
                    current["revision"] += 1
                    current["body"]["title"] = "New wording, same continuing subject"
                    updated = tx.replace(current)
                    return tx.success("existing", {"matter": pin(updated)})

                self.assertEqual("success", store.execute(changed, edit)["status"])
                with store.snapshot() as view:
                    self.assertEqual(original, read_binding(view, SCOPE, KEY))
                self.assertEqual(1, len(store.history(identity_key_ref(SCOPE, KEY))))
                self.assertEqual(2, store.get(matter_ref())["revision"])

    def test_wrong_kind_occupant_in_sqlite_is_index_failure_not_an_unbound_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with SQLiteStore(Path(temporary) / "matter.sqlite", scope_id=SCOPE) as store:
                reference = identity_key_ref(SCOPE, KEY)
                command = create_command("wrong-kind-index", reference["id"], scope_id=SCOPE)
                command["body"]["matter"]["namespace"] = INDEX_NAMESPACE

                def occupy(tx):
                    matter = tx.insert(tx.command["body"]["matter"])
                    return tx.success("created", {"matter": pin(matter)})

                self.assertEqual("success", store.execute(command, occupy)["status"])
                with store.snapshot() as view:
                    self.assert_error("E_STORAGE_UNAVAILABLE", read_binding, view, SCOPE, KEY)


if __name__ == "__main__":
    unittest.main()
