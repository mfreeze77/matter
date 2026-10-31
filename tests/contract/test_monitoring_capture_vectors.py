"""Portable wire vectors only: no rehydrated grants/receipts or live calls."""
import hashlib
import json
from pathlib import Path
import unittest

from matter.contracts import ContractError
from matter.statecivics_capture import validate_capture_handoff, VERSION
from matter.statecivics_monitoring import validate_handoff

ROOT = Path(__file__).resolve().parents[2]


class MonitoringCaptureVectorTests(unittest.TestCase):
    def test_published_schema_matches_checkout_and_installed_resource(self):
        from importlib.resources import files
        published = (ROOT / "docs/contracts/monitoring-handoff-v1.1.schema.json").read_bytes()
        self.assertEqual(published, (ROOT / "schemas/monitoring-handoff-v1.1.schema.json").read_bytes())
        self.assertEqual(published, files("matter._schemas").joinpath("monitoring-handoff-v1.1.schema.json").read_bytes())

    def test_recorded_candidate_vectors_and_explicit_version_refusal(self):
        directory = ROOT / "tests/fixtures/civic/handoff-v1.1"
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "candidate_consumer_run_required")
        vectors = {}
        for item in manifest["vectors"]:
            with self.subTest(vector=item["name"]):
                raw = (directory / item["file"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])
                vector = json.loads(raw)
                self.assertEqual(vector["evidence_kind"], "synthetic_recorded_runtime")
                self.assertEqual(vector["provider_calls_live"], 0)
                request = validate_capture_handoff(vector["request"])
                result = validate_capture_handoff(vector["result"], "result")
                self.assertEqual(request["contract_version"], VERSION)
                self.assertEqual(result["contract_version"], VERSION)
                self.assertEqual(result["treatment"], vector["expected"]["treatment"])
                self.assertEqual(result["decision_basis"]["judgments"], vector["expected"]["judgments"])
                self.assertEqual(result["source_finding_reference"], vector["source_finding"])
                self.assertEqual(result["qualification"], "unqualified")
                self.assertFalse(result["consequential_use"])
                self.assertIsNone(result["assessment_reference"])
                self.assertEqual(result["permitted_use"], "capture_only")
                for value, kind in ((request, "request"), (result, "result")):
                    with self.assertRaises(ContractError):
                        validate_handoff(value, kind)
                vectors[item["name"]] = vector
        paired = [vectors[name] for name in ("audience-a-positive", "audience-b-quiet", "audience-b-unknown")]
        self.assertEqual(len({json.dumps(v["source_finding"], sort_keys=True) for v in paired}), 1)
        self.assertEqual([v["result"]["treatment"] for v in paired], ["digest", "quiet", "quiet"])
        self.assertEqual(paired[2]["result"]["decision_basis"]["judgments"]["objective"], "unknown")
        self.assertNotIn("no_relevance", paired[2]["result"]["reasons"])
        self.assertEqual(vectors["mixed-native-study-baseline"]["request"]["baseline"]["decision_basis"], "native_attention")
