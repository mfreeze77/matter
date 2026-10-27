"""Behavioral conformance for MAT-026; no providers or private data."""

from copy import deepcopy
from decimal import localcontext
import json
import os
import subprocess
import sys
import unittest

from matter.canonical import canonical_bytes, canonical_digest, loads, source_digest
from matter.contracts import ContractError
from matter.semantic import (
    Batch, Capabilities, FixtureExecutor, PrecisionProfile, Question, RawExecution,
    execute_batch, normalize_response,
)


def instant(second):
    return {"state": "known", "value": f"2026-10-27T01:00:{second:02}Z", "precision": "second"}


def make_question(primitive="proposition_probability", identity="claim", state=None):
    state = {"source": "Synthetic known fixture."} if state is None else state
    criteria = {"true": "The source supports the proposition.", "false": "The source does not support it."}
    if primitive == "choice":
        criteria = [{"id": "support", "description": "The passage supports the claim."},
                    {"id": "oppose", "description": "The passage opposes the claim."}]
    elif primitive == "score":
        criteria = ["No qualifying source.", "Some qualifying evidence.", "Complete qualifying evidence."]
    return {"id": identity, "family": "synthetic:evidence", "revision": "1.0", "primitive": primitive,
            "instructions": "Does the synthetic source support the declared proposition?", "criteria": criteria,
            "specification_digest": "a" * 64, "rendering_revision": "1.0",
            "packet_digest": canonical_digest(state, "matter.semantic.packet.v1"), "bound_ids": ["synthetic:claim"]}


def make_batch(*primitives, change=None):
    state = {"source": "Synthetic known fixture."}
    value = {"schema_version": "1.0", "id": "synthetic-batch", "scope_id": "synthetic-scope",
             "run_id": "synthetic-run", "stage_id": "synthetic-stage", "state": state,
             "packet_digest": canonical_digest(state, "matter.semantic.packet.v1"),
             "questions": [make_question(kind, f"q{index}", state) for index, kind in enumerate(primitives or ("proposition_probability",))],
             "context": {"provider": "synthetic", "transport": "fixture", "requested_model": "recording-v1",
                         "adapter_version": "1.0", "mode": "offline_fixture", "deadline": instant(10),
                         "max_request_bytes": 65536, "max_response_bytes": 65536}}
    if change:
        change(value)
    return Batch(value)


def capabilities(**changes):
    value = {"provider": "synthetic", "transport": "fixture", "adapter_version": "1.0",
             "primitives": ["choice", "score", "proposition_probability"], "modes": ["offline_fixture"],
             "max_questions": 128, "max_request_bytes": 65536, "max_response_bytes": 65536}
    value.update(changes)
    return Capabilities(value)


def answer(question):
    value = {"id": question["id"], "primitive": question["primitive"]}
    if value["primitive"] == "proposition_probability":
        value["probability"] = "0.1234567890123456789"
    elif value["primitive"] == "choice":
        value.update(choice="support", probabilities={"support": "0.75", "oppose": "0.25"}, confidence="0.5")
    else:
        value.update(score="1.25", probabilities={"0": "0.125", "1": "0.5", "2": "0.375"},
                     legend=dict(enumerate(question["criteria"])), confidence="0.15")
        value["legend"] = {str(key): item for key, item in value["legend"].items()}
    return value


def response(batch, *, change=None):
    value = {"answers": [answer(q) for q in batch.value["questions"]], "resolved_model": "recording-v1"}
    if change:
        change(value)
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


class ContractTests(unittest.TestCase):
    def test_all_variants_serialize_and_remain_separate(self):
        batch = make_batch("choice", "score", "proposition_probability")
        result = normalize_response(batch, response(batch))
        self.assertTrue(result.primitive_valid)
        answers = [item["answer"] for item in result.value["diagnostics"]]
        self.assertEqual(answers[0]["choice"], "support")
        self.assertEqual(answers[1]["score"], "1.25")
        self.assertEqual(answers[1]["legend"]["1"], "Some qualifying evidence.")
        self.assertEqual(answers[1]["probabilities"]["2"], "0.375")
        self.assertEqual(answers[2]["probability"], "0.1234567890123456789")
        self.assertNotIn("confidence", answers[2])
        self.assertEqual(loads(batch.canonical), batch.value)
        self.assertEqual(loads(result.canonical), result.value)
        self.assertEqual(canonical_digest(loads(result.canonical), "matter.semantic.batchresult.v1"), result.digest)

    def test_raw_lexemes_and_bytes_survive_high_precision_numbers(self):
        batch = make_batch("proposition_probability", "score", "choice")
        raw = response(batch).replace(b'"0.1234567890123456789"', b'0.1234567890123456789')
        raw = raw.replace(b'"0.125"', b'1.25e-1').replace(b'"1.25"', b'1.25000')
        raw = raw.replace(b'"0.15"', b'0.1500000000000000000001')
        result = normalize_response(batch, raw)
        self.assertTrue(result.primitive_valid)
        retained = result.value["raw_response"]
        import base64
        self.assertEqual(base64.b64decode(retained["base64"]), raw)
        self.assertEqual(retained["sha256"], source_digest(raw))
        self.assertIn("0.1234567890123456789", [n["lexeme"] for n in retained["numeric_lexemes"]])
        self.assertIn("1.25e-1", [n["lexeme"] for n in retained["numeric_lexemes"]])
        normalized = result.value["diagnostics"]
        self.assertEqual(normalized[0]["answer"]["probability"], "0.1234567890123456789")
        self.assertEqual(normalized[1]["answer"]["confidence"], "0.1500000000000000000001")
        self.assertEqual(normalized[1]["answer"]["score_residual"], "0")

    def test_exact_residuals_do_not_depend_on_ambient_decimal_precision(self):
        batch = make_batch("score")
        def change(body):
            body["answers"][0].update(score="1.2500000000000000000001")
        profile = PrecisionProfile("synthetic-rounding", "1.0", probability_quantum="0.000000000000000000001")
        with localcontext() as context:
            context.prec = 3
            result = normalize_response(batch, response(batch, change=change), precision=profile)
        self.assertTrue(result.primitive_valid)
        self.assertEqual(result.value["diagnostics"][0]["answer"]["score_residual"], "0.0000000000000000000001")

    def test_probability_half_is_neither_severity_nor_confidence(self):
        batch = make_batch()
        result = normalize_response(batch, response(batch, change=lambda v: v["answers"][0].update(probability="0.5")))
        self.assertEqual(result.value["diagnostics"][0]["answer"],
                         {"id": "q0", "primitive": "proposition_probability", "probability": "0.5"})

    def test_missing_extra_duplicate_and_wrong_type_refuse_whole_batch(self):
        batch = make_batch("choice", "score", "proposition_probability")
        mutations = (
            lambda v: v["answers"].pop(),
            lambda v: v["answers"].append({"id": "unexpected", "primitive": "choice"}),
            lambda v: v["answers"].append(deepcopy(v["answers"][0])),
            lambda v: v["answers"][0].update(primitive="score"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                result = normalize_response(batch, response(batch, change=mutate))
                self.assertFalse(result.primitive_valid)
                self.assertTrue(result.value["faults"])
                self.assertTrue(any(d["status"] == "valid" for d in result.value["diagnostics"]))
                self.assertFalse(result.value["admission"]["consequential_use"])

    def test_malformed_ids_do_not_raise_or_hide_other_valid_answers(self):
        batch = make_batch("choice", "score")
        for identity in (None, [], {}, True):
            with self.subTest(identity=identity):
                raw = response(batch, change=lambda v: v["answers"][0].update(id=identity))
                result = normalize_response(batch, raw)
                self.assertFalse(result.primitive_valid)
                self.assertEqual(result.value["diagnostics"][1]["status"], "valid")

    def test_missing_fields_per_primitive_are_not_defaulted(self):
        for primitive, fields in (("choice", ("choice", "probabilities", "confidence")),
                                 ("score", ("score", "legend", "probabilities", "confidence")),
                                 ("proposition_probability", ("probability",))):
            batch = make_batch(primitive)
            for field in fields:
                with self.subTest(primitive=primitive, field=field):
                    raw = response(batch, change=lambda v: v["answers"][0].pop(field))
                    self.assertFalse(normalize_response(batch, raw).primitive_valid)

    def test_bool_nonfinite_out_of_range_and_unbounded_numeric_values_refused(self):
        batch = make_batch()
        for token in (b'true', b'NaN', b'Infinity', b'-0.1', b'1.0001', b'1e1000000', b'0.123' + b'4' * 256):
            raw = response(batch).replace(b'"0.1234567890123456789"', token)
            with self.subTest(token=token[:25]):
                self.assertFalse(normalize_response(batch, raw).primitive_valid)

    def test_confidence_and_probabilities_are_checked_without_clamping(self):
        for primitive in ("choice", "score"):
            batch = make_batch(primitive)
            for field, value in (("confidence", "1.1"), ("confidence", True), ("probabilities", {})):
                raw = response(batch, change=lambda v: v["answers"][0].update({field: value}))
                self.assertFalse(normalize_response(batch, raw).primitive_valid)

    def test_choice_must_match_declared_options_and_transmitted_argmax(self):
        batch = make_batch("choice")
        for selected in ("unknown", "oppose"):
            raw = response(batch, change=lambda v: v["answers"][0].update(choice=selected))
            self.assertFalse(normalize_response(batch, raw).primitive_valid)

    def test_score_legend_distribution_and_fractional_mean_are_not_coerced(self):
        batch = make_batch("score")
        for mutate in (
            lambda a: a.update(score="1.3"),
            lambda a: a["legend"].update({"0": "Altered rubric."}),
            lambda a: a["probabilities"].update({"3": "0"}),
            lambda a: a.update(score="3"),
        ):
            raw = response(batch, change=lambda v: mutate(v["answers"][0]))
            self.assertFalse(normalize_response(batch, raw).primitive_valid)

    def test_response_cannot_supply_or_widen_its_precision(self):
        batch = make_batch("score")
        raw = response(batch, change=lambda v: v["answers"][0].update(score="1.26"))
        self.assertFalse(normalize_response(batch, raw).primitive_valid)
        trusted = PrecisionProfile("synthetic-nearest", "1.0", score_quantum="0.02")
        self.assertTrue(normalize_response(batch, raw, precision=trusted).primitive_valid)
        own_profile = response(batch, change=lambda v: v.update(precision_profile={"score_quantum": "1"}))
        self.assertFalse(normalize_response(batch, own_profile).primitive_valid)

    def test_rounding_profile_requires_the_declared_numeric_grid(self):
        batch = make_batch("choice")
        raw = response(batch, change=lambda v: v["answers"][0].update(
            probabilities={"support": "0.751", "oppose": "0.249"}))
        trusted = PrecisionProfile("synthetic-two-decimal", "1", probability_quantum="0.01")
        self.assertFalse(normalize_response(batch, raw, precision=trusted).primitive_valid)

    def test_quantization_uses_feasible_probability_intervals(self):
        batch = make_batch("score")
        def change(body):
            body["answers"][0].update(score="1.43", probabilities={"0": "0", "1": "0.57", "2": "0.42"})
        raw = response(batch, change=change)
        self.assertFalse(normalize_response(batch, raw).primitive_valid)
        trusted = PrecisionProfile("synthetic-two-decimal", "1", probability_quantum="0.01", score_quantum="0.01")
        result = normalize_response(batch, raw, precision=trusted)
        self.assertTrue(result.primitive_valid)
        self.assertEqual(result.value["diagnostics"][0]["answer"]["distribution_residual"], "-0.01")
        self.assertEqual(result.value["diagnostics"][0]["answer"]["score_residual"], "0.02")

    def test_binary_float_only_mapping_cannot_claim_exact_admission(self):
        batch = make_batch()
        result = normalize_response(batch, {"answers": [{"id": "q0", "probability": 0.1234567890123456789}]})
        self.assertFalse(result.primitive_valid)
        self.assertFalse(result.value["admission"]["exact_numeric"])
        self.assertEqual(result.value["raw_response"]["state"], "unavailable")
        self.assertEqual(result.value["faults"][0]["code"], "original_wire_required")

    def test_duplicate_object_keys_invalid_encoding_and_unexpected_fields_refused(self):
        batch = make_batch()
        valid = response(batch)
        self.assertTrue(normalize_response(batch, valid).primitive_valid)
        malformed = {
            "duplicate_key": b'{"resolved_model":"ignored",' + valid[1:],
            "bom": b'\xef\xbb\xbf' + valid,
            "invalid_utf8": valid.replace(b'"recording-v1"', b'"recording-\xff-v1"'),
            "unpaired_surrogate": valid.replace(b'"recording-v1"', b'"\\ud800"'),
            "trailing_data": valid + b' {}',
        }
        for case, raw in malformed.items():
            with self.subTest(case=case):
                result = normalize_response(batch, raw)
                self.assertFalse(result.primitive_valid)
                self.assertEqual(result.value["execution_status"], "failed")
                self.assertEqual(result.value["faults"], [{"code": "invalid_response", "path": []}])
                self.assertEqual(result.value["diagnostics"], [])
        raw = response(batch, change=lambda v: v["answers"][0].update(host_action="send"))
        result = normalize_response(batch, raw)
        self.assertFalse(result.primitive_valid)
        self.assertEqual(result.value["execution_status"], "completed")
        self.assertEqual(result.value["faults"], [{"code": "invalid_primitive", "path": ["answers", 0]}])
        self.assertEqual(result.value["diagnostics"][0]["reason"], "invalid_primitive")

    def test_question_and_batch_are_deeply_detached_and_immutable(self):
        raw = make_question("choice")
        question = Question(raw)
        old_digest = question.digest
        raw["criteria"][0]["description"] = "Changed externally."
        detached = question.value
        detached["criteria"].reverse()
        self.assertEqual(question.digest, old_digest)
        with self.assertRaises(AttributeError):
            question._encoded = b'{}'
        batch = make_batch()
        changed = batch.value
        changed["context"]["requested_model"] = "other"
        self.assertNotEqual(batch.value["context"]["requested_model"], "other")

    def test_order_and_context_changes_bind_distinct_batch_identity(self):
        batch = make_batch("choice", "score")
        value = batch.value
        value["questions"].reverse()
        self.assertNotEqual(batch.digest, Batch(value).digest)
        changed = make_batch("choice", "score", change=lambda v: v["context"].update(requested_model="other"))
        self.assertNotEqual(batch.digest, changed.digest)

    def test_invalid_question_criteria_duplicate_ids_and_packet_mismatch_refused(self):
        for change in (
            lambda v: v["questions"][0]["criteria"].append(v["questions"][0]["criteria"][0]),
            lambda v: v["questions"].append(deepcopy(v["questions"][0])),
            lambda v: v["questions"][0].update(packet_digest="b" * 64),
            lambda v: v["state"].update(source="Changed bytes."),
        ):
            with self.assertRaises(ContractError):
                make_batch("choice", change=change)


class ExecutorTests(unittest.TestCase):
    def execute(self, batch=None, *, raw=None, caps=None, times=None, precision=None):
        batch = batch or make_batch()
        fixture = FixtureExecutor(caps or capabilities(), {batch.digest: raw or response(batch)})
        clock = iter(times or (instant(0), instant(1)))
        return execute_batch(fixture, batch, clock=lambda: next(clock), precision=precision)

    def test_offline_execution_and_reencoding_without_vendor_sdk(self):
        result = self.execute()
        self.assertTrue(result.primitive_valid)
        self.assertEqual(result.value["execution_status"], "completed")
        self.assertTrue(result.value["timing"]["called"])
        self.assertEqual(result.value["resolved_model"], "recording-v1")
        self.assertEqual(result.value["admission"]["qualification_status"], "unknown")

    def test_import_and_roundtrip_with_provider_imports_and_network_blocked(self):
        script = '''
import builtins, socket
original = builtins.__import__
def blocked(name, *args, **kwargs):
    if name.split('.')[0] in {'typesafe_sdk', 'openai', 'httpx', 'requests'}:
        raise AssertionError('vendor import attempted')
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
socket.create_connection = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network attempted'))
from matter.semantic import PrecisionProfile
from matter.canonical import loads
profile = PrecisionProfile()
assert loads(profile.canonical) == profile.value
'''
        env = {key: value for key, value in os.environ.items() if not key.endswith("API_KEY")}
        completed = subprocess.run([sys.executable, "-I", "-c", script], env=env, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_no_host_mutation_or_delivery_capability_on_success(self):
        from unittest.mock import patch
        batch = make_batch()
        before = batch.canonical
        with patch("matter.storage.SQLiteStore.execute") as storage_write:
            result = self.execute(batch)
            storage_write.assert_not_called()
        self.assertEqual(batch.canonical, before)
        self.assertFalse(result.value["admission"]["consequential_use"])
        self.assertNotIn("proposed_actions", result.value)

    def test_unsupported_type_mode_and_adapter_identity_fail_before_dispatch(self):
        for batch in (make_batch("future_primitive"),
                      make_batch(change=lambda v: v["context"].update(mode="provider_shadow")),
                      make_batch(change=lambda v: v["context"].update(provider="other"))):
            class Spy:
                capabilities = capabilities()
                calls = 0
                def execute(self, request):
                    self.calls += 1
                    raise AssertionError("unsupported dispatch")
            executor = Spy()
            result = execute_batch(executor, batch, clock=lambda: instant(0))
            self.assertEqual(result.value["execution_status"], "unsupported")
            self.assertEqual(executor.calls, 0)
            self.assertFalse(result.value["timing"]["called"])

    def test_request_budget_fails_before_dispatch(self):
        batch = make_batch()
        result = self.execute(batch, caps=capabilities(max_request_bytes=1))
        self.assertEqual(result.value["execution_status"], "budget_exhausted")
        self.assertFalse(result.value["timing"]["called"])

    def test_response_budget_applies_to_host_and_adapter_limits(self):
        batch = make_batch(change=lambda v: v["context"].update(max_response_bytes=1))
        result = self.execute(batch)
        self.assertEqual(result.value["execution_status"], "budget_exhausted")
        self.assertFalse(result.primitive_valid)

    def test_deadline_before_dispatch_does_not_call_executor(self):
        result = self.execute(times=(instant(10),))
        self.assertEqual(result.value["execution_status"], "timed_out")
        self.assertFalse(result.value["timing"]["called"])

    def test_late_completion_retains_diagnostics_but_is_not_admitted(self):
        result = self.execute(times=(instant(0), instant(10)))
        self.assertEqual(result.value["execution_status"], "timed_out")
        self.assertFalse(result.primitive_valid)
        self.assertEqual(result.value["diagnostics"][0]["status"], "valid")
        self.assertEqual(result.value["raw_response"]["state"], "available")

    def test_backward_clock_is_an_explicit_failure(self):
        result = self.execute(times=(instant(2), instant(1)))
        self.assertFalse(result.primitive_valid)
        self.assertEqual(result.value["faults"][-1]["code"], "clock_reversed")

    def test_recording_miss_does_not_fallback_or_invent_a_negative(self):
        batch = make_batch()
        clock = iter((instant(0), instant(1)))
        result = execute_batch(FixtureExecutor(capabilities(), {}), batch, clock=lambda: next(clock))
        self.assertEqual(result.value["execution_status"], "failed")
        self.assertEqual(result.value["diagnostics"], [])
        self.assertEqual(result.value["raw_response"]["state"], "unavailable")

    def test_fixture_cannot_claim_provider_shadow_execution(self):
        with self.assertRaises(ContractError):
            FixtureExecutor(capabilities(modes=["provider_shadow"]), {})

    def test_adapter_exception_does_not_expose_payload_or_secrets(self):
        class Failing:
            capabilities = capabilities()
            def execute(self, batch):
                raise RuntimeError("synthetic-secret-marker")
        clock = iter((instant(0), instant(1)))
        result = execute_batch(Failing(), make_batch(), clock=lambda: next(clock))
        self.assertNotIn("synthetic-secret-marker", str(result.value))
        self.assertEqual(result.value["execution_status"], "failed")

    def test_adapter_receives_immutable_batch_and_cannot_mutate_prepared_request(self):
        batch = make_batch()
        original = batch.canonical
        class Modifying:
            capabilities = capabilities()
            def execute(self, request):
                request.value["questions"][0]["instructions"] = "Changed detached copy."
                return RawExecution(response(request))
        clock = iter((instant(0), instant(1)))
        result = execute_batch(Modifying(), batch, clock=lambda: next(clock))
        self.assertTrue(result.primitive_valid)
        self.assertEqual(batch.canonical, original)


if __name__ == "__main__":
    unittest.main()
