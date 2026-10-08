"""Exact, host-declared subject keys for continuing matter identity.

The host chooses adapter-owned namespaces whose keys identify continuing
subjects. This neutral policy cannot infer semantic durability from arbitrary
strings. It does not normalize, case-fold, trim, split delimiters, fall back to
run IDs, expand a matter's key set, or rebind keys to a different subject.

The policy reference binds its complete versioned configuration. Index entries
use stable bare matter references so display edits do not churn the index.
Multiple candidates remain explicit; this module never selects a winner or
merges them. The matter service verifies the current candidate records, their
actual identity keys and domain kinds under a revision-checked command.
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import json
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from .canonical import canonical_digest, source_digest
from .contracts import schema_for
from .storage import PROJECTION_TYPE, Snapshot, StorageError, Transaction, entity_ref
from .storage.base import _validate_fragment, _validate_projection


INDEX_NAMESPACE = "matter.identity_keys"
_INDEX_FILE = "matter-identity-key.schema.json"

__all__ = [
    "INDEX_NAMESPACE", "ExactIdentityPolicy", "new_matter_id", "identity_key_ref",
    "binding_value", "read_binding",
]


def new_matter_id() -> str:
    """Allocate an opaque UUID4 before preparing a command, then retain it.

    A command retry must reuse its original proposed identity; allocating a new
    ID while preparing or replaying would change that command's canonical bytes.
    """
    return str(uuid4())


@dataclass(frozen=True, slots=True, init=False)
class ExactIdentityPolicy:
    """Immutable exact-key policy for a nonempty set of declared namespaces."""

    key_namespaces: tuple[str, ...]

    def __init__(self, *, key_namespaces: Iterable[str]) -> None:
        if isinstance(key_namespaces, (str, bytes, bytearray)):
            raise StorageError("E_SCHEMA_INVALID", "Identity policy requires a namespace collection.")
        try:
            supplied = tuple(key_namespaces)
        except TypeError:
            raise StorageError("E_SCHEMA_INVALID", "Identity policy requires a namespace collection.") from None
        namespaces = tuple(_validate_fragment(value, "namespace") for value in supplied)
        if not namespaces or len(set(namespaces)) != len(namespaces):
            raise StorageError("E_SCHEMA_INVALID", "Identity namespaces must be nonempty and distinct.")
        object.__setattr__(self, "key_namespaces", tuple(sorted(namespaces)))

    @property
    def definition(self) -> dict[str, Any]:
        """Return a detached canonical configuration, including all behavior."""
        return {
            "algorithm": "matter.exact-subject-keys.v1",
            "identity": "continuing_subject",
            "normalization": "none",
            "key_namespaces": list(self.key_namespaces),
            "key_expansion": "forbidden",
            "key_rebinding": "forbidden",
        }

    @property
    def reference(self) -> dict[str, str]:
        """Bind configuration and algorithm version in a core component_ref."""
        return {
            "namespace": "matter", "id": "exact-subject-keys", "version": "1.0",
            "digest": canonical_digest(self.definition, "matter.identity-policy.v1"),
        }

    def validate_keys(self, keys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate exact pairs without normalizing or changing their order."""
        if type(keys) is not list or not keys:
            raise StorageError("E_SCHEMA_INVALID", "At least one declared subject key is required.")
        validated = [_validate_fragment(key, "identity_key") for key in keys]
        identities = [(key["namespace"], key["value"]) for key in validated]
        if len(set(identities)) != len(identities):
            raise StorageError("E_SCHEMA_INVALID", "A subject key must be declared only once.")
        if any(namespace not in self.key_namespaces for namespace, _ in identities):
            raise StorageError("E_POLICY_INVALID", "A subject-key namespace is not allowed by this policy.")
        return validated


def identity_key_ref(scope_id: str, key: dict[str, Any]) -> dict[str, str]:
    """Address an exact key using structured canonical framing, not delimiters."""
    scope = _validate_fragment(scope_id, "identifier")
    validated = _validate_fragment(key, "identity_key")
    return {
        "scope_id": scope, "namespace": INDEX_NAMESPACE, "record_type": PROJECTION_TYPE,
        "id": "key-" + canonical_digest(
            {"scope_id": scope, "key": validated}, "matter.identity-key.v1",
        ),
    }


def _integrity_error() -> StorageError:
    return StorageError("E_STORAGE_UNAVAILABLE", "The matter identity-key binding could not be verified.")


@lru_cache(maxsize=1)
def _binding_contract() -> tuple[dict[str, str], Draft202012Validator]:
    try:
        content = files("matter._schemas").joinpath(_INDEX_FILE).read_bytes()
        schema = json.loads(content)
        Draft202012Validator.check_schema(schema)
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        descriptor = {
            "namespace": "matter", "id": "matter-identity-key", "version": "1.0",
            "digest": source_digest(content),
        }
        return descriptor, Draft202012Validator(schema, registry=registry)
    except (OSError, ValueError, TypeError, KeyError, SchemaError):
        raise _integrity_error() from None


def binding_value(
    scope_id: str, key: dict[str, Any], matters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a detached schema-bound value with unique, same-scope bare refs.

    More than one matter is representable so an ambiguous mapping cannot be
    silently reduced to a winner. Creating this value neither changes a matter
    nor establishes that its proposed keys or domain are consistent.
    """
    scope = _validate_fragment(scope_id, "identifier")
    validated_key = _validate_fragment(key, "identity_key")
    if type(matters) is not list or not matters:
        raise StorageError("E_SCHEMA_INVALID", "An identity binding requires at least one matter.")
    references = [_validate_fragment(reference, "matter_ref") for reference in matters]
    if any(reference["scope_id"] != scope for reference in references):
        raise StorageError("E_SCOPE_FORBIDDEN")
    identities = [(reference["namespace"], reference["id"]) for reference in references]
    if len(set(identities)) != len(identities):
        raise StorageError("E_SCHEMA_INVALID", "A matter can appear only once in an identity binding.")
    descriptor, validator = _binding_contract()
    body = {"scope_id": scope, "key": validated_key, "matters": references}
    if not validator.is_valid(body):
        raise StorageError("E_SCHEMA_INVALID")
    return {"schema": deepcopy(descriptor), "value": body}


def read_binding(
    view: Snapshot | Transaction, scope_id: str, key: dict[str, Any],
) -> dict[str, Any] | None:
    """Read a verified projection, preserving absence and storage refusals.

    Revision conflicts from a transaction's dependency checks propagate. A
    malformed returned binding is storage failure, never an absent subject or
    a successful partial candidate list. The storage port defines E_NOT_FOUND;
    an identity lookup cannot conceal an occupant of the wrong record kind.
    This function does not probe another scope or bypass that port on absence.
    """
    reference = identity_key_ref(scope_id, key)
    try:
        stored = view.lookup_identity(deepcopy(reference))
    except StorageError as error:
        if error.code == "E_NOT_FOUND":
            return None
        raise
    try:
        projection = _validate_projection(stored)
        if (
            entity_ref(projection) != reference
            or projection["creation_receipt"]["scope_id"] != scope_id
        ):
            raise _integrity_error()
        contents = projection["value"]
        expected = binding_value(scope_id, key, contents["value"]["matters"])
        # Equality checks both the exact schema descriptor and the complete
        # closed value shape, including the original scope and exact key.
        if contents != expected:
            raise _integrity_error()
        return projection
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _integrity_error() from None
