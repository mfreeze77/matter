"""MAT-021 immutable delivery declarations and fenced durable outbox values.

This module declares host/transport contracts; it performs no network I/O and
imports no downstream transport client. Concrete protocol operations live in
``matter.delivery`` over the existing scoped storage port.
"""
from copy import deepcopy

from ._rule_values import FrozenValue, checked, descriptor, domain, fragment
from .canonical import canonical_bytes, canonical_digest
from .storage import PROJECTION_TYPE, StorageError, entity_ref

NAMESPACE = "matter.delivery"
REQUEST_EXTENSION = "matter:delivery-request"
RESULT_EXTENSION = "matter:delivery-result"
OBSERVATION_EXTENSION = "matter:delivery-observation"
ENGINE = descriptor("matter", "delivery-outbox", "1.0", {
    "authorization": "original-context-current-gates-atomic-budget-commit",
    "transport": "injected-explicit-capabilities", "baseline": "observed-milestone-order",
    "source_authority": False}, "matter.delivery-engine.v1")


def fail(code="E_EVIDENCE_INVALID"):
    raise StorageError(code, "The delivery declaration or its retained original context is invalid.")


def stable(reference):
    return {key: reference[key] for key in ("namespace", "id")}


def equivalent_key(decision, baseline):
    before = None if baseline is None else {key: baseline[key] for key in ("material_contract", "material_digest")}
    return canonical_digest({"matter": entity_ref(decision["matter"]), "purpose": stable(decision["purpose"]),
        "audience": stable(decision["audience"]), "before": before,
        "after": {key: decision[key] for key in ("material_contract", "material_digest")}}, "matter.delivery-delta.v1")


def slot_ref(scope_id, key):
    return {"scope_id": scope_id, "namespace": NAMESPACE, "record_type": PROJECTION_TYPE, "id": "delta-" + key}


def authorization_value(record):
    """Validate an ACTUAL stored immutable authorization, never a caller flag."""
    fragment(record, "receipt_record")
    if (record["namespace"] != NAMESPACE or record["provenance"]["origin"] != "system" or
            record["provenance"]["producer"] != ENGINE or record["body"]["stage"] != "operation" or
            record["body"]["outcome"] != "matter:delivery_authorized"):
        fail("E_AUTHORITY_REQUIRED")
    wrapped = record["body"]["details"]
    if wrapped != domain("delivery-authorization", wrapped.get("value")):
        fail()
    value = wrapped["value"]
    if (record["scope_id"] != value["scope_id"] or record["provenance"]["recorded_at"] != value["authorized_at"] or
            record["body"]["recorded_at"] != value["authorized_at"]):
        fail()
    return deepcopy(value)


class TransportCapabilities(FrozenValue):
    """Host-admitted transport guarantees, not inferred universal exactly-once."""
    def __init__(self, value): self._freeze(domain("delivery-transport", value)["value"])
    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["version"], value, "matter.delivery-transport.v1")


class DestinationDefinition(FrozenValue):
    """Explicit exact audience/destination permission and transport binding."""
    def __init__(self, value):
        value = domain("delivery-destination", value)["value"]
        target = value["permission_target"]
        if target["record_type"] in {"receipt", "control"} or (target["record_type"] == PROJECTION_TYPE and target["namespace"].startswith("matter.")):
            fail("E_POLICY_INVALID")
        self._freeze(value)
    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["version"], value, "matter.delivery-destination.v1")


class TransportResult(FrozenValue):
    """Safe terminal observation; not-found never proves an old sender is fenced."""
    def __init__(self, value):
        value = domain("delivery-transport-result", value)["value"]
        if value["status"] == "delivered" and (value["milestone"] is None or value["receipt_id"] is None): fail()
        self._freeze(value)
