"""MAT-029 behavioral stages over actual budgets, packets and typed execution."""

from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from threading import Event
import unittest

from matter.budgets import BudgetDefinition, BudgetService, REQUEST_EXTENSION, budget_ref
from matter.canonical import canonical_bytes
from matter.contracts import ContractError
from matter.semantic import Capabilities, RawExecution
from matter.semantic.packets import PacketProfile, prepare_packet
from matter.semantic.questions import QuestionRegistry, QuestionSpecification
from matter.semantic.rendering import render_question
from matter.semantic.stages import StageError, StageExecutor, StageInput, StagePlan
from matter.storage import entity_ref, pin

from control_helpers import control_command
from integration import test_assessment_commit as core_fixture
from integration.helpers import _in_scope, fixture
from rule_helpers import EARLY, LATE, component


class StageTests(unittest.TestCase):
    def setUp(self):
        self.f = core_fixture.AssessmentCommitTests(methodName="runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.candidate = self.f.observe("candidate-a", payload=b"SYNTHETIC fetched candidate details.\n")
        self.specs = {name: self.spec(name) for name in ("support", "contradiction", "selection", "recovery")}
        self.questions = QuestionRegistry(list(self.specs.values()))
        self.calls, self.choice, self.invalid = [], self.candidate["id"], False
        outer = self
        class Spy:
            capabilities = Capabilities({"provider": "synthetic", "transport": "fixture", "adapter_version": "1.0",
                "primitives": ["choice", "proposition_probability"], "modes": ["offline_fixture", "recorded_replay"],
                "max_questions": 128, "max_request_bytes": 65536, "max_response_bytes": 65536})
            def execute(inner, batch):
                outer.calls.append(batch.value)
                answers = []
                for question in batch.value["questions"]:
                    value = {"id": question["id"], "primitive": question["primitive"]}
                    if question["primitive"] == "choice":
                        value.update(choice=outer.choice, probabilities={outer.candidate["id"]: "0.9", "insufficient": "0.1"}, confidence="0.5")
                    else:
                        value["probability"] = "0.1234567890123456789"
                    answers.append(value)
                if outer.invalid:
                    answers = answers[:-1]
                return RawExecution(json.dumps({"answers": answers, "resolved_model": "synthetic-fixed"}).encode())
        self.spy = Spy()
        self.targets = [entity_ref(item) for item in (self.f.subject, self.f.source, self.candidate)]
        self.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="assessment", targets=self.targets)
        self.sequence = 0

    def spec(self, name):
        choice = name == "selection"
        return QuestionSpecification({"schema_version": "1.0", "namespace": "synthetic", "id": name,
            "family": "synthetic." + name, "revision": "1.0", "primitive": "choice" if choice else "proposition_probability",
            "instructions": ("Which admitted candidate does {{sources}} select?" if choice else "Does {{sources}} establish the declared " + name + " proposition?"),
            "criteria": ([{"id": self.candidate["id"], "description": "The explicitly admitted candidate A."},
                          {"id": "insufficient", "description": "No candidate can be selected from the provided evidence."}]
                         if choice else {"true": "The proposition is supported.", "false": "The proposition is not supported."}),
            "required_fields": [{"name": "sources", "path": ["evidence"], "description": "Exact selected source bytes."}],
            "renderer": {"id": "canonical-json-bindings", "version": "1.0"}})

    def reserve(self, *, calls=4, candidates=4, expires=LATE, commit=True):
        self.sequence += 1
        limits = {"calls": calls, "input_bytes": 4 * 65536, "output_bytes": 4 * 65536,
                  "elapsed_ms": 10000, "candidates": candidates, "retries": 0, "cost_units": 0}
        self.definition = BudgetDefinition({"schema_version": "1.0", "namespace": "synthetic", "id": "stages-" + str(self.sequence),
            "semantic_version": "1.0", "kind": "resource", "window": {"start": EARLY, "end": LATE, "bounds": "closed_open"},
            "limits": limits, "units": {key: "synthetic:" + key for key in limits}, "description": "Synthetic committed stage allocation."})
        self.budgets = BudgetService(self.f.storage, definitions=[self.definition], controls=self.f.controls, clock=lambda: self.f.now)
        command = _in_scope(fixture("commands/reserve_budget.json"), self.f.storage.scope_id)
        command.update(command_id="stage-reserve-" + str(self.sequence), idempotency_key="stage-reserve-" + str(self.sequence),
            actor=self.f.actor, authority=entity_ref(self.f.authority), expected_revisions=[], body={"budget": self.definition.reference,
                "reservation_id": "stages-" + str(self.sequence), "amounts": limits, "expires_at": expires, "targets": self.targets})
        prepared = self.budgets.prepare(command, token=self.token)
        result = self.budgets.execute(prepared)
        self.assertEqual(result["outcome"], "reserved", result)
        reference = result["body"]["reservation"]
        if commit:
            command = _in_scope(fixture("commands/settle_budget.json"), self.f.storage.scope_id)
            command.update(command_id="stage-commit-" + str(self.sequence), idempotency_key="stage-commit-" + str(self.sequence),
                actor=self.f.actor, authority=entity_ref(self.f.authority), expected_revisions=[], body={"reservation": reference, "action": "commit"})
            result = self.budgets.execute(self.budgets.prepare(command, token=self.token))
            self.assertEqual(result["outcome"], "committed", result)
            reference = result["body"]["reservation"]
        self.reservation = reference
        self.ceiling = {"max_calls": 4, "max_input_bytes": 4 * 65536, "max_output_bytes": 4 * 65536,
                        "max_elapsed_ms": 10000, "max_evidence": 16}
        self.runner = StageExecutor(questions=self.questions, budgets=self.budgets, executor=self.spy, clock=lambda: self.f.now)

    def packet(self, *, candidate=False, wrong_binding=False, access=None, access_context=None):
        record = self.candidate if candidate else self.f.source
        profile = PacketProfile({"namespace": "synthetic", "id": "stage-packet", "version": "1.0", "required_roles": [],
            "allowed_origins": ["source"], "locator_adapters": [self.f.adapter.reference], "max_sources": 16,
            "max_source_bytes": 65536, "max_packet_bytes": 65536})
        with self.f.storage.snapshot() as view:
            return prepare_packet(view, profile, payloads=self.f.payloads, scope_id=self.f.storage.scope_id,
                binding={"kind": "candidate_relation", "left": pin(self.f.source), "right": pin(self.f.source if wrong_binding else record),
                         "relation": "synthetic:about"}, as_of=self.f.now, evidence=[self.f.evidence(record)],
                coverage={"status": "complete", "snapshot": component("coverage")}, access=access, access_context=access_context)

    def stage(self, name, questions, *, requires=(), packet_key=None, max_candidates=0):
        return {"id": name, "packet_key": packet_key or name, "transform": component("transform-" + name),
            "questions": [{"id": identity, "specification": self.specs[identity].reference, "use_if": None} for identity in questions],
            "requires": list(requires), "max_candidates": max_candidates}

    def edge(self, stage="select", question="selection"):
        return {"stage": stage, "question": question, "accepted": {"choices": [self.candidate["id"]]},
                "require_qualified": True, "bindings": [{"answer_pointer": "/choice", "packet_pointer": "/binding/right/id"}]}

    def plan(self, stages):
        return StagePlan({"namespace": "synthetic", "id": "stage-plan", "version": "1.0", "stages": stages}, questions=self.questions)

    def material(self, stage, parents, *, packet=None, candidate_count=0, wrong_parents=False, access=None, access_context=None):
        packet = packet or self.packet()
        with self.f.storage.snapshot() as view:
            rendered = [render_question(self.questions.resolve(item["specification"]), packet.state, item["id"], source_manifest=packet.source_manifest,
                **({"access": access, "access_context": access_context, "access_view": view} if access is not None else {}))
                for item in stage["questions"]]
        context = {"provider": "synthetic", "transport": "fixture", "requested_model": "synthetic-fixed", "adapter_version": "1.0",
                   "mode": "offline_fixture", "deadline": LATE, "max_request_bytes": 65536, "max_response_bytes": 65536}
        return StageInput(packet=packet, rendered_questions=rendered, context=context, transform=stage["transform"],
            parents=[] if wrong_parents else [item["receipt"] for item in parents], candidate_count=candidate_count)

    def execute(self, plan, prepare, **options):
        return self.runner.execute(plan, prepare=prepare, reservation=self.reservation, ceiling=self.ceiling,
            run_id="stage-test", **options)

    def qualified(self, **_):
        return {"status": "qualified", "certificate": component("synthetic-admitted-certificate")}

    def dependent(self):
        return self.plan([self.stage("select", ["selection"]), self.stage("details", ["recovery"], requires=[self.edge()], max_candidates=1)])

    def test_same_fixed_packet_support_and_contradiction_use_one_request(self):
        self.reserve()
        plan = self.plan([self.stage("support", ["support"], packet_key="fixed"), self.stage("contradiction", ["contradiction"], packet_key="fixed")])
        packet = self.packet()
        run = self.execute(plan, lambda stage, parents, **_: self.material(stage, parents, packet=packet))
        self.assertEqual(run.value["status"], "completed", run.value)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([item["id"] for item in self.calls[0]["questions"]], ["contradiction", "support"])
        self.assertEqual(run.value["resources"]["actual_invocations"], 1)

    def test_selection_and_real_fetch_future_precede_dependent_dispatch_with_exact_parent(self):
        self.reserve()
        future, fetching, seen = Future(), Event(), []
        def prepare(stage, parents, **_):
            if stage["id"] == "select":
                return self.material(stage, parents)
            seen.append((stage, parents))
            self.assertEqual(parents[0]["answer"]["choice"], self.candidate["id"])
            fetching.set()
            return future
        with ThreadPoolExecutor(max_workers=1) as pool:
            work = pool.submit(self.execute, self.dependent(), prepare, qualify=self.qualified)
            self.assertTrue(fetching.wait(timeout=5))
            self.assertEqual(len(self.calls), 1)
            stage, parents = seen[0]
            future.set_result(self.material(stage, parents, packet=self.packet(candidate=True), candidate_count=1))
            run = work.result(timeout=10)
        self.assertEqual(run.value["status"], "completed", run.value)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(run.value["stages"]["details"]["parents"], [run.value["stages"]["select"]["reference"]])
        self.assertEqual(self.calls[1]["state"]["binding"]["right"], pin(self.candidate))
        self.assertEqual(run.value["resources"]["reserved_candidates"], 1)
        self.assertTrue(all(item["qualification"]["certificate"] == component("synthetic-admitted-certificate")
            for item in run.value["gate_decisions"]["details"]))

    def test_invalid_plans_fail_distinctly_before_any_dispatch(self):
        cases = json.loads((Path(__file__).parents[1] / "fixtures/semantic/stage_plans.json").read_text())["invalid"]
        for case in cases:
            raw = self.dependent().value
            raw.pop("order")
            if case["mutation"] == "missing_parent":
                raw["stages"][1]["requires"][0]["stage"] = "absent"
            elif case["mutation"] == "sibling":
                raw["stages"][1]["requires"][0].update(stage="details", question="recovery", accepted={"minimum": "0", "maximum": "1"})
            else:
                raw["stages"][0]["requires"] = [{"stage": "details", "question": "recovery", "accepted": {"minimum": "0", "maximum": "1"},
                                                 "require_qualified": True, "bindings": []}]
            with self.assertRaises(StageError) as error:
                StagePlan(raw, questions=self.questions)
            self.assertEqual(error.exception.reason, case["reason"])
        self.assertEqual(self.calls, [])

    def test_unqualified_and_uncertain_selection_stop_without_default_or_fetch(self):
        for qualified, choice in ((False, self.candidate["id"]), (True, "insufficient")):
            self.reserve()
            self.choice = choice
            prepared = []
            def build(stage, parents, **_):
                prepared.append(stage["id"])
                return self.material(stage, parents)
            run = self.execute(self.dependent(), build, qualify=self.qualified if qualified else None)
            self.assertEqual(run.value["stages"]["details"]["status"], "blocked")
            self.assertEqual(prepared, ["select"])
        self.assertEqual(len(self.calls), 2)

    def test_cancellation_before_second_stage_prevents_fetch_and_dispatch(self):
        self.reserve()
        stop = Event()
        def prepare(stage, parents, **_):
            self.assertEqual(stage["id"], "select")
            return self.material(stage, parents)
        original = self.spy.execute
        def execute(batch):
            result = original(batch)
            stop.set()
            return result
        self.spy.execute = execute
        run = self.execute(self.dependent(), prepare, qualify=self.qualified, cancelled=stop.is_set)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(run.value["batches"]), 1)
        self.assertEqual(run.value["stages"]["details"]["status"], "cancelled")

    def test_speculative_same_packet_answer_can_be_ignored_without_second_request(self):
        self.reserve()
        stage = self.stage("fanout", ["support", "contradiction"])
        # JSON false is distinct from the actual integer zero, not a numeric
        # alias that could make a speculative result eligible accidentally.
        stage["questions"][1]["use_if"] = {"pointer": "/coverage/mandatory_omissions", "equals": False}
        run = self.execute(self.plan([stage]), lambda value, parents, **_: self.material(value, parents))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.calls[0]["questions"]), 2)
        self.assertEqual(run.value["stages"]["fanout"]["ignored_questions"], ["contradiction"])

    def test_held_or_expired_allocations_never_dispatch(self):
        self.reserve(commit=False)
        with self.assertRaises(ContractError) as error:
            self.execute(self.plan([self.stage("one", ["support"])]), lambda *args, **kw: self.fail("no preparation"))
        self.assertEqual(error.exception.code, "E_BUDGET_EXHAUSTED")
        self.assertEqual(self.calls, [])

    def test_one_decreasing_call_and_candidate_allocation_is_not_reset_per_batch(self):
        self.reserve(calls=1)
        plan = self.plan([self.stage("one", ["support"]), self.stage("two", ["recovery"])])
        run = self.execute(plan, lambda stage, parents, **_: self.material(stage, parents, packet=self.packet(candidate=stage["id"] == "two")))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(run.value["resources"]["remaining_budget"]["max_calls"], 0)
        self.assertEqual(run.value["stages"]["two"]["error_code"], "E_BUDGET_EXHAUSTED")
        account = self.f.storage.get(budget_ref(self.f.storage.scope_id, self.definition))["value"]["value"]
        self.assertEqual(account["charged"]["calls"], 1)
        self.assertIsNone(run.value["resources"]["cost"]["value"])

    def test_parent_trace_and_consumed_choice_must_match_host_transform(self):
        for wrong_parents in (True, False):
            self.reserve()
            def prepare(stage, parents, **_):
                return self.material(stage, parents, packet=self.packet(candidate=True, wrong_binding=True) if parents else self.packet(),
                    candidate_count=1 if parents else 0, wrong_parents=wrong_parents and bool(parents))
            run = self.execute(self.dependent(), prepare, qualify=self.qualified)
            self.assertEqual(run.value["stages"]["details"]["status"], "blocked")
        self.assertEqual(len(self.calls), 2)

    def test_failed_whole_batch_retains_partial_diagnostics_and_blocks_children(self):
        self.reserve()
        self.invalid = True
        plan = self.plan([self.stage("select", ["selection", "support"]), self.stage("details", ["recovery"], requires=[self.edge()], max_candidates=1)])
        run = self.execute(plan, lambda stage, parents, **_: self.material(stage, parents), qualify=self.qualified)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(run.value["stages"]["select"]["status"], "invalid")
        self.assertEqual(run.value["stages"]["details"]["status"], "blocked")
        self.assertTrue(any(item["status"] == "valid" for item in run.value["batches"][0]["result"]["diagnostics"]))

    def test_expired_qualification_after_fetch_prevents_dependent_dispatch(self):
        self.reserve()
        expired = Event()
        def prepare(stage, parents, **_):
            if parents:
                expired.set()
            return self.material(stage, parents, packet=self.packet(candidate=bool(parents)), candidate_count=int(bool(parents)))
        def qualify(**kwargs):
            return {"status": "expired", "certificate": None} if expired.is_set() else self.qualified()
        run = self.execute(self.dependent(), prepare, qualify=qualify)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(run.value["stages"]["details"]["error_code"], "E_DEPENDENCY_STALE")

    def test_candidate_quota_and_expired_work_stop_before_host_preparation(self):
        self.reserve(candidates=0)
        run = self.execute(self.plan([self.stage("fetch", ["support"], max_candidates=1)]),
            lambda *args, **kwargs: self.fail("candidate fetch must not start"))
        self.assertEqual(run.value["stages"]["fetch"]["error_code"], "E_BUDGET_EXHAUSTED")
        self.f.now = deepcopy(LATE)
        with self.assertRaises(ContractError) as error:
            self.execute(self.plan([self.stage("expired", ["support"])]), lambda *args, **kwargs: self.fail("expired work"))
        self.assertEqual(error.exception.code, "E_BUDGET_EXHAUSTED")
        self.assertEqual(self.calls, [])

    def test_opaque_dispatch_failure_never_claims_zero_actual_calls_or_refunds(self):
        self.reserve()
        def failed(batch, **kwargs):
            raise RuntimeError("SYNTHETIC-PRIVATE-ADAPTER-ERROR")
        self.runner.dispatch = failed
        run = self.execute(self.plan([self.stage("one", ["support"])]), lambda stage, parents, **_: self.material(stage, parents))
        self.assertIsNone(run.value["resources"]["actual_invocations"])
        self.assertEqual(run.value["resources"]["unobserved_dispatches"], 1)
        self.assertEqual(run.value["resources"]["reserved_calls"], 1)
        self.assertNotIn("PRIVATE-ADAPTER", canonical_bytes(run.value).decode())

    def test_actual_control_stop_before_run_does_not_wait_for_stage_work(self):
        self.reserve()
        command = _in_scope(control_command("stage-stop", self.f.authority, targets=[self.f.subject], action="cancel", now=self.f.now), self.f.storage.scope_id)
        command["actor"] = self.f.actor
        command["body"]["control"]["body"]["actor"] = self.f.actor
        self.assertEqual(self.f.controls.apply(self.f.controls.prepare(command))["status"], "success")
        with self.assertRaises(ContractError) as error:
            self.execute(self.plan([self.stage("one", ["support"])]), lambda *args, **kwargs: self.fail("stopped preparation"))
        self.assertEqual(error.exception.code, "E_CANCELLED")
        self.assertEqual(self.calls, [])

    def test_protected_packet_uses_actual_access_dispatch_and_default_refuses(self):
        from matter.access import AccessService, HostAccessPolicy
        provider = component("synthetic-provider")
        policy = HostAccessPolicy(scope_id=self.f.storage.scope_id, audiences=[self.f.audience],
            providers=[{"reference": provider, "provider": "synthetic", "transport": "fixture"}],
            grants=[{"reference": pin(item), "audiences": [self.f.audience], "providers": [provider]}
                    for item in (self.f.subject, self.f.source, self.candidate)])
        access = AccessService(policy=policy, controls=self.f.controls, current_read=self.f.storage.snapshot)
        with self.f.storage.snapshot() as view:
            context = access.capture(view, token=self.token, audience=self.f.audience, provider=provider,
                references=[pin(self.f.subject), pin(self.f.source), pin(self.candidate)])
        self.f.service.access = access
        request = self.f.request()
        prepared_view = self.f.service.prepare(request, token=self.token, plan=self.f.plan, access_context=context).view
        packet = self.packet(access=access, access_context=context)
        prepare = lambda stage, parents, **_: self.material(stage, parents, packet=packet, access=access, access_context=context)
        self.reserve()
        plan = self.plan([self.stage("one", ["support"])])
        refused = self.execute(plan, prepare)
        self.assertEqual(refused.value["stages"]["one"]["error_code"], "E_AUTHORITY_REQUIRED")
        self.assertEqual(self.calls, [])
        # A new explicit work assignment; do not reset an old allocation's
        # local remainder to retry a previously attempted run.
        self.reserve()
        self.runner.dispatch = lambda batch, **kwargs: access.dispatch(prepared_view, context, batch, self.spy, **kwargs)
        run = self.execute(plan, prepare)
        self.assertEqual(run.value["status"], "completed", run.value)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(run.value["inputs"]["one"]["rendered_questions"][0]["manifest"]["access_context"], context.reference)


if __name__ == "__main__":
    unittest.main()
