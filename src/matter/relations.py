"""Host-defined typed links, independent of equivalence and identity grouping.

Original endpoints and evidence remain historical pins. Graph checks use the
current identity partition and each edge's frozen rule, including during a
merge proposed by another service. No related-to closure creates equivalence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from .canonical import canonical_bytes, canonical_digest, source_digest
from .contracts import _FORMAT_CHECKER, command_digest, schema_for, validate_command, validate_record
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin, snapshot_digest
from .storage.base import _validate_fragment, _validate_projection


RELATION_NAMESPACE = "matter.links"
INDEX_NAMESPACE = "matter.link_indexes"
_LIMIT = 4096
_ENGINE = {"namespace": "matter", "id": "typed-relations", "version": "1.0",
           "digest": canonical_digest({"algorithm": "frozen-relation-graph", "version": "1.0"}, "matter.relation-engine.v1")}


def _invalid(detail="The typed matter relationship or its graph could not be verified."):
    return StorageError("E_EVIDENCE_INVALID", detail)


def _same(a, b):
    return canonical_bytes(a) == canonical_bytes(b)


def _identity(value):
    ref = entity_ref(value)
    return ref["scope_id"], ref["namespace"], ref["id"]


def _scoped(scope, value, fragment):
    result = _validate_fragment(value, fragment)
    if result["scope_id"] != scope:
        raise StorageError("E_SCOPE_FORBIDDEN")
    return result


def _lookup(view, ref):
    try:
        return view.lookup_identity(ref)
    except StorageError as error:
        if error.code == "E_NOT_FOUND":
            return None
        raise


def _current(view, scope, reference, fragment="pinned_ref"):
    ref = _scoped(scope, reference, fragment)
    stored = view.lookup_identity(entity_ref(ref))
    try:
        record = _validate_projection(stored) if stored.get("record_type") == PROJECTION_TYPE else validate_record(stored)
        if entity_ref(record) != entity_ref(ref) or record["creation_receipt"]["scope_id"] != scope:
            raise _invalid()
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise _invalid() from None
    if (("revision" in ref and ref["revision"] != record.get("revision"))
            or ("digest" in ref and ref["digest"] != snapshot_digest(record))):
        raise StorageError("E_REVISION_CONFLICT")
    return record


def _authority(view, scope, reference):
    record = _current(view, scope, reference, "receipt_dependency")
    if record["record_type"] != "receipt" or record["body"]["stage"] != "authority" or record["provenance"]["origin"] != "host":
        raise StorageError("E_AUTHORITY_REQUIRED")
    return record


class RelationRule:
    """Immutable host definition; descriptor binds every graph constraint."""
    __slots__ = ("_encoded",)

    def __init__(self, kind, *, namespace, id, version="1.0", directed=True, allow_self=False, acyclic=False):
        if any(type(value) is not bool for value in (directed, allow_self, acyclic)):
            raise StorageError("E_POLICY_INVALID")
        try:
            kind = _validate_fragment(kind, "namespaced_name")
            component = _validate_fragment({"namespace": namespace, "id": id, "version": version, "digest": "0" * 64}, "component_ref")
        except ValueError:
            raise StorageError("E_POLICY_INVALID") from None
        definition = {"kind": kind, "namespace": component["namespace"], "id": component["id"],
                      "version": component["version"], "directed": directed, "allow_self": allow_self, "acyclic": acyclic}
        object.__setattr__(self, "_encoded", canonical_bytes(definition))

    def __setattr__(self, name, value):
        raise AttributeError("RelationRule is immutable.")

    @property
    def definition(self):
        return json.loads(self._encoded)

    @property
    def reference(self):
        definition = self.definition
        return {key: definition[key] for key in ("namespace", "id", "version")} | {
            "digest": canonical_digest(definition, "matter.relation-rule.v1")}


def _rule(value):
    if type(value) is not dict or set(value) != {"kind", "namespace", "id", "version", "directed", "allow_self", "acyclic"}:
        raise _invalid()
    try:
        return RelationRule(**value)
    except (ValueError, TypeError):
        raise _invalid() from None


class RelationPolicy:
    """Trusted host actor/authority admission and exact rule allowlist."""
    __slots__ = ("_encoded",)

    def __init__(self, scope_id, *, actors, authorities, rules):
        scope = _validate_fragment(scope_id, "identifier")
        try:
            actors = [_scoped(scope, item, "actor_ref") for item in actors]
            authorities = [_scoped(scope, item, "receipt_dependency") for item in authorities]
            rules = [item.definition if isinstance(item, RelationRule) else None for item in rules]
        except (TypeError, ValueError) as error:
            if isinstance(error, StorageError) and error.code == "E_SCOPE_FORBIDDEN":
                raise
            raise StorageError("E_POLICY_INVALID") from None
        if any(not values or None in values or len({canonical_bytes(v) for v in values}) != len(values)
               for values in (actors, authorities, rules)):
            raise StorageError("E_POLICY_INVALID")
        if len({(r["kind"], canonical_bytes(_rule(r).reference)) for r in rules}) != len(rules):
            raise StorageError("E_POLICY_INVALID")
        definition = {"scope_id": scope, "actors": sorted(actors, key=canonical_bytes),
                      "authorities": sorted(authorities, key=canonical_bytes), "rules": sorted(rules, key=canonical_bytes)}
        object.__setattr__(self, "_encoded", canonical_bytes(definition))

    def __setattr__(self, name, value):
        raise AttributeError("RelationPolicy is immutable.")

    @property
    def definition(self):
        return json.loads(self._encoded)

    @property
    def scope_id(self):
        return self.definition["scope_id"]

    def authorize(self, view, command):
        definition = self.definition
        scope = self.scope_id
        if (command["scope_id"] != scope or command["actor"]["scope_id"] != scope
                or command["authority"]["scope_id"] != scope
                or any(ref["scope_id"] != scope for ref in command["expected_revisions"])):
            raise StorageError("E_SCOPE_FORBIDDEN")
        if command["actor"] not in definition["actors"]:
            raise StorageError("E_AUTHORITY_REQUIRED")
        authority = next((ref for ref in definition["authorities"] if entity_ref(ref) == command["authority"]), None)
        if authority is None:
            raise StorageError("E_AUTHORITY_REQUIRED")
        _authority(view, scope, authority)
        body = command["body"]
        rule = next((_rule(value) for value in definition["rules"]
                     if value["kind"] == body["relation_kind"] and _same(_rule(value).reference, body["relationship_schema"])), None)
        if rule is None:
            raise StorageError("E_POLICY_INVALID")
        return rule, authority


def _member_watch(reference):
    return "matter-link-member-" + canonical_digest(entity_ref(reference), "matter.link-member.v1")


def _graph_watch(scope, kind):
    return "matter-link-graph-" + canonical_digest({"scope_id": scope, "kind": kind}, "matter.link-graph.v1")


def relation_ref(scope, body, rule):
    endpoints = [entity_ref(body["from_matter"]), entity_ref(body["to_matter"])]
    if not rule.definition["directed"]:
        endpoints.sort(key=canonical_bytes)
    component = body["relationship_schema"]
    key = {"scope_id": scope, "endpoints": endpoints, "kind": body["relation_kind"],
           "schema": {key: component[key] for key in ("namespace", "id")}}
    return {"scope_id": scope, "namespace": RELATION_NAMESPACE, "record_type": "matter_relation",
            "id": "link-" + canonical_digest(key, "matter.link.v1")}


def _index_ref(record):
    return {**entity_ref(record), "namespace": INDEX_NAMESPACE, "record_type": PROJECTION_TYPE}


def _watches(record):
    body = record["body"]
    return sorted({_member_watch(body["from_matter"]), _member_watch(body["to_matter"]),
                   _graph_watch(record["scope_id"], body["relation_kind"])})


@lru_cache(maxsize=1)
def _contract():
    try:
        data = files("matter._schemas").joinpath("matter-link-index.schema.json").read_bytes()
        schema = json.loads(data)
        Draft202012Validator.check_schema(schema)
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        return ({"namespace": "matter", "id": "matter-link-index", "version": "1.0", "digest": source_digest(data)},
                Draft202012Validator(schema, registry=registry, format_checker=_FORMAT_CHECKER))
    except (OSError, ValueError, TypeError, KeyError, SchemaError):
        raise StorageError("E_STORAGE_UNAVAILABLE", "The installed typed relation schema is unavailable.") from None


def _index_value(record, rule, authority):
    descriptor, validator = _contract()
    value = {"scope_id": record["scope_id"], "relation": pin(record), "rule": rule.definition, "authority": authority}
    if not validator.is_valid(value):
        raise _invalid()
    return {"schema": deepcopy(descriptor), "value": value}


def _parents(body, authority):
    return sorted({canonical_bytes(ref): ref for ref in [body["from_matter"], body["to_matter"], *body["basis"], authority]}.values(), key=canonical_bytes)


def _read_index(view, scope, stored):
    descriptor, validator = _contract()
    try:
        index = _validate_projection(stored)
        if (index["scope_id"] != scope or index["namespace"] != INDEX_NAMESPACE
                or index["creation_receipt"]["scope_id"] != scope
                or not _same(index["value"]["schema"], descriptor)
                or not validator.is_valid(index["value"]["value"])):
            raise _invalid()
        value = index["value"]["value"]
        if value["scope_id"] != scope:
            raise _invalid()
        reference = _scoped(scope, value["relation"], "matter_relation_dependency")
        authority = _scoped(scope, value["authority"], "receipt_dependency")
        rule = _rule(value["rule"])
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    record = _current(view, scope, reference, "matter_relation_dependency")
    _authority(view, scope, authority)
    body, provenance = record["body"], record["provenance"]
    for ref in [body["from_matter"], body["to_matter"], *body["basis"]]:
        _scoped(scope, ref, "pinned_ref")
    if (record["record_type"] != "matter_relation" or record["namespace"] != RELATION_NAMESPACE
            or record["revision"] != 1 or index["revision"] != 1 or body["status"] != "active"
            or "supersedes" in record or record["creation_receipt"] != index["creation_receipt"]
            or entity_ref(record) != relation_ref(scope, body, rule) or entity_ref(index) != _index_ref(record)
            or not _same(body["relationship_schema"], rule.reference) or body["relation_kind"] != rule.definition["kind"]
            or body["authority"] != entity_ref(authority) or index["watch_keys"] != _watches(record)
            or not _same(index["value"], _index_value(record, rule, authority))
            or provenance != {"origin": "host", "producer": _ENGINE, "recorded_at": provenance["recorded_at"],
                              "parents": _parents(body, authority)}):
        raise _invalid()
    return record, index, rule


def _watched(view, scope, watch):
    values = view.watchers(watch)
    if type(values) is not list:
        raise _invalid()
    if len(values) > _LIMIT:
        raise StorageError("E_BUDGET_EXHAUSTED")
    result = []
    for stored in values:
        record, index, rule = _read_index(view, scope, stored)
        if watch not in index["watch_keys"]:
            raise _invalid()
        actual = view.lookup_identity(entity_ref(index))
        if not _same(actual, index):
            raise _invalid()
        result.append((record, index, rule))
    return result


def collect_relations(view, scope, members):
    """Collect raw edges touching these original identities, with verified indexes."""
    records, indexes = {}, {}
    members = list(members)
    if len(members) > _LIMIT:
        raise StorageError("E_BUDGET_EXHAUSTED")
    for member in members:
        reference = _scoped(scope, entity_ref(member), "matter_ref")
        for record, index, _ in _watched(view, scope, _member_watch(reference)):
            if reference not in (entity_ref(record["body"]["from_matter"]), entity_ref(record["body"]["to_matter"])):
                raise _invalid()
            records[_identity(record)] = record
            indexes[_identity(index)] = index
            if len(records) > _LIMIT:
                raise StorageError("E_BUDGET_EXHAUSTED")
    return {"records": sorted(records.values(), key=canonical_bytes), "indexes": sorted(indexes.values(), key=canonical_bytes)}


def _root(view, scope, reference, mapping, cache):
    from .identity_groups import read_group
    bare = entity_ref(reference)
    if _identity(bare) in mapping:
        return mapping[_identity(bare)]
    key = _identity(bare)
    if key not in cache:
        group = read_group(view, scope, bare)
        survivor = entity_ref(group["survivor"])
        for member in group["members"]:
            cache[_identity(member)] = survivor
        if len(cache) > _LIMIT:
            raise StorageError("E_BUDGET_EXHAUSTED")
    return cache[key]


def _validate_graph(view, scope, edges, mapping):
    if len(edges) > _LIMIT:
        raise StorageError("E_BUDGET_EXHAUSTED")
    directions = {rule.definition["directed"] for _, _, rule in edges}
    if len(directions) > 1:
        raise StorageError("E_POLICY_INVALID", "One relation kind cannot mix directed and undirected graph semantics.")
    cache, adjacency, indegree = {}, {}, {}
    projected = []
    for record, _, rule in edges:
        body = record["body"]
        start = _identity(_root(view, scope, body["from_matter"], mapping, cache))
        end = _identity(_root(view, scope, body["to_matter"], mapping, cache))
        if start == end and not rule.definition["allow_self"]:
            raise StorageError("E_MERGE_CONFLICT", "The identity partition creates a forbidden typed self-relation.")
        projected.append((start, end))
        adjacency.setdefault(start, set()).add(end)
        adjacency.setdefault(end, set())
    if len(adjacency) > _LIMIT:
        raise StorageError("E_BUDGET_EXHAUSTED")
    if not any(rule.definition["acyclic"] for _, _, rule in edges):
        return
    if directions == {False}:
        parents = {}
        def find(node):
            parents.setdefault(node, node)
            while parents[node] != node:
                parents[node] = parents[parents[node]]
                node = parents[node]
            return node
        for start, end in sorted({tuple(sorted(pair)) for pair in projected}):
            first, second = find(start), find(end)
            if first == second:
                raise StorageError("E_MERGE_CONFLICT", "The typed relation graph must remain acyclic.")
            parents[first] = second
    else:
        indegree = {node: 0 for node in adjacency}
        for targets in adjacency.values():
            for target in targets:
                indegree[target] += 1
        ready = [node for node, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            node = ready.pop()
            visited += 1
            for target in adjacency[node]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        if visited != len(adjacency):
            raise StorageError("E_MERGE_CONFLICT", "The typed relation graph must remain acyclic.")


def validate_identity_partition(view, scope, mapping):
    """Check affected frozen-rule graphs against an explicit complete partition.

    Mapping is a sequence of {member: bare matter ref, survivor: bare matter ref}.
    Returned graph records can include outside neighbors; they are dependencies,
    not automatically child evidence belonging to an affected identity group.
    """
    from .identity_groups import read_group
    entries = list(mapping)
    if len(entries) > _LIMIT:
        raise StorageError("E_BUDGET_EXHAUSTED")
    mapped = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"member", "survivor"}:
            raise StorageError("E_SCHEMA_INVALID")
        member = _scoped(scope, entry["member"], "matter_ref")
        survivor = _scoped(scope, entry["survivor"], "matter_ref")
        if _identity(member) in mapped:
            raise StorageError("E_SCHEMA_INVALID")
        mapped[_identity(member)] = survivor
    checked_members = set()
    for entry in entries:
        if _identity(entry["survivor"]) not in mapped or mapped[_identity(entry["survivor"])] != entry["survivor"]:
            raise StorageError("E_MERGE_CONFLICT", "Every partition must contain its own representative.")
        if _identity(entry["member"]) not in checked_members:
            group = read_group(view, scope, entry["member"])
            group_members = {_identity(member) for member in group["members"]}
            if not group_members <= mapped.keys():
                raise StorageError("E_MERGE_CONFLICT", "The planned partition must cover each affected group completely.")
            checked_members.update(group_members)
    touching = collect_relations(view, scope, [entry["member"] for entry in entries])
    records, indexes = {}, {}
    for kind in sorted({record["body"]["relation_kind"] for record in touching["records"]}):
        edges = _watched(view, scope, _graph_watch(scope, kind))
        if any(record["body"]["relation_kind"] != kind for record, _, _ in edges):
            raise _invalid()
        _validate_graph(view, scope, edges, mapped)
        for record, index, _ in edges:
            records[_identity(record)] = record
            indexes[_identity(index)] = index
            if len(records) > _LIMIT:
                raise StorageError("E_BUDGET_EXHAUSTED")
    return {"records": sorted(records.values(), key=canonical_bytes), "indexes": sorted(indexes.values(), key=canonical_bytes)}


class _Collector:
    def __init__(self, view, include):
        self.view, self.include = view, include

    def get(self, reference):
        value = self.view.get(reference)
        self.include(pin(value))
        return value

    def lookup_identity(self, reference):
        value = self.view.lookup_identity(reference)
        self.include(pin(value))
        return value

    def watchers(self, key):
        values = self.view.watchers(key)
        for value in values:
            self.include(pin(value))
        return values


class RelationService:
    def __init__(self, storage, *, policy):
        if not isinstance(policy, RelationPolicy):
            raise StorageError("E_POLICY_INVALID")
        if storage.scope_id != policy.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        self._storage, self._policy = storage, policy

    @property
    def scope_id(self):
        return self._storage.scope_id

    def _command(self, command):
        value = validate_command(command)
        if value["operation"] != "link_matters":
            raise StorageError("E_SCHEMA_INVALID")
        return value

    def prepare(self, command):
        command = self._command(command)
        identities = {_identity(ref) for ref in command["expected_revisions"]}
        if len(identities) != len(command["expected_revisions"]):
            raise StorageError("E_SCHEMA_INVALID")
        def include(reference):
            if _identity(reference) not in identities:
                command["expected_revisions"].append(reference)
                identities.add(_identity(reference))
        with self._storage.snapshot() as snapshot:
            try:
                journal = snapshot.command_receipt(command["idempotency_key"])
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
            else:
                if journal["command_digest"] != command_digest(command):
                    raise StorageError("E_IDEMPOTENCY_CONFLICT")
                return command
            self._state(_Collector(snapshot, include), command)
        return validate_command(command)

    def _state(self, view, command):
        rule, authority = self._policy.authorize(view, command)
        body = deepcopy(command["body"])
        for reference in [body["from_matter"], body["to_matter"]]:
            _current(view, self.scope_id, reference, "matter_dependency")
        seen = set()
        for reference in body["basis"]:
            if _identity(reference) in seen:
                raise StorageError("E_SCHEMA_INVALID")
            seen.add(_identity(reference))
            _current(view, self.scope_id, reference)
        body["basis"].sort(key=canonical_bytes)
        if not rule.definition["directed"] and canonical_bytes(entity_ref(body["from_matter"])) > canonical_bytes(entity_ref(body["to_matter"])):
            body["from_matter"], body["to_matter"] = body["to_matter"], body["from_matter"]
        reference = relation_ref(self.scope_id, body, rule)
        existing = _lookup(view, reference)
        index = _lookup(view, _index_ref(reference))
        if (existing is None) != (index is None):
            raise _invalid()
        if existing is not None:
            record, _, frozen = _read_index(view, self.scope_id, index)
            if not _same(existing, record):
                raise _invalid()
            if not _same(frozen.definition, rule.definition):
                raise StorageError("E_SOURCE_IDENTITY_CONFLICT", "The existing edge retains its original relationship rule.")
            expected_body = deepcopy(record["body"])
            expected_body.update(from_matter=body["from_matter"], to_matter=body["to_matter"])
            if not _same(expected_body, {**body, "authority": command["authority"], "status": "active"}):
                raise StorageError("E_SOURCE_IDENTITY_CONFLICT", "The existing typed edge has a different evidence or rule declaration.")
        edges = _watched(view, self.scope_id, _graph_watch(self.scope_id, body["relation_kind"]))
        if any(record["body"]["relation_kind"] != body["relation_kind"] for record, _, _ in edges):
            raise _invalid()
        if existing is None:
            projected = {"body": {**body, "status": "active"}, "scope_id": self.scope_id}
            edges.append((projected, None, rule))
        try:
            _validate_graph(view, self.scope_id, edges, {})
        except StorageError as error:
            if error.code == "E_MERGE_CONFLICT":
                raise StorageError("E_RULE_CONFLICT", error.detail) from None
            raise
        return body, rule, authority, reference, existing

    def link(self, command):
        return self._storage.execute(self._command(command), self._link)

    def _link(self, tx):
        body, rule, authority, reference, existing = self._state(tx, tx.command)
        if existing is not None:
            return tx.success("linked", {"relation": pin(existing)})
        recorded_at = {"state": "known", "value": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"), "precision": "microsecond"}
        record = tx.insert({"schema_version": "1.0", **reference,
            "provenance": {"origin": "host", "producer": deepcopy(_ENGINE), "recorded_at": recorded_at, "parents": _parents(body, authority)},
            "body": {**body, "authority": tx.command["authority"], "status": "active"}})
        tx.put_projection(_index_ref(record), _index_value(record, rule, authority), watch_keys=_watches(record))
        return tx.success("linked", {"relation": pin(record)})

    def for_matter(self, matter):
        with self._storage.snapshot() as snapshot:
            _current(snapshot, self.scope_id, entity_ref(matter), "matter_ref")
            return collect_relations(snapshot, self.scope_id, [matter])["records"]
