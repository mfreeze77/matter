"""Bounded, atomic registrations for explicitly scoped absence dependencies.

An arrival changes current usability; it does not rewrite the original
historical coverage proof or assert a proposition's truth. Supported intake
enumerates exact source-bucket registrations in its write transaction. These
are direct validity notices, not transitive invalidation or a background scan.
"""

from __future__ import annotations

from copy import deepcopy

from .candidate_sets import matches, read_dependency
from .canonical import canonical_bytes, canonical_digest
from .citations import _domain
from .contracts import validate_record
from .coverage import (
    _bounded, _classify, _invalid, _previous, _refs, _specification,
    coverage_ref, match_observation, read_coverage,
)
from .identity_dependencies import _identity, _lookup, _scoped, _sorted, _value
from .source_catalogs import catalog_observations, read_catalog, source_catalog_ref, source_key, source_watch_key
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .storage.base import STORAGE_NAMESPACE, _validate_fragment, _validate_projection
from .time import compare_times


NEGATIVE_NAMESPACE = "matter.negative_dependencies"
MAX_NEGATIVE_REGISTRATIONS = 4096

__all__ = [
    "NEGATIVE_NAMESPACE", "MAX_NEGATIVE_REGISTRATIONS", "negative_dependency_ref",
    "read_negative_dependency", "negative_status", "require_current_negative_dependency",
]


def negative_dependency_ref(scope_id, identifier):
    """Address a host's stable scoped watch ID, independent of future event IDs."""
    scope = _validate_fragment(scope_id, "identifier")
    identity = _validate_fragment(identifier, "identifier")
    return {"scope_id": scope, "namespace": NEGATIVE_NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "negative-" + canonical_digest({"scope_id": scope, "id": identity},
                                                  "matter.negative-dependency.v1")}


def _spec(watch):
    return _specification({key: watch[key] for key in ("query", "eligible_sources", "observed_interval")})


def _watches(scope, specification):
    return sorted(source_watch_key(scope, source) for source in specification["eligible_sources"])


def _target(scope, reference):
    ref = _scoped(scope, reference)
    if ref["record_type"] not in {"assessment", PROJECTION_TYPE}:
        raise StorageError("E_SCHEMA_INVALID", "A negative dependency must belong to an assessment or host derivative.")
    if ref["record_type"] == PROJECTION_TYPE and ref["namespace"].startswith("matter."):
        raise StorageError("E_SCOPE_FORBIDDEN", "Internal projections are not host absence results.")
    return ref


def _stored_registration(stored, scope):
    try:
        record = _validate_projection(stored)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid("The stored negative registration is malformed.") from None
    body = _value("negative-dependency", record["value"])
    watch = body["watch"]
    spec = _spec(watch)
    if (record["scope_id"] != scope or record["namespace"] != NEGATIVE_NAMESPACE
            or record["creation_receipt"]["scope_id"] != scope or body["scope_id"] != scope
            or watch["scope_id"] != scope or "assessed_as_of" not in watch
            or entity_ref(record) != negative_dependency_ref(scope, watch["id"])
            or record["watch_keys"] != _watches(scope, spec)
            or watch["eligible_sources"] != spec["eligible_sources"]
            or entity_ref(body["coverage_snapshot"]) != coverage_ref(scope, spec)
            or (body["status"] == "invalidated") != (body["invalidation"] is not None)):
        raise _invalid("The stored negative registration has an inconsistent scope or watch binding.")
    _target(scope, body["reference"])
    _scoped(scope, body["coverage_snapshot"], "projection_dependency")
    _scoped(scope, body["authority"], "receipt_dependency")
    if body["catalogs"] != _refs(scope, body["catalogs"], "projection_dependency"):
        raise _invalid()
    expected = [source_catalog_ref(scope, source) for source in spec["eligible_sources"]]
    if _sorted(entity_ref(item) for item in body["catalogs"]) != _sorted(expected):
        raise _invalid()
    for field in ("matches", "indeterminate"):
        if body[field] != _refs(scope, body[field], "observation_dependency"):
            raise _invalid()
    if set(map(canonical_bytes, body["matches"])) & set(map(canonical_bytes, body["indeterminate"])):
        raise _invalid()
    if body["status"] == "current" and (body["matches"] or body["indeterminate"]):
        raise _invalid()
    if body["status"] == "evidence_present" and not body["matches"]:
        raise _invalid()
    if body["status"] == "indeterminate" and (not body["indeterminate"] or body["matches"]):
        raise _invalid()
    if body["invalidation"] is not None:
        invalidation = body["invalidation"]
        _scoped(scope, invalidation["receipt"], "receipt_ref")
        field = "matches" if invalidation["eligibility"] == "matched" else "indeterminate"
        if invalidation["observation"] not in body[field]:
            raise _invalid()
    return record


def read_negative_dependency(view, scope_id, reference):
    """Verify the current registration and the receipt of any arrival change.

    Old coverage and target pins remain historical dependencies, so they are
    checked for current usability by ``negative_status`` rather than refreshed
    here. A stale target does not prevent unrelated intake from being recorded.
    """
    scope = _validate_fragment(scope_id, "identifier")
    fragment = "pinned_ref" if "revision" in reference or "digest" in reference else "entity_ref"
    ref = _scoped(scope, reference, fragment)
    stored = _lookup(view, entity_ref(ref))
    if stored is None:
        raise StorageError("E_NOT_FOUND")
    record = _stored_registration(stored, scope)
    if not matches(record, ref):
        raise StorageError("E_REVISION_CONFLICT")
    body = record["value"]["value"]
    if body["invalidation"] is not None:
        change = body["invalidation"]
        observation = read_dependency(view, scope, change["observation"])
        actual = match_observation(observation, _spec(body["watch"]))
        if actual is False or (actual is True) != (change["eligibility"] == "matched"):
            raise _invalid("An invalidation must retain its matching or indeterminate observation.")
        receipt = view.get(change["receipt"])
        # Reads remain outside structural catches: revision and storage failures
        # never turn into a successful no-match or an empty watch list.
        try:
            receipt = validate_record(receipt)
            if (entity_ref(receipt) != change["receipt"] or receipt["record_type"] != "receipt"
                    or receipt["namespace"] != STORAGE_NAMESPACE or receipt["creation_receipt"] != change["receipt"]
                    or receipt["body"]["stage"] != "operation" or receipt["provenance"]["origin"] != "system"):
                raise _invalid()
        except (ValueError, TypeError, KeyError, RecursionError):
            raise _invalid("The arrival's operation receipt is invalid.") from None
        details = _value("storage-receipt-details", receipt["body"]["details"])
        if (receipt["id"] != "command-" + details["command_digest"]
                or pin(record) not in details["writes"] or change["observation"] not in details["writes"]):
            raise _invalid("An arrival and its watch update must share one durable operation receipt.")
    return record


def _catalog_view(view, scope, specification):
    catalogs, records = [], {}
    for source in specification["eligible_sources"]:
        catalog = read_catalog(view, scope, source)
        if catalog is None:
            raise _invalid("A registered negative scope requires its declared source catalog.")
        catalogs.append(catalog)
        for record in catalog_observations(view, scope, catalog):
            records[_identity(record)] = record
    _bounded(list(records.values()))
    return catalogs, records


def inspect_registration(view, scope, body, policy, authority):
    selected = _scoped(scope, body["coverage"], "projection_dependency")
    coverage = read_coverage(view, scope, selected)
    snapshot = coverage["value"]["value"]
    if snapshot["adapter"] not in policy.definition["adapters"]:
        raise StorageError("E_POLICY_INVALID", "The coverage adapter is not admitted by this policy.")
    if compare_times(body["as_of"], snapshot["as_of"]) != 0:
        raise _invalid("A negative proof must retain its coverage's original knowledge boundary.")
    spec = snapshot["specification"]
    target = read_dependency(view, scope, _target(scope, body["reference"]))
    address = negative_dependency_ref(scope, body["id"])
    old = _previous(view, scope, address, body["previous"], read_negative_dependency)
    if old is not None and entity_ref(old["value"]["value"]["reference"]) != entity_ref(target):
        raise _invalid("A watch ID cannot be reassigned to another host derivative.")
    watch = {"id": body["id"], "scope_id": scope, **deepcopy(spec), "catalog": snapshot["catalog"],
             "coverage": snapshot["coverage"], "assessed_as_of": deepcopy(snapshot["as_of"])}
    for field in ("expires_at", "next_check_at"):
        if field in body:
            if compare_times(body[field], body["as_of"]) < 0:
                raise _invalid("A negative watch's time condition cannot precede its proof boundary.")
            watch[field] = deepcopy(body[field])
    _validate_fragment(watch, "negative_watch")
    if target["record_type"] == "assessment":
        manifest = target["body"]["dependency_manifest"]
        if not any(matches(coverage, reference) for reference in manifest["positive"]):
            raise _invalid("The assessment must retain the exact coverage snapshot in its positive dependencies.")
        if not any(canonical_bytes(watch) == canonical_bytes(item) for item in manifest["negative"]):
            raise _invalid("The assessment must retain this exact time-bounded negative scope.")
    for source in spec["eligible_sources"]:
        registrations = _source_registrations(view, scope, source)
        # Preparation retains every bucket member's current pin. Transactional
        # discovery refuses a newly added unpinned watch, so competing writers
        # cannot both consume the final slot. Refreshing an existing ID consumes
        # no additional slot; a newly joined source bucket must have capacity.
        occupies_slot = any(entity_ref(item) == address for item in registrations)
        if not occupies_slot and len(registrations) >= MAX_NEGATIVE_REGISTRATIONS:
            raise StorageError("E_BUDGET_EXHAUSTED", "The source bucket has reached its negative-registration bound.")
    catalogs, records = _catalog_view(view, scope, spec)
    original = {canonical_bytes(item) for item in snapshot["observations"]}
    if not original.issubset({canonical_bytes(pin(item)) for item in records.values()}):
        raise _invalid("The source catalog cannot omit observations retained by its coverage snapshot.")
    matched = list(snapshot["matches"])
    unknown = list(snapshot["indeterminate"])
    # The historical proof's cutoff is not a permanent arrival filter. An
    # observation admitted after the frozen catalog snapshot must reconsider
    # current use even if it reports a past event and is only available later.
    for record in records.values():
        if canonical_bytes(pin(record)) not in original:
            eligible = match_observation(record, spec)
            if eligible is True:
                matched.append(pin(record))
            elif eligible is None:
                unknown.append(pin(record))
    status = ("unusable_coverage" if snapshot["result"] == "unusable_coverage" else
              "evidence_present" if matched else "indeterminate" if unknown else "current")
    draft = {"scope_id": scope, "watch": watch, "reference": pin(target), "coverage_snapshot": pin(coverage),
             "catalogs": _sorted(pin(item) for item in catalogs), "status": status,
             "matches": _sorted(matched), "indeterminate": _sorted(unknown), "invalidation": None,
             "policy": policy.reference, "authority": deepcopy(authority)}
    return {"address": address, "previous": old, "draft": draft}


def commit_registration(tx, plan):
    draft = plan["draft"]
    stored = tx.put_projection(plan["address"], _domain("negative-dependency", draft),
                               watch_keys=_watches(tx.command["scope_id"], _spec(draft["watch"])))
    changes = [{"cause": "coverage_change", "before": [pin(plan["previous"])] if plan["previous"] else [],
                "after": [pin(stored)]}]
    return tx.success("registered", {"registration": pin(stored), "changes": changes})


def _source_registrations(view, scope, source):
    """Read the same checked, bounded source bucket for admission and arrival."""
    records = _bounded(view.watchers(source_watch_key(scope, source)), MAX_NEGATIVE_REGISTRATIONS)
    seen, verified = set(), []
    for stored in records:
        record = read_negative_dependency(view, scope, pin(stored))
        if (source not in record["value"]["value"]["watch"]["eligible_sources"]
                or canonical_bytes(record) != canonical_bytes(stored) or _identity(record) in seen):
            raise _invalid("The source bucket contains an inconsistent negative registration.")
        seen.add(_identity(record))
        verified.append(record)
    return _sorted(verified)


def collect_arrival_watches(view, scope_id, observation):
    """Collect every registration in this exact source bucket, including firsts.

    A prepare call collects their current pins. The same lookup under the
    transaction refuses an unpinned newly registered watch. Unknown future
    observation IDs are irrelevant because the bucket is source-scoped.
    """
    scope = _validate_fragment(scope_id, "identifier")
    if observation["scope_id"] != scope:
        raise StorageError("E_SCOPE_FORBIDDEN")
    source = source_key(observation["body"]["source_identity"]["namespace"])
    return _source_registrations(view, scope, source)


def record_arrival(tx, observation):
    """Atomically stale every current potentially matching watch exactly once.

    This is called only after a genuinely new observation is inserted. Exact
    retries and duplicate deliveries return before this hook. A known future
    availability or unknown eligibility conservatively requires reconsideration;
    the notice does not claim that an earlier historical absence was false.
    """
    scope = tx.command["scope_id"]
    changes = []
    for registration in collect_arrival_watches(tx, scope, observation):
        body = deepcopy(registration["value"]["value"])
        if body["status"] != "current":
            continue
        eligible = match_observation(observation, _spec(body["watch"]))
        if eligible is False:
            continue
        field = "matches" if eligible is True else "indeterminate"
        body[field] = _sorted([*body[field], pin(observation)])
        body["status"] = "invalidated"
        body["invalidation"] = {"observation": pin(observation), "receipt": tx.receipt_ref,
                                "eligibility": "matched" if eligible is True else "indeterminate"}
        stored = tx.put_projection(entity_ref(registration), _domain("negative-dependency", body),
                                   watch_keys=_watches(scope, _spec(body["watch"])))
        changes.append({"cause": "negative_scope_arrival", "before": [pin(registration)], "after": [pin(stored)]})
    return changes


def _usable(view, scope, record, as_of):
    body = record["value"]["value"]
    watch = body["watch"]
    if compare_times(as_of, watch["assessed_as_of"]) < 0:
        raise _invalid("A current-use check cannot predate the original proof; select a historical snapshot instead.")
    if body["status"] != "current":
        return body["status"]
    if "expires_at" in watch and compare_times(as_of, watch["expires_at"]) >= 0:
        return "expired"
    if "next_check_at" in watch and compare_times(as_of, watch["next_check_at"]) >= 0:
        return "review_due"
    target = _lookup(view, entity_ref(body["reference"]))
    coverage = _lookup(view, entity_ref(body["coverage_snapshot"]))
    if (target is None or coverage is None or not matches(target, body["reference"])
            or not matches(coverage, body["coverage_snapshot"])):
        return "dependency_stale"
    coverage = read_coverage(view, scope, body["coverage_snapshot"])
    snapshot = coverage["value"]["value"]
    if (watch["catalog"] != snapshot["catalog"] or watch["coverage"] != snapshot["coverage"]
            or watch["assessed_as_of"] != snapshot["as_of"]
            or canonical_bytes(_spec(watch)) != canonical_bytes(snapshot["specification"])):
        raise _invalid("A negative watch must retain the coverage declaration it actually used.")
    if snapshot["result"] != "adequate_empty":
        raise _invalid("Only adequate empty coverage can admit current absence use.")
    catalogs, records = _catalog_view(view, scope, _spec(watch))
    if (any(item["value"]["value"]["baseline"] is None for item in catalogs)
            or not set(map(canonical_bytes, snapshot["observations"])).issubset(
                {canonical_bytes(pin(item)) for item in records.values()})):
        raise _invalid("The original coverage population is no longer represented by its source catalogs.")
    matched, unknown, _ = _classify(records.values(), _spec(watch), as_of)
    if matched:
        return "evidence_present"
    if unknown:
        return "indeterminate"
    return "current"


def negative_status(view, scope_id, reference, *, as_of):
    """Return current usability at an explicit clock value without any writes.

    Expiry and next-check yield expired/review_due. They do not invent a source
    event, advance collection completeness, resolve a matter, or execute work.
    Unrelated catalog arrivals leave a narrow watch usable. Future-known
    observations already in the catalog are reevaluated at the requested cut.
    """
    scope = _validate_fragment(scope_id, "identifier")
    boundary = _validate_fragment(as_of, "known_time")
    fragment = "pinned_ref" if "revision" in reference or "digest" in reference else "entity_ref"
    ref = _scoped(scope, reference, fragment)
    current = _lookup(view, entity_ref(ref))
    if current is None:
        raise StorageError("E_NOT_FOUND")
    record = read_negative_dependency(view, scope, pin(current))
    if not matches(record, ref):
        return "dependency_stale"
    return _usable(view, scope, record, boundary)


def require_current_negative_dependency(view, scope_id, reference, *, as_of):
    """Return the current usable registration or explicitly refuse its use."""
    status = negative_status(view, scope_id, reference, as_of=as_of)
    if status != "current":
        raise StorageError("E_DEPENDENCY_STALE", "The registered absence is not currently usable: " + status + ".")
    return read_negative_dependency(view, scope_id, reference)
