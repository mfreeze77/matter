"""Explicit, non-destructive equivalence and reversible identity correction.

Merge authority is separate from association acceptance. Original IDs, exact
keys, claims and source references survive; current identity is a complete,
flat partition with immutable movement history. Prepare once and retain the
exact command to recover a durable result. A retry never replays old writes.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from itertools import combinations, product

from ._identity_children import collect_children, conflicts
from .association_policy import _values
from .canonical import canonical_bytes, canonical_digest, source_digest
from .candidate_sets import read_dependency
from .citations import _domain
from .contracts import ContractError, command_digest, validate_command, validate_record
from .identity_dependencies import (
    NAMESPACE as DEPENDENCY_NAMESPACE,
    _identity, _invalid, _lookup, _matches, _scoped, _sorted, _value,
    invalidate_dependencies, read_registration,
)
from .identity_groups import group_ref, group_value, read_group, write_groups
from .occurrences import _ReadCollector
from .relations import validate_identity_partition
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin, snapshot_digest
from .storage.base import _validate_fragment, _validate_projection


RECEIPT_NAMESPACE = "matter.identity_receipts"
SEPARATION_NAMESPACE = "matter.identity_separations"
MAX_MERGE_MEMBERS = 128
_ENGINE = {"namespace": "matter", "id": "identity-corrections", "version": "1.0",
           "digest": source_digest(b"matter.identity-corrections.v1")}
_OPERATIONS = {"merge_matters", "correct_merge", "release_identity_separations"}

__all__ = ["MergePolicy", "IdentityCorrectionService", "read_decision", "read_release", "separation_ref",
           "RECEIPT_NAMESPACE", "SEPARATION_NAMESPACE", "MAX_MERGE_MEMBERS"]


def _now():
    return {"state": "known", "value": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "precision": "microsecond"}


def _same(left, right):
    return canonical_bytes(left) == canonical_bytes(right)


def _ref(value):
    return entity_ref(value) if "body" in value or "value" in value else deepcopy(value)


def _unique(values):
    return _sorted({canonical_bytes(value): value for value in values}.values())


def _conflict(detail):
    return StorageError("E_MERGE_CONFLICT", detail)


def _command(value, operation=None):
    command = validate_command(value)
    if command["operation"] not in _OPERATIONS or operation is not None and command["operation"] != operation:
        raise ContractError("E_SCHEMA_INVALID", "A matter merge or identity correction is required.")
    return command


def _policy_reference(definition):
    return {"namespace": "matter", "id": "merge-policy", "version": "1.0",
            "digest": canonical_digest(definition, "matter.merge-policy.v1")}


class MergePolicy:
    """Immutable host admission of a distinct equivalence capability.

    The host authenticates actors and admits actual host-origin authority
    receipts. Evidence and evaluator confidence cannot configure this object.
    No policy can override a protected separation by merely changing version.
    """

    __slots__ = ("_encoded",)

    def __init__(self, scope_id, *, actors, authorities, allow_correction=False):
        scope = _validate_fragment(scope_id, "identifier")
        if type(allow_correction) is not bool:
            raise StorageError("E_POLICY_INVALID")
        definition = {"scope_id": scope, "actors": _values(actors, "actor_ref", scope_id=scope),
                      "authorities": _values(authorities, "receipt_dependency", scope_id=scope),
                      "allow_correction": allow_correction, "capability": "merge"}
        object.__setattr__(self, "_encoded", canonical_bytes(definition))

    def __setattr__(self, name, value):
        raise AttributeError("MergePolicy is immutable.")

    @property
    def definition(self):
        return json.loads(self._encoded)

    @property
    def scope_id(self):
        return self.definition["scope_id"]

    @property
    def reference(self):
        return _policy_reference(self.definition)

    @property
    def ref(self):
        return self.reference

    def authorize(self, view, command, *, correction=False):
        definition = self.definition
        if (command["scope_id"] != self.scope_id or command["actor"]["scope_id"] != self.scope_id
                or command["authority"]["scope_id"] != self.scope_id
                or any(item["scope_id"] != self.scope_id for item in command["expected_revisions"])):
            raise StorageError("E_SCOPE_FORBIDDEN")
        if command["actor"] not in definition["actors"] or correction and not definition["allow_correction"]:
            raise StorageError("E_AUTHORITY_REQUIRED", "Explicit host merge/correction authority is required.")
        authority = next((item for item in definition["authorities"] if entity_ref(item) == command["authority"]), None)
        if authority is None:
            raise StorageError("E_AUTHORITY_REQUIRED", "An admitted host authority receipt is required.")
        stored = view.get(authority)
        _authority(stored, authority)
        return deepcopy(authority)


def _authority(stored, reference):
    try:
        record = validate_record(stored)
        if (record["record_type"] != "receipt" or not _matches(record, reference)
                or record["provenance"]["origin"] != "host" or record["body"]["stage"] != "authority"
                or record["creation_receipt"]["scope_id"] != reference["scope_id"]):
            raise StorageError("E_AUTHORITY_REQUIRED")
    except (ValueError, TypeError, KeyError, RecursionError):
        raise StorageError("E_AUTHORITY_REQUIRED", "The admitted receipt must record actual host authority.") from None


def _decision_ref(scope, command_id, kind):
    family = kind if kind in {"merge", "release"} else "correction"
    return {"scope_id": scope, "namespace": RECEIPT_NAMESPACE, "record_type": "receipt",
            "id": family + "-" + canonical_digest({"scope_id": scope, "command_id": command_id},
                                                   "matter.identity-" + family + ".v1")}


def _group_view(group):
    return {"survivor": pin(group["survivor"]), "members": _sorted(pin(item) for item in group["members"]),
            "indexes": _sorted(pin(item) for item in group["indexes"])}


def _group_mapping(groups):
    return {_identity(member): entity_ref(group["survivor"]) for group in groups for member in group["members"]}


def _verify_views(groups, scope):
    members, indexes = {}, {}
    for group in groups:
        if group["members"] != _sorted(group["members"]) or group["indexes"] != _sorted(group["indexes"]):
            raise _invalid()
        local = {_identity(item) for item in group["members"]}
        if len(local) != len(group["members"]) or _identity(group["survivor"]) not in local:
            raise _invalid()
        if group["survivor"] not in group["members"]:
            raise _invalid()
        expected_indexes = {_identity(group_ref(member)) for member in group["members"]}
        if group["indexes"] and {_identity(item) for item in group["indexes"]} != expected_indexes:
            raise _invalid()
        if len(group["indexes"]) not in {0, len(group["members"])}:
            raise _invalid()
        if not group["indexes"] and len(group["members"]) != 1:
            raise _invalid()
        for member in group["members"]:
            if member["scope_id"] != scope or _identity(member) in members or "revision" not in member:
                raise _invalid()
            members[_identity(member)] = member
        for index in group["indexes"]:
            if index["scope_id"] != scope or _identity(index) in indexes or "revision" not in index:
                raise _invalid()
            indexes[_identity(index)] = index
    return members, indexes


def read_decision(view, scope, reference, *, _merge_only=False):
    """Verify immutable identity proof without consulting current partitions.

    Historical basis and child pins are preserved declarations, not refreshed
    transactional inputs. Public historical_view additionally reads the exact
    historical member, mirror and child snapshots from a consistent snapshot.
    """
    ref = _scoped(scope, reference, "receipt_dependency")
    stored = view.get(ref)
    try:
        record = validate_record(stored)
        if record["record_type"] != "receipt" or not _matches(record, ref):
            raise _invalid()
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    detail = _value("identity-decision", record["body"]["details"])
    if _merge_only and detail["kind"] != "merge":
        raise _invalid("A correction must cite a merge directly, not a correction chain.")
    parents = _unique([*detail["basis"], *([detail["previous"]] if detail["previous"] is not None else [])])
    if (detail["scope_id"] != scope or record["creation_receipt"]["scope_id"] != scope
            or entity_ref(record) != _decision_ref(scope, record["body"]["operation_id"], detail["kind"])
            or record["body"]["stage"] != "authority" or record["body"]["outcome"] != "matter:identity_" + detail["kind"]
            or record["body"]["recorded_at"] != detail["as_of"]
            or record["provenance"] != {"origin": "host", "producer": _ENGINE,
                "recorded_at": detail["as_of"], "parents": parents}
            or not _same(record["body"]["evidence"], parents)
            or detail["policy"] != _policy_reference(detail["policy_definition"])):
        raise _invalid()
    definition = detail["policy_definition"]
    if (definition["scope_id"] != scope or detail["actor"] not in definition["actors"]
            or detail["authority"] not in definition["authorities"]
            or detail["kind"] != "merge" and not definition["allow_correction"]):
        raise _invalid()
    admitted = MergePolicy(scope, actors=definition["actors"], authorities=definition["authorities"],
                           allow_correction=definition["allow_correction"])
    if definition != admitted.definition or detail["basis"] != _sorted(detail["basis"]):
        raise _invalid()
    if len({_identity(item) for item in detail["basis"]}) != len(detail["basis"]):
        raise _invalid()
    for item in [detail["actor"], detail["authority"], *definition["actors"], *definition["authorities"],
                 *parents, *detail["protections"]]:
        if item["scope_id"] != scope:
            raise _invalid()
    authority = view.get(detail["authority"])
    _authority(authority, detail["authority"])
    before, before_indexes = _verify_views(detail["before"], scope)
    after, after_indexes = _verify_views(detail["after"], scope)
    if (set(before) != set(after) or len(before) > MAX_MERGE_MEMBERS
            or any(after[key]["revision"] != before[key]["revision"] + 1 for key in before)
            or len(after_indexes) != len(after)
            or any(index["revision"] != before_indexes.get(key, {"revision": 0})["revision"] + 1
                   for key, index in after_indexes.items())):
        raise _invalid()
    if detail["kind"] == "merge":
        if len(detail["before"]) < 2 or len(detail["after"]) != 1 or detail["previous"] is not None or detail["protections"]:
            raise _invalid()
    elif len(detail["before"]) != 1 or len(detail["after"]) < 2 or detail["previous"] is None:
        raise _invalid()
    else:
        # A correction can verify its immutable governing merge while the new
        # after-state is still being written. It must never dereference its
        # predicted new mirrors/protections here.
        prior = read_decision(view, scope, detail["previous"], _merge_only=True)
        earlier = prior["body"]["details"]["value"]
        if earlier["kind"] != "merge":
            raise _invalid()
        old = earlier["after"][0]
        current = detail["before"][0]
        old_members = {_identity(item): item for item in old["members"]}
        if (entity_ref(old["survivor"]) != entity_ref(current["survivor"])
                or old["indexes"] != current["indexes"] or set(old_members) != set(before)
                or any(before[key]["revision"] < old_members[key]["revision"] for key in before)):
            raise _invalid()
        if detail["kind"] == "undo" and _group_mapping(detail["after"]) != _group_mapping(earlier["before"]):
            raise _invalid()
        expected_protections = {
            _identity(separation_ref(first, second))
            for first_group, second_group in combinations(detail["after"], 2)
            for first, second in product(first_group["members"], second_group["members"])
        }
        if (len(detail["protections"]) != len(expected_protections)
                or {_identity(item) for item in detail["protections"]} != expected_protections
                or any("revision" not in item for item in detail["protections"])
                or detail["protections"] != _sorted(detail["protections"])):
            raise _invalid("The correction proof must preserve every cross-partition separation.")
    old_mapping, new_mapping = _group_mapping(detail["before"]), _group_mapping(detail["after"])
    seen = set()
    for child in detail["children"]:
        key = canonical_bytes(child["reference"])
        if key in seen or child["reference"]["scope_id"] != scope:
            raise _invalid()
        seen.add(key)
        owners = child["original_matters"]
        if (len({_identity(item) for item in owners}) != len(owners)
                or any(_identity(item) not in before for item in owners)
                or child["before"] != _unique(old_mapping[_identity(item)] for item in owners)
                or child["after"] != _unique(new_mapping[_identity(item)] for item in owners)):
            raise _invalid()
        expected_action = "shared" if len(owners) > 1 else (
            "retained" if child["before"] == child["after"] else "moved")
        if child["action"] not in {expected_action, "invalidated"}:
            raise _invalid()
        revisions = [change for change in detail["changes"] if child["reference"] in change["before"]]
        if child["action"] == "invalidated" and not revisions:
            raise _invalid()
        if child["record_action"] == "revisioned" and (
            child["reference"]["record_type"] != PROJECTION_TYPE
            or child["reference"]["namespace"] != DEPENDENCY_NAMESPACE
            or not any(any(_identity(item) == _identity(child["reference"])
                           and item.get("revision") == child["reference"].get("revision", 0) + 1
                           for item in change["after"]) for change in revisions)
        ):
            raise _invalid()
    for change in detail["changes"]:
        if change["cause"] != "association_correction" or any(item["scope_id"] != scope for item in change["before"] + change["after"]):
            raise _invalid()
    core_change = {"cause": "association_correction", "before": _sorted([*before.values(), *before_indexes.values()]),
                   "after": _sorted([*after.values(), *after_indexes.values()])}
    if core_change not in detail["changes"]:
        raise _invalid()
    for conflict in detail["conflicts"]:
        if any(item["scope_id"] != scope for item in conflict["references"]):
            raise _invalid()
    return record


def separation_ref(first, second):
    members = _sorted([_validate_fragment(entity_ref(first), "matter_ref"),
                       _validate_fragment(entity_ref(second), "matter_ref")])
    if members[0]["scope_id"] != members[1]["scope_id"]:
        raise StorageError("E_SCOPE_FORBIDDEN")
    if members[0] == members[1]:
        raise _conflict("A matter cannot be separated from itself.")
    return {"scope_id": members[0]["scope_id"], "namespace": SEPARATION_NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "separation-" + canonical_digest(members, "matter.identity-separation.v1")}


def _separation_watch(member):
    return "identity-separation-" + canonical_digest(entity_ref(member), "matter.identity-separation-watch.v1")


def _read_separation(view, scope, stored):
    try:
        record = _validate_projection(stored)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    body = _value("identity-separation", record["value"])
    members = body["members"]
    if (body["scope_id"] != scope or record["creation_receipt"]["scope_id"] != scope
            or entity_ref(record) != separation_ref(*members) or members != _sorted(members)
            or record["watch_keys"] != sorted(_separation_watch(member) for member in members)):
        raise _invalid()
    previous = body["previous"]
    if previous is None:
        if record["revision"] != 1 or body["status"] != "protected":
            raise _invalid()
    elif (previous["scope_id"] != scope or entity_ref(previous) != entity_ref(record)
          or previous.get("revision") != record["revision"] - 1):
        raise _invalid()
    if body["status"] == "protected":
        decision = read_decision(view, scope, body["decision"])
        detail = decision["body"]["details"]["value"]
        mapping = _group_mapping(detail["after"])
        if (detail["kind"] == "merge" or pin(record) not in detail["protections"]
                or any(_identity(item) not in mapping for item in members)
                or mapping[_identity(members[0])] == mapping[_identity(members[1])]
                or {"cause": "association_correction", "before": [previous] if previous else [],
                    "after": [pin(record)]} not in detail["changes"]):
            raise _invalid()
    else:
        decision = read_release(view, scope, body["decision"])
        detail = decision["body"]["details"]["value"]
        matches = [entry for entry in detail["separations"] if entry["after"] == pin(record)]
        if (len(matches) != 1 or matches[0]["before"] != previous
                or matches[0]["members"] != members):
            raise _invalid()
    return record


def _separations(view, scope, members):
    found = {}
    for member in members:
        watched_values = view.watchers(_separation_watch(member))
        if type(watched_values) is not list:
            raise _invalid()
        for watched in watched_values:
            record = _read_separation(view, scope, watched)
            current = _lookup(view, entity_ref(record))
            if (entity_ref(member) not in record["value"]["value"]["members"]
                    or current is None or not _same(current, record)):
                raise _invalid()
            found[_identity(record)] = record
    return _sorted(found.values())


def _release_parents(detail):
    return _unique([*detail["basis"], *(entry["before"] for entry in detail["separations"]),
                    *(entry["protected_by"] for entry in detail["separations"])])


def read_release(view, scope, reference):
    """Verify a bounded explicit release proof without reading old mutable pins.

    Each selected protection is backed by its actual correction receipt. That
    receipt reads only its governing merge, so repeated release/re-protection
    does not create recursive traversal of the whole mutable history.
    """
    ref = _scoped(scope, reference, "receipt_dependency")
    stored = view.get(ref)
    try:
        record = validate_record(stored)
        if record["record_type"] != "receipt" or not _matches(record, ref):
            raise _invalid()
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None
    detail = _value("identity-release", record["body"]["details"])
    parents = _release_parents(detail)
    if (detail["scope_id"] != scope or record["creation_receipt"]["scope_id"] != scope
            or entity_ref(record) != _decision_ref(scope, record["body"]["operation_id"], "release")
            or record["body"]["stage"] != "authority" or record["body"]["outcome"] != "matter:identity_separations_released"
            or record["body"]["recorded_at"] != detail["as_of"]
            or record["provenance"] != {"origin": "host", "producer": _ENGINE,
                "recorded_at": detail["as_of"], "parents": parents}
            or not _same(record["body"]["evidence"], parents)):
        raise _invalid()
    definition = detail["policy_definition"]
    policy = MergePolicy(scope, actors=definition["actors"], authorities=definition["authorities"],
                         allow_correction=definition["allow_correction"])
    if (definition != policy.definition or detail["policy"] != policy.reference
            or not definition["allow_correction"] or detail["actor"] not in definition["actors"]
            or detail["authority"] not in definition["authorities"]
            or detail["basis"] != _sorted(detail["basis"])
            or len({_identity(item) for item in detail["basis"]}) != len(detail["basis"])):
        raise _invalid()
    if any(item["scope_id"] != scope for item in [detail["actor"], detail["authority"], *parents]):
        raise _invalid()
    authority = view.get(detail["authority"])
    _authority(authority, detail["authority"])
    seen, expected_changes = set(), []
    if len(detail["separations"]) > MAX_MERGE_MEMBERS * (MAX_MERGE_MEMBERS - 1) // 2:
        raise _invalid()
    for entry in detail["separations"]:
        before, after = entry["before"], entry["after"]
        if (any(item["scope_id"] != scope for item in [before, after, *entry["members"], entry["protected_by"]])
                or _identity(before) in seen or entity_ref(before) != separation_ref(*entry["members"])
                or entity_ref(after) != entity_ref(before) or "revision" not in before
                or after.get("revision") != before["revision"] + 1 or entry["members"] != _sorted(entry["members"])):
            raise _invalid()
        seen.add(_identity(before))
        protected = read_decision(view, scope, entry["protected_by"])
        proof = protected["body"]["details"]["value"]
        mapping = _group_mapping(proof["after"])
        writes = [change for change in proof["changes"] if change["after"] == [before]]
        written = len(writes) == 1 and writes[0]["cause"] == "association_correction"
        if written:
            prior = writes[0]["before"]
            written = (not prior if before["revision"] == 1 else
                       len(prior) == 1 and entity_ref(prior[0]) == entity_ref(before)
                       and prior[0].get("revision") == before["revision"] - 1)
        if (proof["kind"] == "merge" or before not in proof["protections"]
                or not written
                or any(_identity(member) not in mapping for member in entry["members"])
                or mapping[_identity(entry["members"][0])] == mapping[_identity(entry["members"][1])]):
            raise _invalid("Release must name the exact protection produced by its correction receipt.")
        expected_changes.append({"cause": "disposition_change", "before": [before], "after": [after]})
    if detail["changes"] != expected_changes:
        raise _invalid()
    return record


def _predict(groups, partitions):
    old_indexes = {_identity(index): index for group in groups for index in group["indexes"]}
    after = []
    for partition in partitions:
        members = _sorted({**pin(member), "revision": member["revision"] + 1} for member in partition["members"])
        indexes = _sorted({**group_ref(member), "revision": old_indexes.get(_identity(group_ref(member)), {"revision": 0})["revision"] + 1}
                          for member in partition["members"])
        survivor = next(item for item in members if entity_ref(item) == partition["survivor"])
        after.append({"survivor": survivor, "members": members, "indexes": indexes})
    return sorted(after, key=lambda group: canonical_bytes(group["survivor"]))


class IdentityCorrectionService:
    def __init__(self, storage, *, policy: MergePolicy):
        if not isinstance(policy, MergePolicy):
            raise StorageError("E_POLICY_INVALID", "A separate host merge policy is required.")
        if policy.scope_id != storage.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        self._storage, self._policy = storage, policy

    @property
    def scope_id(self):
        return self._storage.scope_id

    @property
    def merge_policy(self):
        return self._policy.reference

    def _scope(self, command):
        body = command["body"]
        refs = [command["actor"], command["authority"], *command["expected_revisions"]]
        if command["operation"] == "release_identity_separations":
            refs.extend([*body["separations"], *body["basis"]])
        elif command["operation"] == "merge_matters":
            refs.extend([body["survivor"], *body["merged"], *body["equivalence_basis"]])
        else:
            refs.extend([body["merge_receipt"], *body["basis"]])
            for partition in body["partitions"]:
                refs.extend([partition["matter"], *partition["members"], *partition.get("identity_members", [])])
        if command["scope_id"] != self.scope_id or any(item["scope_id"] != self.scope_id for item in refs):
            raise StorageError("E_SCOPE_FORBIDDEN")

    def prepare(self, command):
        command = _command(command)
        self._scope(command)
        expected = command["expected_revisions"]
        identities = {_identity(item) for item in expected}
        if len(identities) != len(expected):
            raise StorageError("E_SCHEMA_INVALID", "Expected revisions must have distinct identities.")

        def include(reference):
            _scoped(self.scope_id, reference)
            if _identity(reference) not in identities:
                expected.append(deepcopy(reference))
                identities.add(_identity(reference))

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
            command["body"].setdefault("as_of", _now())
            self._state(_ReadCollector(snapshot, include), command)
        return validate_command(command)

    def _current_correction(self, view, reference):
        receipt = read_decision(view, self.scope_id, reference)
        detail = receipt["body"]["details"]["value"]
        if detail["kind"] != "merge":
            raise _conflict("Correction requires the latest governing merge receipt.")
        group = read_group(view, self.scope_id, entity_ref(detail["after"][0]["survivor"]))
        if (not group["indexes"] or any(index["value"]["value"]["decision"] != pin(receipt) for index in group["indexes"])
                or {_identity(member) for member in group["members"]} != {_identity(member) for member in detail["after"][0]["members"]}):
            raise _conflict("An older receipt cannot overwrite an intervening identity decision.")
        return receipt, group

    def _state(self, view, command):
        self._scope(command)
        if command["operation"] == "release_identity_separations":
            return self._release_state(view, command)
        body, scope = command["body"], self.scope_id
        correction = command["operation"] == "correct_merge"
        authority = self._policy.authorize(view, command, correction=correction)
        basis = body["basis"] if correction else body["equivalence_basis"]
        if len({_identity(item) for item in basis}) != len(basis):
            raise _conflict("The equivalence/correction basis must contain distinct identities.")
        for reference in basis:
            read_dependency(view, scope, reference)
        previous = None
        if not correction:
            if body["merge_policy"] != self._policy.reference:
                raise StorageError("E_POLICY_INVALID")
            supplied = [body["survivor"], *body["merged"]]
            if len({_identity(item) for item in supplied}) != len(supplied):
                raise _conflict("Merge operands must be distinct original matter identities.")
            groups = [read_group(view, scope, reference) for reference in supplied]
            if entity_ref(groups[0]["survivor"]) != entity_ref(body["survivor"]):
                raise _conflict("The declared survivor must be its group's current representative.")
            if len({_identity(group["survivor"]) for group in groups}) != len(groups):
                raise _conflict("The merge operands already belong to the same identity group.")
            members = [member for group in groups for member in group["members"]]
            partitions = [{"survivor": entity_ref(groups[0]["survivor"]), "members": members}]
        else:
            previous, current = self._current_correction(view, body["merge_receipt"])
            groups, members = [current], current["members"]
            current_members = {_identity(member): member for member in members}
            partitions, assigned = [], set()
            for declared in body["partitions"]:
                if not declared.get("identity_members"):
                    raise _conflict("Each correction partition requires explicit original identity_members.")
                selected = []
                for reference in declared["identity_members"]:
                    identity = _identity(reference)
                    if identity in assigned or identity not in current_members:
                        raise _conflict("Correction partitions must cover original identities exactly once.")
                    member = current_members[identity]
                    if not _matches(member, reference):
                        raise StorageError("E_REVISION_CONFLICT")
                    assigned.add(identity)
                    selected.append(member)
                if _identity(declared["matter"]) not in {_identity(item) for item in selected}:
                    raise _conflict("Each partition representative must belong to that partition.")
                partitions.append({"survivor": declared["matter"], "members": selected})
            if assigned != set(current_members):
                raise _conflict("Correction partitions omit current group members.")
            if body["correction_kind"] == "undo":
                expected = {_identity(group["survivor"]): {_identity(item) for item in group["members"]}
                            for group in previous["body"]["details"]["value"]["before"]}
                actual = {_identity(group["survivor"]): {_identity(item) for item in group["members"]} for group in partitions}
                if actual != expected:
                    raise _conflict("Undo must restore the exact pre-merge partitions and representatives.")
        if len(members) > MAX_MERGE_MEMBERS:
            raise StorageError("E_BUDGET_EXHAUSTED", "The merge/correction exceeds the supported 128-member bound.")
        inventory = collect_children(view, scope, members)
        separations = _separations(view, scope, members)
        destination = _group_mapping(partitions)
        for separation in separations:
            separation_body = separation["value"]["value"]
            first, second = separation_body["members"]
            if (separation_body["status"] == "protected"
                    and _identity(first) in destination and _identity(second) in destination
                    and destination[_identity(first)] == destination[_identity(second)]):
                raise _conflict("This operation would defeat a protected identity separation.")
        for disposition in inventory["dispositions"]:
            decision = disposition["value"]["value"]
            first, second = decision["subject"], decision["target"]
            if (decision["capability"] == "merge" and decision["status"] == "blocked"
                    and _identity(first) in destination and _identity(second) in destination
                    and destination[_identity(first)] == destination[_identity(second)]):
                raise _conflict("A host merge rejection or protection applies across the complete identity groups.")
        mapping = [{"member": entity_ref(member), "survivor": destination[_identity(member)]} for member in members]
        validate_identity_partition(view, scope, mapping)
        if correction:
            for declared, partition in zip(body["partitions"], partitions):
                identities = {_identity(member) for member in partition["members"]}
                required = _sorted(child["reference"] for child in inventory["children"]
                                   if any(_identity(owner) in identities for owner in child["original_matters"]))
                if len({canonical_bytes(item) for item in declared["members"]}) != len(declared["members"]) or _sorted(declared["members"]) != required:
                    raise _conflict("The correction must retain every current child in each original owner's partition.")
        kind = body["correction_kind"] if correction else "merge"
        address = _decision_ref(scope, command["command_id"], kind)
        if _lookup(view, address) is not None:
            raise StorageError("E_SOURCE_IDENTITY_CONFLICT")
        planned_protections = []
        if correction:
            existing = {_identity(item): item for item in separations}
            for first_group, second_group in combinations(partitions, 2):
                for first, second in product(first_group["members"], second_group["members"]):
                    address = separation_ref(first, second)
                    present = existing.get(_identity(address))
                    if present is None:
                        occupied = _lookup(view, address)
                        if occupied is not None:
                            raise _invalid("A separation occupies an address without its required watches.")
                    write = present is None or present["value"]["value"]["status"] == "released"
                    planned_protections.append({"reference": {**address, "revision": present["revision"] + 1 if present else 1}
                                               if write else pin(present),
                                                "members": _sorted([entity_ref(first), entity_ref(second)]),
                                                "existing": present, "write": write})
        return {"groups": groups, "members": members, "partitions": partitions, "inventory": inventory,
                "separations": separations, "protections": planned_protections,
                "kind": kind, "authority": authority, "previous": previous, "basis": _sorted(basis)}

    def merge(self, command):
        return self._storage.execute(_command(command, "merge_matters"), self._commit)

    def correct(self, command):
        return self._storage.execute(_command(command, "correct_merge"), self._commit)

    def _release_state(self, view, command):
        body, scope = command["body"], self.scope_id
        authority = self._policy.authorize(view, command, correction=True)
        if body["merge_policy"] != self._policy.reference:
            raise StorageError("E_POLICY_INVALID")
        if (len({_identity(item) for item in body["separations"]}) != len(body["separations"])
                or len({_identity(item) for item in body["basis"]}) != len(body["basis"])):
            raise _conflict("Release requires distinct current separations and basis references.")
        if len(body["separations"]) > MAX_MERGE_MEMBERS * (MAX_MERGE_MEMBERS - 1) // 2:
            raise StorageError("E_BUDGET_EXHAUSTED")
        for reference in body["basis"]:
            read_dependency(view, scope, reference)
        records, groups = [], set()
        for reference in body["separations"]:
            current = _lookup(view, entity_ref(reference))
            if current is None:
                raise StorageError("E_NOT_FOUND")
            if not _matches(current, reference):
                raise StorageError("E_REVISION_CONFLICT")
            record = _read_separation(view, scope, current)
            if record["value"]["value"]["status"] != "protected":
                raise _conflict("Only a current protected separation can be released.")
            for member in record["value"]["value"]["members"]:
                if _identity(member) in groups:
                    continue
                group = read_group(view, scope, member)
                groups.update(_identity(item) for item in group["members"])
            records.append(record)
        if _lookup(view, _decision_ref(scope, command["command_id"], "release")) is not None:
            raise StorageError("E_SOURCE_IDENTITY_CONFLICT")
        return {"records": sorted(records, key=lambda item: canonical_bytes(pin(item))), "authority": authority}

    def release_separations(self, command):
        """Release only named barriers; a fresh merge still needs all guards."""
        return self._storage.execute(_command(command, "release_identity_separations"), self._release)

    def _release(self, tx):
        self._scope(tx.command)
        state = self._release_state(tx, tx.command)
        body = tx.command["body"]
        separations = [{"before": pin(record), "after": {**pin(record), "revision": record["revision"] + 1},
                        "members": record["value"]["value"]["members"],
                        "protected_by": record["value"]["value"]["decision"]} for record in state["records"]]
        changes = [{"cause": "disposition_change", "before": [entry["before"]], "after": [entry["after"]]} for entry in separations]
        detail = {"scope_id": self.scope_id, "actor": tx.command["actor"], "authority": state["authority"],
                  "policy": self._policy.reference, "policy_definition": self._policy.definition,
                  "basis": _sorted(body["basis"]), "reason": body["reason"], "as_of": body.get("as_of") or _now(),
                  "separations": separations, "changes": changes}
        parents = _release_parents(detail)
        receipt = tx.insert({"schema_version": "1.0", **_decision_ref(self.scope_id, tx.command["command_id"], "release"),
            "provenance": {"origin": "host", "producer": deepcopy(_ENGINE), "recorded_at": detail["as_of"], "parents": parents},
            "body": {"stage": "authority", "operation_id": tx.command["command_id"], "recorded_at": detail["as_of"],
                     "outcome": "matter:identity_separations_released", "evidence": parents,
                     "details": _domain("identity-release", detail)}})
        read_release(tx, self.scope_id, pin(receipt))
        for original, entry in zip(state["records"], separations):
            value = deepcopy(original["value"]["value"])
            value.update(status="released", decision=pin(receipt), previous=pin(original))
            updated = tx.put_projection(entity_ref(original), _domain("identity-separation", value),
                                        watch_keys=tuple(original["watch_keys"]))
            if pin(updated) != entry["after"]:
                raise _invalid()
        return tx.success("released", {"separations": [entry["after"] for entry in separations],
                                        "release_receipt": pin(receipt), "changes": changes})

    def _commit(self, tx):
        state = self._state(tx, tx.command)
        groups, partitions, inventory = state["groups"], state["partitions"], state["inventory"]
        before = sorted((_group_view(group) for group in groups), key=lambda group: canonical_bytes(group["survivor"]))
        after = _predict(groups, partitions)
        old_mapping, new_mapping = _group_mapping(groups), _group_mapping(partitions)
        changes = [{"cause": "association_correction",
                    "before": _sorted(ref for group in before for ref in [*group["members"], *group["indexes"]]),
                    "after": _sorted(ref for group in after for ref in [*group["members"], *group["indexes"]])}]
        invalidated, revisioned = set(), set()
        for registration in inventory["registrations"]:
            value = registration["value"]["value"]
            if value["status"] == "current":
                changed = {**pin(registration), "revision": registration["revision"] + 1}
                changes.append({"cause": "association_correction", "before": _sorted([pin(registration), value["reference"]]),
                                "after": [changed]})
                invalidated.update([canonical_bytes(pin(registration)), canonical_bytes(value["reference"])])
                revisioned.add(canonical_bytes(pin(registration)))
        children = []
        for child in inventory["children"]:
            entry = deepcopy(child)
            entry["before"] = _unique(old_mapping[_identity(item)] for item in child["original_matters"])
            entry["after"] = _unique(new_mapping[_identity(item)] for item in child["original_matters"])
            key = canonical_bytes(child["reference"])
            entry["action"] = "invalidated" if key in invalidated else (
                "shared" if len(entry["original_matters"]) > 1 else "retained" if entry["before"] == entry["after"] else "moved")
            entry["record_action"] = "revisioned" if key in revisioned else "retained"
            children.append(entry)
        for protection in state["protections"]:
            if protection["write"]:
                changes.append({"cause": "association_correction",
                                "before": [pin(protection["existing"])] if protection["existing"] else [],
                                "after": [protection["reference"]]})
        detail = {"scope_id": self.scope_id, "kind": state["kind"], "actor": tx.command["actor"],
                  "authority": state["authority"], "policy": self._policy.reference, "policy_definition": self._policy.definition,
                  "basis": state["basis"], "as_of": tx.command["body"].get("as_of") or _now(),
                  "previous": pin(state["previous"]) if state["previous"] else None,
                  "before": before, "after": after, "children": children,
                  "conflicts": conflicts(inventory, state["members"], new_mapping),
                  "protections": _sorted(item["reference"] for item in state["protections"]), "changes": changes}
        parents = _unique([*detail["basis"], *([detail["previous"]] if detail["previous"] else [])])
        receipt = tx.insert({"schema_version": "1.0", **_decision_ref(self.scope_id, tx.command["command_id"], state["kind"]),
            "provenance": {"origin": "host", "producer": deepcopy(_ENGINE), "recorded_at": detail["as_of"], "parents": parents},
            "body": {"stage": "authority", "operation_id": tx.command["command_id"], "recorded_at": detail["as_of"],
                     "outcome": "matter:identity_" + state["kind"], "evidence": parents,
                     "details": _domain("identity-decision", detail)}})
        # All predictions are verified against the actual writes. Storage's
        # rollback boundary includes this proof, every mirror and every hook.
        actual = write_groups(tx, partitions, pin(receipt))
        if sorted((_group_view(group) for group in actual), key=lambda group: canonical_bytes(group["survivor"])) != after:
            raise _invalid()
        for protection in state["protections"]:
            if not protection["write"]:
                continue
            stored = tx.put_projection(entity_ref(protection["reference"]), _domain("identity-separation", {
                "scope_id": self.scope_id, "members": protection["members"], "status": "protected", "decision": pin(receipt),
                "previous": pin(protection["existing"]) if protection["existing"] else None}),
                watch_keys=tuple(sorted(_separation_watch(member) for member in protection["members"])))
            if pin(stored) != protection["reference"]:
                raise _invalid()
        invalidate_dependencies(tx, inventory["registrations"], pin(receipt))
        views = _sorted(reference for group in after for reference in group["indexes"])
        if state["kind"] == "merge":
            survivor = after[0]["survivor"]
            return tx.success("committed", {"survivor": survivor,
                "redirects": _sorted(entity_ref(member) for member in after[0]["members"] if entity_ref(member) != entity_ref(survivor)),
                "merge_receipt": pin(receipt), "identity_views": views, "changes": changes})
        return tx.success("committed", {"matters": _sorted(member for group in after for member in group["members"]),
                "correction_receipt": pin(receipt), "identity_views": views, "changes": changes})

    def resolve(self, matter):
        with self._storage.snapshot() as view:
            return read_group(view, self.scope_id, _ref(matter))["survivor"]

    def view(self, matter):
        with self._storage.snapshot() as snapshot:
            reads = {}
            checked = _ReadCollector(snapshot, lambda reference: reads.setdefault(_identity(reference), deepcopy(reference)))
            group = read_group(checked, self.scope_id, _ref(matter))
            inventory = collect_children(checked, self.scope_id, group["members"])
            result = _group_view(group)
            result["children"] = inventory["children"]
            result["protections"] = _sorted(pin(item) for item in _separations(checked, self.scope_id, group["members"]))
            result["read_set"] = _sorted(reads.values())
            return result

    def historical_view(self, receipt):
        reference = pin(receipt) if "body" in receipt else receipt
        with self._storage.snapshot() as snapshot:
            record = read_decision(snapshot, self.scope_id, reference)
            detail = record["body"]["details"]["value"]
            for group in [*detail["before"], *detail["after"]]:
                mirrors = []
                for reference in [*group["members"], *group["indexes"]]:
                    stored = snapshot.get(reference)
                    if not _matches(stored, reference):
                        raise _invalid()
                    if reference["record_type"] == PROJECTION_TYPE:
                        _validate_projection(stored)
                        value = stored["value"]["value"]
                        expected = group_value(value)
                        if (not _same(stored["value"], expected) or stored["watch_keys"]
                                or stored["creation_receipt"]["scope_id"] != self.scope_id
                                or value.get("scope_id") != self.scope_id
                                or entity_ref(stored) != group_ref(value["member"])
                                or value.get("survivor") != entity_ref(group["survivor"])
                                or value.get("members") != _sorted(entity_ref(item) for item in group["members"])):
                            raise _invalid()
                        mirrors.append(stored)
                if mirrors:
                    decision = read_decision(snapshot, self.scope_id, mirrors[0]["value"]["value"]["decision"])
                    frozen = decision["body"]["details"]["value"]
                    selected = [entry for entry in frozen["after"]
                                if entity_ref(entry["survivor"]) == entity_ref(group["survivor"])
                                and entry["indexes"] == group["indexes"]]
                    if len(selected) != 1 or any(
                        mirror["value"]["value"]["decision"] != pin(decision) for mirror in mirrors
                    ):
                        raise _invalid()
            for child in detail["children"]:
                stored = snapshot.get(child["reference"])
                if not _matches(stored, child["reference"]):
                    raise _invalid()
            # Receipt identity is part of historical meaning. A copied receipt
            # must not claim a different operation's old member/mirror writes.
            for group in detail["after"]:
                for reference in [*group["members"], *group["indexes"]]:
                    if entity_ref(snapshot.receipt_for(reference)) != record["creation_receipt"]:
                        raise _invalid("The historical identity snapshots belong to another committing receipt.")
                for reference in group["indexes"]:
                    mirror = snapshot.get(reference)
                    if mirror["value"]["value"]["decision"] != pin(record):
                        raise _invalid()
            for change in detail["changes"][1:]:
                for reference in change["after"]:
                    current = snapshot.get(reference)
                    if entity_ref(snapshot.receipt_for(reference)) != record["creation_receipt"]:
                        raise _invalid()
                    if current["namespace"] == DEPENDENCY_NAMESPACE:
                        checked = read_registration(snapshot, self.scope_id, reference)
                        if checked["value"]["value"]["invalidation"] != pin(record):
                            raise _invalid()
                    elif current["namespace"] == SEPARATION_NAMESPACE:
                        checked = _read_separation(snapshot, self.scope_id, current)
                        if checked["value"]["value"]["decision"] != pin(record):
                            raise _invalid()
                    else:
                        raise _invalid()
            return deepcopy(detail)

    def separation_history(self, separation):
        """Verify every protected/released snapshot and its actual commit."""
        reference = _scoped(self.scope_id, entity_ref(separation), "entity_ref")
        if reference["record_type"] != PROJECTION_TYPE or reference["namespace"] != SEPARATION_NAMESPACE:
            raise StorageError("E_SCHEMA_INVALID")
        with self._storage.snapshot() as snapshot:
            current = _lookup(snapshot, reference)
            if current is None:
                raise StorageError("E_NOT_FOUND")
            history = snapshot.history(reference)
            if type(history) is not list or len(history) != current["revision"]:
                raise _invalid()
            if len(history) > 4096:
                raise StorageError("E_BUDGET_EXHAUSTED", "The explicit separation history exceeds its traversal bound.")
            previous, verified = None, []
            for revision, raw in enumerate(history, start=1):
                record = _read_separation(snapshot, self.scope_id, raw)
                body = record["value"]["value"]
                if (entity_ref(record) != reference or record["revision"] != revision
                        or record["creation_receipt"] != current["creation_receipt"]
                        or body["previous"] != (pin(previous) if previous else None)
                        or previous is not None and body["status"] == previous["value"]["value"]["status"]):
                    raise _invalid()
                decision = (read_decision(snapshot, self.scope_id, body["decision"])
                            if body["status"] == "protected" else read_release(snapshot, self.scope_id, body["decision"]))
                if entity_ref(snapshot.receipt_for(pin(record))) != decision["creation_receipt"]:
                    raise _invalid()
                verified.append(record)
                previous = record
            if not _same(verified[-1], current):
                raise _invalid()
            return deepcopy(verified)

    def plan_correction(self, merge_receipt, *, partitions=None, correction_kind="undo"):
        """Build explicit current partition membership for review/preparation.

        An omitted partition list restores the receipt's original groups.
        Explicit lists name original matters, with each first item the desired
        representative. This helper does not authorize or execute correction.
        """
        if correction_kind not in {"undo", "split"}:
            raise StorageError("E_SCHEMA_INVALID")
        reference = pin(merge_receipt) if "body" in merge_receipt else merge_receipt
        with self._storage.snapshot() as view:
            receipt, group = self._current_correction(view, reference)
            inventory = collect_children(view, self.scope_id, group["members"])
            current = {_identity(member): member for member in group["members"]}
            if partitions is None:
                old_groups = receipt["body"]["details"]["value"]["before"]
                partitions = [[entity_ref(old["survivor"]), *[entity_ref(item) for item in old["members"]
                              if entity_ref(item) != entity_ref(old["survivor"])]] for old in old_groups]
            if not isinstance(partitions, (list, tuple)) or len(partitions) < 2:
                raise _conflict("A correction requires at least two nonempty identity partitions.")
            result, assigned = [], set()
            for partition in partitions:
                if not isinstance(partition, (list, tuple)) or not partition:
                    raise _conflict("Each identity partition must be nonempty.")
                refs = [_scoped(self.scope_id, entity_ref(item), "matter_ref") for item in partition]
                identities = {_identity(item) for item in refs}
                if len(identities) != len(refs) or assigned & identities or not identities <= set(current):
                    raise _conflict("Partition identities must be original, disjoint group members.")
                assigned.update(identities)
                result.append({"matter": refs[0], "identity_members": _sorted(pin(current[_identity(item)]) for item in refs),
                    "members": _sorted(child["reference"] for child in inventory["children"]
                                       if any(_identity(owner) in identities for owner in child["original_matters"]))})
            if assigned != set(current):
                raise _conflict("Partition identities must cover the complete current group.")
            return result
