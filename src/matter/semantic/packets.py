"""MAT-028: bounded source-linked packets over explicit authorized snapshots.

No candidate discovery, source fetching, provider invocation or host mutation
occurs here. Audit omissions stay separate from the model-visible state.
"""

from __future__ import annotations

from copy import deepcopy

from .._rule_values import FrozenValue, bounded, checked, descriptor, fragment, same, unique
from ..canonical import canonical_bytes, canonical_digest, source_digest
from ..citations import verify_locator_validation
from ..contracts import ContractError, validate_record
from ..provenance_groups import resolve_groups
from ..storage import StorageError, pin
from ..time import compare_times, knowledge_eligible


MAX_PACKET_BYTES = 1_048_576
MAX_CANDIDATES = 128


def _fail(detail="The semantic packet does not satisfy its declared contract.", code="E_EVIDENCE_INVALID"):
    raise ContractError(code, detail)


def preparation_reference():
    definition = {"algorithm": "matter.semantic.packet-preparation.v1",
                  "selection": "mandatory-first-canonical-pin", "availability": "inclusive-known-cut",
                  "text": "exact-whole-utf8-or-validated-quotation", "overflow": "whole-source-omission",
                  "lineage": "existing-resolve-groups-with-receipt-cut", "audit": "separate-from-model-state",
                  "mechanical": "exact-times-counts-and-identifier-equality"}
    return descriptor("matter", "semantic-packet-preparation", "1.0", definition,
                      "matter.semantic.packet-preparation.v1")


class PacketProfile(FrozenValue):
    """Immutable preparation semantics; no policy/source text is executable."""
    __slots__ = ()

    def __init__(self, value):
        data = checked(value, required=("namespace", "id", "version", "required_roles", "allowed_origins",
                                       "locator_adapters", "max_sources", "max_source_bytes", "max_packet_bytes"))
        for field, kind in (("namespace", "namespace"), ("id", "identifier"), ("version", "text")):
            fragment(data[field], kind)
        for field, kind in (("required_roles", "namespaced_name"), ("allowed_origins", "text"), ("locator_adapters", "component_ref")):
            data[field] = unique([fragment(item, kind) for item in bounded(data[field], 32)])
        if not data["allowed_origins"] or not set(data["allowed_origins"]) <= {"source", "adapter", "host", "system", "derived", "evaluator"}:
            _fail("An explicit allowed-origin set is required.", "E_POLICY_INVALID")
        if not data["locator_adapters"]:
            _fail("An explicit admitted locator adapter is required.", "E_POLICY_INVALID")
        for field, limit in (("max_sources", MAX_CANDIDATES), ("max_source_bytes", MAX_PACKET_BYTES), ("max_packet_bytes", MAX_PACKET_BYTES)):
            if type(data[field]) is not int or not 1 <= data[field] <= limit:
                _fail("An explicit supported packet resource bound is required.", "E_POLICY_INVALID")
        if data["max_source_bytes"] > data["max_packet_bytes"]:
            _fail("The source byte bound exceeds the packet byte bound.", "E_POLICY_INVALID")
        self._freeze(data)

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["version"], value,
                          "matter.semantic.packet-profile.v1")


class PreparedPacket(FrozenValue):
    """Detached selected state and separately retained exact audit manifest."""
    __slots__ = ()

    def __init__(self, value, *, _prepared=False):
        if not _prepared:
            _fail("Use prepare_packet to create a prepared source packet.", "E_POLICY_INVALID")
        self._freeze(value)

    @property
    def state(self):
        return self.value["state"]

    @property
    def canonical(self):
        return canonical_bytes(self.state)

    @property
    def digest(self):
        return canonical_digest(self.state, "matter.semantic.packet.v1")

    @property
    def source_manifest(self):
        return self.value["source_manifest"]

    @property
    def audit_digest(self):
        return canonical_digest(self.value, "matter.semantic.packet-audit.v1")


class _Reads:
    def __init__(self, view, scope):
        self.view, self.scope, self.pins = view, scope, {}

    def remember(self, record):
        reference = pin(record)
        if reference["scope_id"] != self.scope:
            _fail(code="E_SCOPE_FORBIDDEN")
        self.pins[canonical_bytes(reference)] = reference
        return record

    def get(self, reference):
        reference = fragment(reference, "pinned_ref")
        if reference["scope_id"] != self.scope:
            _fail(code="E_SCOPE_FORBIDDEN")
        record = self.remember(self.view.get(reference))
        if not same(pin(record), reference):
            _fail("The authorized view returned a different exact snapshot.")
        return record

    def lookup_identity(self, reference):
        if reference["scope_id"] != self.scope:
            _fail(code="E_SCOPE_FORBIDDEN")
        return self.remember(self.view.lookup_identity(reference))

    def receipt_for(self, reference):
        return self.remember(self.view.receipt_for(reference))


def _known_record(reads, reference, boundary):
    record = validate_record(reads.get(reference))
    if record["record_type"] == "observation":
        return record, knowledge_eligible(record["body"]["available_at"], boundary)
    if knowledge_eligible(record["provenance"]["recorded_at"], boundary) is not True:
        return record, False
    receipt = validate_record(reads.receipt_for(reference))
    return record, knowledge_eligible(receipt["provenance"]["recorded_at"], boundary)


def _binding(reads, value, boundary):
    if type(value) is not dict:
        _fail(code="E_SCHEMA_INVALID")
    if value.get("kind") == "claim":
        data = checked(value, required=("kind", "claim"))
        reference = fragment(data["claim"], "claim_dependency")
        record, known = _known_record(reads, reference, boundary)
        if known is not True:
            _fail("The bound claim was unavailable at the knowledge cut.", "E_EVIDENCE_UNAVAILABLE")
        return {"kind": "claim", "claim": reference, "proposition": deepcopy(record["body"])}
    if value.get("kind") == "candidate_relation":
        data = checked(value, required=("kind", "left", "right", "relation"))
        fragment(data["relation"], "namespaced_name")
        for name in ("left", "right"):
            reference = fragment(data[name], "pinned_ref")
            if reference["record_type"] not in {"observation", "occurrence", "matter"}:
                _fail("A candidate endpoint must be an observation, occurrence or matter.")
            _, known = _known_record(reads, reference, boundary)
            if known is not True:
                _fail("A candidate endpoint was unavailable at the knowledge cut.", "E_EVIDENCE_UNAVAILABLE")
            data[name] = reference
        return data
    _fail("A claim or candidate-relation binding is required.", "E_SCHEMA_INVALID")


def _text(reads, payloads, record, item, adapters, boundary):
    validation = fragment(item["validation"], "domain_value")
    try:
        adapter = validation["value"]["adapter"]
    except (KeyError, TypeError):
        _fail()
    if adapter not in adapters:
        _fail("The locator adapter is not admitted by the packet profile.")
    declaration = verify_locator_validation(validation, evidence=record, locator=item["locator"],
                                             quotation=item["quotation"], adapter=adapter)
    for dependency in declaration["dependencies"]:
        stored = reads.get(dependency)
        if stored["record_type"] == "observation":
            known = knowledge_eligible(stored["body"]["available_at"], boundary)
        else:
            try:
                receipt = validate_record(reads.receipt_for(dependency))
                known = knowledge_eligible(receipt["provenance"]["recorded_at"], boundary)
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
                known = False
        if known is not True:
            return None, "locator_dependency_not_available_at_cut"
    if declaration["result"]["status"] != "valid":
        return None, "locator_" + declaration["result"]["status"]
    content = record["body"]["content"]
    result = payloads.read(content)
    if result.status != "available":
        return None, "payload_" + result.status
    raw = result.data
    if type(raw) is not bytes or result.digest != content["digest"] or source_digest(raw) != content["digest"] or ("byte_length" in content and len(raw) != content["byte_length"]):
        _fail("Payload bytes do not match their original source reference.")
    if item["locator"]["kind"] == "selected_span":
        # The admitted adapter binds the exact locator and quotation; preserve
        # that quotation rather than inventing a different excerpt boundary.
        return item["quotation"], None
    try:
        return raw.decode("utf-8", errors="strict"), None
    except UnicodeDecodeError:
        return None, "unsupported_text_encoding"


def _groups(reads, scope, references, boundary):
    if not references:
        return {"groups": [], "unresolved": [], "available": True}
    resolution = resolve_groups(reads, scope, references, max_nodes=MAX_CANDIDATES)
    available = True
    for dependency in resolution["dependencies"]:
        stored = reads.get(dependency)
        if stored["record_type"] == "observation":
            known = knowledge_eligible(stored["body"]["available_at"], boundary)
        else:
            try:
                receipt = validate_record(reads.receipt_for(dependency))
                known = knowledge_eligible(receipt["provenance"]["recorded_at"], boundary)
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
                known = False
        if known is not True:
            available = False
    return {"groups": resolution["groups"] if available else [],
            "unresolved": resolution["unresolved"] if available else [], "available": available}


def _mechanical(selected, occurrence_refs, provenance):
    refs = [item["reference"] for item in selected]
    counts = {"observations": len(refs), "occurrences": len(occurrence_refs),
              "provenance_groups": len(provenance["groups"])}
    inputs = [{"reference": item["reference"], "source_identity": item["source_identity"],
               "available_at": item["available_at"], "occurred_at": item["occurred_at"],
               "occurred_interval": item["occurred_interval"]} for item in selected]
    matches, dates = [], []
    for i, left in enumerate(selected):
        for right in selected[i + 1:]:
            matches.append({"left": left["reference"], "right": right["reference"],
                            "same_source_event": all(left["source_identity"][key] == right["source_identity"][key] for key in ("namespace", "event_id")),
                            "same_source_revision": left["source_identity"] == right["source_identity"]})
            dates.append({"left": left["reference"], "right": right["reference"],
                          "availability_order": compare_times(left["available_at"], right["available_at"]),
                          "event_order": compare_times(left["occurred_at"], right["occurred_at"])})
    return {"inputs": inputs, "counts": counts, "occurrence_inputs": occurrence_refs,
            "provenance_inputs": provenance["groups"], "identifier_matches": matches, "date_comparisons": dates}


def prepare_packet(view, profile, *, payloads, scope_id, binding, as_of, evidence=(), occurrences=(), coverage,
                   access=None, access_context=None):
    """Prepare one exact bounded snapshot from explicitly supplied references.

    The host opens a consistent authorized read view and admits locator adapter
    declarations. These inputs confer no authority themselves. Oversized sources
    are omitted whole, never silently chopped into an apparently complete text.
    """
    if not isinstance(profile, PacketProfile):
        _fail("A validated immutable packet profile is required.", "E_POLICY_INVALID")
    scope = fragment(scope_id, "identifier")
    if payloads.scope_id != scope:
        _fail(code="E_SCOPE_FORBIDDEN")
    boundary, supplied_coverage = fragment(as_of, "known_time"), fragment(coverage, "coverage")
    admitted_access = None
    if access is not None:
        if access_context is None:
            _fail("The installed access boundary requires its original context.", "E_AUTHORITY_REQUIRED")
        admitted_access = access.require_current(view, access_context)
        view = access.view(view, admitted_access)
    elif access_context is not None:
        _fail("An access context requires its installed host boundary.", "E_AUTHORITY_REQUIRED")
    definition = profile.value
    reads = _Reads(view, scope)
    bound = _binding(reads, binding, boundary)
    candidates, seen = [], set()
    for raw in bounded(evidence, MAX_CANDIDATES):
        item = checked(raw, required=("reference", "roles", "locator", "quotation", "validation"))
        ref = fragment(item["reference"], "observation_dependency")
        if ref["scope_id"] != scope:
            _fail(code="E_SCOPE_FORBIDDEN")
        key = canonical_bytes(ref)
        if key in seen:
            _fail("An evidence snapshot may be supplied only once.", "E_SCHEMA_INVALID")
        seen.add(key)
        item["reference"] = ref
        item["roles"] = sorted(unique([fragment(role, "namespaced_name") for role in bounded(item["roles"], 32)]))
        item["mandatory"] = bool(set(item["roles"]) & set(definition["required_roles"]))
        candidates.append(item)
    candidates.sort(key=lambda item: (not item["mandatory"], canonical_bytes(item["reference"])))
    selected, omitted, truncated = [], [], []
    base = {"scope_id": scope, "as_of": boundary, "binding": bound, "profile": profile.reference,
            "preparation": preparation_reference()}
    if admitted_access is not None:
        base["access_context"] = admitted_access.reference

    def omit(item, reason):
        entry = {"reference": item["reference"], "roles": item["roles"], "mandatory": item["mandatory"], "reason": reason}
        omitted.append(entry)
        if reason in {"source_byte_limit", "packet_byte_limit", "source_count_limit"}:
            truncated.append(entry)

    for item in candidates:
        try:
            record, known = _known_record(reads, item["reference"], boundary)
        except StorageError as error:
            if error.code != "E_NOT_FOUND":
                raise
            omit(item, "source_not_found")
            continue
        if known is not True:
            omit(item, "not_yet_available" if known is False else "unknown_availability")
            continue
        if record["provenance"]["origin"] not in definition["allowed_origins"]:
            omit(item, "ineligible_origin")
            continue
        text, reason = _text(reads, payloads, record, item, definition["locator_adapters"], boundary)
        if reason:
            omit(item, reason)
            continue
        if len(text.encode("utf-8")) > definition["max_source_bytes"]:
            omit(item, "source_byte_limit")
            continue
        if len(selected) >= definition["max_sources"]:
            omit(item, "source_count_limit")
            continue
        event_time = record["body"].get("occurred_at", {"state": "unknown", "reason": "not_reported"})
        entry = {"reference": item["reference"], "roles": item["roles"], "locator": deepcopy(item["locator"]),
                 "text": text, "text_digest": source_digest(text.encode("utf-8")),
                 "validation": deepcopy(item["validation"]), "source_identity": record["body"]["source_identity"],
                 "available_at": record["body"]["available_at"], "occurred_at": event_time,
                 "occurred_interval": deepcopy(record["body"].get("occurred_interval"))}
        # Final mechanical/coverage overhead is checked again below. This early
        # check bounds provisional source payloads without guessing full size.
        if len(canonical_bytes({**base, "evidence": selected + [entry]})) > definition["max_packet_bytes"]:
            omit(item, "packet_byte_limit")
            continue
        selected.append(entry)

    occurrence_records, historical_omissions = [], []
    candidate_refs = [item["reference"] for item in candidates]
    for ref in sorted(unique([fragment(item, "occurrence_dependency") for item in bounded(occurrences, MAX_CANDIDATES)]), key=canonical_bytes):
        record, known = _known_record(reads, ref, boundary)
        if not any(reference in record["body"]["observations"] for reference in candidate_refs):
            _fail("A supplied occurrence has no candidate observation membership.")
        if known is not True:
            historical_omissions.append({"reference": ref, "reason": "grouping_not_available_at_cut"})
        else:
            occurrence_records.append((ref, record))
    occurrence_records.sort(key=lambda pair: canonical_bytes(pair[0]))

    def assemble():
        selected_refs = [item["reference"] for item in selected]
        occurrence_refs, occurrence_omissions = [], deepcopy(historical_omissions)
        for ref, record in occurrence_records:
            if any(reference in record["body"]["observations"] for reference in selected_refs):
                occurrence_refs.append(ref)
            else:
                occurrence_omissions.append({"reference": ref, "reason": "cohort_not_selected"})
        provenance = _groups(reads, scope, selected_refs, boundary)
        included_roles = {role for item in selected for role in item["roles"]}
        missing_roles = sorted(set(definition["required_roles"]) - included_roles)
        complete = (supplied_coverage["status"] == "complete" and not missing_roles and
                    not any(item["mandatory"] for item in omitted) and not occurrence_omissions and
                    provenance["available"] and not provenance["unresolved"])
        verdict = {"status": "complete" if complete else "incomplete", "missing_roles": missing_roles,
                   "mandatory_omissions": sum(item["mandatory"] for item in omitted),
                   "provenance_status": "complete" if provenance["available"] and not provenance["unresolved"] else "incomplete",
                   "occurrence_status": "incomplete" if occurrence_omissions else "explicit_supplied_set",
                   "source_coverage": supplied_coverage}
        state = {**base, "evidence": deepcopy(selected), "coverage": verdict,
                 "mechanical": _mechanical(selected, occurrence_refs, provenance)}
        return state, occurrence_omissions, provenance

    state, occurrence_omissions, provenance = assemble()
    while len(canonical_bytes(state)) > definition["max_packet_bytes"]:
        if not selected:
            _fail("Packet metadata exceeds the declared total byte bound.", "E_BUDGET_EXHAUSTED")
        removed = selected.pop()
        item = next(candidate for candidate in candidates if candidate["reference"] == removed["reference"])
        omit(item, "packet_byte_limit")
        state, occurrence_omissions, provenance = assemble()
    source_manifest = {"included": [{"reference": item["reference"], "roles": item["roles"], "locator": item["locator"],
                                      "text_digest": item["text_digest"]} for item in selected],
                       "excluded": omitted,
                       "truncation": {"status": "truncated" if truncated else "complete", "omitted_sources": truncated,
                                      "max_sources": definition["max_sources"], "max_source_bytes": definition["max_source_bytes"],
                                      "max_packet_bytes": definition["max_packet_bytes"]}}
    audit = {"state": state, "source_manifest": source_manifest, "occurrence_omissions": occurrence_omissions,
             "provenance_omissions": provenance["unresolved"] if provenance["available"] else [{"reason": "provenance_not_available_at_cut"}],
             "dependencies": [reads.pins[key] for key in sorted(reads.pins)],
             "limits": ["Host source roles, scope permission and adapter admission are declarations, not source truth.",
                        "Availability filtering does not establish model ignorance of later facts.",
                        "Occurrence inputs are the explicit supplied set, not discovered complete membership."]}
    if len(canonical_bytes(audit)) > 4 * MAX_PACKET_BYTES:
        _fail(code="E_BUDGET_EXHAUSTED")
    if access is not None:
        access.require_packet(view._view, admitted_access, state)
    return PreparedPacket(audit, _prepared=True)
