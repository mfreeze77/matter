"""Offline installed-package check for MAT-013, MAT-026 and MAT-036.

Run with the synthetic episode JSONL path as the only argument. This small
check demonstrates the interfaces, not provider quality or live usefulness.
The profile here contains settings only; rule-bearing profiles and refusal
cases are covered by the MAT-013 behavioral suite.
"""

from copy import deepcopy
from pathlib import Path
import sys

from matter.canonical import canonical_digest, loads
from matter.evaluation import load_jsonl
from matter.profiles import ProfileDefinition, ProfileRegistry, compare_profiles
from matter.rules import RuleRegistry, SchemaRegistry
from matter.semantic import Batch, Capabilities, FixtureExecutor, execute_batch


def time(value):
    return {"state": "known", "value": value, "precision": "second"}


def profiles():
    budget = {"max_calls": 0, "max_input_bytes": 0, "max_output_bytes": 0,
              "max_evidence": 0, "max_elapsed_ms": 0}

    def component(parameters):
        return {"semantic_version": "1.0", "description": "Synthetic settings only.",
                "rules": [], "parameters": parameters, "dependencies": [],
                "outputs": [], "data_scopes": [], "capabilities": [],
                "conflict_resolvers": [], "resource_limits": budget,
                "lifecycle_extensions": [],
                "conformance_cases": [{"name": "settings", "invariant": "No rule executes."}]}

    value = {"schema_version": "1.0", "namespace": "example", "profile_id": "settings",
             "semantic_version": "1.0", "description": "Independent evidence and audience settings.",
             "components": {"evidence": component({}), "audience": component({"cadence": "daily"})},
             "required_outputs": [], "resource_limits": budget,
             "incomplete_evaluation": "retain_unresolved"}
    first = ProfileDefinition(value, rules=RuleRegistry(), schemas=SchemaRegistry())
    changed = deepcopy(value)
    changed["semantic_version"] = "2.0"
    changed["components"]["audience"]["parameters"]["cadence"] = "weekly"
    second = ProfileDefinition(changed, rules=RuleRegistry(), schemas=SchemaRegistry())
    assert first.component_references["evidence"] == second.component_references["evidence"]
    assert compare_profiles(first, second)["qualification_transfer"] is False
    history, notice = ProfileRegistry([first]).supersede(first.reference, second)
    assert history.resolve(first.reference).value == first.value
    assert notice["cause"] == "policy_change"


def execution():
    state = {"synthetic": True}
    packet = canonical_digest(state, "matter.semantic.packet.v1")
    batch = Batch({"schema_version": "1.0", "id": "example-batch", "scope_id": "example:offline",
        "run_id": "example-run", "stage_id": "example-stage", "state": state, "packet_digest": packet,
        "questions": [{"id": "claim", "family": "evidence", "revision": "1.0",
            "primitive": "proposition_probability", "instructions": "Is the supplied synthetic proposition true?",
            "criteria": {"true": "The declared proposition holds.", "false": "The declared proposition does not hold."},
            "specification_digest": packet, "rendering_revision": "1.0", "packet_digest": packet,
            "bound_ids": ["example-proposition"]}],
        "context": {"provider": "fixture", "transport": "memory", "requested_model": "synthetic-v1",
            "adapter_version": "1.0", "mode": "offline_fixture", "deadline": time("2026-01-02T00:00:00Z"),
            "max_request_bytes": 65536, "max_response_bytes": 65536}})
    capabilities = Capabilities({"provider": "fixture", "transport": "memory", "adapter_version": "1.0",
        "primitives": ["proposition_probability"], "modes": ["offline_fixture"], "max_questions": 1,
        "max_request_bytes": 65536, "max_response_bytes": 65536})
    raw = (b'{"resolved_model":"synthetic-v1","answers":[{"id":"claim",'
           b'"primitive":"proposition_probability","probability":0.1234567890123456789}]}')
    result = execute_batch(FixtureExecutor(capabilities, {batch.digest: raw}), batch,
                           clock=lambda: time("2026-01-01T00:00:00Z"))
    value = loads(result.canonical)
    assert result.primitive_valid
    assert value["diagnostics"][0]["answer"]["probability"] == "0.1234567890123456789"
    assert value["admission"]["consequential_use"] is False
    assert value["admission"]["qualification_status"] == "unknown"


def corpus(path):
    frozen = load_jsonl(Path(path).read_bytes())
    report = frozen.denominators()
    assert report["total"] == 9
    assert report["counts"]["eligible"] == 3
    assert report["counts"]["unlabeled"] == 1
    assert report["counts"]["teacher_only"] == 1
    prefix = frozen.prefix(as_of=time("2026-01-01T00:00:03Z"))
    assert prefix["included"]
    assert "labels" not in prefix
    assert load_jsonl(Path(path).read_bytes(), expected_sha256=frozen.sha256).sha256 == frozen.sha256


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: ready_foundations.py SYNTHETIC_EPISODES_JSONL")
    profiles()
    execution()
    corpus(sys.argv[1])
    print("Policy history, exact offline typed answer and frozen synthetic corpus passed; no provider or action.")
