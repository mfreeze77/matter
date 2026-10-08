"""Transport-neutral persistence port for trusted, synchronous host handlers.

The port establishes storage atomicity, not business-operation authorization.
Handlers must declare every preexisting read that influences their writes in
the command's expected_revisions. Only reads through the transaction can be
checked by this port; provider calls and external actions belong outside it.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
from functools import lru_cache
from typing import Any, Callable, Protocol

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from ..canonical import CanonicalError, canonical_bytes, canonical_digest
from ..contracts import ContractError, _FORMAT_CHECKER, error_result, record_digest, schema_for


PROJECTION_TYPE = "matter:projection"
STORAGE_NAMESPACE = "matter.storage"
MUTABLE_RECORD_TYPES = frozenset({
    "occurrence", "matter", "evidence_relation", "accepted_association",
    "matter_relation",
})
_CORE_ID = "https://github.com/mfreeze77/matter/schemas/core-record.schema.json"
_IDENTITY_FIELDS = ("scope_id", "namespace", "record_type", "id")


class StorageError(ContractError):
    """A semantic storage refusal; raw database exception text is never public."""

    def __init__(
        self,
        code: str,
        detail: str | None = None,
        *,
        retriable: bool = False,
        affected_references: tuple[dict[str, Any], ...] = (),
    ) -> None:
        super().__init__(code, detail)
        self.retriable = retriable
        self.affected_references = deepcopy(affected_references)

    def result(self, operation: str, operation_id: str) -> dict[str, Any]:
        return error_result(
            operation, operation_id, self.code, detail=self.detail,
            retriable=self.retriable, affected_references=self.affected_references,
        )


@lru_cache(maxsize=8)
def _fragment_validator(name: str) -> Draft202012Validator:
    core = schema_for("record")
    registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
    return Draft202012Validator(
        {"$ref": f"{_CORE_ID}#/$defs/{name}"}, registry=registry, format_checker=_FORMAT_CHECKER,
    )


def _validate_fragment(value: Any, name: str) -> Any:
    try:
        canonical_bytes(value)
        valid = _fragment_validator(name).is_valid(value)
    except (CanonicalError, RecursionError):
        valid = False
    if not valid:
        raise StorageError("E_SCHEMA_INVALID")
    return deepcopy(value)


def _reference(value: Any, *, pinned: bool = False) -> dict[str, Any]:
    return _validate_fragment(value, "pinned_ref" if pinned else "entity_ref")


def entity_ref(value: dict[str, Any]) -> dict[str, Any]:
    """Extract an unpinned reference from a record, projection, or pinned ref."""
    if type(value) is not dict or any(key not in value for key in _IDENTITY_FIELDS):
        raise StorageError("E_SCHEMA_INVALID")
    return _reference({key: value[key] for key in _IDENTITY_FIELDS})


def _identity(value: dict[str, Any]) -> tuple[str, str, str]:
    # Type is immutable metadata, not another namespace for the same opaque ID.
    return value["scope_id"], value["namespace"], value["id"]


def _validate_projection(value: Any) -> dict[str, Any]:
    """Validate the internal projection shape, distinct from a core record."""
    required = {
        "schema_version", "record_type", "scope_id", "namespace", "id",
        "revision", "creation_receipt", "value", "watch_keys",
    }
    if type(value) is not dict or set(value) != required:
        raise StorageError("E_SCHEMA_INVALID")
    try:
        canonical_bytes(value)
    except CanonicalError:
        raise StorageError("E_SCHEMA_INVALID") from None
    if value["schema_version"] != "1.0":
        raise StorageError("E_VERSION_UNSUPPORTED")
    if value["record_type"] != PROJECTION_TYPE:
        raise StorageError("E_SCHEMA_INVALID")
    entity_ref(value)
    _validate_fragment(value["revision"], "revision")
    _validate_fragment(value["creation_receipt"], "receipt_ref")
    _validate_fragment(value["value"], "domain_value")
    if type(value["watch_keys"]) is not list:
        raise StorageError("E_SCHEMA_INVALID")
    for key in value["watch_keys"]:
        _validate_fragment(key, "identifier")
    if len(set(value["watch_keys"])) != len(value["watch_keys"]):
        raise StorageError("E_SCHEMA_INVALID", "Watch keys must be unique.")
    return deepcopy(value)


def snapshot_digest(value: dict[str, Any]) -> str:
    """Digest a complete immutable snapshot, including a projection revision."""
    if type(value) is dict and value.get("record_type") == PROJECTION_TYPE:
        return canonical_digest(_validate_projection(value), "projection.v1")
    return record_digest(value)


def pin(value: dict[str, Any]) -> dict[str, Any]:
    """Pin mutable records by revision and immutable records by exact digest."""
    digest = snapshot_digest(value)  # Validate the complete snapshot first.
    reference = entity_ref(value)
    if value["record_type"] in MUTABLE_RECORD_TYPES | {PROJECTION_TYPE}:
        return {**reference, "revision": value["revision"]}
    return {**reference, "digest": digest}


class Snapshot(Protocol):
    """A scope-bound, consistent read view, valid only inside its context."""

    def get(self, reference: dict[str, Any]) -> dict[str, Any]:
        """Read current state, or a historical snapshot when a pin is supplied."""
        ...

    def history(self, reference: dict[str, Any]) -> list[dict[str, Any]]:
        """Read all snapshots in storage revision order; absence is E_NOT_FOUND."""
        ...

    def watchers(self, watch_key: str) -> list[dict[str, Any]]:
        """Read registered projections for an exact opaque watch key."""
        ...

    def command_receipt(self, idempotency_key: str) -> dict[str, Any]:
        """Read the original command, digest, result, and full operation receipt."""
        ...

    def receipt_for(self, reference: dict[str, Any]) -> dict[str, Any]:
        """Read the operation receipt that committed the selected snapshot."""
        ...


class Transaction(Protocol):
    """Trusted local writes under one checked command and receipt identity."""

    @property
    def command(self) -> dict[str, Any]: ...

    @property
    def receipt_ref(self) -> dict[str, Any]: ...

    def get(self, reference: dict[str, Any]) -> dict[str, Any]:
        """Read current state; preexisting reads must have declared pins."""
        ...

    def watchers(self, watch_key: str) -> list[dict[str, Any]]: ...

    def insert(self, record_input: dict[str, Any]) -> dict[str, Any]:
        """Insert a core input; assign creation_receipt and initial revision."""
        ...

    def replace(self, record: dict[str, Any]) -> dict[str, Any]:
        """Append the next mutable revision, preserving its creation receipt."""
        ...

    def put_projection(
        self, reference: dict[str, Any], value: dict[str, Any],
        *, watch_keys: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Create or revision a schema-bound projection and its exact-key watches."""
        ...

    def success(self, outcome: str, body: dict[str, Any]) -> dict[str, Any]:
        """Build a typed result using this command's ID and operation receipt."""
        ...


CommandHandler = Callable[[Transaction], dict[str, Any]]


class Storage(Protocol):
    """Persistence boundary; an authorized host supplies the scope and handler.

    execute returns a valid result for valid commands. Invalid wire envelopes
    raise ContractError before execution. Ordinary terminal refusals are
    journaled without writes. Storage outages are explicit and may leave a
    committed outcome uncertain: retry the EXACT command to retrieve it.
    """

    @property
    def scope_id(self) -> str: ...

    def execute(self, command: dict[str, Any], handler: CommandHandler) -> dict[str, Any]: ...

    def snapshot(self) -> AbstractContextManager[Snapshot]: ...

    def get(self, reference: dict[str, Any]) -> dict[str, Any]: ...

    def history(self, reference: dict[str, Any]) -> list[dict[str, Any]]: ...

    def command_receipt(self, idempotency_key: str) -> dict[str, Any]: ...

    def watchers(self, watch_key: str) -> list[dict[str, Any]]: ...

    def receipt_for(self, reference: dict[str, Any]) -> dict[str, Any]: ...

    def close(self) -> None: ...
