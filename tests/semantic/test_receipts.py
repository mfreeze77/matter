"""MAT-030 raw evidence, immutable attempts and exact replay; no provider calls."""

import base64
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import unittest

from matter.canonical import source_digest
from matter.contracts import ContractError
from matter.semantic.contracts import ExecutionFault, ExecutionInstrumentation, RawExecution, execute_batch
from semantic import test_contracts as contracts_fixture


class ExecutionEvidenceTests(unittest.TestCase):
    def metadata(self, identity="attempt", **changes):
        value = {"logical_request_id": "logical", "attempt_id": identity, "started": contracts_fixture.instant(0),
                 "completed": contracts_fixture.instant(1), "request_bytes": 123, "response_bytes": None,
                 "usage": {"input_tokens": 10, "output_tokens": None, "total_tokens": None}}
        value.update(changes)
        return ExecutionInstrumentation(value)

    def execute(self, returned):
        batch = contracts_fixture.make_batch()
        class Adapter:
            capabilities = contracts_fixture.capabilities()
            def execute(inner, _):
                if isinstance(returned, Exception):
                    raise returned
                return returned
        return execute_batch(Adapter(), batch, clock=lambda: contracts_fixture.instant(0))

    def test_default_fixture_shape_is_unchanged_and_native_precision_is_separate(self):
        batch = contracts_fixture.make_batch()
        neutral = contracts_fixture.response(batch)
        ordinary = self.execute(RawExecution(neutral)).value
        self.assertNotIn("native_response", ordinary)
        self.assertNotIn("instrumentation", ordinary)
        native = b'{"answers":{"claim":{"noul":0.1234567890123456789}}}'
        result = self.execute(RawExecution(neutral, native_response=native, instrumentation=self.metadata())).value
        self.assertEqual(base64.b64decode(result["native_response"]["base64"]), native)
        self.assertEqual(result["native_response"]["sha256"], source_digest(native))
        self.assertEqual(base64.b64decode(result["raw_response"]["base64"]), neutral)
        self.assertEqual(result["diagnostics"][0]["answer"]["probability"], "0.1234567890123456789")
        self.assertEqual(result["instrumentation"]["response_bytes"], None)
        self.assertEqual(result["instrumentation"]["unavailable"]["response_bytes"], "not_observed")
        self.assertEqual(result["usage"]["value"]["unavailable"]["output_tokens"], "not_reported")

    def test_safe_typed_fault_retains_observations_without_exception_text(self):
        native = b'{"error":"synthetic rate limit"}'
        metadata = self.metadata(response_bytes=len(native))
        result = self.execute(ExecutionFault("rate_limited", native_response=native, instrumentation=metadata)).value
        self.assertEqual(result["execution_status"], "failed")
        self.assertEqual(result["faults"], [{"code": "rate_limited", "path": []}])
        self.assertEqual(result["instrumentation"]["attempt_id"], "attempt")
        self.assertEqual(base64.b64decode(result["native_response"]["base64"]), native)
        self.assertEqual(result["admission"]["primitive_status"], "invalid")
        for code, status in (("timeout", "timed_out"), ("cancelled", "cancelled"), ("response_budget", "budget_exhausted")):
            self.assertEqual(self.execute(ExecutionFault(code, instrumentation=metadata)).value["execution_status"], status)
        generic = self.execute(RuntimeError("SYNTHETIC-SECRET-EXCEPTION")).value
        self.assertNotIn("SECRET", str(generic))

    def test_instrumentation_is_immutable_bounded_and_rejects_secret_fields(self):
        original = self.metadata()
        changed = original.value
        changed["attempt_id"] = "changed"
        self.assertEqual(original.value["attempt_id"], "attempt")
        with self.assertRaises(AttributeError):
            original.attempt_id = "changed"
        for value in ({"authorization": "SYNTHETIC-SECRET"}, {"request_bytes": True},
                      {"request_bytes": 1.5}, {"usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": "3"}}):
            with self.assertRaises(ContractError) as error:
                ExecutionInstrumentation(value)
            self.assertNotIn("SECRET", str(error.exception))

    def test_missing_precision_and_model_are_explicit_and_never_qualified(self):
        rounded = self.execute(ExecutionFault("precision_unavailable", instrumentation=self.metadata())).value
        self.assertFalse(rounded["admission"]["exact_numeric"])
        self.assertEqual(rounded["admission"]["primitive_status"], "invalid")
        native = b'{"answers":{"q":{"noul":0.1234567890123456789}}}'
        unknown_model = self.execute(ExecutionFault("model_unresolved", native_response=native, instrumentation=self.metadata())).value
        self.assertIsNone(unknown_model["resolved_model"])
        self.assertEqual(unknown_model["faults"], [{"code": "model_unresolved", "path": []}])
        self.assertEqual(base64.b64decode(unknown_model["native_response"]["base64"]), native)
        self.assertFalse(unknown_model["admission"]["consequential_use"])

    def test_concurrent_attempts_keep_their_own_native_bytes_and_ids(self):
        batch = contracts_fixture.make_batch()
        def run(identity):
            native = ("native-" + identity).encode()
            result = self.execute(RawExecution(contracts_fixture.response(batch), native_response=native,
                instrumentation=self.metadata(identity))).value
            return result["instrumentation"]["attempt_id"], base64.b64decode(result["native_response"]["base64"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ("one", "two")))
        self.assertEqual(results, [("one", b"native-one"), ("two", b"native-two")])

    def test_execution_fault_survives_actual_contextmanager_traceback_updates(self):
        @contextmanager
        def guard():
            yield
        fault = ExecutionFault("timeout", instrumentation=self.metadata())
        with self.assertRaises(ExecutionFault) as error:
            with guard():
                raise fault
        self.assertIs(error.exception, fault)
        self.assertEqual(error.exception.code, "timeout")
        with self.assertRaises(AttributeError):
            fault._code = "provider_error"


if __name__ == "__main__":
    unittest.main()


from matter.canonical import canonical_bytes
from matter.semantic.contracts import Batch, PrecisionProfile
from matter.semantic.receipts import ExecutionReceiptStore, normalized_digest
from matter.semantic.cache import execution_key
from matter.storage import pin, entity_ref, StorageError
from semantic import test_stages as stages_fixture
from rule_helpers import component


class DurableExecutionTests(unittest.TestCase):
    def setUp(self):
        self.stage = stages_fixture.StageTests(methodName="runTest")
        self.stage.setUp()
        self.addCleanup(self.stage.doCleanups)
        self.stage.reserve(calls=4)
        self.f = self.stage.f
        self.service = ExecutionReceiptStore(self.f.storage, payloads=self.f.payloads, controls=self.f.controls,
            clock=lambda: self.f.now, questions=self.stage.questions, budgets=self.stage.budgets)
        stage = self.stage.stage("evidence", ["support", "contradiction"])
        self.material = self.stage.material(stage, [])
        self.batch = Batch({"schema_version": "1.0", "id": "batch", "run_id": "logical", "stage_id": "evidence",
            "scope_id": self.f.storage.scope_id, "state": self.material.packet.state, "packet_digest": self.material.packet.digest,
            "questions": [item.question.value for item in self.material.rendered_questions], "context": self.material.value["context"]})
        self.binding = {"model": "synthetic-fixed", "resolution": component("fixed-model-resolution")}
        self.request = self.service.request(self.batch, packet=self.material.packet, rendered_questions=self.material.rendered_questions,
            token=self.stage.token, model_binding=self.binding)

    def run_attempt(self, identity, request=None, **kw):
        return self.service.run(request or self.request, executor=self.stage.spy, token=self.stage.token,
            logical_request_id="logical", attempt_id=identity, allocation=self.stage.reservation, **kw)

    def test_real_sqlite_cache_reuse_keeps_original_attempt_and_no_new_invocation(self):
        first = self.run_attempt("first")
        self.assertEqual(first["status"], "completed", first)
        self.assertEqual(len(self.stage.calls), 1)
        original = self.service.read(first["execution"])
        second_request = deepcopy(self.request)
        second_request["batch"].update(id="new-batch", run_id="new-logical", stage_id="new-stage")
        second = self.run_attempt("second", second_request)
        self.assertEqual(second["status"], "reused", second)
        self.assertEqual(len(self.stage.calls), 1)
        reused = self.service.read(second["execution"])
        self.assertEqual(self.service.read(first["execution"]), original)
        self.assertEqual(reused["body"]["details"]["value"]["source_execution"], first["execution"])
        self.assertEqual(reused["provenance"]["origin"], "evaluator")
        self.assertFalse(second["result"].value["admission"]["consequential_use"])
        self.assertEqual(self.run_attempt("second", second_request)["status"], "reused")
        self.assertEqual(len(self.stage.calls), 1)

    def test_failed_batch_partial_heads_are_durable_and_replay_cannot_admit(self):
        self.stage.invalid = True
        first = self.run_attempt("invalid")
        self.assertEqual(first["status"], "completed", first)
        result = self.service.replay(first["execution"])
        self.assertFalse(result.primitive_valid)
        self.assertTrue(any(item["answer"] is not None for item in result.value["diagnostics"]))
        self.assertTrue(any(fault["code"] == "missing_answer" for fault in result.value["faults"]))
        self.assertIsNone(self.service.lookup(self.request, token=self.stage.token))
        self.assertEqual(len(self.stage.calls), 1)

    def test_exact_high_precision_payload_roundtrip_and_unavailable_usage(self):
        first = self.run_attempt("precision")
        self.assertEqual(first["status"], "completed", first)
        record = self.service.read(first["execution"])
        value = record["body"]["details"]["value"]
        self.assertNotIn("base64", str(value))
        self.assertEqual(value["result"]["diagnostics"][0]["answer"]["probability"], "0.1234567890123456789")
        raw = self.f.payloads.read(value["neutral_response"]).data
        replay = self.service.replay(first["execution"])
        self.assertEqual(base64.b64decode(replay.value["raw_response"]["base64"]), raw)
        self.assertEqual(replay.value["usage"]["value"], None)
        self.assertEqual(replay.value["cost"]["value"], None)
        self.assertEqual(value["normalized_digest"], self.service.read(first["execution"])["body"]["details"]["value"]["normalized_digest"])
        rounded = raw.replace(b"0.1234567890123456789", b"0.12345678901234568")
        self.assertNotEqual(source_digest(raw), source_digest(rounded))

    def test_independent_cache_identity_changes_and_unknown_resolution(self):
        self.assertEqual(self.run_attempt("original")["status"], "completed")
        extra = deepcopy(self.request); extra["packet"]["dependencies"].append(pin(self.f.subject))
        self.assertIsNone(self.service.lookup(extra, token=self.stage.token))
        original_key = execution_key(self.batch, rendered=self.request["rendered"], precision=PrecisionProfile(),
            model_binding=self.binding, token=self.stage.token)
        for field in ("requested_model", "adapter_version", "transport"):
            data = self.batch.value
            data["context"][field] += "-different"
            key = execution_key(Batch(data), rendered=self.request["rendered"], precision=PrecisionProfile(), model_binding=self.binding, token=self.stage.token)
            self.assertNotEqual(key, original_key)
        for mutation in ("model", "order", "renderer", "packet", "precision"):
            data, rendered, binding, precision = self.batch.value, deepcopy(self.request["rendered"]), deepcopy(self.binding), PrecisionProfile()
            if mutation == "model": binding["model"] = "another"
            if mutation == "order": data["questions"].reverse(); rendered.reverse()
            if mutation == "renderer": rendered[0]["manifest"]["renderer"]["version"] = "different"
            if mutation == "packet": data["state"]["synthetic_extra"] = True; data["packet_digest"] = __import__('matter.canonical', fromlist=['canonical_digest']).canonical_digest(data["state"], "matter.semantic.packet.v1"); [q.update(packet_digest=data["packet_digest"]) for q in data["questions"]]
            if mutation == "precision": precision = PrecisionProfile("rounded", probability_quantum="0.01")
            self.assertNotEqual(execution_key(Batch(data), rendered=rendered, precision=precision, model_binding=binding, token=self.stage.token), original_key, mutation)
        request = deepcopy(self.request); request["model_binding"] = None
        self.assertIsNone(self.service.lookup(request, token=self.stage.token))

    def test_revocation_classifier_rechecked_before_each_reuse(self):
        self.assertEqual(self.run_attempt("original")["status"], "completed")
        decisions = []
        def qualifier(**args):
            decisions.append(args["execution"])
            return {"status": "qualified" if len(decisions) == 1 else "revoked", "certificate": component("synthetic-qualified")}
        self.assertIsNotNone(self.service.lookup(self.request, token=self.stage.token, qualify=qualifier))
        self.assertIsNone(self.service.lookup(self.request, token=self.stage.token, qualify=qualifier))
        self.assertEqual(len(decisions), 2)
        self.assertEqual(len(self.stage.calls), 1)

    def test_unknown_dispatch_is_durable_and_same_attempt_never_reissued(self):
        def opaque(**_):
            raise RuntimeError("SYNTHETIC-PRIVATE")
        first = self.run_attempt("unknown", dispatch=opaque)
        self.assertEqual(first["status"], "unknown", first)
        second = self.run_attempt("unknown")
        self.assertEqual(second["status"], "unknown")
        self.assertFalse(second["dispatched"])
        self.assertEqual(len(self.stage.calls), 0)
        self.assertNotIn("PRIVATE", str(self.service.read(first["execution"])))

    def test_fractional_score_native_and_neutral_evidence_survive_actual_persistence(self):
        import json
        from matter.semantic.questions import QuestionRegistry, QuestionSpecification
        from matter.semantic.rendering import render_question
        from matter.semantic.contracts import Capabilities
        score = QuestionSpecification({**self.stage.specs["support"].value, "id": "score", "family": "synthetic.score",
            "primitive": "score", "criteria": ["No source support.", "Direct source support."]})
        self.service.questions = QuestionRegistry([self.stage.specs["support"], score])
        packet = self.material.packet
        rendered = [self.material.rendered_questions[0], render_question(score, packet.state, "score", source_manifest=packet.source_manifest)]
        data = self.batch.value; data["questions"] = [item.question.value for item in rendered]
        batch = Batch(data)
        profile = PrecisionProfile("synthetic-rounded", probability_quantum="0.1", score_quantum="0.1")
        request = self.service.request(batch, packet=packet, rendered_questions=rendered, token=self.stage.token,
            precision=profile, model_binding=self.binding)
        wire = ('{"answers":[{"id":"support","primitive":"proposition_probability","probability":0.1234567890123456789},'
            '{"id":"score","primitive":"score","score":"0.7","legend":{"0":"No source support.","1":"Direct source support."},'
            '"probabilities":{"0":"0.3","1":"0.6"},"confidence":"0.1234567890123456789"}],"resolved_model":"synthetic-fixed"}').encode()
        native = b'{"vendorOriginal":{"noul":0.1234567890123456789,"score":0.7}}'
        class Adapter:
            capabilities = Capabilities({**self.stage.spy.capabilities.value, "primitives": ["proposition_probability", "score"]})
            def execute(inner, _):
                return RawExecution(wire, native_response=native, instrumentation=ExecutionInstrumentation({"request_bytes": None, "response_bytes": None}))
        result = self.service.run(request, executor=Adapter(), token=self.stage.token, logical_request_id="logical", attempt_id="score",
            allocation=self.stage.reservation)
        self.assertEqual(result["status"], "completed", result)
        replay = self.service.replay(result["execution"])
        self.assertTrue(replay.primitive_valid, replay.value)
        answers = {item["id"]: item["answer"] for item in replay.value["diagnostics"]}
        self.assertEqual(answers["score"]["score"], "0.7")
        self.assertEqual(answers["score"]["distribution_residual"], "-0.1")
        self.assertEqual(answers["score"]["score_residual"], "0.1")
        self.assertEqual(answers["score"]["confidence"], "0.1234567890123456789")
        self.assertEqual(base64.b64decode(replay.value["raw_response"]["base64"]), wire)
        self.assertEqual(base64.b64decode(replay.value["native_response"]["base64"]), native)
        changed = deepcopy(request); changed["precision"] = PrecisionProfile().value
        self.assertIsNone(self.service.lookup(changed, token=self.stage.token))

    def test_started_receipt_is_recoverable_without_reissuing_and_original_control_cannot_be_renewed(self):
        value = self.service._metadata(self.service._clip_request(self.request, self.stage.reservation), token=self.stage.token, logical_request_id="logical", attempt_id="interrupted",
            phase="started", allocation=self.stage.reservation)
        command = self.service.prepare(value, command_id="interrupted", idempotency_key="interrupted")
        claimed = []; first = self.service.commit(command, _claimed=claimed)
        self.assertEqual(first["status"], "success", first)
        self.assertEqual(claimed, [True])
        replay_claim = []; self.assertEqual(self.service.commit(command, _claimed=replay_claim), first)
        self.assertEqual(replay_claim, [])
        from matter.storage import SQLiteStore
        reopened = SQLiteStore(self.f.database, scope_id=self.f.storage.scope_id)
        self.addCleanup(reopened.close)
        service = ExecutionReceiptStore(reopened, payloads=self.f.payloads, controls=self.f.controls,
            clock=lambda: self.f.now, questions=self.stage.questions, budgets=self.stage.budgets)
        recovered = service.run(self.request, executor=self.stage.spy, token=self.stage.token, logical_request_id="logical",
            attempt_id="interrupted", allocation=self.stage.reservation)
        self.assertEqual(recovered["status"], "started")
        self.assertFalse(recovered["dispatched"])
        self.assertIsNone(recovered["result"])
        self.assertEqual(len(self.stage.calls), 0)
        self.assertEqual(len(service.history("logical", "interrupted")), 1)
        completion = deepcopy(value); completion["phase"] = "unknown"
        completion["control_token"]["captured_at"] = contracts_fixture.instant(0)
        with self.assertRaises(ContractError):
            service.prepare(completion, command_id="renew", idempotency_key="renew")

    def test_actual_read_revocation_blocks_history_and_cache_after_success(self):
        from control_helpers import control_command
        from integration.helpers import _in_scope
        first = self.run_attempt("original")
        command = _in_scope(control_command("deny-semantic-read", self.f.authority, targets=[self.f.source],
            action="deny", capabilities=["read"], now=self.f.now), self.f.storage.scope_id)
        command["actor"] = self.f.actor; command["body"]["control"]["body"]["actor"] = self.f.actor
        self.assertEqual(self.f.controls.apply(self.f.controls.prepare(command))["status"], "success")
        for operation in (lambda: self.service.read(first["execution"]), lambda: self.service.replay(first["execution"]),
                          lambda: self.service.lookup(self.request, token=self.stage.token)):
            with self.assertRaises(ContractError) as error:
                operation()
            self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")
        self.assertEqual(len(self.stage.calls), 1)

    def test_changed_source_basis_blocks_reuse_but_durable_history_remains_inspectable(self):
        from matter.semantic.packets import PreparedPacket
        raw = self.material.packet.value; raw["dependencies"].append(pin(self.f.subject))
        packet = PreparedPacket(raw, _prepared=True)
        request = self.service.request(self.batch, packet=packet, rendered_questions=self.material.rendered_questions,
            token=self.stage.token, model_binding=self.binding)
        first = self.run_attempt("original", request)
        self.assertEqual(first["status"], "completed", first)
        self.f.rename_subject()
        self.assertEqual(self.service.replay(first["execution"]).value["diagnostics"][0]["answer"]["probability"], "0.1234567890123456789")
        with self.assertRaises(ContractError) as error:
            self.service.lookup(request, token=self.stage.token)
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")

    def test_serialized_receipt_cannot_promote_failed_admission_or_mutate_engine(self):
        self.stage.invalid = True
        result = execute_batch(self.stage.spy, self.batch, clock=lambda: self.f.now)
        value = self.service._metadata(self.request, token=self.stage.token, logical_request_id="logical", attempt_id="observed",
            phase="observed", result=result)
        command = self.service.prepare(value, command_id="observed", idempotency_key="observed")
        bad = deepcopy(command); bad["body"]["receipt"]["provenance"]["origin"] = "host"
        with self.assertRaises(ContractError): self.service.commit(bad)
        foreign = deepcopy(value); foreign["allocation"] = {**self.stage.reservation, "scope_id": "foreign-scope"}
        with self.assertRaises(ContractError) as scope_error:
            self.service.prepare(foreign, command_id="foreign-allocation", idempotency_key="foreign-allocation")
        self.assertEqual(scope_error.exception.code, "E_SCOPE_FORBIDDEN")
        value["result"]["admission"]["primitive_status"] = "valid"
        from matter.canonical import canonical_digest
        value["normalized_digest"] = normalized_digest(value["result"])
        with self.assertRaises(ContractError): self.service.prepare(value, command_id="promote", idempotency_key="promote")
        self.assertEqual(self.service.commit(command)["status"], "success")

    def test_stage_unknown_request_is_stored_without_fabricated_result_or_parent_receipt(self):
        from matter.semantic.stages import StageExecutor
        def opaque(*args, **kw):
            raise RuntimeError("SYNTHETIC-PRIVATE")
        self.stage.runner = StageExecutor(questions=self.stage.questions, budgets=self.stage.budgets,
            executor=self.stage.spy, clock=lambda: self.f.now, dispatch=opaque)
        plan = self.stage.plan([self.stage.stage("evidence", ["support"])])
        run = self.stage.execute(plan, lambda stage, parents, **kw: self.stage.material(stage, parents))
        self.assertIsNone(run.value["batches"][0]["result"])
        recorded = self.service.record_stage_batch(run, 0, token=self.stage.token, attempt_id="stage-observed",
            command_id="stage-observed", idempotency_key="stage-observed", model_binding=self.binding)
        self.assertEqual(recorded["status"], "success", recorded)
        value = self.service.read(recorded["body"]["execution"])["body"]["details"]["value"]
        self.assertEqual(value["phase"], "observed")
        self.assertIsNone(value["result"])
        self.assertIsNone(self.service.replay(recorded["body"]["execution"]))
        self.assertEqual(value["request"]["stage"]["plan"], plan.reference)
        self.assertEqual(value["request"]["stage"]["members"][0]["stage_id"], "evidence")
        self.assertIsNone(self.service.lookup(value["request"], token=self.stage.token))

    def test_cancellation_after_provider_retains_raw_completion_in_failed_operation_journal(self):
        from control_helpers import control_command
        from integration.helpers import _in_scope
        def dispatch(**args):
            result = execute_batch(args["executor"], args["batch"], clock=self.service.clock, precision=args["precision"])
            command = _in_scope(control_command("stop-during-call", self.f.authority, targets=[self.f.source], action="cancel", now=self.f.now), self.f.storage.scope_id)
            command["actor"] = self.f.actor; command["body"]["control"]["body"]["actor"] = self.f.actor
            self.assertEqual(self.f.controls.apply(self.f.controls.prepare(command))["status"], "success")
            return result
        finished = self.run_attempt("cancelled", dispatch=dispatch)
        self.assertEqual(finished["status"], "refused", finished)
        self.assertEqual(finished["operation"]["error"]["code"], "E_CANCELLED")
        from matter.semantic.cache import attempt_ref
        from matter.canonical import canonical_digest
        address = attempt_ref(self.f.storage.scope_id, "logical", "cancelled")
        journal = self.service.attempt("finish-" + canonical_digest(address, "matter.semantic.command.v1"))
        value = journal["command"]["body"]["receipt"]["body"]["details"]["value"]
        self.assertEqual(value["result"]["diagnostics"][0]["answer"]["probability"], "0.1234567890123456789")
        self.assertIsNotNone(value["neutral_response"])
        self.assertEqual(len(self.service.history("logical", "cancelled")), 1)
        self.assertEqual(self.run_attempt("cancelled")["status"], "started")
        self.assertEqual(len(self.stage.calls), 1)

    def test_retry_is_distinct_observation_not_independent_evidence_and_zero_retry_quota_stops_dispatch(self):
        first = self.run_attempt("first")
        second = self.run_attempt("retry", retry_of=first["execution"], reuse=False)
        self.assertEqual(second["status"], "refused", second)
        self.assertEqual(second["operation"]["error"]["code"], "E_BUDGET_EXHAUSTED")
        self.assertEqual(len(self.stage.calls), 1)
        result = execute_batch(self.stage.spy, self.batch, clock=lambda: self.f.now)
        observed = self.service.record(self.request, token=self.stage.token, logical_request_id="logical", attempt_id="actual-host-retry",
            phase="observed", result=result, retry_of=first["execution"], command_id="observed-retry", idempotency_key="observed-retry")
        self.assertEqual(observed["status"], "success", observed)
        value = self.service.read(observed["body"]["execution"])["body"]["details"]["value"]
        self.assertEqual(value["retry_of"], first["execution"])
        self.assertEqual(value["sources"], self.service.read(first["execution"])["body"]["details"]["value"]["sources"])
        self.assertEqual(self.service.read(observed["body"]["execution"])["provenance"]["origin"], "evaluator")
        self.assertEqual(len(self.stage.calls), 2)

    def test_protected_packet_requires_installed_original_access_boundary_before_recording(self):
        from matter.access import AccessService, HostAccessPolicy
        from matter.semantic.questions import QuestionRegistry
        audience, provider = component("semantic-audience"), component("semantic-provider")
        policy = HostAccessPolicy(scope_id=self.f.storage.scope_id, audiences=[audience],
            providers=[{"reference": provider, "provider": "synthetic", "transport": "fixture"}],
            grants=[{"reference": pin(record), "audiences": [audience], "providers": [provider]}
                for record in (self.f.source, self.f.subject, self.stage.candidate)])
        access = AccessService(policy=policy, controls=self.f.controls)
        with self.f.storage.snapshot() as view:
            context = access.capture(view, token=self.stage.token, audience=audience, provider=provider,
                references=[pin(self.f.source), pin(self.f.subject), pin(self.stage.candidate)])
        packet = self.stage.packet(access=access, access_context=context)
        stage = self.stage.stage("protected", ["support"])
        material = self.stage.material(stage, [], packet=packet, access=access, access_context=context)
        data = self.batch.value; data.update(state=packet.state, packet_digest=packet.digest,
            questions=[item.question.value for item in material.rendered_questions])
        batch = Batch(data)
        with self.assertRaises(ContractError) as error:
            self.service.request(batch, packet=packet, rendered_questions=material.rendered_questions,
                token=self.stage.token, model_binding=self.binding)
        self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")
        self.assertNotIn(self.f.source["id"], str(error.exception))
        self.assertEqual(len(self.stage.calls), 0)
        self.service.access = access
        self.assertEqual(self.service.request(batch, packet=packet, rendered_questions=material.rendered_questions,
            token=self.stage.token, model_binding=self.binding, access_context=context)["batch"], batch.value)
        access.current_read = self.f.storage.snapshot
        request = self.service.request(batch, packet=packet, rendered_questions=material.rendered_questions,
            token=self.stage.token, model_binding=self.binding, access_context=context)
        from matter.semantic.cache import attempt_ref
        before_allocation = self.f.storage.get(self.stage.reservation)
        with self.assertRaises(ContractError) as missing:
            self.service.run(request, executor=self.stage.spy, token=self.stage.token, logical_request_id="protected",
                attempt_id="protected-first", allocation=self.stage.reservation, access_context=context)
        self.assertEqual(missing.exception.code, "E_AUTHORITY_REQUIRED")
        with self.assertRaises(StorageError) as absent:
            self.f.storage.get(attempt_ref(self.f.storage.scope_id, "protected", "protected-first"))
        self.assertEqual(absent.exception.code, "E_NOT_FOUND")
        with self.f.storage.snapshot() as view:
            self.assertEqual(view.watchers(self.service._watch(self.stage.reservation)), [])
        self.assertEqual(self.f.storage.get(self.stage.reservation), before_allocation)
        self.assertEqual(len(self.stage.calls), 0)
        def guarded(**args):
            from matter.assessments import FrozenAssessmentView
            from matter.budgets import _Reads
            with self.f.storage.snapshot() as snapshot:
                tracked = _Reads(snapshot, self.f.storage.scope_id)
                access.require_packet(tracked, context, args["batch"].value["state"])
                detached = FrozenAssessmentView({"records": list(tracked.records.values()), "absent": list(tracked.absent.values()),
                    "watch_queries": tracked.queries})
            return access.dispatch(detached, context, args["batch"], args["executor"],
                rendered_questions=material.rendered_questions, clock=args["clock"], precision=args["precision"])
        first = self.service.run(request, executor=self.stage.spy, token=self.stage.token, logical_request_id="protected",
            attempt_id="protected-first", allocation=self.stage.reservation, access_context=context, dispatch=guarded)
        self.assertEqual(first["status"], "completed", first)
        second = self.service.run(request, executor=self.stage.spy, token=self.stage.token, logical_request_id="protected",
            attempt_id="protected-second", allocation=self.stage.reservation, access_context=context)
        self.assertEqual(second["status"], "reused", second)
        self.assertEqual(len(self.stage.calls), 1)

    def test_effective_dispatch_deadline_is_clipped_and_original_submission_recovers(self):
        first = self.run_attempt("bounded")
        self.assertEqual(first["status"], "completed", first)
        self.assertEqual(len(self.stage.calls), 1)
        from matter.budgets import milliseconds
        actual = self.stage.calls[0]
        self.assertEqual(milliseconds(actual["context"]["deadline"], self.f.now), 10000)
        record = self.service.read(first["execution"])
        request = record["body"]["details"]["value"]["request"]
        self.assertEqual(request["requested_deadline"], self.request["batch"]["context"]["deadline"])
        self.assertNotEqual(request["batch"]["context"]["deadline"], request["requested_deadline"])
        self.assertEqual(self.run_attempt("bounded")["status"], "completed")
        self.assertEqual(len(self.stage.calls), 1)

    def test_canonical_decimal_digest_is_stable_while_original_wire_is_distinct(self):
        from matter.semantic.contracts import normalize_response
        raw = contracts_fixture.response(contracts_fixture.make_batch())
        batch = contracts_fixture.make_batch()
        alternative = raw.replace(b"0.1234567890123456789", b"0.123456789012345678900")
        first, second = normalize_response(batch, raw), normalize_response(batch, alternative)
        self.assertTrue(first.primitive_valid)
        self.assertTrue(second.primitive_valid)
        self.assertNotEqual(first.value["raw_response"]["sha256"], second.value["raw_response"]["sha256"])
        self.assertEqual(normalized_digest(first.value), normalized_digest(second.value))

    def test_rubric_and_option_order_change_exact_request_identity(self):
        from matter.semantic.questions import QuestionSpecification
        from matter.semantic.rendering import render_question
        packet = self.material.packet
        score = QuestionSpecification({**self.stage.specs["support"].value, "family": "synthetic.score", "primitive": "score",
            "criteria": ["No source support.", "Direct source support."]})
        rendered = render_question(score, packet.state, "score", source_manifest=packet.source_manifest)
        data = self.batch.value; data["questions"] = [rendered.question.value]
        before = execution_key(Batch(data), rendered=[rendered.value], precision=PrecisionProfile(), model_binding=self.binding, token=self.stage.token)
        changed = score.value; changed["criteria"].reverse()
        after_render = render_question(QuestionSpecification(changed), packet.state, "score", source_manifest=packet.source_manifest)
        data["questions"] = [after_render.question.value]
        self.assertNotEqual(before, execution_key(Batch(data), rendered=[after_render.value], precision=PrecisionProfile(), model_binding=self.binding, token=self.stage.token))
        choice = self.stage.specs["selection"]
        first = render_question(choice, packet.state, "selection", source_manifest=packet.source_manifest)
        data["questions"] = [first.question.value]
        before = execution_key(Batch(data), rendered=[first.value], precision=PrecisionProfile(), model_binding=self.binding, token=self.stage.token)
        changed = choice.value; changed["criteria"].reverse()
        second = render_question(QuestionSpecification(changed), packet.state, "selection", source_manifest=packet.source_manifest)
        data["questions"] = [second.question.value]
        self.assertNotEqual(before, execution_key(Batch(data), rendered=[second.value], precision=PrecisionProfile(), model_binding=self.binding, token=self.stage.token))

    def test_reuse_revocation_between_lookup_and_writer_refuses_without_new_call(self):
        first = self.run_attempt("original")
        original = self.service.read(first["execution"])
        observed = []
        def classify(**args):
            observed.append(args["as_of"])
            return {"status": "qualified" if len(observed) < 3 else "revoked", "certificate": component("changing-certificate")}
        reuse = self.run_attempt("revoked-at-writer", qualify=classify)
        self.assertEqual(reuse["status"], "refused", reuse)
        self.assertEqual(reuse["operation"]["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(len(observed), 3)
        self.assertEqual(len(self.stage.calls), 1)
        self.assertEqual(self.service.read(first["execution"]), original)

    def test_actual_stage_dispatch_claims_before_io_and_reuse_view_counts_zero_new_calls(self):
        from matter.semantic.stages import StageExecutor
        from matter.semantic.cache import attempt_ref
        from matter.budgets import _value
        prepared = self.material
        outer = self
        class ClaimCheckingAdapter:
            capabilities = outer.stage.spy.capabilities
            def execute(inner, batch):
                # This actual storage read happens INSIDE injected I/O: a real
                # started claim must already be durable and no tx may be held.
                row = outer.f.storage.get(attempt_ref(outer.f.storage.scope_id, batch.value["run_id"], batch.value["id"]))
                outer.assertEqual(_value(row, "semantic-execution-attempt")["phase"], "started")
                return outer.stage.spy.execute(batch)
        outcomes = []
        def dispatch(batch, *, rendered_questions, clock, precision):
            request = self.service.request(batch, packet=prepared.packet, rendered_questions=rendered_questions,
                token=self.stage.token, model_binding=self.binding, precision=precision)
            outcome = self.service.run(request, executor=ClaimCheckingAdapter(), token=self.stage.token,
                logical_request_id=batch.value["run_id"], attempt_id=batch.value["id"], allocation=self.stage.reservation)
            outcomes.append(outcome)
            return self.service.view_result(outcome, batch)
        runner = StageExecutor(questions=self.stage.questions, budgets=self.stage.budgets, executor=self.stage.spy,
            clock=lambda: self.f.now, dispatch=dispatch)
        plan = self.stage.plan([self.stage.stage("evidence", ["support", "contradiction"])])
        build = lambda stage, parents, **kw: prepared
        first = runner.execute(plan, prepare=build, reservation=self.stage.reservation, ceiling=self.stage.ceiling, run_id="stage-first")
        self.assertEqual(first.value["status"], "completed", first.value)
        self.assertEqual(first.value["resources"]["actual_invocations"], 1)
        second = runner.execute(plan, prepare=build, reservation=self.stage.reservation, ceiling=self.stage.ceiling, run_id="stage-second")
        self.assertEqual(second.value["status"], "completed", second.value)
        self.assertEqual(second.value["resources"]["actual_invocations"], 0)
        self.assertEqual(len(self.stage.calls), 1)
        self.assertEqual(len(outcomes), 2)
        first_event = self.service.read(outcomes[0]["execution"])
        self.assertEqual(self.service.read(outcomes[1]["execution"])["body"]["details"]["value"]["source_execution"], outcomes[0]["execution"])
        view = second.value["batches"][0]["result"]
        self.assertEqual(view["batch_digest"], Batch(second.value["batches"][0]["batch"]).digest)
        self.assertFalse(view["timing"]["called"])
        self.assertFalse(view["execution_observation"]["independent_trial"])
        self.assertEqual(view["execution_observation"]["source_execution"], outcomes[0]["execution"])
        self.assertEqual(self.service.read(outcomes[0]["execution"]), first_event)
        wrong = deepcopy(second.value["batches"][0]["batch"]); wrong["questions"].reverse()
        with self.assertRaises(ContractError): self.service.view_result(outcomes[1], Batch(wrong))

    def test_cached_child_rechecks_transitive_actual_parent_source_basis(self):
        from matter.semantic.packets import PreparedPacket
        raw = self.material.packet.value; raw["dependencies"].append(pin(self.f.subject))
        parent_request = self.service.request(self.batch, packet=PreparedPacket(raw, _prepared=True),
            rendered_questions=self.material.rendered_questions, token=self.stage.token, model_binding=self.binding)
        parent = self.run_attempt("parent", parent_request)
        child_packet = self.stage.packet(candidate=True)
        child_material = self.stage.material(self.stage.stage("child", ["recovery"]), [], packet=child_packet)
        data = self.batch.value; data.update(id="child", stage_id="child", state=child_packet.state,
            packet_digest=child_packet.digest, questions=[item.question.value for item in child_material.rendered_questions])
        batch = Batch(data)
        request = self.service.request(batch, packet=child_packet, rendered_questions=child_material.rendered_questions,
            token=self.stage.token, model_binding=self.binding)
        result = execute_batch(self.stage.spy, batch, clock=lambda: self.f.now)
        child = self.service.record(request, token=self.stage.token, logical_request_id="child-logical", attempt_id="child",
            phase="observed", result=result, parents=[parent["execution"]], command_id="child", idempotency_key="child")
        self.assertEqual(child["status"], "success", child)
        self.assertIsNotNone(self.service.lookup(request, token=self.stage.token, parents=[parent["execution"]]))
        narrow = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="assessment",
            targets=[entity_ref(self.stage.candidate)])
        with self.assertRaises(ContractError) as narrow_error:
            self.service.record(request, token=narrow, logical_request_id="narrow-child", attempt_id="narrow-child",
                phase="observed", result=result, parents=[parent["execution"]], command_id="narrow-child", idempotency_key="narrow-child")
        self.assertEqual(narrow_error.exception.code, "E_AUTHORITY_REQUIRED")
        self.f.rename_subject()
        with self.assertRaises(ContractError) as error:
            self.service.lookup(request, token=self.stage.token, parents=[parent["execution"]])
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.assertTrue(self.service.replay(child["body"]["execution"]).primitive_valid)
        from control_helpers import control_command
        from integration.helpers import _in_scope
        deny = _in_scope(control_command("deny-parent-source-history", self.f.authority, targets=[self.f.source],
            action="deny", capabilities=["read"], now=self.f.now), self.f.storage.scope_id)
        deny["actor"] = self.f.actor; deny["body"]["control"]["body"]["actor"] = self.f.actor
        self.assertEqual(self.f.controls.apply(self.f.controls.prepare(deny))["status"], "success")
        with self.assertRaises(ContractError) as history_error:
            self.service.read(child["body"]["execution"])
        self.assertEqual(history_error.exception.code, "E_AUTHORITY_REQUIRED")

    def test_recovering_existing_attempt_rejects_other_consumer_without_source_read_rights(self):
        from matter.authority import AuthorityPolicy
        from matter.controls import ControlService
        original = self.run_attempt("actor-a-attempt")
        actor_b = {**self.f.actor, "id": "different-consumer"}
        policy_b = AuthorityPolicy(self.f.storage.scope_id, actors=[actor_b], authorities=[pin(self.f.authority)],
            capabilities=["assessment"], targets=[entity_ref(self.stage.candidate)])
        controls_b = ControlService(self.f.storage, policy=policy_b, clock=lambda: self.f.now)
        token_b = controls_b.capture(actor=actor_b, authority=entity_ref(self.f.authority), capability="assessment",
            targets=[entity_ref(self.stage.candidate)])
        with self.f.storage.snapshot() as view:
            with self.assertRaises(ContractError):
                controls_b._view(view, actor=actor_b, authority=entity_ref(self.f.authority), capability="read",
                    targets=[entity_ref(self.f.source)], now=self.f.now)
        with self.assertRaises(ContractError) as refused:
            self.service.run(self.request, executor=self.stage.spy, token=token_b, logical_request_id="logical",
                attempt_id="actor-a-attempt", allocation=self.stage.reservation)
        self.assertEqual(refused.exception.code, "E_AUTHORITY_REQUIRED")
        self.assertNotIn(self.f.source["id"], str(refused.exception))
        self.assertEqual(self.run_attempt("actor-a-attempt")["execution"], original["execution"])
        self.assertEqual(len(self.stage.calls), 1)

    def test_recovering_attempt_rejects_changed_lineage_allocation_and_access_context(self):
        original = self.run_attempt("same-attempt")
        baseline = {"executor": self.stage.spy, "token": self.stage.token, "logical_request_id": "logical",
            "attempt_id": "same-attempt", "allocation": self.stage.reservation}
        changes = ({"parents": [original["execution"]]}, {"retry_of": original["execution"]},
                   {"allocation": {**self.stage.reservation, "scope_id": "foreign-scope"}},
                   {"allocation": {**self.stage.reservation, "revision": True}},
                   {"allocation": {**self.stage.reservation, "revision": float(self.stage.reservation["revision"])}},
                   {"access_context": {"different": "consumer"}})
        for changed in changes:
            with self.subTest(changed=tuple(changed)):
                with self.assertRaises(ContractError) as refused:
                    self.service.run(self.request, **{**baseline, **changed})
                self.assertEqual(refused.exception.code, "E_AUTHORITY_REQUIRED" if "access_context" in changed else "E_IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.run_attempt("same-attempt")["execution"], original["execution"])
        self.assertEqual(len(self.stage.calls), 1)

    def test_reused_retry_recovers_exact_original_lineage_after_cancellation(self):
        from control_helpers import control_command
        from integration.helpers import _in_scope
        first = self.run_attempt("original")
        reused = self.run_attempt("requested-retry", retry_of=first["execution"])
        self.assertEqual(reused["status"], "reused", reused)
        metadata = self.service.read(reused["execution"])["body"]["details"]["value"]
        self.assertEqual(metadata["retry_of"], first["execution"])
        self.assertEqual(metadata["source_execution"], first["execution"])
        self.assertEqual(self.run_attempt("requested-retry", retry_of=first["execution"])["execution"], reused["execution"])
        with self.assertRaises(ContractError) as changed:
            self.run_attempt("requested-retry")
        self.assertEqual(changed.exception.code, "E_IDEMPOTENCY_CONFLICT")
        stop = _in_scope(control_command("cancel-recovered-attempt", self.f.authority, targets=[self.f.source],
            action="cancel", now=self.f.now), self.f.storage.scope_id)
        stop["actor"] = self.f.actor; stop["body"]["control"]["body"]["actor"] = self.f.actor
        self.assertEqual(self.f.controls.apply(self.f.controls.prepare(stop))["status"], "success")
        historical = self.run_attempt("requested-retry", retry_of=first["execution"])
        self.assertEqual(historical["execution"], reused["execution"])
        self.assertFalse(historical["dispatched"])
        self.assertEqual(self.run_attempt("original")["execution"], first["execution"])
        self.assertEqual(len(self.stage.calls), 1)

    def test_same_attempt_id_in_distinct_logical_requests_has_distinct_reuse_commands(self):
        first = self.run_attempt("source")
        records = []
        for logical in ("B", "C"):
            outcome = self.service.run(self.request, executor=self.stage.spy, token=self.stage.token,
                logical_request_id=logical, attempt_id="1", allocation=self.stage.reservation)
            self.assertEqual(outcome["status"], "reused", outcome)
            records.append(outcome["execution"])
            metadata = self.service.read(outcome["execution"])["body"]["details"]["value"]
            self.assertEqual(metadata["logical_request_id"], logical)
            self.assertEqual(metadata["source_execution"], first["execution"])
            again = self.service.run(self.request, executor=self.stage.spy, token=self.stage.token,
                logical_request_id=logical, attempt_id="1", allocation=self.stage.reservation)
            self.assertEqual(again["execution"], outcome["execution"])
        self.assertNotEqual(*records)
        self.assertEqual(len(self.stage.calls), 1)

    def test_provider_shadow_missing_dispatcher_creates_no_claim_then_allows_guarded_attempt_and_cache(self):
        from matter.semantic.contracts import Capabilities
        from matter.semantic.cache import attempt_ref
        request = deepcopy(self.request); request["batch"]["context"]["mode"] = "provider_shadow"
        original_allocation = self.f.storage.get(self.stage.reservation)
        with self.assertRaises(ContractError) as missing:
            self.service.run(request, executor=self.stage.spy, token=self.stage.token, logical_request_id="shadow",
                attempt_id="1", allocation=self.stage.reservation)
        self.assertEqual(missing.exception.code, "E_AUTHORITY_REQUIRED")
        with self.assertRaises(StorageError) as absent:
            self.f.storage.get(attempt_ref(self.f.storage.scope_id, "shadow", "1"))
        self.assertEqual(absent.exception.code, "E_NOT_FOUND")
        with self.f.storage.snapshot() as view:
            self.assertEqual(view.watchers(self.service._watch(self.stage.reservation)), [])
        self.assertEqual(self.f.storage.get(self.stage.reservation), original_allocation)
        self.assertEqual(len(self.stage.calls), 0)
        outer = self
        class ShadowFixture:
            capabilities = Capabilities({**outer.stage.spy.capabilities.value, "modes": ["provider_shadow"]})
            def execute(inner, batch): return outer.stage.spy.execute(batch)
        def guarded(**args):
            return execute_batch(args["executor"], args["batch"], clock=args["clock"], precision=args["precision"])
        first = self.service.run(request, executor=ShadowFixture(), token=self.stage.token, logical_request_id="shadow",
            attempt_id="1", allocation=self.stage.reservation, dispatch=guarded)
        self.assertEqual(first["status"], "completed", first)
        # Existing history and a new cache read do no I/O and need no dispatcher.
        historical = self.service.run(request, executor=ShadowFixture(), token=self.stage.token, logical_request_id="shadow",
            attempt_id="1", allocation=self.stage.reservation)
        self.assertEqual(historical["execution"], first["execution"])
        reused = self.service.run(request, executor=ShadowFixture(), token=self.stage.token, logical_request_id="other-shadow",
            attempt_id="1", allocation=self.stage.reservation)
        self.assertEqual(reused["status"], "reused", reused)
        self.assertEqual(len(self.stage.calls), 1)

    def test_invalid_durable_journal_caps_and_phase_refuse_before_budget_dispatch(self):
        from matter.semantic.cache import attempt_ref
        from integration.helpers import create_command
        first = self.run_attempt("source")
        address = attempt_ref(self.f.storage.scope_id, "logical", "source")
        original = self.f.storage.get(address)
        valid = deepcopy(original["value"])
        mutations = [({"calls": -5, "elapsed_ms": -100000}, "completed"), ({"calls": "1"}, "completed"),
            ({"calls": True}, "completed"), ({"unrecognized": 0}, "completed"),
            ({key: value for key, value in valid["value"]["caps"].items() if key != "calls"}, "started"),
            ({}, "started"), (valid["value"]["caps"], "not-a-phase")]
        def privileged_fixture_write(payload, suffix):
            # Deliberately bypass the private schema constructor to simulate a
            # malformed imported journal through the real generic storage port.
            current = self.f.storage.get(address)
            command = create_command("journal-" + suffix, "journal-subject-" + suffix, scope_id=self.f.storage.scope_id,
                expected_revisions=[pin(current)])
            def handler(tx):
                tx.put_projection(address, payload, watch_keys=current["watch_keys"])
                subject = tx.insert(tx.command["body"]["matter"])
                return tx.success("created", {"matter": pin(subject)})
            self.assertEqual(self.f.storage.execute(command, handler)["status"], "success")
        for index, (caps, phase) in enumerate(mutations):
            with self.subTest(index=index):
                malformed = deepcopy(valid); malformed["value"].update(caps=caps, phase=phase)
                privileged_fixture_write(malformed, "bad-" + str(index))
                with self.assertRaises(ContractError) as refused:
                    self.run_attempt("not-dispatched-" + str(index), reuse=False)
                self.assertEqual(refused.exception.code, "E_SCHEMA_INVALID")
                self.assertEqual(len(self.stage.calls), 1)
                privileged_fixture_write(valid, "restore-" + str(index))
        self.assertTrue(self.service.replay(first["execution"]).primitive_valid)
