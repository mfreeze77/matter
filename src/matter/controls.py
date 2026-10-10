"""Trusted controls, durable scoped fences, and cooperative cancellation hooks.

Only host code may instantiate these capabilities or use the raw storage port.
Evaluation and transport happen outside SQLite transactions. A fence protects
the authorization/commit boundary; it cannot preempt a running Python callable
or undo a transport that crossed its documented authorization boundary.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from .authority import AuthorityPolicy, CAPABILITIES
from .canonical import canonical_bytes, canonical_digest
from .citations import _contract, _domain
from .contracts import command_digest, validate_command, validate_record
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .storage.base import _validate_fragment, _validate_projection
from .time import compare_times


CONTROL_NAMESPACE = "matter.controls"
TOKEN_EXTENSION = "matter:control-token"
_ENGINE = {"namespace": "matter", "id": "trusted-controls", "version": "1.0",
           "digest": canonical_digest({"implementation": "trusted-controls.v1"}, "matter.component.v1")}
DEFAULT_OPERATION_CAPABILITIES = {
    "ingest_observation": "write", "create_matter": "write", "update_matter_metadata": "write",
    "commit_occurrence_grouping": "association", "publish_association_candidates": "association",
    "propose_association": "association", "accept_association": "association", "decide_association": "association",
    "append_claim": "write", "relate_evidence": "association", "revise_evidence_acceptance": "association",
    "link_matters": "association", "merge_matters": "merge", "correct_merge": "correction",
    "release_identity_separations": "correction", "commit_assessment": "assessment",
    "invalidate_dependents": "assessment", "request_transition": "transition",
    "assess": "assessment", "publish_coverage": "write", "register_negative_watch": "assessment",
}


def _now():
    return {"state": "known", "value": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "precision": "microsecond"}


def _key(ref):
    return ref["scope_id"], ref["namespace"], ref["id"]


def _sorted(values):
    return sorted(values, key=canonical_bytes)


def _unique(values):
    return _sorted({canonical_bytes(value): deepcopy(value) for value in values}.values())


def _targets(scope, values):
    if type(values) not in (list, tuple):
        raise StorageError("E_SCHEMA_INVALID")
    result = [_validate_fragment(value, "entity_ref") for value in values]
    if any(value["scope_id"] != scope for value in result):
        raise StorageError("E_SCOPE_FORBIDDEN")
    if len({_key(value) for value in result}) != len(result):
        raise StorageError("E_SCHEMA_INVALID", "Control targets must have distinct identities.")
    if any(value["namespace"].startswith("matter.") and value["record_type"] == PROJECTION_TYPE for value in result):
        raise StorageError("E_SCOPE_FORBIDDEN", "Internal projections cannot be user control targets.")
    return _sorted(result)


def _checked(name, value):
    descriptor, validator = _contract(name)
    canonical_bytes(value)
    if not validator.is_valid(value):
        raise StorageError("E_SCHEMA_INVALID", "The trusted-control value does not match its declared schema.")
    return deepcopy(value)


def control_effect(action, reason, *, capabilities=(), payload=None):
    """Construct a typed effect; it grants no authority by itself."""
    body = {"action": action, "reason": reason, "capabilities": sorted(capabilities)}
    if payload is not None:
        body["payload"] = deepcopy(payload)
    return {"schema": deepcopy(_contract("control-effect")[0]), "value": _checked("control-effect", body)}


def control_fence_ref(scope_id, target=None):
    scope = _validate_fragment(scope_id, "identifier")
    if target is not None:
        target = _targets(scope, [target])[0]
    return {"scope_id": scope, "namespace": CONTROL_NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "fence-" + canonical_digest({"scope_id": scope, "target": target}, "matter.control-fence.v1")}


def _sequence_ref(scope):
    return {"scope_id": scope, "namespace": CONTROL_NAMESPACE, "record_type": PROJECTION_TYPE, "id": "sequence"}


def _lookup(view, reference):
    try:
        return view.get(reference)
    except StorageError as error:
        if error.code != "E_NOT_FOUND":
            raise
        return None


def _projection(view, reference, name):
    try:
        stored = view.lookup_identity(reference)
    except StorageError as error:
        if error.code != "E_NOT_FOUND":
            raise
        return None
    descriptor, validator = _contract(name)
    try:
        record = _validate_projection(stored)
        if (entity_ref(record) != reference or record["watch_keys"] or record["value"]["schema"] != descriptor
                or not validator.is_valid(record["value"]["value"]) or record["value"]["value"]["scope_id"] != reference["scope_id"]):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise StorageError("E_STORAGE_UNAVAILABLE", "A control projection failed integrity validation.") from None
    return record


def _fence(view, scope, target):
    record = _projection(view, control_fence_ref(scope, target), "control-fence")
    if record is not None and record["value"]["value"]["target"] != target:
        raise StorageError("E_STORAGE_UNAVAILABLE", "A control fence has the wrong target.")
    return record


def _control(view, reference):
    record = validate_record(view.get(reference))
    if record["record_type"] != "control" or pin(record) != reference:
        raise StorageError("E_STORAGE_UNAVAILABLE", "A control receipt could not be verified.")
    return record


def _effect(record):
    effect = record["body"]["effect"]
    if effect["schema"] != _contract("control-effect")[0]:
        raise StorageError("E_POLICY_INVALID", "Unregistered control effects are inert and cannot be applied.")
    value = _checked("control-effect", effect["value"])
    action, kind = value["action"], record["body"]["control_kind"]
    if ((action == "cancel" and kind != "cancellation")
            or (action == "resume" and kind not in {"instruction", "correction", "decision"})
            or (action in {"deny", "allow"} and kind != "permission")
            or (action in {"invalidate", "disposition"} and kind in {"permission", "cancellation"})
            or bool(value["capabilities"]) != (action in {"deny", "allow"})):
        raise StorageError("E_POLICY_INVALID", "The control kind and typed effect disagree.")
    return value


def _active(record, now):
    body = record["body"]
    # For this registered effect schema only, unknown/not_applicable means
    # explicitly no automatic expiry. Other unknown endpoints are refused.
    end = body["effective_until"]
    return compare_times(body["effective_from"], now) <= 0 and (end["state"] == "unknown" or compare_times(now, end) < 0)


def _governing(body):
    return _unique([body["last_control"], *body["cancellations"],
                    *[item["control"] for item in body["denials"]], *[item["control"] for item in body["dispositions"]]])


class _Collector:
    def __init__(self, view, include):
        self.view, self.include = view, include

    def get(self, reference):
        value = self.view.get(reference)
        self.include(pin(value))
        return value

    def lookup_identity(self, reference):
        value = self.view.lookup_identity(reference)
        self.include(pin(value))
        return value


class ControlService:
    """Host-only control lane. It never calls an evaluator or consults budgets.

    ``prepare`` fills the next audit epoch and exact read pins once. Persist
    and retry that returned command unchanged. A stale refusal requires a new
    command ID/key and a fresh explicit prepare; it is never silently retried.
    """

    def __init__(self, storage, *, policy: AuthorityPolicy, clock=None, hooks=None):
        if not isinstance(policy, AuthorityPolicy):
            raise StorageError("E_POLICY_INVALID")
        if policy.scope_id != storage.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        self._storage, self.policy = storage, policy
        self._clock = clock or _now
        if not callable(self._clock):
            raise StorageError("E_POLICY_INVALID")
        self._hooks = dict(hooks or {})
        for name, hook in self._hooks.items():
            _validate_fragment(name, "identifier")
            if not callable(hook):
                raise StorageError("E_POLICY_INVALID")

    @property
    def scope_id(self):
        return self._storage.scope_id

    def _time(self, as_of=None):
        now = _validate_fragment(self._clock(), "known_time")
        if as_of is not None and compare_times(_validate_fragment(as_of, "known_time"), now) != 0:
            raise StorageError("E_POLICY_INVALID", "Historical or future time cannot authorize current work; inject a host clock for simulation.")
        return now

    def _command(self, command):
        value = validate_command(command)
        if value["operation"] != "record_control":
            raise StorageError("E_SCHEMA_INVALID")
        if value["scope_id"] != self.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        control = value["body"]["control"]
        body = control["body"]
        if (control["scope_id"] != self.scope_id or body["scope"]["scope_id"] != self.scope_id
                or body["actor"] != value["actor"] or body["authority"] != value["authority"]):
            raise StorageError("E_SCOPE_FORBIDDEN", "The authenticated envelope and control must name the same actor, authority and scope.")
        targets = _targets(self.scope_id, body["scope"]["targets"])
        if body["scope"]["targets"] != targets:
            raise StorageError("E_SCHEMA_INVALID", "Control targets use canonical ordering.")
        if control["namespace"].startswith("matter."):
            raise StorageError("E_SCOPE_FORBIDDEN", "Host control identities must use a host namespace.")
        _effect(control)
        for reference in [*value["expected_revisions"], *control.get("supersedes", []), *control["provenance"]["parents"]]:
            if reference["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")
        return value

    def _state(self, view, command, *, preparing=False):
        control, scope = command["body"]["control"], self.scope_id
        body, now = control["body"], self._time()
        targets = body["scope"]["targets"]
        authority = self.policy.authorize(view, actor=command["actor"], authority=command["authority"],
                                          targets=targets, control_kind=body["control_kind"])
        effect = _effect(control)
        if any(cap not in self.policy.definition["capabilities"] for cap in effect["capabilities"]):
            raise StorageError("E_AUTHORITY_REQUIRED", "A permission control exceeds its static capability ceiling.")
        existing = _lookup(view, entity_ref(control))
        if existing is not None:
            original = deepcopy(existing)
            original.pop("creation_receipt", None)
            if canonical_bytes(original) != canonical_bytes(control):
                raise StorageError("E_SOURCE_IDENTITY_CONFLICT", "A control identity cannot be reused with changed content.")
            return {"existing": existing, "authority": authority}
        end = body["effective_until"]
        if effect["action"] in {"resume", "allow"} and end["state"] != "unknown":
            raise StorageError("E_POLICY_INVALID", "Release is explicit permanent supersession; temporary overrides are unsupported.")
        if (compare_times(body["effective_from"], now) > 0
                or (end["state"] == "known" and (compare_times(end, body["effective_from"]) <= 0 or compare_times(end, now) <= 0))
                or (end["state"] == "unknown" and end["reason"] != "not_applicable")):
            raise StorageError("E_POLICY_INVALID", "Controls must apply now and have an explicit valid expiry policy.")
        sequence = _projection(view, _sequence_ref(scope), "control-sequence")
        epoch = 1 + (sequence["value"]["value"]["epoch"] if sequence else 0)
        if not preparing and body["control_epoch"] != epoch:
            raise StorageError("E_REVISION_CONFLICT", "Prepare a new control attempt against the current sequence.")
        _validate_fragment(epoch, "counter")
        fences = [_fence(view, scope, target) for target in (targets or [None])]
        superseded = {canonical_bytes(ref): ref for ref in control.get("supersedes", [])}
        if len(superseded) != len(control.get("supersedes", [])):
            raise StorageError("E_SCHEMA_INVALID")
        for ref in superseded.values():
            _validate_fragment(ref, "control_dependency")
            old = _control(view, ref)
            if old["body"]["scope"] != body["scope"]:
                raise StorageError("E_SCOPE_FORBIDDEN", "Supersession cannot cross target scopes.")
        for fence in fences:
            if fence is None:
                if effect["action"] in {"resume", "allow"}:
                    raise StorageError("E_POLICY_INVALID", "Release requires an existing exact restriction.")
                continue
            previous = fence["value"]["value"]
            # Read and retain exact current governing controls in the journal.
            for ref in _governing(previous):
                _control(view, ref)
            required = []
            if effect["action"] == "resume":
                required = [ref for ref in previous["cancellations"] if _control(view, ref)["body"]["scope"] == body["scope"]]
                if not required:
                    raise StorageError("E_POLICY_INVALID", "No cancellation is available to release.")
            elif effect["action"] == "allow":
                current = {item["capability"]: item["control"] for item in previous["denials"]
                           if _control(view, item["control"])["body"]["scope"] == body["scope"]}
                if any(cap not in current for cap in effect["capabilities"]):
                    raise StorageError("E_POLICY_INVALID", "Permission release must name currently denied capabilities.")
                required = [current[cap] for cap in effect["capabilities"]]
            if any(canonical_bytes(ref) not in superseded for ref in required):
                raise StorageError("E_AUTHORITY_REQUIRED", "Release must explicitly supersede the current restriction.")
        return {"existing": None, "authority": authority, "epoch": epoch, "fences": fences, "effect": effect}

    def prepare(self, command):
        command = self._command(command)
        expected = command["expected_revisions"]
        present = {_key(ref): ref for ref in expected}
        if len(present) != len(expected):
            raise StorageError("E_SCHEMA_INVALID")
        def include(reference):
            if _key(reference) not in present:
                expected.append(reference)
                present[_key(reference)] = reference
        with self._storage.snapshot() as view:
            try:
                journal = view.command_receipt(command["idempotency_key"])
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
            else:
                if journal["command_digest"] != command_digest(command):
                    raise StorageError("E_IDEMPOTENCY_CONFLICT")
                return command
            state = self._state(_Collector(view, include), command, preparing=True)
            if state["existing"] is None:
                command["body"]["control"]["body"]["control_epoch"] = state["epoch"]
        return self._command(command)

    def apply(self, command):
        command = self._command(command)
        return self._storage.execute(command, self._apply)

    def _stronger(self, tx, previous, control):
        """Retain the conjunction of same-scope restrictions for future work.

        All newly applied restrictions are effective now. The later expiry
        therefore dominates; explicit no-expiry dominates every finite end.
        Resume/allow remain the only operations that can reduce a restriction.
        """
        if previous is None:
            return pin(control)
        old = _control(tx, previous)
        end, new_end = old["body"]["effective_until"], control["body"]["effective_until"]
        if end["state"] == "unknown" or (new_end["state"] == "known" and compare_times(end, new_end) >= 0):
            return previous
        return pin(control)

    def _apply(self, tx):
        command = tx.command
        state = self._state(tx, command)
        if state["existing"] is not None:
            record = state["existing"]
            return tx.success("duplicate", {"control": pin(record), "control_epoch": record["body"]["control_epoch"]})
        control = tx.insert(command["body"]["control"])
        ref, effect, epoch = pin(control), state["effect"], state["epoch"]
        tx.put_projection(_sequence_ref(self.scope_id), _domain("control-sequence", {"scope_id": self.scope_id, "epoch": epoch}))
        for target, existing in zip(control["body"]["scope"]["targets"] or [None], state["fences"]):
            value = deepcopy(existing["value"]["value"]) if existing else {
                "scope_id": self.scope_id, "target": target, "epoch": epoch, "last_control": ref,
                "cancellations": [], "denials": [], "dispositions": []}
            value.update(epoch=epoch, last_control=ref)
            action = effect["action"]
            def same_scope(reference):
                return _control(tx, reference)["body"]["scope"] == control["body"]["scope"]
            if action in {"cancel", "resume"}:
                same = [item for item in value["cancellations"] if same_scope(item)]
                value["cancellations"] = [item for item in value["cancellations"] if not same_scope(item)]
                if action == "cancel":
                    value["cancellations"].append(self._stronger(tx, same[0] if same else None, control))
                value["cancellations"] = _unique(value["cancellations"])
            if action in {"deny", "allow"}:
                denied = {item["capability"]: item["control"] for item in value["denials"] if same_scope(item["control"])}
                others = [item for item in value["denials"] if not same_scope(item["control"])]
                for capability in effect["capabilities"]:
                    if action == "deny":
                        denied[capability] = self._stronger(tx, denied.get(capability), control)
                    else:
                        denied.pop(capability)
                value["denials"] = _sorted([*others, *[{"capability": cap, "control": denied[cap]} for cap in sorted(denied)]])
            if action in {"invalidate", "disposition"}:
                kinds = {item["kind"]: item["control"] for item in value["dispositions"] if same_scope(item["control"])}
                others = [item for item in value["dispositions"] if not same_scope(item["control"])]
                kinds[control["body"]["control_kind"]] = ref
                value["dispositions"] = _sorted([*others, *[{"kind": kind, "control": kinds[kind]} for kind in sorted(kinds)]])
            tx.put_projection(control_fence_ref(self.scope_id, target), _domain("control-fence", value))
        return tx.success("applied", {"control": ref, "control_epoch": epoch})

    def _view(self, view, *, actor, authority, capability, targets, now, audit=False):
        targets = _targets(self.scope_id, targets)
        admitted = self.policy.authorize(view, actor=actor, authority=authority, targets=targets, capability=capability)
        fences, controls, active, epoch = [], {}, {}, 0
        for target in [None, *targets]:
            fence = _fence(view, self.scope_id, target)
            fences.append({"target": target, "reference": control_fence_ref(self.scope_id, target),
                           "pin": pin(fence) if fence else None})
            if fence is None:
                continue
            body = fence["value"]["value"]
            epoch = max(epoch, body["epoch"])
            for reference in _governing(body):
                control = _control(view, reference)
                scope = control["body"]["scope"]
                if scope["scope_id"] != self.scope_id or (target is None and scope["targets"] or target is not None and target not in scope["targets"]):
                    raise StorageError("E_STORAGE_UNAVAILABLE", "A fence references a control outside its target scope.")
                controls[canonical_bytes(reference)] = reference
                if _active(control, now):
                    active[canonical_bytes(reference)] = reference
            if any(canonical_bytes(reference) in active for reference in body["cancellations"]) and not audit:
                raise StorageError("E_CANCELLED", "An applicable host cancellation is active.")
            if any(item["capability"] == capability and canonical_bytes(item["control"]) in active for item in body["denials"]):
                raise StorageError("E_AUTHORITY_REQUIRED", "An applicable host permission denial is active.")
        return {"scope_id": self.scope_id, "actor": deepcopy(actor), "authority": admitted, "policy": self.policy.reference,
                "capability": capability, "targets": targets, "control_epoch": epoch, "captured_at": now,
                "fences": fences, "controls": _sorted(controls.values()), "active_controls": _sorted(active.values())}

    def capture(self, *, actor, authority, capability, targets, as_of=None):
        """Capture before expensive work. The result is detached, never authority by itself."""
        with self._storage.snapshot() as view:
            return _checked("control-token", self._view(view, actor=actor, authority=authority, capability=capability,
                            targets=targets, now=self._time(as_of)))

    def require_current(self, view, token, *, capability, targets, as_of=None):
        token = _checked("control-token", token)
        required = _targets(self.scope_id, targets)
        if (token["scope_id"] != self.scope_id or token["policy"] != self.policy.reference
                or token["capability"] != capability or (not required and token["targets"])
                or any(target not in token["targets"] for target in required)):
            raise StorageError("E_AUTHORITY_REQUIRED", "The work token does not cover the trusted operation context.")
        current = self._view(view, actor=token["actor"], authority=token["authority"], capability=capability,
                             targets=token["targets"], now=self._time(as_of))
        if any(current[key] != token[key] for key in ("fences", "controls", "active_controls", "control_epoch")):
            raise StorageError("E_DEPENDENCY_STALE", "The work used an earlier applicable control state.")
        return deepcopy(token)

    def check(self, token, *, capability=None, targets=None, as_of=None):
        token = _checked("control-token", token)
        with self._storage.snapshot() as view:
            return self.require_current(view, token, capability=capability or token["capability"],
                                        targets=token["targets"] if targets is None else targets, as_of=as_of)

    def read(self, token, reference):
        """Authorize and read within one consistent snapshot; no historical-time bypass."""
        target = entity_ref(reference)
        with self._storage.snapshot() as view:
            self.require_current(view, token, capability="read", targets=[target])
            return deepcopy(view.get(reference))

    def authorize_dispatch(self, transaction, token, *, targets):
        """Linearize a host's dispatch authorization inside its transaction.

        The host derives targets from its actual intent and declares all reads.
        It must record that authorization before external I/O. This seam does
        not send, lease an outbox item, or promise exactly-once transport.
        """
        return self.require_current(transaction, token, capability="delivery", targets=targets)

    def current(self, target=None):
        """Trusted-host introspection of current control state, not an end-user data API."""
        with self._storage.snapshot() as view:
            return deepcopy(_fence(view, self.scope_id, target))

    def _audit(self, view, command, targets):
        # Exact replay may return a past result after cancellation. Reading that
        # journal still requires present read authority and respects read denial.
        self._view(view, actor=command["actor"], authority=command["authority"], capability="read",
                   targets=targets, now=self._time(), audit=True)

    def _hook_identity(self, control, name, attempt, phase):
        return "hook-" + canonical_digest({"control": control, "hook": name, "attempt": attempt, "phase": phase}, "matter.control-hook.v1")

    def hook_status(self, control, hook_id, *, attempt_id="initial"):
        """Return none, started (outcome unknown), succeeded, or failed from durable receipts."""
        for phase in ("finished", "started"):
            reference = {"scope_id": self.scope_id, "namespace": "matter.controls.hooks", "record_type": "receipt",
                         "id": self._hook_identity(control, hook_id, attempt_id, phase)}
            record = _lookup(self._storage, reference)
            if record is not None:
                return deepcopy(record["body"]["details"]["value"])
        return None

    def _hook_receipt(self, control, name, attempt, phase, status, error_type=None, *, claimed=None):
        identity = self._hook_identity(pin(control), name, attempt, phase)
        input_control = deepcopy(control)
        input_control.pop("creation_receipt")
        command = {"schema_version": "1.0", "operation": "record_control", "command_id": identity,
                   "idempotency_key": identity, "scope_id": self.scope_id, "actor": control["body"]["actor"],
                   "authority": control["body"]["authority"], "expected_revisions": [pin(control)], "body": {"control": input_control}}
        def handler(tx):
            tx.get(pin(control))
            now = self._time()
            tx.insert({"schema_version": "1.0", "record_type": "receipt", "scope_id": self.scope_id,
                "namespace": "matter.controls.hooks", "id": identity,
                "provenance": {"origin": "host", "producer": _ENGINE, "recorded_at": now, "parents": [pin(control)]},
                "body": {"stage": "operation", "operation_id": identity, "recorded_at": now,
                         "outcome": "matter:control_hook_" + status, "evidence": [pin(control)],
                         "details": _domain("control-hook", {"control": pin(control), "hook_id": name,
                             "attempt_id": attempt, "status": status, "error_type": error_type})}})
            result = tx.success("duplicate", {"control": pin(control), "control_epoch": control["body"]["control_epoch"]})
            if claimed is not None:
                claimed.append(True)
            return result
        return self._storage.execute(command, handler)

    def run_hooks(self, control, *, attempt_id):
        """Explicit hook attempt; retrying an ID never blindly reruns a started callback.

        Hook outcomes are separately observable. A failed/unavailable follow-up
        does not change the already committed control result. Callers may query
        status or use a NEW attempt ID to explicitly retry cooperative work.
        """
        _validate_fragment(attempt_id, "identifier")
        record = _control(self._storage, control)
        reports = []
        for name, hook in self._hooks.items():
            prior = self.hook_status(control, name, attempt_id=attempt_id)
            if prior is not None:
                reports.append(prior)
                continue
            # The callback may run only in the unique reservation handler's
            # caller. The handler sets this process-local bit before COMMIT;
            # an unavailable commit outcome is never treated as authorization.
            claimed = []
            # Reserve by using a unique receipt insertion. A competing caller
            # that replays this command must not run the callback.
            identity = self._hook_identity(control, name, attempt_id, "started")
            try:
                before = self._storage.command_receipt(identity)
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    reports.append({"hook_id": name, "attempt_id": attempt_id, "status": "unavailable"})
                    continue
            else:
                reports.append(self.hook_status(control, name, attempt_id=attempt_id))
                continue
            # _hook_receipt reports its reservation ownership through the
            # storage handler, so simultaneous exact retries cannot both run.
            result = self._hook_receipt(record, name, attempt_id, "started", "started", claimed=claimed)
            if result["status"] != "success" or not claimed:
                reports.append({"hook_id": name, "attempt_id": attempt_id, "status": "unavailable" if result["status"] != "success" else "started"})
                continue
            status, error_type = "succeeded", None
            try:
                hook(deepcopy(record))
            except Exception as error:
                status, error_type = "failed", type(error).__name__
            finished = self._hook_receipt(record, name, attempt_id, "finished", status, error_type)
            reports.append(self.hook_status(control, name, attempt_id=attempt_id) if finished["status"] == "success"
                           else {"hook_id": name, "attempt_id": attempt_id, "status": "started"})
        return reports

def command_targets(command):
    """Derive coverage from the complete prepared command, never a supplied subset.

    All explicit entity identities in body/readset count; internal projections
    and receipt/control identities are implementation bookkeeping. Existing
    service preparation must first publish its complete decision read set.
    """
    value = validate_command(command)
    found = {}
    def visit(item):
        if type(item) is dict:
            if all(key in item for key in ("scope_id", "namespace", "record_type", "id")):
                ref = entity_ref(item)
                if ref["record_type"] not in {"receipt", "control"} and not (ref["record_type"] == PROJECTION_TYPE and ref["namespace"].startswith("matter.")):
                    found[_key(ref)] = ref
            for child in item.values():
                visit(child)
        elif type(item) is list:
            for child in item:
                visit(child)
    visit(value["body"])
    visit(value["expected_revisions"])
    return _targets(value["scope_id"], list(found.values()))


class GuardedStorage:
    """Mutation port decorator for trusted services; raw reads remain host-only.

    Use ``controls.read`` for permission-checked data delivery. Snapshot/get
    delegation here is for existing trusted service preparation, not an API
    exposed to agents. The raw storage handle remains privileged host machinery.
    """

    def __init__(self, storage, *, controls: ControlService, operation_capabilities=None):
        if storage is not controls._storage:
            raise StorageError("E_POLICY_INVALID", "The guard and service must share one storage handle.")
        self._storage, self.controls = storage, controls
        self._operations = dict(DEFAULT_OPERATION_CAPABILITIES if operation_capabilities is None else operation_capabilities)
        if any(cap not in CAPABILITIES for cap in self._operations.values()) or "record_control" in self._operations:
            raise StorageError("E_POLICY_INVALID")

    def __getattr__(self, name):
        return getattr(self._storage, name)

    def _context(self, command):
        command = validate_command(command)
        if command["operation"] not in self._operations:
            raise StorageError("E_AUTHORITY_REQUIRED", "This trusted route has no declared capability.")
        return self._operations[command["operation"]], command_targets(command)

    def capture(self, prepared_command):
        command = validate_command(prepared_command)
        capability, targets = self._context(command)
        return self.controls.capture(actor=command["actor"], authority=command["authority"], capability=capability, targets=targets)

    def prepare(self, command, *, token):
        """Bind an ORIGINAL pre-work token; never capture or refresh authority here."""
        command = validate_command(command)
        capability, targets = self._context(command)
        token = _checked("control-token", token)
        if command["actor"] != token["actor"] or command["authority"] != entity_ref(token["authority"]):
            raise StorageError("E_AUTHORITY_REQUIRED")
        self.controls.check(token, capability=capability, targets=targets)
        extensions = command.setdefault("extensions", {})
        wrapped = {"schema": deepcopy(_contract("control-token")[0]), "value": deepcopy(token)}
        if TOKEN_EXTENSION in extensions and extensions[TOKEN_EXTENSION] != wrapped:
            raise StorageError("E_IDEMPOTENCY_CONFLICT", "An existing work token cannot be replaced.")
        extensions[TOKEN_EXTENSION] = wrapped
        present = {_key(ref): ref for ref in command["expected_revisions"]}
        for reference in [token["authority"], *token["controls"], *[entry["pin"] for entry in token["fences"] if entry["pin"] is not None]]:
            if _key(reference) in present and present[_key(reference)] != reference:
                raise StorageError("E_DEPENDENCY_STALE")
            if _key(reference) not in present:
                command["expected_revisions"].append(deepcopy(reference))
                present[_key(reference)] = reference
        return validate_command(command)

    def execute(self, command, handler):
        command = validate_command(command)
        capability, targets = self._context(command)
        wrapped = command.get("extensions", {}).get(TOKEN_EXTENSION)
        if wrapped is None or wrapped["schema"] != _contract("control-token")[0]:
            raise StorageError("E_AUTHORITY_REQUIRED", "Protected work requires its original control token.")
        token = _checked("control-token", wrapped["value"])
        if command["actor"] != token["actor"] or command["authority"] != entity_ref(token["authority"]):
            raise StorageError("E_AUTHORITY_REQUIRED")
        def guarded(tx):
            self.controls.require_current(tx, token, capability=capability, targets=targets)
            return handler(tx)
        return self._storage.execute(command, guarded,
            replay_guard=lambda view: self.controls._audit(view, command, targets))
