"""Host-injected association capability, separate from evaluator declarations.

This is a local, scope-bound allowlist, not an identity provider or the general
control-epoch service. The host admits actual authority receipts before it
constructs this policy; observation and model payloads cannot configure it.
"""

from __future__ import annotations

from copy import deepcopy
import json

from .canonical import canonical_bytes, canonical_digest
from .contracts import validate_record
from .storage import StorageError, entity_ref, snapshot_digest
from .storage.base import _validate_fragment


def _values(values, fragment, *, scope_id=None):
    if isinstance(values, (str, bytes, dict)):
        raise StorageError("E_POLICY_INVALID")
    try:
        result = [_validate_fragment(item, fragment) for item in values]
    except (TypeError, ValueError):
        raise StorageError("E_POLICY_INVALID") from None
    encoded = [canonical_bytes(item) for item in result]
    if not result or len(set(encoded)) != len(encoded):
        raise StorageError("E_POLICY_INVALID", "Policy lists must be nonempty and unique.")
    if scope_id is not None and any(item["scope_id"] != scope_id for item in result):
        raise StorageError("E_SCOPE_FORBIDDEN")
    return sorted(result, key=canonical_bytes)


class AssociationPolicy:
    """An immutable host capability for one actor/authority scope.

    Allowed semantic acceptance is explicit host review. A reported confidence
    or qualification certificate is retained as evidence, never consulted as
    a permission. No configuration of this policy grants matter-merge powers.
    """

    __slots__ = ("_encoded",)

    def __init__(self, scope_id, *, actors, authorities, matching_rules, relations,
                 allow_semantic=False, allow_correction=False):
        scope = _validate_fragment(scope_id, "identifier")
        if type(allow_semantic) is not bool or type(allow_correction) is not bool:
            raise StorageError("E_POLICY_INVALID")
        definition = {
            "scope_id": scope,
            "actors": _values(actors, "actor_ref", scope_id=scope),
            "authorities": _values(authorities, "receipt_dependency", scope_id=scope),
            "matching_rules": _values(matching_rules, "component_ref"),
            "relations": _values(relations, "component_ref"),
            "allow_semantic": allow_semantic,
            "allow_correction": allow_correction,
            "capabilities": ["attach", "relate"],
            "exact_matching": "any_exact_key_in_declared_host_catalog",
            "semantic_acceptance": "explicit_host_review",
        }
        object.__setattr__(self, "_encoded", canonical_bytes(definition))

    def __setattr__(self, name, value):
        raise AttributeError("AssociationPolicy is immutable.")

    @property
    def definition(self):
        return json.loads(self._encoded)

    @property
    def scope_id(self):
        return self.definition["scope_id"]

    @property
    def reference(self):
        return {"namespace": "matter", "id": "association-acceptance-policy", "version": "1.0",
                "digest": canonical_digest(self.definition, "matter.association-policy.v1")}

    @property
    def ref(self):
        return self.reference

    def authorize(self, view, command, *, rule=None, relation=None, capability=None,
                  semantic=False, correction=False):
        definition = self.definition
        scope = definition["scope_id"]
        if (command["scope_id"] != scope or command["actor"]["scope_id"] != scope
                or command["authority"]["scope_id"] != scope
                or any(ref["scope_id"] != scope for ref in command["expected_revisions"])):
            raise StorageError("E_SCOPE_FORBIDDEN")
        if command["actor"] not in definition["actors"]:
            raise StorageError("E_AUTHORITY_REQUIRED", "The host has not granted this actor association authority.")
        authority = next((ref for ref in definition["authorities"]
                          if entity_ref(ref) == command["authority"]), None)
        if authority is None:
            raise StorageError("E_AUTHORITY_REQUIRED", "An admitted host authority receipt is required.")
        # Port failures remain port failures. A claimed evaluator receipt does
        # not become authority by appearing in a command's authority field.
        stored = view.get(authority)
        try:
            receipt = validate_record(stored)
            valid = (entity_ref(receipt) == entity_ref(authority)
                     and snapshot_digest(receipt) == authority["digest"]
                     and receipt["record_type"] == "receipt"
                     and receipt["body"]["stage"] == "authority"
                     and receipt["provenance"]["origin"] == "host")
        except (ValueError, TypeError, KeyError, RecursionError):
            valid = False
        if not valid:
            raise StorageError("E_AUTHORITY_REQUIRED", "The admitted receipt must record host authority.")
        if rule is not None and rule not in definition["matching_rules"]:
            raise StorageError("E_POLICY_INVALID", "This matching rule is outside the host policy.")
        if relation is not None and relation not in definition["relations"]:
            raise StorageError("E_AUTHORITY_REQUIRED", "This relationship is outside the host policy.")
        if capability is not None and capability not in definition["capabilities"]:
            raise StorageError("E_AUTHORITY_REQUIRED", "Association acceptance does not grant merge authority.")
        if semantic and not definition["allow_semantic"]:
            raise StorageError("E_AUTHORITY_REQUIRED", "The host policy does not allow reviewed semantic acceptance.")
        if correction and not definition["allow_correction"]:
            raise StorageError("E_AUTHORITY_REQUIRED", "Explicit correction authority is required to release a decision.")
        return deepcopy(authority)
