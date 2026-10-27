"""MAT-032 one original, optional, lossless TypeSafe System One HTTP adapter.

Only explicit construction reads TYPESAFE_API_KEY. Core imports do not import
this module. Native bytes never pass through SDK floats; SDK-shaped injected
responses require their original raw_http_response.content. No SDK is imported.
The host owns durable attempts, egress, retries, qualification and actual IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import math
import os
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ...canonical import canonical_bytes
from ...contracts import ContractError
from ...time import known_time_key
from ..contracts import (Batch, Capabilities, ExecutionFault, ExecutionInstrumentation,
                         MAX_QUESTIONS, MAX_WIRE_BYTES, PrecisionProfile, RawExecution,
                         _Number, _parse_wire)


ENDPOINT = "https://api.typesafe.ai/v1/systemone"
API_KEY_ENV = "TYPESAFE_API_KEY"
ADAPTER_VERSION = "matter-typesafe-http/1.0"


class TypeSafeConfigurationError(ContractError):
    def __init__(self, reason):
        super().__init__("E_POLICY_INVALID", reason)


def _configuration(reason):
    raise TypeSafeConfigurationError(reason) from None


def _now():
    return {"state": "known", "value": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "precision": "microsecond"}


def _nanos(instant):
    main, fraction = known_time_key(instant)
    return ((date.fromisoformat(main[:10]).toordinal() * 86400 + int(main[11:13]) * 3600 +
             int(main[14:16]) * 60 + int(main[17:19])) * 1000000000 + int(fraction))


@dataclass(frozen=True, slots=True, repr=False)
class HTTPResponse:
    """An injected status and original bytes; no header or exception container."""
    status: int
    content: bytes

    def __post_init__(self):
        if type(self.status) is not int or not 100 <= self.status <= 599 or type(self.content) is not bytes:
            raise ContractError("E_SCHEMA_INVALID", "An HTTP status and original response bytes are required.")

    def __repr__(self):
        return "HTTPResponse(status=" + str(self.status) + ", content_bytes=" + str(len(self.content)) + ")"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _stdlib_http(*, body, api_key, timeout, max_response_bytes):
    """Exactly one bounded request to the fixed endpoint; redirects disabled."""
    request = Request(ENDPOINT, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json",
        "Authorization": "Bearer " + api_key, "User-Agent": "matter-typesafe-http/1.0"})
    # No ambient proxy credential/configuration selection and no global opener.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return HTTPResponse(response.status, response.read(max_response_bytes + 1))
    except HTTPError as error:
        # Error headers and arbitrary exception text never leave this boundary.
        try:
            return HTTPResponse(error.code, error.read(max_response_bytes + 1))
        finally:
            error.close()


def _emit(value):
    """Emit validated original number tokens directly, without float conversion."""
    if isinstance(value, _Number):
        return value.lexeme
    if type(value) is dict:
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + _emit(child) for key, child in value.items()) + "}"
    if type(value) is list:
        return "[" + ",".join(_emit(child) for child in value) + "]"
    if value is None or type(value) in {str, bool}:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    raise ContractError("E_SCHEMA_INVALID", "An original numeric lexeme is required.")


def _contains_secret(value, secret):
    if type(value) is str:
        return secret in value
    if type(value) is dict:
        return any(secret in key or _contains_secret(child, secret) for key, child in value.items())
    if type(value) is list:
        return any(_contains_secret(child, secret) for child in value)
    return False


def _usage(body):
    raw = body.get("usage") if type(body) is dict else None
    if type(raw) is not dict:
        return None
    result = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = raw.get(key)
        token = value.lexeme if isinstance(value, _Number) else ""
        # Native usage counts must be integer JSON tokens, not booleans,
        # strings, fractional values or a guessed sum of other counters.
        if token and token.isascii() and token.isdigit() and len(token) <= 16:
            number = int(token)
            result[key] = number if number <= 2**53 - 1 else None
        else:
            result[key] = None
    return result


def _project_answers(body):
    answers = body["answers"]
    if type(answers) is not dict or len(answers) > 2 * MAX_QUESTIONS:
        raise ContractError("E_SCHEMA_INVALID", "A bounded native answer map is required.")
    result = []
    mapping = {"noul": "proposition_probability", "choice": "choice", "score": "score"}
    fields = {"noul": {"type", "noul"}, "choice": {"type", "choice", "probabilities", "confidence"},
              "score": {"type", "score", "legend", "probabilities", "confidence"}}
    for identity, native in answers.items():
        if type(native) is not dict:
            result.append({"id": identity, "primitive": None, "native_invalid": True})
            continue
        kind = native.get("type") if type(native.get("type")) is str else None
        answer = {"id": identity, "primitive": mapping.get(kind, kind)}
        for key, value in native.items():
            if key not in {"type", "id", "primitive"}:
                answer["probability" if key == "noul" else key] = value
        if kind not in fields or set(native) != fields[kind]:
            answer["native_shape_invalid"] = True
        numbers = ("probability",) if kind == "noul" else ("score", "confidence") if kind == "score" else ("confidence",) if kind == "choice" else ()
        bad = any(not isinstance(answer.get(field), _Number) for field in numbers)
        if kind in {"choice", "score"}:
            probabilities = answer.get("probabilities")
            bad = bad or type(probabilities) is not dict or any(not isinstance(value, _Number) for value in probabilities.values())
        if bad:
            # Neutral decimal strings are legitimate core values, but native
            # quoted numbers are not. Preserve that distinction as an invalid
            # head; the original native artifact retains the actual bad value.
            answer["native_numeric_type_invalid"] = True
        result.append(answer)
    return result


class TypeSafeHTTPExecutor:
    """Explicit selected adapter; the injected HTTP callable is trusted host code.

    Transport signature: ``transport(body=bytes, api_key=str, timeout=seconds,
    max_response_bytes=int)`` returns HTTPResponse or an SDK-shaped object whose
    raw_http_response has original bytes and status_code. No automatic retries.
    Each instance's local call cap is shared safely across concurrent callers.
    """
    __slots__ = ("_model", "_api_key", "_timeout", "_max_calls", "_calls", "_lock", "_transport", "_clock",
                 "_capabilities", "_precision")

    def __init__(self, *, model, timeout, max_calls, api_key=None, max_retries=0,
                 max_request_bytes=MAX_WIRE_BYTES, max_response_bytes=MAX_WIRE_BYTES,
                 transport=None, clock=None, precision=None):
        if type(model) is not str or not model or model != model.strip() or len(model) > 65536 or any(ord(c) < 32 for c in model):
            _configuration("TypeSafe requires an explicit nonempty model.")
        try:
            canonical_bytes(model)
        except (ValueError, TypeError):
            _configuration("TypeSafe model configuration must be valid canonical text.")
        if type(timeout) not in {int, float} or not 0 < timeout <= 300 or not math.isfinite(timeout):
            _configuration("TypeSafe requires a finite positive timeout of at most 300 seconds.")
        if type(max_calls) is not int or not 0 <= max_calls <= 2**53 - 1:
            _configuration("TypeSafe requires an explicit nonnegative local call limit.")
        if type(max_retries) is not int or max_retries != 0:
            _configuration("TypeSafe automatic retries must be zero; the host owns explicit attempts.")
        for amount in (max_request_bytes, max_response_bytes):
            if type(amount) is not int or not 1 <= amount <= MAX_WIRE_BYTES:
                _configuration("TypeSafe byte limits must fit the bounded core wire contract.")
        key = os.environ.get(API_KEY_ENV) if api_key is None else api_key
        if type(key) is not str or not key:
            _configuration("TypeSafe selection requires TYPESAFE_API_KEY or an explicit api_key.")
        if len(key) > 4096 or any(not 33 <= ord(character) <= 126 for character in key):
            _configuration("TypeSafe credentials must be a bounded single-line ASCII token.")
        if key in model:
            _configuration("TypeSafe model configuration contains credential material.")
        if transport is not None and not callable(transport) or clock is not None and not callable(clock):
            _configuration("TypeSafe requires callable injected transport and clock boundaries.")
        if precision is not None and not isinstance(precision, PrecisionProfile):
            _configuration("TypeSafe precision must be an explicit trusted PrecisionProfile.")
        self._model, self._api_key, self._timeout, self._max_calls = model, key, timeout, max_calls
        self._calls, self._lock = 0, Lock()
        self._transport, self._clock, self._precision = transport or _stdlib_http, clock or _now, precision or PrecisionProfile()
        self._capabilities = Capabilities({"provider": "typesafe", "transport": "http", "adapter_version": ADAPTER_VERSION,
            "primitives": ["choice", "score", "proposition_probability"], "modes": ["provider_shadow"],
            "max_questions": MAX_QUESTIONS, "max_request_bytes": max_request_bytes, "max_response_bytes": max_response_bytes})

    @property
    def capabilities(self):
        return self._capabilities

    @property
    def precision_profile(self):
        return self._precision

    @property
    def calls_made(self):
        with self._lock:
            return self._calls

    def _metadata(self, *, started=None, completed=None, request_bytes=None, response_bytes=None, usage=None):
        if started is not None and completed is not None and known_time_key(completed) < known_time_key(started):
            completed = None
        return ExecutionInstrumentation({"started": started, "completed": completed, "request_bytes": request_bytes,
            "response_bytes": response_bytes, "usage": usage,
            "unavailable": {"logical_request_id": "not_supplied", "attempt_id": "not_supplied"}})

    def _request(self, batch):
        if not isinstance(batch, Batch):
            raise ContractError("E_SCHEMA_INVALID", "A bounded semantic Batch is required.")
        data = batch.value
        context = data["context"]
        caps = self.capabilities.value
        if any(context[key] != caps[key] for key in ("provider", "transport", "adapter_version")) or context["requested_model"] != self._model:
            raise ExecutionFault("unavailable", instrumentation=self._metadata(request_bytes=0))
        if context["mode"] not in caps["modes"] or type(data["state"]) not in {str, dict, list}:
            raise ExecutionFault("unavailable", instrumentation=self._metadata(request_bytes=0))
        questions = {}
        for question in data["questions"]:
            kind = question["primitive"]
            if kind == "choice":
                criteria = {item["id"]: item["description"] for item in question["criteria"]}
            elif kind == "score" and len(question["criteria"]) <= 10:
                criteria = list(question["criteria"])
            elif kind == "proposition_probability":
                criteria = {key: question["criteria"][key] for key in ("true", "false")}
                kind = "noul"
            else:
                raise ExecutionFault("unavailable", instrumentation=self._metadata(request_bytes=0))
            questions[question["id"]] = {"type": kind, "instructions": question["instructions"], "criteria": criteria}
        raw = json.dumps({"state": data["state"], "model": self._model, "questions": questions}, ensure_ascii=False,
            allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > min(context["max_request_bytes"], caps["max_request_bytes"]):
            raise ExecutionFault("unavailable", instrumentation=self._metadata(request_bytes=0))
        return raw

    def execute(self, batch):
        body = self._request(batch)
        started = self._clock()
        remaining = _nanos(batch.value["context"]["deadline"]) - _nanos(started)
        if remaining <= 0:
            raise ExecutionFault("timeout", instrumentation=self._metadata(started=started, completed=started, request_bytes=0))
        timeout = min(self._timeout, remaining / 1000000000)
        maximum = min(batch.value["context"]["max_response_bytes"], self.capabilities.value["max_response_bytes"])
        with self._lock:
            if self._calls >= self._max_calls:
                raise ExecutionFault("unavailable", instrumentation=self._metadata(started=started, completed=started, request_bytes=0))
            self._calls += 1
        code, response, raw, status = None, None, None, None
        try:
            response = self._transport(body=body, api_key=self._api_key, timeout=timeout, max_response_bytes=maximum)
        except (TimeoutError,):
            code = "timeout"
        except URLError as error:
            code = "timeout" if isinstance(error.reason, TimeoutError) else "transport_error"
        except Exception:
            code = "transport_error"
        # Raise outside the transport exception handler: no native exception,
        # headers or secret-bearing exception context is retained in a fault.
        if code is not None:
            raise ExecutionFault(code, instrumentation=self._metadata(started=started, completed=self._clock(), request_bytes=len(body))) from None
        if isinstance(response, HTTPResponse):
            status, raw = response.status, response.content
        else:
            try:
                native = response.raw_http_response
                raw, status = native.content, native.status_code
            except Exception:
                raw = None
            if type(raw) is not bytes:
                raise ExecutionFault("precision_unavailable", instrumentation=self._metadata(
                    started=started, completed=self._clock(), request_bytes=len(body))) from None
        if len(raw) > maximum:
            raise ExecutionFault("response_budget", instrumentation=self._metadata(started=started,
                completed=self._clock(), request_bytes=len(body), response_bytes=len(raw)))
        metadata = self._metadata(started=started, completed=self._clock(), request_bytes=len(body), response_bytes=len(raw))
        parsed, safe_native = None, None
        try:
            parsed, _ = _parse_wire(raw, maximum)
            if self._api_key.encode("ascii") not in raw and not _contains_secret(parsed, self._api_key):
                safe_native = raw
        except (ContractError, ValueError, TypeError):
            pass
        if safe_native is None:
            fault = ("rate_limited" if status == 429 else "timeout" if status in {408, 504} else "provider_error") if type(status) is int else "provider_error"
            raise ExecutionFault(fault, instrumentation=metadata)
        metadata = self._metadata(started=started, completed=self._clock(), request_bytes=len(body), response_bytes=len(raw), usage=_usage(parsed))
        if type(status) is not int or not 200 <= status <= 299:
            fault = ("rate_limited" if status == 429 else "timeout" if status in {408, 504} else "provider_error") if type(status) is int else "provider_error"
            raise ExecutionFault(fault,
                native_response=safe_native, instrumentation=metadata)
        if type(parsed) is not dict or type(parsed.get("model")) is not str or not parsed["model"]:
            raise ExecutionFault("model_unresolved", native_response=safe_native, instrumentation=metadata)
        try:
            canonical_bytes(parsed["model"])
            if not {"model", "answers"} <= set(parsed) <= {"model", "answers", "usage"}:
                raise ContractError("E_SCHEMA_INVALID")
            neutral = _emit({"answers": _project_answers(parsed), "resolved_model": parsed["model"]}).encode("utf-8")
        except (ContractError, ValueError, TypeError, RecursionError):
            raise ExecutionFault("provider_error", native_response=safe_native, instrumentation=metadata) from None
        if len(neutral) > maximum:
            raise ExecutionFault("response_budget", native_response=safe_native, instrumentation=metadata)
        return RawExecution(neutral, native_response=safe_native, instrumentation=metadata)
