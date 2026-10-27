"""MAT-026: exact typed answers, diagnostic admission and an injected executor.

These are detached interface values, not stored judgments or qualification
certificates. No SDK, credential loader, host mutation or delivery API is used.
An adapter projects its native response into the neutral wire shape documented
in ``docs/semantic-executor.md`` without converting numeric lexemes to floats.
"""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import json
import re
from typing import Protocol

from ..canonical import canonical_bytes, canonical_digest, loads, source_digest
from ..contracts import ContractError
from ..time import known_time_key


PRIMITIVES = frozenset({"choice", "score", "proposition_probability"})
MAX_WIRE_BYTES = 1024 * 1024
MAX_QUESTIONS = 128
_HASH = re.compile(r"[0-9a-f]{64}")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


def _fail(reason="The value does not satisfy the semantic contract."):
    raise ContractError("E_SCHEMA_INVALID", reason)


def _shape(value, required, optional=()):
    if type(value) is not dict or not set(required) <= set(value) <= set(required) | set(optional):
        _fail()


def _text(value):
    if type(value) is not str or not value or len(value) > 65536:
        _fail()
    canonical_bytes(value)
    return value


def _digest(value):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        _fail()
    return value


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail()
    return value


def _number(value):
    # All arithmetic is decimal, even if the caller changed Decimal's context.
    # Bound exponent and coefficient before fixed-point expansion or arithmetic.
    token = value.lexeme if isinstance(value, _Number) else value
    if type(token) is not str or len(token) > 256 or _DECIMAL.fullmatch(token) is None:
        _fail("An exact decimal lexeme is required.")
    try:
        number = Decimal(token)
        if not number.is_finite() or abs(number.as_tuple().exponent) > 128 or len(number.as_tuple().digits) > 128:
            _fail("The exact decimal exceeds the supported bound.")
        return number
    except InvalidOperation:
        _fail()


def _decimal_string(value):
    if value == 0:
        return "0"
    return format(value, "f").rstrip("0").rstrip(".") if value.as_tuple().exponent < 0 else format(value, "f")


def _probability(value):
    number = _number(value)
    if not 0 <= number <= 1:
        _fail("A probability must be in the closed unit interval.")
    return number


class _Frozen:
    """Canonical bytes internally; all public data is reconstructed and detached."""
    __slots__ = ("_encoded",)

    def _freeze(self, value):
        object.__setattr__(self, "_encoded", canonical_bytes(value))

    def __setattr__(self, name, value):
        raise AttributeError(type(self).__name__ + " is immutable.")

    @property
    def value(self):
        return loads(self._encoded)

    @property
    def canonical(self):
        return self._encoded

    @property
    def digest(self):
        return canonical_digest(self.value, "matter.semantic." + type(self).__name__.lower() + ".v1")


class Question(_Frozen):
    """One fully rendered question; registry and rendering belong to MAT-027."""
    __slots__ = ()

    def __init__(self, value):
        canonical_bytes(value)
        _shape(value, ("id", "family", "revision", "primitive", "instructions", "criteria",
                       "specification_digest", "rendering_revision", "packet_digest", "bound_ids"))
        for field in ("id", "family", "revision", "instructions", "rendering_revision", "primitive"):
            _text(value[field])
        # Unknown primitive names can be represented, so negotiation can refuse
        # them explicitly before calling an adapter. They never validate answers.
        for field in ("specification_digest", "packet_digest"):
            _digest(value[field])
        if type(value["bound_ids"]) is not list or len(value["bound_ids"]) > 128:
            _fail()
        for identity in value["bound_ids"]:
            _text(identity)
        if len(set(value["bound_ids"])) != len(value["bound_ids"]):
            _fail()
        criteria = value["criteria"]
        if value["primitive"] == "choice":
            if type(criteria) is not list or not 2 <= len(criteria) <= 128:
                _fail()
            for option in criteria:
                _shape(option, ("id", "description"))
                _text(option["id"])
                _text(option["description"])
            if len({option["id"] for option in criteria}) != len(criteria):
                _fail()
        elif value["primitive"] == "score":
            if type(criteria) is not list or not 2 <= len(criteria) <= 128:
                _fail()
            for description in criteria:
                _text(description)
        elif value["primitive"] == "proposition_probability":
            _shape(criteria, ("true", "false"))
            _text(criteria["true"])
            _text(criteria["false"])
        self._freeze(value)


class Batch(_Frozen):
    """An immutable ordered independent batch and its explicit host context."""
    __slots__ = ()

    def __init__(self, value):
        canonical_bytes(value)
        _shape(value, ("schema_version", "id", "scope_id", "run_id", "stage_id", "state", "packet_digest",
                       "questions", "context"))
        if value["schema_version"] != "1.0":
            _fail()
        for field in ("id", "scope_id", "run_id", "stage_id"):
            _text(value[field])
        _digest(value["packet_digest"])
        if value["packet_digest"] != canonical_digest(value["state"], "matter.semantic.packet.v1"):
            _fail("The exact frozen state must match its packet digest.")
        if type(value["questions"]) is not list or not 1 <= len(value["questions"]) <= MAX_QUESTIONS:
            _fail()
        questions = [Question(item).value for item in value["questions"]]
        if len({item["id"] for item in questions}) != len(questions):
            _fail("Question correlation IDs must be unique.")
        if any(item["packet_digest"] != value["packet_digest"] for item in questions):
            _fail("Every question must bind the exact batch packet.")
        context = value["context"]
        _shape(context, ("provider", "transport", "requested_model", "adapter_version", "mode", "deadline",
                         "max_request_bytes", "max_response_bytes"))
        for field in ("provider", "transport", "requested_model", "adapter_version"):
            _text(context[field])
        if context["mode"] not in ("offline_fixture", "recorded_replay", "provider_shadow"):
            _fail("Qualified contribution requires the later admission contract.")
        known_time_key(context["deadline"])
        for field in ("max_request_bytes", "max_response_bytes"):
            _integer(context[field], 1, MAX_WIRE_BYTES)
        self._freeze(value)


class Capabilities(_Frozen):
    """Explicit adapter declaration, checked before its execute method is called."""
    __slots__ = ()

    def __init__(self, value):
        canonical_bytes(value)
        _shape(value, ("provider", "transport", "adapter_version", "primitives", "modes", "max_questions",
                       "max_request_bytes", "max_response_bytes"))
        for field in ("provider", "transport", "adapter_version"):
            _text(value[field])
        for field, allowed in (("primitives", PRIMITIVES),
                               ("modes", {"offline_fixture", "recorded_replay", "provider_shadow"})):
            items = value[field]
            if (type(items) is not list or not items or any(type(item) is not str or item not in allowed for item in items)
                    or len(set(items)) != len(items)):
                _fail()
        _integer(value["max_questions"], 1, MAX_QUESTIONS)
        for field in ("max_request_bytes", "max_response_bytes"):
            _integer(value[field], 1, MAX_WIRE_BYTES)
        self._freeze(value)


class PrecisionProfile(_Frozen):
    """Host-selected independent nearest-rounding assumptions, never response data.

    Zero quantums mean exact distribution sums and Score means. Nonzero values
    specify nearest-rounding intervals, not a generic error budget. The profile
    is bound in the result and cannot issue semantic qualification.
    """
    __slots__ = ()

    def __init__(self, identity="exact-decimal", version="1.0", *, probability_quantum="0", score_quantum="0"):
        _text(identity)
        _text(version)
        for quantum in (probability_quantum, score_quantum):
            if type(quantum) is not str or not 0 <= _number(quantum) <= 1:
                _fail()
        self._freeze({"id": identity, "version": version, "rounding": "nearest",
                      "probability_quantum": _decimal_string(_number(probability_quantum)),
                      "score_quantum": _decimal_string(_number(score_quantum))})


@dataclass(frozen=True, slots=True)
class _Number:
    lexeme: str


def _parse_wire(raw, maximum):
    if type(raw) is not bytes or len(raw) > maximum:
        _fail("An original response within its byte budget is required.")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("Duplicate JSON object keys are forbidden.")
            result[key] = value
        return result
    def number(token):
        _number(token)
        return _Number(token)
    def constant(_):
        _fail("Non-finite wire numbers are forbidden.")
    try:
        text = raw.decode("utf-8", errors="strict")
        if text.startswith("\ufeff"):
            _fail()
        value = json.loads(text, object_pairs_hook=pairs, parse_int=number, parse_float=number, parse_constant=constant)
        lexemes = []
        def collect(item, path):
            if isinstance(item, _Number):
                lexemes.append({"path": path, "lexeme": item.lexeme})
            elif type(item) is dict:
                for key, child in item.items():
                    canonical_bytes(key)
                    collect(child, path + [key])
            elif type(item) is list:
                for index, child in enumerate(item):
                    collect(child, path + [index])
            else:
                canonical_bytes(item)
        collect(value, [])
        return value, lexemes
    except (UnicodeError, ValueError, RecursionError):
        _fail("The original response is not valid bounded JSON.")


def _distribution(raw, keys, profile):
    if type(raw) is not dict or set(raw) != set(keys):
        _fail("Distribution IDs must exactly match the declared criteria.")
    probabilities = {key: _probability(raw[key]) for key in keys}
    quantum = _number(profile.value["probability_quantum"])
    if quantum and any(p % quantum != 0 for p in probabilities.values()):
        _fail("A probability does not lie on the trusted rounding grid.")
    half = quantum / 2
    lower = {key: max(Decimal(0), p - half) for key, p in probabilities.items()}
    upper = {key: min(Decimal(1), p + half) for key, p in probabilities.items()}
    if not sum(lower.values()) <= 1 <= sum(upper.values()):
        _fail("The distribution cannot sum to one under the trusted precision profile.")
    return probabilities, lower, upper


def _score_extreme(keys, lower, upper, *, reverse):
    values = dict(lower)
    remaining = 1 - sum(values.values())
    for key in sorted(keys, key=int, reverse=reverse):
        extra = min(remaining, upper[key] - values[key])
        values[key] += extra
        remaining -= extra
    return sum(Decimal(key) * values[key] for key in keys)


def _answer(question, raw, profile):
    primitive = question["primitive"]
    common = ("id", "primitive")
    if primitive == "choice":
        _shape(raw, common + ("choice", "probabilities", "confidence"))
        keys = [option["id"] for option in question["criteria"]]
        if type(raw["choice"]) is not str or raw["choice"] not in keys:
            _fail("The choice must name a declared option.")
        probabilities, _, _ = _distribution(raw["probabilities"], keys, profile)
        if probabilities[raw["choice"]] != max(probabilities.values()):
            _fail("The selected option must have maximal transmitted probability.")
        return {"id": question["id"], "primitive": primitive, "choice": raw["choice"],
                "probabilities": {key: _decimal_string(p) for key, p in probabilities.items()},
                "confidence": _decimal_string(_probability(raw["confidence"])),
                "distribution_residual": _decimal_string(sum(probabilities.values()) - 1)}
    if primitive == "score":
        _shape(raw, common + ("score", "legend", "probabilities", "confidence"))
        keys = [str(i) for i in range(len(question["criteria"]))]
        legend = dict(zip(keys, question["criteria"]))
        if raw["legend"] != legend:
            _fail("The returned legend must preserve the exact ordered rubric.")
        probabilities, lower, upper = _distribution(raw["probabilities"], keys, profile)
        score = _number(raw["score"])
        quantum = _number(profile.value["score_quantum"])
        if quantum and score % quantum != 0:
            _fail("The Score does not lie on the trusted rounding grid.")
        half = quantum / 2
        minimum = _score_extreme(keys, lower, upper, reverse=False)
        maximum = _score_extreme(keys, lower, upper, reverse=True)
        if not 0 <= score <= len(keys) - 1 or score + half < minimum or score - half > maximum:
            _fail("The Score is inconsistent with its rubric distribution and trusted precision profile.")
        return {"id": question["id"], "primitive": primitive, "score": _decimal_string(score),
                "legend": legend, "probabilities": {key: _decimal_string(p) for key, p in probabilities.items()},
                "confidence": _decimal_string(_probability(raw["confidence"])),
                "distribution_residual": _decimal_string(sum(probabilities.values()) - 1),
                "score_residual": _decimal_string(score - sum(Decimal(key) * p for key, p in probabilities.items()))}
    if primitive == "proposition_probability":
        _shape(raw, common + ("probability",))
        return {"id": question["id"], "primitive": primitive,
                "probability": _decimal_string(_probability(raw["probability"]))}
    _fail("This primitive is unsupported.")


class BatchResult(_Frozen):
    """An immutable unqualified attempt; only factories construct valid results."""
    __slots__ = ()

    def __init__(self, value, *, _factory=False):
        if not _factory:
            raise ContractError("E_POLICY_INVALID", "Use normalize_response or execute_batch.")
        self._freeze(value)

    @property
    def primitive_valid(self):
        return self.value["admission"]["primitive_status"] == "valid"


def _result(batch, profile, *, status="completed", raw=None, lexemes=(), model=None, diagnostics=(), faults=(),
            called=False, started=None, completed=None, exact=True):
    faults = list(faults)
    value = {"schema_version": "1.0", "batch_digest": batch.digest, "execution_status": status,
             "context": batch.value["context"], "precision_profile": profile.value,
             "resolved_model": model, "model_unavailable_reason": None if model is not None else "not_reported",
             "raw_response": ({"state": "available", "sha256": source_digest(raw), "byte_length": len(raw),
                 "base64": base64.b64encode(raw).decode("ascii"), "numeric_lexemes": list(lexemes)}
                 if raw is not None else {"state": "unavailable", "reason": "not_returned"}),
             "diagnostics": list(diagnostics), "faults": faults,
             "admission": {"primitive_status": "valid" if not faults and status == "completed" else "invalid",
                 "exact_numeric": exact, "qualification_status": "unknown", "certificate": None,
                 "consequential_use": False, "reasons": ["semantic_qualification_not_established", "host_authority_not_granted"]},
             "timing": {"called": called, "started": started, "completed": completed},
             "usage": {"value": None, "reason": "not_measured_by_this_interface"},
             "cost": {"value": None, "reason": "price_basis_not_supplied"}}
    return BatchResult(value, _factory=True)


def normalize_response(batch, raw, *, precision=None):
    """Validate a neutral raw JSON response without admitting consequential use.

    The raw ``answers`` array retains duplicates for diagnosis. Native adapters
    must preserve their original artifact separately when projecting into this
    neutral shape; this function's raw artifact is the exact bytes it received.
    An SDK mapping containing floats is refused, not relabeled exact evidence.
    """
    if not isinstance(batch, Batch) or (precision is not None and not isinstance(precision, PrecisionProfile)):
        _fail()
    profile = precision or PrecisionProfile()
    if type(raw) is not bytes:
        return _result(batch, profile, status="failed", exact=False,
                       faults=[{"code": "original_wire_required", "path": []}])
    maximum = batch.value["context"]["max_response_bytes"]
    if len(raw) > maximum:
        return _result(batch, profile, status="budget_exhausted",
                       faults=[{"code": "response_byte_limit", "path": []}])
    try:
        body, lexemes = _parse_wire(raw, maximum)
        _shape(body, ("answers", "resolved_model"))
        _text(body["resolved_model"])
        if type(body["answers"]) is not list or len(body["answers"]) > 2 * MAX_QUESTIONS:
            _fail()
    except (ContractError, ValueError):
        return _result(batch, profile, status="failed", raw=raw,
                       faults=[{"code": "invalid_response", "path": []}])
    questions = {q["id"]: q for q in batch.value["questions"]}
    ids = [answer.get("id") if type(answer) is dict else None for answer in body["answers"]]
    counts = Counter(identity for identity in ids if type(identity) is str)
    faults = [{"code": "missing_answer", "path": ["answers"], "id": identity}
              for identity in questions if identity not in counts]
    diagnostics = []
    with localcontext() as context:
        context.prec = 1024
        context.Emax, context.Emin = 2048, -2048
        for index, answer in enumerate(body["answers"]):
            identity = ids[index]
            code = None
            normalized = None
            if type(identity) is not str or identity not in questions:
                code = "unexpected_answer"
            elif counts[identity] != 1:
                code = "duplicate_answer"
            elif answer.get("primitive") != questions[identity]["primitive"]:
                code = "wrong_primitive"
            else:
                try:
                    normalized = _answer(questions[identity], answer, profile)
                except (ContractError, ValueError, TypeError):
                    code = "invalid_primitive"
            if code:
                faults.append({"code": code, "path": ["answers", index]})
            diagnostics.append({"index": index, "id": identity if type(identity) is str else None,
                                "status": "valid" if code is None else "invalid", "answer": normalized,
                                "reason": code})
    return _result(batch, profile, raw=raw, lexemes=lexemes, model=body["resolved_model"],
                   diagnostics=diagnostics, faults=faults)


@dataclass(frozen=True, slots=True)
class RawExecution:
    """Only the original neutral wire bytes cross back from an adapter."""
    raw_response: bytes

    def __post_init__(self):
        if type(self.raw_response) is not bytes:
            _fail("An adapter must return original neutral wire bytes.")


class Executor(Protocol):
    @property
    def capabilities(self) -> Capabilities: ...

    def execute(self, batch: Batch) -> RawExecution: ...


class FixtureExecutor:
    """Exact batch-digest recordings only; no fallback, network or host hooks."""
    __slots__ = ("_capabilities", "_recordings")

    def __init__(self, capabilities, recordings):
        if not isinstance(capabilities, Capabilities) or type(recordings) is not dict:
            _fail()
        if any(mode not in ("offline_fixture", "recorded_replay") for mode in capabilities.value["modes"]):
            _fail("A fixture cannot declare provider execution.")
        for digest, raw in recordings.items():
            _digest(digest)
            if type(raw) is not bytes or len(raw) > capabilities.value["max_response_bytes"]:
                _fail()
        self._capabilities = capabilities
        self._recordings = dict(recordings)

    @property
    def capabilities(self):
        return self._capabilities

    def execute(self, batch):
        if batch.digest not in self._recordings:
            raise ContractError("E_EVIDENCE_UNAVAILABLE", "No exact batch recording is available.")
        return RawExecution(self._recordings[batch.digest])


def execute_batch(executor, batch, *, clock, precision=None):
    """Negotiate before dispatch and check a cooperative absolute deadline.

    The trusted host injects its clock and adapter. There are no retries or
    action callbacks. A synchronous callback cannot be preempted by this seam;
    an overrun is retained diagnostically and barred from primitive admission.
    """
    if not isinstance(batch, Batch) or (precision is not None and not isinstance(precision, PrecisionProfile)):
        _fail()
    profile = precision or PrecisionProfile()
    capabilities = executor.capabilities
    if not isinstance(capabilities, Capabilities):
        _fail()
    caps, data = capabilities.value, batch.value
    context = data["context"]
    mismatched = any(context[field] != caps[field] for field in ("provider", "transport", "adapter_version"))
    unsupported = any(q["primitive"] not in caps["primitives"] for q in data["questions"])
    if mismatched or unsupported or context["mode"] not in caps["modes"]:
        return _result(batch, profile, status="unsupported", faults=[{"code": "unsupported_capability", "path": []}])
    if (len(data["questions"]) > caps["max_questions"] or
            len(batch.canonical) > min(context["max_request_bytes"], caps["max_request_bytes"])):
        return _result(batch, profile, status="budget_exhausted", faults=[{"code": "request_budget", "path": []}])
    started = clock()
    start_key = known_time_key(started)
    deadline = known_time_key(context["deadline"])
    if start_key >= deadline:
        return _result(batch, profile, status="timed_out", started=started, completed=started,
                       faults=[{"code": "deadline_before_dispatch", "path": []}])
    try:
        execution = executor.execute(batch)
        if not isinstance(execution, RawExecution):
            _fail()
        maximum = min(context["max_response_bytes"], caps["max_response_bytes"])
        if len(execution.raw_response) > maximum:
            result = _result(batch, profile, status="budget_exhausted", faults=[{"code": "response_byte_limit", "path": []}])
        else:
            result = normalize_response(batch, execution.raw_response, precision=profile)
    except Exception:
        # Errors do not echo arbitrary adapter exceptions, which may carry data
        # or secrets, and cannot turn into a fabricated negative answer.
        result = _result(batch, profile, status="failed", faults=[{"code": "executor_failed", "path": []}])
    completed = clock()
    end_key = known_time_key(completed)
    value = result.value
    value["timing"] = {"called": True, "started": started, "completed": completed}
    if end_key < start_key or end_key >= deadline:
        value["execution_status"] = "failed" if end_key < start_key else "timed_out"
        value["faults"].append({"code": "clock_reversed" if end_key < start_key else "deadline_after_dispatch", "path": []})
        value["admission"]["primitive_status"] = "invalid"
    return BatchResult(value, _factory=True)
