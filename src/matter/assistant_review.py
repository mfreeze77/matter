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
from .access import AccessService
from .canonical import canonical_bytes, canonical_digest
from .contexts import _MutationService, _control_command
from .contracts import ContractError
from .identity_dependencies import _lookup
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times

VERSION = "1.0"
SCHEMA = "assistant-review"
MAX_BYTES = 262144
LEDGER_FIELDS = {"judgments": "judgment", "reviews": "review", "conveyed": "conveyed",
                 "feedback": "feedback", "findings": "finding"}


def _fail(code="E_EVIDENCE_INVALID"):
    raise StorageError(code, "The assistant review boundary is unavailable, stale or invalid.")


def _wire(kind, value):
    if len(canonical_bytes(value)) > MAX_BYTES:
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
            groups.append(contribution["lineage"])
        if len(set(groups)) != len(groups):
            _fail("E_EVIDENCE_INVALID")
        _ledger(value["ledger"], lens)
        if value["ledger"] is not None and compare_times(value["ledger"]["as_of"], value["as_of"]) > 0:
            _fail("E_EVIDENCE_UNAVAILABLE")
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


def pressure_contribution(artifact, *, lineage):
    """Host-selected provenance group plus exact source-material identity.

    Reprints use the same canonical source content and lineage. A correction or
    new deadline has changed material, even when it belongs to the same lineage.
    This does not infer independence or assign a relevance/importance weight.
    """
    artifact = _wire("host_artifact", artifact)
    if (artifact["reference"]["kind"] != "evidence" or host_artifact_reference(artifact) != artifact["reference"]
            or artifact["classification"] not in {"source_quote", "source_fact"}):
        _fail("E_EVIDENCE_INVALID")
    return {"reference": artifact["reference"], "lineage": lineage,
            "material_digest": canonical_digest(artifact["content"], "matter.review-source-material.v1")}


def _consumed_ref(scope_id, request, contribution):
    return {"scope_id": scope_id, "namespace": "adapter:assistant-review", "record_type": PROJECTION_TYPE,
            "id": "consumed-" + canonical_digest({"lens": request.value["lens"],
                "lineage": contribution["lineage"], "material_digest": contribution["material_digest"]},
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
            "id": "lens-" + canonical_digest(value["lens"], "matter.assistant-lens.v1")}


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
            _fail("E_AUTHORITY_REQUIRED")

    def _guard(self, view, payload):
        request = ReviewRequest(payload["request"]).value
        self.controls._view(view, actor=payload["token"]["actor"], authority=entity_ref(payload["token"]["authority"]),
                            capability="assessment", targets=[pressure_ref(self.scope_id, request),
                            review_ref(self.scope_id, ReviewRequest(request).wake_id)], now=self.clock())
        self.controls.require_current(view, payload["token"], capability="assessment",
                                      targets=[entity_ref(r) for r in _refs(request)])
        for reference in _refs(request):
            if pin(view.get(entity_ref(reference))) != reference:
                _fail("E_DEPENDENCY_STALE")
        self.access.require_current(view, payload["access_context"], references=_refs(request),
                                    audience=request["audience"], provider=request["provider"])

    def _read_targets(self, view, payload):
        request = ReviewRequest(payload["request"])
        return [pressure_ref(self.scope_id, request), review_ref(self.scope_id, request.wake_id),
                *[entity_ref(r) for r in _refs(request.value)],
                *[_consumed_ref(self.scope_id, request, c) for c in request.value["contributions"]]]

    def _action(self, action, request, *, token, access_context, command_id, result=None):
        target = pressure_ref(self.scope_id, request) if action == "pressure" else review_ref(self.scope_id, request.wake_id)
        with self.storage.snapshot() as view:
            old = _lookup(view, target)
        payload = _message("mutation", action=action, request=request.value,
            result=None if result is None else result.value, token=token,
            access_context=access_context.value if hasattr(access_context, "value") else access_context,
            previous=None if old is None else pin(old))
        command = self._prepare(_control_command(self.controls, payload=payload, schema=SCHEMA, target=target,
            command_id=command_id, idempotency_key=command_id, actor=token["actor"],
            authority=entity_ref(token["authority"]), kind="decision"))
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

    def _state(self, view, command, payload, *, preparing):
        payload = _wire("mutation", payload)
        request = self._request(payload["request"])
        action = payload["action"]
        target = pressure_ref(self.scope_id, request) if action == "pressure" else review_ref(self.scope_id, request.wake_id)
        schema_kind = "pressure" if action == "pressure" else "attempt"
        if (command["actor"] != payload["token"]["actor"] or
                command["authority"] != entity_ref(payload["token"]["authority"]) or
                command["body"]["control"]["body"]["scope"]["targets"] != [target]):
            _fail("E_AUTHORITY_REQUIRED")
        old, old_control = self._prior(view, command, payload, target, SCHEMA, preparing=preparing)
        prior = None if old is None else _wire(schema_kind, old["value"]["value"])
        pressure = _lookup(view, pressure_ref(self.scope_id, request))
        pressure_body = None if pressure is None else _wire("pressure", pressure["value"]["value"])
        pending = [] if pressure_body is None else pressure_body["pending"]
        active_wake = None if pressure_body is None else pressure_body["active_wake"]
        consumed = {canonical_bytes(c): _lookup(view, _consumed_ref(self.scope_id, request, c))
                    for c in request.value["contributions"]}
        fresh = True
        try:
            self._guard(view, payload)
        except ContractError:
            if action != "finish":
                raise
            fresh = False
        result = payload["result"]
        if action == "pressure":
            if result is not None:
                _fail()
            merged = {c["lineage"]: c for c in pending}
            for contribution in request.value["contributions"]:
                if consumed[canonical_bytes(contribution)] is None:
                    merged[contribution["lineage"]] = contribution
            value = _message("pressure", lens=request.value["lens"], matter=request.value["matter"],
                dependencies=request.value["dependencies"], pending=sorted(merged.values(), key=canonical_bytes), active_wake=active_wake,
                ledger=request.value["ledger"], control=None)
        elif action == "start":
            if result is not None or prior is not None:
                _fail("E_IDEMPOTENCY_CONFLICT")
            if active_wake is not None:
                _fail("E_DELIVERY_UNKNOWN")
            if any(c not in pending for c in request.value["contributions"]):
                _fail("E_DEPENDENCY_STALE")
            value = _message("attempt", request=request.value, outcome_unknown=True, started_at=self.clock(), finished_at=None, phase="started", result=None, control=None)
        else:
            if prior is None or prior["phase"] != "started" or prior["request"] != request.value:
                _fail("E_IDEMPOTENCY_CONFLICT")
            result = ReviewResult(result).value
            self._result_scope(request, result)
            value = _message("attempt", request=prior["request"], outcome_unknown=result["status"] == "unknown", started_at=prior["started_at"], finished_at=self.clock(), phase=result["status"] if fresh else "stale",
                             result=result if fresh else None, control=None)
        return {"old": old, "old_control": old_control, "targets": self._read_targets(view, payload),
                "value": value, "pressure": pressure, "consumed": consumed, "fresh": fresh}

    def _write(self, tx, payload, state, control):
        request = ReviewRequest(payload["request"])
        value = state["value"]
        value["control"] = control
        target = pressure_ref(self.scope_id, request) if payload["action"] == "pressure" else review_ref(self.scope_id, request.wake_id)
        tx.put_projection(target, domain(SCHEMA, value))
        if payload["action"] == "start":
            pressure = deepcopy(state["pressure"]["value"]["value"])
            pressure["active_wake"] = request.wake_id
            tx.put_projection(pressure_ref(self.scope_id, request), domain(SCHEMA, pressure))
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
                c["lineage"] == old["lineage"] and c["material_digest"] == old["material_digest"] for old in covered)]
            pressure["ledger"] = value["result"]["ledger"] or pressure["ledger"]
            pressure["active_wake"] = None
            tx.put_projection(pressure_ref(self.scope_id, request), domain(SCHEMA, pressure))
        elif payload["action"] == "finish" and not value["outcome_unknown"]:
            pressure = deepcopy(state["pressure"]["value"]["value"])
            if pressure["active_wake"] != request.wake_id:
                _fail("E_DEPENDENCY_STALE")
            pressure["active_wake"] = None
            tx.put_projection(pressure_ref(self.scope_id, request), domain(SCHEMA, pressure))

    def record_pressure(self, request, *, token, access_context, command_id):
        """Host-selected distinct contributions; no numeric threshold is supplied.

        A host-declared provenance lineage occupies one pending slot. Reprints
        do not add slots; a changed exact reference can replace that slot while
        the prior association remains in immutable storage history.
        """
        request = self._request(request)
        self._host_guard(request)
        artifacts = self.resolve(request, [c["reference"] for c in request.value["contributions"]],
                                 token=token, access_context=access_context)
        by_ref = {canonical_bytes(a["reference"]): a for a in artifacts}
        for contribution in request.value["contributions"]:
            if pressure_contribution(by_ref[canonical_bytes(contribution["reference"])],
                                     lineage=contribution["lineage"]) != contribution:
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
                return view.get(pressure_ref(self.scope_id, request))
        return self._action("pressure", request, token=token, access_context=access_context, command_id=command_id)[0]

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
            self._host_guard(request, _result_refs(body["result"]), historical=True, at=self.clock())
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
        if prior_body["phase"] != "started":
            # Completion replay is read guarded and cannot clear newly arrived
            # pressure or update a rule for a second time.
            if prior_body["result"] != result.value:
                _fail("E_IDEMPOTENCY_CONFLICT")
            self._host_guard(request, _result_refs(prior_body["result"]), historical=True, at=self.clock())
            with self.storage.snapshot() as view:
                self.access.require_history(view, access_context, references=_refs(request.value))
                self.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])},
                                     [entity_ref(r) for r in _refs(request.value)])
            return prior
        fresh = True
        try:
            self._host_guard(request)
        except ContractError:
            fresh = False
        if fresh and result.value["status"] == "completed":
            references = [result.value["review"], result.value["session"], *result.value["rule_changes"]]
            if result.value["ledger"] is not None:
                if compare_times(result.value["ledger"]["as_of"], self.clock()) > 0:
                    _fail("E_EVIDENCE_UNAVAILABLE")
                references += [r for name in LEDGER_FIELDS for r in result.value["ledger"][name]]
            self._host_guard(request, references, at=self.clock())
            artifacts = self._resolve(request, references, at=self.clock())
            persisted_review = next(a for a in artifacts if a["reference"] == result.value["review"])
            content = persisted_review["content"]
            if content.get("wake_id") != request.wake_id:
                _fail("E_EVIDENCE_INVALID")
            for field in ("status", "proposal", "reviewed", "rule_changes"):
                if content.get(field) != result.value[field]:
                    _fail("E_EVIDENCE_INVALID")
        if not fresh and result.value["status"] != "unknown":
            # Retain a safe stopped result without admitting stale host output.
            result = ReviewResult(_message("review_result", wake_id=request.wake_id, status="stopped", proposal=None,
                review=None, session=None, reviewed=[], ledger=None, rule_changes=[], error_code="context_changed"))
        return self._action("finish", request, token=token, access_context=access_context,
                            command_id="assistant-finish-" + uuid4().hex, result=result)[0]

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
            result = reviewer(request.value, request.wake_id)
        except Exception:
            result = _message("review_result", wake_id=request.wake_id, status="unknown", proposal=None,
                review=None, session=None, reviewed=[], ledger=None, rule_changes=[], error_code="review_outcome_unknown")
        return self.complete(request, result, token=token, access_context=access_context)

    def _resolve(self, request, references, *, at):
        if not isinstance(references, (tuple, list)) or len(references) > request.value["limits"]["max_reads"]:
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
            if len(seen) + len(visiting) >= request.value["limits"]["max_reads"]:
                _fail("E_BUDGET_EXHAUSTED")
            _pointer(reference, request.value["lens"])
            self._host_guard(request, [reference], at=at)
            try:
                artifact = _wire("host_artifact", self.host.resolve(deepcopy(request.value["lens"]), deepcopy(reference), deepcopy(at)))
            except ContractError:
                raise
            except Exception:
                _fail("E_EVIDENCE_UNAVAILABLE")
            total += len(canonical_bytes(artifact))
            if total > request.value["limits"]["max_bytes"]:
                _fail("E_BUDGET_EXHAUSTED")
            if (artifact["reference"] != reference or host_artifact_reference(artifact) != reference
                    or artifact["lens"] != request.value["lens"]):
                _fail("E_EVIDENCE_INVALID")
            if compare_times(artifact["available_at"], at) > 0:
                _fail("E_EVIDENCE_UNAVAILABLE")
            if (reference["kind"] == "finding" and artifact["classification"] not in {"source_quote", "jev_judgment", "interpretation"} or
                    reference["kind"] == "judgment" and artifact["classification"] != "jev_judgment" or
                    reference["kind"] == "evidence" and artifact["classification"] not in {"source_quote", "source_fact"}):
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
        self._host_guard(request, [a["reference"] for a in result], at=at)
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

    def pressure(self, request, *, token, access_context):
        request = self._request(request)
        self._host_guard(request)
        with self.storage.snapshot() as view:
            self._guard(view, {"request": request.value, "token": token,
                              "access_context": access_context.value if hasattr(access_context, "value") else access_context})
            body = deepcopy(view.get(pressure_ref(self.scope_id, request))["value"]["value"])
        self._host_guard(request, _pressure_refs(body), historical=True)
        self._resolve(request, _pressure_refs(body), at=request.value["as_of"])
        return body


    def inspect(self, request, *, actor, authority, access_context):
        """Read an attempt under present authority; started means outcome unknown.

        No automatic takeover or retry is authorized by this read. Historical
        results are not fresh proposals and cannot perform another reset.
        """
        request = self._request(request)
        self._host_guard(request, historical=True)
        with self.storage.snapshot() as view:
            self.controls._audit(view, {"actor": actor, "authority": authority},
                                 [entity_ref(r) for r in _refs(request.value)])
            self.access.require_history(view, access_context, references=_refs(request.value))
            row = view.get(review_ref(self.scope_id, request.wake_id))
            value = deepcopy(row["value"]["value"])
        self._host_guard(request, _result_refs(value["result"]), historical=True, at=self.clock())
        if compare_times(value["finished_at"] or value["started_at"], self.clock()) > 0:
            _fail("E_EVIDENCE_UNAVAILABLE")
        value["human_communicated"] = False
        return value

    def history(self, request, *, actor, authority, access_context):
        """Authorized pointer-only pressure history; reset never deletes it."""
        request = self._request(request)
        with self.storage.snapshot() as view:
            self.controls._audit(view, {"actor": actor, "authority": authority},
                                 [entity_ref(r) for r in _refs(request.value)])
            self.access.require_history(view, access_context, references=_refs(request.value))
            rows = view.history(pressure_ref(self.scope_id, request))
        for row in rows:
            body = _wire("pressure", row["value"]["value"])
            refs = [c["reference"] for c in body["pending"]]
            if body["ledger"] is not None:
                refs += [ref for name in LEDGER_FIELDS for ref in body["ledger"][name]]
            self._host_guard(request, refs, historical=True)
        return deepcopy(rows)
