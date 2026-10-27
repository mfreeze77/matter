"""MAT-020 atomic, separate resource/attention allocation ledgers.

Reservations are unused holds. Commit charges the full conservative allocation
BEFORE work; committed or uncertain work is never automatically refunded.
Actual invocation/transport evidence remains separate from allocated capacity.
"""

from copy import deepcopy
from datetime import date

from ._rule_values import FrozenValue, descriptor, domain, fragment
from .assessments import _Tracked
from .canonical import canonical_bytes, canonical_digest
from .contracts import validate_command
from .controls import ControlService, command_targets
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times, contains, known_time_key


NAMESPACE = "matter.budgets"
REQUEST_EXTENSION = "matter:budget-request"
_RESOURCE = {"calls", "input_bytes", "output_bytes", "elapsed_ms", "candidates", "retries", "cost_units"}
_ATTENTION = {"deliveries", "interruption_units"}
_UNUSED = {"state": "unknown", "reason": "not_applicable"}


def _fail(code="E_POLICY_INVALID"):
    raise StorageError(code, "The budget declaration or original allocation context is invalid.")


def milliseconds(later, earlier):
    """Floor a known UTC difference without floats or subsecond precision loss."""
    def nanos(value):
        main, fraction = known_time_key(value)
        return ((date.fromisoformat(main[:10]).toordinal() * 86400 + int(main[11:13]) * 3600 +
                 int(main[14:16]) * 60 + int(main[17:19])) * 1000000000 + int(fraction))
    return (nanos(later) - nanos(earlier)) // 1000000


def _lookup(view, reference):
    try:
        return view.get(reference)
    except StorageError as error:
        if error.code != "E_NOT_FOUND":
            raise
        return None


class _Reads(_Tracked):
    def _remember(self, value):
        result = super()._remember(value)
        if len(self.records) > 4096 or sum(len(canonical_bytes(item)) for item in self.records.values()) > 8388608:
            _fail("E_BUDGET_EXHAUSTED")
        return result

    def exact(self, reference):
        value = self.get(entity_ref(reference))
        if pin(value) != reference:
            _fail("E_DEPENDENCY_STALE")
        return value


def _value(record, name):
    wrapped = record["value"]
    if wrapped != domain(name, wrapped["value"]):
        _fail("E_EVIDENCE_INVALID")
    return wrapped["value"]


class BudgetDefinition(FrozenValue):
    """Host-installed exact units, limits and one explicit fixed window."""
    def __init__(self, value):
        value = domain("budget-policy", value)["value"]
        keys = set(value["limits"])
        permitted = _RESOURCE if value["kind"] == "resource" else _ATTENTION
        if (not keys <= permitted or set(value["units"]) != keys or not any(value["limits"].values()) or
                value["window"]["bounds"] != "closed_open" or
                compare_times(value["window"]["start"], value["window"]["end"]) != -1):
            _fail()
        fragment(value["window"]["start"], "known_time")
        fragment(value["window"]["end"], "known_time")
        self._freeze(value)

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["semantic_version"], value, "matter.budget-policy.v1")


def budget_ref(scope_id, definition):
    value = definition.value
    # A version change within the same account/window cannot mint fresh quota.
    identity = {"namespace": value["namespace"], "id": value["id"], "kind": value["kind"], "window": value["window"]}
    return {"scope_id": fragment(scope_id, "identifier"), "namespace": NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "account-" + canonical_digest(identity, "matter.budget-account.v1")}


def reservation_ref(account, identity):
    return {**entity_ref(account), "id": "allocation-" + canonical_digest({"account": entity_ref(account),
        "reservation_id": fragment(identity, "identifier")}, "matter.budget-allocation.v1")}


def _watch(account):
    return "budget-held-" + canonical_digest(entity_ref(account), "matter.budget-held.v1")


class BudgetEnvelope(FrozenValue):
    @property
    def remaining_budget(self):
        return self.value["remaining_budget"]


class BudgetService:
    def __init__(self, storage, *, definitions, controls, clock):
        definitions = tuple(definitions)
        if (not isinstance(controls, ControlService) or controls.scope_id != storage.scope_id or not callable(clock) or
                not definitions or len(definitions) > 128 or any(not isinstance(item, BudgetDefinition) for item in definitions)):
            _fail()
        if len({canonical_bytes(item.reference) for item in definitions}) != len(definitions):
            _fail()
        self.storage, self.scope_id, self.controls, self.clock = storage, storage.scope_id, controls, clock
        self.definitions = definitions

    def _definition(self, reference):
        for definition in self.definitions:
            if definition.reference == reference:
                return definition
        _fail()

    def _command(self, command):
        command = validate_command(command)
        if command["operation"] not in {"reserve_budget", "settle_budget"} or command["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        return command

    def _load(self, view, definition):
        address = budget_ref(self.scope_id, definition)
        stored = _lookup(view, address)
        zero = {key: 0 for key in definition.value["limits"]}
        value = {"schema_version": "1.0", "budget": definition.reference, "charged": zero.copy(), "held": zero.copy()} if stored is None else _value(stored, "budget-account")
        if value["budget"] != definition.reference or set(value["charged"]) != set(zero) or set(value["held"]) != set(zero):
            _fail()
        holders = view.watchers(_watch(address))
        if len(holders) > 512:
            _fail("E_BUDGET_EXHAUSTED")
        total = zero.copy()
        for row in holders:
            reservation = _value(row, "budget-reservation")
            if (reservation["account"] != address or reservation["budget"] != definition.reference or
                    reservation["status"] != "held" or row["watch_keys"] != [_watch(address)] or set(reservation["amounts"]) != set(zero)):
                _fail("E_STORAGE_UNAVAILABLE")
            for key, amount in reservation["amounts"].items():
                total[key] += amount
        if total != value["held"] or any(value["charged"][key] + total[key] > limit for key, limit in definition.value["limits"].items()):
            _fail("E_STORAGE_UNAVAILABLE")
        return address, value, holders

    def _available(self, definition, account, holders, now):
        held = {key: 0 for key in account["held"]}
        next_times = []
        for row in holders:
            value = _value(row, "budget-reservation")
            if compare_times(now, value["expires_at"]) == -1:
                next_times.append(value["expires_at"])
                for key, amount in value["amounts"].items():
                    held[key] += amount
        remaining = {key: limit - account["charged"][key] - held[key] for key, limit in definition.value["limits"].items()}
        next_at = min(next_times, key=known_time_key) if next_times else deepcopy(_UNUSED)
        if compare_times(now, definition.value["window"]["start"]) == -1:
            next_at = definition.value["window"]["start"]
        return remaining, next_at

    def _inspect(self, view, command, request, now):
        token = request["token"]["value"]
        if request["token"] != domain("control-token", token) or token["actor"] != command["actor"] or entity_ref(token["authority"]) != command["authority"]:
            _fail("E_AUTHORITY_REQUIRED")
        body = command["body"]
        reservation = None if command["operation"] == "reserve_budget" else view.exact(body["reservation"])
        allocation = None if reservation is None else _value(reservation, "budget-reservation")
        definition = self._definition(body["budget"] if allocation is None else allocation["budget"])
        capability = "assessment" if definition.value["kind"] == "resource" else "delivery"
        targets = body["targets"] if allocation is None else allocation["targets"]
        self.controls._view(view, actor=command["actor"], authority=command["authority"], capability=capability,
            targets=targets, now=now, audit=command["operation"] == "settle_budget")
        self.controls._audit(view, command, targets)
        if allocation is None:
            self.controls.require_current(view, token, capability=capability, targets=targets, as_of=now)
            if set(body["amounts"]) != set(definition.value["limits"]) or not any(body["amounts"].values()):
                _fail()
            if compare_times(body["expires_at"], definition.value["window"]["end"]) == 1:
                _fail()
        elif body["action"] == "commit" and allocation["status"] == "held" and compare_times(now, allocation["expires_at"]) == -1:
            if allocation["token"] != request["token"]:
                _fail("E_AUTHORITY_REQUIRED")
            self.controls.require_current(view, token, capability=capability, targets=targets, as_of=now)
        address, account, holders = self._load(view, definition)
        return definition, address, account, holders, reservation, allocation

    def prepare(self, command, *, token):
        command = self._command(command)
        if REQUEST_EXTENSION in command.get("extensions", {}):
            _fail()
        request = {"token": domain("control-token", token), "captured_at": fragment(self.clock(), "known_time")}
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            self._inspect(view, command, request, request["captured_at"])
            if command["operation"] == "reserve_budget":
                definition = self._definition(command["body"]["budget"])
                _lookup(view, reservation_ref(budget_ref(self.scope_id, definition), command["body"]["reservation_id"]))
            command["expected_revisions"] = sorted([pin(item) for item in view.records.values()], key=canonical_bytes)
        command.setdefault("extensions", {})[REQUEST_EXTENSION] = domain("budget-request", request)
        return validate_command(command)

    def execute(self, command):
        command = self._command(command)
        wrapped = command.get("extensions", {}).get(REQUEST_EXTENSION)
        if type(wrapped) is not dict or wrapped != domain("budget-request", wrapped.get("value")):
            _fail()
        request = wrapped["value"]
        def handler(tx):
            now = fragment(self.clock(), "known_time")
            if compare_times(now, request["captured_at"]) == -1:
                _fail("E_DEPENDENCY_STALE")
            view = _Reads(tx, self.scope_id)
            definition, address, account, holders, row, allocation = self._inspect(view, command, request, now)
            remaining, next_at = self._available(definition, account, holders, now)
            if command["operation"] == "reserve_budget":
                body = command["body"]
                target = reservation_ref(address, body["reservation_id"])
                if _lookup(view, target) is not None:
                    _fail("E_IDEMPOTENCY_CONFLICT")
                if (contains(definition.value["window"], now) is not True or compare_times(now, body["expires_at"]) != -1 or
                        any(amount > remaining[key] for key, amount in body["amounts"].items())):
                    return tx.success("budget_limited", {"reason": "Shared allocation capacity or its declared time window is unavailable.",
                        "remaining": remaining, "next_eligible_at": next_at})
                if len(holders) >= 512 and all(compare_times(now, _value(item, "budget-reservation")["expires_at"]) == -1 for item in holders):
                    _fail("E_BUDGET_EXHAUSTED")
                # Expire only unused holds, in this same writer transaction.
                for old in holders:
                    value = _value(old, "budget-reservation")
                    if compare_times(now, value["expires_at"]) >= 0:
                        for key, amount in value["amounts"].items():
                            account["held"][key] -= amount
                        value.update(status="expired", settled_at=now)
                        tx.put_projection(entity_ref(old), domain("budget-reservation", value))
                for key, amount in body["amounts"].items():
                    account["held"][key] += amount
                    remaining[key] -= amount
                value = {"schema_version": "1.0", "budget": definition.reference, "account": address,
                    "reservation_id": body["reservation_id"], "amounts": body["amounts"], "targets": body["targets"],
                    "token": request["token"], "created_at": now, "expires_at": body["expires_at"], "status": "held", "settled_at": None}
                stored = tx.put_projection(target, domain("budget-reservation", value), watch_keys=(_watch(address),))
                tx.put_projection(address, domain("budget-account", account))
                return tx.success("reserved", {"reservation": pin(stored), "remaining": remaining,
                    "next_eligible_at": body["expires_at"] if next_at["state"] == "unknown" or compare_times(body["expires_at"], next_at) < 0 else next_at})
            if allocation["status"] != "held":
                return tx.success("unchanged", {"reservation": pin(row), "reason": "Finalized allocations cannot be released or renewed.",
                    "remaining": remaining, "next_eligible_at": next_at})
            expired = compare_times(now, allocation["expires_at"]) >= 0
            status = "expired" if expired else "committed" if command["body"]["action"] == "commit" else "released"
            for key, amount in allocation["amounts"].items():
                account["held"][key] -= amount
                if status == "committed":
                    account["charged"][key] += amount
            allocation.update(status=status, settled_at=now)
            stored = tx.put_projection(entity_ref(row), domain("budget-reservation", allocation))
            tx.put_projection(address, domain("budget-account", account))
            remaining, next_at = self._available(definition, account, [item for item in holders if entity_ref(item) != entity_ref(row)], now)
            return tx.success(status, {"reservation": pin(stored), "reason": "Conservative allocation " + status + ".",
                "remaining": remaining, "next_eligible_at": next_at})
        def audit(view):
            self.controls._audit(view, command, command_targets(command))
        return self.storage.execute(command, handler, replay_guard=audit, dependency_error_code="E_DEPENDENCY_STALE")

    def require_committed(self, view, reference, *, as_of=None):
        now = fragment(self.clock(), "known_time")
        if as_of is not None and compare_times(fragment(as_of, "known_time"), now) == 1:
            _fail()
        view = _Reads(view, self.scope_id)
        stored = view.exact(fragment(reference, "projection_dependency"))
        value = _value(stored, "budget-reservation")
        definition = self._definition(value["budget"])
        if value["status"] != "committed" or compare_times(now, value["expires_at"]) != -1 or contains(definition.value["window"], now) is not True:
            _fail("E_BUDGET_EXHAUSTED")
        token = value["token"]["value"]
        if value["token"] != domain("control-token", token):
            _fail()
        self.controls.require_current(view, token, capability="assessment" if definition.value["kind"] == "resource" else "delivery",
            targets=value["targets"], as_of=now)
        self.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])}, value["targets"])
        return value

    def resource_envelope(self, view, reference, *, ceiling, as_of=None):
        """Conservative GraphExecutor envelope; recheck require_committed before work."""
        now = fragment(self.clock(), "known_time")
        if as_of is not None and compare_times(fragment(as_of, "known_time"), now) == 1:
            _fail()
        value = self.require_committed(view, reference, as_of=now)
        definition = self._definition(value["budget"])
        if definition.value["kind"] != "resource":
            _fail()
        if set(ceiling) != {"max_calls", "max_input_bytes", "max_output_bytes", "max_elapsed_ms", "max_evidence"}:
            _fail()
        if any(type(amount) is not int or amount < 0 for amount in ceiling.values()):
            _fail()
        for amount in ceiling.values():
            fragment(amount, "counter")
        mapping = {"max_calls": "calls", "max_input_bytes": "input_bytes", "max_output_bytes": "output_bytes", "max_elapsed_ms": "elapsed_ms"}
        if not set(mapping.values()) <= set(value["amounts"]):
            _fail()
        remaining = {key: min(ceiling[key], value["amounts"][dimension]) for key, dimension in mapping.items()}
        finished = fragment(self.clock(), "known_time")
        if compare_times(finished, value["expires_at"]) != -1:
            _fail("E_BUDGET_EXHAUSTED")
        remaining["max_elapsed_ms"] = min(remaining["max_elapsed_ms"], max(0, milliseconds(value["expires_at"], finished)))
        remaining["max_evidence"] = ceiling["max_evidence"]
        envelope = BudgetEnvelope()
        envelope._freeze({"schema_version": "1.0", "reservation": reference, "budget": value["budget"],
            "remaining_budget": remaining, "deadline": value["expires_at"], "original_token": value["token"]})
        return envelope
