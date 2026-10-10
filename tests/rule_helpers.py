"""Synthetic MAT-012 rule, binding, packet, and certificate helpers."""
from copy import deepcopy

from matter.canonical import canonical_digest
from matter.rules import RuleDefinition, RuleRegistry, SchemaDefinition, SchemaRegistry
from matter.evaluators import BindingRegistry, DeterministicBinding, RecordedBinding, QualificationRegistry
from matter.evaluators.packets import prepare_input, preparation_reference
from matter.evaluators.runner import RuleEvaluator
from matter.storage import pin

from claim_helpers import ClaimTestCase, SCOPE


NOW = {"state": "known", "value": "2026-10-10T12:00:00Z", "precision": "second"}
EARLY = {"state": "known", "value": "2026-10-09T12:00:00Z", "precision": "second"}
LATE = {"state": "known", "value": "2026-10-11T12:00:00Z", "precision": "second"}


def component(identity):
    return {"namespace": "example", "id": identity, "version": "1.0",
            "digest": canonical_digest({"id": identity}, "synthetic.component.v1")}


def schema(identity, properties, required=None):
    return SchemaDefinition("example", identity, "1.0", {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:example:" + identity,
        "type": "object", "additionalProperties": False, "properties": properties,
        "required": list(properties) if required is None else required,
    })


class RuleTestCase(ClaimTestCase):
    def setUp(self):
        super().setUp()
        self.input_schema = schema("question", {"enabled": {"type": "boolean"}})
        self.output_schema = schema("answer", {"label": {"type": "string"},
                                                "score": {"type": "string"}}, ["label"])
        self.proposal_schema = schema("review-proposal", {"reason": {"type": "string"}})
        self.schemas = SchemaRegistry([self.input_schema, self.output_schema, self.proposal_schema])
        self.calls = []

    def response(self, *, label="example:positive", status="applicable", qualification=None, uses=None, proposals=None):
        return {"execution_status": "completed", "evaluation_status": status,
                "semantic_output": {"schema": self.output_schema.reference, "value": {"label": label}},
                "qualification": qualification or {"status": "unknown"},
                "used_evidence": uses or [], "proposed_consequences": proposals or [],
                "limitations": []}

    def function(self, request):
        self.calls.append(deepcopy(request))
        uses = [{"reference": item["reference"], "locator": item["locator"]}
                for item in request["input"]["packet"]["evidence"]]
        return self.response(uses=uses)

    def binding(self, function=None, *, identity="comparison"):
        return DeterministicBinding("example", identity, "1.0",
            implementation=component("implementation-" + identity),
            semantics="Return a declared synthetic comparison without host mutation.",
            conformance_cases=[{"name": "fixed-input", "invariant": "The declared label is preserved."}],
            function=function or self.function)

    def recorded(self, recordings=(), *, identity="external"):
        return RecordedBinding("example", identity, "1.0", evaluator=component("external-model"),
                               semantics="Frozen synthetic external answer.", recordings=recordings)

    def definition(self, binding, *, identity="evidence-rule"):
        output = self.output_schema.reference
        labels = [("positive", "applicable"), ("negative", "applicable"),
                  ("unknown", "insufficient_evidence"), ("inapplicable", "not_applicable"),
                  ("ambiguous", "ambiguous"), ("conflicting", "conflicting")]
        return {
            "schema_version": "1.0", "namespace": "example", "rule_id": identity,
            "semantic_version": "1.0", "family": "evidence",
            "description": "Synthetic evidence rule with explicit unresolved outcomes.",
            "input_schema": self.input_schema.reference, "output_schema": output,
            "proposition_template": "Evaluate the declared proposition over admitted evidence.",
            "evidence_preparation": preparation_reference(),
            "evidence_requirements": {"allowed_kinds": ["observation"], "allowed_origins": ["source", "adapter", "host"],
                "minimum": 1, "required_roles": ["example:basis"], "require_complete_coverage": True,
                "locator_adapters": [self.adapter.reference], "incomplete_label": "example:unknown"},
            "preconditions": [], "dependencies": [],
            "outcomes": [{"label": "example:" + label, "description": label, "evaluation_status": status,
                         "implications": [],
                         "fallback_output": {"schema": output, "value": {"label": "example:" + label}}}
                        for label, status in labels],
            "evaluator_binding": binding.reference,
            "qualification_requirement": ({"kind": "deterministic", "reason": "No learned comparison."}
                if binding.mode == "deterministic" else {"kind": "certificate", "reason": "Requires admitted synthetic evaluation.",
                    "task_scope": component("task-scope"), "threshold_policy": component("threshold")}),
            "conflict_policy": component("retain-conflicts"), "consequence_permissions": [],
            "resource_limits": {"max_input_bytes": 262144, "max_output_bytes": 65536,
                "max_evidence": 16, "max_elapsed_ms": 1000, "max_calls": 1, "max_retries": 0},
            "temporal_dependencies": [],
            "conformance_cases": [{"name": "unknown", "invariant": "A missing prerequisite never means false."}],
        }

    def rule(self, binding, *, change=None, identity="evidence-rule"):
        definition = self.definition(binding, identity=identity)
        if change:
            change(definition)
        return RuleDefinition(definition, schemas=self.schemas)

    def evidence(self, source=None):
        source = source or self.source
        locator = deepcopy(source["body"]["content"]["locator"])
        validation = self.adapter.validate(source, locator, checked_at=NOW)
        return {"reference": pin(source), "locator": locator, "quotation": None,
                "roles": ["example:basis"], "validation": validation}

    def packet(self, rule, *, evidence=None, view=None, **kwargs):
        context = [] if rule.value["qualification_requirement"]["kind"] == "deterministic" else [component("task-scope")]
        params = {"scope_id": SCOPE,
            "proposition": {"schema": self.input_schema.reference, "value": {"enabled": True}},
            "evidence": [self.evidence()] if evidence is None else evidence,
            "coverage": {"status": "complete", "snapshot": component("coverage")},
            "as_of": NOW, "context": context}
        params.update(kwargs)
        if view is not None:
            return prepare_input(view, rule, schemas=self.schemas, **params)
        with self.storage.snapshot() as snapshot:
            return prepare_input(snapshot, rule, schemas=self.schemas, **params)

    def runner(self, rules, bindings, *, qualifications=None, monotonic=None, clock=None):
        return RuleEvaluator(rules=RuleRegistry(rules), bindings=BindingRegistry(bindings),
            schemas=self.schemas, qualifications=qualifications,
            clock=clock or (lambda: deepcopy(NOW)), monotonic=monotonic or (lambda: 0))

    def evaluate(self, binding=None, rule=None, packet=None, **kwargs):
        binding = binding or self.binding()
        rule = rule or self.rule(binding)
        packet = packet or self.packet(rule)
        result = self.runner([rule], [binding]).evaluate(packet, judgment_id="judgment", attempt_id="attempt", **kwargs)
        return result, rule, binding, packet

    def certificate(self, rule, binding, *, change=None):
        definition = rule.value
        value = {"rule": rule.reference, "binding": binding.reference,
            "input_schema": definition["input_schema"], "output_schema": definition["output_schema"],
            "preparation": definition["evidence_preparation"],
            "task_scope": component("task-scope"), "threshold_policy": component("threshold"),
            "valid_from": EARLY, "valid_until": LATE, "evaluation_evidence": [pin(self.source)]}
        if change:
            change(value)
        return {**value, "reference": {"namespace": "example", "id": "external-certificate", "version": "1.0",
            "digest": canonical_digest(value, "matter.qualification-certificate.v1")}}

    def assert_code(self, code, function, *args, **kwargs):
        from matter.contracts import ContractError
        with self.assertRaises(ContractError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def recorded_result(self, *, certificate=None, qualifier="qualified", qualifications=None, clock=None):
        initial = self.recorded()
        rule = self.rule(initial)
        packet = self.packet(rule)
        reported = {"status": qualifier}
        if certificate:
            reported["certificate"] = certificate["reference"]
        response = self.response(qualification=reported)
        binding = self.recorded([{"input_digest": packet.digest, "response": response}])
        runner = self.runner([rule], [binding], qualifications=qualifications, clock=clock)
        return runner.evaluate(packet, judgment_id="recorded-judgment", attempt_id="recorded-attempt"), rule, binding, packet

