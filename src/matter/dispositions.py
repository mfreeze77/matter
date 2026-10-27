"""MAT-018 exact audience/purpose/subject dispositions on the host control path.

Acknowledgement records receipt, not agreement or repair. Rejection names one
exact proposal snapshot. No disposition changes evidence or domain lifecycle.
"""

from __future__ import annotations

from ._rule_values import FrozenValue, domain, fragment
from .canonical import canonical_digest
from .contexts import (
    _MutationService, _active, _binding, _condition, _context_targets, _control_command,
    _fail, _interval, _namespace, _record_targets, _scoped,
)
from .identity_dependencies import _value
from .storage import PROJECTION_TYPE, entity_ref, pin


class DispositionDefinition(FrozenValue):
    """A host decision about one exact subject and two exact context versions."""

    def __init__(self, value):
        body = domain("disposition-definition", value)["value"]
        _namespace(body["namespace"])
        _interval(body)
        if (body["kind"] == "deferral" and body["effective_until"]["state"] != "known"
                or (body["kind"] == "decision") != (body["decision"] is not None)):
            _fail("E_POLICY_INVALID")
        if body["kind"] == "rejection" and body["subject"]["record_type"] not in {"association_proposal", PROJECTION_TYPE}:
            _fail("E_POLICY_INVALID")
        scope = body["matter"]["scope_id"]
        for reference in (body["subject"], body["purpose"]["context"], body["audience"]["context"]):
            _scoped(scope, reference)
        self._freeze(body)

    @property
    def reference(self):
        body = self.value
        return {"namespace": body["namespace"], "id": "disposition-" + body["kind"], "version": "1.0",
                "digest": canonical_digest(body, "matter.disposition-definition.v1")}


def disposition_ref(definition):
    body = definition.value if isinstance(definition, DispositionDefinition) else DispositionDefinition(definition).value
    key = {name: body[name] for name in ("kind", "matter", "purpose", "audience", "subject")}
    return {"scope_id": body["matter"]["scope_id"], "namespace": body["namespace"], "record_type": PROJECTION_TYPE,
            "id": "disposition-" + canonical_digest(key, "matter.disposition-scope.v1")}


class DispositionSelection(FrozenValue):
    def __init__(self, record, definition, at):
        self._freeze({"disposition": pin(record), "definition": definition.value,
                      "reference": definition.reference,
                      "active": definition.value["status"] == "active" and _active(definition.value, at), "at": at,
                      "dependencies": [pin(record)],
                      "time_conditions": _condition(definition.reference, definition.value, at)})

    @property
    def dependencies(self):
        return self.value["dependencies"]

    @property
    def time_conditions(self):
        return self.value["time_conditions"]


class DispositionService(_MutationService):
    mutation_schema = "disposition-mutation"

    def prepare(self, definition, *, command_id, idempotency_key, actor, authority, previous=None):
        if not isinstance(definition, DispositionDefinition) or definition.value["matter"]["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        return self._prepare(_control_command(self.controls,
            payload={"definition": definition.value, "previous": previous}, schema=self.mutation_schema,
            target=disposition_ref(definition), command_id=command_id, idempotency_key=idempotency_key,
            actor=actor, authority=authority, kind=definition.value["kind"]))

    def _read_targets(self, view, payload):
        definition = DispositionDefinition(payload["definition"])
        body = definition.value
        targets = [disposition_ref(definition), body["matter"], entity_ref(body["subject"])]
        for name in ("purpose", "audience"):
            binding = _binding(view, self.scope_id, body[name]["context"])
            if binding["reference"] != body[name]["reference"] or binding["definition"]["kind"] != name:
                _fail()
            targets.extend(_context_targets(binding))
        return targets

    def _state(self, view, command, payload, *, preparing):
        definition = DispositionDefinition(payload["definition"])
        body = definition.value
        if body["matter"]["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        control = command["body"]["control"]["body"]
        if control["scope"]["targets"] != [disposition_ref(definition)] or control["control_kind"] != body["kind"]:
            _fail("E_SCOPE_FORBIDDEN")
        now = self.controls._time()
        if not _active(body, now):
            _fail("E_POLICY_INVALID")
        old, old_control = self._prior(view, command, payload, disposition_ref(definition), "disposition-current", preparing=preparing)
        if body["status"] == "withdrawn" and old is None:
            _fail("E_POLICY_INVALID")
        for reference in (body["matter"], body["subject"]):
            view.get(_scoped(self.scope_id, reference))
        for name in ("purpose", "audience"):
            binding = _binding(view, self.scope_id, body[name]["context"])
            if pin(view.get(entity_ref(binding["context"]))) != binding["context"]:
                _fail("E_DEPENDENCY_STALE")
            if not _active(binding["definition"], now):
                _fail("E_POLICY_INVALID")
        return {"old": old, "old_control": old_control, "targets": self._read_targets(view, payload)}

    def _write(self, tx, payload, state, control):
        definition = DispositionDefinition(payload["definition"])
        tx.put_projection(disposition_ref(definition), domain("disposition-current",
            {"scope_id": self.scope_id, "definition": definition.value, "control": control}))

    def read(self, token, reference, *, at=None):
        with self.storage.snapshot() as view:
            record = view.get(_scoped(self.scope_id, reference))
            body = _value("disposition-current", record["value"])
            definition = DispositionDefinition(body["definition"])
            if body["scope_id"] != self.scope_id or entity_ref(record) != disposition_ref(definition):
                _fail()
            control = view.get(body["control"])
            retained = _value(self.mutation_schema, control["body"]["effect"]["value"]["payload"])
            if retained["definition"] != definition.value or control["body"]["scope"]["targets"] != [entity_ref(record)]:
                _fail()
            self._audit_read(view, token, [*self._read_targets(view, retained), *_record_targets(control)])
            return DispositionSelection(record, definition, fragment(at or self.controls._time(), "known_time"))
