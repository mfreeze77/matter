"""MAT-032 injected HTTP/SDK-wire conformance; zero live provider requests."""

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import json
import os
import socket
import subprocess
import sys
from threading import Barrier, Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from matter.canonical import canonical_bytes, loads, source_digest
from matter.semantic import Batch, PrecisionProfile, execute_batch, normalize_response
from matter.semantic.contracts import ExecutionFault
from matter.semantic.providers.typesafe import (ADAPTER_VERSION, ENDPOINT, HTTPResponse,
    TypeSafeConfigurationError, TypeSafeHTTPExecutor, _NoRedirect)
from matter.semantic.receipts import normalized_digest
from semantic import test_contracts as core_fixture


KEY = "SYNTHETIC-ONLY-KEY-DO-NOT-PERSIST"
MODEL = "Jev-synthetic-fixed-1"


def batch(*primitives, change=None):
    original = core_fixture.make_batch(*primitives).value
    original["context"].update(provider="typesafe", transport="http", requested_model=MODEL,
        adapter_version=ADAPTER_VERSION, mode="provider_shadow")
    if change:
        change(original)
    return Batch(original)


def native_wire(request, *, model=MODEL):
    """Hand-declared native numeric tokens; never build numeric fixtures from floats."""
    answers = []
    for question in request.value["questions"]:
        kind = question["primitive"]
        if kind == "proposition_probability":
            value = b'{"type":"noul","noul":0.1234567890123456789}'
        elif kind == "choice":
            names = [item["id"] for item in question["criteria"]]
            probabilities = b",".join(json.dumps(name).encode() + b":" + (b"0.75" if index == 0 else b"0.25")
                for index, name in enumerate(names))
            value = b'{"type":"choice","choice":' + json.dumps(names[0]).encode() + b',"probabilities":{' + probabilities + b'},"confidence":0.50000}'
        else:
            legend = json.dumps(dict(enumerate(question["criteria"])), ensure_ascii=False, separators=(",", ":")).encode()
            if len(question["criteria"]) == 3:
                probabilities, score = b'{"0":1.25e-1,"1":0.5,"2":0.375}', b"1.25000"
            else:
                probabilities = b"{" + b",".join(json.dumps(str(index)).encode() + b":" + (b"0.5" if index < 2 else b"0")
                    for index in range(len(question["criteria"]))) + b"}"
                score = b"0.5"
            value = b'{"type":"score","score":' + score + b',"legend":' + legend + b',"probabilities":' + probabilities + b',"confidence":0.1500000000000000000001}'
        answers.append(json.dumps(question["id"]).encode() + b":" + value)
    return b'{"model":' + json.dumps(model).encode() + b',"answers":{' + b",".join(answers) + b'},"usage":{"input_tokens":12,"output_tokens":3}}'


class TypeSafeAdapterTests(unittest.TestCase):
    def executor(self, response=None, *, transport=None, **configuration):
        self.observed = []
        def injected(**kwargs):
            # Deliberately retain only public synthetic request-body evidence.
            self.observed.append({key: kwargs[key] for key in ("body", "timeout", "max_response_bytes")})
            return response
        values = {"model": MODEL, "api_key": KEY, "timeout": 30, "max_calls": 4,
                  "transport": transport or injected, "clock": lambda: core_fixture.instant(0)}
        values.update(configuration)
        return TypeSafeHTTPExecutor(**values)

    def execute(self, executor, request, *, precision=None):
        return execute_batch(executor, request, clock=lambda: core_fixture.instant(0), precision=precision or executor.precision_profile)

    def test_native_projection_preserves_all_three_meanings_and_ordered_request_criteria(self):
        request = batch("choice", "score", "proposition_probability")
        raw = native_wire(request)
        executor = self.executor(HTTPResponse(200, raw))
        result = self.execute(executor, request)
        self.assertTrue(result.primitive_valid, result.value)
        wire_request = json.loads(self.observed[0]["body"])
        self.assertEqual(wire_request["model"], MODEL)
        self.assertEqual(list(wire_request["questions"]), ["q0", "q1", "q2"])
        self.assertEqual(list(wire_request["questions"]["q0"]["criteria"]), ["support", "oppose"])
        self.assertEqual(wire_request["questions"]["q1"]["criteria"], request.value["questions"][1]["criteria"])
        self.assertEqual(wire_request["questions"]["q2"]["type"], "noul")
        self.assertEqual(wire_request["questions"]["q2"]["criteria"], request.value["questions"][2]["criteria"])
        heads = result.value["diagnostics"]
        self.assertEqual(heads[0]["answer"]["choice"], "support")
        self.assertEqual(heads[1]["answer"]["score"], "1.25")
        self.assertEqual(heads[2]["answer"]["probability"], "0.1234567890123456789")
        self.assertNotIn("confidence", heads[2]["answer"])
        self.assertEqual(base64.b64decode(result.value["native_response"]["base64"]), raw)
        self.assertIsNone(result.value["instrumentation"]["attempt_id"])
        self.assertIsNone(result.value["instrumentation"]["logical_request_id"])
        self.assertEqual(result.value["usage"]["value"]["input_tokens"], 12)
        self.assertIsNone(result.value["usage"]["value"]["total_tokens"])
        self.assertIsNone(result.value["cost"]["value"])
        self.assertFalse(result.value["admission"]["consequential_use"])

    def test_exact_native_numeric_lexemes_survive_normalization_core_encoding_and_hashing(self):
        request = batch("choice", "score", "proposition_probability")
        raw = native_wire(request)
        result = self.execute(self.executor(HTTPResponse(200, raw)), request)
        neutral = base64.b64decode(result.value["raw_response"]["base64"])
        self.assertIn(b"0.1234567890123456789", neutral)
        self.assertIn(b"1.25e-1", neutral)
        self.assertIn(b"1.25000", neutral)
        self.assertIn(b"0.1500000000000000000001", neutral)
        self.assertEqual(result.value["native_response"]["sha256"], source_digest(raw))
        self.assertNotEqual(source_digest(neutral), source_digest(raw))
        again = normalize_response(request, neutral, precision=PrecisionProfile())
        self.assertEqual(normalized_digest(result.value), normalized_digest(again.value))
        self.assertEqual(loads(result.canonical), result.value)
        self.assertEqual(canonical_bytes(loads(result.canonical)), result.canonical)
        score = result.value["diagnostics"][1]["answer"]
        self.assertEqual(score["confidence"], "0.1500000000000000000001")
        self.assertEqual(score["score_residual"], "0")
        self.assertEqual(score["distribution_residual"], "0")

    def test_sdk_integer_score_maps_are_ignored_in_favor_of_original_wire(self):
        request = batch("score", "proposition_probability")
        raw = native_wire(request)
        sdk = SimpleNamespace(raw_http_response=SimpleNamespace(content=raw, status_code=200),
            scores={"q0": SimpleNamespace(score=1.25, probabilities={0: 0.125, 1: 0.5, 2: 0.375})},
            nouls={"q1": SimpleNamespace(noul=0.12345678901234568)})
        result = self.execute(self.executor(sdk), request)
        self.assertTrue(result.primitive_valid, result.value)
        self.assertEqual(result.value["diagnostics"][1]["answer"]["probability"], "0.1234567890123456789")
        self.assertEqual(result.value["diagnostics"][0]["answer"]["probabilities"]["0"], "0.125")
        rounded = SimpleNamespace(scores=sdk.scores, nouls=sdk.nouls)
        result = self.execute(self.executor(rounded), request)
        self.assertFalse(result.value["admission"]["exact_numeric"])
        self.assertEqual(result.value["faults"], [{"code": "precision_unavailable", "path": []}])
        self.assertFalse(result.primitive_valid)

    def test_native_quoted_numbers_booleans_and_shape_spoofing_do_not_silently_qualify(self):
        request = batch("proposition_probability", "proposition_probability")
        raw = native_wire(request)
        original = b'"noul":0.1234567890123456789'
        replacements = [b'"noul":"0.1234567890123456789"', b'"noul":true',
            b'"probability":0.1234567890123456789', b'"noul":0.1234567890123456789,"confidence":0.9',
            b'"noul":0.1234567890123456789,"id":"q1"', b'"noul":0.1234567890123456789,"primitive":"choice"']
        for replacement in replacements:
            with self.subTest(replacement=replacement):
                malformed = raw.replace(original, replacement, 1)
                result = self.execute(self.executor(HTTPResponse(200, malformed)), request)
                self.assertFalse(result.primitive_valid, result.value)
                self.assertEqual(result.value["diagnostics"][0]["status"], "invalid")
                self.assertEqual(result.value["diagnostics"][1]["status"], "valid")
                self.assertEqual(base64.b64decode(result.value["native_response"]["base64"]), malformed)

    def test_missing_unexpected_duplicate_and_unknown_type_answers_refuse_whole_batch(self):
        request = batch("proposition_probability", "proposition_probability")
        raw = native_wire(request)
        cases = [raw.replace(b'"q1":', b'"unrequested":'),
                 raw.replace(b'"q1":', b'"q0":'),
                 raw.replace(b'"type":"noul"', b'"type":"box","primitive":"proposition_probability"', 1),
                 raw.replace(b'"type":"noul"', b'"type":{}', 1)]
        for malformed in cases:
            result = self.execute(self.executor(HTTPResponse(200, malformed)), request)
            self.assertFalse(result.primitive_valid, result.value)
            self.assertFalse(result.value["admission"]["consequential_use"])

    def test_response_cannot_select_criteria_or_widen_trusted_precision(self):
        request = batch("choice", "score")
        raw = native_wire(request)
        for malformed in (raw[:-1] + b',"precision_profile":{"probability_quantum":1}}',
                raw.replace(b'"oppose":0.25', b'"oppose":0.24'),
                raw.replace(b'"No qualifying source."', b'"Replacement meaning."')):
            result = self.execute(self.executor(HTTPResponse(200, malformed)), request)
            self.assertFalse(result.primitive_valid, result.value)
            self.assertEqual(result.value["precision_profile"], PrecisionProfile().value)

    def test_timeout_rate_limit_and_missing_model_each_consume_one_attempt_without_retries(self):
        request = batch()
        def timeout(**_):
            raise TimeoutError("SYNTHETIC-SECRET-MUST-NOT-LEAK")
        for transport, response, code, status in ((timeout, None, "timeout", "timed_out"),
                (None, HTTPResponse(429, b'{"error":"synthetic rate limit"}'), "rate_limited", "failed"),
                (None, HTTPResponse(200, native_wire(request).replace(b'"model":"' + MODEL.encode() + b'",', b'')), "model_unresolved", "failed")):
            with self.subTest(code=code):
                executor = self.executor(response, transport=transport)
                result = self.execute(executor, request)
                self.assertEqual(executor.calls_made, 1)
                self.assertEqual(result.value["execution_status"], status)
                self.assertEqual(result.value["faults"], [{"code": code, "path": []}])
                self.assertFalse(result.value["admission"]["consequential_use"])
                self.assertNotIn("SECRET", result.canonical.decode())
                self.assertIsNone(result.value["cost"]["value"])

    def test_local_call_limit_is_shared_across_threads_and_context_model_is_explicit(self):
        request = batch()
        lock, observed, barrier = Lock(), [], Barrier(8)
        def transport(**kwargs):
            with lock:
                observed.append(len(kwargs["body"]))
            return HTTPResponse(200, native_wire(request))
        executor = self.executor(transport=transport, max_calls=2)
        def call(_):
            barrier.wait(timeout=10)
            return self.execute(executor, request)
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(call, range(8)))
        self.assertEqual(len(observed), 2)
        self.assertEqual(executor.calls_made, 2)
        self.assertEqual(sum(result.primitive_valid for result in results), 2)
        other = batch(change=lambda value: value["context"].update(requested_model="another-explicit-model"))
        executor = self.executor(HTTPResponse(200, native_wire(request)))
        self.assertFalse(self.execute(executor, other).primitive_valid)
        self.assertEqual(executor.calls_made, 0)

    def test_native_score_bound_deadline_and_wire_budgets_fail_before_or_after_actual_boundary(self):
        too_many = batch("score", change=lambda value: value["questions"][0].update(criteria=["Level " + str(i) for i in range(11)]))
        executor = self.executor(HTTPResponse(200, b'{}'))
        self.assertFalse(self.execute(executor, too_many).primitive_valid)
        self.assertEqual(executor.calls_made, 0)
        expired = batch(change=lambda value: value["context"].update(deadline=core_fixture.instant(0)))
        self.assertEqual(self.execute(executor, expired).value["execution_status"], "timed_out")
        self.assertEqual(executor.calls_made, 0)
        request = batch()
        executor = self.executor(HTTPResponse(200, native_wire(request)), max_response_bytes=64)
        result = self.execute(executor, request)
        self.assertEqual(result.value["execution_status"], "budget_exhausted")
        self.assertEqual(executor.calls_made, 1)
        self.assertNotIn("native_response", result.value)
        executor = self.executor(HTTPResponse(200, b'{}'), max_request_bytes=16)
        self.assertEqual(self.execute(executor, request).value["execution_status"], "budget_exhausted")
        self.assertEqual(executor.calls_made, 0)

    def test_response_credential_echo_and_exception_text_are_never_persisted(self):
        request = batch()
        escaped = b"\\u0053" + KEY[1:].encode()
        for raw in (b'{"error":"' + KEY.encode() + b'"}', b'{"error":"' + escaped + b'"}', b"not-json " + KEY.encode()):
            result = self.execute(self.executor(HTTPResponse(500, raw)), request)
            self.assertFalse(result.primitive_valid)
            self.assertNotIn("native_response", result.value)
            self.assertNotIn(KEY, result.canonical.decode())
        def secret_error(**_):
            raise URLError(KEY)
        executor = self.executor(transport=secret_error)
        with self.assertRaises(ExecutionFault) as fault:
            executor.execute(request)
        self.assertNotIn(KEY, str(fault.exception))
        self.assertIsNone(fault.exception.__context__)
        self.assertIsNone(fault.exception.__cause__)

    def test_selected_configuration_is_required_and_never_reads_dotenv_or_adds_retries(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TypeSafeConfigurationError) as missing:
                TypeSafeHTTPExecutor(model=MODEL, timeout=1, max_calls=1, transport=lambda **_: None)
        self.assertIn("TYPESAFE_API_KEY", str(missing.exception))
        for changes in ({"model": ""}, {"timeout": True}, {"timeout": float("inf")}, {"max_calls": True},
                {"max_retries": 1}, {"api_key": "SYNTHETIC\r\nHEADER"}):
            with self.subTest(changes=changes):
                with self.assertRaises(TypeSafeConfigurationError):
                    self.executor(**changes)

    def test_offline_mode_does_not_dispatch_selected_http_adapter(self):
        request = batch(change=lambda value: value["context"].update(mode="recorded_replay"))
        executor = self.executor(HTTPResponse(200, native_wire(request)))
        result = self.execute(executor, request)
        self.assertEqual(result.value["execution_status"], "unsupported")
        self.assertEqual(executor.calls_made, 0)

    def test_stdlib_path_has_fixed_endpoint_disables_redirects_and_bounds_reads(self):
        request = batch()
        observed = []
        class Opener:
            def open(inner, sent, *, timeout):
                observed.append((sent.full_url, sent.method, timeout))
                raise HTTPError(ENDPOINT, 302, "SYNTHETIC-SECRET", {"Location": "https://not-followed.invalid/" + KEY},
                    BytesIO(b'{"error":"redirect refused"}'))
        with patch("matter.semantic.providers.typesafe.build_opener", return_value=Opener()) as build:
            executor = TypeSafeHTTPExecutor(model=MODEL, api_key=KEY, timeout=30, max_calls=1, clock=lambda: core_fixture.instant(0))
            result = self.execute(executor, request)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0], ENDPOINT)
        self.assertEqual(observed[0][1], "POST")
        self.assertEqual(observed[0][2], 10)
        self.assertTrue(any(isinstance(handler, _NoRedirect) for handler in build.call_args.args))
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, None, {}, "https://not-followed.invalid"))
        self.assertFalse(result.primitive_valid)
        self.assertNotIn(KEY, result.canonical.decode())

    def test_core_and_provider_imports_need_no_sdk_credential_or_socket(self):
        script = """import os, socket, sys
class NoCredentials(dict):
    def get(self, name, *args):
        if name == 'TYPESAFE_API_KEY': raise AssertionError('credential read during import')
        return super().get(name, *args)
os.environ = NoCredentials(os.environ)
def denied(*args, **kwargs): raise AssertionError('network access during import')
socket.create_connection = denied
socket.socket.connect = denied
import matter.semantic
assert not any(name.startswith('typesafe_sdk') for name in sys.modules)
import matter.semantic.providers.typesafe
assert not any(name.startswith('typesafe_sdk') for name in sys.modules)
"""
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


class DurableTypeSafeTests(unittest.TestCase):
    """Actual MAT-020/030/031/072 ports, with injected synthetic HTTP only."""

    def setUp(self):
        from matter.access import AccessService, HostAccessPolicy
        from matter.semantic.receipts import ExecutionReceiptStore
        from matter.semantic.qualification import SemanticQualificationService
        from matter.semantic.questions import QuestionRegistry, QuestionSpecification
        from matter.storage import pin
        from rule_helpers import component, LATE
        from semantic import test_stages
        self.stage = test_stages.StageTests(methodName="runTest")
        self.stage.setUp()
        self.addCleanup(self.stage.doCleanups)
        self.stage.reserve(calls=4)
        self.f = self.stage.f
        score = self.stage.spec("severity").value
        score.update(primitive="score", criteria=["No qualifying source.", "Some qualifying evidence.", "Complete qualifying evidence."])
        self.stage.specs["severity"] = QuestionSpecification(score)
        self.stage.questions = QuestionRegistry(list(self.stage.specs.values()))
        audience, provider = component("typesafe-audience"), component("typesafe-provider")
        policy = HostAccessPolicy(scope_id=self.f.storage.scope_id, audiences=[audience],
            providers=[{"reference": provider, "provider": "typesafe", "transport": "http"}],
            grants=[{"reference": pin(record), "audiences": [audience], "providers": [provider]}
                for record in (self.f.subject, self.f.source, self.stage.candidate)])
        self.access = AccessService(policy=policy, controls=self.f.controls, current_read=self.f.storage.snapshot)
        with self.f.storage.snapshot() as view:
            self.context = self.access.capture(view, token=self.stage.token, audience=audience, provider=provider,
                references=[pin(record) for record in (self.f.subject, self.f.source, self.stage.candidate)])
        packet = self.stage.packet(access=self.access, access_context=self.context)
        self.material = self.stage.material(self.stage.stage("typed", ["support", "selection", "severity"]), [], packet=packet,
            access=self.access, access_context=self.context)
        deadline = deepcopy(self.f.now)
        deadline["value"] = "2026-10-10T12:00:01Z"
        self.batch = Batch({"schema_version": "1.0", "id": "typed-batch", "run_id": "typed-run", "stage_id": "typed",
            "scope_id": self.f.storage.scope_id, "state": packet.state, "packet_digest": packet.digest,
            "questions": [item.question.value for item in self.material.rendered_questions],
            "context": {"provider": "typesafe", "transport": "http", "requested_model": MODEL,
                "adapter_version": ADAPTER_VERSION, "mode": "provider_shadow", "deadline": deadline,
                "max_request_bytes": 65536, "max_response_bytes": 65536}})
        self.receipts = ExecutionReceiptStore(self.f.storage, payloads=self.f.payloads, controls=self.f.controls,
            clock=lambda: self.f.now, questions=self.stage.questions, budgets=self.stage.budgets, access=self.access)
        self.qualification = SemanticQualificationService(self.f.storage, controls=self.f.controls,
            receipts=self.receipts, reviewers=[component("synthetic-reviewer")], clock=lambda: self.f.now)
        self.request = self.receipts.request(self.batch, packet=packet, rendered_questions=self.material.rendered_questions,
            token=self.stage.token, model_binding={"model": MODEL, "resolution": component("synthetic-fixed-resolution")},
            access_context=self.context)
        self.dispatches = 0

    def dispatch(self, **args):
        from matter.assessments import FrozenAssessmentView
        from matter.budgets import _Reads
        with self.f.storage.snapshot() as view:
            reads = _Reads(view, self.f.storage.scope_id)
            self.access.require_packet(reads, self.context, args["batch"].value["state"])
            frozen = FrozenAssessmentView({"records": list(reads.records.values()), "absent": list(reads.absent.values()),
                                           "watch_queries": reads.queries})
        self.dispatches += 1
        # The read transaction has CLOSED before the actual egress boundary.
        return self.access.dispatch(frozen, self.context, args["batch"], args["executor"],
            rendered_questions=self.material.rendered_questions, clock=args["clock"], precision=args["precision"])

    def run_attempt(self, identity, transport):
        executor = TypeSafeHTTPExecutor(model=MODEL, api_key=KEY, timeout=30, max_calls=1,
            transport=transport, clock=lambda: self.f.now)
        value = self.receipts.run(self.request, executor=executor, token=self.stage.token,
            logical_request_id="typed-logical", attempt_id=identity, allocation=self.stage.reservation,
            access_context=self.context, dispatch=self.dispatch, reuse=False)
        self.assertEqual(value["status"], "completed", value)
        self.assertEqual(executor.calls_made, 1)
        return value, executor

    def assert_unqualified(self, observation):
        from rule_helpers import component
        with self.f.storage.snapshot() as view:
            decision = self.qualification.inspect(view, observation["execution"], question_id="support", certificate=None,
                domain_scope=component("synthetic-provider-domain"), measure={"name": "probability", "unit": "probability"},
                token=self.stage.token)
        self.assertFalse(decision.eligible)
        self.assertFalse(decision.value["host_authority_granted"])
        self.assertFalse(observation["result"].value["admission"]["consequential_use"])

    def test_guarded_actual_attempt_preserves_native_and_neutral_payloads_hashes_and_exact_replay(self):
        from integration.helpers import create_command, create_matter
        from matter.storage import SQLiteStore
        observed = []
        native = native_wire(self.batch)
        def injected(**arguments):
            observed.append(arguments["timeout"])
            # A real separate writer proves no read transaction spans HTTP.
            with SQLiteStore(self.f.database, scope_id=self.f.storage.scope_id) as writer:
                command = create_command("during-typesafe-boundary", "synthetic-independent-matter", scope_id=writer.scope_id)
                self.assertEqual(writer.execute(command, create_matter)["status"], "success")
            return HTTPResponse(200, native)
        value, executor = self.run_attempt("exact", injected)
        self.assertTrue(value["result"].primitive_valid, value)
        self.assertEqual(self.dispatches, 1)
        self.assertEqual(observed, [1])
        stored = self.receipts.read(value["execution"])["body"]["details"]["value"]
        replayed = self.receipts.replay(value["execution"])
        self.assertEqual(self.f.payloads.read(stored["native_response"]).data, native)
        neutral = self.f.payloads.read(stored["neutral_response"]).data
        self.assertIn(b"0.1234567890123456789", neutral)
        self.assertIn(b"1.25000", neutral)
        self.assertIn(b"1.25e-1", neutral)
        self.assertIn(b"0.1500000000000000000001", neutral)
        self.assertEqual(base64.b64decode(replayed.value["native_response"]["base64"]), native)
        self.assertEqual(base64.b64decode(replayed.value["raw_response"]["base64"]), neutral)
        self.assertEqual(stored["normalized_digest"], normalized_digest(replayed.value))
        self.assertEqual(stored["logical_request_id"], "typed-logical")
        self.assertEqual(stored["attempt_id"], "exact")
        self.assertIsNone(stored["result"]["instrumentation"]["attempt_id"])
        self.assertEqual(replayed.value["diagnostics"][0]["answer"]["probability"], "0.1234567890123456789")
        self.assertEqual(replayed.value["diagnostics"][2]["answer"]["confidence"], "0.1500000000000000000001")
        self.assertEqual(replayed.value["diagnostics"][2]["answer"]["score_residual"], "0")
        self.assert_unqualified(value)
        recovered = self.receipts.run(self.request, executor=executor, token=self.stage.token,
            logical_request_id="typed-logical", attempt_id="exact", allocation=self.stage.reservation,
            access_context=self.context, dispatch=self.dispatch, reuse=False)
        self.assertEqual(recovered["execution"], value["execution"])
        self.assertFalse(recovered["dispatched"])
        self.assertEqual(executor.calls_made, 1)
        self.assertEqual(self.dispatches, 1)

    def test_timeout_rate_missing_model_and_float_only_sdk_are_recorded_and_remain_unqualified(self):
        def timeout(**_):
            raise TimeoutError("SYNTHETIC-UNPERSISTED-EXCEPTION")
        without_model = native_wire(self.batch).replace(b'"model":"' + MODEL.encode() + b'",', b'')
        transports = [("timeout", timeout),
            ("rate_limited", lambda **_: HTTPResponse(429, b'{"error":"synthetic rate limit"}')),
            ("model_unresolved", lambda **_: HTTPResponse(200, without_model)),
            ("precision_unavailable", lambda **_: SimpleNamespace(nouls={"support": 0.12345678901234568}))]
        for code, transport in transports:
            with self.subTest(code=code):
                value, _ = self.run_attempt(code, transport)
                self.assertEqual(value["result"].value["faults"], [{"code": code, "path": []}])
                history = self.receipts.history("typed-logical", code)
                self.assertEqual([item["body"]["details"]["value"]["phase"] for item in history], ["started", "completed"])
                stored = self.receipts.read(value["execution"])["body"]["details"]["value"]
                self.assertIsNone(stored["retry_of"])
                self.assertEqual(stored["result"]["timing"]["called"], True)
                self.assertIsNone(stored["result"]["cost"]["value"])
                self.assertNotIn(KEY, str(stored))
                self.assert_unqualified(value)
        self.assertEqual(self.dispatches, 4)
        forbidden = TypeSafeHTTPExecutor(model=MODEL, api_key=KEY, timeout=30, max_calls=1,
            transport=lambda **_: self.fail("Exhausted durable allocation dispatched HTTP."), clock=lambda: self.f.now)
        fifth = self.receipts.run(self.request, executor=forbidden, token=self.stage.token,
            logical_request_id="typed-logical", attempt_id="fifth", allocation=self.stage.reservation,
            access_context=self.context, dispatch=self.dispatch, reuse=False)
        self.assertEqual(fifth["status"], "refused", fifth)
        self.assertEqual(fifth["operation"]["error"]["code"], "E_BUDGET_EXHAUSTED")
        self.assertEqual(forbidden.calls_made, 0)
        self.assertEqual(self.dispatches, 4)


if __name__ == "__main__":
    unittest.main()
