"""Persistent continuing subjects resolved by exact, adapter-declared keys.

Prepare a command once and retain it for exact retries. Identity is scoped and
durable; titles, processing runs, audiences, and assessment policies do not
establish it. This service creates subjects and revisions their display
metadata. It does not cluster evidence, add aliases, merge subjects, associate
observations, or apply lifecycle transitions.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .canonical import canonical_bytes
from .contracts import ContractError, command_digest, validate_command, validate_record
from .identity_keys import (
    INDEX_NAMESPACE, ExactIdentityPolicy, binding_value, identity_key_ref,
    read_binding,
)
from .storage import Snapshot, Storage, StorageError, Transaction, entity_ref, pin
from .storage.base import STORAGE_NAMESPACE, _validate_fragment


_OPERATIONS = frozenset({"create_matter", "update_matter_metadata"})
# Built-in persistence namespaces are implementation-owned, not subject IDs.
_RESERVED_NAMESPACES = frozenset({STORAGE_NAMESPACE, INDEX_NAMESPACE, "matter.observations"})


def _identity(value: dict[str, Any]) -> tuple[str, str, str]:
    return value["scope_id"], value["namespace"], value["id"]


def _key(value: dict[str, str]) -> tuple[str, str]:
    return value["namespace"], value["value"]


def _command(value: dict[str, Any], operation: str | None = None) -> dict[str, Any]:
    command = validate_command(value)
    if command["operation"] not in _OPERATIONS or (
        operation is not None and command["operation"] != operation
    ):
        raise ContractError("E_SCHEMA_INVALID", "The command is not supported by this matter operation.")
    return command


def _integrity_error() -> StorageError:
    return StorageError("E_STORAGE_UNAVAILABLE", "The persistent matter identity binding could not be verified.")


def _conflict(records: list[dict[str, Any]] | None = None) -> StorageError:
    return StorageError(
        "E_SOURCE_IDENTITY_CONFLICT", "The declared subject identity conflicts with existing state.",
        affected_references=tuple(entity_ref(record) for record in (records or [])),
    )


def _lookup(view: Snapshot | Transaction, reference: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return view.lookup_identity(reference)
    except StorageError as exc:
        if exc.code == "E_NOT_FOUND":
            return None
        raise


def _stored_matter(value: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    try:
        record = validate_record(value)
        if record["record_type"] != "matter" or entity_ref(record) != reference:
            raise _integrity_error()
        keys = record["body"]["identity_keys"]
        if len({_key(key) for key in keys}) != len(keys):
            raise _integrity_error()
    except ContractError:
        raise _integrity_error() from None
    return record


def _bindings(
    view: Snapshot | Transaction, scope_id: str, keys: list[dict[str, str]],
) -> tuple[list[dict[str, Any] | None], list[dict[str, Any]]]:
    """Read and verify all requested bindings before deciding zero/one/many."""
    indexes = []
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key in keys:
        index = read_binding(view, scope_id, key)
        indexes.append(index)
        if index is None:
            continue
        for reference in index["value"]["value"]["matters"]:
            identity = _identity(reference)
            if identity not in records:
                value = _lookup(view, reference)
                if value is None:
                    raise _integrity_error()
                records[identity] = _stored_matter(value, reference)
            if key not in records[identity]["body"]["identity_keys"]:
                raise _integrity_error()
    return indexes, list(records.values())


def _resolved(
    indexes: list[dict[str, Any] | None], records: list[dict[str, Any]],
    domain_kind: str | None = None,
) -> dict[str, Any] | None:
    if not records:
        return None
    # A partially bound key set is not permission to attach its unbound keys.
    # Applying the same rule to reads prevents a lookup from implying aliases.
    if len(records) != 1 or any(index is None for index in indexes):
        raise _conflict(records)
    record = records[0]
    if domain_kind is not None and record["body"]["domain_kind"] != domain_kind:
        raise _conflict(records)
    return record


class MatterService:
    """Scope-bound subject identity and metadata operations for a trusted host.

    The host supplies its authority receipt and explicitly configures adapter
    namespaces for continuing-subject keys. A declared namespace is an adapter
    responsibility, not proof that a string is a real-world subject identifier.
    Storage checks scope, read revisions, and atomicity; it does not authenticate
    callers or turn a structurally valid receipt into business authority.
    """

    def __init__(self, storage: Storage, *, identity_policy: ExactIdentityPolicy) -> None:
        _validate_fragment(storage.scope_id, "identifier")
        if not isinstance(identity_policy, ExactIdentityPolicy):
            raise StorageError("E_POLICY_INVALID", "An exact subject-key policy is required.")
        self._storage, self._policy = storage, identity_policy

    @property
    def scope_id(self) -> str:
        return self._storage.scope_id

    @property
    def identity_policy(self) -> dict[str, Any]:
        """Return the detached policy reference to put in creation commands."""
        return self._policy.reference

    def _check_scope(self, command: dict[str, Any]) -> None:
        matter = command["body"]["matter"]
        references = [command["actor"], command["authority"], matter]
        references.extend(command["expected_revisions"])
        if command["operation"] == "create_matter":
            references.extend(matter["provenance"]["parents"])
            references.extend(matter.get("supersedes", []))
        if command["scope_id"] != self.scope_id or any(
            reference["scope_id"] != self.scope_id for reference in references
        ):
            raise StorageError("E_SCOPE_FORBIDDEN")

    def prepare(self, command: dict[str, Any]) -> dict[str, Any]:
        """Capture current dependencies without changing caller-supplied pins.

        This read-only step may refuse invalid keys, scope, or index integrity.
        Execution journals ordinary semantic refusals. A concurrent identity or
        metadata change produces E_REVISION_CONFLICT; use a NEW command to make
        a fresh decision, and the exact saved command to recover an old outcome.
        """
        command = _command(command)
        self._check_scope(command)
        expected = command["expected_revisions"]
        identities = set()
        for reference in expected:
            identity = _identity(reference)
            if identity in identities:
                raise StorageError("E_SCHEMA_INVALID", "Expected revisions contain a duplicate identity.")
            identities.add(identity)

        def include(reference: dict[str, Any]) -> None:
            if reference["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")
            identity = _identity(reference)
            if identity not in identities:
                expected.append(deepcopy(reference))
                identities.add(identity)

        with self._storage.snapshot() as view:
            try:
                journal = view.command_receipt(command["idempotency_key"])
            except StorageError as exc:
                if exc.code != "E_NOT_FOUND":
                    raise
            else:
                if command_digest(command) != journal["command_digest"]:
                    raise StorageError("E_IDEMPOTENCY_CONFLICT")
                return command

            matter = command["body"]["matter"]
            if command["operation"] == "create_matter":
                keys = self._policy.validate_keys(matter["body"]["identity_keys"])
                indexes, records = _bindings(view, self.scope_id, keys)
                for index in indexes:
                    if index is not None:
                        include(pin(index))
                for record in records:
                    include(pin(record))
                occupied = _lookup(view, entity_ref(matter))
                if occupied is not None:
                    include(pin(occupied))
                for reference in matter["provenance"]["parents"] + matter.get("supersedes", []):
                    include(reference)
            else:
                # A body pin is a precondition, never permission to silently
                # refresh a stale edit to the latest display metadata.
                include(matter)
                current = _lookup(view, entity_ref(matter))
                if current is not None and current["record_type"] == "matter":
                    current = _stored_matter(current, entity_ref(matter))
                    keys = self._policy.validate_keys(current["body"]["identity_keys"])
                    indexes, records = _bindings(view, self.scope_id, keys)
                    for index in indexes:
                        if index is not None:
                            include(pin(index))
                    for record in records:
                        include(pin(record))
        return validate_command(command)

    def create(self, command: dict[str, Any]) -> dict[str, Any]:
        """Create all declared key bindings atomically or return one existing ID."""
        return self._storage.execute(_command(command, "create_matter"), self._create)

    def _create(self, tx: Transaction) -> dict[str, Any]:
        command = tx.command
        self._check_scope(command)
        proposed = command["body"]["matter"]
        if command["body"]["identity_policy"] != self._policy.reference:
            raise StorageError("E_POLICY_INVALID", "The declared subject-key policy is not the configured policy.")
        keys = self._policy.validate_keys(proposed["body"]["identity_keys"])
        if proposed["namespace"] in _RESERVED_NAMESPACES:
            raise StorageError("E_SCOPE_FORBIDDEN", "The persistence namespace is reserved.")
        if "lifecycle" in proposed["body"] or "supersedes" in proposed:
            raise StorageError("E_POLICY_INVALID", "Matter creation cannot apply lifecycle or replacement decisions.")

        indexes, records = _bindings(tx, self.scope_id, keys)
        current = _resolved(indexes, records, proposed["body"]["domain_kind"])
        occupied = _lookup(tx, entity_ref(proposed))
        if occupied is not None and (
            current is None or entity_ref(occupied) != entity_ref(current)
        ):
            raise _conflict([occupied])
        if current is not None:
            # The current command has its own receipt. Creation provenance,
            # metadata, revisions, keys, and the original receipt stay intact.
            return tx.success("existing", {"matter": pin(current)})

        for reference in proposed["provenance"]["parents"]:
            if entity_ref(reference) == entity_ref(proposed):
                raise StorageError("E_EVIDENCE_INVALID", "A matter cannot be its own provenance parent.")
            tx.get(reference)
        stored = tx.insert(proposed)
        for key in keys:
            tx.put_projection(
                identity_key_ref(self.scope_id, key),
                binding_value(self.scope_id, key, [entity_ref(stored)]),
            )
        return tx.success("created", {"matter": pin(stored)})

    def update_metadata(self, command: dict[str, Any]) -> dict[str, Any]:
        """Replace optional title/description/extensions; omission clears them."""
        return self._storage.execute(
            _command(command, "update_matter_metadata"), self._update_metadata,
        )

    def _update_metadata(self, tx: Transaction) -> dict[str, Any]:
        command = tx.command
        self._check_scope(command)
        target = command["body"]["matter"]
        current = _stored_matter(tx.get(target), entity_ref(target))
        keys = self._policy.validate_keys(current["body"]["identity_keys"])
        indexes, records = _bindings(tx, self.scope_id, keys)
        if any(index is None for index in indexes):
            raise _integrity_error()
        resolved = _resolved(indexes, records)
        if resolved is None or entity_ref(resolved) != entity_ref(current):
            raise _integrity_error()

        changed = deepcopy(current)
        metadata = command["body"]["metadata"]
        for field in ("title", "description"):
            changed["body"].pop(field, None)
            if field in metadata:
                changed["body"][field] = deepcopy(metadata[field])
        changed.pop("extensions", None)
        if "extensions" in metadata:
            changed["extensions"] = deepcopy(metadata["extensions"])
        # Strict JSON distinguishes booleans from integers, including inside
        # unknown extension payloads; Python container equality does not.
        if canonical_bytes(changed) == canonical_bytes(current):
            return tx.success("unchanged", {"matter": pin(current)})
        changed["revision"] += 1
        stored = tx.replace(changed)
        return tx.success("updated", {"matter": pin(stored)})

    def resolve(
        self, keys: list[dict[str, str]], *, domain_kind: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the current subject, None for all-unbound keys, or an error.

        Scope is the host-bound store scope. Exact key values are never trimmed,
        case-folded, or inferred from titles. A mixed bound/unbound query and an
        ambiguous mapping raise E_SOURCE_IDENTITY_CONFLICT, without writes.
        """
        keys = self._policy.validate_keys(keys)
        if domain_kind is not None:
            _validate_fragment(domain_kind, "namespaced_name")
        with self._storage.snapshot() as view:
            indexes, records = _bindings(view, self.scope_id, keys)
            return _resolved(indexes, records, domain_kind)
