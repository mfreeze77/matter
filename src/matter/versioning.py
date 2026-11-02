"""Opt-in compatibility envelopes; admission is neither authority nor qualification.

Existing native record/command readers still validate the payload. This boundary
preserves optional extensions and refuses undeclared reader semantics before a
host consumes a portable payload. It never converts or upgrades stored records.
"""
from copy import deepcopy
import re

from .canonical import ENCODING_VERSION, CanonicalError, canonical_bytes, canonical_digest, loads
from .contracts import ContractError
from ._rule_values import checked, fragment

MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
MAX_ENVELOPE_DEPTH = 128
_FEATURE = re.compile(r"[a-z][a-z0-9]*(?:[._/-][a-z0-9]+)*", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}", re.ASCII)


def _list(values, pattern):
    if type(values) not in (list, tuple) or len(values) > 64:
        raise ContractError("E_SCHEMA_INVALID")
    if any(type(v) is not str or len(v) > 128 or pattern.fullmatch(v) is None for v in values):
        raise ContractError("E_SCHEMA_INVALID")
    if len(set(values)) != len(values):
        raise ContractError("E_SCHEMA_INVALID")
    return list(values)


def _check_depth(value):
    pending = [(value, 0)]
    nodes = 0
    while pending:
        node, depth = pending.pop()
        nodes += 1
        if nodes > MAX_ENVELOPE_BYTES:
            raise ContractError("E_BUDGET_EXHAUSTED")
        if type(node) in (dict, list):
            depth += 1
            if depth > MAX_ENVELOPE_DEPTH:
                raise ContractError("E_SCHEMA_INVALID")
            pending.extend((child, depth) for child in (node.values() if type(node) is dict else node))


def _envelope(value):
    # Check before canonical validation/deepcopy can consume interpreter stack.
    _check_depth(value)
    value = checked(value, required=("schema_version", "encoding", "required_features",
        "required_semantics", "payload", "extensions"))
    if value["schema_version"] != "1.0" or value["encoding"] != ENCODING_VERSION:
        raise ContractError("E_VERSION_UNSUPPORTED")
    _list(value["required_features"], _FEATURE)
    _list(value["required_semantics"], _DIGEST)
    if type(value["extensions"]) is not dict:
        raise ContractError("E_SCHEMA_INVALID")
    if len(canonical_bytes(value)) > MAX_ENVELOPE_BYTES:
        raise ContractError("E_BUDGET_EXHAUSTED")
    return value


def semantic_fingerprint(component):
    """Bind exact namespace/id/version/content; equal output shape is insufficient."""
    return canonical_digest(fragment(component, "component_ref"), "semantic-component")


def make_envelope(payload, *, required_features=(), required_semantics=(), extensions=None):
    """Declare requirements explicitly; nothing is inferred from model output."""
    return _envelope({"schema_version": "1.0", "encoding": ENCODING_VERSION,
        "required_features": _list(required_features, _FEATURE),
        "required_semantics": _list(required_semantics, _DIGEST),
        "payload": payload, "extensions": {} if extensions is None else extensions})


def read_envelope(source, *, supported_features=(), known_semantics=(), expected_semantics=None):
    """Strictly decode and preserve the entire envelope, including unknown extensions.

    A caller supplies its supported features and exact admitted semantic pins.
    The payload must separately pass the existing native schema/access readers.
    """
    if type(source) not in (str, bytes):
        raise ContractError("E_SCHEMA_INVALID")
    try:
        if len(source) > MAX_ENVELOPE_BYTES:
            raise ContractError("E_BUDGET_EXHAUSTED")
        size = len(source.encode("utf-8", "surrogatepass")) if type(source) is str else len(source)
        if size > MAX_ENVELOPE_BYTES:
            raise ContractError("E_BUDGET_EXHAUSTED")
        value = _envelope(loads(source))
        features = _list(supported_features, _FEATURE)
        semantics = _list(known_semantics, _DIGEST)
        expected = None if expected_semantics is None else _list(expected_semantics, _DIGEST)
    except ContractError:
        raise
    except (CanonicalError, RecursionError):
        raise ContractError("E_SCHEMA_INVALID") from None
    if not set(value["required_features"]) <= set(features) or not set(value["required_semantics"]) <= set(semantics):
        raise ContractError("E_VERSION_UNSUPPORTED")
    if expected is not None and set(expected) != set(value["required_semantics"]):
        raise ContractError("E_VERSION_UNSUPPORTED")
    return value


def migration_manifest():
    """Describe the existing trusted SQLite migration registry, without executing it.

    Committed upgrades are one-way; rollback means restoring a compatible prior
    backup before new writes, never editing the migration ledger or dropping rows.
    """
    from .storage import migrations
    return {"schema_version": "1.0", "backend": "sqlite", "application_id": migrations.APPLICATION_ID,
        "target_version": migrations.SCHEMA_VERSION, "encoding": ENCODING_VERSION,
        "rollback": "restore_pre_upgrade_backup_before_new_writes",
        "steps": [{"from_version": step.version - 1, "to_version": step.version,
            "resource": step.name, "sha256": step.checksum} for step in migrations._registry()]}


def require_migration_manifest(value):
    """A supplied manifest cannot replace packaged SQL or authorize a downgrade."""
    try:
        same = canonical_bytes(value) == canonical_bytes(migration_manifest())
    except ContractError:
        raise
    except (CanonicalError, RecursionError):
        raise ContractError("E_SCHEMA_INVALID") from None
    if not same:
        raise ContractError("E_VERSION_UNSUPPORTED")
    return deepcopy(value)
