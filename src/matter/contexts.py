"""MAT-018 independent, versioned host contexts and explicit consumption.

Context definitions are data. Responsibility and treatment preferences neither
grant a capability nor alter evidence. Mutations use the existing trusted
control transaction; only their exact public context slot gets a control fence.
"""

from __future__ import annotations

from copy import deepcopy

from ._rule_values import FrozenValue, bounded, domain, fragment
from .canonical import canonical_bytes, canonical_digest
from .controls import ControlService, _Collector, _targets, command_targets, control_effect
from .identity_dependencies import _lookup, _value
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times


_ENGINE = {"namespace": "matter", "id": "host-contexts", "version": "1.0",
           "digest": canonical_digest({"implementation": "matter.contexts.v1"}, "matter.component.v1")}
_UNBOUNDED = {"state": "unknown", "reason": "not_applicable"}


def _fail(code="E_EVIDENCE_INVALID"):
    raise StorageError(code, "The scoped host context does not match its declared contract.")


def _namespace(value):
    name = fragment(value, "identifier")
    if name == "matter" or name.startswith("matter."):
        _fail("E_SCOPE_FORBIDDEN")
    return name


def _interval(value):
    start, end = value["effective_from"], value["effective_until"]
    if ((end["state"] == "known" and compare_times(end, start) <= 0)
            or (end["state"] == "unknown" and end["reason"] != "not_applicable")):
        _fail("E_POLICY_INVALID")


def _active(value, at):
    return compare_times(at, value["effective_from"]) >= 0 and (
        value["effective_until"]["state"] == "unknown" or compare_times(at, value["effective_until"]) < 0)


def _condition(reference, value, at):
    boundaries = [value["effective_from"]]
    if value["effective_until"]["state"] == "known":
        boundaries.append(value["effective_until"])
    future = [point for point in boundaries if compare_times(point, at) > 0]
    if not future:
        return []
    from .time import known_time_key
    return [{"condition": reference, "next_check_at": min(future, key=known_time_key),
             "expires_at": deepcopy(_UNBOUNDED)}]


class ContextDefinition(FrozenValue):
    """One immutable purpose/objective/audience/responsibility/preference version."""

    def __init__(self, value):
        body = domain("context-definition", value)["value"]
        _namespace(body["namespace"])
        fragment(body["semantic_version"], "identifier")
        _interval(body)
        if body["kind"] == "responsibility":
            scopes = {ref["scope_id"] for ref in body["applies_to"]}
            if scopes and scopes != {body["content"]["owner"]["scope_id"]}:
                _fail("E_SCOPE_FORBIDDEN")
        self._freeze(body)

    @property
    def reference(self):
        value = self.value
        return {"namespace": value["namespace"], "id": value["id"], "version": value["semantic_version"],
                "digest": canonical_digest(value, "matter.context-definition.v1")}


def context_ref(scope_id, definition):
    value = definition.value if isinstance(definition, ContextDefinition) else definition
    return {"scope_id": fragment(scope_id, "identifier"), "namespace": _namespace(value["namespace"]),
            "record_type": PROJECTION_TYPE, "id": "context-" + canonical_digest(
                {"id": value["id"]}, "matter.context-address.v1")}


def _version_ref(scope, definition):
    value = definition.value
    return {"scope_id": scope, "namespace": "matter.context_versions", "record_type": PROJECTION_TYPE,
            "id": canonical_digest({"namespace": value["namespace"], "id": value["id"],
                                    "version": value["semantic_version"]}, "matter.context-version-address.v1")}


def _scoped(scope, reference):
    ref = fragment(reference, "pinned_ref" if "revision" in reference or "digest" in reference else "entity_ref")
    if ref["scope_id"] != scope:
        _fail("E_SCOPE_FORBIDDEN")
    return ref


def _binding(view, scope, reference):
    ref = _scoped(scope, reference)
    pointer = view.get(ref)
    body = _value("context-current", pointer["value"])
    version = view.get(_scoped(scope, body["version"]))
    stored = _value("context-version", version["value"])
    definition = ContextDefinition(stored["definition"])
    if (body["scope_id"] != scope or stored["scope_id"] != scope
            or entity_ref(pointer) != context_ref(scope, definition)
            or entity_ref(version) != _version_ref(scope, definition)
            or body["reference"] != definition.reference):
        _fail()
    control = view.get(_scoped(scope, body["control"]))
    declared = _value("context-mutation", control["body"]["effect"]["value"]["payload"])
    if declared["definition"] != definition.value or control["body"]["scope"]["targets"] != [entity_ref(pointer)]:
        _fail()
    return {"context": pin(pointer), "version": pin(version), "reference": definition.reference,
            "definition": definition.value, "control": body["control"], "public_targets": _record_targets(control)}


def _record_targets(record):
    """Reuse the control contract's complete public-reference traversal."""
    control = deepcopy(record)
    control.pop("creation_receipt", None)
    return command_targets({"schema_version": "1.0", "operation": "record_control", "command_id": record["id"],
        "idempotency_key": record["id"], "scope_id": record["scope_id"], "actor": record["body"]["actor"],
        "authority": record["body"]["authority"], "expected_revisions": [], "body": {"control": control}})


def _refs(values):
    return sorted({canonical_bytes(entity_ref(ref)): entity_ref(ref) for ref in values}.values(), key=canonical_bytes)


def _context_targets(binding):
    return [entity_ref(binding["context"]), *binding["definition"]["applies_to"], *binding["public_targets"]]


class ContextSelection(FrozenValue):
    """Only the explicitly selected components, their pins and interval guards."""

    def __init__(self, components, at):
        conditions = [condition for item in components for condition in _condition(item["reference"], item["definition"], at)]
        self._freeze({"at": at, "components": [{**item, "active": _active(item["definition"], at)} for item in components],
                      "dependencies": [ref for item in components for ref in (item["context"], item["version"])],
                      "time_conditions": conditions})

    @property
    def dependencies(self):
        return self.value["dependencies"]

    @property
    def time_conditions(self):
        return self.value["time_conditions"]


def _control_command(controls, *, payload, schema, target, command_id, idempotency_key, actor, authority, kind):
    now = controls._time()
    scope = controls.scope_id
    actor = fragment(actor, "actor_ref")
    authority = fragment(entity_ref(authority), "receipt_ref")
    if actor["scope_id"] != scope or authority["scope_id"] != scope:
        _fail("E_SCOPE_FORBIDDEN")
    record = {"schema_version": "1.0", "record_type": "control", "scope_id": scope,
        "namespace": target["namespace"], "id": "context-control-" + fragment(command_id, "identifier"),
        "provenance": {"origin": "host", "producer": _ENGINE, "recorded_at": now, "parents": []},
        "body": {"control_kind": kind, "actor": actor, "authority": authority,
            "scope": {"scope_id": scope, "targets": [target]}, "control_epoch": 0,
            "effective_from": now, "effective_until": deepcopy(_UNBOUNDED),
            "effect": control_effect("disposition", "Explicit host context decision.", payload=domain(schema, payload))}}
    return {"schema_version": "1.0", "operation": "record_control", "command_id": command_id,
            "idempotency_key": fragment(idempotency_key, "identifier"), "scope_id": scope,
            "actor": actor, "authority": authority, "expected_revisions": [], "body": {"control": record}}


class _MutationService:
    """Existing host control transaction plus exact domain projection writes."""

    def __init__(self, storage, *, controls):
        if not isinstance(controls, ControlService) or storage is not controls._storage:
            _fail("E_POLICY_INVALID")
        self.storage, self.controls, self.scope_id = storage, controls, storage.scope_id

    def _payload(self, command):
        command = self.controls._command(command)
        if command["body"]["control"]["provenance"]["origin"] != "host":
            _fail("E_AUTHORITY_REQUIRED")
        effect = command["body"]["control"]["body"]["effect"]["value"]
        if effect["action"] != "disposition" or "payload" not in effect:
            _fail("E_SCHEMA_INVALID")
        payload = _value(self.mutation_schema, effect["payload"])
        return command, payload

    def _authorize(self, view, command, targets):
        targets = _targets(self.scope_id, _refs([*targets, *command_targets(command)]))
        self.controls.policy.authorize(view, actor=command["actor"], authority=command["authority"], targets=targets,
            control_kind=command["body"]["control"]["body"]["control_kind"])
        self.controls._audit(view, command, targets)

    def _prepare(self, command):
        command, payload = self._payload(command)
        pins = {}
        def include(reference):
            pins[canonical_bytes(entity_ref(reference))] = reference
        with self.storage.snapshot() as snapshot:
            view = _Collector(snapshot, include)
            state = self._state(view, command, payload, preparing=True)
            self._authorize(view, command, state["targets"])
            if state["old"] is not None:
                command["body"]["control"]["supersedes"] = [state["old_control"]]
        command["expected_revisions"] = sorted(pins.values(), key=canonical_bytes)
        return self.controls.prepare(command)

    def commit(self, command):
        command, payload = self._payload(command)
        def replay(view):
            self._authorize(view, command, self._read_targets(view, payload))
        return self.storage.execute(command, self._commit, replay_guard=replay)

    def _commit(self, tx):
        command, payload = self._payload(tx.command)
        state = self._state(tx, command, payload, preparing=False)
        self._authorize(tx, command, state["targets"])
        result = self.controls._apply(tx)
        self._write(tx, payload, state, result["body"]["control"])
        return result

    def _prior(self, view, command, payload, address, schema, *, preparing):
        previous = payload["previous"]
        old = _lookup(view, address)
        if (old is None) != (previous is None) or old is not None and pin(old) != previous:
            _fail("E_DEPENDENCY_STALE")
        control = None if old is None else _value(schema, old["value"])["control"]
        if not preparing and command["body"]["control"].get("supersedes", []) != ([] if old is None else [control]):
            _fail("E_AUTHORITY_REQUIRED")
        return old, control

    def _audit_read(self, view, token, targets):
        return self.controls.require_current(view, token, capability="read", targets=_refs(targets))


class ContextService(_MutationService):
    """Persist exact context versions; read or capture selected public slots."""

    mutation_schema = "context-mutation"

    def prepare(self, definition, *, command_id, idempotency_key, actor, authority, previous=None):
        if not isinstance(definition, ContextDefinition):
            _fail("E_POLICY_INVALID")
        target = context_ref(self.scope_id, definition)
        return self._prepare(_control_command(self.controls,
            payload={"definition": definition.value, "previous": previous}, schema=self.mutation_schema,
            target=target, command_id=command_id, idempotency_key=idempotency_key, actor=actor,
            authority=authority, kind="preference" if definition.value["kind"] == "preference" else "decision"))

    def _read_targets(self, view, payload):
        definition = ContextDefinition(payload["definition"])
        targets = [context_ref(self.scope_id, definition), *definition.value["applies_to"]]
        if payload["previous"] is not None:
            targets.extend(_context_targets(_binding(view, self.scope_id, payload["previous"])))
        return targets

    def _state(self, view, command, payload, *, preparing):
        definition = ContextDefinition(payload["definition"])
        address = context_ref(self.scope_id, definition)
        if definition.value["kind"] == "responsibility" and definition.value["content"]["owner"]["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        if command["body"]["control"]["body"]["scope"]["targets"] != [address]:
            _fail("E_SCOPE_FORBIDDEN")
        expected_kind = "preference" if definition.value["kind"] == "preference" else "decision"
        if command["body"]["control"]["body"]["control_kind"] != expected_kind:
            _fail("E_SCHEMA_INVALID")
        old, old_control = self._prior(view, command, payload, address, "context-current", preparing=preparing)
        if old is not None and _binding(view, self.scope_id, pin(old))["definition"]["kind"] != definition.value["kind"]:
            _fail("E_POLICY_INVALID")
        for reference in definition.value["applies_to"]:
            view.get(_scoped(self.scope_id, reference))
        version = _lookup(view, _version_ref(self.scope_id, definition))
        if version is not None and _value("context-version", version["value"])["definition"] != definition.value:
            _fail("E_SOURCE_IDENTITY_CONFLICT")
        return {"old": old, "old_control": old_control, "version": version,
                "targets": self._read_targets(view, payload)}

    def _write(self, tx, payload, state, control):
        definition = ContextDefinition(payload["definition"])
        version = state["version"]
        if version is None:
            version = tx.put_projection(_version_ref(self.scope_id, definition), domain("context-version",
                {"scope_id": self.scope_id, "definition": definition.value, "control": control}))
        tx.put_projection(context_ref(self.scope_id, definition), domain("context-current",
            {"scope_id": self.scope_id, "reference": definition.reference, "version": pin(version),
             "control": control}))

    def read(self, token, reference, *, at=None):
        with self.storage.snapshot() as view:
            binding = _binding(view, self.scope_id, reference)
            self._audit_read(view, token, _context_targets(binding))
            return ContextSelection([binding], fragment(at or self.controls._time(), "known_time"))

    def capture(self, token, references):
        with self.storage.snapshot() as view:
            selected = []
            for reference in bounded(references, 128):
                binding = _binding(view, self.scope_id, reference)
                current = view.get(entity_ref(binding["context"]))
                if pin(current) != binding["context"]:
                    _fail("E_DEPENDENCY_STALE")
                selected.append(binding)
            if len({canonical_bytes(item["context"]) for item in selected}) != len(selected):
                _fail("E_SCHEMA_INVALID")
            self._audit_read(view, token, [ref for item in selected for ref in _context_targets(item)])
            return ContextSelection(selected, self.controls._time())
