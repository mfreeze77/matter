"""Existing core indexes composed into an explicit, guarded identity view.

Original ownership and evidence snapshots survive logical owner changes. This
module reuses the claim, citation, association and relationship proof readers;
it neither invents source semantics nor rewrites their historical endpoints.
"""

from __future__ import annotations

from copy import deepcopy

from . import claims, evidence_relations
from .associations import AssociationReader
from .canonical import canonical_bytes
from .contracts import validate_record
from .identity_dependencies import (
    _identity, _invalid, _lookup, _matches, _sorted, collect_dependencies,
)
from .identity_keys import read_binding
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .storage.base import _validate_fragment, _validate_projection


MAX_CHILDREN = 4096


def collect_children(view, scope, members):
    """Return current ownership indexes and their exact retained references.

    Immutable receipts can cite an older mutable evidence snapshot. Its pin is
    retained as cited; reading today's occupant guards concurrent changes but
    never silently refreshes that historical citation. Existing service indexes
    and explicitly registered host derivatives define this inventory's coverage.
    """
    from .relations import collect_relations

    originals = {_identity(member): entity_ref(member) for member in members}
    entries, records, dispositions, indexes = {}, {}, {}, {}

    def add(reference, owners, *, record=None):
        reference = _validate_fragment(reference, "pinned_ref")
        if reference["scope_id"] != scope:
            raise StorageError("E_SCOPE_FORBIDDEN")
        owners = {_identity(owner): entity_ref(owner) for owner in owners if _identity(owner) in originals}
        if not owners:
            return
        key = canonical_bytes(reference)
        if key not in entries:
            if len(entries) >= MAX_CHILDREN:
                raise StorageError("E_BUDGET_EXHAUSTED", "The identity child inventory exceeds its supported bound.")
            entries[key] = {"reference": deepcopy(reference), "original_matters": []}
        merged = {_identity(owner): owner for owner in entries[key]["original_matters"]}
        merged.update(owners)
        entries[key]["original_matters"] = _sorted(merged.values())
        if record is not None:
            records[key] = record

    def evidence(reference, owners):
        if reference["scope_id"] != scope:
            raise StorageError("E_SCOPE_FORBIDDEN")
        stored = _lookup(view, entity_ref(reference))
        if stored is None or entity_ref(stored) != entity_ref(reference):
            raise _invalid("A retained child references missing or incompatible evidence.")
        if stored["record_type"] == PROJECTION_TYPE:
            _validate_projection(stored)
        else:
            validate_record(stored)
        add(reference, owners, record=stored if _matches(stored, reference) else None)
        # An occurrence is a grouping of original observations, not an extra
        # independent report. Only inspect its body when this is the cited pin.
        if stored["record_type"] == "occurrence" and _matches(stored, reference):
            for observation in stored["body"]["observations"]:
                evidence(observation, owners)

    association_reader = AssociationReader(scope)
    for member in members:
        owner = entity_ref(member)
        for key in member["body"]["identity_keys"]:
            binding = read_binding(view, scope, key)
            if binding is None or owner not in binding["value"]["value"]["matters"]:
                raise _invalid("The original matter's exact key binding is unavailable.")
            add(pin(binding), [owner], record=binding)
            indexes[_identity(binding)] = binding
        for watched in view.watchers(claims._subject_watch(scope, owner)):
            claim = claims._from_projection(view, scope, watched)
            if canonical_bytes(claim["body"]["subject"]) != canonical_bytes(owner):
                raise _invalid()
            add(pin(claim), [owner], record=claim)
            add(pin(watched), [owner], record=watched)
            indexes[_identity(watched)] = watched
            for source in claim["body"]["attribution"]:
                evidence(source, [owner])
            for relation_index in view.watchers(evidence_relations._watch(pin(claim), "claim")):
                try:
                    reference = relation_index["value"]["value"]["relation"]
                    _validate_fragment(reference, "evidence_relation_dependency")
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise _invalid() from None
                stored = _lookup(view, entity_ref(reference))
                if stored is None or not _matches(stored, reference):
                    raise _invalid()
                relation = evidence_relations._stored_relation(view, scope, stored)
                checked = evidence_relations._read_index(view, relation)
                if (canonical_bytes(checked) != canonical_bytes(relation_index)
                        or relation["body"]["claim"] != pin(claim)):
                    raise _invalid()
                add(pin(relation), [owner], record=relation)
                add(pin(checked), [owner], record=checked)
                indexes[_identity(checked)] = checked
                evidence(relation["body"]["evidence"], [owner])
        related = association_reader.for_member(view, owner)
        for disposition in related["dispositions"]:
            dispositions[_identity(disposition)] = disposition
            add(pin(disposition), [owner], record=disposition)
        for index in related["indexes"]:
            indexes[_identity(index)] = index
            add(pin(index), [owner], record=index)
        for association in related["associations"]:
            add(pin(association), [owner], record=association)
            for endpoint in association["body"]["members"]:
                if endpoint["record_type"] != "matter":
                    evidence(endpoint, [owner])
    links = collect_relations(view, scope, members)
    for link in links["records"]:
        owners = [entity_ref(link["body"][name]) for name in ("from_matter", "to_matter")]
        add(pin(link), owners, record=link)
    for index in links["indexes"]:
        # A link index is retained with its declared endpoint owners.
        body = index["value"]["value"]
        associated = [record for record in links["records"]
                      if canonical_bytes(pin(record)) == canonical_bytes(body["relation"])]
        if len(associated) != 1:
            raise _invalid("The typed relation index does not bind one retained relation.")
        link = associated[0]
        owners = [entity_ref(link["body"][name]) for name in ("from_matter", "to_matter")]
        add(pin(index), owners, record=index)
        indexes[_identity(index)] = index
    registrations = collect_dependencies(view, scope, members)
    for registration in registrations:
        body = registration["value"]["value"]
        owners = body["original_matters"]
        add(pin(registration), owners, record=registration)
        evidence(body["reference"], owners)
        indexes[_identity(registration)] = registration
    return {"children": [entries[key] for key in sorted(entries)], "records": records,
            "dispositions": _sorted(dispositions.values()), "indexes": _sorted(indexes.values()),
            "registrations": registrations}


def conflicts(inventory, members, destination):
    """Report mechanical overlap without deciding whether a claim is true."""
    findings = []
    grouped_claims, grouped_associations, grouped_links = {}, {}, {}
    for key, record in inventory["records"].items():
        kind, body = record["record_type"], record.get("body", {})
        if kind == "claim":
            subject = body["subject"]
            if "schema" not in subject and _identity(subject) in destination:
                signature = canonical_bytes([destination[_identity(subject)], body["predicate"]])
                grouped_claims.setdefault(signature, []).append(pin(record))
        elif kind == "accepted_association":
            endpoints = [destination.get(_identity(item), entity_ref(item)) for item in body["members"]]
            relation = {name: body["relation"][name] for name in ("namespace", "id")}
            signature = canonical_bytes([endpoints, relation, body["capability"]])
            grouped_associations.setdefault(signature, []).append(pin(record))
        elif kind == "matter_relation":
            endpoints = [destination.get(_identity(body[name]), entity_ref(body[name]))
                         for name in ("from_matter", "to_matter")]
            signature = canonical_bytes([endpoints, body["relation_kind"]])
            grouped_links.setdefault(signature, []).append(pin(record))
    for collection, kind, reason in (
        (grouped_claims, "overlapping_claims", "Assertions share an effective subject and predicate; every original assertion remains available for assessment."),
        (grouped_associations, "overlapping_associations", "Attachments have overlapping effective endpoints; both decisions and their original evidence are retained."),
        (grouped_links, "overlapping_links", "Typed links have overlapping effective endpoints; neither original relationship is deleted."),
    ):
        for refs in collection.values():
            if len(refs) > 1:
                findings.append({"kind": kind, "references": _sorted(refs), "reason": reason})
    member_map = {_identity(member): member for member in members}
    for child in inventory["children"]:
        if child["reference"]["record_type"] in {"observation", "occurrence"} and len(child["original_matters"]) > 1:
            findings.append({"kind": "shared_evidence", "references": _sorted([
                child["reference"], *(pin(member_map[_identity(item)]) for item in child["original_matters"])]),
                "reason": "The same evidence snapshot contributes to more than one original matter; merging does not create independent corroboration."})
    metadata = {}
    for member in members:
        metadata.setdefault(canonical_bytes(destination[_identity(member)]), []).append(member)
    for group in metadata.values():
        values = {canonical_bytes({key: member["body"].get(key) for key in
                                   ("title", "description", "domain_kind", "lifecycle")}) for member in group}
        if len(values) > 1:
            findings.append({"kind": "metadata_difference", "references": _sorted(pin(member) for member in group),
                "reason": "Original descriptions, kinds or lifecycle values differ; the survivor supplies a display identity without resolving these differences."})
    return _sorted(findings)
