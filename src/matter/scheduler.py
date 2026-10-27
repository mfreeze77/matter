"""MAT-020 durable finite conditions, coalesced firing and atomic attention.

No daemon, business calendar or evaluator is invoked here. The host supplies a
prepared deterministic AttentionService command retaining the timer's original
token. Direct controls are applied through ControlService, never this queue.
"""

from copy import deepcopy

from ._rule_values import FrozenValue, descriptor, domain, fragment
from .attention import AttentionService
from .budgets import _Reads, _lookup, _value, milliseconds
from .canonical import canonical_bytes, canonical_digest
from .contracts import ContractError, validate_command
from .controls import ControlService, command_targets
from .dependencies import capture_dependencies
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times, known_time_key


NAMESPACE = "matter.scheduler"
REQUEST_EXTENSION = "matter:timer-request"
_UNUSED = {"state": "unknown", "reason": "not_applicable"}
_ENGINE = descriptor("matter", "finite-scheduler", "1.0", {"catchup": "latest-due-per-condition",
    "firing": "atomic-attention-stage", "controls": "original-work-token", "semantic_calls": 0}, "matter.scheduler.v1")


def _fail(code="E_POLICY_INVALID"):
    raise StorageError(code, "The timer or original temporal condition is invalid.")


class TimerDefinition(FrozenValue):
    def __init__(self, value):
        value = domain("timer-definition", value)["value"]
        checkpoints = value["checkpoints"]
        if (len(canonical_bytes(value)) > 262144 or len({item["id"] for item in checkpoints}) != len(checkpoints) or
                any(compare_times(left["at"], right["at"]) != -1 for left, right in zip(checkpoints, checkpoints[1:])) or
                compare_times(checkpoints[-1]["at"], value["expires_at"]) != -1 or
                any(ref["scope_id"] != value["matter"]["scope_id"] for ref in [value["assessment"], *value["dependencies"]]) or
                value["assessment"] not in value["dependencies"] or value["matter"] not in value["dependencies"]):
            _fail()
        self._freeze(value)

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["semantic_version"], value, "matter.timer-definition.v1")


def timer_ref(scope_id, definition):
    value = definition.value
    return {"scope_id": fragment(scope_id, "identifier"), "namespace": NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "timer-" + canonical_digest({"namespace": value["namespace"], "id": value["id"],
                "condition_id": value["condition_id"]}, "matter.timer-slot.v1")}


def _watch(scope):
    return "timer-active-" + canonical_digest(scope, "matter.timer-active.v1")


def _next(value):
    points = value["definition"]["checkpoints"]
    return points[value["next_index"]]["at"] if value["status"] == "active" and value["next_index"] < len(points) else deepcopy(_UNUSED)


def firing_key(definition, checkpoint):
    return "fire-" + canonical_digest({"definition": definition.reference, "condition": definition.value["condition_id"],
        "generation": definition.value["generation"], "checkpoint": checkpoint}, "matter.timer-firing.v1")


def _firing_ref(scope, key):
    return {"scope_id": scope, "namespace": NAMESPACE, "record_type": "receipt", "id": key}


class Scheduler:
    def __init__(self, storage, *, attention, controls, clock):
        if (not isinstance(attention, AttentionService) or not isinstance(controls, ControlService) or
                attention.storage is not storage or attention.controls is not controls or not callable(clock)):
            _fail()
        self.storage, self.scope_id, self.attention, self.controls, self.clock = storage, storage.scope_id, attention, controls, clock

    def _command(self, command):
        command = validate_command(command)
        if command["operation"] not in {"schedule_timer", "fire_timer"} or command["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        return command

    def _definition(self, value):
        definition = TimerDefinition(value)
        if definition.value["matter"]["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        return definition

    def _require_installed(self, definition):
        self.attention.assessments.profiles.resolve(definition.value["profile"])
        for reference in definition.value["rules"]:
            self.attention.assessments.rules.resolve(reference)

    def _capture(self, view, definition, token, now):
        return capture_dependencies(view, scope_id=self.scope_id, as_of=now,
            positive=definition.value["dependencies"], control_token=token, controls=self.controls)

    def _targets(self, command, view):
        return command_targets({**command, "expected_revisions": sorted([pin(item) for item in view.records.values()], key=canonical_bytes)})

    def _history_access(self, view, command):
        if self.attention.access is None:
            return
        firing = _lookup(view, _firing_ref(self.scope_id, command["body"]["firing_key"]))
        if firing is not None:
            details = firing["body"]["details"]
            if details != domain("timer-firing", details["value"]):
                _fail("E_EVIDENCE_INVALID")
            decision = view.get(details["value"]["attention_decision"])
            payload = decision["body"]["details"]
            if payload != domain("attention-decision", payload["value"]):
                _fail("E_EVIDENCE_INVALID")
            context, references = payload["value"]["request"]["access_context"], [payload["value"]["assessment"]]
        else:
            inner = command["body"]["attention_command"]
            if inner is None:
                _fail("E_AUTHORITY_REQUIRED")
            original = self.attention._request(inner["value"])
            context, references = original["access_context"], [original["assessment"]]
        self.attention.access.require_history(view, context, references=references)

    def _schedule(self, view, command, request, now):
        body = command["body"]
        wrapped = body["timer"]
        if wrapped != domain("timer-definition", wrapped["value"]):
            _fail()
        definition = self._definition(wrapped["value"])
        address = timer_ref(self.scope_id, definition)
        previous = _lookup(view, address)
        if (None if previous is None else pin(previous)) != body["previous"]:
            _fail("E_DEPENDENCY_STALE")
        old = None if previous is None else _value(previous, "timer-state")
        if body["action"] == "create" and old is not None or body["action"] != "create" and old is None:
            _fail("E_DEPENDENCY_STALE")
        token = request["token"]["value"]
        if request["token"] != domain("control-token", token) or token["actor"] != command["actor"] or entity_ref(token["authority"]) != command["authority"]:
            _fail("E_AUTHORITY_REQUIRED")
        targets = command_targets(command)
        self.controls._view(view, actor=command["actor"], authority=command["authority"], capability="write", targets=targets,
            now=now, audit=body["action"] == "cancel")
        self.controls._audit(view, command, targets)
        if body["action"] == "cancel":
            if old["definition"] != definition.value:
                _fail("E_DEPENDENCY_STALE")
            return definition, address, previous, None
        if old is not None and (definition.value["generation"] <= old["definition"]["generation"] or
                                definition.value["semantic_version"] == old["definition"]["semantic_version"]):
            _fail("E_POLICY_INVALID")
        self._require_installed(definition)
        self.controls.require_current(view, token, capability="assessment", targets=targets, as_of=now)
        assessment, lane = self.attention.assessments.read_current(view, definition.value["assessment"], definition.value["profile"], as_of=now)
        if any(assessment["body"].get(key) != definition.value[key] for key in ("matter", "profile", "purpose", "audience")):
            _fail("E_SCOPE_FORBIDDEN")
        graph = self.attention.assessments._current_value(lane)["publication"]["graph"]
        if {canonical_bytes(ref) for ref in definition.value["rules"]} != {canonical_bytes(node["rule"]) for node in graph["nodes"].values()}:
            _fail("E_EVIDENCE_INVALID")
        manifest = self._capture(view, definition, token, now)
        for item in view.watchers(_watch(self.scope_id)):
            _value(item, "timer-state")
        self.controls.require_current(view, token, capability="assessment", targets=self._targets(command, view), as_of=now)
        return definition, address, previous, manifest

    def prepare_schedule(self, command, *, token):
        command = self._command(command)
        if command["operation"] != "schedule_timer" or REQUEST_EXTENSION in command.get("extensions", {}):
            _fail()
        request = {"token": domain("control-token", token), "captured_at": fragment(self.clock(), "known_time")}
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            self._schedule(view, command, request, request["captured_at"])
            command["expected_revisions"] = sorted([pin(item) for item in view.records.values()], key=canonical_bytes)
        command.setdefault("extensions", {})[REQUEST_EXTENSION] = domain("timer-request", request)
        return command

    def _fire(self, view, command, request, now):
        row = view.exact(command["body"]["timer"])
        state = _value(row, "timer-state")
        definition = self._definition(state["definition"])
        if entity_ref(row) != timer_ref(self.scope_id, definition) or state["next_index"] > len(definition.value["checkpoints"]):
            _fail("E_EVIDENCE_INVALID")
        if request["token"] != state["token"]:
            _fail("E_AUTHORITY_REQUIRED")
        token = state["token"]["value"]
        if token["actor"] != command["actor"] or entity_ref(token["authority"]) != command["authority"]:
            _fail("E_AUTHORITY_REQUIRED")
        self.controls.policy.authorize(view, actor=command["actor"], authority=command["authority"],
            targets=token["targets"], capability="assessment")
        self.controls._audit(view, command, token["targets"])
        existing = _lookup(view, _firing_ref(self.scope_id, command["body"]["firing_key"]))
        if existing is not None:
            detail = existing["body"]["details"]
            if detail != domain("timer-firing", detail["value"]) or detail["value"]["definition"] != definition.reference:
                _fail("E_IDEMPOTENCY_CONFLICT")
            self._history_access(view, command)
            return row, state, definition, [], ("already_fired", existing)
        if state["status"] != "active":
            return row, state, definition, [], ("inert", state["status"])
        if compare_times(now, definition.value["expires_at"]) >= 0:
            return row, state, definition, [], ("inert", "expired")
        if -milliseconds(now, request["captured_at"]) > definition.value["max_clock_skew_ms"]:
            _fail("E_DEPENDENCY_STALE")
        try:
            self._require_installed(definition)
        except ContractError as error:
            if error.code != "E_POLICY_INVALID":
                raise
            return row, state, definition, [], ("inert", "original_policy_unavailable")
        try:
            self.controls.require_current(view, token, capability="assessment", targets=token["targets"], as_of=now)
            manifest = self._capture(view, definition, token, now)
            if state["manifest"] != domain("timer-manifest", manifest.value):
                _fail("E_DEPENDENCY_STALE")
        except StorageError as error:
            if error.code not in {"E_CANCELLED", "E_DEPENDENCY_STALE", "E_AUTHORITY_REQUIRED", "E_EVIDENCE_UNAVAILABLE"}:
                raise
            return row, state, definition, [], ("inert", "original_context_unavailable")
        due = [item for item in definition.value["checkpoints"][state["next_index"]:] if compare_times(item["at"], now) <= 0]
        if not due:
            return row, state, definition, [], ("not_due", "No declared checkpoint is due.")
        if command["body"]["firing_key"] != firing_key(definition, due[-1]):
            _fail("E_DEPENDENCY_STALE")
        wrapped = command["body"]["attention_command"]
        if wrapped is None:
            return row, state, definition, due, ("inert", "attention_preparation_unavailable")
        if wrapped != domain("operation-command", wrapped["value"]):
            _fail()
        inner = validate_command(wrapped["value"])
        attention_request = self.attention._request(inner)
        if (attention_request["action"] != "evaluate" or attention_request["token"] != state["token"] or
                inner["actor"] != command["actor"] or inner["authority"] != command["authority"] or
                attention_request["assessment"] != definition.value["assessment"] or
                any(inner["body"].get(key) != definition.value[key] for key in ("matter", "profile", "purpose", "audience"))):
            _fail("E_AUTHORITY_REQUIRED")
        # Checking the retained original command now captures all actual reads
        # for the outer atomic fire; the stage repeats it under the write lock.
        self.attention._inspect(view, inner, attention_request, now, original=True)
        self.controls.require_current(view, token, capability="assessment", targets=self._targets(command, view), as_of=now)
        return row, state, definition, due, None

    def prepare_fire(self, command):
        command = self._command(command)
        if command["operation"] != "fire_timer" or REQUEST_EXTENSION in command.get("extensions", {}):
            _fail()
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            row = view.exact(command["body"]["timer"])
            state = _value(row, "timer-state")
            request = {"token": state["token"], "captured_at": fragment(self.clock(), "known_time")}
            self._fire(view, command, request, request["captured_at"])
            inner = command["body"]["attention_command"]
            pins = [pin(item) for item in view.records.values()]
            if inner is not None:
                pins.extend(inner["value"]["expected_revisions"])
            by_id = {}
            for reference in pins:
                key = canonical_bytes(entity_ref(reference))
                if key in by_id and by_id[key] != reference:
                    _fail("E_DEPENDENCY_STALE")
                by_id[key] = reference
            command["expected_revisions"] = sorted(by_id.values(), key=canonical_bytes)
        command.setdefault("extensions", {})[REQUEST_EXTENSION] = domain("timer-request", request)
        return command

    def execute(self, command):
        command = self._command(command)
        wrapped = command.get("extensions", {}).get(REQUEST_EXTENSION)
        if type(wrapped) is not dict or wrapped != domain("timer-request", wrapped.get("value")):
            _fail()
        request = wrapped["value"]
        if request["token"] != domain("control-token", request["token"]["value"]):
            _fail("E_AUTHORITY_REQUIRED")
        def handler(tx):
            view, now = _Reads(tx, self.scope_id), fragment(self.clock(), "known_time")
            if command["operation"] == "schedule_timer":
                definition, address, previous, manifest = self._schedule(view, command, request, now)
                if command["body"]["action"] == "cancel":
                    old = _value(previous, "timer-state")
                    if old["status"] == "cancelled":
                        return tx.success("unchanged", {"timer": pin(previous), "next_check_at": _next(old)})
                    old.update(status="cancelled", updated_at=now, reason="Explicit host timer cancellation.")
                    stored = tx.put_projection(address, domain("timer-state", old))
                    return tx.success("cancelled", {"timer": pin(stored), "next_check_at": _next(old)})
                active = view.watchers(_watch(self.scope_id))
                if len(active) >= 512 and not any(entity_ref(item) == address for item in active):
                    _fail("E_BUDGET_EXHAUSTED")
                value = {"schema_version": "1.0", "definition": definition.value, "token": request["token"],
                    "manifest": domain("timer-manifest", manifest.value), "status": "active", "next_index": 0,
                    "created_at": now, "updated_at": now, "last_firing": None, "reason": "Explicit bounded temporal condition."}
                stored = tx.put_projection(address, domain("timer-state", value), watch_keys=(_watch(self.scope_id),))
                return tx.success("scheduled", {"timer": pin(stored), "next_check_at": _next(value)})
            row, state, definition, due, outcome = self._fire(view, command, request, now)
            if outcome is not None:
                kind, reason = outcome
                if kind == "already_fired":
                    detail = reason["body"]["details"]["value"]
                    return tx.success(kind, {"timer": pin(row), "firing": pin(reason), **{key: detail[key] for key in (
                        "scheduled_at", "actual_at", "coalesced_count", "attention_decision")}})
                if kind == "inert" and state["status"] == "active" and reason != "attention_preparation_unavailable":
                    state.update(status="expired" if reason == "expired" else "inert", updated_at=now, reason=reason)
                    row = tx.put_projection(entity_ref(row), domain("timer-state", state))
                return tx.success(kind, {"timer": pin(row), "reason": reason, "next_check_at": _next(state)})
            inner = command["body"]["attention_command"]["value"]
            staged = self.attention.stage(tx, inner)
            if staged["decision"] is None:
                _fail("E_EVIDENCE_INVALID")
            details = {"schema_version": "1.0", "timer": entity_ref(row), "definition": definition.reference,
                "firing_key": command["body"]["firing_key"], "condition_id": definition.value["condition_id"],
                "generation": definition.value["generation"], "scheduled_at": due[-1]["at"], "actual_at": now,
                "delay_ms": milliseconds(now, due[-1]["at"]), "coalesced_count": len(due),
                "attention_decision": staged["decision"], "token": state["token"]}
            firing = tx.insert({"schema_version": "1.0", "record_type": "receipt", **_firing_ref(self.scope_id, command["body"]["firing_key"]),
                "provenance": {"origin": "system", "producer": _ENGINE, "recorded_at": now, "parents": [staged["decision"]]},
                "body": {"stage": "operation", "operation_id": command["command_id"], "recorded_at": now,
                    "outcome": "matter:timer_fired", "evidence": [definition.value["assessment"], staged["decision"]],
                    "details": domain("timer-firing", details)}})
            state["next_index"] += len(due)
            state.update(status="completed" if state["next_index"] == len(definition.value["checkpoints"]) else "active",
                updated_at=now, last_firing=pin(firing), reason="Latest due checkpoint applied once.")
            stored = tx.put_projection(entity_ref(row), domain("timer-state", state),
                watch_keys=(_watch(self.scope_id),) if state["status"] == "active" else ())
            return tx.success("fired", {"timer": pin(stored), "firing": pin(firing), "scheduled_at": due[-1]["at"],
                "actual_at": now, "coalesced_count": len(due), "attention_decision": staged["decision"]})
        def audit(view):
            targets = [*command_targets(command), *request["token"]["value"]["targets"]]
            if command["operation"] == "fire_timer":
                # Snapshot replay supports the exact old timer pin after the
                # firing/cancel operation has revisioned its current projection.
                state = _value(view.get(command["body"]["timer"]), "timer-state")
                targets.extend(state["token"]["value"]["targets"])
            targets = sorted({canonical_bytes(entity_ref(item)): entity_ref(item) for item in targets}.values(), key=canonical_bytes)
            self.controls._audit(view, command, targets)
            if command["operation"] == "fire_timer" and self.attention.access is not None:
                self._history_access(view, command)
        return self.storage.execute(command, handler, replay_guard=audit, dependency_error_code="E_DEPENDENCY_STALE")

    def due(self):
        """Bounded trusted-host discovery; public source bodies need host READ APIs."""
        now = fragment(self.clock(), "known_time")
        with self.storage.snapshot() as snapshot:
            rows = snapshot.watchers(_watch(self.scope_id))
            result = []
            for row in rows:
                state = _value(row, "timer-state")
                definition = self._definition(state["definition"])
                due = [point for point in definition.value["checkpoints"][state["next_index"]:] if compare_times(point["at"], now) <= 0]
                if state["status"] == "active" and (due or compare_times(now, definition.value["expires_at"]) >= 0):
                    key = firing_key(definition, due[-1] if due else definition.value["checkpoints"][-1])
                    result.append({"timer": pin(row), "firing_key": key, "scheduled_at": _next(state)})
            return sorted(result, key=canonical_bytes)
