"""Adversarial currentness and malformed-port checks for identity views."""

from copy import deepcopy
import unittest

from association_helpers import AssociationTestCase, SCOPE
from integration.helpers import create_command, domain_value
from matter.associations import AssociationReader
from matter.identity_dependencies import (
    _watches, dependency_ref, read_registration, register_identity_dependency,
    require_current_identity_dependency,
)
from matter.citations import _domain
from matter.storage import StorageError, entity_ref, pin
from identity_helpers import IdentityTestCase
from matter_helpers import matter_command


class MatterRedirectCreationTests(IdentityTestCase):
    def test_existing_create_accepts_survivor_or_original_owner_without_key_rebinding(self):
        survivor, original, other = (self.matter(label) for label in ("survivor", "original", "other-member"))
        self.merge(survivor, [original, other])
        current = self.current(survivor)
        before = {identity["id"]: self.storage.history(entity_ref(identity)) for identity in (survivor, original, other)}
        keys = original["body"]["identity_keys"]
        for label, proposed_id in (("canonical", survivor["id"]), ("original", original["id"]), ("fresh", "unused-proposal-id")):
            command = matter_command("existing-" + label, matter_id=proposed_id, keys=keys, scope_id=SCOPE)
            result = self.matters.create(self.matters.prepare(command))
            self.assertEqual("existing", result.get("outcome"), result)
            self.assertEqual(pin(current), result["body"]["matter"])
        different = matter_command("wrong-member", matter_id=other["id"], keys=keys, scope_id=SCOPE)
        result = self.matters.create(self.matters.prepare(different))
        self.assert_failure(result, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertEqual(current, self.matters.resolve(keys))
        for identity in (survivor, original, other):
            self.assertEqual(before[identity["id"]], self.storage.history(entity_ref(identity)))


class DependencyCurrentnessTests(AssociationTestCase):
    def test_registration_inventory_cannot_omit_original_or_add_unrelated_dependencies(self):
        first, second = self.matter("declared-original"), self.matter("unrelated-original")
        target = {"scope_id": SCOPE, "namespace": "example:derived", "record_type": "matter:projection", "id": "malformed-inventory"}
        for label in ("omitted", "extra-matter", "host-projection"):
            captured = {}
            target_ref = {**target, "id": label}
            command = create_command("seed-" + label, "host-" + label, scope_id=SCOPE)

            def seed(tx):
                derived = tx.put_projection(target_ref, domain_value({"synthetic": label}))
                dependencies = {
                    "omitted": [pin(second)],
                    "extra-matter": [pin(first), pin(second)],
                    "host-projection": [pin(first), pin(derived)],
                }[label]
                from matter.canonical import canonical_bytes
                body = {"scope_id": SCOPE, "reference": pin(derived), "original_matters": [entity_ref(first)],
                        "dependencies": sorted(dependencies, key=canonical_bytes), "status": "current", "invalidation": None}
                captured["registration"] = tx.put_projection(dependency_ref(derived), _domain("identity-dependency", body),
                                                             watch_keys=_watches(body["original_matters"]))
                created = tx.insert(tx.command["body"]["matter"])
                return tx.success("created", {"matter": pin(created)})

            self.assertEqual("success", self.storage.execute(command, seed)["status"])
            with self.subTest(label=label), self.storage.snapshot() as view:
                with self.assertRaises(StorageError) as error:
                    read_registration(view, SCOPE, pin(captured["registration"]))
                self.assertEqual("E_EVIDENCE_INVALID", error.exception.code)

    def test_historical_registration_cannot_bypass_its_current_replacement(self):
        first, second = self.matter("first-dependent"), self.matter("second-dependent")
        target = {"scope_id": SCOPE, "namespace": "example:derived", "record_type": "matter:projection", "id": "derived"}
        captured = {}
        initial = create_command("initial-registration", "initial-host-record", scope_id=SCOPE,
                                 expected_revisions=[pin(first)])

        def create(tx):
            derived = tx.put_projection(target, domain_value({"synthetic": "identity-dependent output"}))
            captured["target"] = derived
            captured["old"] = register_identity_dependency(tx, pin(derived), matters=[pin(first)])
            created = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(created)})

        self.assertEqual("success", self.storage.execute(initial, create)["status"])
        old = captured["old"]
        replacement = create_command("broaden-registration", "broaden-host-record", scope_id=SCOPE,
            expected_revisions=[pin(first), pin(second), pin(captured["target"]), pin(old)])

        def broaden(tx):
            captured["new"] = register_identity_dependency(tx, pin(captured["target"]), matters=[pin(first), pin(second)])
            created = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(created)})

        self.assertEqual("success", self.storage.execute(replacement, broaden)["status"])
        self.assertEqual(2, captured["new"]["revision"])
        with self.storage.snapshot() as view:
            # Historical storage retrieval remains available for inspection.
            self.assertEqual(old, view.get(pin(old)))
            self.assertEqual(captured["new"], require_current_identity_dependency(view, SCOPE, dependency_ref(target)))
            with self.assertRaises(StorageError) as error:
                require_current_identity_dependency(view, SCOPE, pin(old))
            self.assertIn(error.exception.code, {"E_DEPENDENCY_STALE", "E_REVISION_CONFLICT"})


class AssociationWatchIntegrityTests(unittest.TestCase):
    def test_malformed_watched_projection_is_typed_evidence_failure(self):
        member = {"scope_id": SCOPE, "namespace": "example:matters", "record_type": "matter", "id": "member"}

        class BrokenWatchPort:
            def watchers(self, key):
                return [{}]

        with self.assertRaises(StorageError) as error:
            AssociationReader(SCOPE).for_member(BrokenWatchPort(), member)
        self.assertEqual("E_EVIDENCE_INVALID", error.exception.code)

    def test_storage_watch_failures_retain_their_retry_and_conflict_codes(self):
        member = {"scope_id": SCOPE, "namespace": "example:matters", "record_type": "matter", "id": "member"}
        for code in ("E_STORAGE_UNAVAILABLE", "E_REVISION_CONFLICT"):
            class UnavailableWatchPort:
                def watchers(self, key):
                    raise StorageError(code)

            with self.subTest(code=code), self.assertRaises(StorageError) as error:
                AssociationReader(SCOPE).for_member(UnavailableWatchPort(), deepcopy(member))
            self.assertEqual(code, error.exception.code)
