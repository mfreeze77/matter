"""MAT-014 staged behavior using an explicit synthetic host staging read view."""
from copy import deepcopy
from threading import Barrier, Event
import time
import unittest

from matter.canonical import canonical_bytes, canonical_digest
from matter.conflicts import ConflictResolver, ConflictResolverRegistry
from matter.contracts import ContractError, validate_record
from matter.evaluators import BindingRegistry, DeterministicBinding, QualificationRegistry, RuleEvaluator, prepare_input
from matter.evaluators.packets import check_input_current
from matter.executor import GraphExecutor, GraphRun
from matter.planner import RulePlan, PlanError
from matter.profiles import ProfileDefinition
from matter.rules import RuleRegistry, SchemaDefinition, SchemaRegistry
from matter.storage import entity_ref, pin
from unit import test_profile_validation as fixtures

NOW = {"state": "known", "value": "2026-10-27T12:00:00Z", "precision": "second"}


class RuleDagTests(unittest.TestCase):
    def setUp(self):
        self.helper = fixtures.ProfileTests()
        self.helper.setUp()
        self.helper.input = SchemaDefinition("example", "staged-input", "1.0", {
            "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:graph:input",
            "type": "object", "additionalProperties": False,
            "properties": {"question": {"type": "string"}, "candidate_revision": {"type": "integer"}}, "required": ["question"]})
        self.helper.output = SchemaDefinition("example", "staged-output", "1.0", {
            "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:graph:output",
            "type": "object", "additionalProperties": False,
            "properties": {"label": {"type": "string"}, "candidate_revision": {"type": "integer"}}, "required": ["label"]})
        self.helper.schemas = SchemaRegistry([self.helper.input, self.helper.output, self.helper.proposal])
        self.resolver = ConflictResolver("example", "retained-conflicts", "1.0")
        self.helper.resolver = self.resolver.reference
        self.rules, self.bindings, self.calls, self.staged, self.prepared_calls = {}, [], [], {}, []
        self.clock = lambda: deepcopy(NOW)

    def response(self, revision=7, *, label="example:yes", status="applicable", qualification=None):
        return {"execution_status": "completed", "evaluation_status": status,
                "semantic_output": {"schema": self.helper.output.reference, "value": {"label": label, "candidate_revision": revision}},
                "qualification": qualification or {"status": "unknown"}, "used_evidence": [],
                "proposed_consequences": [], "limitations": []}

    def rule(self, name, *, function=None, dependencies=(), change=None):
        def invoke(request):
            self.calls.append(name)
            return function(request) if function is not None else self.response()
        binding = DeterministicBinding("example", "binding-" + name, "1.0", implementation=fixtures.ref("impl-" + name),
            semantics="Synthetic exact staged comparison.", conformance_cases=[{"name": "fixed", "invariant": "Preserve selected revision."}], function=invoke)
        self.helper.binding = binding
        def update(value):
            value["qualification_requirement"] = {"kind": "deterministic", "reason": "Exact synthetic operation."}
            value["resource_limits"].update(max_input_bytes=262144, max_output_bytes=16384)
            value["dependencies"] = [{"rule": dependency.reference, "accepted_labels": ["example:yes"],
                "accepted_statuses": ["applicable"], "require_qualified": True} for dependency in dependencies]
            if change:
                change(value)
        rule = self.helper.make_rule(identity=name, change=update)
        self.rules[name] = rule
        self.bindings.append(binding)
        return rule

    def profile(self):
        component = self.helper.component(list(self.rules.values()))
        component["outputs"] = [{"name": "example:" + name, "rule": rule.reference,
            "schema": self.helper.output.reference, "accepted_labels": ["example:yes"], "accepted_statuses": ["applicable"]} for name, rule in self.rules.items()]
        n = len(self.rules)
        component["resource_limits"] = {"max_calls": n, "max_input_bytes": 262144*n,
            "max_output_bytes": 16384*n, "max_evidence": 16, "max_elapsed_ms": max(1000*n, 1)}
        value = self.helper.definition()
        value.update(components={"evidence": component}, required_outputs=["example:" + name for name in self.rules],
            resource_limits=component["resource_limits"])
        return ProfileDefinition(value, rules=RuleRegistry(self.rules.values()), schemas=self.helper.schemas,
            allowed_data_scopes=["synthetic"], conflict_resolvers=[self.resolver.reference])

    def plan(self, *, conditions=(), compositions=(), mappings=None):
        if mappings is None:
            mappings = [{"from": next(name for name, source in self.rules.items() if source.reference == dependency["rule"]),
                         "to": name, "source_pointer": "/candidate_revision", "target_pointer": "/candidate_revision"}
                        for name, rule in self.rules.items() for dependency in rule.value["dependencies"]]
        return RulePlan(self.profile(), rules=RuleRegistry(self.rules.values()), schemas=self.helper.schemas,
            nodes={name: rule.reference for name, rule in self.rules.items()}, input_bindings=mappings,
            conditions=conditions, compositions=compositions)

    def get(self, reference):
        key = canonical_bytes(entity_ref(reference))
        if key not in self.staged:
            raise ContractError("E_EVIDENCE_UNAVAILABLE")
        return deepcopy(self.staged[key])

    def current(self, prepared, *, as_of):
        return check_input_current(self, prepared, as_of=as_of)

    def prepare(self, name, predecessors):
        self.prepared_calls.append(name)
        upstream = []
        proposition = {"question": name}
        for predecessor in predecessors.values():
            # Explicit synthetic host staging, not production persistence or
            # fabricated authority in GraphExecutor. Public prepare_input reads
            # a fully schema-validated stored-shape fixture through this view.
            record = deepcopy(predecessor["judgment"])
            record["creation_receipt"] = {"scope_id": record["scope_id"], "namespace": "example.host",
                "record_type": "receipt", "id": "stage:" + record["id"]}
            record = validate_record(record)
            self.staged[canonical_bytes(entity_ref(record))] = record
            proposition["candidate_revision"] = record["body"]["semantic_output"]["value"]["candidate_revision"]
            if any(item["rule"] == record["body"]["rule"] for item in self.rules[name].value["dependencies"]):
                upstream.append({"reference": pin(record), "expected_input": predecessor["input"], "available_at": NOW})
        return prepare_input(self, self.rules[name], schemas=self.helper.schemas, scope_id="synthetic",
            proposition={"schema": self.helper.input.reference, "value": proposition},
            coverage={"status": "complete", "snapshot": fixtures.ref("coverage")}, as_of=NOW,
            context=[fixtures.ref("task")], upstream=upstream)

    def execute(self, plan=None, *, prepare=None, qualifications=None, **kwargs):
        evaluator = RuleEvaluator(rules=RuleRegistry(self.rules.values()), bindings=BindingRegistry(self.bindings),
            schemas=self.helper.schemas, qualifications=qualifications, clock=self.clock)
        return GraphExecutor(evaluator, conflicts=ConflictResolverRegistry([self.resolver]), clock=self.clock).execute(
            plan or self.plan(), prepare=prepare or self.prepare, run_id="synthetic-stage", check_current=self.current, **kwargs).value

    def test_recovery_receives_validated_selected_candidate_revision(self):
        selection = self.rule("selection", function=lambda request: self.response(17))
        def recover(request):
            packet = request["input"]["packet"]
            self.assertEqual(packet["proposition"]["value"]["candidate_revision"], 17)
            self.assertEqual(packet["upstream"][0]["judgment"]["body"]["semantic_output"]["value"]["candidate_revision"], 17)
            return self.response(17)
        self.rule("recovery", function=recover, dependencies=[selection])
        result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.calls, ["selection", "recovery"])
        self.assertEqual(result["nodes"]["recovery"]["upstream_input_digests"]["selection"], result["nodes"]["selection"]["input_digest"])

    def test_dependent_builder_cannot_change_selected_revision(self):
        selection = self.rule("selection", function=lambda request: self.response(17))
        self.rule("recovery", dependencies=[selection])
        def wrong(name, predecessors):
            prepared = self.prepare(name, predecessors)
            if name == "recovery":
                upstream = [{"reference": pin(self.get(entity_ref(item["judgment"]))),
                    "expected_input": item["expected_input"], "available_at": NOW} for item in prepared.value["packet"]["upstream"]]
                return prepare_input(self, self.rules[name], schemas=self.helper.schemas, scope_id="synthetic",
                    proposition={"schema": self.helper.input.reference, "value": {"question": name, "candidate_revision": 18}},
                    coverage={"status": "complete", "snapshot": fixtures.ref("coverage")}, as_of=NOW,
                    context=[fixtures.ref("task")], upstream=upstream)
            return prepared
        result = self.execute(prepare=wrong)
        self.assertEqual(result["nodes"]["recovery"]["status"], "failed")
        self.assertEqual(result["nodes"]["recovery"]["error_code"], "E_EVIDENCE_INVALID")
        self.assertEqual(self.calls, ["selection"])

    def test_conditional_cycle_fails_before_dispatch(self):
        self.rule("left")
        self.rule("right")
        edge = {"accepted_labels": ["example:yes"], "accepted_statuses": ["applicable"], "require_qualified": True}
        with self.assertRaises(ContractError):
            self.plan(conditions=[{**edge, "from": "left", "to": "right"}, {**edge, "from": "right", "to": "left"}])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.prepared_calls, [])

    def test_independent_calls_are_genuinely_concurrent(self):
        barrier = Barrier(2)
        def together(request):
            barrier.wait(timeout=2)
            return self.response()
        self.rule("left", function=together)
        self.rule("right", function=together)
        result = self.execute(max_workers=2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["resource_reservations"]["actual_invocations"], 2)

    def test_completion_order_does_not_change_explicit_composition(self):
        outputs = []
        for slow in ("left", "right"):
            self.setUp()
            self.resolver = ConflictResolver("example", "ordered", "1.0", mode="precedence", precedence=["left", "right"])
            self.helper.resolver = self.resolver.reference
            def result(name, revision):
                def invoke(request):
                    if name == slow:
                        time.sleep(0.02)
                    return self.response(revision)
                return invoke
            self.rule("left", function=result("left", 1))
            self.rule("right", function=result("right", 2))
            composition = {"id": "comparison", "resolver": self.resolver.reference, "nodes": ["left", "right"], "mandatory_gates": []}
            output = self.execute(self.plan(compositions=[composition]), max_workers=2)["compositions"][0]
            outputs.append(output)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0]["selected_node"], "left")
        self.assertEqual(len(outputs[0]["originals"]), 2)

    def test_incomplete_precedence_is_refused_before_preparation_or_evaluation(self):
        self.resolver = ConflictResolver("example", "incomplete-order", "1.0", mode="precedence", precedence=["left"])
        self.helper.resolver = self.resolver.reference
        self.rule("left")
        self.rule("right")
        composition = {"id": "comparison", "resolver": self.resolver.reference,
            "nodes": ["left", "right"], "mandatory_gates": []}
        with self.assertRaises(ContractError) as error:
            self.execute(self.plan(compositions=[composition]))
        self.assertEqual(error.exception.code, "E_POLICY_INVALID")
        self.assertEqual(self.prepared_calls, [])
        self.assertEqual(self.calls, [])

    def test_conflicting_qualified_outputs_remain_inspectable_when_quiet(self):
        self.rule("left", function=lambda request: self.response(1))
        self.rule("right", function=lambda request: self.response(2))
        composition = {"id": "comparison", "resolver": self.resolver.reference, "nodes": ["left", "right"], "mandatory_gates": []}
        result = self.execute(self.plan(compositions=[composition]))
        composed = result["compositions"][0]
        self.assertEqual(composed["status"], "conflicting")
        self.assertEqual(composed["treatment"], "quiet")
        self.assertEqual([item["judgment"]["body"]["semantic_output"]["value"]["candidate_revision"] for item in composed["originals"]], [1, 2])
        self.assertIsNone(composed["semantic_output"])

    def test_unqualified_predecessor_blocks_before_dependent_input_preparation(self):
        source = self.rule("source", change=lambda value: value.update(qualification_requirement={
            "kind": "certificate", "reason": "Requires separate qualification.", "task_scope": fixtures.ref("task"), "threshold_policy": fixtures.ref("threshold")}))
        self.rule("dependent", dependencies=[source])
        result = self.execute()
        self.assertEqual(result["nodes"]["dependent"]["status"], "blocked")
        self.assertIn("qualification", result["nodes"]["dependent"]["reason"])
        self.assertEqual(self.prepared_calls, ["source"])
        self.assertIsNone(result["nodes"]["dependent"]["judgment"])

    def test_ambiguous_and_timedout_predecessors_do_not_imply_false(self):
        for fault in ("ambiguous", "timeout"):
            self.setUp()
            def invoke(request):
                if fault == "timeout":
                    raise TimeoutError()
                return self.response(label="example:ambiguous", status="ambiguous")
            def change(value):
                value["outcomes"].append({"label": "example:ambiguous", "description": "Conflicting candidate possibilities.",
                    "evaluation_status": "ambiguous", "implications": []})
            source = self.rule("source", function=invoke, change=change)
            self.rule("dependent", dependencies=[source])
            result = self.execute()
            self.assertEqual(result["nodes"]["dependent"]["status"], "blocked")
            self.assertIsNone(result["nodes"]["dependent"]["judgment"])
            self.assertEqual(self.calls, ["source"])

    def test_concurrent_nodes_share_remaining_call_budget_deterministically(self):
        self.rule("left")
        self.rule("right")
        plan = self.plan()
        budget = {**plan.value["resource_limits"], "max_calls": 1}
        result = self.execute(plan, remaining_budget=budget, max_workers=2)
        self.assertEqual(result["resource_reservations"]["reserved_attempts"], 1)
        self.assertEqual(result["resource_reservations"]["actual_invocations"], 1)
        self.assertEqual(self.calls, ["left"])
        self.assertEqual(result["nodes"]["right"]["status"], "budget_exhausted")

    def test_reported_remaining_budget_subtracts_conservative_reservations(self):
        self.rule("source")
        plan = self.plan()
        budget = plan.value["resource_limits"]
        self.assertEqual(budget["max_calls"], 1)
        result = self.execute(plan)
        resources = result["resource_reservations"]
        self.assertEqual(resources["admitted_budget"], budget)
        remaining = resources["remaining_budget"]
        self.assertEqual(remaining["max_calls"], 0)
        self.assertEqual(remaining["max_input_bytes"], budget["max_input_bytes"] - resources["reserved_input_bytes"])
        self.assertEqual(remaining["max_output_bytes"], budget["max_output_bytes"] - resources["reserved_output_bytes"])
        self.assertEqual(remaining["max_elapsed_ms"], max(0, budget["max_elapsed_ms"] - resources["elapsed_ms"]))
        self.assertEqual(remaining["max_evidence"], budget["max_evidence"])
        self.calls.clear()
        chained = self.execute(plan, remaining_budget=remaining)
        self.assertEqual(chained["nodes"]["source"]["status"], "budget_exhausted")
        self.assertEqual(self.calls, [])

    def test_failed_source_coverage_cannot_be_outweighed_by_high_impact(self):
        self.rule("coverage", change=lambda value: value["evidence_requirements"].update(require_complete_coverage=True))
        self.rule("impact", function=lambda request: self.response(999999))
        composition = {"id": "attention", "resolver": self.resolver.reference, "nodes": ["impact"], "mandatory_gates": [{
            "node": "coverage", "accepted_labels": ["example:yes"], "accepted_statuses": ["applicable"], "require_qualified": True}]}
        def prepare(name, predecessors):
            if name == "coverage":
                return prepare_input(self, self.rules[name], schemas=self.helper.schemas, scope_id="synthetic",
                    proposition={"schema": self.helper.input.reference, "value": {"question": name}},
                    coverage={"status": "partial", "snapshot": fixtures.ref("failed-source"), "reason": "Collection failed."}, as_of=NOW)
            return self.prepare(name, predecessors)
        result = self.execute(self.plan(compositions=[composition]), prepare=prepare)
        self.assertEqual(result["nodes"]["coverage"]["status"], "unresolved")
        self.assertEqual(result["nodes"]["impact"]["status"], "completed")
        self.assertEqual(result["compositions"][0]["status"], "withheld")
        self.assertEqual(result["resource_reservations"]["actual_invocations"], 1)

    def test_known_false_condition_skips_while_unknown_condition_blocks(self):
        self.rule("source")
        self.rule("conditional")
        edge = {"from": "source", "to": "conditional", "accepted_labels": ["example:unknown"],
            "accepted_statuses": ["insufficient_evidence"], "require_qualified": True}
        result = self.execute(self.plan(conditions=[edge]))
        self.assertEqual(result["nodes"]["conditional"]["status"], "skipped")
        self.assertEqual(self.prepared_calls, ["source"])
        self.setUp()
        self.rule("source", function=lambda request: self.response(label="example:unknown", status="insufficient_evidence"))
        self.rule("conditional")
        edge.update(accepted_labels=["example:yes"], accepted_statuses=["applicable"])
        result = self.execute(self.plan(conditions=[edge]))
        self.assertEqual(result["nodes"]["conditional"]["status"], "blocked")
        self.assertEqual(self.prepared_calls, ["source"])

    def test_cancelled_run_never_prepares_or_invokes_nodes(self):
        self.rule("source")
        result = self.execute(cancelled=lambda: True)
        self.assertEqual(result["nodes"]["source"]["status"], "cancelled")
        self.assertEqual(self.prepared_calls, [])
        self.assertEqual(self.calls, [])

    def test_byte_and_time_budgets_prevent_dispatch(self):
        self.rule("source")
        plan = self.plan()
        for field in ("max_input_bytes", "max_output_bytes", "max_elapsed_ms"):
            budget = {**plan.value["resource_limits"], field: 0}
            result = self.execute(plan, remaining_budget=budget)
            self.assertEqual(result["nodes"]["source"]["status"], "budget_exhausted")
        self.assertEqual(self.calls, [])

    def test_unavailable_host_staging_is_a_typed_blocked_path(self):
        source = self.rule("source")
        self.rule("dependent", dependencies=[source])
        def prepare(name, predecessors):
            if name == "dependent":
                raise ContractError("E_EVIDENCE_UNAVAILABLE")
            return self.prepare(name, predecessors)
        result = self.execute(prepare=prepare)
        self.assertEqual(result["nodes"]["dependent"]["status"], "blocked")
        self.assertEqual(result["nodes"]["dependent"]["error_code"], "E_EVIDENCE_UNAVAILABLE")
        self.assertEqual(self.calls, ["source"])

    def test_same_rule_alternative_judgment_cannot_replace_the_selected_result(self):
        source = self.rule("source")
        self.rule("dependent", dependencies=[source])
        def swap(name, predecessors):
            if name == "dependent":
                predecessors["source"]["judgment"]["id"] = "different-same-rule-result"
            return self.prepare(name, predecessors)
        result = self.execute(prepare=swap)
        self.assertEqual(result["nodes"]["dependent"]["status"], "failed")
        self.assertEqual(result["nodes"]["dependent"]["error_code"], "E_EVIDENCE_INVALID")
        self.assertEqual(self.calls, ["source"])

    def test_expired_exact_certificate_blocks_descendant_without_building_input(self):
        reported = {}
        def change(value):
            value["qualification_requirement"] = {"kind": "certificate", "reason": "Separate qualification.",
                "task_scope": fixtures.ref("task"), "threshold_policy": fixtures.ref("threshold")}
        source = self.rule("source", function=lambda request: self.response(qualification=reported), change=change)
        self.rule("dependent", dependencies=[source])
        meaning = source.value
        material = {"rule": source.reference, "binding": meaning["evaluator_binding"],
            "input_schema": meaning["input_schema"], "output_schema": meaning["output_schema"],
            "preparation": meaning["evidence_preparation"], "task_scope": fixtures.ref("task"),
            "threshold_policy": fixtures.ref("threshold"),
            "valid_from": {"state": "known", "value": "2026-10-01T00:00:00Z", "precision": "second"},
            "valid_until": {"state": "known", "value": "2026-10-26T00:00:00Z", "precision": "second"},
            "evaluation_evidence": [{"scope_id": "synthetic", "namespace": "example", "record_type": "observation", "id": "reviewed", "digest": "a" * 64}]}
        reference = {**fixtures.ref("certificate"), "digest": canonical_digest(material, "matter.qualification-certificate.v1")}
        reported.update(status="qualified", certificate=reference)
        result = self.execute(qualifications=QualificationRegistry([{**material, "reference": reference}]))
        self.assertEqual(result["nodes"]["source"]["judgment"]["body"]["qualification"]["status"], "expired")
        self.assertEqual(result["nodes"]["dependent"]["status"], "blocked")
        self.assertEqual(result["nodes"]["dependent"]["reason"], "qualification_expired")
        self.assertEqual(self.prepared_calls, ["source"])

    def expiring_qualification(self, source):
        meaning = source.value
        material = {"rule": source.reference, "binding": meaning["evaluator_binding"],
            "input_schema": meaning["input_schema"], "output_schema": meaning["output_schema"],
            "preparation": meaning["evidence_preparation"], "task_scope": fixtures.ref("task"),
            "threshold_policy": fixtures.ref("threshold"),
            "valid_from": {"state": "known", "value": "2026-10-01T00:00:00Z", "precision": "second"},
            "valid_until": {"state": "known", "value": "2026-10-27T12:00:01Z", "precision": "second"},
            "evaluation_evidence": [{"scope_id": "synthetic", "namespace": "example", "record_type": "observation", "id": "reviewed", "digest": "a" * 64}]}
        reference = {**fixtures.ref("certificate"), "digest": canonical_digest(material, "matter.qualification-certificate.v1")}
        return QualificationRegistry([{**material, "reference": reference}]), {"status": "qualified", "certificate": reference}

    def test_certificate_expiry_after_child_execution_blocks_required_and_conditional_paths(self):
        for conditional in (False, True):
            self.setUp()
            finished = Event()
            self.clock = lambda: ({**NOW, "value": "2026-10-27T12:00:02Z"} if finished.is_set() else deepcopy(NOW))
            reported = {}
            def requirement(value):
                value["qualification_requirement"] = {"kind": "certificate", "reason": "Separate qualification.",
                    "task_scope": fixtures.ref("task"), "threshold_policy": fixtures.ref("threshold")}
            source = self.rule("source", function=lambda request: self.response(qualification=reported), change=requirement)
            self.rule("dependent", dependencies=[] if conditional else [source],
                function=lambda request: (finished.set(), self.response())[1])
            qualifications, claim = self.expiring_qualification(source)
            reported.update(claim)
            conditions = ([{"from": "source", "to": "dependent", "accepted_labels": ["example:yes"],
                "accepted_statuses": ["applicable"], "require_qualified": True}] if conditional else [])
            result = self.execute(self.plan(conditions=conditions), qualifications=qualifications)
            self.assertEqual(self.calls, ["source", "dependent"])
            self.assertEqual(result["nodes"]["source"]["judgment"]["body"]["qualification"]["status"], "qualified")
            dependent = result["nodes"]["dependent"]
            self.assertEqual(dependent["judgment"]["body"]["execution_status"], "completed")
            self.assertEqual(dependent["status"], "blocked")
            self.assertEqual(dependent["reason"], "final_qualification_expired")
            self.assertEqual(dependent["final_edge_admissions"][0]["reason"], "qualification_expired")
            self.assertEqual(result["status"], "incomplete")
            self.assertNotEqual(result["stop_reason"], "completed")

    def test_initially_false_condition_does_not_hide_final_qualification_expiry(self):
        finished = Event()
        self.clock = lambda: ({**NOW, "value": "2026-10-27T12:00:02Z"} if finished.is_set() else deepcopy(NOW))
        reported = {}
        def requirement(value):
            value["qualification_requirement"] = {"kind": "certificate", "reason": "Separate qualification.",
                "task_scope": fixtures.ref("task"), "threshold_policy": fixtures.ref("threshold")}
        source = self.rule("source", function=lambda request: self.response(qualification=reported), change=requirement)
        self.rule("a-skipped")
        self.rule("z-late", function=lambda request: (finished.set(), self.response())[1])
        qualifications, claim = self.expiring_qualification(source)
        reported.update(claim)
        conditions = [{"from": "source", "to": "a-skipped", "accepted_labels": ["example:unknown"],
                       "accepted_statuses": ["insufficient_evidence"], "require_qualified": True},
                      {"from": "source", "to": "z-late", "accepted_labels": ["example:yes"],
                       "accepted_statuses": ["applicable"], "require_qualified": True}]
        result = self.execute(self.plan(conditions=conditions), qualifications=qualifications)
        self.assertEqual(self.calls, ["source", "z-late"])
        self.assertNotIn("a-skipped", self.prepared_calls)
        self.assertEqual(result["nodes"]["a-skipped"]["status"], "blocked")
        self.assertEqual(result["nodes"]["a-skipped"]["reason"], "final_qualification_expired")
        self.assertIsNone(result["nodes"]["a-skipped"]["judgment"])

    def test_cancellation_during_attempt_is_latched_and_blocks_later_work(self):
        cancelled = Event()
        source = self.rule("source", function=lambda request: (cancelled.set(), self.response())[1])
        self.rule("dependent", dependencies=[source])
        result = self.execute(cancelled=cancelled.is_set)
        self.assertEqual(result["stop_reason"], "cancelled")
        self.assertEqual(result["nodes"]["source"]["status"], "cancelled")
        self.assertEqual(result["nodes"]["dependent"]["status"], "cancelled")
        self.assertIsNotNone(result["nodes"]["source"]["judgment"])
        self.assertEqual(self.prepared_calls, ["source"])
        self.assertEqual(self.calls, ["source"])

    def test_shared_elapsed_deadline_retains_late_attempt_as_unusable_diagnostic(self):
        self.rule("source", function=lambda request: (time.sleep(0.02), self.response())[1])
        plan = self.plan()
        result = self.execute(plan, remaining_budget={**plan.value["resource_limits"], "max_elapsed_ms": 5})
        self.assertEqual(result["stop_reason"], "elapsed_limit")
        self.assertEqual(result["nodes"]["source"]["status"], "timed_out")
        self.assertEqual(result["nodes"]["source"]["judgment"]["body"]["execution_status"], "completed")
        self.assertEqual(result["status"], "incomplete")

    def test_final_stale_predecessor_withholds_already_executed_descendant(self):
        finished = Event()
        source = self.rule("source")
        self.rule("dependent", dependencies=[source], function=lambda request: (finished.set(), self.response())[1])
        evaluator = RuleEvaluator(rules=RuleRegistry(self.rules.values()), bindings=BindingRegistry(self.bindings),
            schemas=self.helper.schemas, clock=self.clock)
        def current(prepared, *, as_of):
            material = prepared.value if hasattr(prepared, "value") else prepared
            if finished.is_set() and material["packet"]["rule"] == source.reference:
                raise ContractError("E_DEPENDENCY_STALE")
            return self.current(prepared, as_of=as_of)
        result = GraphExecutor(evaluator, clock=self.clock).execute(self.plan(), prepare=self.prepare,
            run_id="stale-stage", check_current=current).value
        self.assertEqual(self.calls, ["source", "dependent"])
        self.assertEqual(result["nodes"]["source"]["status"], "blocked")
        self.assertEqual(result["nodes"]["dependent"]["status"], "blocked")
        self.assertEqual(result["nodes"]["dependent"]["reason"], "final_predecessor_blocked")
        self.assertIsNotNone(result["nodes"]["dependent"]["judgment"])

    def test_malformed_edge_fields_and_missing_consumption_mapping_fail_closed(self):
        source = self.rule("source")
        self.rule("dependent", dependencies=[source])
        with self.assertRaises(ContractError):
            self.plan(mappings=[])
        with self.assertRaises(ContractError):
            self.plan(conditions=[{"from": [], "to": "dependent", "accepted_labels": ["example:yes"],
                "accepted_statuses": ["applicable"], "require_qualified": True}])

    def test_rejected_caller_node_text_is_not_echoed_in_plan_errors(self):
        self.rule("source")
        private_text = "private-operator-content"
        with self.assertRaises(PlanError) as error:
            self.plan(conditions=[{"from": private_text, "to": "source", "accepted_labels": ["example:yes"],
                "accepted_statuses": ["applicable"], "require_qualified": True}])
        self.assertEqual(error.exception.path, "/conditions/0")
        self.assertNotIn(private_text, error.exception.detail)

    def test_exact_input_digest_is_retained_and_no_default_resolver_exists(self):
        self.rule("source")
        result = self.execute()
        run_input = result["inputs"]["source"]
        self.assertEqual(canonical_digest(run_input, "matter.evaluation-input.v1"), result["nodes"]["source"]["input_digest"])
        with self.assertRaises(ContractError):
            ConflictResolverRegistry().resolve(self.resolver.reference)

    def test_graph_result_cannot_be_constructed_from_arbitrary_claimed_results(self):
        with self.assertRaises(ContractError):
            GraphRun({"status": "completed", "nodes": {}})
        self.rule("source")
        evaluator = RuleEvaluator(rules=RuleRegistry(self.rules.values()), bindings=BindingRegistry(self.bindings),
            schemas=self.helper.schemas, clock=self.clock)
        run = GraphExecutor(evaluator, clock=self.clock).execute(self.plan(), prepare=self.prepare,
            run_id="immutable-stage", check_current=self.current)
        reference = run.reference
        run.value["nodes"].clear()
        self.assertEqual(run.reference, reference)
        self.assertEqual(len(run.value["nodes"]), 1)
        with self.assertRaises(AttributeError):
            run._encoded = b"{}"

    def test_independent_inputs_from_different_host_scopes_cannot_be_combined(self):
        self.rule("left")
        self.rule("right")
        def prepare(name, predecessors):
            if name == "right":
                return prepare_input(self, self.rules[name], schemas=self.helper.schemas, scope_id="other-scope",
                    proposition={"schema": self.helper.input.reference, "value": {"question": name}},
                    coverage={"status": "complete", "snapshot": fixtures.ref("coverage")}, as_of=NOW)
            return self.prepare(name, predecessors)
        result = self.execute(prepare=prepare)
        self.assertEqual(result["scope_id"], "synthetic")
        self.assertEqual(result["nodes"]["right"]["status"], "failed")
        self.assertEqual(result["nodes"]["right"]["error_code"], "E_SCOPE_FORBIDDEN")
        self.assertEqual(self.calls, ["left"])


if __name__ == "__main__":
    unittest.main()
