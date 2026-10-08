"""Persistent exact-key identity, context independence and metadata revisioning."""

from copy import deepcopy

from matter.identity_keys import binding_value, identity_key_ref
from matter.matters import MatterService
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, entity_ref, pin, snapshot_digest

from integration.helpers import domain_value
from matter_helpers import (
    MatterTestCase,
    SCOPE,
    assessment_fixture_command,
    competing_matter_results,
    identity_key,
    identity_policy,
    matter_command,
    metadata_command,
    restarted_subject,
    store_assessment_fixture,
)
from observation_helpers import PAYLOAD, observation_command


class MatterContinuityTests(MatterTestCase):
    def _new(self, command_id="original", *, keys=None, **kwargs):
        command = matter_command(command_id, keys=keys, **kwargs)
        prepared, result = self.submit_create(command)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["outcome"], "created")
        return command, prepared, result, self.storage.get(result["body"]["matter"])

    def _bindings(self, record):
        return [self.storage.get(identity_key_ref(record["scope_id"], key))
                for key in record["body"]["identity_keys"]]

    def _with_reads(self, command, *snapshots):
        result = deepcopy(command)
        result["expected_revisions"] = [pin(snapshot) for snapshot in snapshots]
        return result

    def _seed_ambiguous_binding(self, key):
        """Install two legitimate synthetic candidates, not a merge or association."""
        first = matter_command("seed-ambiguous", keys=[key])
        second = matter_command("seed-second", keys=[key])["body"]["matter"]
        first["extensions"] = {"example:synthetic-fixture": domain_value({"second": second})}

        def handler(tx):
            command = tx.command
            one = tx.insert(command["body"]["matter"])
            two = tx.insert(command["extensions"]["example:synthetic-fixture"]["value"]["second"])
            declared = one["body"]["identity_keys"][0]
            tx.put_projection(identity_key_ref(SCOPE, declared),
                              binding_value(SCOPE, declared, [entity_ref(one), entity_ref(two)]))
            return tx.success("created", {"matter": pin(one)})

        result = self.storage.execute(first, handler)
        self.assertEqual(result["status"], "success", result)
        records = [self.storage.get(entity_ref(value)) for value in (first["body"]["matter"], second)]
        return records, self.storage.get(identity_key_ref(SCOPE, key))

    def test_an_opportunity_needs_no_failure_or_display_fields(self):
        command = matter_command("opportunity", matter_id="host-opaque-subject-7")
        command["body"]["matter"]["body"].pop("title")
        _, result = self.submit_create(command)
        self.assertEqual(result["outcome"], "created")
        stored = self.storage.get(result["body"]["matter"])
        self.assertEqual(stored["id"], "host-opaque-subject-7")
        self.assertEqual(stored["revision"], 1)
        self.assertEqual(stored["body"], {
            "domain_kind": "example:opportunity", "identity_keys": [identity_key()],
        })
        self.assertEqual(self.service.resolve([identity_key()]), stored)
        self.assertIsNone(self.service.resolve([identity_key("unbound-subject")]))
        self.assertEqual(self.record_counts(), {"matter": 1, "matter:projection": 1, "receipt": 1})

    def test_declared_subject_survives_new_process_run_proposal_and_later_evidence(self):
        original, prepared, first, stored = self._new()
        bindings = self._bindings(stored)
        later = matter_command("later-run", keys=stored["body"]["identity_keys"])
        later["body"]["matter"]["body"]["title"] = "Reworded title in another process"
        later["body"]["matter"]["provenance"]["run_id"] = "run:new-process"
        self.assertNotEqual(later["body"]["matter"]["id"], stored["id"])
        self.storage.close()
        message = restarted_subject(self, self.database, self.payload_directory, later)
        self.assertEqual(message["result"]["outcome"], "existing")
        self.assertEqual(message["result"]["body"]["matter"], pin(stored))
        self.assertEqual(message["resolved"], stored)
        self.assertEqual(message["evidence"]["outcome"], "committed")

        with SQLiteStore(self.database, scope_id=SCOPE) as reopened:
            service = MatterService(reopened, identity_policy=identity_policy())
            self.assertEqual(service.resolve(stored["body"]["identity_keys"]), stored)
            self.assertEqual(reopened.history(pin(stored)), [stored])
            self.assertEqual(reopened.command_receipt(prepared["idempotency_key"])["result"], first)
            for binding in bindings:
                self.assertEqual(reopened.get(entity_ref(binding)), binding)
            evidence = reopened.get(message["evidence"]["body"]["observation"])
            self.assertEqual(evidence["provenance"]["run_id"], "run:new-process")
            self.assertEqual(stored["provenance"], original["body"]["matter"]["provenance"])
        self.assertEqual(self.record_counts(), {"matter": 1, "matter:projection": 2, "observation": 1, "receipt": 3})

    def test_all_new_keys_commit_one_matter_and_each_key_binding_with_one_receipt(self):
        keys = [identity_key("subject-a"), identity_key("registry-a", "example:registry")]
        _, _, result, stored = self._new(keys=keys)
        bindings = self._bindings(stored)
        self.assertEqual(stored["body"]["identity_keys"], keys)
        for key, binding in zip(keys, bindings):
            with self.subTest(key=key):
                self.assertEqual(self.service.resolve([key]), stored)
                self.assertEqual(binding["revision"], 1)
                self.assertEqual(binding["creation_receipt"], stored["creation_receipt"])
                self.assertEqual(binding["value"], binding_value(SCOPE, key, [entity_ref(stored)]))
                self.assertEqual(entity_ref(self.storage.receipt_for(pin(binding))), result["receipt"])
        self.assertEqual(self.service.resolve(list(reversed(keys))), stored)
        self.assertEqual(self.record_counts(), {"matter": 1, "matter:projection": 2, "receipt": 1})

    def test_existing_keys_preserve_fields_indexes_and_original_identity(self):
        keys = [identity_key("subject-a"), identity_key("registry-a", "example:registry")]
        _, _, first, stored = self._new(keys=keys)
        bindings = self._bindings(stored)
        for label, supplied in (("all", list(reversed(keys))), ("subset", keys[:1])):
            with self.subTest(keys=label):
                command = matter_command(f"existing-{label}", keys=supplied)
                proposed = command["body"]["matter"]
                proposed["body"].update(title="A different title", description="A different description")
                proposed["extensions"] = {"example:display": domain_value({"audience": "different"})}
                prepared, result = self.submit_create(command)
                self.assertEqual(result["outcome"], "existing")
                self.assertEqual(result["body"]["matter"], first["body"]["matter"])
                self.assertNotEqual(result["receipt"], first["receipt"])
                self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["result"], result)
                self.assert_missing(entity_ref(proposed))
        self.assertEqual(self.storage.history(pin(stored)), [stored])
        self.assertEqual(self._bindings(stored), bindings)
        self.assertEqual(self.service.resolve(keys), stored)

    def test_mixed_bound_and_unbound_keys_cannot_expand_an_existing_identity(self):
        bound, unbound = identity_key("bound"), identity_key("new-key")
        _, _, _, stored = self._new(keys=[bound])
        binding = self._bindings(stored)[0]
        command = self._with_reads(matter_command("implicit-expansion", keys=[bound, unbound]), stored, binding)
        result = self.service.create(command)
        self.assert_failure(result, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertEqual(self.storage.get(pin(stored)), stored)
        self.assertEqual(self.storage.get(entity_ref(binding)), binding)
        self.assert_missing(identity_key_ref(SCOPE, unbound))
        self.assert_missing(entity_ref(command["body"]["matter"]))
        with self.assertRaises(StorageError) as error:
            self.service.resolve([bound, unbound])
        self.assertEqual(error.exception.code, "E_SOURCE_IDENTITY_CONFLICT")

    def test_keys_bound_to_different_matters_return_conflict_without_partial_binding(self):
        key_a, key_b = identity_key("one"), identity_key("two")
        _, _, _, one = self._new("one", keys=[key_a])
        _, _, _, two = self._new("two", keys=[key_b])
        bindings = self._bindings(one) + self._bindings(two)
        proposed = matter_command("contradiction", keys=[key_a, key_b])
        command = self._with_reads(proposed, one, two, *bindings)
        failure = self.service.create(command)
        self.assert_failure(failure, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertCountEqual(failure["error"]["affected_references"], [entity_ref(one), entity_ref(two)])
        with self.assertRaises(StorageError) as error:
            self.service.resolve([key_a, key_b])
        self.assertEqual(error.exception.code, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertCountEqual(error.exception.affected_references, [entity_ref(one), entity_ref(two)])
        self.assertEqual(self._bindings(one) + self._bindings(two), bindings)
        self.assert_missing(entity_ref(proposed["body"]["matter"]))

    def test_one_well_formed_key_mapping_with_two_candidates_is_an_explicit_conflict(self):
        key = identity_key("ambiguous")
        records, binding = self._seed_ambiguous_binding(key)
        with self.assertRaises(StorageError) as error:
            self.service.resolve([key])
        self.assertEqual(error.exception.code, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertCountEqual(error.exception.affected_references, [entity_ref(record) for record in records])
        command = self._with_reads(matter_command("ambiguous-create", keys=[key]), binding, *records)
        result = self.service.create(command)
        self.assert_failure(result, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertCountEqual(result["error"]["affected_references"], [entity_ref(record) for record in records])
        update = self._with_reads(metadata_command("ambiguous-update", records[0], {"title": "Must not commit"}),
                                  binding, *records)
        failure = self.service.update_metadata(update)
        self.assert_failure(failure, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertEqual(self.storage.get(entity_ref(binding)), binding)
        self.assertEqual([self.storage.get(pin(record)) for record in records], records)

    def test_domain_mismatch_and_occupied_proposed_id_cannot_reinterpret_existing_subjects(self):
        key_a, key_b = identity_key("one"), identity_key("two")
        _, _, _, one = self._new("one", keys=[key_a])
        _, _, _, two = self._new("two", keys=[key_b])
        bindings = self._bindings(one) + self._bindings(two)
        wrong_kind = matter_command("wrong-domain", keys=[key_a], domain_kind="example:question")
        occupied = matter_command("occupied-id", keys=[key_a], matter_id=two["id"])
        for command in (wrong_kind, occupied):
            with self.subTest(command=command["command_id"]):
                result = self.service.create(self._with_reads(command, one, two, *bindings))
                self.assert_failure(result, "E_SOURCE_IDENTITY_CONFLICT")
        with self.assertRaises(StorageError) as error:
            self.service.resolve([key_a], domain_kind="example:question")
        self.assertEqual(error.exception.code, "E_SOURCE_IDENTITY_CONFLICT")
        self.assertEqual(self.service.resolve([key_a], domain_kind="example:opportunity"), one)
        self.assertEqual(self.service.resolve([key_b]), two)
        self.assertEqual(self._bindings(one) + self._bindings(two), bindings)

    def test_policy_and_duplicate_key_refusals_are_typed_and_do_not_create_children(self):
        cases = []
        unsupported = matter_command("unsupported-policy")
        unsupported["body"]["identity_policy"]["version"] = "99.0"
        cases.append((unsupported, "E_POLICY_INVALID"))
        disallowed = matter_command("disallowed-namespace", keys=[identity_key("subject", "example:undeclared")])
        cases.append((disallowed, "E_POLICY_INVALID"))
        duplicate = matter_command("duplicate-key", keys=[identity_key(), identity_key()])
        cases.append((duplicate, "E_SCHEMA_INVALID"))
        for command, code in cases:
            with self.subTest(command=command["command_id"]):
                result = self.service.create(command)
                self.assert_failure(result, code)
                self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], result)
                self.assert_missing(entity_ref(command["body"]["matter"]))
        self.assertEqual(self.record_counts(), {"receipt": 3})

    def test_initial_lifecycle_and_supersession_do_not_enter_through_creation(self):
        _, _, _, original = self._new()
        for field in ("lifecycle", "supersedes"):
            with self.subTest(field=field):
                key = identity_key(field)
                command = matter_command(field, keys=[key])
                proposed = command["body"]["matter"]
                if field == "lifecycle":
                    proposed["body"][field] = {
                        "profile": deepcopy(self.policy.reference), "state": "example:open",
                        "transition_receipt": deepcopy(command["authority"]),
                    }
                else:
                    proposed[field] = [pin(original)]
                failure = self.service.create(command)
                self.assert_failure(failure, "E_POLICY_INVALID")
                self.assert_missing(entity_ref(proposed))
                self.assert_missing(identity_key_ref(SCOPE, key))
        self.assertEqual(self.storage.history(pin(original)), [original])

    def test_creation_lineage_is_pinned_and_foreign_or_missing_parents_do_not_create_a_matter(self):
        _, _, _, parent = self._new("parent", keys=[identity_key("parent")])
        child = matter_command("derived-subject", keys=[identity_key("derived-subject")])
        child["body"]["matter"]["provenance"].update(origin="derived", parents=[pin(parent)])
        prepared, result = self.submit_create(child)
        self.assertEqual(result["outcome"], "created")
        self.assertIn(pin(parent), prepared["expected_revisions"])
        stored = self.storage.get(result["body"]["matter"])
        self.assertEqual(stored["provenance"], child["body"]["matter"]["provenance"])

        missing = matter_command("missing-parent", keys=[identity_key("missing-parent")])
        missing_pin = {**pin(parent), "id": "missing-parent-id"}
        missing["body"]["matter"]["provenance"].update(origin="derived", parents=[missing_pin])
        prepared, failure = self.submit_create(missing)
        self.assertIn(missing_pin, prepared["expected_revisions"])
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        foreign = matter_command("foreign-parent", keys=[identity_key("foreign-parent")])
        foreign_pin = {**pin(parent), "scope_id": "synthetic:foreign"}
        foreign["body"]["matter"]["provenance"].update(origin="derived", parents=[foreign_pin])
        with self.assertRaises(StorageError) as error:
            self.service.prepare(foreign)
        self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
        for command in (missing, foreign):
            self.assert_missing(entity_ref(command["body"]["matter"]))
            self.assert_missing(identity_key_ref(SCOPE, command["body"]["matter"]["body"]["identity_keys"][0]))

    def test_prepare_is_read_only_defensive_and_preserves_caller_pins(self):
        _, _, _, stored = self._new()
        command = matter_command("new-proposal", keys=stored["body"]["identity_keys"])
        command["expected_revisions"] = [pin(stored)]
        before = deepcopy(command)
        prepared = self.service.prepare(command)
        self.assertEqual(command, before)
        self.assertEqual(prepared["expected_revisions"][0], pin(stored))
        self.assertIn(pin(self._bindings(stored)[0]), prepared["expected_revisions"])
        self.assertEqual(len(prepared["expected_revisions"]), 2)
        prepared["body"]["matter"]["body"]["title"] = "Only the returned copy changes"
        self.assertEqual(command, before)
        self.assertEqual(self.record_counts(), {"matter": 1, "matter:projection": 1, "receipt": 1})

    def test_metadata_revisions_preserve_identity_provenance_lifecycle_and_history(self):
        _, _, _, created = self._new()
        bindings = self._bindings(created)
        seed = matter_command("preexisting-lifecycle-fixture", matter_id=created["id"],
                              keys=created["body"]["identity_keys"])
        seed["expected_revisions"] = [pin(created)]

        def install_fixture(tx):
            # This creates a synthetic preexisting state to test preservation;
            # it does not implement or qualify lifecycle transition behavior.
            record = tx.get(entity_ref(tx.command["body"]["matter"]))
            record["revision"] += 1
            record["body"]["lifecycle"] = {
                "profile": tx.command["body"]["identity_policy"], "state": "example:open",
                "transition_receipt": tx.receipt_ref,
            }
            return tx.success("existing", {"matter": pin(tx.replace(record))})

        result = self.storage.execute(seed, install_fixture)
        self.assertEqual(result["status"], "success", result)
        before = self.storage.get(result["body"]["matter"])
        metadata = {
            "title": "Reworded opportunity", "description": "A more precise description of the same subject.",
            "extensions": {"example:display": domain_value({"category": "opportunity", "priority": "review"})},
        }
        _, changed = self.submit_metadata(metadata_command("reworded", before, metadata))
        self.assertEqual(changed["outcome"], "updated")
        updated = self.storage.get(changed["body"]["matter"])
        expected = deepcopy(before)
        expected["revision"] += 1
        expected["body"].update(title=metadata["title"], description=metadata["description"])
        expected["extensions"] = deepcopy(metadata["extensions"])
        self.assertEqual(updated, expected)
        self.assertEqual(self.storage.history(entity_ref(created)), [created, before, updated])
        self.assertEqual(self.storage.get(pin(created)), created)
        self.assertEqual(self.storage.get(pin(before)), before)
        self.assertEqual(self.service.resolve(created["body"]["identity_keys"]), updated)
        self.assertEqual(self._bindings(updated), bindings)
        self.assertNotEqual(entity_ref(self.storage.receipt_for(pin(updated))), updated["creation_receipt"])

    def test_complete_metadata_replacement_clears_omissions_and_noops_do_not_revision(self):
        command = matter_command("original")
        proposed = command["body"]["matter"]
        proposed["body"]["description"] = "Original optional description"
        proposed["extensions"] = {"example:display": domain_value({"category": "synthetic"})}
        _, first = self.submit_create(command)
        original = self.storage.get(first["body"]["matter"])
        identical = {"title": original["body"]["title"], "description": original["body"]["description"],
                     "extensions": deepcopy(original["extensions"])}
        _, noop = self.submit_metadata(metadata_command("same-metadata", original, identical))
        self.assertEqual(noop["outcome"], "unchanged")
        self.assertEqual(noop["body"]["matter"], pin(original))
        _, cleared = self.submit_metadata(metadata_command("clear-metadata", original, {}))
        self.assertEqual(cleared["outcome"], "updated")
        current = self.storage.get(cleared["body"]["matter"])
        self.assertEqual(current["revision"], 2)
        self.assertEqual(current["body"], {
            "domain_kind": original["body"]["domain_kind"], "identity_keys": original["body"]["identity_keys"],
        })
        self.assertNotIn("extensions", current)
        _, noop_again = self.submit_metadata(metadata_command("already-clear", current, {}))
        self.assertEqual(noop_again["outcome"], "unchanged")
        self.assertEqual(noop_again["body"]["matter"], pin(current))
        self.assertEqual(self.storage.history(entity_ref(original)), [original, current])
        self.assertEqual(self._bindings(current)[0]["revision"], 1)

    def test_nested_integer_boolean_changes_are_distinct_metadata_revisions(self):
        command = matter_command("typed-original")
        integer_extensions = {"example:display": domain_value({"nested": [{"enabled": 1, "disabled": 0}]})}
        command["body"]["matter"]["extensions"] = deepcopy(integer_extensions)
        _, first = self.submit_create(command)
        original = self.storage.get(first["body"]["matter"])
        bindings = self._bindings(original)
        boolean_extensions = {"example:display": domain_value({"nested": [{"enabled": True, "disabled": False}]})}
        expected_records = [original]
        for command_id, extensions, expected_type in (
            ("booleans", boolean_extensions, bool),
            ("integers-again", integer_extensions, int),
        ):
            with self.subTest(representation=command_id):
                before = expected_records[-1]
                metadata = {"title": before["body"]["title"], "extensions": extensions}
                _, result = self.submit_metadata(metadata_command(command_id, before, metadata))
                self.assertEqual(result["outcome"], "updated")
                current = self.storage.get(result["body"]["matter"])
                self.assertEqual(current["revision"], before["revision"] + 1)
                values = current["extensions"]["example:display"]["value"]["nested"][0]
                self.assertIs(type(values["enabled"]), expected_type)
                self.assertIs(type(values["disabled"]), expected_type)
                self.assertNotEqual(snapshot_digest(current), snapshot_digest(before))
                expected_records.append(current)
        history = self.storage.history(entity_ref(original))
        self.assertEqual(len(history), 3)
        self.assertEqual([record["revision"] for record in history], [1, 2, 3])
        self.assertEqual(len({snapshot_digest(record) for record in history}), 3)
        for record, expected_type in zip(history, (int, bool, int)):
            values = record["extensions"]["example:display"]["value"]["nested"][0]
            self.assertIs(type(values["enabled"]), expected_type)
            self.assertIs(type(values["disabled"]), expected_type)
        self.assertEqual(self._bindings(expected_records[-1]), bindings)

    def test_stale_metadata_refusal_and_exact_results_survive_later_revisions(self):
        _, original_command, original_result, original = self._new()
        first_command = self.service.prepare(metadata_command("first-update", original, {"title": "First revision"}))
        stale_command = self.service.prepare(metadata_command("stale-update", original, {"title": "Stale revision"}))
        first = self.service.update_metadata(first_command)
        self.assertEqual(first["outcome"], "updated")
        one = self.storage.get(first["body"]["matter"])
        stale = self.service.update_metadata(stale_command)
        self.assert_failure(stale, "E_REVISION_CONFLICT")
        _, second = self.submit_metadata(metadata_command("second-update", one, {"title": "Second revision"}))
        two = self.storage.get(second["body"]["matter"])
        self.assertEqual(two["revision"], 3)
        self.assertEqual(self.service.prepare(first_command), first_command)
        self.assertEqual(self.service.update_metadata(first_command), first)
        self.assertEqual(self.service.update_metadata(stale_command), stale)
        self.assertEqual(self.service.create(original_command), original_result)
        self.assertEqual(self.storage.command_receipt(stale_command["idempotency_key"])["result"], stale)
        self.assertEqual(self.storage.history(entity_ref(original)), [original, one, two])
        self.assertEqual(self.service.resolve(original["body"]["identity_keys"]), two)

    def test_every_key_index_is_a_metadata_dependency_and_stale_caller_pins_are_preserved(self):
        keys = [identity_key("subject"), identity_key("registry", "example:registry")]
        _, _, _, original = self._new(keys=keys)
        bindings = self._bindings(original)
        command = metadata_command("stale-index", original, {"title": "Must wait for a new command"},
                                   expected_revisions=[pin(bindings[1])])
        frozen = self.service.prepare(command)
        for binding in bindings:
            self.assertIn(pin(binding), frozen["expected_revisions"])
        refresh = self._with_reads(matter_command("synthetic-index-refresh", keys=keys), bindings[1])

        def refresh_binding(tx):
            current = tx.get(entity_ref(bindings[1]))
            tx.put_projection(entity_ref(current), current["value"])
            return tx.success("existing", {"matter": pin(original)})

        result = self.storage.execute(refresh, refresh_binding)
        self.assertEqual(result["status"], "success", result)
        rebuilt = self.service.prepare(command)
        self.assertEqual(rebuilt["expected_revisions"][0], pin(bindings[1]))
        failure = self.service.update_metadata(frozen)
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        self.assertEqual(self.storage.get(pin(original)), original)
        self.assertEqual(self.service.update_metadata(frozen), failure)
        _, fresh = self.submit_metadata(metadata_command("fresh-index", original, {"title": "A fresh checked update"}))
        self.assertEqual(fresh["outcome"], "updated")
        self.assertEqual(self.storage.get(fresh["body"]["matter"])["revision"], 2)

    def test_purpose_and_audience_bindings_coexist_without_assigning_new_matter_identity(self):
        _, _, _, original = self._new()
        bindings = self._bindings(original)
        assessments = []
        contexts = (("triage", "owner", "1.0"), ("review", "public", "1.0"))
        for index, (purpose, audience, version) in enumerate(contexts):
            command = assessment_fixture_command(f"context-{index}", original, purpose=purpose,
                                                 audience=audience, version=version)
            result = self.storage.execute(command, store_assessment_fixture)
            self.assertEqual(result["status"], "success", result)
            assessments.append(self.storage.get(result["body"]["assessment"]))
        _, changed = self.submit_metadata(metadata_command("new-wording", original, {"description": "Updated wording"}))
        current = self.storage.get(changed["body"]["matter"])
        command = assessment_fixture_command("context-2", current, purpose="triage", audience="owner", version="2.0")
        result = self.storage.execute(command, store_assessment_fixture)
        self.assertEqual(result["status"], "success", result)
        assessments.append(self.storage.get(result["body"]["assessment"]))
        self.assertEqual([record["body"]["matter"] for record in assessments], [pin(original), pin(original), pin(current)])
        self.assertEqual([(record["body"]["purpose"]["id"], record["body"]["audience"]["id"],
                           record["body"]["purpose"]["version"]) for record in assessments],
                         [*contexts, ("triage", "owner", "2.0")])
        self.assertTrue(all(record["body"]["evaluation_state"] == "incomplete" for record in assessments))
        self.assertEqual(self.service.resolve(current["body"]["identity_keys"]), current)
        self.assertEqual(self._bindings(current), bindings)
        self.assertEqual(self.record_counts(), {"assessment": 3, "matter": 1, "matter:projection": 1, "receipt": 5})
        for record in assessments:
            self.assertEqual(self.storage.history(pin(record)), [record])

    def test_same_key_values_in_distinct_declared_namespaces_remain_distinct_subjects(self):
        first_key = identity_key("same-value", "example:subject")
        second_key = identity_key("same-value", "example:registry")
        _, _, _, first = self._new("first", keys=[first_key])
        _, _, _, second = self._new("second", keys=[second_key])
        self.assertNotEqual(entity_ref(first), entity_ref(second))
        self.assertEqual(self.service.resolve([first_key]), first)
        self.assertEqual(self.service.resolve([second_key]), second)

    def test_scope_collisions_stay_separate_and_foreign_metadata_cannot_be_read_or_linked(self):
        _, _, _, local = self._new()
        foreign_scope = "synthetic:foreign"
        foreign_command = matter_command("original", matter_id=local["id"], scope_id=foreign_scope)
        with SQLiteStore(self.database, scope_id=foreign_scope) as foreign_storage:
            foreign_service = MatterService(foreign_storage, identity_policy=identity_policy())
            result = foreign_service.create(foreign_service.prepare(foreign_command))
            self.assertEqual(result["outcome"], "created")
            foreign = foreign_storage.get(result["body"]["matter"])
            self.assertEqual(self.service.resolve([identity_key()]), local)
            self.assertEqual(foreign_service.resolve([identity_key()]), foreign)
            self.assertNotEqual(entity_ref(local), entity_ref(foreign))
            for store, reference in ((self.storage, pin(foreign)), (foreign_storage, pin(local))):
                with self.assertRaises(StorageError) as error:
                    store.get(reference)
                self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
            command = metadata_command("foreign-target", local, {"title": "Forbidden cross-scope update"})
            command["body"]["matter"] = pin(foreign)
            failure = self.service.update_metadata(command)
            self.assert_failure(failure, "E_SCOPE_FORBIDDEN")
            self.assertEqual(foreign_service.resolve([identity_key()]), foreign)
            self.assertEqual(self.service.resolve([identity_key()]), local)

    def test_unresolved_observation_intake_can_remain_without_any_matter(self):
        observations = ObservationIngestor(self.storage, FilePayloadStore(self.payload_directory, scope_id=SCOPE))
        command = observation_command("unresolved", "unresolved", scope_id=SCOPE)
        result = observations.ingest(observations.prepare(command), payload=PAYLOAD)
        self.assertEqual(result["outcome"], "committed")
        self.assertIsNone(self.service.resolve([identity_key()]))
        self.assertEqual(self.record_counts(), {"observation": 1, "matter:projection": 1, "receipt": 1})

    def test_unavailable_storage_does_not_turn_resolution_into_no_match(self):
        self._new()
        self.storage.close()
        with self.assertRaises(StorageError) as error:
            self.service.resolve([identity_key()])
        self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")

    def test_competing_create_processes_produce_one_identity_and_a_durable_losing_command(self):
        commands = [self.service.prepare(matter_command(f"create-{label}")) for label in ("one", "two")]
        results = competing_matter_results(self, self.database, commands)
        winners = [command for command in commands if results[command["command_id"]]["status"] == "success"]
        losers = [command for command in commands if results[command["command_id"]]["status"] == "failure"]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(losers), 1, results)
        first, loser = results[winners[0]["command_id"]], results[losers[0]["command_id"]]
        self.assertEqual(first["outcome"], "created")
        self.assert_failure(loser, "E_REVISION_CONFLICT")
        stored = self.storage.get(first["body"]["matter"])
        self.assertEqual(self.service.resolve([identity_key()]), stored)
        self.assert_missing(entity_ref(losers[0]["body"]["matter"]))
        self.assertEqual(self.service.create(losers[0]), loser)
        self.assertEqual(self.storage.command_receipt(losers[0]["idempotency_key"])["result"], loser)
        _, converged = self.submit_create(matter_command("new-command-after-race"))
        self.assertEqual(converged["outcome"], "existing")
        self.assertEqual(converged["body"]["matter"], pin(stored))
        self.assertEqual(self.storage.history(pin(stored)), [stored])
        self.assertEqual(self._bindings(stored)[0]["revision"], 1)
        self.assertEqual(self.record_counts(), {"matter": 1, "matter:projection": 1, "receipt": 3})

    def test_competing_metadata_processes_preserve_history_and_require_a_fresh_cas(self):
        _, _, _, original = self._new()
        bindings = self._bindings(original)
        commands = [self.service.prepare(metadata_command(f"metadata-{label}", original, {"title": label}))
                    for label in ("one", "two")]
        results = competing_matter_results(self, self.database, commands)
        winners = [command for command in commands if results[command["command_id"]]["status"] == "success"]
        losers = [command for command in commands if results[command["command_id"]]["status"] == "failure"]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(losers), 1, results)
        success, failure = results[winners[0]["command_id"]], results[losers[0]["command_id"]]
        self.assertEqual(success["outcome"], "updated")
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        winner = self.storage.get(success["body"]["matter"])
        self.assertEqual(winner["body"]["title"], winners[0]["body"]["metadata"]["title"])
        self.assertEqual(winner["revision"], 2)
        self.assertEqual(self.storage.history(entity_ref(original)), [original, winner])
        self.assertEqual(self.service.update_metadata(losers[0]), failure)
        fresh = metadata_command("metadata-fresh-cas", winner, losers[0]["body"]["metadata"])
        _, committed = self.submit_metadata(fresh)
        self.assertEqual(committed["outcome"], "updated")
        current = self.storage.get(committed["body"]["matter"])
        self.assertEqual(current["revision"], 3)
        self.assertEqual(current["body"]["title"], losers[0]["body"]["metadata"]["title"])
        self.assertEqual(entity_ref(current), entity_ref(original))
        self.assertEqual(self.storage.history(entity_ref(original)), [original, winner, current])
        self.assertEqual(self._bindings(current), bindings)
