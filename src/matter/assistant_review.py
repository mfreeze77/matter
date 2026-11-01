"""MAT-088/089 bounded assistant wake-ups and host-owned ledger references.

A trusted host supplies current/read guards and exact artifact readers. No
assistant, retriever, threshold, scheduler or delivery client is constructed.
Only pointers and Matter workflow state enter the existing control/store port.
"""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from ._rule_values import FrozenValue, domain
from .access import AccessContext, AccessService
from .canonical import CanonicalError, canonical_bytes, canonical_digest
from .contexts import _MutationService, _control_command, _mutation_targets
from .contracts import ContractError
from .identity_dependencies import _lookup
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times

VERSION = "1.0"
SCHEMA = "assistant-review"
MAX_BYTES = 262144
MAX_VERIFY_READS = 256
MAX_VERIFY_BYTES = 1048576
LEDGER_FIELDS = {"judgments": "judgment", "reviews": "review", "conveyed": "conveyed",
                 "feedback": "feedback", "findings": "finding"}


def _fail(code="E_EVIDENCE_INVALID"):
    raise StorageError(code, "The assistant review boundary is unavailable, stale or invalid.")


def _wire(kind, value):
    try:
        encoded=canonical_bytes(value)
    except (CanonicalError,RecursionError,TypeError):
        _fail("E_SCHEMA_INVALID")
    if len(encoded) > MAX_BYTES:
        _fail("E_BUDGET_EXHAUSTED")
    value = domain(SCHEMA, value)["value"]
    if value["message_type"] != kind:
        _fail("E_SCHEMA_INVALID")
    return value


def _message(kind, **fields):
    return {"contract_version": VERSION, "message_type": kind, **fields}


def _refs(request):
    return [request["matter"], *request["dependencies"]]


def _host_refs(request):
    values = [request["host_control"], request["assessment"], *[c["reference"] for c in request["contributions"]]]
    if request["ledger"] is not None:
        values += [r for name in LEDGER_FIELDS for r in request["ledger"][name]]
    return _unique(values)


def _result_refs(result):
    if result is None:
        return []
    refs = [result[name] for name in ("review", "session") if result[name] is not None] + result["rule_changes"]
    if result["ledger"] is not None:
        refs += [r for name in LEDGER_FIELDS for r in result["ledger"][name]]
    return _unique(refs)


def _attempt_refs(body):
    refs=_result_refs(body["result"])
    if body["reconciliation"] is not None:
        refs.append(body["reconciliation"])
    return _unique(refs)


def _pressure_refs(body):
    refs = [c["reference"] for c in body["pending"]]
    if body["ledger"] is not None:
        refs += [r for name in LEDGER_FIELDS for r in body["ledger"][name]]
    return _unique(refs)


def _unique(values):
    return sorted({canonical_bytes(v): v for v in values}.values(), key=canonical_bytes)


def _pointer(reference, lens, kind=None):
    # Structural validation is performed by the containing wire value.
    if reference["host"] != lens["host"] or (kind is not None and reference["kind"] != kind):
        _fail("E_SCOPE_FORBIDDEN")


def _ledger(value, lens):
    if value is None:
        return
    value = _wire("ledger", value)
    if value["lens"] != lens:
        _fail("E_SCOPE_FORBIDDEN")
    for name, kind in LEDGER_FIELDS.items():
        for reference in value[name]:
            _pointer(reference, lens, kind)


class ReviewRequest(FrozenValue):
    def __init__(self, value):
        value = _wire("review_request", value)
        lens = value["lens"]
        _pointer(value["assessment"], lens, "judgment")
        _pointer(value["host_control"], lens, "control")
        if any(ref["scope_id"] != value["matter"]["scope_id"] for ref in value["dependencies"]):
            _fail("E_SCOPE_FORBIDDEN")
        identities = [canonical_bytes(entity_ref(ref)) for ref in _refs(value)]
        if len(set(identities)) != len(identities):
            _fail("E_EVIDENCE_INVALID")
        groups = []
        for contribution in value["contributions"]:
            _pointer(contribution["reference"], lens, "evidence")
            groups.append((contribution["lineage"], contribution["material_version"]))
        if len(set(groups)) != len(groups):
            _fail("E_EVIDENCE_INVALID")
        _ledger(value["ledger"], lens)
        if value["ledger"] is not None and compare_times(value["ledger"]["as_of"], value["as_of"]) > 0:
            _fail("E_EVIDENCE_UNAVAILABLE")
        roots = _host_refs(value)
        if len(roots) > min(96, value["limits"]["max_reads"]):
            _fail("E_BUDGET_EXHAUSTED")
        self._freeze(value)

    @property
    def wake_id(self):
        value = self.value
        # Quota renewal, wrapper time, reason wording and a second trigger route
        # cannot manufacture a new trial over identical semantic inputs.
        basis = {k: value[k] for k in ("lens", "matter", "assessment", "audience", "provider")}
        basis["dependencies"] = _unique(value["dependencies"])
        basis["contributions"] = sorted(value["contributions"], key=canonical_bytes)
        basis["ledger"] = None if value["ledger"] is None else {
            name: _unique(value["ledger"][name]) for name in LEDGER_FIELDS}
        return canonical_digest(basis, "matter.assistant-wake.v1")


class ReviewResult(FrozenValue):
    def __init__(self, value):
        value = _wire("review_result", value)
        completed = value["status"] == "completed"
        if completed:
            if (value["proposal"] is None or value["review"] is None or value["session"] is None
                    or value["error_code"] is not None):
                _fail("E_EVIDENCE_INVALID")
        elif (value["proposal"] is not None or value["review"] is not None or value["session"] is not None or value["reviewed"] or value["ledger"] is not None
              or value["rule_changes"]):
            _fail("E_EVIDENCE_INVALID")
        if len(_result_refs(value)) > 96:
            _fail("E_BUDGET_EXHAUSTED")
        self._freeze(value)


def host_artifact_reference(value):
    """Compute the exact host projection digest; includes lens and provenance.

    `value` has the host_artifact shape; its reference digest is excluded from
    its own preimage. This is integrity, not host authentication or source truth.
    """
    body = deepcopy(value)
    reference = body.pop("reference")
    body["identity"] = {k: reference[k] for k in ("host", "kind", "id")}
    return {**reference, "digest": canonical_digest(body, "matter.host-artifact.v1")}


def review_ledger_digest(ledger, review_reference):
    """Bind the exact selected ledger, excluding only the review's own pointer.

    Excluding its own identity avoids a self-referential digest. Other roots,
    context, versions and the knowledge cut remain part of the binding.
    """
    if ledger is None:
        return None
    value=_wire("ledger",ledger)
    identity={k:review_reference[k] for k in ("host","kind","id")}
    value["reviews"]=[ref for ref in value["reviews"] if {k:ref[k] for k in identity}!=identity]
    return canonical_digest(value,"matter.assistant-review-ledger.v1")


def pressure_contribution(artifact, *, lineage, material_version):
    """Host-selected provenance group plus exact source-material identity.

    Reprints use the same canonical source content, lineage and material version. A correction or
    new deadline has changed material, even when it belongs to the same lineage.
    This does not infer independence or assign a relevance/importance weight.
    """
    artifact = _wire("host_artifact", artifact)
    if (artifact["reference"]["kind"] != "evidence" or host_artifact_reference(artifact) != artifact["reference"]
            or artifact["classification"] not in {"source_quote", "source_fact"}):
        _fail("E_EVIDENCE_INVALID")
    return {"reference": artifact["reference"], "lineage": lineage, "material_version": material_version,
            "material_digest": canonical_digest(artifact["content"], "matter.review-source-material.v1")}


def _consumed_ref(scope_id, request, contribution):
    return {"scope_id": scope_id, "namespace": "adapter:assistant-review", "record_type": PROJECTION_TYPE,
            "id": "consumed-" + canonical_digest({"lens": request.value["lens"],
                "matter": entity_ref(request.value["matter"]), "lineage": contribution["lineage"],
                "material_version": contribution["material_version"]},
                "matter.review-consumed.v1")}


@dataclass(frozen=True)
class ReviewHost:
    """Installed authenticated host port, never constructed from model output.

    Guards take (request, references, as_of) and return None on success; resolve
    takes (lens, reference, as_of). Guards verify the native matter/context and
    audience/provider binding against the actual host projection, not just IDs.
    Current requires active approved intent, exact revision, source/context
    currentness, account/client/access and provider/tool egress. Read permits
    authorized history without granting reuse. See the receiving contract.
    """
    binding: str
    require_current: Callable
    require_read: Callable
    resolve: Callable


def pressure_ref(scope_id, request):
    value = request.value if isinstance(request, ReviewRequest) else request
    return {"scope_id": scope_id, "namespace": "adapter:assistant-review", "record_type": PROJECTION_TYPE,
            "id": "pressure-" + canonical_digest({"lens":value["lens"], "matter":entity_ref(value["matter"])}, "matter.assistant-pressure.v1")}


def _lens_lock_ref(scope_id, request):
    return {"scope_id":scope_id,"namespace":"adapter:assistant-review","record_type":PROJECTION_TYPE,
            "id":"lens-"+canonical_digest({k:v for k,v in request.value["lens"].items() if k!="revision_id"},"matter.assistant-lens.v1")}


def review_ref(scope_id, wake_id):
    return {"scope_id": scope_id, "namespace": "adapter:assistant-review", "record_type": PROJECTION_TYPE,
            "id": "wake-" + wake_id}


class AssistantReviewService(_MutationService):
    mutation_schema = SCHEMA

    def __init__(self, storage, *, controls, access, host, clock):
        super().__init__(storage, controls=controls)
        if (not isinstance(access, AccessService) or access.controls is not controls
                or not isinstance(host, ReviewHost) or not callable(clock)
                or any(not callable(x) for x in (host.require_current, host.require_read, host.resolve))):
            _fail("E_POLICY_INVALID")
        self.access, self.host, self.clock = access, host, clock

    def _request(self, request):
        request = request if isinstance(request, ReviewRequest) else ReviewRequest(request)
        if request.value["matter"]["scope_id"] != self.scope_id or request.value["lens"]["host"] != self.host.binding:
            _fail("E_SCOPE_FORBIDDEN")
        if compare_times(request.value["as_of"], self.clock()) > 0:
            _fail("E_EVIDENCE_UNAVAILABLE")
        return request

    def _host_guard(self, request, references=None, *, historical=False, at=None):
        value = request.value
        guard = self.host.require_read if historical else self.host.require_current
        try:
            accepted = guard(deepcopy(value), deepcopy(_host_refs(value) if references is None else references),
                             deepcopy(at or value["as_of"]))
            if accepted is not None:
                _fail("E_AUTHORITY_REQUIRED")
        except ContractError:
            raise
        except Exception:
            _fail("E_STORAGE_UNAVAILABLE")

    def _guard(self, view, payload):
        request = ReviewRequest(payload["request"]).value
        self.controls._view(view, actor=payload["token"]["actor"], authority=entity_ref(payload["token"]["authority"]),
                            capability="assessment", targets=[pressure_ref(self.scope_id, request),
                            review_ref(self.scope_id, ReviewRequest(request).wake_id), _lens_lock_ref(self.scope_id, ReviewRequest(request))], now=self.clock())
        self.controls.require_current(view, payload["token"], capability="assessment",
                                      targets=[entity_ref(r) for r in _refs(request)])
        for reference in _refs(request):
            if pin(view.get(entity_ref(reference))) != reference:
                _fail("E_DEPENDENCY_STALE")
        self.access.require_current(view, payload["access_context"], references=_refs(request),
                                    audience=request["audience"], provider=request["provider"])

    def _read_targets(self, view, payload):
        request = ReviewRequest(payload["request"])
        return [_lens_lock_ref(self.scope_id, request), pressure_ref(self.scope_id, request), review_ref(self.scope_id, request.wake_id),
                *[entity_ref(r) for r in _refs(request.value)],
                *[_consumed_ref(self.scope_id, request, c) for c in request.value["contributions"]]]

    def _action(self, action, request, *, token=None, access_context, command_id, result=None, witness=None, submitted_result_digest=None, actor=None, authority=None):
        target = pressure_ref(self.scope_id, request) if action == "pressure" else review_ref(self.scope_id, request.wake_id)
        with self.storage.snapshot() as view:
            old = _lookup(view, target)
        payload = _message("mutation", action=action, witness=witness, submitted_result_digest=submitted_result_digest, request=request.value,
            result=None if result is None else result.value, token=token,
            access_context=access_context.value if hasattr(access_context, "value") else access_context,
            previous=None if old is None else pin(old))
        command = self._prepare(_control_command(self.controls, payload=payload, schema=SCHEMA, target=target,
            command_id=command_id, idempotency_key=command_id, actor=actor if token is None else token["actor"],
            authority=entity_ref(authority if token is None else token["authority"]),
            kind="correction" if action=="reconcile" else "decision"))
        ran = False
        def handler(tx):
            nonlocal ran
            ran = True
            return self._commit(tx)
        def replay(view):
            self._authorize(view, command, self._read_targets(view, payload))
        outcome = self.storage.execute(command, handler, replay_guard=replay)
        if outcome["status"] != "success":
            _fail(outcome["error"]["code"])
        return self.storage.get(target), ran

    def _authorize(self, view, command, targets):
        _, payload = self._payload(command)
        if payload["action"] == "reconcile":
            self.controls._view(view, actor=command["actor"], authority=command["authority"],
                capability="correction", targets=_mutation_targets(command, targets), now=self.clock(), audit=True)
        return super()._authorize(view, command, targets)

    def _state(self, view, command, payload, *, preparing):
        payload = _wire("mutation", payload)
        request = self._request(payload["request"])
        action = payload["action"]
        target = pressure_ref(self.scope_id, request) if action == "pressure" else review_ref(self.scope_id, request.wake_id)
        schema_kind = "pressure" if action == "pressure" else "attempt"
        kind=command["body"]["control"]["body"]["control_kind"]
        if command["body"]["control"]["body"]["scope"]["targets"] != [target]:
            _fail("E_AUTHORITY_REQUIRED")
        if action=="reconcile":
            if payload["token"] is not None or kind!="correction":
                _fail("E_AUTHORITY_REQUIRED")
        elif (payload["token"] is None or kind!="decision" or
              command["actor"]!=payload["token"].get("actor") or
              command["authority"]!=entity_ref(payload["token"].get("authority"))):
            _fail("E_AUTHORITY_REQUIRED")
        old, old_control = self._prior(view, command, payload, target, SCHEMA, preparing=preparing)
        prior = None if old is None else _wire(schema_kind, old["value"]["value"])
        pressure = _lookup(view, pressure_ref(self.scope_id, request))
        pressure_body = None if pressure is None else _wire("pressure", pressure["value"]["value"])
        pending = [] if pressure_body is None else pressure_body["pending"]
        lock = _lookup(view, _lens_lock_ref(self.scope_id, request))
        active_wake = None if lock is None else _wire("lens_lock",lock["value"]["value"])["active_wake"]
        consumed = {canonical_bytes(c): _lookup(view, _consumed_ref(self.scope_id, request, c))
                    for c in request.value["contributions"]}
        fresh = True
        try:
            if action!="reconcile":
                self._guard(view, payload)
        except ContractError:
            if action != "finish":
                raise
            fresh = False
        result = payload["result"]
        if action == "pressure":
            if result is not None:
                _fail()
            merged = {(c["lineage"],c["material_version"]): c for c in pending}
            for contribution in request.value["contributions"]:
                used=consumed[canonical_bytes(contribution)]
                if used is not None and used["value"]["value"]["contribution"]["material_digest"]!=contribution["material_digest"]:
                    _fail("E_SOURCE_IDENTITY_CONFLICT")
                if used is None:
                    key=(contribution["lineage"],contribution["material_version"])
                    if key in merged and merged[key]["material_digest"]!=contribution["material_digest"]:
                        _fail("E_SOURCE_IDENTITY_CONFLICT")
                    merged[key] = contribution
            if len(merged)>128:
                _fail("E_BUDGET_EXHAUSTED")
            value = _message("pressure", lens=request.value["lens"], matter=request.value["matter"],
                dependencies=request.value["dependencies"], pending=sorted(merged.values(), key=canonical_bytes),
                ledger=request.value["ledger"], control=None)
        elif action == "start":
            if result is not None or prior is not None:
                _fail("E_IDEMPOTENCY_CONFLICT")
            if active_wake is not None:
                _fail("E_DELIVERY_UNKNOWN")
            if any(c not in pending for c in request.value["contributions"]):
                _fail("E_DEPENDENCY_STALE")
            value = _message("attempt", request=request.value, submitted_result_digest=None, reconciliation=None, outcome_unknown=True, started_at=self.clock(), finished_at=None, phase="started", result=None, control=None)
        elif action=="reconcile":
            if (prior is None or not prior["outcome_unknown"] or active_wake!=request.wake_id
                    or prior["request"]!=request.value or payload["witness"] is None or result is not None):
                _fail("E_IDEMPOTENCY_CONFLICT")
            _pointer(payload["witness"],request.value["lens"],"control")
            value=_message("attempt",request=prior["request"],submitted_result_digest=prior["submitted_result_digest"],
                reconciliation=payload["witness"],outcome_unknown=False,started_at=prior["started_at"],
                finished_at=self.clock(),phase="reconciled",result=prior["result"],control=None)
        else:
            if prior is None or prior["phase"] != "started" or prior["request"] != request.value:
                _fail("E_IDEMPOTENCY_CONFLICT")
            result = ReviewResult(result).value
            self._result_scope(request, result)
            value = _message("attempt", request=prior["request"], submitted_result_digest=payload["submitted_result_digest"], reconciliation=None, outcome_unknown=result["status"] == "unknown", started_at=prior["started_at"], finished_at=self.clock(), phase=result["status"] if fresh else "stale",
                             result=result if fresh else None, control=None)
        return {"old": old, "old_control": old_control, "targets": self._read_targets(view, payload),
                "value": value, "pressure": pressure, "consumed": consumed, "lock":lock, "fresh": fresh}

    def _write(self, tx, payload, state, control):
        request = ReviewRequest(payload["request"])
        value = state["value"]
        value["control"] = control
        if payload["action"] == "pressure":
            _wire("pressure", value)  # Refuse oversize before persisting an unreadable window.
        target = pressure_ref(self.scope_id, request) if payload["action"] == "pressure" else review_ref(self.scope_id, request.wake_id)
        tx.put_projection(target, domain(SCHEMA, value))
        if payload["action"] == "start":
            tx.put_projection(_lens_lock_ref(self.scope_id,request),domain(SCHEMA,_message("lens_lock",
                lens=request.value["lens"],active_wake=request.wake_id,control=control)))
        if payload["action"] == "finish" and value["phase"] == "completed":
            # Exact source pins only: concurrent new/corrected contributions and
            # other lenses survive. The old projection/control journal retains
            # all earlier associations; resetting never erases source history.
            pressure = deepcopy(state["pressure"]["value"]["value"])
            reviewed = value["result"]["reviewed"]
            covered = [c for c in request.value["contributions"] if c["reference"] in reviewed]
            for contribution in covered:
                if state["consumed"][canonical_bytes(contribution)] is not None:
                    continue
                tx.put_projection(_consumed_ref(self.scope_id, request, contribution), domain(SCHEMA,
                    _message("consumed", lens=request.value["lens"], contribution=contribution,
                             wake_id=request.wake_id, control=control)))
            pressure["pending"] = [c for c in pressure["pending"] if not any(
                c["lineage"] == old["lineage"] and c["material_version"]==old["material_version"] and c["material_digest"] == old["material_digest"] for old in covered)]
            pressure["ledger"] = value["result"]["ledger"] or pressure["ledger"]
            tx.put_projection(pressure_ref(self.scope_id, request), domain(SCHEMA, _wire("pressure", pressure)))
        if payload["action"] in {"finish","reconcile"} and not value["outcome_unknown"]:
            tx.put_projection(_lens_lock_ref(self.scope_id,request),domain(SCHEMA,_message("lens_lock",
                lens=request.value["lens"],active_wake=None,control=control)))

    def record_pressure(self, request, *, token, access_context, command_id):
        """Host-selected distinct contributions; no numeric threshold is supplied.

        A lineage/material version has one pending entry. Reprints share that
        version; different revisions stay pending together so late old wrappers
        cannot evict corrections. The host owns provenance/correlation meaning.
        """
        request = self._request(request)
        reader = self._reader_context(access_context, actor=token["actor"], authority=token["authority"])
        self._host_guard(request)
        with self.storage.snapshot() as view:
            prior = _lookup(view, pressure_ref(self.scope_id, request))
        if prior is not None:
            self.pressure(request, token=token, access_context=access_context)
        artifacts = self.resolve(request, [c["reference"] for c in request.value["contributions"]],
                                 token=token, access_context=access_context)
        by_ref = {canonical_bytes(a["reference"]): a for a in artifacts}
        for contribution in request.value["contributions"]:
            if pressure_contribution(by_ref[canonical_bytes(contribution["reference"])],
                                     lineage=contribution["lineage"],material_version=contribution["material_version"]) != contribution:
                _fail("E_EVIDENCE_INVALID")
        with self.storage.snapshot() as view:
            try:
                journal = view.command_receipt(command_id)
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
            else:
                command, payload = self._payload(journal["command"])
                context = access_context.value if hasattr(access_context, "value") else access_context
                if (payload["action"] != "pressure" or payload["request"] != request.value or payload["token"] != token
                        or payload["access_context"] != context):
                    _fail("E_IDEMPOTENCY_CONFLICT")
                self._authorize(view, command, self._read_targets(view, payload))
                if journal["result"]["status"] != "success":
                    _fail(journal["result"]["error"]["code"])
                row=view.get(pressure_ref(self.scope_id, request))
                self._authorize_history_rows(view, view.history(pressure_ref(self.scope_id,request)),
                    reader, actor=token["actor"], authority=token["authority"])
                self._host_guard(request,_pressure_refs(row["value"]["value"]),historical=True,at=self.clock())
                return row
        row=self._action("pressure", request, token=token, access_context=access_context, command_id=command_id)[0]
        self.pressure(request, token=token, access_context=access_context)
        return row

    def claim(self, request, *, token, access_context):
        """Commit once before the host calls its assistant, outside the write TX.

        Returns (acquired, attempt). A started attempt is outcome-unknown on
        recovery and is never reissued. A new wrapper time/route cannot reset it.
        """
        request = self._request(request)
        self.resolve(request, _host_refs(request.value), token=token, access_context=access_context)
        with self.storage.snapshot() as view:
            self._guard(view, {"request": request.value, "token": token,
                              "access_context": access_context.value if hasattr(access_context, "value") else access_context})
            prior = _lookup(view, review_ref(self.scope_id, request.wake_id))
        if prior is not None:
            body = prior["value"]["value"]
            if (compare_times(body["request"]["as_of"], request.value["as_of"]) > 0 or
                    compare_times(body["finished_at"] or body["started_at"], self.clock()) > 0):
                _fail("E_EVIDENCE_UNAVAILABLE")
            self._host_guard(request, _attempt_refs(body), historical=True, at=self.clock())
            return False, prior
        identity = "assistant-start-" + uuid4().hex
        # The store's unique command/expected revisions arbitrate separate real
        # handles. A loser never acquires permission to invoke the callback.
        row, acquired = self._action("start", request, token=token, access_context=access_context, command_id=identity)
        return acquired, row

    def _result_scope(self, request, result):
        if result["wake_id"] != request.wake_id:
            _fail("E_EVIDENCE_INVALID")
        lens = request.value["lens"]
        for name, kind in (("review", "review"), ("session", "session")):
            if result[name] is not None:
                _pointer(result[name], lens, kind)
        reviewed = [c["reference"] for c in request.value["contributions"]]
        if any(ref not in reviewed for ref in result["reviewed"]):
            _fail("E_EVIDENCE_INVALID")
        for reference in result["rule_changes"]:
            _pointer(reference, lens, "rule")
        _ledger(result["ledger"], lens)

    def complete(self, request, result, *, token, access_context):
        request = self._request(request)
        result = result if isinstance(result, ReviewResult) else ReviewResult(result)
        self._result_scope(request, result.value)
        with self.storage.snapshot() as view:
            prior = view.get(review_ref(self.scope_id, request.wake_id))
        prior_body = prior["value"]["value"]
        submitted_digest=canonical_digest(result.value,"matter.assistant-submitted-result.v1")
        if prior_body["phase"] != "started":
            # Completion replay is read guarded and cannot clear newly arrived
            # pressure or update a rule for a second time.
            if prior_body["submitted_result_digest"] != submitted_digest:
                _fail("E_IDEMPOTENCY_CONFLICT")
            self._host_guard(request, _attempt_refs(prior_body), historical=True, at=self.clock())
            with self.storage.snapshot() as view:
                self.access.require_history(view, access_context, references=_refs(request.value))
                self.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])},
                                     [entity_ref(r) for r in _refs(request.value)])
            return prior
        fresh = True
        try:
            if result.value["status"]=="completed":
                self._host_guard(request)
        except ContractError as error:
            if error.code not in {"E_CANCELLED","E_DEPENDENCY_STALE","E_AUTHORITY_REQUIRED","E_SCOPE_FORBIDDEN"}:
                raise
            fresh = False
        if fresh and result.value["status"] == "completed":
            references = [result.value["review"], result.value["session"], *result.value["rule_changes"]]
            if result.value["ledger"] is not None:
                if compare_times(result.value["ledger"]["as_of"], self.clock()) > 0:
                    _fail("E_EVIDENCE_UNAVAILABLE")
                references += [r for name in LEDGER_FIELDS for r in result.value["ledger"][name]]
            self._host_guard(request, references, at=self.clock())
            artifacts = self._resolve(request, references, at=self.clock(), verification=True)
            persisted_review = next(a for a in artifacts if a["reference"] == result.value["review"])
            content = persisted_review["content"]
            if content.get("wake_id") != request.wake_id:
                _fail("E_EVIDENCE_INVALID")
            if (content.get("session")!=result.value["session"] or
                    content.get("ledger_binding")!=review_ledger_digest(result.value["ledger"],result.value["review"])):
                _fail("E_EVIDENCE_INVALID")
            for field in ("status", "proposal", "reviewed", "rule_changes"):
                if content.get(field) != result.value[field]:
                    _fail("E_EVIDENCE_INVALID")
        if not fresh and result.value["status"] != "unknown":
            # Retain a safe stopped result without admitting stale host output.
            result = ReviewResult(_message("review_result", wake_id=request.wake_id, status="stopped", proposal=None,
                review=None, session=None, reviewed=[], ledger=None, rule_changes=[], error_code="context_changed"))
        return self._action("finish", request, token=token, access_context=access_context,
                            command_id="assistant-finish-" + uuid4().hex, result=result, submitted_result_digest=submitted_digest)[0]

    def execute(self, request, *, token, access_context, reviewer):
        """Synchronous convenience; async hosts use claim/complete around review().

        Host transport enforces the requested timeout/tool limits. This SDK does
        not preempt Python callbacks. Exceptions retain unknown outcome, never
        quiet, and the wake identity is not retried automatically.
        """
        request = self._request(request)
        acquired, attempt = self.claim(request, token=token, access_context=access_context)
        if not acquired:
            return attempt
        try:
            self._host_guard(request)
        except ContractError:
            stopped=ReviewResult(_message("review_result",wake_id=request.wake_id,status="stopped",proposal=None,
                review=None,session=None,reviewed=[],ledger=None,rule_changes=[],error_code="before_dispatch_refused"))
            return self.complete(request,stopped,token=token,access_context=access_context)
        try:
            result = reviewer(request.value, request.wake_id)
        except Exception:
            result = _message("review_result", wake_id=request.wake_id, status="unknown", proposal=None,
                review=None, session=None, reviewed=[], ledger=None, rule_changes=[], error_code="review_outcome_unknown")
        return self.complete(request, result, token=token, access_context=access_context)

    def _resolve(self, request, references, *, at, historical=False, verification=False):
        max_reads=MAX_VERIFY_READS if verification else request.value["limits"]["max_reads"]
        max_bytes=MAX_VERIFY_BYTES if verification else request.value["limits"]["max_bytes"]
        if not isinstance(references, (tuple, list)) or len(references) > max_reads:
            _fail("E_BUDGET_EXHAUSTED")
        result, visiting, seen = [], set(), set()
        total = 0
        def visit(reference):
            nonlocal total
            key = canonical_bytes(reference)
            if key in visiting:
                _fail("E_EVIDENCE_INVALID")
            if key in seen:
                return
            if len(seen) + len(visiting) >= max_reads:
                _fail("E_BUDGET_EXHAUSTED")
            _pointer(reference, request.value["lens"])
            self._host_guard(request, [reference], at=at,historical=historical)
            try:
                artifact = _wire("host_artifact", self.host.resolve(deepcopy(request.value["lens"]), deepcopy(reference), deepcopy(at)))
            except ContractError:
                raise
            except Exception:
                _fail("E_EVIDENCE_UNAVAILABLE")
            total += len(canonical_bytes(artifact))
            if total > max_bytes:
                _fail("E_BUDGET_EXHAUSTED")
            if (artifact["reference"] != reference or host_artifact_reference(artifact) != reference
                    or artifact["lens"] != request.value["lens"]):
                _fail("E_EVIDENCE_INVALID")
            if compare_times(artifact["available_at"], at) > 0:
                _fail("E_EVIDENCE_UNAVAILABLE")
            allowed={"finding":{"source_quote","jev_judgment","interpretation"},
                "judgment":{"jev_judgment"},"evidence":{"source_quote","source_fact"},
                "rule":{"rule"},"review":{"review"},"session":{"session"},"control":{"host_control"},
                "feedback":{"user_feedback"},"conveyed":{"communication"},"report":{"communication"}}
            if artifact["classification"] not in allowed[reference["kind"]]:
                _fail("E_EVIDENCE_INVALID")
            if ((artifact["classification"] == "communication") != (artifact["communication_state"] is not None)):
                _fail("E_EVIDENCE_INVALID")
            if (reference["kind"] == "finding" or artifact["classification"] in {"interpretation", "jev_judgment"}) and not artifact["citations"]:
                _fail("E_EVIDENCE_INVALID")
            visiting.add(key)
            for parent in _unique(artifact["citations"] + artifact["derived_from"]):
                visit(parent)
            visiting.remove(key)
            seen.add(key)
            result.append(artifact)
        for reference in _unique(references):
            visit(reference)
        self._host_guard(request, [a["reference"] for a in result], at=at,historical=historical)
        return result

    def resolve(self, request, references, *, token, access_context):
        """Transient authorized content for host packet construction; never stored.

        Preserve returned classification/citations/parents. These are derived
        context, not independent corroboration or qualification. This method
        does not dispatch a model or extend any provider egress grant.
        """
        request = self._request(request)
        if not isinstance(references, (list, tuple)) or any(ref not in _host_refs(request.value) for ref in references):
            _fail("E_SCOPE_FORBIDDEN")
        with self.storage.snapshot() as view:
            self._guard(view, {"request": request.value, "token": token,
                              "access_context": access_context.value if hasattr(access_context, "value") else access_context})
        self._host_guard(request)
        artifacts = self._resolve(request, references, at=request.value["as_of"])
        self._host_guard(request)
        with self.storage.snapshot() as view:
            self._guard(view, {"request": request.value, "token": token,
                              "access_context": access_context.value if hasattr(access_context, "value") else access_context})
        return deepcopy(artifacts)

    def resolve_ledger(self, request, *, token, access_context):
        request = self._request(request)
        ledger = request.value["ledger"]
        references = [] if ledger is None else [r for name in LEDGER_FIELDS for r in ledger[name]]
        return self.resolve(request, references, token=token, access_context=access_context)

    def history_context(self, request, *, actor, authority, audience):
        """Present local READ on exact historical pins, including under cancel.

        This is not an assessment token or provider-egress grant. It lets a
        current operator inspect/reconcile after worker/provider rotation.
        """
        request = self._request(request)
        self._host_guard(request, historical=True, at=self.clock())
        with self.storage.snapshot() as view:
            token = self.controls._view(view, actor=actor, authority=authority,
                capability="read", targets=[entity_ref(r) for r in _refs(request.value)],
                now=self.clock(), audit=True)
            dependencies = self.access._closure(view, _refs(request.value), audience,
                None, token, historical=True)
        return AccessContext({"schema_version":"1.0", "scope_id":self.scope_id,
            "policy":self.access.policy.reference, "audience":audience, "provider":None,
            "token":token, "references":_unique(_refs(request.value)), "dependencies":dependencies})

    def _reader_context(self, context, *, actor, authority):
        data = context.value if isinstance(context, AccessContext) else AccessContext(context).value
        if (data["scope_id"] != self.scope_id or data["token"]["actor"] != actor or
                entity_ref(data["token"]["authority"]) != entity_ref(authority)):
            _fail("E_AUTHORITY_REQUIRED")
        # Metadata inspection never sends a source to the former provider. Its
        # retired egress grant need not survive solely to permit a local read.
        data["provider"] = None
        return data

    def _historical_context(self, view, body, reader):
        control=view.get(body["control"])
        wrapped=control["body"]["effect"]["value"]["payload"]
        payload=_wire("mutation",wrapped["value"])
        if (wrapped!=domain(SCHEMA,payload) or payload["action"]!="pressure" or
                any(payload["request"][name]!=body[name] for name in ("lens","matter","dependencies"))):
            _fail("E_EVIDENCE_INVALID")
        original = payload["access_context"]
        return {**reader, "references":original["references"],
                "dependencies":original["dependencies"]}

    def _authorize_history_rows(self, view, rows, reader, *, actor, authority):
        # Pending entries survive newer writes. Authorize all retained native
        # selections, not just the newest writer's pins. Equal selections can
        # share a check within this one consistent read snapshot only.
        seen = set()
        for row in rows:
            body = _wire("pressure", row["value"]["value"])
            context = self._historical_context(view, body, reader)
            references = [body["matter"], *body["dependencies"]]
            key = canonical_bytes({"references":context["references"],
                "dependencies":context["dependencies"], "targets":references})
            if key not in seen:
                self.access.require_history(view, context, references=references)
                self.controls._audit(view, {"actor":actor,"authority":entity_ref(authority)},
                    [entity_ref(r) for r in references])
                seen.add(key)

    def pressure(self, request, *, token, access_context):
        """Present-authorized metadata for this lens/matter, not model input."""
        request = self._request(request)
        access_context = self._reader_context(access_context, actor=token["actor"], authority=token["authority"])
        self._host_guard(request,historical=True,at=self.clock())
        with self.storage.snapshot() as view:
            self.controls._audit(view,{"actor":token["actor"],"authority":entity_ref(token["authority"])},
                                 [entity_ref(r) for r in _refs(request.value)])
            self.access.require_history(view,access_context,references=_refs(request.value))
            body=deepcopy(view.get(pressure_ref(self.scope_id,request))["value"]["value"])
            self._authorize_history_rows(view, view.history(pressure_ref(self.scope_id,request)),
                access_context, actor=token["actor"], authority=token["authority"])
        self._host_guard(request,_pressure_refs(body),at=self.clock(),historical=True)
        return body


    def inspect(self, request, *, actor, authority, access_context):
        """Read an attempt under present authority; started means outcome unknown.

        No automatic takeover or retry is authorized by this read. Historical
        results are not fresh proposals and cannot perform another reset.
        """
        request = self._request(request)
        access_context = self._reader_context(access_context, actor=actor, authority=authority)
        self._host_guard(request, historical=True)
        with self.storage.snapshot() as view:
            self.controls._audit(view, {"actor": actor, "authority": authority},
                                 [entity_ref(r) for r in _refs(request.value)])
            self.access.require_history(view, access_context, references=_refs(request.value))
            row = view.get(review_ref(self.scope_id, request.wake_id))
            value = deepcopy(row["value"]["value"])
        self._host_guard(request, _attempt_refs(value), historical=True, at=self.clock())
        if compare_times(value["finished_at"] or value["started_at"], self.clock()) > 0:
            _fail("E_EVIDENCE_UNAVAILABLE")
        value["human_communicated"] = False
        return value

    def history(self, request, *, actor, authority, access_context):
        """Authorized pointer-only pressure history; reset never deletes it."""
        request = self._request(request)
        access_context = self._reader_context(access_context, actor=actor, authority=authority)
        with self.storage.snapshot() as view:
            self.controls._audit(view, {"actor": actor, "authority": authority},
                                 [entity_ref(r) for r in _refs(request.value)])
            self.access.require_history(view, access_context, references=_refs(request.value))
            rows = view.history(pressure_ref(self.scope_id, request))
            self._authorize_history_rows(view, rows, access_context, actor=actor, authority=authority)
        for row in rows:
            body = _wire("pressure", row["value"]["value"])
            refs = [c["reference"] for c in body["pending"]]
            if body["ledger"] is not None:
                refs += [ref for name in LEDGER_FIELDS for ref in body["ledger"][name]]
            self._host_guard(request, refs, historical=True, at=self.clock())
        return deepcopy(rows)


    def reconcile(self, request, witness, *, actor, authority, access_context, command_id):
        """Explicit operator control; lookup proof of no in-flight review only.

        Never calls the assistant, clears pressure, or admits a quiet proposal.
        A real host control must attest no review is still running; the original
        wake remains non-dispatchable after reconciliation.
        """
        request=self._request(request)
        access_context = self._reader_context(access_context, actor=actor, authority=authority)
        self._host_guard(request,[witness],historical=True,at=self.clock())
        artifacts=self._resolve(request,[witness],at=self.clock(),historical=True,verification=True)
        proof=next(a for a in artifacts if a["reference"]==witness)
        _pointer(witness,request.value["lens"],"control")
        if (proof["content"].get("wake_id")!=request.wake_id or proof["content"].get("inflight") is not False
                or proof["content"].get("resolution") not in {"observed_completion","not_started","stopped","failed"}):
            _fail("E_EVIDENCE_INVALID")
        with self.storage.snapshot() as view:
            old=view.get(review_ref(self.scope_id,request.wake_id))
            if old["value"]["value"]["phase"]=="reconciled":
                if old["value"]["value"]["reconciliation"]!=witness:
                    _fail("E_IDEMPOTENCY_CONFLICT")
                self.controls._audit(view,{"actor":actor,"authority":authority},[entity_ref(r) for r in _refs(request.value)])
                self.access.require_history(view,access_context,references=_refs(request.value))
                return old
        # Operator controls do not capture or renew a work token. Read source
        # history on a plain snapshot; a collecting/write view would incorrectly
        # require old version pins to be current. Present READ/correction rights
        # are rechecked atomically by _authorize on the actual entity targets.
        with self.storage.snapshot() as view:
            self.access.require_history(view,access_context,references=_refs(request.value))
            self.controls._audit(view,{"actor":actor,"authority":authority},[entity_ref(r) for r in _refs(request.value)])
        return self._action("reconcile",request,access_context=access_context,actor=actor,authority=authority,
                            command_id=command_id,witness=witness)[0]
