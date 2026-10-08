"""Accepted many-to-many memberships, corrections, lineage and checked races."""

from copy import deepcopy

from matter.canonical import canonical_bytes
from matter.occurrences import OccurrenceService, occurrence_index_ref
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.provenance_groups import assignment_ref
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from integration.helpers import _in_scope, create_command, create_matter, ingest_observation
from observation_helpers import observation_command
from occurrence_helpers import (
    DIAGNOSTIC,
    SCOPE,
    OccurrenceTestCase,
    competing_groupings,
    coverage,
    declared,
    event_key,
    group_key,
    grouping_command,
    grouping_policy,
    occurrence_input,
    replacement,
    unknown,
)


class OccurrenceGroupingTests(OccurrenceTestCase):
    def test_split_revises_membership_atomically_and_preserves_original_reports_and_history(self):
        first = self.observe("execution-a-log")
        second = self.observe("execution-b-log")
        old = self.group("execution-a", [first, second], assignments=[declared(first), declared(second)])
        self.assert_counts(self.count([first, second]), 2, 1, 1)
        proposed = occurrence_input("execution-b", [second])
        command = grouping_command("split-mistaken-group", creates=[proposed],
                                   replacements=[replacement(old, [first])])
        prepared, result = self.submit(command)
        self.assertEqual(result["outcome"], "committed")
        current = self.storage.get(entity_ref(old))
        created = self.storage.get(entity_ref(proposed))
        self.assertEqual(result["body"]["previous"], [pin(old)])
        self.assertCountEqual(result["body"]["occurrences"], [pin(current), pin(created)])
        self.assertEqual(current["revision"], 2)
        self.assertEqual(created["revision"], 1)
        self.assertEqual(current["body"]["observations"], [pin(first)])
        self.assertEqual(created["body"]["observations"], [pin(second)])
        self.assertEqual(current["body"]["identity_keys"], old["body"]["identity_keys"])
        self.assertEqual(current["creation_receipt"], old["creation_receipt"])
        self.assertEqual(self.storage.history(entity_ref(old)), [old, current])
        self.assertEqual(self.storage.history(pin(first)), [first])
        self.assertEqual(self.storage.history(pin(second)), [second])
        self.assertEqual(self.observations.read_payload(pin(first)).data, DIAGNOSTIC)
        self.assertEqual(self.observations.read_payload(pin(second)).data, DIAGNOSTIC)
        self.assert_counts(self.count([first, second]), 2, 2, 1)
        for record in (current, created):
            self.assertEqual(entity_ref(self.storage.receipt_for(pin(record))), result["receipt"])
            index = self.storage.get(occurrence_index_ref(SCOPE, record))
            self.assertEqual(entity_ref(self.storage.receipt_for(pin(index))), result["receipt"])
        self.assertEqual(self.storage.command_receipt(prepared["idempotency_key"])["command"], prepared)

    def test_removing_membership_preserves_an_empty_shell_without_counting_it(self):
        report = self.observe("report")
        original = self.group("old-group", [report], assignments=[declared(report)])
        retained = self.group("other-happening", [report])
        _, result = self.submit(grouping_command("remove-one-membership", replacements=[replacement(original, [])]))
        self.assertEqual(result["outcome"], "committed")
        empty = self.storage.get(entity_ref(original))
        self.assertEqual(empty["body"]["observations"], [])
        self.assertEqual(empty["body"]["provenance_groups"], [])
        self.assertEqual(self.service.resolve([event_key("old-group")]), empty)
        self.assertEqual(self.storage.history(entity_ref(original)), [original, empty])
        self.assertEqual(self.service.occurrences_for(pin(report)), [retained])
        self.assert_counts(self.count([report]), 1, 1, 1)
        self.assertEqual(self.storage.get(pin(report)), report)

    def test_set_order_and_repeat_acceptance_are_noops_without_new_revisions(self):
        first, second = self.observe("first"), self.observe("second")
        keys = [event_key("z-key"), event_key("a-key")]
        occurrence = self.group("event", [second, first], keys=keys,
                                assignments=[declared(first), declared(second)])
        self.assertEqual(occurrence["body"]["identity_keys"], sorted(keys, key=canonical_bytes))
        self.assertEqual(occurrence["body"]["observations"], sorted([pin(first), pin(second)], key=canonical_bytes))
        self.assertEqual(occurrence["body"]["provenance_groups"], [group_key()])
        index = self.storage.get(occurrence_index_ref(SCOPE, occurrence))
        old_assignment = self.storage.get(assignment_ref(SCOPE, pin(first)))
        command = grouping_command("same-members-reordered", replacements=[replacement(occurrence, [first, second])],
                                   assignments=[declared(first)])
        _, repeated = self.submit(command)
        self.assertEqual(repeated["outcome"], "unchanged")
        self.assertEqual(repeated["body"]["previous"], [])
        proposed = occurrence_input("unused-proposal", [first, second], keys=list(reversed(keys)))
        _, exact_event = self.submit(grouping_command("same-event-new-proposal", creates=[proposed]))
        self.assertEqual(exact_event["outcome"], "unchanged")
        self.assertEqual(exact_event["body"]["occurrences"], [pin(occurrence)])
        self.assert_missing(entity_ref(proposed))
        self.assertEqual(self.storage.history(entity_ref(occurrence)), [occurrence])
        self.assertEqual(self.storage.get(entity_ref(index)), index)
        self.assertEqual(self.storage.get(entity_ref(old_assignment)), old_assignment)

    def test_existing_execution_key_does_not_silently_change_members_or_event_details(self):
        first, second = self.observe("first"), self.observe("second")
        occurrence = self.group("event", [first], assignments=[declared(first)])
        for label, members in (("new-members", [first, second]), ("new-time", [first])):
            with self.subTest(change=label):
                proposed = occurrence_input(label, members, execution="event")
                if label == "new-time":
                    proposed["body"]["occurred_at"] = {"state": "unknown", "reason": "not_reported"}
                with self.assertRaises(StorageError) as error:
                    self.service.prepare(grouping_command(label, creates=[proposed]))
                self.assertEqual(error.exception.code, "E_ASSOCIATION_CONFLICT")
                self.assert_missing(entity_ref(proposed))
        self.assertEqual(self.service.resolve([event_key("event")]), occurrence)
        self.assertEqual(self.service.occurrences_for(pin(second)), [])

    def test_correcting_a_root_group_propagates_through_transitive_ancestry_only(self):
        root = self.observe("root")
        report = self.observe("report", parents=[root])
        summary = self.observe("summary", parents=[report])
        unrelated = self.observe("unrelated")
        affected = self.group("affected", [summary], assignments=[declared(root, group_key("old"))])
        untouched = self.group("untouched", [unrelated], assignments=[declared(unrelated, group_key("unrelated"))])
        old_assignment = self.storage.get(assignment_ref(SCOPE, pin(root)))
        command = grouping_command("correct-root", assignments=[declared(root, group_key("corrected"))])
        prepared, result = self.submit(command)
        self.assertEqual(result["outcome"], "committed")
        updated = self.storage.get(entity_ref(affected))
        assignment = self.storage.get(assignment_ref(SCOPE, pin(root)))
        self.assertEqual(assignment["revision"], old_assignment["revision"] + 1)
        self.assertEqual(updated["revision"], affected["revision"] + 1)
        self.assertEqual(updated["body"]["observations"], [pin(summary)])
        self.assertEqual(updated["body"]["provenance_groups"], [group_key("corrected")])
        self.assertEqual(result["body"]["previous"], [pin(affected)])
        self.assertEqual(result["body"]["occurrences"], [pin(updated)])
        self.assertIn(pin(old_assignment), prepared["expected_revisions"])
        self.assertIn(pin(affected), prepared["expected_revisions"])
        self.assertEqual(self.storage.history(entity_ref(affected)), [affected, updated])
        self.assertEqual(self.storage.history(entity_ref(untouched)), [untouched])
        for original in (root, report, summary, unrelated):
            self.assertEqual(self.storage.get(pin(original)), original)
        self.assertEqual(self.count([summary])["provenance_groups"], [group_key("corrected")])

    def test_resolving_unknown_root_assignment_updates_descendant_counts_and_history(self):
        root = self.observe("root")
        summary = self.observe("summary", parents=[root])
        old = self.group("execution", [summary], assignments=[unknown(root)])
        before = self.count([summary])
        self.assert_counts(before, 1, 1, 0)
        self.assertEqual(before["provenance_coverage"]["status"], "partial")
        _, result = self.submit(grouping_command("declare-known-root", assignments=[declared(root)]))
        self.assertEqual(result["outcome"], "committed")
        current = self.storage.get(entity_ref(old))
        self.assertEqual(current["revision"], 2)
        self.assertEqual(old["body"]["provenance_groups"], [])
        self.assertEqual(current["body"]["provenance_groups"], [group_key()])
        after = self.count([summary])
        self.assert_counts(after, 1, 1, 1)
        self.assertEqual(after["unresolved_provenance"], [])
        self.assertEqual(after["provenance_coverage"]["status"], "complete")
        self.assertNotEqual(after["provenance_coverage"]["snapshot"], before["provenance_coverage"]["snapshot"])

    def test_parented_and_evaluator_reports_cannot_be_assigned_an_independent_root_group(self):
        root = self.observe("root")
        summary = self.observe("summary", parents=[root])
        parented_source = self.observe("parented-source", parents=[root], origin="source")
        evaluator = self.observe("evaluator", origin="evaluator")
        counts = self.record_counts()
        for observation in (summary, parented_source, evaluator):
            with self.subTest(observation=observation["id"]):
                command = grouping_command(f"forged-root:{observation['id']}", assignments=[declared(observation)])
                with self.assertRaises(StorageError) as error:
                    self.service.prepare(command)
                self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")
                self.assert_missing(assignment_ref(SCOPE, pin(observation)))
        self.assertEqual(self.record_counts(), counts)

    def test_missing_ancestor_remains_explicit_in_accepted_grouping_and_counts(self):
        command = observation_command("import-incomplete-lineage", "orphan", payload=DIAGNOSTIC,
                                      scope_id=SCOPE, event_id="orphan")
        absent = {"scope_id": SCOPE, "namespace": "example", "record_type": "observation",
                  "id": "missing-ancestor", "digest": "0" * 64}
        command["body"]["observation"]["provenance"].update(origin="derived", parents=[absent])
        # An imported, structurally valid historical fixture has unavailable
        # ancestry. Normal ObservationIngestor admission would refuse this pin.
        self.payloads.put(DIAGNOSTIC)
        result = self.storage.execute(command, ingest_observation)
        self.assertEqual(result["status"], "success", result)
        orphan = self.storage.get(result["body"]["observation"])
        occurrence = self.group("incomplete-event", [orphan])
        counted = self.count([orphan])
        self.assert_counts(counted, 1, 1, 0)
        self.assertEqual(occurrence["body"]["provenance_groups"], [])
        self.assertEqual(counted["provenance_coverage"]["status"], "partial")
        self.assertEqual(counted["unresolved_provenance"], [{
            "observation": pin(orphan), "reason": "missing_parent", "parent": absent,
        }])

    def test_non_observation_parent_does_not_become_a_fresh_provenance_root(self):
        command = create_command("synthetic-matter-parent", "matter-parent", scope_id=SCOPE)
        result = self.storage.execute(command, create_matter)
        self.assertEqual(result["status"], "success", result)
        parent = self.storage.get(result["body"]["matter"])
        summary = self.observe("summary-of-matter", parents=[parent])
        self.group("reported-event", [summary])
        counted = self.count([summary])
        self.assert_counts(counted, 1, 1, 0)
        self.assertEqual(counted["unresolved_provenance"], [{
            "observation": pin(summary), "reason": "non_observation_parent", "parent": pin(parent),
        }])
        self.assertEqual(counted["provenance_coverage"]["status"], "partial")

    def test_duplicate_members_targets_keys_and_root_assignments_are_refused_without_writes(self):
        report = self.observe("report")
        old = self.group("original", [report], assignments=[declared(report)])
        duplicate_key = occurrence_input("duplicate-key", [report], keys=[event_key("new"), event_key("new")])
        duplicate_target = occurrence_input("duplicate-target", [report])
        cases = (
            grouping_command("duplicate-member", creates=[occurrence_input("duplicate-member", [report, report])]),
            grouping_command("duplicate-key", creates=[duplicate_key]),
            grouping_command("duplicate-create", creates=[duplicate_target, deepcopy(duplicate_target)]),
            grouping_command("duplicate-replacement", replacements=[replacement(old, []), replacement(old, [report])]),
            grouping_command("duplicate-assignment", assignments=[declared(report), unknown(report)]),
        )
        counts = self.record_counts()
        for command in cases:
            with self.subTest(command=command["command_id"]):
                with self.assertRaises(StorageError) as error:
                    self.service.prepare(command)
                self.assertEqual(error.exception.code, "E_SCHEMA_INVALID")
        self.assertEqual(self.record_counts(), counts)
        self.assertEqual(self.storage.history(entity_ref(old)), [old])

    def test_missing_or_wrongly_pinned_direct_members_fail_durably_without_children(self):
        report = self.observe("report")
        for label in ("missing", "wrong-digest"):
            with self.subTest(reference=label):
                bad = pin(report)
                bad["id" if label == "missing" else "digest"] = "missing-report" if label == "missing" else "0" * 64
                proposed = occurrence_input(label, [bad])
                command = grouping_command(label, creates=[proposed], expected_revisions=[bad])
                result = self.service.commit(command)
                self.assert_failure(result, "E_REVISION_CONFLICT")
                self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], result)
                self.assert_missing(entity_ref(proposed))
                self.assert_missing(occurrence_index_ref(SCOPE, proposed))
        self.assertNotIn("occurrence", self.record_counts())

    def test_policy_mismatch_is_a_durable_refusal_before_group_creation(self):
        report = self.observe("report")
        proposed = occurrence_input("event", [report])
        command = grouping_command("unsupported-policy", creates=[proposed])
        command["body"]["grouping_policy"]["version"] = "99.0"
        result = self.service.commit(command)
        self.assert_failure(result, "E_POLICY_INVALID")
        self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], result)
        self.assert_missing(entity_ref(proposed))

    def test_batch_conflict_cannot_leave_the_earlier_valid_creation_committed(self):
        report = self.observe("report")
        first = occurrence_input("would-be-created", [report])
        occupied = occurrence_input(report["id"], [report])
        command = grouping_command("batch-id-conflict", creates=[first, occupied], expected_revisions=[pin(report)])
        result = self.service.commit(command)
        self.assert_failure(result, "E_SOURCE_IDENTITY_CONFLICT")
        self.assert_missing(entity_ref(first))
        self.assertEqual(self.storage.get(pin(report)), report)
        self.assertNotIn("occurrence", self.record_counts())
        journal = self.storage.command_receipt(command["idempotency_key"])
        self.assertEqual(journal["receipt"]["body"]["details"]["value"]["writes"], [])

    def test_new_dependent_after_root_correction_preparation_cannot_escape_propagation(self):
        root = self.observe("root")
        report = self.observe("report", parents=[root])
        summary = self.observe("summary", parents=[report])
        self.submit(grouping_command("initial-root", assignments=[declared(root, group_key("before"))]))
        correction = self.service.prepare(grouping_command("frozen-correction", assignments=[declared(root, group_key("after"))]))
        dependent = self.group("late-dependent", [summary])
        failure = self.service.commit(correction)
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        self.assertEqual(self.service.commit(correction), failure)
        self.assertEqual(self.storage.get(entity_ref(dependent)), dependent)
        self.assertEqual(self.count([summary])["provenance_groups"], [group_key("before")])
        _, result = self.submit(grouping_command("fresh-correction", assignments=[declared(root, group_key("after"))]))
        self.assertEqual(result["outcome"], "committed")
        updated = self.storage.get(entity_ref(dependent))
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["body"]["provenance_groups"], [group_key("after")])
        self.assertEqual(result["body"]["previous"], [pin(dependent)])

    def test_root_correction_after_membership_preparation_refuses_obsolete_group_data(self):
        root = self.observe("root")
        summary = self.observe("summary", parents=[root])
        self.submit(grouping_command("initial-root", assignments=[declared(root, group_key("before"))]))
        proposed = occurrence_input("proposed-event", [summary])
        frozen = self.service.prepare(grouping_command("frozen-membership", creates=[proposed]))
        self.submit(grouping_command("change-root", assignments=[declared(root, group_key("after"))]))
        failure = self.service.commit(frozen)
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        self.assert_missing(entity_ref(proposed))
        self.assertEqual(self.service.commit(frozen), failure)
        _, result = self.submit(grouping_command("fresh-membership", creates=[proposed]))
        self.assertEqual(result["outcome"], "committed")
        stored = self.storage.get(entity_ref(proposed))
        self.assertEqual(stored["body"]["provenance_groups"], [group_key("after")])

    def test_stale_occurrence_and_index_pins_are_refused_without_refreshing_the_callers_command(self):
        report = self.observe("report")
        old = self.group("event", [report], assignments=[declared(report, group_key("before"))])
        old_index = self.storage.get(occurrence_index_ref(SCOPE, old))
        self.submit(grouping_command("change-root", assignments=[declared(report, group_key("after"))]))
        command = grouping_command("stale-replacement", replacements=[replacement(old, [])],
                                   expected_revisions=[pin(old), pin(old_index)])
        before = deepcopy(command)
        with self.assertRaises(StorageError) as error:
            self.service.prepare(command)
        self.assertEqual(error.exception.code, "E_REVISION_CONFLICT")
        self.assertEqual(command, before)
        failure = self.service.commit(command)
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        self.assertEqual(self.service.occurrences_for(pin(report))[0]["revision"], 2)

    def test_exact_grouping_retry_after_restart_does_not_restore_superseded_membership(self):
        first, second = self.observe("first"), self.observe("second")
        proposed = occurrence_input("event", [first, second])
        original_command, original_result = self.submit(grouping_command(
            "initial-grouping", creates=[proposed], assignments=[declared(first), declared(second)],
        ))
        old = self.storage.get(entity_ref(proposed))
        _, correction = self.submit(grouping_command("correct-grouping", replacements=[replacement(old, [first])]))
        current = self.storage.get(entity_ref(old))
        self.assertEqual(correction["outcome"], "committed")
        self.storage.close()
        with SQLiteStore(self.database, scope_id=SCOPE) as reopened:
            service = OccurrenceService(reopened, grouping_policy=grouping_policy())
            self.assertEqual(service.prepare(original_command), original_command)
            self.assertEqual(service.commit(original_command), original_result)
            self.assertEqual(service.resolve([event_key("event")]), current)
            self.assertEqual(service.occurrences_for(pin(first)), [current])
            self.assertEqual(service.occurrences_for(pin(second)), [])
            self.assertEqual(reopened.history(entity_ref(old)), [old, current])

    def test_same_execution_keys_in_another_scope_remain_isolated(self):
        report = self.observe("report")
        local = self.group("event", [report], assignments=[declared(report)])
        foreign_scope = "synthetic:foreign"
        with SQLiteStore(self.database, scope_id=foreign_scope) as storage:
            observations = ObservationIngestor(storage, FilePayloadStore(self.directory / "payloads", scope_id=foreign_scope))
            command = _in_scope(self.observation_commands["report"], foreign_scope)
            result = observations.ingest(observations.prepare(command), payload=DIAGNOSTIC)
            foreign_report = storage.get(result["body"]["observation"])
            service = OccurrenceService(storage, grouping_policy=grouping_policy())
            proposed = occurrence_input("event", [foreign_report], scope_id=foreign_scope)
            command = grouping_command("group:event", creates=[proposed], assignments=[declared(foreign_report)], scope_id=foreign_scope)
            result = service.commit(service.prepare(command))
            self.assertEqual(result["outcome"], "committed")
            foreign = storage.get(entity_ref(proposed))
            self.assertEqual(self.service.resolve([event_key("event")]), local)
            self.assertEqual(service.resolve([event_key("event")]), foreign)
            self.assertNotEqual(entity_ref(local), entity_ref(foreign))
            for selected_service, reference in ((self.service, pin(foreign_report)), (service, pin(report))):
                with self.assertRaises(StorageError) as error:
                    selected_service.counts([reference], coverage=coverage())
                self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
            bad = grouping_command("foreign-link", replacements=[replacement(local, [foreign_report])])
            with self.assertRaises(StorageError) as error:
                self.service.prepare(bad)
            self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
            self.assertEqual(self.storage.get(entity_ref(local)), local)

    def test_two_processes_cannot_both_replace_one_membership_revision(self):
        first, second = self.observe("first"), self.observe("second")
        old = self.group("event", [first, second], assignments=[declared(first), declared(second)])
        commands = [self.service.prepare(grouping_command(f"replace-{label}", replacements=[replacement(old, [record])]))
                    for label, record in (("first", first), ("second", second))]
        results = competing_groupings(self, self.database, commands)
        winners = [command for command in commands if results[command["command_id"]]["status"] == "success"]
        losers = [command for command in commands if results[command["command_id"]]["status"] == "failure"]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(losers), 1, results)
        self.assertEqual(results[winners[0]["command_id"]]["outcome"], "committed")
        failure = results[losers[0]["command_id"]]
        self.assert_failure(failure, "E_REVISION_CONFLICT")
        current = self.storage.get(entity_ref(old))
        self.assertEqual(current["body"]["observations"], winners[0]["body"]["replacements"][0]["observations"])
        self.assertEqual(self.storage.history(entity_ref(old)), [old, current])
        self.assertEqual(self.service.commit(losers[0]), failure)
        self.assertEqual(self.storage.command_receipt(losers[0]["idempotency_key"])["result"], failure)
        fresh = grouping_command("fresh-replacement", replacements=[replacement(current, losers[0]["body"]["replacements"][0]["observations"])])
        _, committed = self.submit(fresh)
        self.assertEqual(committed["outcome"], "committed")
        self.assertEqual(self.storage.get(entity_ref(old))["revision"], 3)

    def test_two_processes_cannot_create_two_occurrences_for_one_exact_execution_key(self):
        report = self.observe("report")
        self.submit(grouping_command("declare-root", assignments=[declared(report)]))
        commands = [self.service.prepare(grouping_command(f"create-{label}", creates=[
            occurrence_input(f"proposal-{label}", [report], execution="same-execution"),
        ])) for label in ("one", "two")]
        results = competing_groupings(self, self.database, commands)
        winners = [command for command in commands if results[command["command_id"]]["status"] == "success"]
        losers = [command for command in commands if results[command["command_id"]]["status"] == "failure"]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(losers), 1, results)
        self.assert_failure(results[losers[0]["command_id"]], "E_REVISION_CONFLICT")
        stored = self.service.resolve([event_key("same-execution")])
        self.assertEqual(entity_ref(stored), entity_ref(winners[0]["body"]["creates"][0]))
        self.assert_missing(entity_ref(losers[0]["body"]["creates"][0]))
        self.assert_counts(self.count([report]), 1, 1, 1)
        self.assertEqual(self.record_counts()["occurrence"], 1)
