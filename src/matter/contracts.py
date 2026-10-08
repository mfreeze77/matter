"""Portable Matter v1 structural validation and transport-neutral failures.

Validation preserves input values and never checks the existence, authority,
freshness, or truth of a referenced record. Those checks belong to the host,
storage, and rule implementations. Schema resources are bundled locally;
validation does not fetch schema URLs or evidence locators over the network.
"""

from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
import json
import re
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .canonical import CanonicalError, canonical_bytes, canonical_digest, loads


SCHEMA_VERSION = "1.0"
ContractKind = Literal["record", "command", "result"]
_SCHEMA_FILES = {
    "record": "core-record.schema.json",
    "command": "operation-command.schema.json",
    "result": "operation-result.schema.json",
}
_ERROR_DETAILS = {
    "E_SCHEMA_INVALID": "The value does not satisfy the declared contract.",
    "E_VERSION_UNSUPPORTED": "The declared contract version is not supported.",
    "E_SCOPE_FORBIDDEN": "The operation is not permitted in the requested scope.",
    "E_NOT_FOUND": "The requested readable record was not found.",
    "E_IDEMPOTENCY_CONFLICT": "The idempotency key is bound to different content.",
    "E_SOURCE_IDENTITY_CONFLICT": "The source identity is bound to different content.",
    "E_REVISION_CONFLICT": "An expected record revision no longer matches.",
    "E_ASSOCIATION_CONFLICT": "The proposed association conflicts with accepted state.",
    "E_MERGE_CONFLICT": "The requested merge conflicts with accepted state.",
    "E_EVIDENCE_INVALID": "The supplied evidence does not meet its declared contract.",
    "E_EVIDENCE_UNAVAILABLE": "Required evidence is not currently available.",
    "E_DEPENDENCY_STALE": "A required dependency is no longer current.",
    "E_POLICY_INVALID": "The applicable policy is missing or invalid.",
    "E_RULE_CONFLICT": "Applicable rule results conflict without an accepted resolution.",
    "E_AUTHORITY_REQUIRED": "The operation requires an applicable authority receipt.",
    "E_BUDGET_EXHAUSTED": "The applicable resource budget has been exhausted.",
    "E_CANCELLED": "The operation was cancelled.",
    "E_STORAGE_UNAVAILABLE": "Storage could not establish a durable outcome.",
    "E_DELIVERY_UNKNOWN": "The transport outcome could not be established.",
}
ERROR_CODES = frozenset(_ERROR_DETAILS)


class ContractError(ValueError):
    """A safe validation failure with a stable, transport-neutral code.

    ``detail`` never contains a rejected payload or a jsonschema exception's
    instance rendering. A transport adapter can use :func:`error_result` with
    its own operation identity when exposing the failure to a caller.
    """

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail if detail is not None else _ERROR_DETAILS[code]
        super().__init__(self.detail)


_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{3}|\.[0-9]{6}|\.[0-9]{9})?Z"
)
# Enable only the explicitly supported format. Optional jsonschema extras must
# not silently change the set of admitted records on another installation.
_FORMAT_CHECKER = FormatChecker(formats=[])


@_FORMAT_CHECKER.checks("matter-utc-time")
def _is_utc_time(value: Any) -> bool:
    """Check the supported RFC 3339 UTC subset without changing precision."""
    if not isinstance(value, str):
        return True  # The schema's type keyword rejects non-strings.
    if _TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        # Validate the calendar and time without rounding nanoseconds.
        datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


@lru_cache(maxsize=1)
def _schema_resources() -> dict[str, dict[str, Any]]:
    resource_root = files("matter._schemas")
    result = {}
    for kind, filename in _SCHEMA_FILES.items():
        schema = json.loads(resource_root.joinpath(filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        result[kind] = schema
    return result


def schema_for(kind: ContractKind) -> dict[str, Any]:
    """Return a defensive copy of one bundled Draft 2020-12 schema.

    Other schemas may reference definitions in the core record schema. A
    consumer outside Python should register all three resources by ``$id``.
    """
    if kind not in _SCHEMA_FILES:
        raise ValueError("contract kind must be record, command, or result")
    return deepcopy(_schema_resources()[kind])


@lru_cache(maxsize=3)
def _validator(kind: ContractKind) -> Draft202012Validator:
    schemas = _schema_resources()
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    # Registry's default retrieval is disabled. Unregistered references fail
    # locally; no remote retriever is supplied.
    return Draft202012Validator(
        schemas[kind], registry=registry, format_checker=_FORMAT_CHECKER
    )


def _validate(value: Any, kind: ContractKind) -> dict[str, Any]:
    # JSON Schema treats 1.0 as an integer and cannot detect keys lost by a
    # permissive decoder. Enforce the wire value domain before schema checks;
    # decode_* additionally validates the original token stream with loads().
    try:
        canonical_bytes(value)
    except CanonicalError:
        raise ContractError("E_SCHEMA_INVALID") from None
    if not isinstance(value, dict):
        raise ContractError("E_SCHEMA_INVALID")
    version = value.get("schema_version")
    if isinstance(version, str) and version != SCHEMA_VERSION:
        raise ContractError("E_VERSION_UNSUPPORTED")
    try:
        problem = next(_validator(kind).iter_errors(value), None)
    except RecursionError:
        raise ContractError(
            "E_SCHEMA_INVALID", "Contract nesting exceeds implementation capacity."
        ) from None
    if problem is not None:
        raise ContractError("E_SCHEMA_INVALID")
    if kind == "result" and value["status"] == "failure":
        if value["error"]["operation_id"] != value["operation_id"]:
            raise ContractError(
                "E_SCHEMA_INVALID", "Failure operation identities must agree."
            )
    return deepcopy(value)


def validate_record(value: Any) -> dict[str, Any]:
    """Validate a stored-record envelope without interpreting its evidence."""
    return _validate(value, "record")


def validate_command(value: Any) -> dict[str, Any]:
    """Validate a command's structure without authorizing or executing it."""
    return _validate(value, "command")


def validate_result(value: Any) -> dict[str, Any]:
    """Validate a result; execution failures cannot contain success fields."""
    return _validate(value, "result")


def _decode(source: str | bytes, kind: ContractKind) -> dict[str, Any]:
    try:
        value = loads(source)
    except CanonicalError:
        raise ContractError("E_SCHEMA_INVALID") from None
    return _validate(value, kind)


def decode_record(source: str | bytes) -> dict[str, Any]:
    """Strictly decode JSON before record validation, preserving unknown time."""
    return _decode(source, "record")


def decode_command(source: str | bytes) -> dict[str, Any]:
    """Strictly decode a command without accepting duplicate keys or floats."""
    return _decode(source, "command")


def decode_result(source: str | bytes) -> dict[str, Any]:
    """Strictly decode a transport-neutral operation result."""
    return _decode(source, "result")


def record_digest(value: Any) -> str:
    """Hash a validated record, binding its record kind and schema version."""
    record = validate_record(value)
    return canonical_digest(record, f"record.{record['record_type']}.v1")


def command_digest(value: Any) -> str:
    """Hash a validated command for the persistence idempotency journal."""
    command = validate_command(value)
    return canonical_digest(command, f"command.{command['operation']}.v1")


def error_result(
    operation: str,
    operation_id: str,
    code: str,
    *,
    retriable: bool = False,
    affected_references: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    detail: str | None = None,
) -> dict[str, Any]:
    """Construct and validate an explicit failure, never a domain conclusion.

    The host must filter ``affected_references`` to records this caller may
    read. A custom ``detail`` must already be safe for that caller; do not pass
    raw provider/storage exception text. Default detail strings are static.
    ``retriable`` is an explicit host judgment, not an automatic retry policy.
    """
    if not isinstance(code, str) or code not in ERROR_CODES:
        raise ContractError("E_SCHEMA_INVALID", "Unknown operation error code.")
    return validate_result(
        {
            "schema_version": SCHEMA_VERSION,
            "operation": operation,
            "operation_id": operation_id,
            "status": "failure",
            "error": {
                "code": code,
                "operation_id": operation_id,
                "retriable": retriable,
                "affected_references": list(affected_references),
                "detail": detail if detail is not None else _ERROR_DETAILS[code],
            },
        }
    )
