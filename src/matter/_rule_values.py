"""Private value helpers for detached, immutable evaluator contracts."""

from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .canonical import canonical_bytes, canonical_digest, loads, source_digest
from .contracts import ContractError, _FORMAT_CHECKER, schema_for
from .storage.base import _validate_fragment


class FrozenValue:
    """Canonical bytes internally; every public JSON value is a detached copy."""
    __slots__ = ("_encoded",)

    def _freeze(self, value):
        object.__setattr__(self, "_encoded", canonical_bytes(value))

    def __setattr__(self, name, value):
        raise AttributeError(type(self).__name__ + " is immutable.")

    @property
    def value(self):
        return loads(self._encoded)


def checked(value, *, required, optional=(), code="E_SCHEMA_INVALID"):
    try:
        canonical_bytes(value)
        valid = type(value) is dict and set(required) <= set(value) <= set(required) | set(optional)
    except (ValueError, TypeError, RecursionError):
        valid = False
    if not valid:
        raise ContractError(code)
    return deepcopy(value)


def fragment(value, name):
    return _validate_fragment(value, name)


def bounded(values, maximum, *, code="E_BUDGET_EXHAUSTED"):
    if not isinstance(values, (list, tuple)):
        raise ContractError("E_SCHEMA_INVALID")
    if len(values) > maximum:
        raise ContractError(code)
    return deepcopy(list(values))


def unique(values):
    keys = [canonical_bytes(value) for value in values]
    if len(keys) != len(set(keys)):
        raise ContractError("E_SCHEMA_INVALID", "Duplicate values are not permitted.")
    return values


def same(left, right):
    return canonical_bytes(left) == canonical_bytes(right)


@lru_cache(maxsize=16)
def runtime_schema(name):
    data = files("matter._schemas").joinpath(name + ".schema.json").read_bytes()
    schema = json.loads(data)
    Draft202012Validator.check_schema(schema)
    core = schema_for("record")
    registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
    ref = {"namespace": "matter", "id": name, "version": "1.0", "digest": source_digest(data)}
    return ref, Draft202012Validator(schema, registry=registry, format_checker=_FORMAT_CHECKER)


def domain(name, value):
    ref, validator = runtime_schema(name)
    canonical_bytes(value)
    if not validator.is_valid(value):
        raise ContractError("E_SCHEMA_INVALID")
    return {"schema": deepcopy(ref), "value": deepcopy(value)}


def descriptor(namespace, identity, version, value, kind):
    ref = {"namespace": namespace, "id": identity, "version": version,
           "digest": canonical_digest(value, kind)}
    return fragment(ref, "component_ref")


def preparation_reference():
    """Versioned declared semantics, not a claim of automatically hashing code."""
    definition = {"algorithm": "matter.rule-packet.v1", "order": "preserved",
        "sources": "current-exact-pins", "availability": "inclusive-known-cut",
        "citations": "admitted-locator-validation", "omissions": "explicit",
        "negative_dependencies": "registered-current", "controls": "fixed-host-token",
        "input_schema": runtime_schema("rule-evaluation-input")[0]}
    return descriptor("matter", "rule-packet-preparation", "1.0", definition,
                      "matter.rule-packet-preparation.v1")

