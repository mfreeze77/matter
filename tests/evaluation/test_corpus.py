"""Behavioral corpus contract checks, independent of provider execution."""

from copy import deepcopy
from pathlib import Path
import unittest

from matter.canonical import canonical_bytes, source_digest
from matter.contracts import ContractError
from matter.evaluation import freeze_corpus, load_jsonl, validate_episode


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/evaluation/episodes.jsonl"


def time(value):
    return {"state": "known", "value": value,
            "precision": "nanosecond" if "." in value else "second"}


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.corpus = load_jsonl(self.raw)
        self.manifest = self.corpus.value

    def reject(self, manifest, path=None):
        with self.assertRaises(ContractError) as caught:
            freeze_corpus(manifest)
        if path:
            self.assertIn(path, str(caught.exception))

    def external(self):
        manifest = self.manifest
        episode = manifest["episodes"][0]
        source = episode["sources"][0]
        payload = source["artifact"]["text"].encode()
        source["artifact"] = {"kind": "external", "reference": "artifact:private-export/one",
                              "permission_reference": "host-reviewed-export:synthetic-reference"}
        key = (episode["id"], source["reference"]["id"], source["reference"]["revision"])
        return manifest, key, payload

    def test_starter_cases_have_explicit_expected_denominators(self):
        report = self.corpus.denominators()
        self.assertEqual(report["total"], 9)
        self.assertEqual(report["counts"], {"eligible": 3, "excluded": 1, "unlabeled": 1,
                         "teacher_only": 1, "derived_only": 1, "disputed": 1, "unresolved": 1, "unverified": 0})
        self.assertEqual(sum(report["counts"].values()), report["total"])
        self.assertEqual(report["label_counts"], {"independent": 7, "teacher": 1, "derived": 1})
        outcomes = {case["case_id"]: case.get("reference_outcome") for case in report["cases"]}
        self.assertEqual(outcomes["routine-attention"], "quiet")
        self.assertEqual(outcomes["failure-recovery"], "unrecovered")
        self.assertEqual(outcomes["late-recovery"], "recovered")
        self.assertIsNone(outcomes["retry-association"])
        self.assertIsNone(outcomes["misleading-attention"])

    def test_quiet_unlabeled_episode_is_preserved(self):
        case = next(item for item in self.corpus.denominators()["cases"] if item["episode_id"] == "quiet")
        self.assertEqual(case["category"], "unlabeled")
        self.assertEqual(self.corpus.value["episodes"][-1]["observations"], [])

    def test_unknown_observation_and_altered_source_pins_fail(self):
        for field, replacement in (("observation_id", "unknown-report"), ("source", {"id": "routine-source", "revision": 999, "sha256": "a" * 64})):
            with self.subTest(field=field):
                manifest = deepcopy(self.manifest)
                manifest["episodes"][0]["labels"][0]["evidence"][0][field] = replacement
                self.reject(manifest, "/evidence")

    def test_wrong_synthetic_source_hash_fails_before_evaluation(self):
        self.manifest["episodes"][0]["sources"][0]["reference"]["sha256"] = "a" * 64
        self.reject(self.manifest, "/sha256")

    def test_labels_need_nonempty_provenance_and_reviewed_evidence(self):
        for transform in (lambda label: label.pop("reviewer"),
                          lambda label: label.update(evidence=[]),
                          lambda label: label["reviewer"].update(role=""),
                          lambda label: label.update(reviewed_at=time("2026-01-01T00:00:00Z"))):
            manifest = deepcopy(self.manifest)
            transform(manifest["episodes"][0]["labels"][0])
            self.reject(manifest)

    def test_teacher_cannot_be_declared_independent_by_origin_alone(self):
        self.manifest["episodes"][2]["labels"][0]["origin"] = "independent"
        self.reject(self.manifest, "/origin")

    def test_independent_disputed_status_excludes_primary_case(self):
        self.manifest["episodes"][0]["labels"][0]["status"] = "disputed"
        report = freeze_corpus(self.manifest).denominators()
        self.assertEqual(report["counts"]["eligible"], 2)
        self.assertEqual(report["counts"]["disputed"], 2)

    def test_teacher_disagreement_does_not_replace_independent_reference(self):
        episode = self.manifest["episodes"][0]
        teacher = deepcopy(episode["labels"][0])
        teacher.update(id="teacher-routine", origin="teacher", outcome="intervene",
                       reviewer={"kind": "model", "role": "synthetic-teacher"})
        episode["labels"].append(teacher)
        report = freeze_corpus(self.manifest).denominators()
        case = next(item for item in report["cases"] if item["case_id"] == "routine-attention")
        self.assertEqual(case["reference_outcome"], "quiet")
        self.assertEqual(case["label_ids"], ["routine-reviewed", "teacher-routine"])
        self.assertEqual(report["label_counts"]["teacher"], 2)

    def test_late_old_event_is_absent_before_availability(self):
        prefix = self.corpus.prefix(as_of=time("2026-01-01T00:00:03Z"))
        included = {item["observation"]["id"] for item in prefix["included"]}
        self.assertIn("late-original", included)
        self.assertNotIn("late-correction", included)
        self.assertIn({"episode_id": "late-correction", "observation_id": "late-correction", "reason": "not_yet_available"}, prefix["excluded"])
        after = self.corpus.prefix(as_of=time("2026-01-01T00:00:04Z"))
        correction = next(item["observation"] for item in after["included"] if item["observation"]["id"] == "late-correction")
        self.assertEqual(correction["occurred_at"], time("2026-01-01T00:00:01Z"))

    def test_nanosecond_boundary_does_not_round_into_prefix(self):
        episode = self.manifest["episodes"][0]
        availability = time("2026-01-01T00:00:01.000000001Z")
        episode["sources"][0]["available_at"] = availability
        episode["observations"][0]["available_at"] = availability
        corpus = freeze_corpus(self.manifest)
        before = corpus.prefix(as_of=time("2026-01-01T00:00:01.000000000Z"))
        after = corpus.prefix(as_of=availability)
        self.assertNotIn("routine-report", [item["observation"]["id"] for item in before["included"]])
        self.assertIn("routine-report", [item["observation"]["id"] for item in after["included"]])

    def test_prefix_included_inputs_contain_no_future_reference_labels_or_memberships(self):
        prefix = self.corpus.prefix(as_of=time("2026-01-01T00:00:03Z"))
        packet = canonical_bytes(prefix["included"])
        for hidden in (b'"labels"', b'"cases"', b'"late-reviewed"', b'"id":"late-correction"'):
            self.assertNotIn(hidden, packet)
        self.assertEqual(len(prefix["limits"]), 2)

    def test_unknown_availability_stays_unknown_and_not_eligible(self):
        episode = self.manifest["episodes"][0]
        unknown = {"state": "unknown", "reason": "not_observed"}
        episode["sources"][0]["available_at"] = unknown
        episode["observations"][0]["available_at"] = unknown
        episode["labels"] = []
        corpus = freeze_corpus(self.manifest)
        prefix = corpus.prefix(as_of=time("2026-01-01T00:00:09Z"))
        self.assertIn({"episode_id": "routine", "observation_id": "routine-report", "reason": "unknown_availability"}, prefix["unknown"])

    def test_observation_cannot_precede_its_source(self):
        self.manifest["episodes"][0]["sources"][0]["available_at"] = time("2026-01-01T00:00:02Z")
        self.reject(self.manifest, "/available_at")

    def test_copied_report_retains_occurrence_and_provenance_group(self):
        episode = self.corpus.value["episodes"][2]
        original, copied = episode["observations"]
        self.assertEqual(copied["parents"], [original["id"]])
        self.assertEqual(copied["occurrence_ids"], original["occurrence_ids"])
        self.assertEqual(copied["provenance_groups"], original["provenance_groups"])
        self.assertEqual(len(episode["occurrences"]), 1)

    def test_copy_cannot_create_independent_provenance_or_new_occurrence(self):
        for field in ("occurrence_ids", "provenance_groups"):
            manifest = deepcopy(self.manifest)
            manifest["episodes"][2]["observations"][1][field] = ["invented-group-or-occurrence"]
            self.reject(manifest, "/" + field)

    def test_unknown_parent_and_parent_cycles_are_refused(self):
        for parent in ("unknown-parent", "retry-copy"):
            manifest = deepcopy(self.manifest)
            manifest["episodes"][2]["observations"][1]["parents"] = [parent]
            self.reject(manifest, "/parents")

    def test_occurrence_memberships_must_agree(self):
        self.manifest["episodes"][2]["occurrences"][0]["observation_ids"] = ["retry-original"]
        self.reject(self.manifest, "/occurrence_ids")

    def test_equal_time_derivation_requires_parent_first(self):
        episode = self.manifest["episodes"][2]
        episode["observations"][1]["available_at"] = time("2026-01-01T00:00:01Z")
        episode["sources"][1]["available_at"] = time("2026-01-01T00:00:01Z")
        validate_episode(episode)
        episode["observations"].reverse()
        self.reject(self.manifest, "/parents")

    def two_root_observations(self):
        episode = deepcopy(self.manifest["episodes"][0])
        second = deepcopy(self.manifest["episodes"][1])
        episode["sources"].extend(second["sources"])
        episode["observations"].extend(second["observations"])
        episode["observations"][1]["available_at"] = time("2026-01-01T00:00:02Z")
        episode["occurrences"].extend(second["occurrences"])
        return episode

    def test_decreasing_availability_of_root_observations_fails_chronology(self):
        episode = self.two_root_observations()
        # Both roots have valid source availability and no parent relationship;
        # reversing them must exercise chronology, not another earlier guard.
        validate_episode(episode)
        episode["observations"].reverse()
        with self.assertRaises(ContractError) as caught:
            validate_episode(episode)
        self.assertIn("episode/observations/1/available_at", caught.exception.detail)
        self.assertIn("chronological", caught.exception.detail)

    def test_observation_error_paths_do_not_expose_caller_identity(self):
        marker = "PRIVATE-DESCRIPTIVE-OBSERVATION-MARKER"

        def rename(episode, original):
            for observation in episode["observations"]:
                if observation["id"] == original:
                    observation["id"] = marker
                observation["parents"] = [marker if item == original else item for item in observation["parents"]]
            for occurrence in episode["occurrences"]:
                occurrence["observation_ids"] = [marker if item == original else item for item in occurrence["observation_ids"]]
            for case in episode["cases"]:
                case["target_observation_ids"] = [marker if item == original else item for item in case["target_observation_ids"]]
            for label in episode["labels"]:
                for evidence in label["evidence"]:
                    if evidence["observation_id"] == original:
                        evidence["observation_id"] = marker

        parent = deepcopy(self.manifest["episodes"][2])
        rename(parent, "retry-copy")
        validate_episode(parent)
        parent["observations"][1]["parents"] = ["absent-parent"]

        chronology = self.two_root_observations()
        rename(chronology, "routine-report")
        validate_episode(chronology)
        chronology["observations"].reverse()

        membership = deepcopy(self.manifest["episodes"][0])
        rename(membership, "routine-report")
        validate_episode(membership)
        membership["observations"][0]["occurrence_ids"] = []

        for episode, path in ((parent, "episode/observations/1/parents"),
                              (chronology, "episode/observations/1/available_at"),
                              (membership, "episode/observations/0/occurrence_ids")):
            with self.subTest(path=path):
                with self.assertRaises(ContractError) as caught:
                    validate_episode(episode)
                self.assertTrue(caught.exception.detail.startswith(path + ":"))
                self.assertNotIn(marker, caught.exception.detail)
                self.assertNotIn(marker, str(caught.exception))

    def test_external_artifact_is_metadata_only_until_bytes_verified(self):
        manifest, key, payload = self.external()
        corpus = freeze_corpus(manifest)
        self.assertNotIn(payload.decode(), canonical_bytes(corpus.value).decode())
        self.assertEqual(corpus.source_verification[0]["status"], "not_checked")
        report = corpus.denominators()
        self.assertEqual(report["counts"]["unverified"], 1)
        prefix = corpus.prefix(as_of=time("2026-01-01T00:00:09Z"))
        self.assertIn({"episode_id": "routine", "observation_id": "routine-report", "reason": "source_bytes_not_verified"}, prefix["unknown"])
        verified = freeze_corpus(manifest, source_payloads={key: payload})
        self.assertEqual(verified.source_verification[0]["status"], "verified")
        self.assertEqual(verified.denominators()["counts"]["eligible"], 3)
        self.assertEqual(verified.sha256, corpus.sha256)
        self.assertNotIn(payload.decode(), canonical_bytes(verified.value).decode())

    def test_changed_external_bytes_and_unknown_payload_keys_are_refused(self):
        manifest, key, payload = self.external()
        for payloads in ({key: b"wrong source"}, {key: payload.decode()}, {("routine", "absent", 1): payload}):
            with self.subTest(payloads=list(payloads)):
                with self.assertRaises(ContractError):
                    freeze_corpus(manifest, source_payloads=payloads)

    def test_external_artifact_cannot_embed_private_content(self):
        manifest, _, _ = self.external()
        manifest["episodes"][0]["sources"][0]["artifact"]["text"] = "private text"
        self.reject(manifest)

    def test_scoped_episode_and_duplicate_source_case_observation_ids_are_checked(self):
        foreign = deepcopy(self.manifest)
        foreign["episodes"][0]["scope_id"] = "foreign"
        self.reject(foreign, "scope")
        for array in ("sources", "observations", "occurrences", "cases", "labels"):
            with self.subTest(array=array):
                manifest = deepcopy(self.manifest)
                items = manifest["episodes"][0][array]
                items.append(deepcopy(items[0]))
                self.reject(manifest)

    def test_cross_episode_same_identity_cannot_change_source_meaning(self):
        duplicate = deepcopy(self.manifest["episodes"][0])
        duplicate["id"] = "duplicate-episode"
        duplicate["sources"][0]["artifact"]["text"] = "SYNTHETIC altered source"
        reference = duplicate["sources"][0]["reference"]
        reference["sha256"] = source_digest(duplicate["sources"][0]["artifact"]["text"].encode())
        duplicate["observations"][0]["source"] = deepcopy(reference)
        for label in duplicate["labels"]:
            label["evidence"][0]["source"] = deepcopy(reference)
        self.manifest["episodes"].append(duplicate)
        self.reject(self.manifest, "shared source")

    def test_frozen_corpus_survives_caller_mutation(self):
        corpus = freeze_corpus(self.manifest)
        digest = corpus.sha256
        self.manifest["episodes"][0]["labels"][0]["outcome"] = "changed"
        exposed = corpus.value
        exposed["episodes"].clear()
        exposed_verification = corpus.source_verification
        exposed_verification[0]["status"] = "changed"
        self.assertEqual(corpus.sha256, digest)
        self.assertEqual(len(corpus.value["episodes"]), 6)
        self.assertEqual(corpus.source_verification[0]["status"], "verified")
        with self.assertRaises(AttributeError):
            corpus._verified = frozenset()

    def test_label_revision_and_outcome_changes_invalidate_frozen_hash(self):
        digest = self.corpus.sha256
        self.manifest["episodes"][0]["labels"][0]["revision"] = 2
        revised = freeze_corpus(self.manifest)
        self.assertNotEqual(revised.sha256, digest)
        self.manifest["episodes"][0]["labels"][0]["outcome"] = "intervene"
        self.assertNotEqual(freeze_corpus(self.manifest).sha256, revised.sha256)
        with self.assertRaises(ContractError):
            freeze_corpus(self.manifest, expected_sha256=digest)
        freeze_corpus(self.corpus.value, expected_sha256=digest)

    def test_jsonl_snapshot_has_strict_encoding_and_complete_rows(self):
        bad = [self.raw[:-1], self.raw + b"\n", self.raw.replace(b'"id":"synthetic-starter-v1"', b'"id":"a","id":"b"', 1),
               self.raw.replace(b'"revision":1', b'"revision":1.0', 1), b"[]\n", b"", "not bytes"]
        for raw in bad:
            with self.subTest(raw_type=type(raw)):
                with self.assertRaises(ContractError):
                    load_jsonl(raw)

    def test_malformed_enum_and_reference_values_are_safe_contract_failures(self):
        for field in ("origin", "status", "case_id"):
            manifest = deepcopy(self.manifest)
            manifest["episodes"][0]["labels"][0][field] = []
            self.reject(manifest)
        self.manifest["episodes"][0]["labels"][0]["evidence"][0]["observation_id"] = []
        self.reject(self.manifest)


if __name__ == "__main__":
    unittest.main()
