"""MAT-082 bounded saved-objective bridge over existing guarded Matter ports.

Host truth is injected, never authenticated from JSON. Provider attempts use
MAT-030, decisions use MAT-019, and captures remain owned by StateCivics.
"""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator
from referencing import Registry

from ._rule_values import descriptor, domain
from .access import AccessContext, AccessService
from .attention import AttentionService, _ENGINE
from .budgets import milliseconds
from .canonical import canonical_bytes, canonical_digest, loads
from .contexts import _active, _binding
from .dispositions import DispositionDefinition, disposition_ref
from .contracts import CanonicalError, ContractError, _FORMAT_CHECKER
from .semantic import Batch
from .semantic.contracts import _result
from .semantic.cache import attempt_ref
from .semantic.families.attention import contribution_questions
from .semantic.packets import PreparedPacket
from .semantic.questions import QuestionSpecification
from .semantic.receipts import ExecutionReceiptStore
from .storage import StorageError, entity_ref, pin
from .time import compare_times


VERSION = "monitoring-handoff/1.0.0"
_HOST_FIELDS = ("mode", "context_selection", "host_binding", "intent", "context_components", "evidence", "baseline",
                "dispositions", "capture_binding", "evaluation")


def _fail(code="E_POLICY_INVALID", reason=None):
    error = ContractError(code)
    error.monitoring_reason = reason
    raise error from None


@lru_cache(maxsize=8)
def _validator(kind):
    schema = loads(files("matter._schemas").joinpath("monitoring-handoff.schema.json").read_bytes())
    return Draft202012Validator({"$ref": "#/$defs/" + kind, "$defs": schema["$defs"]},
                               registry=Registry(), format_checker=_FORMAT_CHECKER)


def validate_handoff(value, kind="request"):
    """Strict structural validation using the installed, frozen local resource."""
    if kind not in {"request", "result", "refusal"}:
        _fail()
    try:
        if type(value) in (str, bytes) and len(value) > 65536:
            _fail("E_SCHEMA_INVALID")
        value = loads(value) if type(value) in (str, bytes) else deepcopy(value)
        encoded = canonical_bytes(value)
        if kind == "request" and type(value) is dict and "contract_version" in value and value["contract_version"] != VERSION:
            _fail("E_VERSION_UNSUPPORTED")
        if len(encoded) > 65536 or not _validator(kind).is_valid(value):
            _fail("E_SCHEMA_INVALID")
    except (CanonicalError, TypeError, RecursionError):
        _fail("E_SCHEMA_INVALID")
    return value


def monitoring_refusal(error, *, request_id=None):
    """Bounded wire refusal; never serialize an exception's detail or references."""
    code = getattr(error, "code", "E_POLICY_INVALID")
    if type(code) is not str:
        code = "E_POLICY_INVALID"
    code = {"E_NOT_FOUND": "E_EVIDENCE_UNAVAILABLE", "E_STORAGE_UNAVAILABLE": "E_EVIDENCE_UNAVAILABLE",
            "E_REVISION_CONFLICT": "E_DEPENDENCY_STALE"}.get(code, code)
    reasons = {"E_SCHEMA_INVALID": "invalid_request", "E_VERSION_UNSUPPORTED": "unsupported_version",
        "E_SCOPE_FORBIDDEN": "access_forbidden", "E_AUTHORITY_REQUIRED": "access_forbidden",
        "E_DEPENDENCY_STALE": "context_changed", "E_EVIDENCE_UNAVAILABLE": "source_unavailable",
        "E_POLICY_INVALID": "invalid_request", "E_BUDGET_EXHAUSTED": "resource_limit",
        "E_CANCELLED": "host_cancelled", "E_DELIVERY_UNKNOWN": "outcome_unknown",
        "E_IDEMPOTENCY_CONFLICT": "idempotency_conflict"}
    if code not in reasons:
        code = "E_POLICY_INVALID"
    alternatives = {"E_AUTHORITY_REQUIRED": {"host_controls_unavailable"},
        "E_POLICY_INVALID": {"capture_binding_missing", "capture_binding_invalid", "provider_not_configured"}}
    supplied = getattr(error, "monitoring_reason", None)
    reason = supplied if type(supplied) is str and supplied in alternatives.get(code, set()) else reasons[code]
    if not _validator("id").is_valid(request_id):
        request_id = None
        if code not in {"E_SCHEMA_INVALID", "E_VERSION_UNSUPPORTED"}:
            code, reason = "E_SCHEMA_INVALID", "invalid_request"
    return validate_handoff({"message_type": "monitoring_refusal", "contract_version": VERSION,
        "request_id": request_id, "code": code, "reason": reason}, "refusal")


@dataclass(frozen=True)
class HostMonitoringState:
    """Current server-owned projection; no browser or model constructs this.

    The host checks real ORM ownership/approval/capture relations and pricing.
    Core context pointers and the prepared packet are checked again here.
    """
    projection: dict
    candidate: dict
    contexts: dict
    status: str
    capture_exists: bool
    capture_authorized: bool
    capture_muted: bool
    budget_ceiling: dict
    reserved_cost_usd: str
    source_finding: dict
    baseline_compatible: bool = True


@dataclass(frozen=True)
class MonitoringHost:
    binding: dict
    access: AccessService
    access_context: AccessContext
    current_state: object
    clock: object
    attention: object = None
    output_access: object = None
    output_access_context: object = None


def monitoring_questions():
    """Reuse MAT-034 meanings, with distinct civic current-intent input identity.

    This is a new unqualified input binding, not a transfer of qualification.
    Source interpretation continues to use the existing source-only families.
    """
    result = []
    for original in contribution_questions():
        value = original.value
        if not value["family"].startswith("attention."):
            continue
        value.update(namespace="matter.statecivics", id="monitoring-" + value["family"].split(".")[-1],
                     family="civic.monitoring." + value["family"].split(".")[-1])
        value["instructions"] += (" Monitoring context is the explicitly selected approved intent, not a source fact."
            " A retrospective selection is reconstructed context, not actual historical preference."
            " In capture-only studies an observed capture is the recorded comparison baseline, not proof of delivery or reading."
            " A disposition applies to its exact subject; it does not suppress a materially new deadline or linked correction."
            " Unknown legal effect and unavailable evidence remain unknown. No notification is authorized.")
        for field in value["required_fields"]:
            if field["name"] == "comparison":
                field.update(path=["monitoring"], description="Approved intent and verified conveyed history, with an explicit context clock.")
        result.append(QuestionSpecification(value))
    return tuple(result)


class AdmittedMonitoring:
    """One exact command, original access and source packet. No action authority."""

    def __init__(self, request, *, host, packet):
        self._request = validate_handoff(request)
        if (not isinstance(host, MonitoringHost) or not isinstance(host.access, AccessService)
                or not isinstance(host.access_context, AccessContext) or not isinstance(packet, PreparedPacket)
                or not callable(host.current_state) or not callable(host.clock) or host.access.current_read is None):
            _fail("E_AUTHORITY_REQUIRED", "host_controls_unavailable")
        output_access = host.output_access or host.access
        output_context = host.output_access_context or host.access_context
        if (not isinstance(output_access, AccessService) or not isinstance(output_context, AccessContext)
                or output_access.scope_id != host.access.scope_id or output_access.controls is not host.access.controls
                or output_access.current_read is None):
            _fail("E_AUTHORITY_REQUIRED")
        self.output_access, self.output_context = output_access, output_context
        self.host, self.source_packet = host, packet
        self.digest = canonical_digest(self._request, "matter.monitoring-command.v1")
        self._projection = None
        self._capture_unknown = False
        self.require_current()

    @property
    def request(self):
        return deepcopy(self._request)

    def require_current(self):
        req, host = self._request, self.host
        try:
            current = host.current_state(req["intent"]["id"])
        except ContractError:
            raise
        except Exception:
            _fail("E_AUTHORITY_REQUIRED", "host_controls_unavailable")
        if not isinstance(current, HostMonitoringState):
            _fail("E_AUTHORITY_REQUIRED", "host_controls_unavailable")
        projection = deepcopy(current.projection)
        if req["host_binding"] != host.binding or projection.get("host_binding") != host.binding:
            _fail("E_SCOPE_FORBIDDEN")
        if set(projection) != set(_HOST_FIELDS):
            _fail()
        if current.status != "active":
            _fail("E_CANCELLED")
        for value in (current.capture_exists, current.capture_authorized, current.capture_muted, current.baseline_compatible):
            if type(value) is not bool:
                _fail()
        if not current.capture_exists:
            _fail(reason="capture_binding_missing")
        if not current.capture_authorized:
            _fail("E_AUTHORITY_REQUIRED")
        if current.capture_muted:
            _fail("E_CANCELLED")
        if any(projection[name] != req[name] for name in _HOST_FIELDS):
            _fail("E_DEPENDENCY_STALE")
        if not current.baseline_compatible:
            _fail("E_DEPENDENCY_STALE")
        if req["baseline"]["status"] == "outcome_unknown":
            _fail("E_DELIVERY_UNKNOWN")
        if req["baseline"]["status"] != "no_observed_output":
            expected = {key: host.binding[key] for key in ("user_id", "workspace_id", "client_id")}
            expected["intent_id"] = req["intent"]["id"]
            if req["baseline"]["owner"] != expected:
                _fail("E_SCOPE_FORBIDDEN")
        now = host.clock()
        if (compare_times(req["context_selection"]["effective_at"], now) > 0 or
                compare_times(req["evidence"]["knowledge_cut"], now) > 0):
            _fail("E_EVIDENCE_UNAVAILABLE")
        if compare_times(req["intent"]["approval"]["approved_at"], now) > 0:
            _fail("E_AUTHORITY_REQUIRED")
        if (compare_times(now, req["intent"]["active_from"]) < 0 or
                (req["intent"]["active_until"] is not None and compare_times(now, req["intent"]["active_until"]) >= 0)):
            _fail("E_CANCELLED")
        budget, ceiling = req["budgets"], current.budget_ceiling
        if not _validator("budgets").is_valid(ceiling):
            _fail()
        try:
            exhausted = (budget["price_basis"] != ceiling["price_basis"] or
                    any(budget[k] > ceiling[k] for k in budget if k not in {"max_cost_usd", "price_basis"}) or
                    Decimal(budget["max_cost_usd"]) > Decimal(ceiling["max_cost_usd"]) or
                    type(current.reserved_cost_usd) is not str or
                    not Decimal(current.reserved_cost_usd).is_finite() or
                    not Decimal("0") <= Decimal(current.reserved_cost_usd) <= Decimal(budget["max_cost_usd"]) or
                    budget["timeout_seconds"] > budget["wall_seconds"])
        except (KeyError, TypeError, ValueError, InvalidOperation):
            _fail()
        if exhausted:
            _fail("E_BUDGET_EXHAUSTED")
        packet, state = self.source_packet, self.source_packet.state
        if (packet.digest != req["evidence"]["packet_digest"] or state["as_of"] != req["evidence"]["knowledge_cut"]
                or state["scope_id"] != host.access.scope_id or current.candidate["scope_id"] != state["scope_id"]):
            _fail("E_EVIDENCE_UNAVAILABLE")
        with host.access.current_read() as view:
            host.access.require_packet(view, host.access_context, state)
            self.output_access.require_current(view, self.output_context,
                references=[*current.contexts.values(), *req["dispositions"]], audience=req["context_components"]["audience"])
            if any(host.access_context.value["token"][k] != self.output_context.value["token"][k] for k in ("actor", "authority")):
                _fail("E_AUTHORITY_REQUIRED")
            host.access.require_current(view, host.access_context, references=[current.candidate],
                audience=req["context_components"]["audience"], provider=req["evaluation"]["provider"])
            if pin(view.get(entity_ref(current.candidate))) != current.candidate:
                _fail("E_DEPENDENCY_STALE")
            binding = state["binding"]
            if binding.get("kind") != "claim":
                _fail()
            claim = view.get(binding["claim"])
            finding = view.get(current.source_finding)
            if (claim["body"]["subject"] != entity_ref(current.candidate)
                    or finding["record_type"] not in {"claim", "assessment"}
                    or finding["body"].get("subject", finding["body"].get("matter")) != entity_ref(current.candidate)):
                _fail("E_SCOPE_FORBIDDEN")
            if not state["evidence"]:
                _fail("E_EVIDENCE_UNAVAILABLE")
            if sorted(req["evidence"]["occurrences"], key=canonical_bytes) != sorted(state["mechanical"]["occurrence_inputs"], key=canonical_bytes):
                _fail("E_EVIDENCE_UNAVAILABLE")
            host.access.require_current(view, host.access_context, references=req["evidence"]["correction_of"])
            if set(current.contexts) != set(req["context_components"]):
                _fail()
            for kind, reference in current.contexts.items():
                bound = _binding(view, state["scope_id"], reference)
                if (not _active(bound["definition"], req["context_selection"]["effective_at"])
                        or not _active(bound["definition"], now)):
                    _fail("E_CANCELLED")
                if (pin(view.get(entity_ref(reference))) != reference or
                        bound["reference"] != req["context_components"][kind] or
                        bound["definition"]["kind"] != ("objective" if kind == "scope" else kind) or
                        (bound["definition"]["applies_to"] and entity_ref(current.candidate) not in bound["definition"]["applies_to"])):
                    _fail("E_DEPENDENCY_STALE")
            host.access.require_current(view, host.access_context,
                references=[current.source_finding, *[ref for kind, ref in current.contexts.items() if kind != "preference"], *req["dispositions"]],
                audience=req["context_components"]["audience"], provider=req["evaluation"]["provider"])
            for ref in req["dispositions"]:
                pointer = view.get(ref)
                if pin(view.get(entity_ref(ref))) != ref:
                    _fail("E_DEPENDENCY_STALE")
                wrapped = pointer["value"]
                if wrapped != domain("disposition-current", wrapped["value"]):
                    _fail()
                body = wrapped["value"]
                definition = DispositionDefinition(body["definition"]).value
                control = view.get(body["control"])
                retained = control["body"]["effect"]["value"]["payload"]
                if (body["scope_id"] != state["scope_id"] or entity_ref(pointer) != disposition_ref(definition)
                        or retained != domain("disposition-mutation", retained["value"])
                        or retained["value"]["definition"] != definition
                        or control["body"]["scope"]["targets"] != [entity_ref(pointer)]):
                    _fail("E_AUTHORITY_REQUIRED")
                host.access.require_current(view, host.access_context, references=[definition["subject"]])
                if (definition["purpose"]["reference"] != req["context_components"]["purpose"] or
                        definition["audience"]["reference"] != req["context_components"]["audience"] or
                        definition["matter"] != entity_ref(current.candidate)):
                    _fail("E_SCOPE_FORBIDDEN")
            actual = {canonical_bytes(item["reference"]): item for item in state["evidence"]}
            supplied = {canonical_bytes(item["reference"]): item for item in req["evidence"]["sources"]}
            if len(supplied) != len(req["evidence"]["sources"]) or set(actual) != set(supplied):
                _fail("E_EVIDENCE_UNAVAILABLE")
            for key, selected in actual.items():
                source = supplied[key]
                record = view.get(source["reference"])
                if (source["available_at"]["state"] != "known" or
                        compare_times(source["available_at"], state["as_of"]) > 0 or
                        source["available_at"] != record["body"]["available_at"] or
                        source["artifact_sha256"] != record["body"]["content"]["digest"] or
                        source["occurred_at"] != record["body"]["occurred_at"] or
                        source["published_at"] != record["body"]["source_published_at"] or
                        source["selected_text_sha256"] != selected["text_digest"] or source["locator"] != selected["locator"] or
                        source["origin"] != record["provenance"]["origin"] or source["parents"] != record["provenance"]["parents"]):
                    _fail("E_EVIDENCE_UNAVAILABLE")
            actual_coverage = "complete" if state["coverage"]["status"] == "complete" else "partial"
            if state["coverage"]["source_coverage"]["status"] in {"failed", "not_expected_yet", "expected_not_published"}:
                actual_coverage = "unavailable"
            if req["evidence"]["coverage"] != actual_coverage:
                _fail("E_EVIDENCE_UNAVAILABLE")
        return current

    def audience_packet(self):
        """Reuse MAT-028 source selection; attach only approved current intent.

        Current/retrospective context uses its declared clock independently of
        the original source availability cut. It never adds later source bytes.
        """
        self.require_current()
        req = self._request
        material = self._conveyed_material()
        data = self.source_packet.value
        if "monitoring" in data["state"]:
            _fail()
        data["state"]["monitoring"] = {
            "context_selection": req["context_selection"],
            "intent": {key: deepcopy(req["intent"][key]) for key in
                ("purpose", "scope", "concepts", "interests", "exclusions", "requested_events", "positions", "responsibility")},
            "components": {k: v for k, v in req["context_components"].items() if k != "preference"}, "observed_baseline": material,
            "baseline_status": req["baseline"]["status"], "qualification": "unqualified"}
        data["state"]["preparation"] = descriptor("matter.statecivics", "monitoring-context", "1.0",
            {"base": data["state"]["preparation"], "contract": VERSION, "context_clock": "explicit_separate_from_evidence"},
            "matter.monitoring-transform.v1")
        with self.host.access.current_read() as view:
            scoped = []
            for ref in req["dispositions"]:
                definition = DispositionDefinition(view.get(ref)["value"]["value"]["definition"]).value
                if definition["status"] == "active" and _active(definition, req["context_selection"]["effective_at"]):
                    scoped.append({key: definition[key] for key in ("kind", "subject", "status")})
            data["state"]["monitoring"]["dispositions"] = scoped
            if req["baseline"]["status"] != "no_observed_output":
                data["state"]["monitoring"]["baseline_assessment"] = req["baseline"]["assessment_reference"]
            dependencies = {canonical_bytes(ref): ref for ref in data["dependencies"]}
            for ref in req["dispositions"]:
                dependencies[canonical_bytes(ref)] = ref
            if req["baseline"]["status"] != "no_observed_output":
                ref = req["baseline"]["assessment_reference"]
                dependencies[canonical_bytes(ref)] = ref
            for item in scoped:
                dependencies[canonical_bytes(item["subject"])] = item["subject"]
            data["dependencies"] = [dependencies[key] for key in sorted(dependencies)]
        self.require_current()
        if len(canonical_bytes(data)) > 1048576:
            _fail("E_BUDGET_EXHAUSTED")
        return PreparedPacket(data, _prepared=True)

    def _conveyed_material(self):
        baseline = self._request["baseline"]
        if baseline["status"] == "no_observed_output":
            return None
        current = self.require_current()
        # MAT-019's verified host milestone points at the actual decision/material.
        with self.host.access.current_read() as view:
            self.host.access.require_history(view, self.host.access_context,
                references=[baseline["assessment_reference"]])
            receipt = view.get(baseline["receipt"])
            attention = self.host.attention
            if not isinstance(attention, AttentionService) or attention.access is not self.output_access:
                _fail("E_AUTHORITY_REQUIRED")
            policy = attention._policy(self._request["evaluation"]["policy"])
            if (receipt["provenance"]["origin"] != "host" or receipt["body"]["stage"] != "delivered" or
                    not any(item["producer"] == receipt["provenance"]["producer"] and item["outcome"] == receipt["body"]["outcome"]
                            for item in policy.value["delivery_producers"])):
                _fail("E_AUTHORITY_REQUIRED")
            details = receipt["body"]["details"]
            if details != domain("attention-delivery-milestone", details["value"]):
                _fail()
            details = details["value"]
            decision_record = view.get(details["decision"])
            wrapped = decision_record["body"]["details"]
            if decision_record["provenance"]["producer"] != _ENGINE or wrapped != domain("attention-decision", wrapped["value"]):
                _fail("E_AUTHORITY_REQUIRED")
            decision = wrapped["value"]
            stable = lambda ref: (ref["namespace"], ref["id"])
            if (decision["treatment"] == "quiet" or details["assessment"] != decision["assessment"] or
                    details["purpose"] != decision["purpose"] or details["audience"] != decision["audience"] or
                    details["matter"] != entity_ref(current.candidate) or entity_ref(decision["matter"]) != details["matter"] or
                    compare_times(details["delivered_at"], self.host.clock()) > 0 or
                    compare_times(details["delivered_at"], decision["at"]) < 0 or
                    stable(decision["purpose"]) != stable(self._request["context_components"]["purpose"]) or
                    stable(decision["audience"]) != stable(self._request["context_components"]["audience"]) or
                    decision["policy"] != policy.reference or
                    details["material_digest"] != decision["material_digest"] or
                    canonical_digest(decision["material"], "matter.attention-material.v1") != decision["material_digest"] or
                    decision["assessment"] != baseline["assessment_reference"] or
                    decision["material_digest"] != baseline["conveyed_material_digest"]):
                _fail("E_SCOPE_FORBIDDEN")
            return deepcopy(decision["material"])

    def execute(self, *, receipts, batch, rendered_questions, executor, allocation, model_binding):
        """One durable MAT-030 attempt; exact recovery never auto-retries unknown I/O."""
        self.require_current()
        req, host = self._request, self.host
        if (not isinstance(receipts, ExecutionReceiptStore) or receipts.access is not host.access
                or receipts.budgets is None or not isinstance(batch, Batch)):
            _fail("E_AUTHORITY_REQUIRED")
        packet = self.audience_packet()
        context, budget = batch.value["context"], req["budgets"]
        if (batch.value["state"] != packet.state or context["requested_model"] != req["evaluation"]["model"] or
                context["adapter_version"] != req["evaluation"]["adapter"]["version"] or
                context["mode"] not in {"offline_fixture", "recorded_replay", "provider_shadow"} or
                [q.manifest["specification"] for q in rendered_questions] != req["evaluation"]["questions"]):
            _fail()
        logical = canonical_digest({"host": host.binding, "key": req["idempotency_key"]}, "matter.monitoring-logical.v1")
        with receipts.storage.snapshot() as view:
            try:
                view.get(attempt_ref(receipts.scope_id, logical, "initial"))
                recovering = True
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
                recovering = False
        if context["max_request_bytes"] > budget["max_request_bytes"] or context["max_response_bytes"] > budget["max_response_bytes"]:
            _fail("E_BUDGET_EXHAUSTED")
        if not recovering:
            if not callable(getattr(executor, "execute", None)):
                _fail(reason="provider_not_configured")
            if not 0 < milliseconds(context["deadline"], host.clock()) <= 1000 * min(budget["timeout_seconds"], budget["wall_seconds"]):
                _fail("E_BUDGET_EXHAUSTED")
            with host.access.current_read() as view:
                reserved = receipts.budgets.require_committed(view, allocation)
                if reserved["amounts"].get("calls", 0) > budget["max_calls"]:
                    _fail("E_BUDGET_EXHAUSTED")
        marker = descriptor("matter.statecivics", "monitoring-command", "1.0", {"digest": self.digest}, "matter.monitoring-binding.v1")
        native = receipts.request(batch, packet=packet, rendered_questions=rendered_questions,
            token=host.access_context.value["token"], model_binding=model_binding, access_context=host.access_context,
            stage={"plan": descriptor("matter.statecivics", "monitoring-semantics", "1.0", {"contract": VERSION,
                "consumes": ["source", "purpose", "scope", "audience", "responsibility", "baseline", "dispositions"]},
                "matter.monitoring-semantic-plan.v1"),
                "members": [{"stage_id": "audience", "transform": packet.state["preparation"], "parent_traces": [marker]}]})
        def dispatch(**args):
            try:
                self.require_current()
            except ContractError:
                # The guarded transport has not been entered: this is a known
                # cancellation, not an opaque possibly-sent request. The outer
                # currentness gate preserves the original refusal for the host.
                now = host.clock()
                return _result(args["batch"], args["precision"], status="cancelled", started=now, completed=now,
                    faults=[{"code": "cancelled", "path": []}])
            # Open/close a current read before I/O. Access.dispatch performs its
            # own fresh source gate before and after the injected transport.
            with host.access.current_read() as view:
                detached = packet_state_view(view, packet, access=host.access, context=host.access_context)
            return host.access.dispatch(detached, host.access_context, args["batch"], args["executor"],
                rendered_questions=rendered_questions, clock=host.clock, precision=args["precision"])
        result = receipts.run(native, executor=executor, token=host.access_context.value["token"], logical_request_id=logical,
            attempt_id="initial", allocation=allocation, access_context=host.access_context, dispatch=dispatch)
        self.require_current()
        if (result["status"] in {"started", "unknown"} or
                (result["dispatched"] and result["status"] != "completed")):
            _fail("E_DELIVERY_UNKNOWN")
        executed = result.get("result")
        if executed is not None and executed.value["execution_status"] == "cancelled":
            # A durable cancelled attempt needs a fresh host command identity;
            # resuming the objective cannot turn exact replay into a new call.
            _fail("E_CANCELLED")
        if result["status"] not in {"completed", "reused"}:
            code = result.get("operation", {}).get("error", {}).get("code", "E_POLICY_INVALID")
            allowed = _validator("refusal").schema["$defs"]["refusal"]["properties"]["code"]["enum"]
            _fail(code if code in allowed else "E_POLICY_INVALID")
        return result

    def project(self, *, attention, read_token, access_context, source_finding):
        """Project a real current MAT-019 decision; never manufacture an assessment."""
        current = self.require_current()
        req = self._request
        if (not isinstance(attention, AttentionService) or attention.access is not self.output_access
                or attention is not self.host.attention or source_finding != current.source_finding):
            _fail("E_AUTHORITY_REQUIRED")
        record = attention.current(current.candidate, policy=req["evaluation"]["policy"],
            purpose=req["context_components"]["purpose"], audience=req["context_components"]["audience"],
            read_token=read_token, access_context=access_context)
        if record is None:
            _fail("E_EVIDENCE_UNAVAILABLE")
        value = record["body"]["details"]["value"]
        self._conveyed_material()
        with self.output_access.current_read() as view:
            if value["baseline"] is None:
                _fail("E_DEPENDENCY_STALE")
            wrapped = view.get(value["baseline"])["value"]
            if wrapped != domain("attention-baseline", wrapped["value"]):
                _fail()
            conveyed = wrapped["value"]["delivered"]
            wire_receipt = req["baseline"].get("receipt")
            if ((conveyed is None) != (wire_receipt is None) or
                    (conveyed is not None and value["treatment"] != "correction" and conveyed["delivery_receipt"] != wire_receipt)):
                _fail("E_DEPENDENCY_STALE")
            self.output_access.require_current(view, access_context, references=[source_finding],
                audience=req["context_components"]["audience"])
            view.get(source_finding)
            assessment = view.get(value["assessment"])
            selected_sources = {canonical_bytes(ref) for ref in assessment["body"]["evidence_selection"]["references"]
                                if ref["record_type"] == "observation"}
            if selected_sources != {canonical_bytes(s["reference"]) for s in req["evidence"]["sources"]}:
                _fail("E_EVIDENCE_UNAVAILABLE")
            for ref in assessment["body"]["dependency_manifest"]["positive"]:
                if ref["record_type"] == "observation":
                    available = view.get(ref)["body"]["available_at"]
                    if available["state"] != "known" or compare_times(available, req["evidence"]["knowledge_cut"]) > 0:
                        _fail("E_EVIDENCE_UNAVAILABLE")
            consumed = {canonical_bytes(ref) for ref in assessment["body"]["dependency_manifest"]["positive"]}
            required = [source_finding, *[ref for kind, ref in current.contexts.items() if kind != "preference"], *req["dispositions"]]
            if any(canonical_bytes(ref) not in consumed for ref in required):
                _fail("E_DEPENDENCY_STALE")
            if not set(canonical_bytes(s["reference"]) for s in req["evidence"]["sources"]) <= set(
                    canonical_bytes(ref) for ref in assessment["body"]["evidence_selection"]["references"]):
                _fail("E_EVIDENCE_UNAVAILABLE")
        if req["evidence"]["coverage"] != "complete" and value["treatment"] not in {"quiet", "correction"}:
            _fail("E_EVIDENCE_UNAVAILABLE")
        result = {"message_type": "monitoring_result", "contract_version": VERSION, "request_id": req["request_id"],
            "result_id": "monitoring-" + self.digest, "outcome": "proposal", "treatment": value["treatment"],
            "intent_revision_id": req["intent"]["revision_id"], "evidence_packet_digest": req["evidence"]["packet_digest"],
            "context_components": req["context_components"], "source_finding_reference": source_finding,
            "assessment_reference": value["assessment"], "reasons": value["reasons"],
            "citations": [{"source": s["reference"], "locator": s["locator"], "selected_text_sha256": s["selected_text_sha256"]}
                          for s in req["evidence"]["sources"]], "coverage": req["evidence"]["coverage"],
            "uncertainty": ["Provider qualification is not established; source authority is not expanded."],
            "qualification": "unqualified", "permitted_use": "capture_only", "currentness": "guard_required_before_capture",
            "dependencies": [value["assessment"], pin(record), *current.contexts.values(), *req["dispositions"]],
            "baseline_reference": req["baseline"].get("receipt"), "proposed_next_steps": []}
        self.require_current()
        result = validate_handoff(result, "result")
        capture_key = canonical_digest({"host": self.host.binding, "intent": req["intent"]["id"],
            "candidate": entity_ref(current.candidate), "purpose": req["context_components"]["purpose"],
            "scope": req["context_components"]["scope"], "audience": req["context_components"]["audience"],
            "material": value["material_digest"], "contract": value["material_contract"],
            "baseline": req["baseline"].get("receipt")}, "matter.monitoring-capture.v1")
        self._projection = (deepcopy(result), {"attention": attention, "read_token": deepcopy(read_token),
                            "access_context": access_context, "source_finding": deepcopy(source_finding)}, capture_key)
        return result

    def handoff(self, result, *, capture):
        """Fresh host handoff, not a delivery outcome or new capture implementation."""
        self.require_current()
        value = validate_handoff(result, "result")
        if self._projection is None:
            _fail("E_AUTHORITY_REQUIRED")
        if self._capture_unknown:
            _fail("E_DELIVERY_UNKNOWN")
        original, arguments, capture_key = self._projection
        if value != original or self.project(**arguments) != original:
            _fail("E_DEPENDENCY_STALE")
        if (value["result_id"] != "monitoring-" + self.digest or value["request_id"] != self._request["request_id"]
                or not callable(capture)):
            _fail()
        if value["treatment"] == "quiet":
            return None
        guard_refusal = []
        guard_called = []
        guard_passed = []
        def capture_guard():
            guard_called.append(True)
            try:
                current = self.require_current()
                guard_passed.append(True)
                return current
            except ContractError as error:
                guard_refusal.append(error)
                raise
        try:
            outcome = capture(result=deepcopy(value), binding=deepcopy(self._request["capture_binding"]),
                channels=["in_app"], assessment_key=capture_key, require_current=capture_guard)
        except Exception as error:
            if not guard_passed and any(error is refused for refused in guard_refusal):
                raise
            self._capture_unknown = True
            _fail("E_DELIVERY_UNKNOWN")
        if not guard_called or guard_refusal:
            self._capture_unknown = True
            _fail("E_DELIVERY_UNKNOWN")
        return outcome


def packet_state_view(view, packet, *, access, context):
    """Detach exact source AND control reads with the existing core collector."""
    from .assessments import FrozenAssessmentView, _Tracked
    reads = _Tracked(view, packet.state["scope_id"])
    access.require_packet(reads, context, packet.state)
    for ref in packet.value["dependencies"]:
        reads.get(ref)
    return FrozenAssessmentView({"records": list(reads.records.values()),
                                 "absent": list(reads.absent.values()), "watch_queries": reads.queries})
