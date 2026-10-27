"""MAT-016 scoped dependency declarations and commit/dispatch freshness gates.

Registration is a trusted host transaction operation. A manifest never grants
source access, authenticates a control, or authorizes external delivery.
"""

from __future__ import annotations

from copy import deepcopy

from ._rule_values import FrozenValue, bounded, domain, fragment, unique
from .canonical import canonical_bytes, canonical_digest, loads
from .candidate_sets import matches, require_current_candidates, _snapshot_references
from .controls import _checked as checked_control
from .coverage import _specification, match_observation
from .identity_dependencies import _value
from .negative_dependencies import require_current_negative_dependency
from .source_catalogs import catalog_observations, read_catalog, source_catalog_ref
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .storage.base import _validate_projection
from .time import compare_times, known_time_key


NAMESPACE = "matter.dependencies"
MAX_DEPENDENCIES = 4096
MAX_REASONS = 128
MAX_LIVE_TEMPORAL = 512
_TIME_BITS = 77


def _fail(detail="The scoped dependency registration is invalid.", code="E_EVIDENCE_INVALID"):
    raise StorageError(code, detail)


def _identity(value):
    return tuple(value[key] for key in ("scope_id", "namespace", "id"))


def _scoped(scope, value, name="pinned_ref"):
    ref = fragment(value, name)
    if ref["scope_id"] != scope:
        _fail(code="E_SCOPE_FORBIDDEN")
    return ref


def registration_ref(target):
    ref = entity_ref(target)
    return {"scope_id": ref["scope_id"], "namespace": NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "dependency-" + canonical_digest(list(_identity(ref)), "matter.dependency-registration.v1")}


def scope_fence_ref(scope_id):
    return {"scope_id": fragment(scope_id, "identifier"), "namespace": NAMESPACE,
            "record_type": PROJECTION_TYPE, "id": "scope-fence"}


def _scope_fence(view, scope):
    record = _lookup(view, scope_fence_ref(scope))
    if record is not None:
        _value("dependency-scope-fence", record["value"])
    return record


def object_watch(reference):
    return "dependency-object-" + canonical_digest(list(_identity(reference)), "matter.dependency-object-watch.v1")


def query_watch(scope, source):
    return "dependency-query-" + canonical_digest({"scope": scope, "source": source}, "matter.dependency-query-watch.v1")


def time_watch(scope, scope_fence=None):
    """Capacity-only cohort: live temporal registrations, never a hook scan."""
    return "dependency-time-" + canonical_digest({"scope": scope, "scope_fence": scope_fence}, "matter.dependency-time-watch.v1")


def _time_bits(instant):
    # Fixed-width UTC decimal order matches chronological order, including
    # pre-1970/minimum dates. Preserve all nine fractional digits without a
    # timestamp float or platform datetime conversion. 23 decimal digits fit
    # in 77 bits for every supported four-digit Gregorian year.
    main, fraction = known_time_key(instant)
    digits = "".join(character for character in main if character.isdigit()) + fraction
    return format(int(digits), f"0{_TIME_BITS}b")


def _time_prefix_watch(scope, prefix, scope_fence):
    return "dependency-time-prefix-" + canonical_digest({"scope": scope, "scope_fence": scope_fence}, "matter.dependency-time-prefix-scope.v1") + "-" + prefix


def temporal_deadline(conditions):
    values = [condition["next_check_at"] for condition in conditions]
    values.extend(condition["expires_at"] for condition in conditions if condition["expires_at"]["state"] == "known")
    return min(values, key=known_time_key)


def temporal_watch_keys(scope, conditions, scope_fence=None):
    bits = _time_bits(temporal_deadline(conditions))
    return [_time_prefix_watch(scope, bits[:length], scope_fence) for length in range(1, _TIME_BITS + 1)]


def due_time_watch_keys(scope, now, scope_fence=None):
    """Disjoint exact-key prefix cover of the inclusive interval [0, now].

    A due registration belongs to exactly one returned prefix. Future
    registrations share none, so their rows/payloads are never loaded.
    """
    bits = _time_bits(now)
    return [_time_prefix_watch(scope, bits[:index] + "0", scope_fence) for index, bit in enumerate(bits) if bit == "1"] + [_time_prefix_watch(scope, bits, scope_fence)]


def _lookup(view, reference):
    try:
        return view.lookup_identity(entity_ref(reference))
    except StorageError as error:
        if error.code != "E_NOT_FOUND":
            raise
        return None


def _current(view, scope, reference):
    ref = _scoped(scope, reference)
    record = view.get(entity_ref(ref))
    if not matches(record, ref):
        _fail("A selected dependency snapshot is no longer current.", "E_DEPENDENCY_STALE")
    return record


class _Reads:
    def __init__(self, view, scope):
        self.view, self.scope, self.records = view, scope, {}
        self.operations = 0

    def tick(self):
        self.operations += 1
        if self.operations > MAX_DEPENDENCIES * 8:
            _fail(code="E_BUDGET_EXHAUSTED")

    def remember(self, record):
        reference = _scoped(self.scope, pin(record))
        self.records[_identity(reference)] = reference
        if len(self.records) > MAX_DEPENDENCIES:
            _fail(code="E_BUDGET_EXHAUSTED")
        return deepcopy(record)

    def get(self, reference):
        self.tick()
        _scoped(self.scope, reference, "pinned_ref" if "digest" in reference or "revision" in reference else "entity_ref")
        return self.remember(self.view.get(reference))

    def lookup_identity(self, reference):
        self.tick()
        _scoped(self.scope, reference, "entity_ref")
        return self.remember(self.view.lookup_identity(reference))

    def watchers(self, key):
        self.tick()
        return [self.remember(item) for item in self.view.watchers(key)]


class DependencyManifest(FrozenValue):
    __slots__ = ("_reads",)

    def __init__(self, value, reads, *, _captured=False):
        if not _captured:
            _fail("Use capture_dependencies to bind current dependency snapshots.", "E_POLICY_INVALID")
        self._freeze(value)
        object.__setattr__(self, "_reads", canonical_bytes(reads))

    @property
    def read_pins(self):
        """Transaction proof reads, including query baselines, not semantic edges."""
        return loads(self._reads)

    @property
    def digest(self):
        return canonical_digest(self.value, "matter.dependency-manifest.v1")


def _pins(scope, values):
    refs = [_scoped(scope, item) for item in bounded(values, MAX_DEPENDENCIES)]
    if len({_identity(ref) for ref in refs}) != len(refs):
        _fail("A dependency identity must be declared only once.", "E_SCHEMA_INVALID")
    return sorted(refs, key=canonical_bytes)


def _conditions(values):
    conditions = unique([fragment(item, "time_condition") for item in bounded(values, 128)])
    return sorted(conditions, key=canonical_bytes)


def capture_dependencies(view, *, scope_id, as_of, positive=(), contexts=(), candidate_sets=(),
                         negative_registrations=(), queries=(), time_conditions=(), control_token=None, controls=None):
    """Capture semantic dependencies separately from historical query proof reads.

    Query baselines use the existing typed predicate and source catalogs. A
    later matching/indeterminate observation invalidates the result even when
    its identity did not exist at capture. Nonmatching arrivals do not.
    """
    scope, now = fragment(scope_id, "identifier"), fragment(as_of, "known_time")
    reads = _Reads(view, scope)
    fence = _scope_fence(reads, scope)
    value = {"scope_id": scope, "positive": _pins(scope, positive), "contexts": _pins(scope, contexts),
             "candidate_sets": _pins(scope, candidate_sets), "negative_registrations": _pins(scope, negative_registrations),
             "queries": [], "time_conditions": _conditions(time_conditions), "control_token": None,
             "scope_fence": None if fence is None else pin(fence), "read_access": []}
    for reference in [*value["positive"], *value["contexts"]]:
        _current(reads, scope, reference)
    for reference in value["candidate_sets"]:
        catalog = require_current_candidates(reads, scope, reference)
        considered = _snapshot_references(catalog["value"]["value"])
        expanded = {_identity(ref): ref for ref in [*value["positive"], *considered]}
        if any(ref != expanded[_identity(ref)] for ref in value["positive"]):
            _fail("Candidate dependencies conflict with another semantic snapshot.", "E_DEPENDENCY_STALE")
        value["positive"] = sorted(expanded.values(), key=canonical_bytes)
    for reference in value["negative_registrations"]:
        require_current_negative_dependency(reads, scope, reference, as_of=now)
    for raw in bounded(queries, 32):
        specification = _specification(raw)
        seen, catalogs = [], []
        for source in specification["eligible_sources"]:
            catalog = read_catalog(reads, scope, source)
            catalogs.append({"source": source, "pin": None if catalog is None else pin(catalog)})
            if catalog is not None:
                seen.extend(pin(record) for record in catalog_observations(reads, scope, catalog))
        value["queries"].append({"specification": specification,
                                  "catalogs": catalogs, "seen": sorted(unique(seen), key=canonical_bytes)})
    value["queries"] = sorted(unique(value["queries"]), key=canonical_bytes)
    if control_token is not None:
        token = checked_control("control-token", control_token)
        if token["scope_id"] != scope:
            _fail(code="E_SCOPE_FORBIDDEN")
        if controls is None:
            _fail("An original control context requires its trusted ControlService.", "E_POLICY_INVALID")
        controls.require_current(reads, token, capability=token["capability"], targets=token["targets"], as_of=now)
        value["control_token"] = token
        for reference in [*value["positive"], *value["contexts"]]:
            # Registered derivatives retain their source guards transitively;
            # their newly created identities are not additional source grants.
            # Receipts/controls are bookkeeping, as in command_targets.
            if (reference["record_type"] not in {PROJECTION_TYPE, "receipt", "control"}
                    and not reference["namespace"].startswith("matter.controls")
                    and _lookup(reads, registration_ref(reference)) is None):
                access = controls._view(reads, actor=token["actor"], authority=entity_ref(token["authority"]),
                                        capability="read", targets=[entity_ref(reference)], now=now)
                value["read_access"].append({"reference": reference, "fences": access["fences"]})
    _time_current(value, now)
    for name in ("positive", "contexts", "candidate_sets", "negative_registrations"):
        for reference in value[name]:
            parent = _lookup(reads, registration_ref(reference))
            if parent is not None:
                require_current_dependency(reads, pin(parent), as_of=now, controls=controls)
    if value["time_conditions"]:
        # Admission consults this bounded live cohort under the write lock.
        # Retain its current rows as transaction proof reads, not as semantic
        # dependency edges; an unrelated future timer must not invalidate work.
        for record in reads.watchers(time_watch(scope, value["scope_fence"])):
            read_registration(reads, pin(record))
    if len(canonical_bytes(value)) > 2_097_152:
        _fail(code="E_BUDGET_EXHAUSTED")
    return DependencyManifest(value, sorted(reads.records.values(), key=canonical_bytes), _captured=True)


def watch_keys(manifest, target, status="current"):
    result = {object_watch(ref) for name in ("positive", "contexts", "candidate_sets", "negative_registrations") for ref in manifest[name]}
    result.add(object_watch(target))
    for query in manifest["queries"]:
        result.update(query_watch(manifest["scope_id"], source) for source in query["specification"]["eligible_sources"])
    if status == "current" and manifest["time_conditions"]:
        result.add(time_watch(manifest["scope_id"], manifest["scope_fence"]))
        result.update(temporal_watch_keys(manifest["scope_id"], manifest["time_conditions"], manifest["scope_fence"]))
    token = manifest["control_token"]
    if token is not None:
        result.update(object_watch(item["reference"]) for item in token["fences"])
    for access in manifest["read_access"]:
        result.update(object_watch(item["reference"]) for item in access["fences"])
    return sorted(result)


def read_registration(view, reference):
    ref = fragment(reference, "pinned_ref" if "revision" in reference or "digest" in reference else "entity_ref")
    record = _validate_projection(view.get(entity_ref(ref)))
    body = _value("dependency-registration", record["value"])
    if (record["namespace"] != NAMESPACE or body["scope_id"] != ref["scope_id"] or
            entity_ref(record) != registration_ref(body["target"]) or record["watch_keys"] != watch_keys(body["manifest"], body["target"], body["status"]) or
            body["manifest"]["scope_id"] != body["scope_id"] or body["target"]["scope_id"] != body["scope_id"] or
            (body["status"] == "current") == bool(body["recompute_pending"])):
        _fail()
    if not matches(record, ref):
        _fail("The selected dependency registration is historical.", "E_DEPENDENCY_STALE")
    for name in ("positive", "contexts", "candidate_sets", "negative_registrations"):
        _pins(body["scope_id"], body["manifest"][name])
    for query in body["manifest"]["queries"]:
        specification = _specification(query["specification"])
        _pins(body["scope_id"], query["seen"])
        if [entry["source"] for entry in query["catalogs"]] != specification["eligible_sources"]:
            _fail()
        for entry in query["catalogs"]:
            if entry["pin"] is not None:
                _scoped(body["scope_id"], entry["pin"], "projection_dependency")
                if entity_ref(entry["pin"]) != source_catalog_ref(body["scope_id"], entry["source"]):
                    _fail()
    _conditions(body["manifest"]["time_conditions"])
    token = body["manifest"]["control_token"]
    if token is not None:
        checked_control("control-token", token)
        if token["scope_id"] != body["scope_id"]:
            _fail(code="E_SCOPE_FORBIDDEN")
    elif body["manifest"]["read_access"]:
        _fail("Read-access guards must retain their original host credentials.")
    if body["manifest"]["scope_fence"] is not None:
        reference = _scoped(body["scope_id"], body["manifest"]["scope_fence"], "projection_dependency")
        if entity_ref(reference) != scope_fence_ref(body["scope_id"]):
            _fail()
    for access in body["manifest"]["read_access"]:
        _scoped(body["scope_id"], access["reference"])
        for fence in access["fences"]:
            _scoped(body["scope_id"], fence["reference"], "entity_ref")
            if fence["pin"] is not None:
                _scoped(body["scope_id"], fence["pin"], "projection_dependency")
                if entity_ref(fence["pin"]) != fence["reference"]:
                    _fail()
    return record


def _time_current(manifest, now):
    for condition in manifest["time_conditions"]:
        if compare_times(now, condition["next_check_at"]) >= 0 or (condition["expires_at"]["state"] == "known" and compare_times(now, condition["expires_at"]) >= 0):
            _fail("A dependency is due or expired at the actual freshness gate.", "E_DEPENDENCY_STALE")


def _query_current(view, manifest):
    scope = manifest["scope_id"]
    for query in manifest["queries"]:
        seen = set(map(canonical_bytes, query["seen"]))
        for source in query["specification"]["eligible_sources"]:
            catalog = read_catalog(view, scope, source)
            if catalog is None:
                continue
            for record in catalog_observations(view, scope, catalog):
                if canonical_bytes(pin(record)) not in seen and match_observation(record, query["specification"]) is not False:
                    _fail("A new observation matches or leaves the watched query indeterminate.", "E_DEPENDENCY_STALE")


def _manifest_current(view, manifest, now, controls):
    scope = manifest["scope_id"]
    current_fence = _scope_fence(view, scope)
    if manifest["scope_fence"] != (None if current_fence is None else pin(current_fence)):
        _fail("A scoped invalidation fallback fenced this computation.", "E_DEPENDENCY_STALE")
    for reference in [*manifest["positive"], *manifest["contexts"]]:
        _current(view, scope, reference)
    for reference in manifest["candidate_sets"]:
        require_current_candidates(view, scope, reference)
    for reference in manifest["negative_registrations"]:
        require_current_negative_dependency(view, scope, reference, as_of=now)
    _query_current(view, manifest)
    _time_current(manifest, now)
    token = manifest["control_token"]
    if token is not None:
        if controls is None:
            _fail("Original control checks require the installed ControlService.", "E_POLICY_INVALID")
        controls.require_current(view, token, capability=token["capability"], targets=token["targets"], as_of=now)
        for access in manifest["read_access"]:
            actual = controls._view(view, actor=token["actor"], authority=entity_ref(token["authority"]),
                                    capability="read", targets=[entity_ref(access["reference"])], now=now)
            if actual["fences"] != access["fences"]:
                _fail("A required source used an earlier read-access state.", "E_DEPENDENCY_STALE")


def require_current_dependency(view, reference, *, as_of, controls=None):
    """Check a registered result and its transitive semantic closure, read-only."""
    now = fragment(as_of, "known_time")
    ref = fragment(reference, "pinned_ref" if "revision" in reference or "digest" in reference else "entity_ref")
    view = view if isinstance(view, _Reads) else _Reads(view, ref["scope_id"])
    first = read_registration(view, reference)
    queue, seen = [first], set()
    while queue:
        record = queue.pop()
        key = canonical_bytes(entity_ref(record))
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > MAX_DEPENDENCIES:
            _fail(code="E_BUDGET_EXHAUSTED")
        body = record["value"]["value"]
        if body["status"] != "current":
            _fail("The registered result is invalidated.", "E_DEPENDENCY_STALE")
        _current(view, body["scope_id"], body["target"])
        _manifest_current(view, body["manifest"], now, controls)
        for name in ("positive", "contexts", "candidate_sets", "negative_registrations"):
            for dependency in body["manifest"][name]:
                parent = _lookup(view, registration_ref(dependency))
                if parent is not None:
                    queue.append(read_registration(view, pin(parent)))
    return first


def capture_freshness(view, reference, *, as_of, controls=None):
    record = require_current_dependency(view, reference, as_of=as_of, controls=controls)
    body = record["value"]["value"]
    return domain("freshness-token", {"scope_id": body["scope_id"], "registration": pin(record),
        "target": body["target"], "epoch": body["epoch"], "manifest_digest": canonical_digest(body["manifest"], "matter.dependency-manifest.v1")})


def require_freshness(view, token, *, as_of, controls=None):
    body = _value("freshness-token", token)
    record = require_current_dependency(view, body["registration"], as_of=as_of, controls=controls)
    registration = record["value"]["value"]
    if body != {"scope_id": registration["scope_id"], "registration": pin(record), "target": registration["target"],
                "epoch": registration["epoch"], "manifest_digest": canonical_digest(registration["manifest"], "matter.dependency-manifest.v1")}:
        _fail("The freshness token does not bind this exact registered result.", "E_DEPENDENCY_STALE")
    return record


def recomputation_token(view, reference):
    """Fence further changes while recomputing an already-invalid result."""
    record = read_registration(view, reference)
    body = record["value"]["value"]
    return domain("freshness-token", {"scope_id": body["scope_id"], "registration": pin(record), "target": body["target"],
        "epoch": body["epoch"], "manifest_digest": canonical_digest(body["manifest"], "matter.dependency-manifest.v1")})


def register_dependency(tx, target, manifest, *, as_of, controls=None, previous=None):
    """Register one exact host-owned derivative under existing atomic writes.

    Recomputing an existing target requires its original recomputation token.
    A second correction revisions the old registration and fences publication.
    """
    if not isinstance(manifest, DependencyManifest):
        _fail("A captured dependency manifest is required.", "E_POLICY_INVALID")
    scope = tx.command["scope_id"]
    ref = _scoped(scope, target)
    if ref["record_type"] not in {"judgment", "assessment", PROJECTION_TYPE}:
        _fail("Only judgments, assessments and host derivatives can be registered.", "E_SCHEMA_INVALID")
    if ref["record_type"] == PROJECTION_TYPE and ref["namespace"].startswith("matter.") and ref["namespace"] not in {"matter.assessments", "matter.semantic_cache"}:
        _fail("Unrelated internal state is not a host derivative.", "E_SCOPE_FORBIDDEN")
    _current(tx, scope, ref)
    data = manifest.value
    if data["scope_id"] != scope:
        _fail(code="E_SCOPE_FORBIDDEN")
    _manifest_current(tx, data, fragment(as_of, "known_time"), controls)
    address = registration_ref(ref)
    old = _lookup(tx, address)
    if old is not None:
        old = read_registration(tx, pin(old))
        supplied = _value("freshness-token", previous) if previous is not None else None
        expected = recomputation_token(tx, pin(old))["value"]
        if supplied != expected:
            _fail("Recomputation must retain the exact previous registration token.", "E_DEPENDENCY_STALE")
    elif previous is not None:
        _fail("A previous registration token cannot name an absent target.", "E_DEPENDENCY_STALE")
    if data["time_conditions"]:
        # Existing ports expose exact watch cohorts. The maintained invariant
        # bounds future membership to 512. Due rows are already stale and may
        # await this transaction's hook sweep; do not charge them to admission.
        # During auto-publication the bounded system view permits old-due plus
        # new-future rows to coexist until the hook flushes invalidations.
        live = [record for record in tx.watchers(time_watch(scope, data["scope_fence"]))
                if compare_times(as_of, temporal_deadline(read_registration(tx, pin(record))["value"]["value"]["manifest"]["time_conditions"])) < 0]
        if len(live) >= MAX_LIVE_TEMPORAL and not any(entity_ref(record) == address for record in live):
            _fail("The live temporal cohort is full; only this registration is refused.", "E_BUDGET_EXHAUSTED")
    # Follow reverse target registrations to reject cycles before publication.
    seen = set()
    dependencies = [*data["positive"], *data["contexts"], *data["candidate_sets"], *data["negative_registrations"]]
    pending = list(dependencies)
    while pending:
        dependency = pending.pop()
        if _identity(dependency) == _identity(ref):
            _fail("A dependency cycle is forbidden.", "E_POLICY_INVALID")
        identity = _identity(dependency)
        if identity in seen:
            continue
        seen.add(identity)
        if len(seen) > MAX_DEPENDENCIES:
            _fail(code="E_BUDGET_EXHAUSTED")
        parent = _lookup(tx, registration_ref(dependency))
        if parent is not None:
            parent = read_registration(tx, pin(parent))
            parent_body = parent["value"]["value"]
            if parent_body["status"] != "current":
                _fail("A recomputation cannot consume an invalidated predecessor.", "E_DEPENDENCY_STALE")
            for name in ("positive", "contexts", "candidate_sets", "negative_registrations"):
                pending.extend(parent_body["manifest"][name])
    body = {"scope_id": scope, "target": ref, "manifest": data, "status": "current", "epoch": 0 if old is None else old["value"]["value"]["epoch"] + 1,
            "reasons": [], "recompute_pending": False}
    return tx.put_projection(address, domain("dependency-registration", body), watch_keys=watch_keys(data, ref))
