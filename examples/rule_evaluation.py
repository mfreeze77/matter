"""Synthetic installed-package example: exact rule meaning, one pure attempt.

No persistence, provider calls, source inference, certificate issuance, or
actions. The host explicitly supplies the small proposition being compared.
"""

from matter.canonical import canonical_digest
from matter.evaluators import BindingRegistry, DeterministicBinding, RuleEvaluator, prepare_input, preparation_reference
from matter.rules import RuleDefinition, RuleRegistry, SchemaDefinition, SchemaRegistry


NOW = {"state": "known", "value": "2026-10-10T12:00:00Z", "precision": "second"}


def component(identity):
    return {"namespace": "example", "id": identity, "version": "1.0",
            "digest": canonical_digest({"meaning": identity}, "example.component.v1")}


def schema(identity, properties):
    return SchemaDefinition("example", identity, "1.0", {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:example:" + identity,
        "type": "object", "properties": properties, "required": list(properties), "additionalProperties": False})


def main():
    question = schema("integer-comparison", {"left": {"type": "integer"}, "right": {"type": "integer"}})
    answer = schema("comparison-answer", {"label": {"enum": ["example:equal", "example:different", "example:unknown"]}})
    schemas = SchemaRegistry([question, answer])

    def compare(request):
        values = request["input"]["packet"]["proposition"]["value"]
        label = "example:equal" if values["left"] == values["right"] else "example:different"
        return {"execution_status": "completed", "evaluation_status": "applicable",
                "semantic_output": {"schema": answer.reference, "value": {"label": label}},
                "qualification": {"status": "unknown"}, "used_evidence": [],
                "proposed_consequences": [], "limitations": []}

    binding = DeterministicBinding("example", "integer-equality", "1.0",
        implementation=component("integer-equality-function"), semantics="Compare two declared exact integers.",
        conformance_cases=[{"name": "equal", "invariant": "Equal integers yield example:equal."}], function=compare)
    outcomes = [{"label": "example:" + label, "description": label, "evaluation_status": status,
                 "implications": [], "fallback_output": {"schema": answer.reference, "value": {"label": "example:" + label}}}
                for label, status in (("equal", "applicable"), ("different", "applicable"), ("unknown", "insufficient_evidence"))]
    rule = RuleDefinition({
        "schema_version": "1.0", "namespace": "example", "rule_id": "integer-equality", "semantic_version": "1.0",
        "family": "evidence", "description": "Compare an explicitly supplied synthetic integer pair.",
        "input_schema": question.reference, "output_schema": answer.reference,
        "proposition_template": "Are the two supplied integers equal?", "evidence_preparation": preparation_reference(),
        "evidence_requirements": {"allowed_kinds": ["observation"], "allowed_origins": ["host"],
            "minimum": 0, "required_roles": [], "require_complete_coverage": False,
            "locator_adapters": [], "incomplete_label": "example:unknown"},
        "preconditions": [], "dependencies": [], "outcomes": outcomes, "evaluator_binding": binding.reference,
        "qualification_requirement": {"kind": "deterministic", "reason": "Exact integer equality uses no learned judgment."},
        "conflict_policy": component("retain-conflict"), "consequence_permissions": [],
        "resource_limits": {"max_input_bytes": 65536, "max_output_bytes": 4096, "max_evidence": 0,
            "max_elapsed_ms": 1000, "max_calls": 1, "max_retries": 0},
        "temporal_dependencies": [], "conformance_cases": [{"name": "equal", "invariant": "No external action is proposed."}],
    }, schemas=schemas)

    class NoReads:
        def get(self, reference):
            raise AssertionError("This exact arithmetic example declares no source reads.")

    prepared = prepare_input(NoReads(), rule, schemas=schemas, scope_id="example:arithmetic",
        proposition={"schema": question.reference, "value": {"left": 4, "right": 4}},
        coverage={"status": "partial", "snapshot": component("no-corpus-requested"),
                  "reason": "This comparison requires no source corpus."}, as_of=NOW)
    evaluator = RuleEvaluator(rules=RuleRegistry([rule]), bindings=BindingRegistry([binding]), schemas=schemas,
                              clock=lambda: NOW)
    bundle = evaluator.evaluate(prepared, judgment_id="comparison-1", attempt_id="comparison-attempt-1")
    body = bundle.judgment["body"]
    assert body["execution_status"] == "completed"
    assert body["semantic_output"]["value"]["label"] == "example:equal"
    assert body["qualification"]["status"] == "not_required"
    assert body["proposed_consequences"] == []
    assert "creation_receipt" not in bundle.judgment
    print("completed / applicable / example:equal / not_required; uncommitted attempt, no action")


if __name__ == "__main__":
    main()
