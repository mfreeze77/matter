"""MAT-030 durable exact execution observations; no provider or qualification issuer.

A started observation is claimed before injected I/O. Replaying it never sends
again: an interrupted start is unknown until the host records its actual result.
The raw storage and artifact ports remain trusted host machinery.
"""

import base64
from copy import deepcopy
from datetime import datetime, timedelta

from .._rule_values import checked, descriptor, domain, fragment
from ..budgets import _Reads, _lookup, _value, milliseconds
from ..canonical import canonical_bytes, canonical_digest, source_digest
from ..contracts import ContractError, validate_command
from ..storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from ..time import compare_times, known_time_key
from .cache import attempt_ref, cache_ref, execution_key
from .contracts import Batch, BatchResult, ExecutionFault, ExecutionInstrumentation, PrecisionProfile, execute_batch, normalize_response
from .packets import PreparedPacket
from .rendering import RenderedQuestion, render_question


NAMESPACE = "matter.semantic.executions"
ENGINE = descriptor("matter", "semantic-execution-recorder", "1.0",
    {"identity": "exact-request-and-execution-assumptions", "retry": "explicit-attempt", "authority": "none"},
    "matter.semantic-execution-recorder.v1")


def _fail(code="E_EVIDENCE_INVALID"):
    raise StorageError(code, "The semantic execution or its original context is unavailable or invalid.")


def _precision(value):
    value = checked(value, required=("id", "version", "rounding", "probability_quantum", "score_quantum"))
    profile = PrecisionProfile(value["id"], value["version"], probability_quantum=value["probability_quantum"], score_quantum=value["score_quantum"])
    if profile.value != value:
        _fail()
    return profile


def _refs(values):
    found = {}
    for ref in values:
        fragment(ref, "pinned_ref")
        key = canonical_bytes(entity_ref(ref))
        if key in found and found[key] != ref:
            _fail("E_DEPENDENCY_STALE")
        found[key] = ref
    return sorted(found.values(), key=canonical_bytes)


def _public_refs(refs):
    # Use the same trusted service bookkeeping boundary as ControlService.
    return [ref for ref in refs if ref["record_type"] not in {"receipt", "control"} and
            not (ref["record_type"] == PROJECTION_TYPE and ref["namespace"].startswith("matter."))]


def _targets(refs):
    return [entity_ref(ref) for ref in _public_refs(refs)]

def _strip(result):
    value = deepcopy(result)
    for key in ("raw_response", "native_response"):
        if key in value:
            value[key].pop("base64", None)
    return value


def normalized_digest(result):
    """Canonical admission/answer identity, separately from original wire evidence."""
    return canonical_digest({key: result[key] for key in ("schema_version", "execution_status", "precision_profile",
        "resolved_model", "model_unavailable_reason", "diagnostics", "faults", "admission")},
        "matter.semantic.normalized-execution.v1")


class ExecutionReceiptStore:
    """Immutable existing-core receipts plus scoped external response artifacts.

    No method issues a qualification. `qualify` is an explicitly installed host
    classifier called again on each reuse; its decision cannot alter primitives.
    """
    def __init__(self, storage, *, payloads, controls, clock, questions, access=None, budgets=None):
        if payloads.scope_id != storage.scope_id or controls.scope_id != storage.scope_id or not callable(clock):
            _fail("E_SCOPE_FORBIDDEN")
        self.storage, self.scope_id, self.payloads = storage, storage.scope_id, payloads
        self.controls, self.clock, self.questions, self.access, self.budgets = controls, clock, questions, access, budgets

    def request(self, batch, *, packet, rendered_questions, token, precision=None, model_binding=None,
                access_context=None, stage=None):
        if not isinstance(batch, Batch) or not isinstance(packet, PreparedPacket):
            _fail()
        profile = precision or PrecisionProfile()
        if not isinstance(profile, PrecisionProfile) or batch.value["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        rendered = list(rendered_questions)
        if (not rendered or len(rendered) > 128 or any(not isinstance(item, RenderedQuestion) for item in rendered) or
                [item.question.value for item in rendered] != batch.value["questions"] or
                packet.state != batch.value["state"] or packet.digest != batch.value["packet_digest"]):
            _fail()
        request = {"batch": batch.value, "packet": packet.value, "rendered": [item.value for item in rendered],
            "precision": profile.value, "model_binding": model_binding, "stage": stage, "requested_deadline": batch.value["context"]["deadline"]}
        with self.storage.snapshot() as view:
            self._request(view, request, token, access_context)
        return request

    def _request(self, view, request, token, access_context):
        request = checked(request, required=("batch", "packet", "rendered", "precision", "model_binding", "stage", "requested_deadline"))
        domain("control-token", token)
        if token["scope_id"] != self.scope_id or token["capability"] != "assessment":
            _fail("E_AUTHORITY_REQUIRED")
        batch, packet, profile = Batch(request["batch"]), PreparedPacket(request["packet"], _prepared=True), _precision(request["precision"])
        fragment(request["requested_deadline"], "known_time")
        if compare_times(batch.value["context"]["deadline"], request["requested_deadline"]) == 1:
            _fail()
        if batch.value["scope_id"] != self.scope_id or packet.state != batch.value["state"] or packet.digest != batch.value["packet_digest"]:
            _fail()
        if type(request["rendered"]) is not list or len(request["rendered"]) != len(batch.value["questions"]):
            _fail()
        if self.access is None:
            if access_context is not None or "access_context" in packet.state:
                _fail("E_AUTHORITY_REQUIRED")
        else:
            admitted = self.access.require_packet(view, access_context, packet.state)
            if admitted.value["token"] != token:
                _fail("E_AUTHORITY_REQUIRED")
            provider = next((item for item in self.access.policy.value["providers"] if item["reference"] == admitted.value["provider"]), None)
            if provider is None or any(batch.value["context"][key] != provider[key] for key in ("provider", "transport")):
                _fail("E_AUTHORITY_REQUIRED")
        if request["stage"] is not None:
            stage = checked(request["stage"], required=("plan", "members"))
            fragment(stage["plan"], "component_ref")
            if type(stage["members"]) is not list or not 1 <= len(stage["members"]) <= 128:
                _fail()
            for member in stage["members"]:
                checked(member, required=("stage_id", "transform", "parent_traces"))
                fragment(member["transform"], "component_ref")
                fragment(member["stage_id"], "identifier")
                if type(member["parent_traces"]) is not list or len(member["parent_traces"]) > 128:
                    _fail("E_BUDGET_EXHAUSTED")
                for ref in member["parent_traces"]:
                    fragment(ref, "component_ref")
        for expected, raw in zip(batch.value["questions"], request["rendered"]):
            rendered = RenderedQuestion(raw, _factory=True)
            spec = self.questions.resolve(rendered.manifest["specification"])
            rebuilt = render_question(spec, packet.state, expected["id"], bound_ids=expected["bound_ids"],
                source_manifest=packet.source_manifest, max_render_bytes=1048576,
                **({"access": self.access, "access_context": access_context, "access_view": view} if self.access is not None else {}))
            if rebuilt.value != raw or rendered.question.value != expected:
                _fail()
        # This checks the host model binding shape even when no cache lookup runs.
        execution_key(batch, rendered=request["rendered"], precision=profile,
            model_binding=request["model_binding"], token=token, stage=request["stage"], dependencies=request["packet"]["dependencies"])
        return batch, packet, profile

    def _audit(self, view, value):
        # The consumer must be allowed to read actual transitive parent source
        # material, not only the child's newly selected packet. Historical
        # inspection uses the same closure without requiring unchanged pins.
        pending, seen, sources = [value], set(), []
        while pending:
            material = pending.pop()
            sources.extend(material["sources"])
            for reference in material["parents"]:
                key = canonical_bytes(reference)
                if key in seen:
                    continue
                seen.add(key)
                if len(seen) > 128:
                    _fail("E_BUDGET_EXHAUSTED")
                pending.append(self._details(view.get(reference)))
        sources = _refs(sources)
        token = value["control_token"]
        self.controls._view(view, actor=token["actor"], authority=entity_ref(token["authority"]),
            capability="read", targets=_targets(sources), now=self.clock(), audit=True)
        if self.access is not None:
            self.access.require_history(view, value["access_context"], references=_public_refs(sources))
        elif value["access_context"] is not None:
            _fail("E_AUTHORITY_REQUIRED")
        return sources

    def _current(self, view, value, *, dispatch=False):
        now = fragment(self.clock(), "known_time")
        root_reads = self._audit(view, value)
        self.controls.require_current(view, value["control_token"], capability="assessment", targets=_targets(root_reads), as_of=now)
        if self.access is not None:
            self.access.require_current(view, value["access_context"], references=_public_refs(root_reads))
        pending, seen = [value], set()
        while pending:
            material = pending.pop()
            self._audit(view, material)
            for ref in material["sources"]:
                if pin(view.get(entity_ref(ref))) != ref:
                    _fail("E_DEPENDENCY_STALE")
            token = material["control_token"]
            self.controls.require_current(view, token, capability="assessment", targets=_targets(material["sources"]), as_of=now)
            if self.access is not None:
                self.access.require_current(view, material["access_context"], references=_public_refs(material["sources"]))
            for reference in material["parents"]:
                key = canonical_bytes(reference)
                if key in seen:
                    continue
                seen.add(key)
                if len(seen) > 128:
                    _fail("E_BUDGET_EXHAUSTED")
                parent = self._details(view.get(reference))
                if parent["result"] is None or parent["result"]["admission"]["primitive_status"] != "valid":
                    _fail("E_DEPENDENCY_STALE")
                pending.append(parent)
        token = value["control_token"]
        if dispatch:
            if self.budgets is None or value["allocation"] is None:
                _fail("E_BUDGET_EXHAUSTED")
            allocation = self.budgets.require_committed(view, value["allocation"], as_of=now)
            if allocation["token"]["value"] != token:
                _fail("E_AUTHORITY_REQUIRED")
            return allocation
        return None

    def _artifact(self, raw, now):
        if raw is None:
            return None
        digest = self.payloads.put(raw)
        return {"digest": digest, "byte_length": len(raw), "media_type": "application/octet-stream",
            "locator": {"kind": "whole_artifact", "uri": "urn:matter:semantic-response:" + digest},
            "availability": {"status": "available", "checked_at": now}}

    def _bytes(self, ref):
        if ref is None:
            return None
        read = self.payloads.read(ref)
        if read.status != "available":
            _fail("E_EVIDENCE_UNAVAILABLE")
        return read.data

    def _metadata(self, request, *, token, logical_request_id, attempt_id, phase, result=None,
                  access_context=None, allocation=None, parents=(), retry_of=None, source_execution=None):
        for identity in (logical_request_id, attempt_id):
            fragment(identity, "identifier")
        now = fragment(self.clock(), "known_time")
        packet = PreparedPacket(request["packet"], _prepared=True)
        sources = _refs(packet.value["dependencies"])
        visible = []
        def references(item, depth=0):
            if depth > 64:
                _fail("E_BUDGET_EXHAUSTED")
            if type(item) is dict:
                if all(key in item for key in ("scope_id", "namespace", "record_type", "id")):
                    visible.append(fragment(item, "pinned_ref"))
                for child in item.values():
                    references(child, depth + 1)
            elif type(item) is list:
                for child in item:
                    references(child, depth + 1)
            if len(visible) > 16384:
                _fail("E_BUDGET_EXHAUSTED")
        references(packet.state)
        if any(ref not in sources for ref in _refs(visible)):
            _fail()
        if access_context is not None and hasattr(access_context, "value"):
            access_context = access_context.value
        parent_refs = _refs(list(parents))
        if len(parent_refs) > 128 or any(item["record_type"] != "receipt" for item in parent_refs):
            _fail()
        for reference in (retry_of, source_execution):
            if reference is not None:
                fragment(reference, "receipt_dependency")
        value = None if result is None else _strip(result.value)
        neutral = native = None
        if result is not None:
            if not isinstance(result, BatchResult) or (phase != "reused" and result.value["batch_digest"] != Batch(request["batch"]).digest):
                _fail()
            for key in ("raw_response", "native_response"):
                raw = result.value.get(key, {})
                content = self._artifact(base64.b64decode(raw["base64"], validate=True), now) if raw.get("state") == "available" else None
                if key == "raw_response":
                    neutral = content
                else:
                    native = content
        key = execution_key(Batch(request["batch"]), rendered=request["rendered"], precision=_precision(request["precision"]),
            model_binding=request["model_binding"], parents=parent_refs, token=token, stage=request["stage"], dependencies=request["packet"]["dependencies"])
        data = {"schema_version": "1.0", "phase": phase, "logical_request_id": logical_request_id, "attempt_id": attempt_id,
            "retry_of": retry_of, "source_execution": source_execution, "request": request, "result": value,
            "neutral_response": neutral, "native_response": native,
            "normalized_digest": None if value is None else normalized_digest(value),
            "execution_key": key, "sources": sources, "control_token": token, "access_context": access_context,
            "allocation": allocation, "parents": parent_refs, "created_at": now}
        domain("semantic-execution", data)
        return data

    def _input(self, value):
        identity = canonical_digest(value, "matter.semantic.execution-observation.v1")
        return {"schema_version": "1.0", "scope_id": self.scope_id, "namespace": NAMESPACE, "record_type": "receipt", "id": identity,
            "provenance": {"origin": "evaluator", "producer": ENGINE, "recorded_at": value["created_at"],
                "parents": _refs([*value["sources"], *value["parents"], *[ref for ref in (value["retry_of"], value["source_execution"]) if ref is not None]])},
            "body": {"stage": "evaluation", "operation_id": value["attempt_id"], "recorded_at": value["created_at"],
                "outcome": "matter:semantic_" + value["phase"], "evidence": value["sources"], "details": domain("semantic-execution", value)}}

    def _details(self, record):
        value = record["body"]["details"]
        if value != domain("semantic-execution", value.get("value")):
            _fail()
        raw = deepcopy(record)
        raw.pop("creation_receipt", None)
        if raw != self._input(value["value"]):
            _fail()
        return value["value"]

    def _validate_result(self, value):
        result = value["result"]
        if result is not None:
            checked(result, required=("schema_version", "batch_digest", "execution_status", "context", "precision_profile", "resolved_model", "model_unavailable_reason", "raw_response", "diagnostics", "faults", "admission", "timing", "usage", "cost"), optional=("native_response", "instrumentation"))
            if result["schema_version"] != "1.0" or result["precision_profile"] != value["request"]["precision"] or result["execution_status"] not in {"completed", "failed", "timed_out", "cancelled", "budget_exhausted", "unsupported"}:
                _fail()
            if value["phase"] != "reused" and result["context"] != value["request"]["batch"]["context"]:
                _fail()
            timing = checked(result["timing"], required=("called", "started", "completed"))
            if type(timing["called"]) is not bool:
                _fail()
            for name in ("started", "completed"):
                if timing[name] is not None:
                    fragment(timing[name], "known_time")
            if "instrumentation" in result:
                instrument = ExecutionInstrumentation(result["instrumentation"])
                if instrument.value != result["instrumentation"]:
                    _fail()
                if value["phase"] != "reused" and any(instrument.value[name] not in (None, value[name]) for name in ("logical_request_id", "attempt_id")):
                    _fail()
                usage = instrument.value["usage"]
            else:
                usage = None
            if result["usage"] != ({"value": None, "reason": "not_measured_by_this_interface"} if usage is None else {"value": usage, "reason": None}) or result["cost"] != {"value": None, "reason": "price_basis_not_supplied"}:
                _fail()
            allowed = ExecutionFault.CODES | {"original_wire_required", "response_byte_limit", "invalid_response", "missing_answer", "unexpected_answer", "duplicate_answer", "wrong_primitive", "invalid_primitive", "unsupported_capability", "request_budget", "deadline_before_dispatch", "executor_failed", "native_response_budget", "clock_reversed", "deadline_after_dispatch"}
            if type(result["faults"]) is not list or len(result["faults"]) > 512:
                _fail()
            for fault in result["faults"]:
                checked(fault, required=("code", "path"), optional=("id",))
                if fault["code"] not in allowed or type(fault["path"]) is not list or any(type(item) not in (int, str) for item in fault["path"]):
                    _fail()
        if result is None:
            if value["phase"] not in {"started", "unknown", "observed"} or any(value[key] is not None for key in ("neutral_response", "native_response", "normalized_digest")):
                _fail()
            return
        if value["phase"] in {"started", "unknown"} or (value["phase"] != "reused" and result.get("batch_digest") != Batch(value["request"]["batch"]).digest):
            _fail()
        if normalized_digest(result) != value["normalized_digest"]:
            _fail()
        raw = self._bytes(value["neutral_response"])
        native = self._bytes(value["native_response"])
        for data, key in ((raw, "raw_response"), (native, "native_response")):
            artifact = result.get(key)
            if data is not None and (not artifact or artifact.get("sha256") != source_digest(data) or artifact.get("byte_length") != len(data)):
                _fail()
            if data is None and artifact is not None and artifact.get("state") == "available":
                _fail()
        if raw is None and (result["diagnostics"] or result["resolved_model"] is not None or result["admission"]["primitive_status"] != "invalid"):
            _fail()
        if raw is not None:
            replay = normalize_response(Batch(value["request"]["batch"]), raw, precision=_precision(value["request"]["precision"])).value
            for key in ("diagnostics", "resolved_model", "model_unavailable_reason"):
                if result.get(key) != replay[key]:
                    _fail()
            if result["raw_response"] != _strip(replay)["raw_response"]:
                _fail()
            # A timeout/other original execution failure can NEVER be promoted
            # merely because some returned bytes happen to parse on replay.
            if result["execution_status"] == "completed":
                for key in ("admission", "faults"):
                    if result.get(key) != replay[key]:
                        _fail()
        if result["execution_status"] != "completed" and result["admission"]["primitive_status"] != "invalid":
            _fail()
        if result.get("admission", {}).get("consequential_use") is not False or result.get("admission", {}).get("qualification_status") != "unknown":
            _fail()

    def prepare(self, value, *, command_id, idempotency_key, _retain_refusal=False, qualify=None):
        value = domain("semantic-execution", value)["value"]
        raw = self._input(value)
        token = value["control_token"]
        command = {"schema_version": "1.0", "operation": "record_semantic_execution", "command_id": command_id,
            "idempotency_key": idempotency_key, "scope_id": self.scope_id, "actor": token["actor"],
            "authority": entity_ref(token["authority"]), "expected_revisions": [], "body": {"receipt": raw}}
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            try:
                self._inspect(view, value)
                self._classify(view, value, qualify)
            except ContractError:
                if not _retain_refusal:
                    raise
            command["expected_revisions"] = sorted([pin(item) for item in view.records.values()], key=canonical_bytes)
        return validate_command(command)

    def _inspect(self, view, value):
        self._request(view, value["request"], value["control_token"], value["access_context"])
        self._validate_result(value)
        if value["allocation"] is not None:
            if value["allocation"]["scope_id"] != self.scope_id:
                _fail("E_SCOPE_FORBIDDEN")
            allocated = _value(view.get(value["allocation"]), "budget-reservation")
            if allocated["status"] != "committed" or allocated["token"]["value"] != value["control_token"]:
                _fail("E_AUTHORITY_REQUIRED")
        self._current(view, value, dispatch=value["phase"] == "started")
        expected_key = execution_key(Batch(value["request"]["batch"]), rendered=value["request"]["rendered"],
            precision=_precision(value["request"]["precision"]), model_binding=value["request"]["model_binding"],
            parents=value["parents"], token=value["control_token"], stage=value["request"]["stage"], dependencies=value["request"]["packet"]["dependencies"])
        if expected_key != value["execution_key"] or compare_times(value["created_at"], self.clock()) == 1:
            _fail()
        for ref in _refs([*value["parents"], *[ref for ref in (value["retry_of"], value["source_execution"]) if ref is not None]]):
            record = view.get(ref)
            parent = self._details(record)
            self._audit(view, parent)
            if ref in value["parents"]:
                self._current(view, parent)
                if parent["result"] is None or parent["result"]["admission"]["primitive_status"] != "valid":
                    _fail("E_DEPENDENCY_STALE")
            if ref == value["retry_of"] and (parent["logical_request_id"] != value["logical_request_id"] or parent["attempt_id"] == value["attempt_id"]):
                _fail()
        address = attempt_ref(self.scope_id, value["logical_request_id"], value["attempt_id"])
        old = _lookup(view, address)
        if old is not None:
            previous = _value(old, "semantic-execution-attempt")
            if value["phase"] not in {"completed", "unknown"} or previous["phase"] != "started" or previous["request_digest"] != self._request_digest(value["request"]):
                _fail("E_IDEMPOTENCY_CONFLICT")
            started = self._details(view.get(previous["execution"]))
            if value["request"] != started["request"] or any(value[field] != started[field] for field in ("control_token", "access_context", "allocation", "parents", "retry_of", "sources")) or compare_times(value["created_at"], started["created_at"]) == -1:
                _fail()
        elif value["phase"] in {"completed", "unknown"}:
            _fail("E_DEPENDENCY_STALE")
        if value["source_execution"] is not None:
            source = self._details(view.get(value["source_execution"]))
            self._current(view, source)
            if (value["phase"] != "reused" or source["execution_key"] != value["execution_key"] or
                    source["result"] != value["result"] or source["normalized_digest"] != value["normalized_digest"]):
                _fail()
        elif value["phase"] == "reused":
            _fail()
        if value["phase"] == "started" and value["allocation"] is not None:
            view.watchers(self._watch(value["allocation"]))
        if expected_key is not None:
            _lookup(view, cache_ref(self.scope_id, expected_key))
        return old

    def commit(self, command, *, _claimed=None, qualify=None, _classification=None):
        command = validate_command(command)
        if command["operation"] != "record_semantic_execution" or command["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        raw = command["body"]["receipt"]
        value = self._details(raw)
        if command["actor"] != value["control_token"]["actor"] or command["authority"] != entity_ref(value["control_token"]["authority"]):
            _fail("E_AUTHORITY_REQUIRED")
        def materialize(tx):
            view = _Reads(tx, self.scope_id)
            self._inspect(view, value)
            decision = self._classify(view, value, qualify)
            if _classification is not None:
                _classification.append(decision)
            if value["phase"] == "started":
                allocation = self._current(view, value, dispatch=True)
                used = {"calls": 0, "input_bytes": 0, "output_bytes": 0, "retries": 0, "elapsed_ms": 0}
                for row in view.watchers(self._watch(value["allocation"])):
                    caps = _value(row, "semantic-execution-attempt")["caps"]
                    for key in used:
                        used[key] += caps.get(key, 0)
                caps = self._caps(value)
                if any(used[key] + caps[key] > allocation["amounts"].get(key, 0) for key in used):
                    _fail("E_BUDGET_EXHAUSTED")
            else:
                previous = _lookup(view, attempt_ref(self.scope_id, value["logical_request_id"], value["attempt_id"]))
                caps = {} if previous is None else _value(previous, "semantic-execution-attempt")["caps"]
            stored = tx.insert(raw)
            tx.put_projection(attempt_ref(self.scope_id, value["logical_request_id"], value["attempt_id"]),
                domain("semantic-execution-attempt", {"logical_request_id": value["logical_request_id"], "attempt_id": value["attempt_id"],
                    "phase": value["phase"], "execution": pin(stored), "request_digest": self._request_digest(value["request"]),
                    "allocation": value["allocation"], "caps": caps}),
                watch_keys=(() if value["allocation"] is None else (self._watch(value["allocation"]),)))
            result, binding, key = value["result"], value["request"]["model_binding"], value["execution_key"]
            if (key is not None and result is not None and result["admission"]["primitive_status"] == "valid" and
                    result["admission"]["exact_numeric"] is True and binding is not None and result["resolved_model"] == binding["model"]):
                address = cache_ref(self.scope_id, key)
                if _lookup(view, address) is None:
                    tx.put_projection(address, domain("semantic-execution-cache", {"key": key, "execution": pin(stored)}))
            if _claimed is not None:
                _claimed.append(True)
            return tx.success("recorded", {"execution": pin(stored)})
        def handler(tx):
            try:
                return materialize(tx)
            except StorageError as error:
                if error.code == "E_REVISION_CONFLICT":
                    _fail("E_DEPENDENCY_STALE")
                raise
        def audit(view):
            self._audit(view, value)
        return self.storage.execute(command, handler, replay_guard=audit, dependency_error_code="E_DEPENDENCY_STALE")

    def record(self, request, *, command_id, idempotency_key, **observed):
        value = self._metadata(request, **observed)
        return self.commit(self.prepare(value, command_id=command_id, idempotency_key=idempotency_key))

    def read(self, reference):
        with self.storage.snapshot() as view:
            record = view.get(fragment(reference, "receipt_dependency"))
            value = self._details(record)
            self._audit(view, value)
            self._validate_result(value)
            return deepcopy(record)

    def replay(self, reference):
        record = self.read(reference)
        value = self._details(record)
        if value["result"] is None:
            return None
        result = deepcopy(value["result"])
        for field, artifact in (("raw_response", "neutral_response"), ("native_response", "native_response")):
            raw = self._bytes(value[artifact])
            if raw is not None:
                result[field]["base64"] = base64.b64encode(raw).decode("ascii")
        return BatchResult(result, _factory=True)

    def lookup(self, request, *, token, parents=(), access_context=None, qualify=None):
        key = execution_key(Batch(request["batch"]), rendered=request["rendered"], precision=_precision(request["precision"]),
            model_binding=request["model_binding"], parents=parents, token=token, stage=request["stage"], dependencies=request["packet"]["dependencies"])
        if key is None:
            return None
        with self.storage.snapshot() as view:
            self._request(view, request, token, access_context)
            cached = _lookup(view, cache_ref(self.scope_id, key))
            if cached is None:
                return None
            record = view.get(_value(cached, "semantic-execution-cache")["execution"])
            value = self._details(record)
            self._current(view, value)
            self._validate_result(value)
            if (value["execution_key"] != key or value["result"] is None or
                    value["result"]["admission"]["primitive_status"] != "valid" or value["result"]["admission"]["exact_numeric"] is not True):
                _fail()
            decision = {"status": "unknown", "certificate": None}
            if qualify is not None:
                decision = qualify(view=view, execution=deepcopy(record), request=deepcopy(request), as_of=self.clock())
                checked(decision, required=("status", "certificate"))
                if decision["status"] != "qualified":
                    return None
                fragment(decision["certificate"], "component_ref")
            return {"execution": pin(record), "qualification": decision}

    def _watch(self, allocation):
        return "semantic-allocation-" + canonical_digest(allocation, "matter.semantic-allocation.v1")

    def _caps(self, value):
        context = value["request"]["batch"]["context"]
        return {"calls": 1, "input_bytes": context["max_request_bytes"], "output_bytes": context["max_response_bytes"],
            "retries": int(value["retry_of"] is not None), "elapsed_ms": self._elapsed_cap(context["deadline"], value["created_at"])}

    def run(self, request, *, executor, token, logical_request_id, attempt_id, allocation,
            parents=(), retry_of=None, access_context=None, dispatch=None, qualify=None, reuse=True):
        """One physical attempt, durably claimed; retries require a NEW attempt ID.

        Protected/provider requests require an explicit actual guarded dispatcher.
        A recovered started attempt is outcome-unknown and is never auto-resubmitted.
        No database snapshot remains open across external work.
        """
        address = attempt_ref(self.scope_id, logical_request_id, attempt_id)
        existing = None
        with self.storage.snapshot() as view:
            old = _lookup(view, address)
            if old is not None:
                value = _value(old, "semantic-execution-attempt")
                if value["request_digest"] != self._request_digest(request):
                    _fail("E_IDEMPOTENCY_CONFLICT")
                record = view.get(value["execution"])
                self._audit(view, self._details(record))
                reference = pin(record)
                existing = {"status": value["phase"], "execution": reference, "dispatched": False, "reused": value["phase"] == "reused"}
        if existing is not None:
            existing["result"] = None if existing["status"] == "started" else self.replay(existing["execution"])
            return existing
        cached = self.lookup(request, token=token, parents=parents, access_context=access_context, qualify=qualify) if reuse else None
        if cached is not None:
            original = self.read(cached["execution"])
            material = self._details(original)
            value = self._metadata(request, token=token, logical_request_id=logical_request_id, attempt_id=attempt_id,
                phase="reused", result=self.replay(pin(original)), access_context=access_context, allocation=allocation,
                parents=parents, source_execution=pin(original))
            # Exact reuse identity intentionally omits ephemeral Batch IDs. The
            # immutable original result keeps its ORIGINAL batch digest/context.
            value["result"] = material["result"]
            value["neutral_response"], value["native_response"] = material["neutral_response"], material["native_response"]
            value["normalized_digest"] = material["normalized_digest"]
            command = self.prepare(value, command_id="reuse-" + attempt_id, idempotency_key="reuse-" + canonical_digest(address, "matter.semantic.command.v1"), qualify=qualify, _retain_refusal=True)
            classified = []
            recorded = self.commit(command, qualify=qualify, _classification=classified)
            if recorded["status"] != "success":
                return {"status": "refused", "operation": recorded, "dispatched": False, "reused": False}
            return {"status": "reused", "execution": recorded["body"]["execution"], "result": self.replay(pin(original)),
                "dispatched": False, "reused": True, "original_execution": pin(original), "qualification": classified[-1] if classified else cached["qualification"]}
        request = self._clip_request(request, allocation)
        value = self._metadata(request, token=token, logical_request_id=logical_request_id, attempt_id=attempt_id,
            phase="started", access_context=access_context, allocation=allocation, parents=parents, retry_of=retry_of)
        identity = canonical_digest(address, "matter.semantic.command.v1")
        command = self.prepare(value, command_id="start-" + identity, idempotency_key="start-" + identity)
        claimed = []
        begun = self.commit(command, _claimed=claimed)
        if begun["status"] != "success" or not claimed:
            return {"status": "refused" if begun["status"] != "success" else "started", "operation": begun,
                "execution": begun.get("body", {}).get("execution"), "result": None, "dispatched": False, "reused": False}
        batch, profile = Batch(request["batch"]), _precision(request["precision"])
        with self.storage.snapshot() as view:
            self._current(view, value, dispatch=True)
        protected = "access_context" in batch.value["state"] or batch.value["context"]["mode"] == "provider_shadow"
        if protected and dispatch is None:
            _fail("E_AUTHORITY_REQUIRED")
        try:
            result = (execute_batch(executor, batch, clock=self.clock, precision=profile) if dispatch is None else
                dispatch(batch=batch, stage_input={"packet": request["packet"], "rendered_questions": request["rendered"]},
                    executor=executor, clock=self.clock, precision=profile))
            if not isinstance(result, BatchResult) or result.value["batch_digest"] != batch.digest:
                result = None
        except Exception:
            # An opaque injected boundary may have called the provider. Never
            # claim a known zero or retry it implicitly.
            result = None
        completion = self._metadata(request, token=token, logical_request_id=logical_request_id, attempt_id=attempt_id,
            phase="completed" if result is not None else "unknown", result=result, access_context=access_context,
            allocation=allocation, parents=parents, retry_of=retry_of)
        recorded = self.commit(self.prepare(completion, command_id="finish-" + identity, idempotency_key="finish-" + identity, _retain_refusal=True))
        return {"status": completion["phase"] if recorded["status"] == "success" else "refused", "operation": recorded,
            "execution": recorded.get("body", {}).get("execution"), "result": result, "dispatched": True, "reused": False}

    def history(self, logical_request_id, attempt_id):
        """Current READ-authorized immutable observations, including interrupted starts."""
        with self.storage.snapshot() as view:
            rows = view.history(attempt_ref(self.scope_id, logical_request_id, attempt_id))
            records = []
            for row in rows:
                record = view.get(_value(row, "semantic-execution-attempt")["execution"])
                self._audit(view, self._details(record))
                self._validate_result(self._details(record))
                records.append(record)
            return records

    def attempt(self, idempotency_key):
        """Inspect a durable refused operation under present original-source READ rights."""
        with self.storage.snapshot() as view:
            journal = view.command_receipt(idempotency_key)
            command = journal["command"]
            if command["operation"] != "record_semantic_execution":
                _fail()
            self._audit(view, self._details(command["body"]["receipt"]))
            return journal

    def record_stage_batch(self, run, index, *, token, attempt_id, command_id, idempotency_key,
                           parent_executions=(), access_context=None, precision=None, model_binding=None):
        """Persist an ALREADY-executed StageRun batch, including an unknown result.

        `parent_executions` binds each uncommitted parent trace component exactly
        to a real stored execution receipt. This records observation evidence; it
        does not claim the stage was durably authorized by this recorder before I/O.
        """
        from .stages import StageRun, StageInput
        if not isinstance(run, StageRun) or type(index) is not int or not 0 <= index < len(run.value["batches"]):
            _fail()
        value = run.value
        item = value["batches"][index]
        batch = Batch(item["batch"])
        members = [(name, StageInput(packet=PreparedPacket(raw["packet"], _prepared=True),
                    rendered_questions=[RenderedQuestion(rendered, _factory=True) for rendered in raw["rendered_questions"]],
                    context=raw["context"], transform=raw["transform"], parents=raw["parents"], candidate_count=raw["candidate_count"]))
                   for name, raw in value["inputs"].items() if value["stages"][name].get("batch_index") == index]
        if not members:
            _fail()
        all_rendered = {item.question.value["id"]: item for _, material in members for item in material.rendered_questions}
        rendered = [all_rendered[question["id"]] for question in batch.value["questions"]]
        bindings = {}
        for binding in parent_executions:
            checked(binding, required=("trace", "execution"))
            fragment(binding["trace"], "component_ref"); fragment(binding["execution"], "receipt_dependency")
            key = canonical_bytes(binding["trace"])
            if key in bindings:
                _fail()
            bindings[key] = binding["execution"]
        traces = {canonical_bytes(trace): trace for _, material in members for trace in material.value["parents"]}
        if set(bindings) != set(traces):
            _fail()
        # The exact per-member transformations and original traces remain in
        # the request; actual stored parents are separate core provenance pins.
        stage = {"plan": value["plan"], "members": [{"stage_id": name, "transform": material.value["transform"],
            "parent_traces": material.value["parents"]} for name, material in members]}
        request = self.request(batch, packet=members[0][1].packet, rendered_questions=rendered, token=token,
            precision=precision, model_binding=model_binding, access_context=access_context, stage=stage)
        result = None if item["result"] is None else BatchResult(item["result"], _factory=True)
        return self.record(request, command_id=command_id, idempotency_key=idempotency_key, token=token,
            logical_request_id=value["run_id"], attempt_id=attempt_id, phase="observed", result=result,
            parents=[bindings[key] for key in sorted(bindings)], allocation=value["reservation"], access_context=access_context)

    def _request_digest(self, request):
        submitted = deepcopy(request)
        submitted["batch"]["context"]["deadline"] = submitted["requested_deadline"]
        return canonical_digest(submitted, "matter.semantic.execution-request.v1")

    def _elapsed_cap(self, deadline, now):
        floor = milliseconds(deadline, now)
        fraction = (int(known_time_key(deadline)[1]) - int(known_time_key(now)[1])) % 1000000
        return max(0, floor + int(fraction != 0))

    def _clip_request(self, request, allocation):
        with self.storage.snapshot() as view:
            if self.budgets is None:
                _fail("E_BUDGET_EXHAUSTED")
            admitted = self.budgets.require_committed(view, allocation)
            used = sum(_value(row, "semantic-execution-attempt")["caps"].get("elapsed_ms", 0)
                for row in view.watchers(self._watch(allocation)))
            remaining = admitted["amounts"].get("elapsed_ms", 0) - used
            now = fragment(self.clock(), "known_time")
        if remaining <= 0:
            # Retain the bounded rejected start command durably. The writer
            # refuses its positive caps before any injected work can run.
            return deepcopy(request)
        # Truncating submicrosecond clock detail here shortens the deadline; it
        # never extends a reservation. Caps use exact integer nanosecond residue.
        at = datetime.fromisoformat(now["value"].replace("Z", "+00:00")) + timedelta(milliseconds=remaining)
        limit = {"state": "known", "value": at.isoformat(timespec="microseconds").replace("+00:00", "Z"), "precision": "microsecond"}
        request = deepcopy(request)
        for bound in (admitted["expires_at"], limit):
            if compare_times(bound, request["batch"]["context"]["deadline"]) == -1:
                request["batch"]["context"]["deadline"] = bound
        if compare_times(request["batch"]["context"]["deadline"], now) != 1:
            _fail("E_BUDGET_EXHAUSTED")
        return request

    def _classify(self, view, value, qualifier):
        if value["phase"] != "reused" or qualifier is None:
            return {"status": "unknown", "certificate": None}
        original = view.get(value["source_execution"])
        decision = qualifier(view=view, execution=deepcopy(original), request=deepcopy(value["request"]), as_of=self.clock())
        checked(decision, required=("status", "certificate"))
        if decision["status"] != "qualified":
            _fail("E_DEPENDENCY_STALE")
        fragment(decision["certificate"], "component_ref")
        return decision

    def view_result(self, outcome, batch):
        """Derive a CURRENT-batch observation without changing original evidence.

        This is a detached stage view, not a new physical execution receipt.
        `execution_observation` points to the actual durable observation and its
        immutable original binding. Original failures can never be promoted.
        """
        if not isinstance(batch, Batch) or outcome.get("status") not in {"completed", "reused", "observed"} or outcome.get("execution") is None:
            _fail("E_EVIDENCE_UNAVAILABLE")
        record = self.read(outcome["execution"])
        value = self._details(record)
        if value["result"] is None:
            _fail("E_EVIDENCE_UNAVAILABLE")
        original_batch = Batch(value["request"]["batch"])
        old, current = original_batch.value, batch.value
        if (any(old[key] != current[key] for key in ("scope_id", "state", "packet_digest", "questions")) or
                any(old["context"][key] != current["context"][key] for key in ("provider", "transport", "requested_model", "adapter_version", "mode"))):
            _fail()
        with self.storage.snapshot() as view:
            self._current(view, value)
        original = self.replay(pin(record)).value
        result = deepcopy(original)
        result.update(batch_digest=batch.digest, context=current["context"])
        raw = self._bytes(value["neutral_response"])
        if raw is not None:
            admitted = normalize_response(batch, raw, precision=_precision(value["request"]["precision"])).value
            if admitted["admission"]["primitive_status"] != "valid":
                result["admission"]["primitive_status"] = "invalid"
                result["faults"] = sorted({canonical_bytes(item): item for item in [*result["faults"], *admitted["faults"]]}.values(), key=canonical_bytes)
        reused = value["phase"] == "reused"
        if reused:
            result["timing"] = {"called": False, "started": None, "completed": fragment(self.clock(), "known_time")}
            result["usage"] = {"value": None, "reason": "reused_original_execution"}
            result["cost"] = {"value": None, "reason": "reused_original_execution"}
            result.pop("instrumentation", None)
        if compare_times(fragment(self.clock(), "known_time"), current["context"]["deadline"]) >= 0:
            result["execution_status"] = "timed_out"
            result["admission"]["primitive_status"] = "invalid"
            result["faults"].append({"code": "deadline_before_dispatch", "path": []})
        result["execution_observation"] = {"execution": pin(record), "source_execution": value["source_execution"],
            "original_batch_digest": original["batch_digest"], "current_batch_digest": batch.digest, "reused": reused,
            "independent_trial": False if reused else None, "new_provider_attempt": not reused and original["timing"]["called"]}
        return BatchResult(result, _factory=True)
