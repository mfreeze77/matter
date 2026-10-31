"""Capture study selection, wire isolation and unchanged neutral routing."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from matter.contracts import ContractError
from matter.statecivics_capture import MonitoringCapturePolicy, validate_capture_handoff, VERSION
from matter.statecivics_monitoring import conveyed_capture_identity, validate_handoff
from integration.test_monitoring_capture import policy_value


ROOT = Path(__file__).resolve().parents[2]


class MonitoringCapturePolicyTests(unittest.TestCase):
    def test_runtime_and_packaging_version_match(self):
        import matter
        import tomllib
        value = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(matter.__version__, value["project"]["version"])

    def test_explicit_regions_have_exact_boundaries_and_unknown_gap(self):
        policy = MonitoringCapturePolicy(policy_value())
        for probability, expected in [("0.8", "positive"), ("0.80000000000000001", "positive"),
                                      ("0.2", "negative"), ("0.20000000000000001", "unknown"), ("0.5", "unknown")]:
            self.assertEqual(policy.classify("objective", probability), expected)
        value = policy.value
        value["regions"]["objective"]["positive_minimum"] = "0.9"
        self.assertEqual(policy.value["regions"]["objective"]["positive_minimum"], "0.8")

    def test_exact_precision_is_required_and_changed_profile_refuses(self):
        from matter.semantic import PrecisionProfile
        from matter.statecivics_capture import _require_capture_precision
        value = policy_value(); value.pop("precision")
        with self.assertRaises(ContractError):
            MonitoringCapturePolicy(value)
        policy = MonitoringCapturePolicy(policy_value())
        _require_capture_precision(policy, {"precision": PrecisionProfile().value})
        with self.assertRaises(ContractError):
            _require_capture_precision(policy, {"precision": PrecisionProfile(probability_quantum="0.01").value})

    def test_no_default_thresholds_or_overlapping_regions_or_float_coercion(self):
        for change in [lambda p: p.pop("regions"), lambda p: p["regions"].pop("novelty"),
                       lambda p: p["regions"]["objective"].update(negative_maximum="0.8"),
                       lambda p: p["regions"]["objective"].update(positive_minimum=0.8),
                       lambda p: p["regions"]["objective"].update(positive_minimum="NaN"),
                       lambda p: p["regions"]["objective"].update(positive_minimum="0.8\n")]:
            value = policy_value(); change(value)
            with self.assertRaises(ContractError):
                MonitoringCapturePolicy(value)

    def test_wrong_question_identity_and_unsafe_material_pointer_refuse(self):
        for change in [lambda p: p["questions"]["objective"].update(version="not-this-question"),
                       lambda p: p.update(material_paths=["/provenance/producer"]),
                       lambda p: p.update(material_paths=["/body/~bad"]),
                       lambda p: p.update(native_baseline={"material_contract": p["questions"]["objective"], "paths": {"wrong": "/value"}})]:
            value = policy_value(); change(value)
            with self.assertRaises(ContractError):
                MonitoringCapturePolicy(value)

    def test_capture_identity_uses_material_and_context_not_cadence(self):
        request = json.loads((ROOT / "tests/fixtures/civic/handoff/client-a-request.json").read_text())
        args = dict(host_binding=request["host_binding"], intent_id=request["intent"]["id"],
            candidate=request["evidence"]["sources"][0]["reference"], components=request["context_components"],
            material_digest="1" * 64, material_contract=request["evaluation"]["policy"])
        first = conveyed_capture_identity(**args)
        changed = deepcopy(args)
        changed["components"]["preference"]["digest"] = "2" * 64
        self.assertEqual(conveyed_capture_identity(**changed), first)
        changed["material_digest"] = "3" * 64
        self.assertNotEqual(conveyed_capture_identity(**changed), first)
        changed = deepcopy(args); changed["host_binding"]["client_id"] = "other-client"
        self.assertNotEqual(conveyed_capture_identity(**changed), first)

    def test_versions_are_explicit_and_frozen_schema_inventory_is_untouched(self):
        request = json.loads((ROOT / "tests/fixtures/civic/handoff/client-a-request.json").read_text())
        self.assertEqual(validate_handoff(request), request)
        with self.assertRaises(ContractError):
            validate_capture_handoff(request)
        request.update(contract_version=VERSION, proposal_basis={"kind": "native_attention"})
        self.assertEqual(validate_capture_handoff(request), request)
        with self.assertRaises(ContractError):
            validate_handoff(request)
        import hashlib
        lock = json.loads((ROOT / "tests/fixtures/civic/handoff/contract-lock.json").read_text())
        for item in lock["artifacts"]:
            self.assertEqual(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest(), item["sha256"])



class CaptureGuardRegressionTests(unittest.TestCase):
    def test_source_eligibility_checks_protected_roots_not_only_visible_text(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from matter.civic_attention import source_questions
        from matter.statecivics_capture import _source_reading
        request = json.loads((ROOT / "tests/fixtures/civic/handoff/client-a-request.json").read_text())
        source = request["evidence"]["sources"][0]["reference"]
        private = {**source, "id": "private-protected-dependency"}
        state = {"scope_id": source["scope_id"], "evidence": ["synthetic public text"]}
        value = {"phase": "completed", "request": {"batch": {"state": state},
            "rendered": [{"manifest": {"specification": s.reference}} for s in source_questions()]}}
        access = Mock()
        def gate(view, context, *, references):
            self.assertEqual(references, [source, private])
            raise ContractError("E_AUTHORITY_REQUIRED")
        access.require_current.side_effect = gate
        admitted = SimpleNamespace(source_packet=SimpleNamespace(state=state),
            host=SimpleNamespace(access=access, access_context=object()))
        receipts = Mock(); receipts._audit.return_value = [source, private]
        with patch("matter.statecivics_capture._execution", return_value=({}, value)), self.assertRaises(ContractError):
            _source_reading(object(), admitted, receipts, source)
        access.require_packet.assert_called_once()
        access.require_current.assert_called_once()

    def test_study_baseline_refuses_different_stable_purpose_or_audience(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, MagicMock
        from matter.statecivics_capture import AdmittedCaptureMonitoring, ObservedMonitoringCapture
        request = json.loads((ROOT / "tests/fixtures/civic/handoff/client-a-request.json").read_text())
        reference = request["evidence"]["sources"][0]["reference"]
        owner = {**{k: request["host_binding"][k] for k in ("user_id", "workspace_id", "client_id")}, "intent_id": request["intent"]["id"]}
        request["baseline"] = {"status": "observed_capture", "decision_basis": "unqualified_model_capture",
            "receipt": reference, "capture_admission_reference": reference}
        now = {"state": "known", "value": "2050-01-01T00:00:00Z", "precision": "second"}
        for kind in ("purpose", "audience"):
            with self.subTest(kind=kind):
                prior = deepcopy(request["context_components"])
                prior[kind]["id"] = "other-" + kind
                old = {"control": reference, "original_execution": reference,
                    "host_binding": request["host_binding"], "intent_id": request["intent"]["id"], "candidate": reference,
                    "projection": {"context_components": prior, "treatment": "digest", "dependencies": []}}
                view = Mock(); view.get.return_value = {"provenance": {"recorded_at": now}}
                storage = Mock(); storage.snapshot.return_value = MagicMock()
                storage.snapshot.return_value.__enter__.return_value = view
                service = Mock(storage=storage)
                service._record.return_value = ({}, old)
                service.capture_history.return_value = ObservedMonitoringCapture(receipt=reference,
                    admission_reference=reference, owner=owner, candidate=reference, material={},
                    material_contract={}, captured_at=now)
                admitted = object.__new__(AdmittedCaptureMonitoring)
                admitted._request = request; admitted.output_context = object()
                admitted.host = SimpleNamespace(capture_service=service, binding=request["host_binding"],
                    access=Mock(), access_context=object(), clock=lambda: now,
                    current_state=lambda _: SimpleNamespace(candidate=reference))
                with self.assertRaises(ContractError) as refused:
                    admitted._conveyed_material()
                self.assertEqual(refused.exception.code, "E_SCOPE_FORBIDDEN")


class CaptureMaterialRoutingTests(unittest.TestCase):
    """Routing after guarded inputs; these tests do not establish provenance."""
    def test_old_handled_feedback_does_not_silence_new_deadline_or_linked_correction(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from matter.statecivics_capture import AdmittedCaptureMonitoring
        from matter.dispositions import DispositionDefinition
        from matter.storage import entity_ref
        request = json.loads((ROOT / "tests/fixtures/civic/handoff/client-a-request.json").read_text())
        source = request["evidence"]["sources"][0]["reference"]
        new = {**source, "record_type": "claim", "id": "new-deadline"}
        old = {**new, "id": "old-deadline"}
        projection = {**entity_ref(source), "record_type": "matter:projection", "id": "context", "revision": 1}
        matter = {**entity_ref(source), "record_type": "matter", "id": "subject"}
        now = request["context_selection"]["effective_at"]
        definition = DispositionDefinition({"schema_version": "1.0", "namespace": "synthetic.feedback", "kind": "acknowledgement",
            "matter": matter, "purpose": {"reference": request["context_components"]["purpose"], "context": projection},
            "audience": {"reference": request["context_components"]["audience"], "context": projection},
            "subject": old, "effective_from": now, "effective_until": {"state": "unknown", "reason": "not_applicable"},
            "reason": "Handled this exact prior deadline", "decision": None, "status": "active"})
        disposition = {**projection, "id": "handled-old-deadline"}
        request.update(contract_version=VERSION, proposal_basis={"kind": "unqualified_model_capture", "source_reading": None},
            baseline={"status": "observed_capture", "receipt": source}, dispositions=[disposition])
        value = policy_value(); value["material_paths"] = ["/body/value/value/confidence"]
        policy = MonitoringCapturePolicy(value)
        path = policy.value["material_paths"][0]
        admitted = object.__new__(AdmittedCaptureMonitoring)
        admitted._request = request; admitted.digest = "1" * 64; admitted.require_policy_pin = projection
        admitted._baseline_links = [old]
        admitted.host = SimpleNamespace(binding=request["host_binding"])
        admitted.source_packet = SimpleNamespace(value={"dependencies": [source]})
        current = SimpleNamespace(source_finding=new, contexts={}, candidate={**matter, "revision": 1})
        packet = SimpleNamespace(state={"monitoring": {"observed_baseline": {path: "2050-02-01"}}})
        view = Mock()
        finding = {"body": {"value": {"value": {"confidence": "2050-02-08"}}}}
        view.get.side_effect = lambda ref: finding if ref == new else {"value": {"value": {"definition": definition.value}}}
        positive = {"objective": "positive", "novelty": "positive"}
        result = admitted._proposal(view, policy, positive, packet, current, source, source)["projection"]
        self.assertEqual(result["treatment"], "digest")
        self.assertNotIn("disposition_applies", result["reasons"])
        request["evidence"]["correction_of"] = [old]
        correction = admitted._proposal(view, policy, {"objective": "unknown", "novelty": "unknown"}, packet, current, source, source)["projection"]
        self.assertEqual(correction["treatment"], "correction")
        self.assertIn("semantic_unknown", correction["reasons"])
        self.assertEqual(result["capture_key"], correction["capture_key"])
        request["evidence"]["correction_of"] = []
        finding["body"]["value"]["value"]["confidence"] = "2050-02-01"
        quiet = admitted._proposal(view, policy, positive, packet, current, source, source)["projection"]
        self.assertEqual(quiet["treatment"], "quiet")
        self.assertIn("already_captured", quiet["reasons"])
        finding["body"]["value"]["value"]["confidence"] = "2050-02-08"
        request["evidence"]["coverage"] = "partial"
        partial = admitted._proposal(view, policy, positive, packet, current, source, source)["projection"]
        self.assertEqual(partial["treatment"], "quiet")
        self.assertIn("incomplete_coverage", partial["reasons"])


class CaptureOriginalExecutionTests(unittest.TestCase):
    def test_source_and_audience_cache_aliases_keep_original_currentness(self):
        from unittest.mock import patch
        from matter.statecivics_capture import _original_execution
        from integration.helpers import fixture
        from matter.storage import pin
        record = fixture("records/receipt.json"); record["id"] = "synthetic-cache-alias"
        original = fixture("records/receipt.json"); original["id"] = "synthetic-original"
        state = {"phase": "reused", "source_execution": pin(original),
            "execution_key": "1" * 64, "normalized_digest": "2" * 64, "result": {"synthetic": "same whole result"}}
        prior = {**state, "phase": "completed"}
        with patch("matter.statecivics_capture._execution", side_effect=ContractError("E_CANCELLED")) as read:
            with self.assertRaises(ContractError) as refused:
                _original_execution(object(), object(), record, state)
            self.assertEqual(refused.exception.code, "E_CANCELLED")
            self.assertEqual(read.call_args.args[-1], pin(original))
        with patch("matter.statecivics_capture._execution", return_value=(original, prior)):
            self.assertEqual(_original_execution(object(), object(), record, state), (original, prior))
        with patch("matter.statecivics_capture._execution", return_value=(original, {**prior, "normalized_digest": "3" * 64})):
            with self.assertRaises(ContractError):
                _original_execution(object(), object(), record, state)


class CaptureProjectionIsolationTests(unittest.TestCase):
    def test_returned_projection_cannot_mutate_private_handoff_snapshot(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from matter.statecivics_capture import AdmittedCaptureMonitoring
        result = json.loads((ROOT / "tests/fixtures/civic/handoff-v1.1/audience-a-positive.json").read_text())["result"]
        reference = result["decision_basis"]["capture_admission_reference"]
        actual = SimpleNamespace(value={"value": {"projection": deepcopy(result)}}, reference=reference)
        admitted = object.__new__(AdmittedCaptureMonitoring)
        admitted._request = {"proposal_basis": {"kind": "unqualified_model_capture"}}
        admitted.require_current = Mock()
        admitted.host = SimpleNamespace(capture_service=Mock())
        admitted.host.capture_service.current.return_value = actual
        proposal = admitted.project_capture(admission=reference)
        before = deepcopy(proposal)
        proposal["reasons"].append("host:display-annotation")
        self.assertEqual(admitted._projection[0], before)
