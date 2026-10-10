"""Explicit source coverage and scoped, protected replacement membership.

A coverage snapshot is a host-admitted collection declaration, not a global
search or a source-truth decision. Its observation catalog, knowledge cut,
query, interval and completeness remain inspectable. Historical snapshots are
immutable storage versions. Replacement retires only this snapshot family's
machine-owned membership; it never deletes or rewrites the referenced record.
"""

from __future__ import annotations

from copy import deepcopy
import json

from .association_policy import _values
from .candidate_sets import matches, read_dependency
from .canonical import canonical_bytes, canonical_digest
from .citations import _contract, _domain
from .contracts import command_digest, validate_command, validate_record
from .identity_dependencies import _identity, _lookup, _scoped, _sorted, _value
from .occurrences import _ReadCollector
from .source_catalogs import (
    catalog_observations, catalog_population, catalog_snapshot, ensure_catalog, initialize_catalog, read_catalog,
    source_catalog_ref, source_key,
)
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .storage.base import STORAGE_NAMESPACE, _validate_fragment, _validate_projection
from .time import compare_times, contains, knowledge_eligible, overlaps, validate_interval


COVERAGE_NAMESPACE = "matter.coverage"
MAX_COVERAGE_OBSERVATIONS = 4096
_OPERATIONS = {"publish_coverage", "register_negative_watch"}

__all__ = [
    "CoveragePolicy", "CoverageService", "COVERAGE_NAMESPACE", "coverage_ref",
    "observation_predicate", "match_observation", "read_coverage", "coverage_at",
]


def _invalid(detail="The source coverage declaration could not be verified."):
    return StorageError("E_EVIDENCE_INVALID", detail)


def _bounded(values, maximum=MAX_COVERAGE_OBSERVATIONS):
    if type(values) is not list:
        raise StorageError("E_SCHEMA_INVALID")
    if len(values) > maximum:
        raise StorageError("E_BUDGET_EXHAUSTED", "The declared coverage work exceeds its supported bound.")
    return values


def _refs(scope, values, fragment="pinned_ref"):
    result = [_scoped(scope, item, fragment) for item in _bounded(values)]
    if len({_identity(item) for item in result}) != len(result):
        raise StorageError("E_SCHEMA_INVALID", "A coverage set must contain each identity only once.")
    return _sorted(result)


def observation_predicate(clauses=()):
    """Build a closed exact predicate over admitted observation metadata.

    Scalar clauses select record namespace, source event/revision ID, declared
    origin or media type. An extension clause selects a namespaced extension's
    exact schema and whole canonical JSON value. Clauses are ANDed; no source
    bytes, arbitrary query language, plugin code or domain inference is run.
    """
    if not isinstance(clauses, (list, tuple)):
        raise StorageError("E_SCHEMA_INVALID")
    values = deepcopy(list(clauses))
    _bounded(values, 64)
    if len({canonical_bytes(item) for item in values}) != len(values):
        raise StorageError("E_SCHEMA_INVALID", "A predicate clause must appear only once.")
    value = {"record_type": "observation", "clauses": _sorted(values)}
    descriptor, validator = _contract("observation-predicate")
    if not validator.is_valid(value):
        raise StorageError("E_SCHEMA_INVALID")
    return {"schema": deepcopy(descriptor), "value": value}


def _predicate(query):
    body = _value("observation-predicate", query)
    expected = observation_predicate(body["clauses"])
    if canonical_bytes(query) != canonical_bytes(expected):
        raise _invalid("Predicate clauses must use the installed schema and canonical set order.")
    return body


def _specification(value):
    spec = _validate_fragment(value, "coverage_specification")
    _predicate(spec["query"])
    sources = []
    for source in _bounded(spec["eligible_sources"], 64):
        if source != source_key(source["value"]):
            raise StorageError("E_POLICY_INVALID", "Only an explicit source-namespace selector is supported.")
        sources.append(source)
    if len({canonical_bytes(item) for item in sources}) != len(sources):
        raise StorageError("E_SCHEMA_INVALID", "An eligible source must appear only once.")
    spec["eligible_sources"] = _sorted(sources)
    spec["observed_interval"] = validate_interval(spec["observed_interval"])
    return spec


def coverage_ref(scope_id, specification):
    """Address one exact source/query/interval replacement family."""
    scope = _validate_fragment(scope_id, "identifier")
    spec = _specification(specification)
    return {"scope_id": scope, "namespace": COVERAGE_NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "coverage-" + canonical_digest({"scope_id": scope, "specification": spec},
                                                  "matter.coverage-scope.v1")}


def _and(values):
    return False if any(item is False for item in values) else None if any(item is None for item in values) else True


def match_observation(observation, specification):
    """Return True/False/None for the declared source, predicate and interval.

    This function does not apply a knowledge cut. A current negative watch
    must reconsider a later arrival even when its original historical proof
    predates that arrival's availability. Publication applies knowledge gating
    separately. Missing optional metadata is indeterminate, never a no-match.
    """
    spec = _specification(specification)
    if type(observation) is not dict or observation.get("record_type") != "observation":
        raise StorageError("E_SCHEMA_INVALID")
    body = observation["body"]
    source = body["source_identity"]
    if source_key(source["namespace"]) not in spec["eligible_sources"]:
        return False
    outcomes = []
    for clause in spec["query"]["value"]["clauses"]:
        field = clause["field"]
        if field == "extension":
            actual = observation.get("extensions", {}).get(clause["key"])
            if actual is None:
                outcomes.append(None)
            else:
                outcomes.append(canonical_bytes(actual) == canonical_bytes({
                    "schema": clause["schema"], "value": clause["value"],
                }))
        else:
            actual = {
                "record_namespace": observation["namespace"],
                "source_event_id": source["event_id"],
                "source_revision_id": source.get("revision_id"),
                "origin": observation["provenance"]["origin"],
                "media_type": body["content"]["media_type"],
            }[field]
            outcomes.append(None if actual is None else actual == clause["equals"])
    event = (overlaps(spec["observed_interval"], body["occurred_interval"])
             if "occurred_interval" in body else contains(spec["observed_interval"], body["occurred_at"]))
    return _and([*outcomes, event])


def _classify(records, specification, as_of):
    _validate_fragment(as_of, "known_time")
    matched, indeterminate, excluded = [], [], []
    for record in records:
        knowledge = knowledge_eligible(record["body"]["available_at"], as_of)
        # Knowledge gating is first. Later evidence is not in this historical
        # corpus even when it reports a cancellation effective in the past.
        if knowledge is False:
            excluded.append(pin(record))
            continue
        eligible = match_observation(record, specification)
        outcome = _and([knowledge, eligible])
        (matched if outcome is True else excluded if outcome is False else indeterminate).append(pin(record))
    return _sorted(matched), _sorted(indeterminate), _sorted(excluded)


def _mature_interval(specification, as_of):
    interval = specification["observed_interval"]
    if any(interval[key]["state"] != "known" for key in ("start", "end")):
        return False
    if compare_times(interval["start"], interval["end"]) == 0 and interval["bounds"] != "closed":
        return False
    return compare_times(interval["end"], as_of) <= 0


def _result(body):
    adequate = (body["coverage"]["status"] == "complete" and body["mode"] == "replacement"
                and body["history_complete"] and _mature_interval(body["specification"], body["as_of"]))
    if not adequate:
        return "unusable_coverage"
    if body["matches"]:
        return "evidence_present"
    if body["indeterminate"]:
        return "indeterminate"
    return "adequate_empty"


class CoveragePolicy:
    """Immutable host admission of adapters and scoped replacement permission.

    Adapter/corpus completeness remains a truthful host declaration. An
    explicit source baseline admits the previously ingested population; this
    module cannot discover custom writes outside the supported intake service.
    """

    __slots__ = ("_encoded",)

    def __init__(self, scope_id, *, actors, authorities, adapters, allow_retirement=False):
        scope = _validate_fragment(scope_id, "identifier")
        if type(allow_retirement) is not bool:
            raise StorageError("E_POLICY_INVALID")
        definition = {"scope_id": scope, "actors": _values(actors, "actor_ref", scope_id=scope),
                      "authorities": _values(authorities, "receipt_dependency", scope_id=scope),
                      "adapters": _values(adapters, "component_ref"), "allow_retirement": allow_retirement,
                      "capability": "source_coverage_and_negative_registration"}
        object.__setattr__(self, "_encoded", canonical_bytes(definition))

    def __setattr__(self, name, value):
        raise AttributeError("CoveragePolicy is immutable.")

    @property
    def definition(self):
        return json.loads(self._encoded)

    @property
    def scope_id(self):
        return self.definition["scope_id"]

    @property
    def reference(self):
        return {"namespace": "matter", "id": "coverage-policy", "version": "1.0",
                "digest": canonical_digest(self.definition, "matter.coverage-policy.v1")}

    @property
    def ref(self):
        return self.reference

    def authorize(self, view, command):
        definition = self.definition
        if (command["scope_id"] != self.scope_id or command["actor"]["scope_id"] != self.scope_id
                or command["authority"]["scope_id"] != self.scope_id
                or any(item["scope_id"] != self.scope_id for item in command["expected_revisions"])):
            raise StorageError("E_SCOPE_FORBIDDEN")
        if command["body"]["coverage_policy"] != self.reference:
            raise StorageError("E_POLICY_INVALID", "The configured coverage policy is required.")
        if command["actor"] not in definition["actors"]:
            raise StorageError("E_AUTHORITY_REQUIRED")
        authority = next((item for item in definition["authorities"]
                          if entity_ref(item) == command["authority"]), None)
        if authority is None:
            raise StorageError("E_AUTHORITY_REQUIRED", "An admitted host coverage authority is required.")
        stored = view.get(authority)
        try:
            receipt = validate_record(stored)
            valid = (matches(receipt, authority) and receipt["record_type"] == "receipt"
                     and receipt["body"]["stage"] == "authority" and receipt["provenance"]["origin"] == "host"
                     and receipt["creation_receipt"]["scope_id"] == self.scope_id)
        except (ValueError, TypeError, KeyError, RecursionError):
            valid = False
        if not valid:
            raise StorageError("E_AUTHORITY_REQUIRED", "The admitted receipt must record actual host authority.")
        adapter = command["body"].get("adapter")
        if adapter is not None and adapter not in definition["adapters"]:
            raise StorageError("E_POLICY_INVALID", "The collection adapter is not admitted by the host policy.")
        return deepcopy(authority)


def _stored_coverage(record, scope):
    try:
        record = _validate_projection(record)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    body = _value("coverage-snapshot", record["value"])
    spec = _specification(body["specification"])
    if (record["scope_id"] != scope or body["scope_id"] != scope
            or record["creation_receipt"]["scope_id"] != scope or record["namespace"] != COVERAGE_NAMESPACE
            or record["watch_keys"] or entity_ref(record) != coverage_ref(scope, spec)
            or canonical_bytes(spec) != canonical_bytes(body["specification"]) or body["result"] != _result(body)
            or body["authority"]["scope_id"] != scope or body["publication_receipt"]["scope_id"] != scope):
        raise _invalid()
    for field in ("observations", "matches", "indeterminate", "excluded"):
        if body[field] != _refs(scope, body[field], "observation_dependency"):
            raise _invalid()
    catalogs = _refs(scope, body["catalogs"], "projection_dependency")
    expected = [source_catalog_ref(scope, source) for source in spec["eligible_sources"]]
    if catalogs != body["catalogs"] or _sorted(entity_ref(item) for item in catalogs) != _sorted(expected):
        raise _invalid()
    partitions = [*body["matches"], *body["indeterminate"], *body["excluded"]]
    if len(partitions) != len(body["observations"]) or _sorted(partitions) != body["observations"]:
        raise _invalid()
    members = body["members"]
    if len({_identity(item["reference"]) for item in members}) != len(members) or members != _sorted(members):
        raise _invalid()
    for member in members:
        ref = _scoped(scope, member["reference"], "projection_dependency")
        if ref["namespace"].startswith("matter."):
            raise _invalid()
        if ((member["status"] == "rejected") != (member["ownership"] == "rejected")
                or member["status"] == "retired" and member["ownership"] != "machine"
                or member["review_required"] and member["ownership"] != "reviewed"):
            raise _invalid()
    return record


def _publication_details(view, scope, record):
    body = record["value"]["value"]
    reference = _scoped(scope, body["publication_receipt"], "receipt_ref")
    try:
        receipt = view.get(reference)
    except StorageError as error:
        if error.code == "E_NOT_FOUND":
            raise _invalid("The coverage publication receipt is missing.") from None
        raise
    try:
        receipt = validate_record(receipt)
        if (entity_ref(receipt) != reference or receipt["record_type"] != "receipt"
                or receipt["namespace"] != STORAGE_NAMESPACE or receipt["creation_receipt"] != reference
                or receipt["provenance"]["origin"] != "system" or receipt["body"]["stage"] != "operation"):
            raise _invalid()
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid("The coverage publication requires its actual operation receipt.") from None
    details = _value("storage-receipt-details", receipt["body"]["details"])
    if (receipt["id"] != "command-" + details["command_digest"]
            or pin(record) not in details["writes"] or body["authority"] not in details["read_set"]):
        raise _invalid("The receipt must commit this coverage revision under its declared authority.")
    return details


def _coverage_records(view, scope, record):
    body = record["value"]["value"]
    details = _publication_details(view, scope, record)
    records = []
    sources = body["specification"]["eligible_sources"]
    frozen, history_complete = {}, True
    selected = {_identity(reference): reference for reference in body["catalogs"]}
    for source in sources:
        catalog = read_catalog(view, scope, source)
        if catalog is None:
            raise _invalid("The source catalog supporting this coverage is missing.")
        reference = selected[_identity(catalog)]
        if "revision" not in reference:
            raise _invalid("Coverage populations require an explicit catalog revision.")
        frozen_catalog = catalog_snapshot(catalog, reference["revision"])
        if not any(matches(frozen_catalog, item) for item in [*details["read_set"], *details["writes"]]):
            raise _invalid("The publishing operation must actually read or write each selected catalog snapshot.")
        population = catalog_population(catalog, reference["revision"])
        history_complete = history_complete and population["history_complete"]
        for item in population["observations"]:
            frozen[_identity(item)] = item
    if _sorted(frozen.values()) != body["observations"] or history_complete != body["history_complete"]:
        raise _invalid("Coverage must retain the exact population and history status of its selected catalog revisions.")
    for reference in body["observations"]:
        record = read_dependency(view, scope, reference)
        if record["record_type"] != "observation" or source_key(record["body"]["source_identity"]["namespace"]) not in sources:
            raise _invalid()
        records.append(record)
    if _classify(records, body["specification"], body["as_of"]) != (
        body["matches"], body["indeterminate"], body["excluded"],
    ):
        raise _invalid("Stored coverage must retain the exact declared temporal selection.")
    return records


def read_coverage(view, scope_id, reference):
    """Read and verify the current snapshot; an old pin is a revision refusal."""
    scope = _validate_fragment(scope_id, "identifier")
    fragment = "pinned_ref" if "revision" in reference or "digest" in reference else "entity_ref"
    ref = _scoped(scope, reference, fragment)
    record = _lookup(view, entity_ref(ref))
    if record is None:
        raise StorageError("E_NOT_FOUND")
    record = _stored_coverage(record, scope)
    if not matches(record, ref):
        raise StorageError("E_REVISION_CONFLICT")
    _coverage_records(view, scope, record)
    return record


def coverage_at(view, scope_id, reference):
    """Verify an exact historical coverage pin through a Snapshot port.

    The underlying Transaction refuses historical reads. Source observations
    remain immutable, so today's publication cannot alter this selection.
    """
    scope = _validate_fragment(scope_id, "identifier")
    ref = _scoped(scope, reference, "projection_dependency")
    record = _stored_coverage(view.get(ref), scope)
    if not matches(record, ref):
        raise _invalid()
    _coverage_records(view, scope, record)
    return record


def _previous(view, scope, address, reference, reader):
    old = _lookup(view, address)
    if old is not None:
        old = reader(view, scope, pin(old))
    if reference is None:
        if old is not None:
            raise StorageError("E_REVISION_CONFLICT", "An existing publication requires its exact current pin.")
    else:
        selected = _scoped(scope, reference, "projection_dependency")
        if entity_ref(selected) != address:
            raise _invalid("The previous pin belongs to another declared scope.")
        if old is None or not matches(old, selected):
            raise StorageError("E_REVISION_CONFLICT")
    return old


def _member_update(view, scope, previous, incoming, *, retire):
    proposed, current = {}, {_identity(item["reference"]): deepcopy(item) for item in previous}
    for raw in _bounded(incoming):
        item = _validate_fragment(raw, "coverage_member_input")
        ref = _scoped(scope, item["reference"], "projection_dependency")
        if ref["namespace"].startswith("matter."):
            raise StorageError("E_SCOPE_FORBIDDEN", "Coverage membership is limited to explicitly owned host derivatives.")
        target = read_dependency(view, scope, ref)
        key = _identity(target)
        if key in proposed:
            raise StorageError("E_SCHEMA_INVALID", "A replacement member must appear only once.")
        proposed[key] = {"reference": pin(target), "ownership": item["ownership"]}
    for key, item in proposed.items():
        old = current.get(key)
        if old is not None:
            if old["ownership"] != item["ownership"]:
                raise StorageError("E_AUTHORITY_REQUIRED", "Replacement cannot demote or reassign protected ownership.")
            if old["ownership"] in {"operator", "rejected"}:
                continue
            if old["ownership"] == "reviewed":
                old["review_required"] = old["review_required"] or item["reference"] != old["reference"]
                continue
        current[key] = {**item, "status": "rejected" if item["ownership"] == "rejected" else "active",
                        "review_required": False}
    if retire:
        for key, item in current.items():
            if key not in proposed:
                if item["ownership"] == "machine":
                    item["status"] = "retired"
                elif item["ownership"] == "reviewed":
                    item["review_required"] = True
    _bounded(list(current.values()))
    return _sorted(current.values())


def _command(value, operation=None):
    command = validate_command(value)
    if command["operation"] not in _OPERATIONS or operation is not None and command["operation"] != operation:
        raise StorageError("E_SCHEMA_INVALID")
    return command


class CoverageService:
    """Publish exact coverage and register bounded direct absence dependencies.

    Preparation reads a single snapshot and retains the caller's pins. Commit
    rechecks catalogs and source registrations under the write transaction.
    Every prepared command must be retained for exact retry; old journal replay
    never reinstates obsolete membership or a superseded absence registration.
    """

    def __init__(self, storage, *, policy):
        if not isinstance(policy, CoveragePolicy) or policy.scope_id != storage.scope_id:
            raise StorageError("E_POLICY_INVALID")
        self._storage, self._policy = storage, policy

    @property
    def scope_id(self):
        return self._storage.scope_id

    @property
    def policy(self):
        return self._policy.reference

    def prepare(self, command):
        command = _command(command)
        if (command["scope_id"] != self.scope_id or command["actor"]["scope_id"] != self.scope_id
                or command["authority"]["scope_id"] != self.scope_id
                or any(item["scope_id"] != self.scope_id for item in command["expected_revisions"])):
            raise StorageError("E_SCOPE_FORBIDDEN")
        expected = command["expected_revisions"]
        identities = {_identity(item) for item in expected}
        if len(identities) != len(expected):
            raise StorageError("E_SCHEMA_INVALID")

        def include(reference):
            if reference["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")
            identity = _identity(reference)
            if identity not in identities:
                expected.append(deepcopy(reference))
                identities.add(identity)

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
            self._inspect(_ReadCollector(snapshot, include), command)
        return validate_command(command)

    def publish(self, command):
        return self._storage.execute(_command(command, "publish_coverage"), self._publish)

    def register(self, command):
        return self._storage.execute(_command(command, "register_negative_watch"), self._register)

    def _inspect(self, view, command):
        authority = self._policy.authorize(view, command)
        if command["operation"] == "register_negative_watch":
            from .negative_dependencies import inspect_registration
            return inspect_registration(view, self.scope_id, command["body"], self._policy, authority)
        return self._inspect_publication(view, command, authority)

    def _inspect_publication(self, view, command, authority):
        scope, body = self.scope_id, command["body"]
        spec = _specification(body["specification"])
        address = coverage_ref(scope, spec)
        old = _previous(view, scope, address, body["previous"], read_coverage)
        if old is not None and compare_times(body["as_of"], old["value"]["value"]["as_of"]) < 0:
            raise _invalid("An older knowledge boundary cannot replace the current coverage snapshot.")
        baseline_map = {}
        for item in _bounded(body["source_baselines"], 64):
            source = item["source"]
            encoded = canonical_bytes(source)
            if source not in spec["eligible_sources"] or encoded in baseline_map:
                raise _invalid("Each baseline must name one declared eligible source exactly once.")
            baseline_map[encoded] = item
        catalogs, records, complete = [], {}, True
        for source in spec["eligible_sources"]:
            catalog = read_catalog(view, scope, source)
            if catalog is not None:
                catalogs.append(catalog)
                for record in catalog_observations(view, scope, catalog):
                    records[_identity(record)] = record
            baseline = baseline_map.get(canonical_bytes(source))
            if baseline is not None:
                if catalog is not None and catalog["value"]["value"]["baseline"] is not None:
                    raise StorageError("E_POLICY_INVALID", "A source history baseline can be initialized only once.")
                for reference in _refs(scope, baseline["observations"], "observation_dependency"):
                    record = read_dependency(view, scope, reference)
                    if source_key(record["body"]["source_identity"]["namespace"]) != source:
                        raise _invalid("A baseline observation belongs to another source namespace.")
                    records[_identity(record)] = record
            elif catalog is None or catalog["value"]["value"]["baseline"] is None:
                complete = False
        _bounded(list(records.values()))
        matched, unknown, excluded = _classify(records.values(), spec, body["as_of"])
        draft = {"scope_id": scope, "specification": spec, "catalog": deepcopy(body["catalog"]),
                 "coverage": deepcopy(body["coverage"]), "as_of": deepcopy(body["as_of"]), "mode": body["mode"],
                 "adapter": deepcopy(body["adapter"]), "policy": self._policy.reference, "authority": authority,
                 "observations": _sorted(pin(item) for item in records.values()), "matches": matched,
                 "indeterminate": unknown, "excluded": excluded, "history_complete": complete}
        draft["result"] = _result(draft)
        retire = (self._policy.definition["allow_retirement"] and draft["result"] != "unusable_coverage"
                  and not unknown)
        draft["members"] = _member_update(view, scope, old["value"]["value"]["members"] if old else [],
                                          body["members"], retire=retire)
        return {"address": address, "previous": old, "draft": draft, "baselines": baseline_map,
                "catalogs": catalogs}

    def _publish(self, tx):
        plan = self._inspect(tx, tx.command)
        draft, catalogs = plan["draft"], []
        for source in draft["specification"]["eligible_sources"]:
            baseline = plan["baselines"].get(canonical_bytes(source))
            if baseline is None:
                catalog = ensure_catalog(tx, source)
            else:
                catalog = initialize_catalog(tx, source, baseline["observations"], adapter=draft["adapter"],
                                             authority=draft["authority"], declared_at=draft["as_of"])
            catalogs.append(pin(catalog))
        draft["catalogs"] = _sorted(catalogs)
        draft["publication_receipt"] = tx.receipt_ref
        stored = tx.put_projection(plan["address"], _domain("coverage-snapshot", draft))
        change = {"cause": "coverage_change", "before": [pin(plan["previous"])] if plan["previous"] else [],
                  "after": [pin(stored)]}
        return tx.success("published", {"coverage": pin(stored), "changes": [change]})

    def _register(self, tx):
        from .negative_dependencies import commit_registration
        plan = self._inspect(tx, tx.command)
        return commit_registration(tx, plan)
