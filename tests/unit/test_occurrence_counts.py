"""Named observation, occurrence and provenance counts over explicit cohorts."""

from copy import deepcopy

from matter.storage import StorageError, pin

from occurrence_helpers import (
    OccurrenceTestCase,
    coverage,
    declared,
    group_key,
    grouping_command,
    unknown,
)


class OccurrenceCountTests(OccurrenceTestCase):
    def test_a_log_and_its_derived_report_are_two_observations_one_occurrence_one_group(self):
        log = self.observe("log")
        report = self.observe("report", parents=[log])
        occurrence = self.group("execution-a", [log, report], assignments=[declared(log)])
        result = self.count([log, report])
        self.assert_counts(result, 2, 1, 1)
        self.assertCountEqual(result["observations"], [pin(log), pin(report)])
        self.assertEqual(result["occurrences"], [pin(occurrence)])
        self.assertEqual(result["provenance_groups"], [group_key()])
        self.assertEqual(result["unassociated_observations"], [])
        self.assertEqual(result["unresolved_provenance"], [])
        self.assertEqual(result["provenance_coverage"]["status"], "complete")
        self.assertIn(pin(log), result["dependencies"])
        self.assertIn(pin(report), result["dependencies"])
        self.assertIn(pin(occurrence), result["dependencies"])

    def test_a_standing_requirement_can_have_no_occurrence(self):
        requirement = self.observe("requirement", payload=b"Synthetic standing requirement: retain audit receipts.\n")
        _, accepted = self.submit(grouping_command("declare-requirement-root", assignments=[declared(requirement)]))
        self.assertEqual(accepted["outcome"], "committed")
        result = self.count([requirement])
        self.assert_counts(result, 1, 0, 1)
        self.assertEqual(result["unassociated_observations"], [pin(requirement)])
        self.assertEqual(self.service.occurrences_for(pin(requirement)), [])
        self.assertNotIn("occurrence", self.record_counts())
        self.assertNotIn("matter", self.record_counts())

    def test_one_report_can_describe_two_happenings_without_duplicating_observation_or_group_counts(self):
        report = self.observe("two-happenings")
        first = self.group("execution-a", [report], assignments=[declared(report)])
        second = self.group("execution-b", [report])
        result = self.count([report, report, report])
        self.assert_counts(result, 1, 2, 1)
        self.assertEqual(result["observations"], [pin(report)])
        self.assertCountEqual(result["occurrences"], [pin(first), pin(second)])
        self.assertCountEqual(self.service.occurrences_for(pin(report)), [first, second])

    def test_identical_text_from_another_execution_increases_recurrence_without_proving_a_claim(self):
        first_report = self.observe("execution-a-log")
        self.group("execution-a", [first_report], assignments=[declared(first_report)])
        before = self.count([first_report])
        self.assert_counts(before, 1, 1, 1)
        second_report = self.observe("execution-b-log")
        self.assertEqual(first_report["body"]["content"]["digest"], second_report["body"]["content"]["digest"])
        self.group("execution-b", [second_report], assignments=[declared(second_report)])
        after = self.count([first_report, second_report])
        self.assert_counts(after, 2, 2, 1)
        for kind in ("claim", "evidence_relation", "judgment", "assessment", "matter"):
            self.assertNotIn(kind, self.record_counts())
        for unsupported_conclusion in ("cause", "truth", "independent_confirmations"):
            self.assertNotIn(unsupported_conclusion, after)

    def test_summary_of_two_roots_inherits_the_union_without_creating_or_collapsing_a_group(self):
        first = self.observe("first-root")
        second = self.observe("second-root")
        summary = self.observe("summary", parents=[first, second])
        first_occurrence = self.group("execution-a", [first, summary], assignments=[
            declared(first, group_key("g1")), declared(second, group_key("g2")),
        ])
        second_occurrence = self.group("execution-b", [second, summary])
        result = self.count([summary])
        self.assert_counts(result, 1, 2, 2)
        self.assertCountEqual(result["provenance_groups"], [group_key("g1"), group_key("g2")])
        self.assertCountEqual(result["occurrences"], [pin(first_occurrence), pin(second_occurrence)])
        self.assertEqual(result["unresolved_provenance"], [])
        self.assertEqual(self.storage.get(pin(summary))["provenance"]["parents"], [pin(first), pin(second)])

    def test_peers_in_a_shared_occurrence_do_not_inflate_the_selected_packets_groups(self):
        selected = self.observe("selected-root")
        peer = self.observe("unselected-peer")
        self.group("one-happening", [selected, peer], assignments=[
            declared(selected, group_key("selected")), declared(peer, group_key("peer")),
        ])
        result = self.count([selected])
        self.assert_counts(result, 1, 1, 1)
        self.assertEqual(result["provenance_groups"], [group_key("selected")])
        self.assert_counts(self.count([selected, peer]), 2, 1, 2)

    def test_unassigned_and_explicitly_unknown_roots_remain_unresolved(self):
        undeclared = self.observe("unassigned")
        uncertain = self.observe("unknown")
        self.group("execution-a", [undeclared, uncertain], assignments=[unknown(uncertain, "Synthetic source relationships are unknown.")])
        result = self.count([undeclared, uncertain])
        self.assert_counts(result, 2, 1, 0)
        self.assertEqual(result["coverage"]["status"], "complete")
        self.assertEqual(result["provenance_coverage"]["status"], "partial")
        unresolved = {entry["observation"]["id"]: entry for entry in result["unresolved_provenance"]}
        self.assertEqual(set(unresolved), {"unassigned", "unknown"})
        self.assertEqual(unresolved["unassigned"]["reason"], "unassigned_root")
        self.assertEqual(unresolved["unknown"]["reason"], "unknown_root")
        self.assertEqual(unresolved["unknown"]["detail"], "Synthetic source relationships are unknown.")

    def test_evaluator_root_is_not_promoted_to_a_source_group(self):
        evaluator = self.observe("evaluator-output", origin="evaluator")
        self.group("reported-event", [evaluator])
        result = self.count([evaluator])
        self.assert_counts(result, 1, 1, 0)
        self.assertEqual(result["unresolved_provenance"], [{"observation": pin(evaluator), "reason": "non_source_root"}])
        self.assertEqual(result["provenance_coverage"]["status"], "partial")

    def test_declared_source_origin_does_not_erase_actual_parent_dependence(self):
        source = self.observe("root")
        parented = self.observe("parented-source", parents=[source], origin="source")
        self.group("execution-a", [source, parented], assignments=[declared(source)])
        result = self.count([source, parented])
        self.assert_counts(result, 2, 1, 1)
        self.assertEqual(result["provenance_groups"], [group_key()])
        self.assertEqual(result["unresolved_provenance"], [])

    def test_group_namespace_is_part_of_the_exact_group_identity(self):
        first = self.observe("first")
        second = self.observe("second")
        one = group_key("same-value")
        two = group_key("same-value", namespace="example:alternate-lineage")
        self.group("execution-a", [first, second], assignments=[declared(first, one), declared(second, two)])
        result = self.count([first, second])
        self.assert_counts(result, 2, 1, 2)
        self.assertCountEqual(result["provenance_groups"], [one, two])

    def test_empty_counts_preserve_required_source_coverage_without_claiming_absence(self):
        for status in ("complete", "partial", "failed", "not_expected_yet", "expected_not_published", "manual_review"):
            with self.subTest(coverage=status):
                supplied = coverage(status)
                result = self.count([], source_coverage=supplied)
                self.assert_counts(result, 0, 0, 0)
                self.assertEqual(result["coverage"], supplied)
                self.assertEqual(result["observations"], [])
                self.assertEqual(result["occurrences"], [])
        with self.assertRaises(TypeError):
            self.service.counts([])

    def test_count_results_and_coverage_are_defensive_and_storage_failure_is_explicit(self):
        report = self.observe("report")
        occurrence = self.group("execution-a", [report], assignments=[declared(report)])
        selected, supplied = [pin(report)], coverage("partial")
        before = deepcopy((selected, supplied))
        result = self.service.counts(selected, coverage=supplied)
        result["coverage"]["snapshot"]["id"] = "changed-copy"
        result["observations"][0]["id"] = "changed-copy"
        result["counts"]["occurrences"] = 99
        self.assertEqual((selected, supplied), before)
        self.assertEqual(self.storage.get(pin(occurrence)), occurrence)
        self.assert_counts(self.count([report]), 1, 1, 1)
        self.storage.close()
        with self.assertRaises(StorageError) as error:
            self.service.counts(selected, coverage=supplied)
        self.assertEqual(error.exception.code, "E_STORAGE_UNAVAILABLE")
