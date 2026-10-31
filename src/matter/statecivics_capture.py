"""MAT-084 optional, unqualified study admission. No assessment or sender.

Version 1.1 remains a consumer-conformance candidate until KS-1124 has run its
vectors. The trusted host owns actual capture history and its atomic sink.
"""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator
from referencing import Registry

from ._rule_values import FrozenValue, descriptor, fragment
from .attention import select_attention_treatment
from .access import _public
from .budgets import _Reads
from .canonical import CanonicalError, canonical_bytes, canonical_digest, loads
from .contexts import _active
from .contracts import ContractError, _FORMAT_CHECKER
from .controls import control_effect
from .dependencies import capture_dependencies, register_dependency, registration_ref, require_current_dependency
from .dispositions import DispositionDefinition
from .lifecycle import _pointer
from .semantic.packets import PreparedPacket
from .semantic.receipts import ExecutionReceiptStore, _precision
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times
from .statecivics_monitoring import (
    AdmittedMonitoring, _HOST_FIELDS, _fail, conveyed_capture_identity,
    monitoring_questions, monitoring_refusal,
)


VERSION = "monitoring-handoff/1.1.0"
NAMESPACE = "statecivics.monitoring.capture"
ENGINE = descriptor("matter.statecivics", "capture-admission", "1.1", {
    "use": "isolated-capture-only", "qualification": "unqualified", "authority": "none"},
    "matter.monitoring-capture-engine.v1")


@lru_cache(maxsize=16)
def _validator(kind):
    schema = loads(files("matter._schemas").joinpath("monitoring-handoff-v1.1.schema.json").read_bytes())
    return Draft202012Validator({"$ref": "#/$defs/" + kind, "$defs": schema["$defs"]},
        registry=Registry(), format_checker=_FORMAT_CHECKER)


def _validate(value, kind):
    try:
        if len(canonical_bytes(value)) > 1048576 or not _validator(kind).is_valid(value):
            _fail("E_SCHEMA_INVALID")
    except (CanonicalError, TypeError, RecursionError):
        _fail("E_SCHEMA_INVALID")
    return deepcopy(value)


def validate_capture_handoff(value, kind="request"):
    if kind not in {"request", "result", "refusal"}:
        _fail("E_SCHEMA_INVALID")
    try:
        if type(value) in {str, bytes}:
            if len(value) > 65536:
                _fail("E_SCHEMA_INVALID")
            value = loads(value)
        if type(value) is dict and value.get("contract_version") != VERSION:
            _fail("E_VERSION_UNSUPPORTED")
        if len(canonical_bytes(value)) > 65536:
            _fail("E_SCHEMA_INVALID")
    except (CanonicalError, TypeError, RecursionError):
        _fail("E_SCHEMA_INVALID")
    return _validate(value, kind)


def capture_refusal(error, *, request_id=None):
    result = monitoring_refusal(error, request_id=request_id)
    result["contract_version"] = VERSION
    return validate_capture_handoff(result, "refusal")


@lru_cache(maxsize=16)
def _schema(kind):
    return descriptor("matter.statecivics", "capture-" + kind, "1.1",
        _validator(kind).schema, "matter.monitoring-capture-schema.v1")


def _wrap(kind, value):
    return {"schema": deepcopy(_schema(kind)), "value": _validate(value, kind)}


def _unwrap(kind, value):
    if type(value) is not dict or set(value) != {"schema", "value"} or value["schema"] != _schema(kind):
        _fail("E_EVIDENCE_INVALID")
    return _validate(value["value"], kind)


class MonitoringCapturePolicy(FrozenValue):
    """Explicit host study regions; no defaults, certificate or accuracy claim."""

    def __init__(self, value):
        value = _validate(value, "capture_policy")
        _precision(value["precision"])
        for region in value["regions"].values():
            if not Decimal(region["negative_maximum"]) < Decimal(region["positive_minimum"]):
                _fail()
        for path in [*value["material_paths"], *([] if value["native_baseline"] is None else value["native_baseline"]["paths"].values())]:
            if "~" in path.replace("~0", "").replace("~1", ""):
                _fail()
        if value["native_baseline"] is not None and set(value["native_baseline"]["paths"]) != set(value["material_paths"]):
            _fail()
        expected = {s.value["family"].split(".")[-1]: s.reference for s in monitoring_questions()}
        if value["questions"] != expected:
            _fail()
        self._freeze(value)

    @property
    def reference(self):
        v = self.value
        return descriptor(v["namespace"], v["id"], v["semantic_version"], v, "matter.monitoring-capture-policy.v1")

    @property
    def material_contract(self):
        return descriptor("matter.statecivics", "capture-material", "1.1",
            {"paths": sorted(self.value["material_paths"])}, "matter.monitoring-capture-material-contract.v1")

    def classify(self, role, probability):
        if role not in self.value["regions"]:
            _fail("E_SCHEMA_INVALID")
        _validate(probability, "decimal_probability")
        number = Decimal(probability)
        region = self.value["regions"][role]
        return ("positive" if number >= Decimal(region["positive_minimum"]) else
                "negative" if number <= Decimal(region["negative_maximum"]) else "unknown")


class CaptureReuseEligibility(FrozenValue):
    """Proof of bounded study reuse, never a qualified semantic admission."""

    def __init__(self, value, *, _factory=False):
        if not _factory:
            _fail("E_AUTHORITY_REQUIRED")
        self._freeze(value)


class CaptureAdmission(FrozenValue):
    def __init__(self, reference, value, *, _factory=False):
        if not _factory:
            _fail("E_AUTHORITY_REQUIRED")
        self._freeze({"reference": fragment(reference, "pinned_ref"), "value": _validate(value, "admission_record")})

    @property
    def reference(self):
        return self.value["reference"]


@dataclass(frozen=True)
class ObservedMonitoringCapture:
    """Trusted host's authorized read of a real, successful isolated capture.

    Construct in the injected capture_history resolver after checking the actual
    row, owner, outcome and READ authority. A model/DTO cannot supply this object.
    """
    receipt: dict
    admission_reference: dict
    owner: dict
    candidate: dict
    material: dict
    material_contract: dict
    captured_at: dict


def _require_capture_precision(policy, request):
    if request["precision"] != policy.value["precision"]:
        _fail("E_POLICY_INVALID")


def _source_identity(state):
    # Only the transport's permission snapshot differs across authorized readers.
    return canonical_digest({k: v for k, v in state.items() if k != "access_context"},
        "matter.monitoring-source-reading.v1")


def _execution(view, receipts, reference):
    record = view.get(fragment(reference, "pinned_ref"))
    value = receipts._details(record)
    receipts._request(view, value["request"], value["control_token"], value["access_context"])
    receipts._validate_result(value)
    receipts._current(view, value)
    result = value["result"]
    if (value["phase"] not in {"completed", "reused", "observed"} or result is None or
            result["execution_status"] != "completed" or result["admission"]["primitive_status"] != "valid" or
            result["admission"]["exact_numeric"] is not True or result["resolved_model"] is None):
        _fail("E_EVIDENCE_UNAVAILABLE")
    return record, value


def _original_execution(view, receipts, record, metadata, *, policy=None):
    """Reused observations retain their original work token and whole result."""
    seen = set()
    while metadata["phase"] == "reused":
        key = canonical_bytes(pin(record))
        if key in seen or len(seen) >= 128:
            _fail("E_BUDGET_EXHAUSTED")
        seen.add(key)
        prior, value = _execution(view, receipts, metadata["source_execution"])
        if (value["execution_key"] != metadata["execution_key"] or
                value["normalized_digest"] != metadata["normalized_digest"] or
                value["result"] != metadata["result"]):
            _fail("E_EVIDENCE_INVALID")
        if policy is not None:
            _require_capture_precision(policy, value["request"])
        record, metadata = prior, value
    return record, metadata


def capture_source_reading_eligibility(admitted, *, receipts, execution):
    """One real source-only reading; a fresh, separate recipient access gate."""
    admitted.require_current()
    if not isinstance(receipts, ExecutionReceiptStore) or receipts.controls is not admitted.host.access.controls:
        _fail("E_AUTHORITY_REQUIRED")
    with receipts.storage.snapshot() as view:
        record, state = _source_reading(view, admitted, receipts, execution)
    admitted.require_current()
    return CaptureReuseEligibility({"permitted_use": "capture_only", "qualification": "unqualified",
        "consequential_use": False, "source_only": True, "execution": pin(record),
        "source_identity": _source_identity(state), "recipient": admitted.host.binding,
        "access_context": admitted.host.access_context.reference}, _factory=True)


def _source_reading(view, admitted, receipts, execution):
    from .civic_attention import source_questions
    record, value = _execution(view, receipts, execution)
    _original_execution(view, receipts, record, value)
    state = value["request"]["batch"]["state"]
    if "monitoring" in state or "comparison" in state or _source_identity(state) != _source_identity(admitted.source_packet.state):
        _fail("E_SCOPE_FORBIDDEN")
    if [q["manifest"]["specification"] for q in value["request"]["rendered"]] != [s.reference for s in source_questions()]:
        _fail()
    admitted.host.access.require_packet(view, admitted.host.access_context, admitted.source_packet.state)
    # Eligibility covers the real transitive source read closure, not only
    # the visible source fields. A reader with private protected dependencies
    # must not become shareable by omitting them from rendered text.
    roots = receipts._audit(view, value)
    admitted.host.access.require_current(view, admitted.host.access_context,
        references=[reference for reference in roots if _public(reference)])
    return record, state


class CaptureAdmissionService:
    """Small projection composition over native controls/storage/receipt ports."""

    def __init__(self, storage, *, receipts, controls, clock, capture_history=None):
        if (not isinstance(receipts, ExecutionReceiptStore) or receipts.storage is not storage or
                receipts.controls is not controls or not callable(clock) or
                (capture_history is not None and not callable(capture_history))):
            _fail("E_AUTHORITY_REQUIRED")
        self.storage, self.scope_id = storage, storage.scope_id
        self.receipts, self.controls, self.clock, self.capture_history = receipts, controls, clock, capture_history

    def _address(self, prefix, identity):
        return {"scope_id": self.scope_id, "namespace": NAMESPACE, "record_type": PROJECTION_TYPE,
                "id": prefix + "-" + identity}

    def _command(self, payload, target, *, actor, authority, command_id, idempotency_key):
        payload = _wrap("command_payload", payload)
        # Preserve an exact original command on retry, including its timestamp.
        with self.storage.snapshot() as view:
            try:
                old = view.command_receipt(idempotency_key)["command"]
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
            else:
                record = old["body"]["control"]
                if (old["command_id"] != command_id or old["actor"] != actor or old["authority"] != entity_ref(authority)
                        or record["body"]["effect"]["value"]["payload"] != payload or record["body"]["scope"]["targets"] != [target]):
                    _fail("E_IDEMPOTENCY_CONFLICT")
                return old, True
        now = self.clock()
        record = {"schema_version": "1.0", "record_type": "control", "scope_id": self.scope_id,
            "namespace": NAMESPACE, "id": "capture-control-" + command_id,
            "provenance": {"origin": "host", "producer": ENGINE, "recorded_at": now, "parents": []},
            "body": {"control_kind": "decision", "actor": actor, "authority": entity_ref(authority),
                "scope": {"scope_id": self.scope_id, "targets": [target]}, "control_epoch": 0,
                "effective_from": now, "effective_until": {"state": "unknown", "reason": "not_applicable"},
                "effect": control_effect("disposition", "Capture-only study record, no qualification or delivery.", payload=payload)}}
        return {"schema_version": "1.0", "operation": "record_control", "command_id": command_id,
            "idempotency_key": idempotency_key, "scope_id": self.scope_id, "actor": actor,
            "authority": entity_ref(authority), "expected_revisions": [], "body": {"control": record}}, False

    def install_policy(self, policy, *, actor, authority, command_id, idempotency_key):
        if not isinstance(policy, MonitoringCapturePolicy):
            _fail()
        target = self._address("policy", policy.reference["digest"])
        command, replay = self._command({"action": "install_policy", "policy": policy.value}, target,
            actor=actor, authority=authority, command_id=command_id, idempotency_key=idempotency_key)
        if not replay:
            command = self.controls.prepare(command)
        def write(tx):
            result = self.controls._apply(tx)
            tx.put_projection(target, _wrap("policy_record", {"kind": "capture_policy", "policy": policy.value,
                "control": result["body"]["control"]}))
            return result
        result = self.storage.execute(command, write, replay_guard=lambda v: self.controls._audit(v, command, [target]))
        if result["status"] != "success":
            raise StorageError(result["error"]["code"], result["error"]["detail"])
        return pin(self.storage.get(target))

    def policy(self, view, admitted):
        reference = admitted._request["proposal_basis"]["capture_policy"]
        if admitted.require_policy_pin != reference:
            _fail("E_DEPENDENCY_STALE")
        admitted.output_access.require_current(view, admitted.output_context, references=[reference])
        record = view.get(reference)
        data = _unwrap("policy_record", record["value"])
        policy = MonitoringCapturePolicy(data["policy"])
        control = view.get(data["control"])
        if (entity_ref(record) != self._address("policy", policy.reference["digest"]) or
                control["provenance"]["origin"] != "host" or control["provenance"]["producer"] != ENGINE or
                control["body"]["scope"]["targets"] != [entity_ref(record)] or
                control["body"]["effect"]["value"]["payload"] != _wrap("command_payload", {"action": "install_policy", "policy": policy.value})):
            _fail("E_AUTHORITY_REQUIRED")
        return policy

    def _record(self, view, reference):
        stored = view.get(fragment(reference, "pinned_ref"))
        data = _unwrap("admission_record", stored["value"])
        control = view.get(data["control"])
        expected = {"action": "admit_capture", "command_digest": data["command_digest"],
            "execution": data["execution"], "policy": data["policy"]}
        if (stored["namespace"] != NAMESPACE or control["provenance"]["origin"] != "host" or
                control["provenance"]["producer"] != ENGINE or
                control["body"]["scope"]["targets"] != [entity_ref(stored)] or
                control["body"]["effect"]["value"]["payload"] != _wrap("command_payload", expected)):
            _fail("E_AUTHORITY_REQUIRED")
        return stored, data

    def _derive(self, view, admitted, execution, packet, current):
        policy = self.policy(view, admitted)
        record, metadata = _execution(view, self.receipts, execution)
        request, req = metadata["request"], admitted._request
        marker = descriptor("matter.statecivics", "monitoring-command", "1.0", {"digest": admitted.digest}, "matter.monitoring-binding.v1")
        if (request["packet"] != packet.value or request["batch"]["state"] != packet.state or
                type(request["stage"]) is not dict or
                request["stage"]["members"][0]["parent_traces"] != [marker] or
                request["batch"]["context"]["requested_model"] != req["evaluation"]["model"]):
            _fail("E_DEPENDENCY_STALE")
        if metadata["parents"] != list(admitted._execution_parents()):
            _fail("E_SCOPE_FORBIDDEN")
        if metadata["control_token"] != admitted.host.access_context.value["token"] or metadata["access_context"] != admitted.host.access_context.value:
            _fail("E_AUTHORITY_REQUIRED")
        _require_capture_precision(policy, request)
        if request["model_binding"] is None or request["model_binding"]["model"] != metadata["result"]["resolved_model"]:
            _fail("E_EVIDENCE_UNAVAILABLE")
        expected = [s.reference for s in monitoring_questions()]
        if [item["manifest"]["specification"] for item in request["rendered"]] != expected or req["evaluation"]["questions"] != expected:
            _fail()
        original, metadata = _original_execution(view, self.receipts, record, metadata, policy=policy)
        answers = {item["id"]: item for item in metadata["result"]["diagnostics"]}
        judgments = {}
        for role, question in zip(("objective", "novelty"), request["batch"]["questions"]):
            answer = answers.get(question["id"])
            if answer is None or answer["status"] != "valid" or answer["answer"] is None:
                _fail("E_EVIDENCE_UNAVAILABLE")
            judgments[role] = policy.classify(role, answer["answer"]["probability"])
        source_reading = req["proposal_basis"]["source_reading"]
        if source_reading is not None:
            _source_reading(view, admitted, self.receipts, source_reading)
        return admitted._proposal(view, policy, judgments, packet, current, pin(record), pin(original))

    def admit_capture(self, admitted, *, execution, command_id=None, idempotency_key=None):
        current = admitted.require_current()
        packet = admitted.audience_packet()
        target = self._address("admission", canonical_digest({"command": admitted.digest, "execution": execution}, "matter.capture-admission-slot.v1"))
        identity = target["id"]
        token = admitted.output_context.value["token"]
        payload = {"action": "admit_capture", "command_digest": admitted.digest,
            "execution": execution, "policy": admitted.require_policy_pin}
        command, replay = self._command(payload, target, actor=token["actor"], authority=token["authority"],
            command_id=command_id or identity, idempotency_key=idempotency_key or identity)
        if not replay:
            with self.storage.snapshot() as snapshot:
                reads = _Reads(snapshot, self.scope_id)
                # Registration proof reads are part of the same prepared command.
                deps = self._derive(reads, admitted, execution, packet, current)["projection"]["dependencies"]
                capture_dependencies(reads, scope_id=self.scope_id, as_of=self.clock(), positive=deps,
                    control_token=token, controls=self.controls)
                command["expected_revisions"] = sorted([pin(r) for r in reads.records.values()], key=canonical_bytes)
            command = self.controls.prepare(command)
        def write(tx):
            value = self._derive(tx, admitted, execution, packet, current)
            self.controls.require_current(tx, token, capability="assessment",
                targets=[entity_ref(r) for r in value["projection"]["dependencies"] if _public(r)])
            result = self.controls._apply(tx)
            value["control"] = result["body"]["control"]
            stored = tx.put_projection(target, _wrap("admission_record", value))
            deps = value["projection"]["dependencies"]
            manifest = capture_dependencies(tx, scope_id=self.scope_id, as_of=self.clock(), positive=deps,
                control_token=token, controls=self.controls)
            register_dependency(tx, pin(stored), manifest, as_of=self.clock(), controls=self.controls)
            return result
        def replay_guard(view):
            self._derive(view, admitted, execution, packet, current)
        result = self.storage.execute(command, write,
            replay_guard=replay_guard, dependency_error_code="E_DEPENDENCY_STALE")
        if result["status"] != "success":
            raise StorageError(result["error"]["code"], result["error"]["detail"])
        admitted.require_current()
        return self.current(admitted, pin(self.storage.get(target)))

    def current(self, admitted, reference):
        current = admitted.require_current()
        packet = admitted.audience_packet()
        with self.storage.snapshot() as view:
            stored, data = self._record(view, reference)
            if data["command_digest"] != admitted.digest:
                _fail("E_SCOPE_FORBIDDEN")
            require_current_dependency(view, registration_ref(reference), as_of=self.clock(), controls=self.controls)
            derived = self._derive(view, admitted, data["execution"], packet, current)
            if {k: v for k, v in data.items() if k != "control"} != derived:
                _fail("E_DEPENDENCY_STALE")
        return CaptureAdmission(pin(stored), data, _factory=True)


class AdmittedCaptureMonitoring(AdmittedMonitoring):
    _version = VERSION
    _host_fields = (*_HOST_FIELDS, "proposal_basis")
    _validate = staticmethod(validate_capture_handoff)

    def _execution_precision(self):
        if self._request["proposal_basis"]["kind"] == "native_attention":
            return super()._execution_precision()
        self.require_current()
        with self.host.capture_service.storage.snapshot() as view:
            policy = self.host.capture_service.policy(view, self)
        return _precision(policy.value["precision"])

    def _execution_parents(self):
        reference = self._request["proposal_basis"].get("source_reading")
        return () if reference is None else (reference,)

    def audience_packet(self):
        packet = super().audience_packet()
        reference = self._request["proposal_basis"].get("source_reading")
        if reference is None:
            return packet
        service = self.host.capture_service
        eligibility = capture_source_reading_eligibility(self, receipts=service.receipts, execution=reference)
        with service.storage.snapshot() as view:
            record = view.get(eligibility.value["execution"])
            metadata = service.receipts._details(record)
        data = packet.value
        data["state"]["monitoring"]["source_reading"] = {"execution": pin(record),
            "qualification": "unqualified", "consequential_use": False,
            "diagnostics": metadata["result"]["diagnostics"]}
        if reference not in data["dependencies"]:
            data["dependencies"].append(reference)
            data["dependencies"].sort(key=canonical_bytes)
        if len(canonical_bytes(data)) > 1048576:
            _fail("E_BUDGET_EXHAUSTED")
        return PreparedPacket(data, _prepared=True)

    def require_current(self):
        current = super().require_current()
        if self._request["proposal_basis"]["kind"] == "unqualified_model_capture":
            service = self.host.capture_service
            if (not isinstance(service, CaptureAdmissionService) or service.receipts.access is not self.host.access or
                    service.controls is not self.host.access.controls or current.capture_policy is None):
                _fail("E_AUTHORITY_REQUIRED")
            self.require_policy_pin = current.capture_policy
            with service.storage.snapshot() as view:
                service.policy(view, self)
        return current

    def _baseline_dependency(self):
        b = self._request["baseline"]
        if b.get("decision_basis") == "unqualified_model_capture":
            return "baseline_capture_admission", b["capture_admission_reference"]
        return super()._baseline_dependency()

    def _conveyed_material(self):
        baseline = self._request["baseline"]
        self._baseline_links = []
        if baseline["status"] == "no_observed_output":
            return None
        if baseline.get("decision_basis") != "unqualified_model_capture":
            material = super()._conveyed_material()
            if self._request["proposal_basis"]["kind"] == "native_attention":
                return material
            with self.host.capture_service.storage.snapshot() as view:
                policy = self.host.capture_service.policy(view, self)
                mapping = policy.value["native_baseline"]
                receipt = view.get(baseline["receipt"])
                decision = view.get(receipt["body"]["details"]["value"]["decision"])
                details = decision["body"]["details"]["value"]
                contract = details["material_contract"]
                assessment = view.get(details["assessment"])
                self._baseline_links = [r for refs in details["selections"].values() for r in refs]
                self._baseline_links += assessment["body"]["evidence_selection"]["references"]
            if mapping is None or mapping["material_contract"] != contract:
                _fail("E_DEPENDENCY_STALE")
            return {path: _pointer(material, selected) for path, selected in mapping["paths"].items()}
        service = self.host.capture_service
        if service is None or service.capture_history is None:
            _fail("E_AUTHORITY_REQUIRED")
        observed = service.capture_history(receipt=deepcopy(baseline["receipt"]),
            host_binding=deepcopy(self.host.binding), access_context=self.output_context)
        if not isinstance(observed, ObservedMonitoringCapture):
            _fail("E_AUTHORITY_REQUIRED")
        with service.storage.snapshot() as view:
            stored, old = service._record(view, baseline["capture_admission_reference"])
            admitted_at = view.get(old["control"])["provenance"]["recorded_at"]
            original = view.get(old["original_execution"])
            service.receipts._audit(view, service.receipts._details(original))
            service.receipts._validate_result(service.receipts._details(original))
            self.host.access.require_history(view, self.host.access_context,
                references=[r for r in old["projection"]["dependencies"] if r["record_type"] in {"observation", "claim", "assessment"}])
        expected_owner = {**{k: self.host.binding[k] for k in ("user_id", "workspace_id", "client_id")}, "intent_id": self._request["intent"]["id"]}
        stable = lambda ref: (ref["namespace"], ref["id"])
        prior = old["projection"]["context_components"]
        if (old["host_binding"] != self.host.binding or old["intent_id"] != expected_owner["intent_id"] or
                any(stable(prior[kind]) != stable(self._request["context_components"][kind]) for kind in ("purpose", "audience")) or
                old["projection"]["treatment"] == "quiet" or observed.owner != expected_owner or
                observed.receipt != baseline["receipt"] or observed.admission_reference != baseline["capture_admission_reference"] or
                entity_ref(observed.candidate) != entity_ref(old["candidate"]) or
                entity_ref(old["candidate"]) != entity_ref(self.host.current_state(expected_owner["intent_id"]).candidate)):
            _fail("E_SCOPE_FORBIDDEN")
        if (observed.material != old["material"] or observed.material_contract != old["material_contract"] or
                canonical_digest(observed.material, "matter.monitoring-conveyed-material.v1") != baseline["conveyed_material_digest"] or
                compare_times(observed.captured_at, self.host.clock()) > 0 or
                compare_times(observed.captured_at, admitted_at) < 0 or
                old["projection"]["intent_revision_id"] != baseline["intent_revision_id"]):
            _fail("E_EVIDENCE_UNAVAILABLE")
        self._baseline_links = [old["projection"]["source_finding_reference"], *[c["source"] for c in old["projection"]["citations"]]]
        return deepcopy(observed.material)

    def _native_result(self, result, record):
        value = record["body"]["details"]["value"]
        result.update(decision_basis={"kind": "native_attention", "attention_reference": pin(record)}, consequential_use=False,
            capture_key=conveyed_capture_identity(host_binding=self.host.binding, intent_id=self._request["intent"]["id"],
                candidate=self.host.current_state(self._request["intent"]["id"]).candidate,
                components=self._request["context_components"], material_digest=value["material_digest"],
                material_contract=value["material_contract"], baseline_reference=self._request["baseline"].get("receipt")))
        return result

    def project(self, **kwargs):
        if self._request["proposal_basis"]["kind"] != "native_attention":
            _fail("E_AUTHORITY_REQUIRED")
        return super().project(**kwargs)

    def admit_capture(self, *, execution, command_id=None, idempotency_key=None):
        self.require_current()
        if self._request["proposal_basis"]["kind"] != "unqualified_model_capture":
            _fail("E_AUTHORITY_REQUIRED")
        return self.host.capture_service.admit_capture(self, execution=execution,
            command_id=command_id, idempotency_key=idempotency_key)

    def project_capture(self, *, admission):
        self.require_current()
        if self._request["proposal_basis"]["kind"] != "unqualified_model_capture":
            _fail("E_AUTHORITY_REQUIRED")
        reference = admission.reference if isinstance(admission, CaptureAdmission) else admission
        actual = self.host.capture_service.current(self, reference)
        result = deepcopy(actual.value["value"]["projection"])
        result["decision_basis"]["capture_admission_reference"] = actual.reference
        result = self._validate(result, "result")
        self._projection = (deepcopy(result), {"capture_admission": actual.reference}, result["capture_key"])
        return result

    def _reproject(self, arguments):
        if "capture_admission" in arguments:
            return self.project_capture(admission=arguments["capture_admission"])
        return super()._reproject(arguments)

    def _capture_guard_current(self):
        current = self.require_current()
        if self._projection is not None and "capture_admission" in self._projection[1]:
            self.host.capture_service.current(self, self._projection[1]["capture_admission"])
        return current

    def _proposal(self, view, policy, judgments, packet, current, execution, original_execution):
        req = self._request
        finding = view.get(current.source_finding)
        material = {}
        for path in policy.value["material_paths"]:
            try:
                material[path] = _pointer(finding, path)
            except ContractError as error:
                if error.code != "E_EVIDENCE_INVALID":
                    raise
                material[path] = None
        digest = canonical_digest(material, "matter.monitoring-conveyed-material.v1")
        baseline = packet.state["monitoring"]["observed_baseline"]
        changed = baseline is None or material != baseline
        dispositions = []
        for reference in req["dispositions"]:
            definition = DispositionDefinition(view.get(reference)["value"]["value"]["definition"]).value
            if (definition["status"] == "active" and _active(definition, req["context_selection"]["effective_at"]) and
                    (definition["subject"] == current.source_finding or not changed)):
                dispositions.append(definition["kind"])
        reasons = []
        if not changed:
            reasons.extend(["no_material_change", "already_delivered" if req["baseline"]["status"] == "observed_delivery" else "already_captured"])
        if dispositions:
            reasons.append("disposition_applies")
        unknown = "unknown" in judgments.values() or any(v is None for v in material.values())
        negative = "negative" in judgments.values()
        if unknown:
            reasons.extend(["semantic_unknown", "study_abstained"])
        elif negative:
            reasons.append("unqualified_model_negative")
        else:
            reasons.append("unqualified_model_positive")
        if req["evidence"]["coverage"] != "complete":
            reasons.append("incomplete_coverage")
        linked = {canonical_bytes(r) for r in self._baseline_links} & {canonical_bytes(r) for r in req["evidence"]["correction_of"]}
        correction = baseline is not None and changed and bool(linked)
        treatment, reason = select_attention_treatment(hard_quiet=not changed or bool(dispositions),
            correction=correction, ordinary_quiet=unknown or negative or req["evidence"]["coverage"] != "complete",
            decision_ready=False, handled_by_owner=False, audience_kind="human", owned_by_audience=True,
            preference=None, routine_treatment="digest")
        if reason:
            reasons.append(reason)
        dependencies = {canonical_bytes(r): r for r in [execution, original_execution, current.source_finding,
            *current.contexts.values(), *req["dispositions"], self.require_policy_pin,
            *self.source_packet.value["dependencies"],
            *([] if req["proposal_basis"]["source_reading"] is None else [req["proposal_basis"]["source_reading"]])]}
        key = conveyed_capture_identity(host_binding=self.host.binding, intent_id=req["intent"]["id"],
            candidate=current.candidate, components=req["context_components"], material_digest=digest,
            material_contract=policy.material_contract, baseline_reference=req["baseline"].get("receipt"))
        projection = {"message_type": "monitoring_result", "contract_version": VERSION, "request_id": req["request_id"],
            "result_id": "monitoring-" + self.digest, "outcome": "proposal", "treatment": treatment,
            "intent_revision_id": req["intent"]["revision_id"], "evidence_packet_digest": req["evidence"]["packet_digest"],
            "context_components": req["context_components"], "source_finding_reference": current.source_finding,
            "assessment_reference": None, "reasons": list(dict.fromkeys(reasons)),
            "citations": [{"source": s["reference"], "locator": s["locator"], "selected_text_sha256": s["selected_text_sha256"]}
                          for s in req["evidence"]["sources"]], "coverage": req["evidence"]["coverage"],
            "uncertainty": ["Unqualified model study judgment; no supported source claim, qualification or delivery authority."],
            "qualification": "unqualified", "permitted_use": "capture_only", "currentness": "guard_required_before_capture",
            "dependencies": [dependencies[k] for k in sorted(dependencies)],
            "baseline_reference": req["baseline"].get("receipt"), "proposed_next_steps": [], "consequential_use": False,
            "capture_key": key, "decision_basis": {"kind": "unqualified_model_capture", "capture_admission_reference": None,
                "execution_reference": execution, "original_execution_reference": original_execution,
                "capture_policy": self.require_policy_pin, "judgments": judgments}}
        return {"kind": "capture_admission", "command_digest": self.digest, "host_binding": self.host.binding,
            "intent_id": req["intent"]["id"], "candidate": current.candidate, "execution": execution,
            "original_execution": original_execution, "policy": self.require_policy_pin,
            "source_reading": req["proposal_basis"]["source_reading"], "projection": projection,
            "material": material, "material_contract": policy.material_contract}


def admit_monitoring(request, *, host, packet):
    """Explicit per-objective version selection, never a decoder fallback."""
    try:
        if type(request) in {str, bytes} and len(request) > 65536:
            _fail("E_SCHEMA_INVALID")
        value = loads(request) if type(request) in {str, bytes} else request
    except (CanonicalError, TypeError, RecursionError):
        _fail("E_SCHEMA_INVALID")
    if type(value) is not dict:
        _fail("E_SCHEMA_INVALID")
    version = value.get("contract_version")
    if version == "monitoring-handoff/1.0.0":
        return AdmittedMonitoring(request, host=host, packet=packet)
    if version == VERSION:
        return AdmittedCaptureMonitoring(request, host=host, packet=packet)
    _fail("E_VERSION_UNSUPPORTED")
