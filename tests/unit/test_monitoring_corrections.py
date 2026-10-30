"""Focused ancestor/read-boundary checks; native SQLite coverage is separate.

These trusted-view fragments exercise correction selection and refusal, not
record persistence, host authorization or provider interpretation.
"""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from matter.canonical import canonical_bytes, canonical_digest
from matter.contracts import ContractError
from matter.statecivics_monitoring import _require_correction_lineage


NOW = {"state": "known", "value": "2050-01-01T00:00:00Z", "precision": "second"}


class MonitoringCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {"scope_id": "test:workspace", "namespace": "synthetic", "record_type": "matter", "id": "subject"}
        self.records, self.reads = {}, []

    def record(self, kind, identity, *, parents=(), subject=None, available=None):
        reference = dict(self.candidate, record_type=kind, id=identity)
        reference["digest"] = canonical_digest(identity, "synthetic.correction-ref")
        body = ({"available_at": deepcopy(NOW if available is None else available)} if kind == "observation" else
                {"matter" if kind == "assessment" else "subject": deepcopy(subject or self.candidate)})
        record = dict(reference, body=body, supersedes=deepcopy(list(parents)))
        self.records[canonical_bytes(reference)] = record
        return record, reference

    def check(self, roots, targets, allowed):
        allowed_refs = list(allowed)
        allowed = {canonical_bytes(ref) for ref in allowed}

        def require_current(view, context, *, references):
            for ref in references:
                self.assertIn(canonical_bytes(ref), allowed)

        def get(ref):
            self.assertIn(canonical_bytes(ref), allowed, "retrieved an unauthorized branch")
            self.reads.append(ref)
            return self.records[canonical_bytes(ref)]

        _require_correction_lineage(SimpleNamespace(get=get),
            access=SimpleNamespace(require_current=require_current),
            context=SimpleNamespace(value={"dependencies": allowed_refs}),
            roots=roots, candidate=self.candidate, targets=targets, as_of=NOW)

    def test_claim_correction_does_not_read_unrelated_observation_history(self):
        _, prior = self.record("claim", "claim-old")
        claim, _ = self.record("claim", "claim-new", parents=[prior])
        _, old_source = self.record("observation", "source-old", available={"state": "unknown", "reason": "unavailable"})
        source, _ = self.record("observation", "source-new", parents=[old_source])
        self.check([claim, source], [prior], [prior])
        self.assertEqual(self.reads, [prior])

    def test_direct_target_stops_before_older_ungranted_history(self):
        _, older = self.record("claim", "older")
        _, prior = self.record("claim", "prior", parents=[older])
        current, _ = self.record("claim", "current", parents=[prior])
        self.check([current], [prior], [prior])
        self.assertEqual(self.reads, [prior])

    def test_observation_correction_accepts_available_ancestor(self):
        _, prior = self.record("observation", "prior")
        current, _ = self.record("observation", "current", parents=[prior])
        self.check([current], [prior], [prior])
        self.assertEqual(self.reads, [prior])

    def test_observation_ancestor_with_unknown_or_future_availability_refuses(self):
        for available in ({"state": "unknown", "reason": "unavailable"},
                          dict(NOW, value="2050-01-02T00:00:00Z")):
            with self.subTest(available=available):
                _, prior = self.record("observation", "prior", available=available)
                current, _ = self.record("observation", "current", parents=[prior])
                with self.assertRaises(ContractError) as error:
                    self.check([current], [prior], [prior])
                self.assertEqual(error.exception.code, "E_EVIDENCE_UNAVAILABLE")

    def test_authorized_unrelated_target_is_not_a_correction(self):
        _, unrelated = self.record("claim", "unrelated")
        current, _ = self.record("claim", "current")
        with self.assertRaises(ContractError) as error:
            self.check([current], [unrelated], [unrelated])
        self.assertEqual(error.exception.code, "E_EVIDENCE_UNAVAILABLE")
        self.assertEqual(self.reads, [])

    def test_foreign_subject_or_cross_type_edge_refuses(self):
        for kind, subject, code in (("claim", dict(self.candidate, id="other"), "E_SCOPE_FORBIDDEN"),
                                    ("observation", None, "E_EVIDENCE_UNAVAILABLE")):
            with self.subTest(kind=kind):
                _, prior = self.record(kind, "prior", subject=subject)
                current, _ = self.record("claim", "current", parents=[prior])
                with self.assertRaises(ContractError) as error:
                    self.check([current], [prior], [prior])
                self.assertEqual(error.exception.code, code)

    def test_transitive_link_does_not_read_an_ungranted_sibling_branch(self):
        _, target = self.record("claim", "target")
        _, middle = self.record("claim", "middle", parents=[target])
        _, unrelated = self.record("claim", "ungranted")
        current, _ = self.record("claim", "current", parents=[unrelated, middle])
        self.check([current], [target], [middle, target])
        self.assertEqual(self.reads, [middle, target])

    def test_ancestor_search_is_bounded(self):
        _, target = self.record("claim", "target")
        previous, allowed = target, [target]
        for i in range(129):
            root, previous = self.record("claim", f"revision-{i}", parents=[previous])
            allowed.append(previous)
        with self.assertRaises(ContractError) as error:
            self.check([root], [target], allowed)
        self.assertEqual(error.exception.code, "E_BUDGET_EXHAUSTED")
        self.assertLessEqual(len(self.reads), 128)
