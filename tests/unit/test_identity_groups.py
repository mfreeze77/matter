"""Flat identity partitions, exact mirror proofs, and original-key resolution.

The in-memory port tests isolate the group primitives from host authority and
immutable decision validation, which the correction-service integration tests
exercise against SQLite. Only that decision verifier is stubbed here.
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from matter.canonical import canonical_bytes
from matter.identity_groups import (
    GROUP_NAMESPACE, group_ref, group_schema_ref, group_value,
    read_group, resolve_matter, write_groups,
)
from matter.identity_keys import ExactIdentityPolicy, binding_value, identity_key_ref
from matter.matters import MatterService
from matter.storage import StorageError, entity_ref, pin, snapshot_digest


SCOPE = "synthetic:identity-groups"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/contracts/records"


def record(kind="matter", identity="a"):
    def scoped(value):
        if isinstance(value, dict):
            return {key: SCOPE if key == "scope_id" else scoped(child) for key, child in value.items()}
        if isinstance(value, list):
            return [scoped(child) for child in value]
        return value
    value = scoped(json.loads((FIXTURES / f"{kind}.json").read_text()))
    value["id"] = identity
    if kind == "matter":
        value["body"]["identity_keys"] = [{"namespace": "example:subject", "value": identity}]
    return value


def identity(value):
    return value["scope_id"], value["namespace"], value["id"]


class Port:
    scope_id = SCOPE

    def __init__(self, records=()):
        self.records = {identity(value): deepcopy(value) for value in records}
        self.reads, self.writes = [], []
        self.command = {"scope_id": SCOPE}
        self.receipt_ref = entity_ref(record("receipt", "operation"))

    def lookup_identity(self, reference):
        self.reads.append(deepcopy(reference))
        try:
            return deepcopy(self.records[identity(reference)])
        except KeyError:
            raise StorageError("E_NOT_FOUND") from None

    def get(self, reference):
        raise AssertionError("Current groups must not silently use historical matter snapshots.")

    def replace(self, value):
        old = self.records[identity(value)]
        assert value["revision"] == old["revision"] + 1
        self.records[identity(value)] = deepcopy(value)
        self.writes.append(deepcopy(value))
        return deepcopy(value)

    def put_projection(self, reference, value, *, watch_keys=()):
        old = self.records.get(identity(reference))
        stored = {
            "schema_version": "1.0", **reference, "revision": old["revision"] + 1 if old else 1,
            "creation_receipt": old["creation_receipt"] if old else self.receipt_ref,
            "value": deepcopy(value), "watch_keys": list(watch_keys),
        }
        self.records[identity(reference)] = stored
        self.writes.append(deepcopy(stored))
        return deepcopy(stored)

    def command_receipt(self, key):
        raise StorageError("E_NOT_FOUND")

    @contextmanager
    def snapshot(self):
        yield self


class IdentityGroupTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.c = (record(identity=identity) for identity in ("a", "b", "c"))
        self.port = Port([self.a, self.b, self.c])
        self.decisions = {}
        self.addCleanup(patch.stopall)
        patch("matter.identity_groups._decision", side_effect=lambda view, scope, reference:
              deepcopy(self.decisions[identity(reference)])).start()

    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(StorageError) as error:
            function(*args, **kwargs)
        self.assertEqual(code, error.exception.code)

    def decision(self, partitions, name="merge", *, advance=True):
        receipt = record("receipt", name)
        after = []
        for partition in partitions:
            members = []
            for value in partition["members"]:
                member = deepcopy(value)
                member["revision"] += int(advance)
                members.append(pin(member))
            indexes = []
            for member in partition["members"]:
                ref = group_ref(member)
                old = self.port.records.get(identity(ref))
                indexes.append({**ref, "revision": old["revision"] + 1 if old else 1})
            survivor = next(member for member in members if entity_ref(member) == partition["survivor"])
            after.append({"survivor": survivor, "members": members, "indexes": indexes})
        receipt["body"]["details"]["value"] = {"after": after}
        reference = pin(receipt)
        self.decisions[identity(reference)] = receipt
        return reference

    def merge(self, members=None, survivor=None, name="merge"):
        members = members or [self.a, self.b]
        partitions = [{"survivor": entity_ref(survivor or members[0]), "members": members}]
        return write_groups(self.port, partitions, self.decision(partitions, name))[0]

    def test_schema_descriptor_is_exact_packaged_bytes_and_detached(self):
        data = files("matter._schemas").joinpath("identity-group.schema.json").read_bytes()
        expected = {"namespace": "matter", "id": "identity-group", "version": "1.0",
                    "digest": hashlib.sha256(data).hexdigest()}
        self.assertEqual(expected, group_schema_ref())
        changed = group_schema_ref()
        changed["digest"] = "changed"
        self.assertEqual(expected, group_schema_ref())

    def test_mirror_address_binds_original_scope_namespace_and_id_but_not_revision(self):
        self.assertEqual(group_ref(self.a), group_ref(pin(self.a)))
        changed = deepcopy(self.a)
        changed["revision"] += 1
        self.assertEqual(group_ref(self.a), group_ref(changed))
        cases = [entity_ref(self.a)]
        for field, value in (("scope_id", "synthetic:other"), ("namespace", "example:other"), ("id", "other")):
            cases.append({**entity_ref(self.a), field: value})
        self.assertEqual(4, len({group_ref(value)["id"] for value in cases}))

    def test_missing_mirror_is_singleton_without_any_write(self):
        result = read_group(self.port, SCOPE, pin(self.a))
        self.assertEqual({"survivor": self.a, "members": [self.a], "indexes": []}, result)
        self.assertEqual([], self.port.writes)
        result["survivor"]["body"]["title"] = "detached"
        self.assertEqual(self.a, resolve_matter(self.port, SCOPE, entity_ref(self.a)))

    def test_merge_preserves_original_bodies_and_advances_every_member_once(self):
        group = self.merge(members=[self.b, self.a], survivor=self.a)
        self.assertEqual(["a", "b"], [member["id"] for member in group["members"]])
        self.assertEqual("a", group["survivor"]["id"])
        for original, member in zip([self.a, self.b], group["members"]):
            self.assertEqual(original["revision"] + 1, member["revision"])
            expected = deepcopy(original)
            expected["revision"] += 1
            self.assertEqual(expected, member)
            self.assertEqual(group, read_group(self.port, SCOPE, entity_ref(member)))
        self.assertEqual(4, len(self.port.writes))

    def test_current_revision_and_digest_are_checked_even_with_snapshot_port(self):
        group = self.merge()
        self.assert_error("E_REVISION_CONFLICT", read_group, self.port, SCOPE, pin(self.a))
        current = group["members"][0]
        digest = {**entity_ref(current), "digest": snapshot_digest(current)}
        self.assertEqual(group, read_group(self.port, SCOPE, digest))
        digest["digest"] = "0" * 64
        self.assert_error("E_REVISION_CONFLICT", read_group, self.port, SCOPE, digest)

    def test_metadata_revision_does_not_rewrite_bare_group_membership(self):
        group = self.merge()
        changed = deepcopy(group["survivor"])
        changed["revision"] += 1
        changed["body"]["title"] = "Updated survivor title"
        self.port.replace(changed)
        read = read_group(self.port, SCOPE, entity_ref(self.b))
        self.assertEqual(changed, read["survivor"])
        self.assertEqual(group["indexes"], read["indexes"])

    def test_current_member_cannot_predate_the_identity_decision(self):
        self.merge()
        # A damaged port reports a pre-merge matter head while retaining the
        # valid mirrors. Later metadata revisions are allowed; rollback is not.
        self.port.records[identity(self.a)] = deepcopy(self.a)
        self.assert_error("E_EVIDENCE_INVALID", read_group, self.port, SCOPE, entity_ref(self.b))

    def test_missing_wrong_kind_foreign_descriptor_and_extra_watch_mirrors_refuse(self):
        group = self.merge()
        reference = group_ref(self.b)
        original = deepcopy(self.port.records[identity(reference)])
        cases = [None, {**self.b, **{key: reference[key] for key in ("namespace", "id")}}]
        for change in ("descriptor", "watch", "member", "extra"):
            value = deepcopy(original)
            if change == "descriptor":
                value["value"]["schema"]["digest"] = "0" * 64
            elif change == "watch":
                value["watch_keys"] = ["unrelated-watch"]
            elif change == "member":
                value["value"]["value"]["member"] = entity_ref(self.a)
            else:
                value["value"]["value"]["unexpected"] = True
            cases.append(value)
        for value in cases:
            with self.subTest(value=value):
                if value is None:
                    self.port.records.pop(identity(reference), None)
                else:
                    self.port.records[identity(reference)] = value
                self.assert_error("E_EVIDENCE_INVALID", read_group, self.port, SCOPE, entity_ref(self.a))
        self.port.records[identity(reference)] = original
        self.assertEqual(group, read_group(self.port, SCOPE, entity_ref(self.a)))

    def test_survivor_cycle_and_inconsistent_complete_partition_are_not_redirect_chains(self):
        self.merge()
        ref = group_ref(self.b)
        self.port.records[identity(ref)]["value"]["value"]["survivor"] = entity_ref(self.b)
        self.assert_error("E_EVIDENCE_INVALID", read_group, self.port, SCOPE, entity_ref(self.a))

    def test_decision_must_bind_complete_group_and_exact_projection_revisions(self):
        group = self.merge()
        proof = self.decisions[identity(group["indexes"][0]["value"]["value"]["decision"])]
        original = deepcopy(proof)
        proof["body"]["details"]["value"]["after"][0]["indexes"][0]["revision"] += 1
        self.assert_error("E_EVIDENCE_INVALID", read_group, self.port, SCOPE, entity_ref(self.b))
        proof.clear()
        proof.update(original)
        proof["body"]["details"]["value"]["after"][0]["members"].pop()
        self.assert_error("E_EVIDENCE_INVALID", read_group, self.port, SCOPE, entity_ref(self.b))

    def test_partial_partition_overlap_missing_survivor_and_stale_body_refuse_before_writes(self):
        group = self.merge()
        a, b = group["members"]
        cases = [
            ([{"survivor": entity_ref(a), "members": [a]}], "E_MERGE_CONFLICT"),
            ([{"survivor": entity_ref(a), "members": [a, b]}, {"survivor": entity_ref(b), "members": [b]}], "E_MERGE_CONFLICT"),
            ([{"survivor": entity_ref(self.c), "members": [a, b]}], "E_MERGE_CONFLICT"),
        ]
        changed = deepcopy(b)
        changed["body"]["title"] = "Caller-altered body at unchanged revision"
        cases.append(([{"survivor": entity_ref(a), "members": [a, changed]}], "E_REVISION_CONFLICT"))
        before = deepcopy(self.port.records)
        for partitions, code in cases:
            self.assert_error(code, write_groups, self.port, partitions, pin(record("receipt", "correction")))
            self.assertEqual(before, self.port.records)

    def test_split_writes_explicit_singletons_and_keeps_original_keys(self):
        merged = self.merge()
        partitions = [{"survivor": entity_ref(member), "members": [member]} for member in merged["members"]]
        corrected = write_groups(self.port, partitions, self.decision(partitions, "undo"))
        self.assertEqual(2, len(corrected))
        for group, original in zip(corrected, [self.a, self.b]):
            self.assertEqual(original["body"]["identity_keys"], group["survivor"]["body"]["identity_keys"])
            self.assertEqual(3, group["survivor"]["revision"])
            self.assertEqual(2, group["indexes"][0]["revision"])
            self.assertEqual(group, read_group(self.port, SCOPE, entity_ref(original)))

    def test_scope_and_port_failures_are_not_converted_to_absence(self):
        foreign = {**entity_ref(self.a), "scope_id": "synthetic:other"}
        self.assert_error("E_SCOPE_FORBIDDEN", read_group, self.port, SCOPE, foreign)
        for code in ("E_STORAGE_UNAVAILABLE", "E_REVISION_CONFLICT"):
            with patch.object(self.port, "lookup_identity", side_effect=StorageError(code)):
                self.assert_error(code, read_group, self.port, SCOPE, entity_ref(self.a))

    def test_group_values_reject_duplicate_uncontained_and_foreign_members(self):
        base = {"scope_id": SCOPE, "member": entity_ref(self.a), "survivor": entity_ref(self.a),
                "members": [entity_ref(self.a), entity_ref(self.b)], "decision": pin(record("receipt", "decision"))}
        for field in ("member", "survivor"):
            self.assert_error("E_EVIDENCE_INVALID", group_value, {**base, field: entity_ref(self.c)})
        self.assert_error("E_SCHEMA_INVALID", group_value, {**base, "members": [entity_ref(self.a), entity_ref(self.a)]})
        foreign = {**entity_ref(self.b), "scope_id": "synthetic:other"}
        self.assert_error("E_SCOPE_FORBIDDEN", group_value, {**base, "members": [entity_ref(self.a), foreign]})
        result = group_value({**base, "members": list(reversed(base["members"]))})
        self.assertEqual(base["members"], result["value"]["members"])
        result["value"]["members"][0]["id"] = "mutated"
        self.assertEqual("a", base["members"][0]["id"])

    def test_matter_resolution_preserves_original_key_bindings_and_collapses_only_explicit_groups(self):
        for member in (self.a, self.b):
            key = member["body"]["identity_keys"][0]
            self.port.put_projection(identity_key_ref(SCOPE, key), binding_value(SCOPE, key, [entity_ref(member)]))
        service = MatterService(self.port, identity_policy=ExactIdentityPolicy(key_namespaces=["example:subject"]))
        keys = [self.a["body"]["identity_keys"][0], self.b["body"]["identity_keys"][0]]
        self.assert_error("E_SOURCE_IDENTITY_CONFLICT", service.resolve, keys)
        bindings = {identity(identity_key_ref(SCOPE, key)): deepcopy(self.port.records[identity(identity_key_ref(SCOPE, key))]) for key in keys}
        merged = self.merge()
        self.assertEqual(merged["survivor"], service.resolve(keys))
        self.assertEqual(merged["survivor"], service.resolve([keys[1]]))
        for ref, original in bindings.items():
            self.assertEqual(original, self.port.records[ref])
        self.assert_error("E_SOURCE_IDENTITY_CONFLICT", service.resolve, [keys[1], {"namespace": "example:subject", "value": "new"}])
