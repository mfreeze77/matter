"""Immutable host authority ceilings; observed text cannot construct a grant.

The host authenticates the caller and admits exact authority receipts before
creating this object. This local API is not an identity provider or a sandbox
against Python code that already possesses the trusted storage handle.
"""

from copy import deepcopy
import json

from .association_policy import _values
from .canonical import canonical_bytes, canonical_digest
from .contracts import validate_record
from .storage import StorageError, entity_ref, snapshot_digest
from .storage.base import _validate_fragment


CAPABILITIES = frozenset({"association", "merge", "correction", "transition", "read", "delivery", "assessment", "write"})
CONTROL_KINDS = frozenset({"instruction", "correction", "cancellation", "task_change", "permission",
                          "deferral", "acknowledgement", "rejection", "preference", "decision", "protected_separation"})


class AuthorityPolicy:
    """Static actor/receipt admission and a maximum set of host capabilities.

    Target restrictions are exact references. ``targets=None`` grants scope
    coverage; an explicit list permits only those targets and never permits a
    scope-wide control. Controls can narrow but cannot expand capabilities.
    Association, merge and lifecycle policies remain separate mandatory gates.
    """

    __slots__ = ("_encoded",)

    def __init__(self, scope_id, *, actors, authorities, capabilities, control_kinds=(), targets=None):
        scope = _validate_fragment(scope_id, "identifier")
        capabilities = self._names(capabilities, CAPABILITIES)
        kinds = self._names(control_kinds, CONTROL_KINDS)
        selected = None if targets is None else _values(targets, "entity_ref", scope_id=scope)
        definition = {"scope_id": scope, "actors": _values(actors, "actor_ref", scope_id=scope),
                      "authorities": _values(authorities, "receipt_dependency", scope_id=scope),
                      "capabilities": capabilities, "control_kinds": kinds, "targets": selected}
        object.__setattr__(self, "_encoded", canonical_bytes(definition))

    @staticmethod
    def _names(values, allowed):
        if isinstance(values, (str, bytes, dict)):
            raise StorageError("E_POLICY_INVALID")
        try:
            items = list(values)
            if any(type(value) is not str or value not in allowed for value in items) or len(set(items)) != len(items):
                raise ValueError
        except (TypeError, ValueError):
            raise StorageError("E_POLICY_INVALID") from None
        return sorted(items)

    def __setattr__(self, name, value):
        raise AttributeError("AuthorityPolicy is immutable.")

    @property
    def definition(self):
        return json.loads(self._encoded)

    @property
    def scope_id(self):
        return self.definition["scope_id"]

    @property
    def reference(self):
        return {"namespace": "matter", "id": "host-authority-policy", "version": "1.0",
                "digest": canonical_digest(self.definition, "matter.authority-policy.v1")}

    def authorize(self, view, *, actor, authority, targets, capability=None, control_kind=None):
        if type(targets) not in (list, tuple):
            raise StorageError("E_SCHEMA_INVALID", "Targets must be a detached list or tuple.")
        targets = [_validate_fragment(target, "entity_ref") for target in targets]
        actor = _validate_fragment(actor, "actor_ref")
        reference = entity_ref(authority)
        definition = self.definition
        if actor["scope_id"] != self.scope_id or reference["scope_id"] != self.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        if actor not in definition["actors"]:
            raise StorageError("E_AUTHORITY_REQUIRED", "The host has not admitted this actor.")
        admitted = next((pin for pin in definition["authorities"] if entity_ref(pin) == reference), None)
        if admitted is None or ("digest" in authority and authority != admitted):
            raise StorageError("E_AUTHORITY_REQUIRED", "An exact admitted authority receipt is required.")
        stored = validate_record(view.get(admitted))
        if (stored["record_type"] != "receipt" or stored["provenance"]["origin"] != "host"
                or stored["body"]["stage"] != "authority" or snapshot_digest(stored) != admitted["digest"]):
            raise StorageError("E_AUTHORITY_REQUIRED", "An actual host-origin authority receipt is required.")
        for target in targets:
            _validate_fragment(target, "entity_ref")
            if target["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")
        if definition["targets"] is not None and (not targets or any(t not in definition["targets"] for t in targets)):
            raise StorageError("E_SCOPE_FORBIDDEN", "The requested targets exceed the static host scope.")
        if capability is not None and capability not in definition["capabilities"]:
            raise StorageError("E_AUTHORITY_REQUIRED", "The operation exceeds the static capability ceiling.")
        if control_kind is not None and control_kind not in definition["control_kinds"]:
            raise StorageError("E_AUTHORITY_REQUIRED", "The host has not admitted this control kind.")
        return deepcopy(admitted)
