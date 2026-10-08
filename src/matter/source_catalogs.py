"""Bounded, durable catalogs of exact observations from one source namespace.

New intake appends to the catalog in the observation's transaction. An empty
or newly created catalog does not certify that preexisting observations were
inventoried: its baseline remains null until an authorized host explicitly
initializes it. Initialization is an attestation, not a database scan or proof
of source completeness. Coverage policy and admission belong to the host.

Catalogs retain all supplied immutable observations, including corrections.
They neither apply supersession nor infer absence, publication or availability.
Append-only admission revisions reconstruct an earlier catalog population from
the current projection without reading transaction history. A later baseline
attestation never retroactively certifies an earlier catalog revision.
Watch keys address a source bucket; predicates still decide which new arrivals
affect a particular negative dependency.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .canonical import canonical_bytes, canonical_digest
from .citations import _contract, _domain
from .contracts import validate_record
from .storage import PROJECTION_TYPE, Snapshot, StorageError, Transaction, entity_ref, pin
from .storage.base import _validate_fragment, _validate_projection


CATALOG_NAMESPACE = "matter.source_catalogs"
SOURCE_SELECTOR_NAMESPACE = "matter.source_namespace"
MAX_CATALOG_OBSERVATIONS = 4096

__all__ = [
    "CATALOG_NAMESPACE", "SOURCE_SELECTOR_NAMESPACE", "MAX_CATALOG_OBSERVATIONS",
    "source_key", "source_catalog_ref", "source_watch_key", "catalog_schema_ref",
    "read_catalog", "catalog_observations", "catalog_population", "catalog_snapshot", "append_observation", "ensure_catalog",
    "initialize_catalog",
]


def _invalid() -> StorageError:
    return StorageError("E_EVIDENCE_INVALID", "The declared source catalog evidence is invalid.")


def _damaged() -> StorageError:
    return StorageError("E_STORAGE_UNAVAILABLE", "The source catalog could not be verified.")


def _identity(reference):
    return reference["scope_id"], reference["namespace"], reference["id"]


def source_key(namespace: str) -> dict[str, str]:
    """Select an exact adapter-owned source namespace without normalization."""
    return {"namespace": SOURCE_SELECTOR_NAMESPACE, "value": _validate_fragment(namespace, "namespace")}


def _source(source):
    value = _validate_fragment(source, "identity_key")
    if value["namespace"] != SOURCE_SELECTOR_NAMESPACE:
        raise StorageError("E_SCHEMA_INVALID", "Only explicit source-namespace selectors are supported.")
    return source_key(value["value"])


def _address(scope_id, source):
    return {"scope_id": _validate_fragment(scope_id, "identifier"), "source": _source(source)}


def source_catalog_ref(scope_id: str, source: dict[str, Any]) -> dict[str, Any]:
    """Address a source bucket using structured scope and exact selector bytes."""
    address = _address(scope_id, source)
    return {
        "scope_id": address["scope_id"], "namespace": CATALOG_NAMESPACE,
        "record_type": PROJECTION_TYPE,
        "id": "source-" + canonical_digest(address, "matter.source-catalog.v1"),
    }


def source_watch_key(scope_id: str, source: dict[str, Any]) -> str:
    """Return the stable bucket key used by separately registered watches."""
    return "source-" + canonical_digest(_address(scope_id, source), "matter.source-watch.v1")


def catalog_schema_ref() -> dict[str, str]:
    return deepcopy(_contract("source-catalog")[0])


def _references(scope_id, references):
    if type(references) is not list:
        raise StorageError("E_SCHEMA_INVALID")
    if len(references) > MAX_CATALOG_OBSERVATIONS:
        raise StorageError("E_BUDGET_EXHAUSTED", "The source catalog exceeds its supported observation bound.")
    seen = set()
    result = []
    for raw in references:
        reference = _validate_fragment(raw, "observation_dependency")
        if reference["scope_id"] != scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        identity = _identity(reference)
        if identity in seen:
            raise _invalid()
        seen.add(identity)
        result.append(reference)
    return sorted(result, key=canonical_bytes)


def _checked_catalog(stored, scope_id, source):
    # Resource loading errors remain distinct from malformed stored content.
    descriptor, validator = _contract("source-catalog")
    expected_ref = source_catalog_ref(scope_id, source)
    try:
        catalog = _validate_projection(stored)
        value = catalog["value"]
        body = value["value"]
        if (
            entity_ref(catalog) != expected_ref or catalog["watch_keys"]
            or catalog["creation_receipt"]["scope_id"] != scope_id
            or value["schema"] != descriptor or not validator.is_valid(body)
            or body["scope_id"] != scope_id or body["source"] != source
            or body["observations"] != _references(scope_id, body["observations"])
            or body["admissions"] != sorted(body["admissions"], key=canonical_bytes)
            or body["observations"] != _references(scope_id, [entry["observation"] for entry in body["admissions"]])
            or any(entry["catalog_revision"] > catalog["revision"] for entry in body["admissions"])
            or (body["baseline"] is not None and (
                body["baseline"]["authority"]["scope_id"] != scope_id
                or body["baseline"]["catalog_revision"] > catalog["revision"]
            ))
        ):
            raise _damaged()
        return catalog
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise _damaged() from None


def read_catalog(
    view: Snapshot | Transaction, scope_id: str, source: dict[str, Any],
) -> dict[str, Any] | None:
    """Read the current verified catalog; absence never certifies a baseline.

    Identity lookup detects an occupant of the wrong kind. Actual backend and
    transaction revision errors propagate; malformed stored data is a storage
    refusal, never an empty catalog. Observation records are verified separately
    by ``catalog_observations`` when a caller consumes the catalog's evidence.
    """
    address = _address(scope_id, source)
    reference = source_catalog_ref(address["scope_id"], address["source"])
    try:
        stored = view.lookup_identity(reference)
    except StorageError as error:
        if error.code == "E_NOT_FOUND":
            return None
        raise
    return _checked_catalog(stored, address["scope_id"], address["source"])


def catalog_population(catalog: dict[str, Any], revision: int) -> dict[str, Any]:
    """Derive a selected revision's admitted population from a current catalog.

    All catalog fields and admission bindings are verified first. This pure
    function does not resolve observation bytes or bypass the storage port's
    current-read guards. Callers retain the supplied catalog's checked read pin.
    A baseline declared later cannot certify the selected earlier population.
    """
    selected_revision = _validate_fragment(revision, "revision")
    try:
        scope = _validate_fragment(catalog["scope_id"], "identifier")
        source = _source(catalog["value"]["value"]["source"])
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _damaged() from None
    checked = _checked_catalog(catalog, scope, source)
    if selected_revision > checked["revision"]:
        raise StorageError("E_REVISION_CONFLICT", "The selected catalog revision is not present in this snapshot.")
    body = checked["value"]["value"]
    return {
        "observations": sorted([
            deepcopy(entry["observation"]) for entry in body["admissions"]
            if entry["catalog_revision"] <= selected_revision
        ], key=canonical_bytes),
        "history_complete": body["baseline"] is not None and body["baseline"]["catalog_revision"] <= selected_revision,
    }


def catalog_snapshot(catalog: dict[str, Any], revision: int) -> dict[str, Any]:
    """Reconstruct the exact earlier projection using append-only admissions.

    Creation identity, receipt, descriptor and empty watch set are immutable.
    Later observations and baseline attestations are excluded at the selected
    revision, allowing callers to verify a historical snapshot digest through a
    guarded current read without invoking a transaction history API.
    """
    selected_revision = _validate_fragment(revision, "revision")
    try:
        scope = _validate_fragment(catalog["scope_id"], "identifier")
        source = _source(catalog["value"]["value"]["source"])
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _damaged() from None
    snapshot = _checked_catalog(catalog, scope, source)
    if selected_revision > snapshot["revision"]:
        raise StorageError("E_REVISION_CONFLICT", "The selected catalog revision is not present in this snapshot.")
    snapshot["revision"] = selected_revision
    body = snapshot["value"]["value"]
    body["admissions"] = [entry for entry in body["admissions"] if entry["catalog_revision"] <= selected_revision]
    body["observations"] = sorted([deepcopy(entry["observation"]) for entry in body["admissions"]], key=canonical_bytes)
    if body["baseline"] is not None and body["baseline"]["catalog_revision"] > selected_revision:
        body["baseline"] = None
    return snapshot


def _read_exact(view, scope_id, reference, *, stored=False):
    # Port errors must not be swallowed by structural ValueError catches.
    try:
        value = view.get(deepcopy(reference))
    except StorageError as error:
        if error.code == "E_NOT_FOUND" and stored:
            raise _damaged() from None
        raise
    try:
        record = validate_record(value)
        if pin(record) != reference or record["creation_receipt"]["scope_id"] != scope_id:
            raise ValueError
        return record
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise (_damaged() if stored else _invalid()) from None


def _observation(view, scope_id, source, reference, *, stored=False):
    record = _read_exact(view, scope_id, reference, stored=stored)
    if record["record_type"] != "observation" or record["body"]["source_identity"]["namespace"] != source["value"]:
        raise (_damaged() if stored else _invalid())
    return record


def catalog_observations(
    view: Snapshot | Transaction, scope_id: str, catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve every exact immutable pin in a supplied verified snapshot.

    A historical catalog is allowed when deliberately supplied. Callers needing
    its current revision must obtain it with ``read_catalog`` in their guarded
    view first. Missing records never become a successful partial inventory.
    """
    scope = _validate_fragment(scope_id, "identifier")
    try:
        source = _source(catalog["value"]["value"]["source"])
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _damaged() from None
    checked = _checked_catalog(catalog, scope, source)
    return [
        _observation(view, scope, source, reference, stored=True)
        for reference in checked["value"]["value"]["observations"]
    ]


def _write(tx, body):
    return tx.put_projection(source_catalog_ref(body["scope_id"], body["source"]), _domain("source-catalog", body))


def ensure_catalog(tx: Transaction, source: dict[str, Any]) -> dict[str, Any]:
    """Create an uninitialized empty bucket only when no catalog exists."""
    scope, selected = tx.command["scope_id"], _source(source)
    existing = read_catalog(tx, scope, selected)
    return existing if existing is not None else _write(tx, {
        "scope_id": scope, "source": selected, "observations": [], "admissions": [], "baseline": None,
    })


def append_observation(tx: Transaction, observation: dict[str, Any]) -> dict[str, Any]:
    """Append an actual fresh observation atomically with intake, writing once.

    The existing catalog's immutable pins are preserved without rereading all
    their records. Consumers verify those records when using their evidence.
    Repeating the exact observation is harmless and does not revise the bucket.
    """
    record = validate_record(observation)
    scope = tx.command["scope_id"]
    if record["scope_id"] != scope:
        raise StorageError("E_SCOPE_FORBIDDEN")
    if record["record_type"] != "observation":
        raise _invalid()
    selected = source_key(record["body"]["source_identity"]["namespace"])
    reference = pin(record)
    _observation(tx, scope, selected, reference)
    existing = read_catalog(tx, scope, selected)
    body = deepcopy(existing["value"]["value"]) if existing is not None else {
        "scope_id": scope, "source": selected, "observations": [], "admissions": [], "baseline": None,
    }
    for prior in body["observations"]:
        if _identity(prior) == _identity(reference):
            if prior != reference:
                raise _damaged()
            return existing
    body["observations"] = _references(scope, [*body["observations"], reference])
    body["admissions"] = sorted([
        *body["admissions"],
        {"observation": reference, "catalog_revision": existing["revision"] + 1 if existing else 1},
    ], key=canonical_bytes)
    return _write(tx, body)


def initialize_catalog(
    tx: Transaction, source: dict[str, Any], observations: list[dict[str, Any]], *,
    adapter: dict[str, Any], authority: dict[str, Any], declared_at: dict[str, Any],
) -> dict[str, Any]:
    """Attest a legacy baseline once, preserving all already captured intake.

    The host supplies exact legacy observation pins and authorizes the adapter
    and authority. This helper verifies the supplied records; it cannot prove
    that the host's list covers every historical source observation.
    """
    scope, selected = tx.command["scope_id"], _source(source)
    supplied = _references(scope, observations)
    baseline = {
        "adapter": _validate_fragment(adapter, "component_ref"),
        "authority": _validate_fragment(authority, "receipt_dependency"),
        "declared_at": _validate_fragment(declared_at, "known_time"),
    }
    if baseline["authority"]["scope_id"] != scope:
        raise StorageError("E_SCOPE_FORBIDDEN")
    existing = read_catalog(tx, scope, selected)
    if existing is not None and existing["value"]["value"]["baseline"] is not None:
        raise StorageError("E_POLICY_INVALID", "The source baseline has already been initialized.")
    next_revision = existing["revision"] + 1 if existing else 1
    baseline["catalog_revision"] = next_revision
    _read_exact(tx, scope, baseline["authority"])
    merged = {_identity(ref): ref for ref in existing["value"]["value"]["observations"]} if existing else {}
    admissions = deepcopy(existing["value"]["value"]["admissions"]) if existing else []
    for reference in supplied:
        prior = merged.get(_identity(reference))
        if prior is not None and prior != reference:
            raise _invalid()
        if prior is None:
            admissions.append({"observation": reference, "catalog_revision": next_revision})
        merged[_identity(reference)] = reference
    references = _references(scope, list(merged.values()))
    for reference in references:
        _observation(tx, scope, selected, reference, stored=reference not in supplied)
    return _write(tx, {
        "scope_id": scope, "source": selected, "observations": references,
        "admissions": sorted(admissions, key=canonical_bytes), "baseline": baseline,
    })
