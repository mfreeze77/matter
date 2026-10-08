"""Scoped evidence associations with frozen citation validation and history.

An accepted association records a host decision about one claim or component;
it does not establish truth, retire a contradiction, change a matter, or merge
identities. Adapters execute before the write transaction. Prepare once and
retain the exact command for retries. The host owns receipt admission and
authority; adapter descriptors do not authenticate signatures.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .canonical import canonical_bytes, canonical_digest
from .citations import LocatorAdapter, _contract, _domain, verify_locator_validation
from .claims import read_claim, validate_applicability
from .contracts import ContractError, command_digest, validate_command, validate_record
from .storage import PROJECTION_TYPE, Snapshot, Storage, StorageError, Transaction, entity_ref, pin, snapshot_digest
from .storage.base import _validate_fragment, _validate_projection


INDEX_NAMESPACE = "matter.evidence_relations"
VALIDATION_NAMESPACE = "matter.citations"
_RESERVED = {"matter.storage", "matter.identity_keys", "matter.observations", "matter.occurrences",
             "matter.provenance_groups", "matter.claims", INDEX_NAMESPACE, VALIDATION_NAMESPACE}
_STATUSES = {"proposed", "accepted", "rejected", "superseded"}

__all__ = ["INDEX_NAMESPACE", "VALIDATION_NAMESPACE", "relation_index_ref", "EvidenceRelationService"]


def _invalid() -> StorageError:
    return StorageError("E_EVIDENCE_INVALID", "The cited evidence relation could not be verified.")


def _identity(value):
    return value["scope_id"], value["namespace"], value["id"]


def _matches(record, reference):
    return entity_ref(record) == entity_ref(reference) and (
        record.get("revision") == reference["revision"] if "revision" in reference
        else snapshot_digest(record) == reference["digest"]
    )


def _lookup(view, reference):
    try:
        return view.lookup_identity(reference)
    except StorageError as error:
        if error.code == "E_NOT_FOUND":
            return None
        raise


def _scoped(scope, reference, fragment="pinned_ref"):
    ref = _validate_fragment(reference, fragment)
    if ref["scope_id"] != scope:
        raise StorageError("E_SCOPE_FORBIDDEN")
    return ref


def relation_index_ref(scope_id: str, reference: dict[str, Any]) -> dict[str, Any]:
    scope = _validate_fragment(scope_id, "identifier")
    ref = _scoped(scope, entity_ref(reference), "evidence_relation_ref")
    return {"scope_id": scope, "namespace": INDEX_NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "relation-" + canonical_digest(ref, "matter.evidence-relation-index.v1")}


def _watch(reference, role):
    return "evidence-" + role + "-" + canonical_digest(reference, "matter.evidence-relation-watch.v1")


def _watches(record):
    return tuple(sorted((_watch(record["body"]["claim"], "claim"), _watch(record["body"]["evidence"], "source"))))


def _validation_ref(scope, command_id):
    return {"scope_id": scope, "namespace": VALIDATION_NAMESPACE, "record_type": "receipt",
            "id": "validation-" + canonical_digest({"scope_id": scope, "command_id": command_id},
                                                    "matter.locator-receipt.v1")}


def _input(record):
    value = deepcopy(record)
    value.pop("creation_receipt", None)
    value.pop("revision", None)
    value["body"].pop("locator_validation", None)
    value["body"]["locator"].pop("validation_receipt", None)
    return value


def _index_value(record, original):
    body = record["body"]
    return _domain("evidence-relation-index", {
        "scope_id": record["scope_id"], "relation": pin(record), "claim": body["claim"],
        "evidence": body["evidence"], "locator_validation": body["locator_validation"], "original": original,
    })


def _read_index(view, record):
    ref = relation_index_ref(record["scope_id"], record)
    current = _lookup(view, ref)
    if current is None:
        raise _invalid()
    # Package access is distinct from malformed stored content.
    _contract("evidence-relation-index")
    try:
        index = _validate_projection(current)
        if (entity_ref(index) != ref or index["creation_receipt"] != record["creation_receipt"]
                or index["revision"] != record["revision"]):
            raise _invalid()
        original = _validate_fragment(index["value"]["value"]["original"], "evidence_relation_input")
        reconstructed = _input(record)
        reconstructed["body"]["acceptance"] = deepcopy(original["body"]["acceptance"])
        if (canonical_bytes(reconstructed) != canonical_bytes(original) or "locator_validation" in original["body"]
                or "validation_receipt" in original["body"]["locator"]
                or canonical_bytes(index["value"]) != canonical_bytes(_index_value(record, original))
                or index["watch_keys"] != list(_watches(record))):
            raise _invalid()
        return index
    except StorageError as error:
        if error.code == "E_STORAGE_UNAVAILABLE":
            raise
        raise _invalid() from None
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def _record(view, scope, reference, *, kind=None):
    ref = _scoped(scope, reference)
    stored = view.get(ref)
    try:
        value = validate_record(stored)
        if value["scope_id"] != scope or not _matches(value, ref) or (kind is not None and value["record_type"] != kind):
            raise _invalid()
        return value
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def _dependencies(view, scope, declaration):
    try:
        refs = declaration["value"]["dependencies"]
        if type(refs) is not list:
            raise _invalid()
        refs = [_scoped(scope, reference) for reference in refs]
    except StorageError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    for reference in refs:
        record = view.get(reference)
        if not _matches(record, reference):
            raise _invalid()
    return deepcopy(refs)


def _acceptance(view, scope, value, authority=None):
    acceptance = _validate_fragment(value, "acceptance")
    if "authority" in acceptance:
        _scoped(scope, acceptance["authority"], "receipt_ref")
    if authority is not None and acceptance["status"] != "proposed" and acceptance["authority"] != authority:
        raise StorageError("E_POLICY_INVALID", "Acceptance requires this command's declared authority.")
    if "evaluator_receipt" in acceptance:
        reference = _scoped(scope, acceptance["evaluator_receipt"], "receipt_ref")
        receipt = view.get(reference)
        if receipt["record_type"] != "receipt" or receipt["scope_id"] != scope:
            raise _invalid()
    return acceptance


def _target(claim, target):
    target = _validate_fragment(target, "target_component")
    if target["kind"] == "component" and target["component"] not in claim["body"].get("components", {}):
        raise StorageError("E_EVIDENCE_INVALID", "The cited claim does not declare that component.")
    return target


def _links(view, scope, record, *, read_parents=True):
    body = record["body"]
    claim = read_claim(view, scope, body["claim"])
    evidence = _record(view, scope, body["evidence"])
    if evidence["record_type"] not in {"observation", "judgment", "assessment", "claim"}:
        raise _invalid()
    _target(claim, body["target"])
    validate_applicability(body["applicability"])
    for parent in record["provenance"]["parents"]:
        _scoped(scope, parent)
        if entity_ref(parent) == entity_ref(record):
            raise _invalid()
        if read_parents:
            view.get(parent)
    return claim, evidence


def _stored_relation(view, scope, stored):
    try:
        record = validate_record(stored)
        if (record["scope_id"] != scope or record["record_type"] != "evidence_relation"
                or record["creation_receipt"]["scope_id"] != scope or "supersedes" in record
                or "locator_validation" not in record["body"]):
            raise _invalid()
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    # Immutable validation receipts attest to their historical inputs. A
    # mutable adapter dependency or provenance parent advancing must not make
    # an old contribution impossible to inspect, reject, or supersede.
    _, evidence = _links(view, scope, record, read_parents=False)
    _acceptance(view, scope, record["body"]["acceptance"])
    receipt = _record(view, scope, record["body"]["locator_validation"], kind="receipt")
    try:
        details = receipt["body"]["details"]
        adapter = details["value"]["adapter"]
        locator = deepcopy(record["body"]["locator"])
        old_link = locator.pop("validation_receipt", None)
        if old_link is not None and old_link != entity_ref(receipt):
            raise _invalid()
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    declaration = verify_locator_validation(details, evidence=evidence, locator=locator,
        quotation=record["body"].get("quotation"), adapter=adapter)
    if (
        entity_ref(receipt) != _validation_ref(scope, receipt["body"]["operation_id"])
        or receipt["creation_receipt"] != record["creation_receipt"]
        or receipt["provenance"] != {"origin": "adapter", "producer": adapter,
                                    "recorded_at": declaration["checked_at"], "parents": declaration["dependencies"]}
        or receipt["body"]["stage"] != "evaluation" or receipt["body"]["outcome"] != "matter:locator_valid"
        or receipt["body"]["recorded_at"] != declaration["checked_at"]
        or receipt["body"]["evidence"] != declaration["dependencies"]
        or declaration["result"]["status"] != "valid"
    ):
        raise _invalid()
    return record


class _Collector:
    def __init__(self, view, include):
        self._view, self._include = view, include

    def get(self, reference):
        record = self._view.get(reference)
        self._include(pin(record))
        return record

    def lookup_identity(self, reference):
        record = self._view.lookup_identity(reference)
        self._include(pin(record))
        return record


def _command(value, expected=None):
    command = validate_command(value)
    if command["operation"] not in {"relate_evidence", "revise_evidence_acceptance"} or (
        expected is not None and command["operation"] != expected
    ):
        raise ContractError("E_SCHEMA_INVALID", "A cited evidence operation is required.")
    return command


class EvidenceRelationService:
    """Host-authorized associations; no inference or mutation of claim truth."""

    def __init__(self, storage: Storage, *, locator_adapter: LocatorAdapter) -> None:
        _validate_fragment(storage.scope_id, "identifier")
        _validate_fragment(locator_adapter.reference, "component_ref")
        if hasattr(locator_adapter, "scope_id") and locator_adapter.scope_id != storage.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        self._storage, self._adapter = storage, locator_adapter

    @property
    def scope_id(self):
        return self._storage.scope_id

    def _scope(self, command):
        if command["scope_id"] != self.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        for value in [command["actor"], command["authority"], *command["expected_revisions"]]:
            if value["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")

    def _creation(self, view, command, *, require_validation):
        self._scope(command)
        proposed = deepcopy(command["body"]["relation"])
        if proposed["scope_id"] != self.scope_id or proposed["namespace"] in _RESERVED:
            raise StorageError("E_SCOPE_FORBIDDEN")
        if "supersedes" in proposed:
            raise StorageError("E_POLICY_INVALID", "Relations retire through acceptance revisions.")
        if "locator_validation" in proposed["body"] or "validation_receipt" in proposed["body"]["locator"]:
            raise StorageError("E_EVIDENCE_INVALID", "Citation receipts are assigned by the relation service.")
        current = _lookup(view, entity_ref(proposed))
        if current is not None:
            if current["record_type"] != "evidence_relation":
                raise StorageError("E_SOURCE_IDENTITY_CONFLICT")
            current = _stored_relation(view, self.scope_id, current)
            index = _read_index(view, current)
            if canonical_bytes(index["value"]["value"]["original"]) != canonical_bytes(proposed):
                raise StorageError("E_SOURCE_IDENTITY_CONFLICT", "This relation identity already contains another assertion.")
            return {"current": current, "index": index}
        if _lookup(view, relation_index_ref(self.scope_id, proposed)) is not None:
            raise _invalid()
        if _lookup(view, _validation_ref(self.scope_id, command["command_id"])) is not None:
            raise StorageError("E_SOURCE_IDENTITY_CONFLICT", "The citation receipt identity is occupied.")
        _, evidence = _links(view, self.scope_id, proposed)
        _acceptance(view, self.scope_id, proposed["body"]["acceptance"], command["authority"])
        state = {"current": None, "proposed": proposed, "evidence": evidence}
        if "validation" in command["body"]:
            validation = command["body"]["validation"]
            deps = _dependencies(view, self.scope_id, validation)
            state["declaration"] = verify_locator_validation(validation, evidence=evidence,
                locator=proposed["body"]["locator"], quotation=proposed["body"].get("quotation"),
                adapter=self._adapter.reference, dependencies=deps)
        elif require_validation:
            raise StorageError("E_EVIDENCE_INVALID", "Prepare and retain a frozen locator validation before committing.")
        return state

    def _revision(self, view, command):
        self._scope(command)
        reference = _scoped(self.scope_id, command["body"]["relation"], "evidence_relation_dependency")
        current = _lookup(view, entity_ref(reference))
        if current is None or current["record_type"] != "evidence_relation":
            raise StorageError("E_NOT_FOUND")
        if not _matches(current, reference):
            raise StorageError("E_REVISION_CONFLICT")
        record = _stored_relation(view, self.scope_id, current)
        index = _read_index(view, record)
        acceptance = _acceptance(view, self.scope_id, command["body"]["acceptance"], command["authority"])
        return record, index, acceptance

    def prepare(self, command: dict[str, Any]) -> dict[str, Any]:
        """Freeze validation outside transactions and preserve declared read pins."""
        command = _command(command)
        expected = command["expected_revisions"]
        identities = {_identity(ref) for ref in expected}
        if len(identities) != len(expected):
            raise StorageError("E_SCHEMA_INVALID", "Expected revisions contain a duplicate identity.")

        def include(ref):
            _scoped(self.scope_id, ref)
            if _identity(ref) not in identities:
                expected.append(deepcopy(ref))
                identities.add(_identity(ref))

        with self._storage.snapshot() as snapshot:
            try:
                journal = snapshot.command_receipt(command["idempotency_key"])
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
            else:
                if command_digest(command) != journal["command_digest"]:
                    raise StorageError("E_IDEMPOTENCY_CONFLICT")
                return command
            view = _Collector(snapshot, include)
            if command["operation"] == "revise_evidence_acceptance":
                self._revision(view, command)
                return validate_command(command)
            state = self._creation(view, command, require_validation=False)
        if state["current"] is not None:
            return validate_command(command)
        if "validation" not in command["body"]:
            body = state["proposed"]["body"]
            command["body"]["validation"] = self._adapter.validate(
                state["evidence"], body["locator"], quotation=body.get("quotation"),
            )
        # A second snapshot checks every returned adapter dependency. No adapter
        # or payload operation is executed inside either storage transaction.
        with self._storage.snapshot() as snapshot:
            self._creation(_Collector(snapshot, include), command, require_validation=True)
        return validate_command(command)

    def relate(self, command: dict[str, Any]) -> dict[str, Any]:
        return self._storage.execute(_command(command, "relate_evidence"), self._relate)

    def _relate(self, tx: Transaction):
        state = self._creation(tx, tx.command, require_validation=True)
        if state["current"] is not None:
            record = state["current"]
            return tx.success("duplicate", {"relation": pin(record), "locator_validation": record["body"]["locator_validation"], "changes": []})
        declaration = state["declaration"]
        if declaration["result"]["status"] != "valid":
            code = "E_EVIDENCE_UNAVAILABLE" if declaration["result"]["status"] == "unavailable" else "E_EVIDENCE_INVALID"
            raise StorageError(code, "The adapter could not validate the declared citation.")
        scope, command = self.scope_id, tx.command
        receipt = tx.insert({
            "schema_version": "1.0", **_validation_ref(scope, command["command_id"]),
            "provenance": {"origin": "adapter", "producer": declaration["adapter"],
                           "recorded_at": declaration["checked_at"], "parents": declaration["dependencies"]},
            "body": {"stage": "evaluation", "operation_id": command["command_id"],
                     "recorded_at": declaration["checked_at"], "outcome": "matter:locator_valid",
                     "evidence": declaration["dependencies"], "details": command["body"]["validation"]},
        })
        proposed = deepcopy(state["proposed"])
        proposed["body"]["locator_validation"] = pin(receipt)
        record = tx.insert(proposed)
        tx.put_projection(relation_index_ref(scope, record), _index_value(record, state["proposed"]), watch_keys=_watches(record))
        return tx.success("appended", {"relation": pin(record), "locator_validation": pin(receipt),
                                      "changes": [{"cause": "new_evidence", "before": [], "after": [pin(record)]}]})

    def revise_acceptance(self, command: dict[str, Any]) -> dict[str, Any]:
        return self._storage.execute(_command(command, "revise_evidence_acceptance"), self._revise)

    def _revise(self, tx: Transaction):
        record, index, acceptance = self._revision(tx, tx.command)
        previous = pin(record)
        if record["body"]["acceptance"] == acceptance:
            return tx.success("unchanged", {"relation": previous, "changes": []})
        replacement = deepcopy(record)
        replacement["revision"] += 1
        replacement["body"]["acceptance"] = acceptance
        updated = tx.replace(replacement)
        tx.put_projection(relation_index_ref(self.scope_id, updated),
                          _index_value(updated, index["value"]["value"]["original"]), watch_keys=_watches(updated))
        return tx.success("updated", {"relation": pin(updated), "previous": previous,
                                     "changes": [{"cause": "disposition_change", "before": [previous], "after": [pin(updated)]}]})

    def for_claim(self, claim_pin: dict[str, Any], *, target=None, status=None) -> list[dict[str, Any]]:
        reference = _scoped(self.scope_id, claim_pin, "claim_dependency")
        if status is not None and (type(status) is not str or status not in _STATUSES):
            raise StorageError("E_SCHEMA_INVALID")
        if target is not None:
            target = _validate_fragment(target, "target_component")
        records = []
        with self._storage.snapshot() as snapshot:
            claim = read_claim(snapshot, self.scope_id, reference)
            if target is not None:
                _target(claim, target)
            for watched in snapshot.watchers(_watch(reference, "claim")):
                if watched["namespace"] != INDEX_NAMESPACE:
                    raise _invalid()
                try:
                    relation = _scoped(self.scope_id, watched["value"]["value"]["relation"], "evidence_relation_dependency")
                    if entity_ref(watched) != relation_index_ref(self.scope_id, relation):
                        raise _invalid()
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise _invalid() from None
                current = _lookup(snapshot, entity_ref(relation))
                if current is None or pin(current) != relation:
                    raise _invalid()
                record = _stored_relation(snapshot, self.scope_id, current)
                verified_index = _read_index(snapshot, record)
                if canonical_bytes(watched) != canonical_bytes(verified_index):
                    raise _invalid()
                if record["body"]["claim"] != reference:
                    raise _invalid()
                if (target is None or record["body"]["target"] == target) and (
                    status is None or record["body"]["acceptance"]["status"] == status
                ):
                    records.append(record)
        return sorted(records, key=lambda record: canonical_bytes(entity_ref(record)))

    def history(self, relation_ref: dict[str, Any]) -> list[dict[str, Any]]:
        reference = _scoped(self.scope_id, entity_ref(relation_ref), "evidence_relation_ref")
        with self._storage.snapshot() as snapshot:
            history = snapshot.history(reference)
            records = [_stored_relation(snapshot, self.scope_id, record) for record in history]
            if records:
                index = _read_index(snapshot, records[-1])
                original = index["value"]["value"]["original"]
                if canonical_bytes(_input(records[0])) != canonical_bytes(original):
                    raise _invalid()
                for number, record in enumerate(records, 1):
                    reconstructed = _input(record)
                    reconstructed["body"]["acceptance"] = deepcopy(original["body"]["acceptance"])
                    if record["revision"] != number or canonical_bytes(reconstructed) != canonical_bytes(original):
                        raise _invalid()
            return records
