"""MAT-084 actual native services with synthetic provider/host projections."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import unittest

from matter.canonical import canonical_digest, canonical_bytes
from matter.access import HostAccessPolicy, _public
from matter.contracts import ContractError
from matter.semantic import Batch, Capabilities, RawExecution, PrecisionProfile
from matter.semantic.packets import PreparedPacket
from matter.semantic.questions import QuestionRegistry
from matter.semantic.rendering import render_question
from matter.civic_attention import source_questions
from matter.statecivics_monitoring import monitoring_questions
from matter.statecivics_capture import (
    VERSION, CaptureAdmissionService, MonitoringCapturePolicy,
    ObservedMonitoringCapture, capture_source_reading_eligibility,
    admit_monitoring,
)
from matter.storage import pin, entity_ref
from rule_helpers import component
from integration.test_monitoring_handoff import MonitoringFixture, HOST_FIELDS


def policy_value(native_baseline=None):
    return {"schema_version": "1.1", "namespace": "synthetic.capture", "id": "illustrative-policy",
        "semantic_version": "1.0", "precision": PrecisionProfile().value, "questions": {s.value["family"].split(".")[-1]: s.reference for s in monitoring_questions()},
        # Explicit example configuration, not SDK defaults or owner approval.
        "regions": {r: {"negative_maximum": "0.2", "positive_minimum": "0.8"} for r in ("objective", "novelty")},
        "material_paths": ["/body/value/value/signal"], "native_baseline": native_baseline}


def record_vector(name, h, admitted, proposal):
    target = os.environ.get("MATTER_CAPTURE_VECTOR_OUTPUT")
    if target:
        path = Path(target); path.mkdir(parents=True, exist_ok=True)
        (path / (name + ".json")).write_text(json.dumps({"evidence_kind": "synthetic_recorded_runtime",
            "provider_calls_live": 0, "capture_policy": h.capture_policy.value,
            "request": admitted.request, "result": proposal,
            "expected": {"treatment": proposal["treatment"], "judgments": proposal["decision_basis"].get("judgments")},
            "source_finding": h.state.source_finding}, indent=2) + "\n")


class CaptureFixture(MonitoringFixture):
    def __init__(self, test, *, native_baseline=False, civic=False):
        self.civic_source = civic
        super().__init__(test)
        self.capture_service = CaptureAdmissionService(self.f.storage, receipts=self.receipts,
            controls=self.f.controls, clock=lambda: deepcopy(self.f.now))
        mapping = {"material_contract": self.a.policy.material_contract,
            "paths": {"/body/value/value/signal": "/" + self.a.policy.value["fields"][0]["name"] + "/value"}} if native_baseline else None
        self.capture_policy = MonitoringCapturePolicy(policy_value(mapping))
        self.policy_pin = self.capture_service.install_policy(self.capture_policy, actor=self.f.actor,
            authority=self.f.authority, command_id="capture-policy", idempotency_key="capture-policy")
        self.refresh(extra=[self.policy_pin])
        grants = self.access.policy.value
        for grant in grants["grants"]:
            if grant["reference"] == self.policy_pin and self.other_audience not in grant["audiences"]:
                grant["audiences"].append(self.other_audience)
        self.access.policy = HostAccessPolicy(**grants)
        self.refresh(extra=[self.policy_pin])
        self.renew_allocation()
        self.req.update(contract_version=VERSION,
            proposal_basis={"kind": "unqualified_model_capture", "capture_policy": self.policy_pin, "source_reading": None})
        self.sync()

    def sync(self):
        if self.req["baseline"]["status"] not in {"no_observed_output", "outcome_unknown"}:
            self.req["baseline"].setdefault("decision_basis", "native_attention")
        self.state = replace(self.state, capture_policy=self.policy_pin,
            projection={k: deepcopy(self.req[k]) for k in (*HOST_FIELDS, "proposal_basis")})
        self.host = replace(self.host, capture_service=self.capture_service)

    def refresh(self, **kwargs):
        super().refresh(**kwargs)
        if hasattr(self, "policy_pin") and "proposal_basis" in self.req:
            self.sync()

    def activate_other(self):
        super().activate_other()
        self.refresh(extra=[self.policy_pin])
        self.renew_allocation()

    def prepare_source_packet(self, access, context, **kwargs):
        packet = super().prepare_source_packet(access, context, **kwargs)
        if self.civic_source:
            value = packet.value
            value["state"]["civic"] = {"acting_body": "Synthetic school board", "stance_actor": "Synthetic district",
                "target_act": "Synthetic technology appropriation", "provision": "Synthetic procurement terms"}
            packet = PreparedPacket(value, _prepared=True)
        return packet

    def admit(self, request=None):
        return admit_monitoring(request or self.req, host=self.host, packet=self.packet)


class MonitoringCaptureTests(unittest.TestCase):
    def setUp(self):
        self.h = CaptureFixture(self)

    def test_actual_receipt_becomes_unqualified_study_proposal_and_guarded_capture(self):
        h = self.h
        admitted = h.admit()
        execution = h.execute(admitted)
        self.assertEqual(execution["status"], "completed")
        self.assertEqual(len(h.calls), 1)
        capture_admission = admitted.admit_capture(execution=execution["execution"])
        proposal = admitted.project_capture(admission=capture_admission)
        self.assertEqual(proposal["treatment"], "digest")
        self.assertIsNone(proposal["assessment_reference"])
        self.assertEqual(proposal["qualification"], "unqualified")
        self.assertFalse(proposal["consequential_use"])
        self.assertEqual(proposal["decision_basis"]["judgments"], {"objective": "positive", "novelty": "positive"})
        self.assertEqual(proposal["decision_basis"]["execution_reference"], execution["execution"])
        before = deepcopy(h.claim)
        captures = []
        def sink(**args):
            args["require_current"]()
            captures.append(args["assessment_key"])
            self.assertEqual(args["channels"], ["in_app"])
            return "captured"
        self.assertEqual(admitted.handoff(proposal, capture=sink), "captured")
        self.assertEqual(captures, [proposal["capture_key"]])
        self.assertEqual(h.f.storage.get(pin(before)), before)
        retry = admitted.admit_capture(execution=execution["execution"])
        self.assertEqual(retry.reference, capture_admission.reference)
        self.assertEqual(len(h.calls), 1)

        record_vector("single-command-positive", h, admitted, proposal)
        for detached in ({"probability": "0.99"}, {**execution["execution"], "digest": "0" * 64}):
            with self.subTest(detached=detached), self.assertRaises(ContractError):
                admitted.admit_capture(execution=detached)
        # A new exact host command can reuse the still-current semantic result
        # without calling it qualified or counting a second physical trial.
        h.req.update(request_id="study-semantic-reuse", idempotency_key="study-semantic-reuse")
        h.sync()
        reused_command = h.admit()
        reused = h.execute(reused_command)
        self.assertEqual(reused["status"], "reused")
        self.assertFalse(reused["dispatched"])
        reused_admission = reused_command.admit_capture(execution=reused["execution"])
        reused_result = reused_command.project_capture(admission=reused_admission)
        self.assertEqual(reused_result["decision_basis"]["original_execution_reference"], execution["execution"])
        self.assertNotEqual(reused_result["decision_basis"]["execution_reference"], execution["execution"])
        self.assertEqual(reused_result["capture_key"], proposal["capture_key"])
        self.assertEqual(reused_result["qualification"], "unqualified")
        self.assertEqual(len(h.calls), 1)
        # Ordinary native attention has a real assessment input, not a study
        # projection pin. Its supported prepare port rejects this substitution.
        with self.assertRaises(ContractError):
            h.a.service.prepare(h.f.request(), policy=h.a.policy, assessment=capture_admission.reference,
                contexts=h.a.context_refs, token=h.token)
        # Exercise the ordinary public delivery port with real owners. Study
        # admission/proposal types must fail before a queue receipt or send.
        from matter.delivery import DeliveryService
        from matter.budgets import BudgetDefinition, BudgetService, _lookup
        from matter.attention import delivered_baseline_ref
        from matter.outbox import DestinationDefinition
        from integration.delivery_helpers import SyntheticTransport
        from integration.helpers import _in_scope, fixture
        start = {"state": "known", "value": "2049-01-01T00:00:00Z", "precision": "second"}
        end = {"state": "known", "value": "2051-01-01T00:00:00Z", "precision": "second"}
        budget = BudgetDefinition({"schema_version": "1.0", "namespace": "synthetic", "id": "refused-study-delivery",
            "semantic_version": "1.0", "kind": "attention", "window": {"start": start, "end": end, "bounds": "closed_open"},
            "limits": {"deliveries": 1}, "units": {"deliveries": "synthetic:deliveries"}, "description": "No study delivery allowed."})
        budgets = BudgetService(h.f.storage, definitions=[budget], controls=h.f.controls, clock=h.host.clock)
        transport = SyntheticTransport()
        destination = DestinationDefinition({"namespace": "synthetic", "id": "ordinary-notification", "version": "1.0",
            "audience": h.a.audience_ref, "permission_target": entity_ref(h.f.subject), "transport": transport.capabilities.reference})
        delivery = DeliveryService(h.f.storage, payloads=h.f.payloads, attention=h.a.service, budgets=budgets,
            controls=h.f.controls, destinations=[destination], transports=[transport], clock=h.host.clock)
        token = h.f.controls.capture(actor=h.f.actor, authority=entity_ref(h.f.authority), capability="delivery",
            targets=[entity_ref(h.f.subject), entity_ref(capture_admission.reference)])
        command = _in_scope(fixture("commands/prepare_delivery.json"), h.f.storage.scope_id)
        command.update(command_id="reject-model-delivery", idempotency_key="reject-model-delivery",
            actor=h.f.actor, authority=entity_ref(h.f.authority), expected_revisions=[])
        baseline_slot = delivered_baseline_ref(pin(h.f.subject), purpose=h.a.purpose_ref, audience=h.a.audience_ref)
        with h.f.storage.snapshot() as view:
            before_baseline = _lookup(view, baseline_slot)
        for wrong in (capture_admission.reference, proposal):
            with self.subTest(production_input=wrong), self.assertRaises(ContractError) as denied:
                delivery.prepare(command, decision=wrong, attention_command=h.f.request(), token=token,
                    destination=destination, content=b"Synthetic study is not a delivery decision.", budget=budget,
                    amounts={"deliveries": 1}, expires_at=end)
            self.assertEqual(denied.exception.code, "E_SCHEMA_INVALID")
        self.assertEqual(transport.calls, [])
        with h.f.storage.snapshot() as view:
            self.assertEqual(_lookup(view, baseline_slot), before_baseline)
            with self.assertRaises(ContractError) as missing_queue:
                view.command_receipt(command["idempotency_key"])
            self.assertEqual(missing_queue.exception.code, "E_NOT_FOUND")
        with self.assertRaises(ContractError):
            admitted.project()
        # The actual sink guard, not an earlier check, sees a pause that races
        # with capture. No row is appended on refusal.
        before_state = h.state
        def paused_sink(**args):
            h.state = replace(h.state, status="paused")
            args["require_current"]()
            self.fail("paused result captured")
        with self.assertRaises(ContractError) as paused:
            admitted.handoff(proposal, capture=paused_sink)
        self.assertEqual(paused.exception.code, "E_CANCELLED")
        h.state = before_state
        # An uncertain isolated sink is retained as unknown by this command.
        def uncertain_sink(**args):
            args["require_current"]()
            raise TimeoutError("synthetic sink acknowledgement missing")
        with self.assertRaises(ContractError) as unknown:
            admitted.handoff(proposal, capture=uncertain_sink)
        self.assertEqual(unknown.exception.code, "E_DELIVERY_UNKNOWN")
        with self.assertRaises(ContractError) as retry_unknown:
            admitted.handoff(proposal, capture=lambda **_: self.fail("unknown capture resent"))
        self.assertEqual(retry_unknown.exception.code, "E_DELIVERY_UNKNOWN")


class MixedCaptureBaselineTests(unittest.TestCase):
    def test_native_capture_is_a_real_mixed_baseline_and_repeated_material_stays_quiet(self):
        h = CaptureFixture(self, native_baseline=True)
        h.e.remember(h.f.storage.get(h.policy_pin))
        arguments = h.publish_attention()
        h.observe(arguments)
        h.sync(); h.renew_allocation()
        admitted = h.admit()
        execution = h.execute(admitted)
        admission = admitted.admit_capture(execution=execution["execution"])
        proposal = admitted.project_capture(admission=admission)
        self.assertEqual(proposal["treatment"], "quiet")
        self.assertIn("no_material_change", proposal["reasons"])
        self.assertIsNone(proposal["assessment_reference"])
        self.assertIsNotNone(admitted.request["baseline"]["assessment_reference"])
        self.assertIsNone(admitted.handoff(proposal, capture=lambda **_: self.fail("duplicate captured")))
        record_vector("mixed-native-study-baseline", h, admitted, proposal)


class SourceReadingCaptureTests(unittest.TestCase):
    def test_one_source_reading_two_audiences_positive_quiet_and_unknown(self):
        h = CaptureFixture(self, civic=True)
        h.questions = QuestionRegistry([*h.specs, *source_questions()])
        h.receipts.questions = h.questions
        # The shared source reader has only common source refs, no audience
        # purpose/intent context in either its packet or protected read closure.
        token = h.f.controls.capture(actor=h.f.actor, authority=entity_ref(h.f.authority), capability="assessment",
            targets=[entity_ref(r) for r in h.shared if _public(r)])
        with h.f.storage.snapshot() as view:
            access = h.access.capture(view, token=token, audience=h.a.audience_ref, provider=h.provider, references=h.shared)
        packet = h.prepare_source_packet(h.access, access)
        rendered = tuple(render_question(s, packet.state, s.value["id"], source_manifest=packet.source_manifest,
            access=h.access, access_context=access, access_view=h.f.storage) for s in source_questions())
        context = h.batch(h.admit())[0].value["context"]
        batch = Batch({"schema_version": "1.0", "id": "shared-source", "scope_id": h.f.storage.scope_id,
            "run_id": "shared-source", "stage_id": "source", "state": packet.state, "packet_digest": packet.digest,
            "questions": [q.question.value for q in rendered], "context": context})
        h.stage.token = token
        h.stage.targets = token["targets"]
        # Use the existing committed allocator; no synthetic allocation flags.
        from unittest.mock import patch
        from semantic import test_stages as stages
        early = {"state": "known", "value": "2049-01-01T00:00:00Z", "precision": "second"}
        late = {"state": "known", "value": "2051-01-01T00:00:00Z", "precision": "second"}
        with patch.object(stages, "EARLY", early), patch.object(stages, "LATE", late):
            h.stage.reserve(calls=4, expires=late)
        h.receipts.budgets = h.stage.budgets
        source_calls = []
        class SourceProvider:
            capabilities = Capabilities({**h.executor.capabilities.value, "primitives": ["choice", "proposition_probability"]})
            def execute(self, current):
                source_calls.append(current.digest)
                answers = []
                for q in current.value["questions"]:
                    answer = {"id": q["id"], "primitive": q["primitive"]}
                    if q["primitive"] == "choice":
                        ids = [c["id"] for c in q["criteria"]]
                        answer.update(choice=ids[0], confidence="1", probabilities={k: "1" if i == 0 else "0" for i, k in enumerate(ids)})
                    else:
                        answer["probability"] = "0.9"
                    answers.append(answer)
                return RawExecution(canonical_bytes({"answers": answers, "resolved_model": "synthetic-fixed"}))
        request = h.receipts.request(batch, packet=packet, rendered_questions=rendered, token=token,
            access_context=access, model_binding={"model": "synthetic-fixed", "resolution": component("fixed-resolution")})
        def dispatch(**args):
            with h.f.storage.snapshot() as view:
                from matter.statecivics_monitoring import packet_state_view
                frozen = packet_state_view(view, packet, access=h.access, context=access)
            return h.access.dispatch(frozen, access, args["batch"], args["executor"], rendered_questions=rendered,
                clock=h.host.clock, precision=args["precision"])
        source = h.receipts.run(request, executor=SourceProvider(), token=token, logical_request_id="source-only",
            attempt_id="initial", allocation=h.stage.reservation, access_context=access, dispatch=dispatch)
        self.assertEqual(source["status"], "completed")
        source_ref = source["execution"]
        finding = deepcopy(h.state.source_finding)
        for name, other, probability, treatment, judgment in [
                ("audience-a-positive", False, "0.99", "digest", "positive"),
                ("audience-b-quiet", True, "0.01", "quiet", "negative"),
                ("audience-b-unknown", False, "0.5", "quiet", "unknown")]:
            if other:
                h.activate_other()
            h.req["request_id"] = name; h.req["idempotency_key"] = name
            h.req["proposal_basis"]["source_reading"] = source_ref
            h.probability = probability; h.sync(); h.renew_allocation()
            admitted = h.admit()
            eligibility = capture_source_reading_eligibility(admitted, receipts=h.receipts, execution=source_ref)
            self.assertEqual(eligibility.value["qualification"], "unqualified")
            self.assertEqual(eligibility.value["recipient"], h.host.binding)
            # These are explicitly separate authored trials, not evidence of
            # provider instability or a reason to renew unresolved attempts.
            # Exercise native fresh-trial control instead of returning an older
            # cached synthetic probability for the unchanged third input.
            run = h.receipts.run
            def fresh_trial(*args, **kwargs):
                kwargs["reuse"] = False
                return run(*args, **kwargs)
            with patch.object(h.receipts, "run", fresh_trial):
                outcome = h.execute(admitted)
            admission = admitted.admit_capture(execution=outcome["execution"])
            proposal = admitted.project_capture(admission=admission)
            self.assertEqual(proposal["treatment"], treatment)
            self.assertEqual(proposal["decision_basis"]["judgments"]["objective"], judgment)
            self.assertEqual(proposal["source_finding_reference"], finding)
            if judgment == "unknown":
                self.assertIn("semantic_unknown", proposal["reasons"])
                self.assertNotIn("no_relevance", proposal["reasons"])
            record_vector(name, h, admitted, proposal)
        self.assertEqual(len(source_calls), 1)
        self.assertEqual(len(h.calls), 3)


class CaptureBoundaryTests(unittest.TestCase):
    """Run existing behavioral boundaries through the opt-in 1.1 admission."""
    def setUp(self):
        self.h = CaptureFixture(self)

    def test_missing_trusted_optin_and_mismatched_policy_refuse(self):
        h = self.h
        state, host = h.state, h.host
        for missing in (None, {**h.policy_pin, "digest": "0" * 64}):
            h.state = replace(state, capture_policy=missing)
            with self.subTest(policy=missing), self.assertRaises(ContractError):
                h.admit()
        h.state = state
        h.host = replace(host, capture_service=None)
        with self.assertRaises(ContractError):
            h.admit()
        h.host = host
        self.assertEqual(h.calls, [])

    from integration.test_monitoring_handoff import MonitoringHandoffTests as _Existing
    test_target_draft_pause_revoke_mute_and_scope_refuse_before_execution = _Existing.test_target_draft_pause_revoke_mute_and_scope_refuse_before_execution
    test_intent_edit_during_io_withholds_answer_and_retains_attempt = _Existing.test_intent_edit_during_io_withholds_answer_and_retains_attempt
    test_unknown_prior_outcome_is_not_absent_history = _Existing.test_unknown_prior_outcome_is_not_absent_history
    test_source_grant_revocation_at_dispatch_and_during_io_withholds_and_never_resends = _Existing.test_source_grant_revocation_at_dispatch_and_during_io_withholds_and_never_resends
    test_forged_scope_and_future_manifest_fail_even_if_host_projection_echoes_them = _Existing.test_forged_scope_and_future_manifest_fail_even_if_host_projection_echoes_them
    del _Existing


class StudyCaptureHistoryTests(unittest.TestCase):
    def test_actual_isolated_capture_duplicate_and_linked_correction(self):
        import sqlite3
        from unittest.mock import patch
        from integration import test_lifecycle_episodes as lifecycle
        h = CaptureFixture(self)
        # A small actual host capture table, separate from native Matter
        # assessments/milestones. No source or delivered claim is fabricated.
        host_db = sqlite3.connect(":memory:")
        self.addCleanup(host_db.close)
        host_db.execute("create table captures (capture_key text primary key, receipt text, payload text)")
        admitted = h.admit()
        execution = h.execute(admitted)
        admission = admitted.admit_capture(execution=execution["execution"])
        result = admitted.project_capture(admission=admission)
        original = admission.value["value"]
        owner = {**{k: h.host.binding[k] for k in ("user_id", "workspace_id", "client_id")}, "intent_id": h.req["intent"]["id"]}
        payload = {"status": "captured", "owner": owner, "candidate": original["candidate"],
            "material": original["material"], "material_contract": original["material_contract"],
            "admission_reference": admission.reference, "captured_at": deepcopy(h.f.now)}
        receipt = {"scope_id": h.f.storage.scope_id, "namespace": "synthetic.host", "record_type": "receipt",
            "id": "capture-" + result["capture_key"],
            "digest": canonical_digest(payload, "synthetic.actual-capture-row.v1")}
        def sink(**args):
            with host_db:
                args["require_current"]()
                host_db.execute("insert or ignore into captures values (?, ?, ?)",
                    (args["assessment_key"], json.dumps(receipt), json.dumps(payload)))
            return receipt
        self.assertEqual(admitted.handoff(result, capture=sink), receipt)
        self.assertEqual(admitted.handoff(result, capture=sink), receipt)
        self.assertEqual(host_db.execute("select count(*) from captures").fetchone()[0], 1)
        def history(*, receipt, host_binding, access_context):
            row = host_db.execute("select receipt, payload from captures").fetchone()
            actual_receipt, actual = map(json.loads, row)
            self.assertEqual(receipt, actual_receipt)
            self.assertEqual({k: actual["owner"][k] for k in ("user_id", "workspace_id", "client_id")},
                {k: host_binding[k] for k in ("user_id", "workspace_id", "client_id")})
            self.assertEqual(actual["status"], "captured")
            self.assertIsNotNone(access_context)
            return ObservedMonitoringCapture(receipt=actual_receipt, admission_reference=actual["admission_reference"],
                owner=actual["owner"], candidate=actual["candidate"], material=actual["material"],
                material_contract=actual["material_contract"], captured_at=actual["captured_at"])
        h.capture_service.capture_history = history
        h.req["baseline"] = {"status": "observed_capture", "decision_basis": "unqualified_model_capture",
            "receipt": receipt, "owner": owner, "intent_revision_id": result["intent_revision_id"],
            "assessment_reference": None, "capture_admission_reference": admission.reference,
            "conveyed_material_digest": canonical_digest(original["material"], "matter.monitoring-conveyed-material.v1")}
        h.req.update(request_id="study-duplicate", idempotency_key="study-duplicate")
        h.refresh(extra=[admission.reference]); h.renew_allocation()
        repeated = h.admit()
        second = h.execute(repeated)
        repeat_admission = repeated.admit_capture(execution=second["execution"])
        quiet = repeated.project_capture(admission=repeat_admission)
        self.assertEqual(quiet["treatment"], "quiet")
        self.assertIn("no_material_change", quiet["reasons"])
        self.assertIsNone(repeated.handoff(quiet, capture=lambda **_: self.fail("duplicate captured")))
        record_vector("study-baseline-duplicate", h, repeated, quiet)
        # A real source lineage and changed material can correct an earlier
        # capture even when ordinary relevance/novelty abstain.
        old = h.claim
        future = {"state": "known", "value": "2051-01-01T00:00:00Z", "precision": "second"}
        with patch.object(lifecycle, "FUTURE", future):
            h.claim = h.e.claim("study-linked-retraction", h.e.condition_a, "retracted", h.source,
                effective=h.f.now, supersedes=[old])
        h.req["evidence"]["correction_of"] = [pin(old)]
        h.req.update(request_id="study-correction", idempotency_key="study-correction")
        h.probability = "0.5"
        h.refresh(extra=[pin(h.claim)]); h.renew_allocation()
        corrected = h.admit()
        third = h.execute(corrected)
        correction_admission = corrected.admit_capture(execution=third["execution"])
        correction = corrected.project_capture(admission=correction_admission)
        self.assertEqual(correction["treatment"], "correction")
        self.assertIn("semantic_unknown", correction["reasons"])
        self.assertIn("correction_delta", correction["reasons"])
        self.assertIsNone(correction["assessment_reference"])
        record_vector("study-baseline-linked-correction", h, corrected, correction)


class CaptureAdmissionRecoveryTests(unittest.TestCase):
    def test_definite_control_conflict_uses_explicit_fresh_attempt_without_model_resend(self):
        from unittest.mock import patch
        h = CaptureFixture(self)
        admitted = h.admit()
        execution = h.execute(admitted)
        original_execute = h.f.storage.execute
        injected = []
        def racing(command, *args, **kwargs):
            if not injected and command["operation"] == "record_control":
                payload = command["body"]["control"]["body"]["effect"]["value"]["payload"]["value"]
                if payload["action"] == "admit_capture":
                    injected.append(True)
                    other = h.capture_policy.value; other["id"] = "unrelated-policy"
                    h.capture_service.install_policy(MonitoringCapturePolicy(other), actor=h.f.actor,
                        authority=h.f.authority, command_id="unrelated-control", idempotency_key="unrelated-control")
            return original_execute(command, *args, **kwargs)
        with patch.object(h.f.storage, "execute", racing), self.assertRaises(ContractError) as conflict:
            admitted.admit_capture(execution=execution["execution"])
        self.assertEqual(injected, [True])
        self.assertEqual(conflict.exception.code, "E_DEPENDENCY_STALE")
        # Exact idempotency preserves the actual recorded failure. It must not
        # silently mint another command, renew work tokens or resend a model.
        with self.assertRaises(ContractError) as exact:
            admitted.admit_capture(execution=execution["execution"])
        self.assertEqual(exact.exception.code, "E_DEPENDENCY_STALE")
        admission = admitted.admit_capture(execution=execution["execution"],
            command_id="fresh-capture-control-attempt", idempotency_key="fresh-capture-control-attempt")
        result = admitted.project_capture(admission=admission)
        self.assertEqual(result["treatment"], "digest")
        self.assertEqual(result["decision_basis"]["original_execution_reference"], execution["execution"])
        again = admitted.admit_capture(execution=execution["execution"],
            command_id="fresh-capture-control-attempt", idempotency_key="fresh-capture-control-attempt")
        self.assertEqual(again.reference, admission.reference)
        self.assertEqual(len(h.calls), 1)
