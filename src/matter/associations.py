"""Frozen association proposals and separately authorized attachment decisions.

Candidate catalogs are published explicitly by the host. Completeness is
relative to that declared query, not all possible external candidates. The
service performs no provider call, payload read, ranking, merge or lifecycle
transition. Prepare once and retain the exact command for durable retries.
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

from .association_policy import AssociationPolicy
from .candidate_sets import (
    CANDIDATE_NAMESPACE, build_candidate_snapshot, candidate_set_ref,
    candidate_set_value, exact_candidates, matches, read_candidate_set,
    read_dependency, read_member, require_current_candidates, unavailable_evidence,
)
from .canonical import canonical_bytes, canonical_digest, source_digest
from .contracts import ContractError, _FORMAT_CHECKER, command_digest, schema_for, validate_command, validate_record
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .storage.base import _validate_fragment, _validate_projection


PROPOSAL_NAMESPACE = "matter.association_proposals"
RECEIPT_NAMESPACE = "matter.association_receipts"
ASSOCIATION_NAMESPACE = "matter.associations"
DISPOSITION_NAMESPACE = "matter.association_dispositions"
MEMBERSHIP_NAMESPACE = "matter.association_memberships"
_OPERATIONS = {"publish_association_candidates", "propose_association", "accept_association", "decide_association"}
_ENGINE = {"namespace": "matter", "id": "association-service", "version": "1.0",
           "digest": canonical_digest({"algorithm": "frozen-catalog-host-acceptance", "version": "1.0"},
                                      "matter.association-service.v1")}

__all__ = ["AssociationPolicy", "AssociationService", "association_ref", "disposition_ref"]


def _invalid(detail="The association record or decision binding could not be verified."):
    return StorageError("E_EVIDENCE_INVALID", detail)


def _now():
    return {"state": "known", "value": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "precision": "microsecond"}


def _scoped(scope, value, fragment="pinned_ref"):
    ref = _validate_fragment(value, fragment)
    if ref["scope_id"] != scope:
        raise StorageError("E_SCOPE_FORBIDDEN")
    return ref


def _lookup(view, reference):
    try:
        return view.lookup_identity(reference)
    except StorageError as error:
        if error.code == "E_NOT_FOUND":
            return None
        raise


def _identity(value):
    ref = entity_ref(value)
    return ref["scope_id"], ref["namespace"], ref["id"]


def _same(left, right):
    return canonical_bytes(left) == canonical_bytes(right)


@lru_cache(maxsize=4)
def _contract(name):
    try:
        data = files("matter._schemas").joinpath(name + ".schema.json").read_bytes()
        schema = json.loads(data)
        Draft202012Validator.check_schema(schema)
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        return ({"namespace": "matter", "id": name, "version": "1.0", "digest": source_digest(data)},
                Draft202012Validator(schema, registry=registry, format_checker=_FORMAT_CHECKER))
    except (OSError, ValueError, TypeError, KeyError, SchemaError):
        raise StorageError("E_STORAGE_UNAVAILABLE", "The installed association schema is unavailable.") from None


def _domain(name, body):
    descriptor, validator = _contract(name)
    canonical_bytes(body)
    if not validator.is_valid(body):
        raise _invalid()
    return {"schema": deepcopy(descriptor), "value": deepcopy(body)}


def _value(name, value):
    descriptor, validator = _contract(name)
    try:
        domain = _validate_fragment(value, "domain_value")
        if not _same(domain["schema"], descriptor) or not validator.is_valid(domain["value"]):
            raise _invalid()
        return deepcopy(domain["value"])
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def _pair(scope, subject, target, relation, capability):
    scope = _validate_fragment(scope, "identifier")
    first = _scoped(scope, entity_ref(subject), "association_member_ref")
    second = _scoped(scope, entity_ref(target), "association_member_ref")
    component = _validate_fragment(relation, "component_ref")
    if first == second or capability not in {"attach", "relate", "merge"}:
        raise _invalid("Association decisions require distinct members and a declared capability.")
    if capability == "merge":
        first, second = sorted((first, second), key=canonical_bytes)
    # A new relation version, candidate revision or proposal ID must not evade
    # an earlier decision about these same identities and this capability.
    return {"scope_id": scope, "subject": first, "target": second,
            "relation": {key: component[key] for key in ("namespace", "id")}, "capability": capability}


def association_ref(scope_id, subject, target, relation, capability="attach"):
    key = _pair(scope_id, subject, target, relation, capability)
    return {"scope_id": scope_id, "namespace": ASSOCIATION_NAMESPACE, "record_type": "accepted_association",
            "id": "association-" + canonical_digest(key, "matter.association-pair.v1")}


def disposition_ref(scope_id, subject, target, relation, capability="attach"):
    key = _pair(scope_id, subject, target, relation, capability)
    return {"scope_id": scope_id, "namespace": DISPOSITION_NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "disposition-" + canonical_digest(key, "matter.association-pair.v1")}


def _membership_ref(record):
    return {**entity_ref(record), "namespace": MEMBERSHIP_NAMESPACE, "record_type": PROJECTION_TYPE}


def _watch(member, role):
    return "association-" + role + "-" + canonical_digest(entity_ref(member), "matter.association-watch.v1")


def _membership(record):
    body = record["body"]
    return _domain("association-membership", {
        "scope_id": record["scope_id"], "association": pin(record),
        "subject": entity_ref(body["members"][0]), "target": entity_ref(body["members"][1]),
        "relation": body["relation"], "capability": body["capability"],
    })


def _watches(subject, target):
    return tuple(sorted((_watch(subject, "subject"), _watch(target, "target"))))


def _record_ref(scope, command_id, kind):
    return {"scope_id": scope, "namespace": PROPOSAL_NAMESPACE if kind == "proposal" else RECEIPT_NAMESPACE,
            "record_type": "association_proposal" if kind == "proposal" else "receipt",
            "id": kind + "-" + canonical_digest({"scope_id": scope, "command_id": command_id},
                                                "matter.association-" + kind + ".v1")}


def _record(view, scope, reference, kind):
    ref = _scoped(scope, reference)
    stored = view.get(ref)
    try:
        record = validate_record(stored)
        if record["record_type"] != kind or not matches(record, ref) or record["creation_receipt"]["scope_id"] != scope:
            raise _invalid()
        return record
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


def _receipt(view, scope, reference, name, kind):
    receipt = _record(view, scope, reference, "receipt")
    details = _value(name, receipt["body"]["details"])
    body = receipt["body"]
    if (entity_ref(receipt) != _record_ref(scope, body["operation_id"], kind)
            or details["scope_id"] != scope or receipt["provenance"]["producer"] != _ENGINE):
        raise _invalid()
    return receipt, details


def _equivalent(view, scope, left, right):
    return entity_ref(left) == entity_ref(right) and matches(read_dependency(view, scope, left), right)


def _refs_match(view, scope, supplied, expected):
    if len(supplied) != len(expected) or len({_identity(item) for item in supplied}) != len(supplied):
        raise _invalid("The complete frozen candidate and evidence sets must be retained.")
    by_id = {_identity(item): item for item in expected}
    for reference in supplied:
        target = by_id.get(_identity(reference))
        if target is None or not _equivalent(view, scope, reference, target):
            raise _invalid("The supplied references differ from the frozen candidate set.")


class _Collector:
    def __init__(self, view, include):
        self.view, self.include = view, include

    def get(self, reference):
        record = self.view.get(reference)
        self.include(pin(record))
        return record

    def lookup_identity(self, reference):
        record = self.view.lookup_identity(reference)
        self.include(pin(record))
        return record


def _command(value, operation=None):
    command = validate_command(value)
    if command["operation"] not in _OPERATIONS or (operation is not None and command["operation"] != operation):
        raise ContractError("E_SCHEMA_INVALID", "An association operation is required.")
    return command


class AssociationService:
    def __init__(self, storage, *, policy: AssociationPolicy):
        if not isinstance(policy, AssociationPolicy):
            raise StorageError("E_POLICY_INVALID")
        if storage.scope_id != policy.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        self._storage, self._policy = storage, policy

    @property
    def scope_id(self):
        return self._storage.scope_id

    @property
    def acceptance_policy(self):
        return self._policy.reference

    def prepare(self, command):
        command = _command(command)
        expected = command["expected_revisions"]
        identities = {_identity(ref) for ref in expected}
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
            if command["operation"] == "accept_association" and "as_of" not in command["body"]:
                command["body"]["as_of"] = _now()
            self._inspect(_Collector(snapshot, include), command)
        return validate_command(command)

    def _inspect(self, view, command):
        if command["operation"] == "publish_association_candidates":
            return self._publish_state(view, command)
        if command["operation"] == "propose_association":
            return self._proposal_state(view, command)
        if command["operation"] == "accept_association":
            return self._acceptance_state(view, command)
        return self._decision_state(view, command)

    def _publish_state(self, view, command):
        body, scope = command["body"], self.scope_id
        self._policy.authorize(view, command, rule=body["query"]["matching_rule"])
        snapshot = build_candidate_snapshot(view, scope, body, self._policy.reference, command["authority"])
        reference = candidate_set_ref(scope, snapshot["query"])
        existing = _lookup(view, reference)
        previous = body["previous"]
        if existing is None:
            if previous is not None:
                raise StorageError("E_REVISION_CONFLICT")
        else:
            existing = read_candidate_set(view, scope, reference)
            if previous is None or not matches(existing, previous):
                raise StorageError("E_REVISION_CONFLICT", "Publish against the current candidate-set revision.")
        return snapshot, reference, existing

    def publish_candidates(self, command):
        return self._storage.execute(_command(command, "publish_association_candidates"), self._publish)

    def _publish(self, tx):
        snapshot, reference, existing = self._publish_state(tx, tx.command)
        value = candidate_set_value(snapshot)
        if existing is not None and _same(existing["value"], value):
            return tx.success("unchanged", {"candidate_set": pin(existing), "changes": []})
        current = tx.put_projection(reference, value)
        return tx.success("published", {"candidate_set": pin(current), "changes": [
            {"cause": "association_correction" if existing else "new_evidence",
             "before": [pin(existing)] if existing else [], "after": [pin(current)]}]})

    def _proposal_state(self, view, command, *, new_identity=True):
        body, scope = command["body"], self.scope_id
        self._policy.authorize(view, command, rule=body["matching_rule"])
        if "candidate_set" not in body:
            raise _invalid("A published, pinned candidate set is required.")
        catalog = require_current_candidates(view, scope, body["candidate_set"])
        snapshot = catalog["value"]["value"]
        candidates = exact_candidates(catalog)
        if (not _equivalent(view, scope, body["subject"], snapshot["subject"])
                or not _same(body["matching_rule"], snapshot["query"]["matching_rule"])):
            raise _invalid("The proposal must retain its candidate query and subject.")
        _refs_match(view, scope, body["evidence"], snapshot["evidence"])
        _refs_match(view, scope, [item["candidate"] for item in body["candidates"]],
                    [item["candidate"] for item in candidates])
        expected = {_identity(item["candidate"]): item for item in candidates}
        for item in body["candidates"]:
            _refs_match(view, scope, item["basis"], expected[_identity(item["candidate"])]["basis"])
        mode = snapshot["query"]["mode"]
        missing = unavailable_evidence(view, scope, catalog)
        if not snapshot["evidence"] and not any(item["basis"] for item in snapshot["entries"]):
            missing.append("No usable key or matching evidence was declared.")
        if snapshot["coverage"]["status"] != "complete":
            missing.append("The declared candidate query has incomplete coverage.")
        if mode == "exact_keys":
            if "evaluation" in body:
                raise _invalid("An external result cannot override deterministic exact-key nomination.")
            outcome = "insufficient_evidence" if missing else (
                "no_match" if not candidates else "matched" if len(candidates) == 1 else "ambiguous")
            evaluation = {
                "producer": deepcopy(_ENGINE), "outcome": outcome,
                "selected": [candidates[0]["candidate"]] if outcome == "matched" else [],
                "uncertainty": {"schema": deepcopy(body["matching_rule"]),
                                "value": {"status": "deterministic", "algorithm": "any_exact_key"}},
                "qualification": {"status": "not_required", "reason": "Exact declared-key comparison has no learned judgment."},
                "reason": "Compared exact keys within the declared host candidate catalog.", "missing_evidence": missing,
            }
        else:
            if "evaluation" not in body:
                raise _invalid("Semantic proposals require a frozen external evaluation declaration.")
            evaluation = _validate_fragment(body["evaluation"], "association_evaluation")
            if evaluation["outcome"] == "matched" and len(evaluation["selected"]) != 1:
                raise _invalid("This acceptance policy supports exactly one selected candidate.")
            if evaluation["outcome"] == "ambiguous" and len(candidates) < 2:
                raise _invalid("Ambiguity requires at least two considered candidates.")
            for selected in evaluation["selected"]:
                item = expected.get(_identity(selected))
                if item is None or not _equivalent(view, scope, selected, item["candidate"]):
                    raise _invalid("The selected candidate is outside the frozen candidate set.")
            outcome = evaluation["outcome"]
            if missing and outcome != "evaluation_failed":
                outcome = "insufficient_evidence"
        selected = ([expected[_identity(evaluation["selected"][0])]["candidate"]]
                    if outcome == "matched" else [])
        details = {"scope_id": scope, "mode": mode, "subject": snapshot["subject"], "candidate_set": pin(catalog),
                   "candidates": candidates, "matching_rule": snapshot["query"]["matching_rule"],
                   "evidence": snapshot["evidence"], "coverage": snapshot["coverage"],
                   "assessed_as_of": body["assessed_as_of"], "evaluation": evaluation,
                   "outcome": outcome, "selected": selected}
        _domain("association-evaluation", details)
        if new_identity:
            for kind in ("proposal", "evaluation"):
                if _lookup(view, _record_ref(scope, command["command_id"], kind)) is not None:
                    raise StorageError("E_SOURCE_IDENTITY_CONFLICT", "This proposal or evaluation identity is already occupied.")
        return details, missing

    def propose(self, command):
        return self._storage.execute(_command(command, "propose_association"), self._propose)

    def _propose(self, tx):
        details, missing = self._proposal_state(tx, tx.command)
        scope, operation_id = self.scope_id, tx.command["command_id"]
        parents = self._evaluation_parents(details)
        recorded = details["assessed_as_of"]
        receipt = tx.insert({"schema_version": "1.0", **_record_ref(scope, operation_id, "evaluation"),
            "provenance": {"origin": "system", "producer": deepcopy(_ENGINE), "recorded_at": recorded, "parents": parents},
            "body": {"stage": "evaluation", "operation_id": operation_id, "recorded_at": recorded,
                     "outcome": "matter:" + details["outcome"], "evidence": parents,
                     "details": _domain("association-evaluation", details)}})
        body = {key: deepcopy(details[key]) for key in (
            "subject", "candidate_set", "outcome", "candidates", "selected", "matching_rule", "evidence", "coverage", "assessed_as_of")}
        body.update(evaluator_receipt=entity_ref(receipt), evaluation=pin(receipt),
                    uncertainty=deepcopy(details["evaluation"]["uncertainty"]),
                    qualification=deepcopy(details["evaluation"]["qualification"]))
        proposal = tx.insert({"schema_version": "1.0", **_record_ref(scope, operation_id, "proposal"),
            "provenance": {"origin": "system", "producer": deepcopy(_ENGINE), "recorded_at": recorded,
                           "parents": [pin(receipt)]}, "body": body})
        result = {"proposal": pin(proposal), "candidate_set": details["candidate_set"],
                  "changes": [{"cause": "new_evidence", "before": [], "after": [pin(proposal)]}]}
        outcome = details["outcome"]
        if outcome == "no_match":
            result.update(candidates=[item["candidate"] for item in details["candidates"]],
                          coverage=details["coverage"], evidence=details["evidence"], selected=[])
        elif outcome == "ambiguous":
            result.update(candidates=[item["candidate"] for item in details["candidates"]],
                          reason=details["evaluation"]["reason"])
        elif outcome == "insufficient_evidence":
            result.update(missing_evidence=missing or details["evaluation"]["missing_evidence"] or [details["evaluation"]["reason"]],
                          coverage=details["coverage"])
        elif outcome == "evaluation_failed":
            result["reason"] = details["evaluation"]["reason"]
        return tx.success("proposal" if outcome == "matched" else outcome, result)

    @staticmethod
    def _evaluation_parents(details):
        refs = [details["subject"], details["candidate_set"], *details["evidence"]]
        for candidate in details["candidates"]:
            refs.extend([candidate["candidate"], *candidate["basis"]])
        return sorted({canonical_bytes(ref): ref for ref in refs}.values(), key=canonical_bytes)

    def _read_proposal(self, view, reference):
        record = _record(view, self.scope_id, reference, "association_proposal")
        body = record["body"]
        if any(key not in body for key in ("evaluation", "candidate_set", "coverage", "assessed_as_of")):
            raise _invalid("The stored proposal does not contain a frozen candidate decision.")
        receipt, details = _receipt(view, self.scope_id, body["evaluation"], "association-evaluation", "evaluation")
        self._verify_frozen_evaluation(details)
        expected = {key: deepcopy(details[key]) for key in (
            "subject", "candidate_set", "outcome", "candidates", "selected", "matching_rule", "evidence", "coverage", "assessed_as_of")}
        expected.update(evaluator_receipt=entity_ref(receipt), evaluation=pin(receipt),
                        uncertainty=details["evaluation"]["uncertainty"], qualification=details["evaluation"]["qualification"])
        parents = self._evaluation_parents(details)
        if (not _same(body, expected) or "supersedes" in record
                or entity_ref(record) != _record_ref(self.scope_id, receipt["body"]["operation_id"], "proposal")
                or record["creation_receipt"] != receipt["creation_receipt"]
                or record["provenance"] != {"origin": "system", "producer": _ENGINE,
                    "recorded_at": details["assessed_as_of"], "parents": [pin(receipt)]}
                or receipt["body"]["stage"] != "evaluation" or receipt["body"]["outcome"] != "matter:" + details["outcome"]
                or receipt["body"]["recorded_at"] != details["assessed_as_of"]
                or receipt["provenance"] != {"origin": "system", "producer": _ENGINE,
                    "recorded_at": details["assessed_as_of"], "parents": parents}
                or not _same(receipt["body"]["evidence"], parents)):
            raise _invalid()
        return record, details

    def _verify_frozen_evaluation(self, details):
        """Check immutable proof coherence without refreshing its old inputs."""
        scope, evaluation = self.scope_id, details["evaluation"]
        _scoped(scope, details["subject"], "association_member_dependency")
        _scoped(scope, details["candidate_set"], "projection_dependency")
        for reference in details["evidence"]:
            _scoped(scope, reference)
        if len({_identity(ref) for ref in details["evidence"]}) != len(details["evidence"]):
            raise _invalid()
        identities = set()
        for candidate in details["candidates"]:
            reference = _scoped(scope, candidate["candidate"], "association_member_dependency")
            identity = _identity(reference)
            if identity in identities or identity == _identity(details["subject"]):
                raise _invalid()
            identities.add(identity)
            for basis in candidate["basis"]:
                _scoped(scope, basis)
            if len({_identity(ref) for ref in candidate["basis"]}) != len(candidate["basis"]):
                raise _invalid()
        for selected in [*details["selected"], *evaluation["selected"]]:
            _scoped(scope, selected, "association_member_dependency")
            if _identity(selected) not in identities:
                raise _invalid()
        outcome, reported = details["outcome"], evaluation["outcome"]
        if reported == "matched" and len(evaluation["selected"]) != 1:
            raise _invalid()
        if reported == "ambiguous" and len(details["candidates"]) < 2:
            raise _invalid()
        if outcome != reported and not (outcome == "insufficient_evidence" and reported != "evaluation_failed"):
            raise _invalid("Effective association outcomes must preserve the submitted decision or an evidence refusal.")
        if outcome == "matched" and (
            reported != "matched" or len(details["selected"]) != 1
            or entity_ref(details["selected"][0]) != entity_ref(evaluation["selected"][0])
        ):
            raise _invalid()
        if outcome in {"matched", "no_match", "ambiguous"} and details["coverage"]["status"] != "complete":
            raise _invalid()
        if details["mode"] == "exact_keys":
            if (outcome != reported or not _same(details["selected"], evaluation["selected"])
                    or evaluation["producer"] != _ENGINE
                    or (outcome == "matched" and len(details["candidates"]) != 1)
                    or (outcome == "no_match" and details["candidates"])
                    or outcome == "evaluation_failed"):
                raise _invalid()

    def _read_disposition(self, view, subject, target, relation, capability):
        reference = disposition_ref(self.scope_id, subject, target, relation, capability)
        stored = _lookup(view, reference)
        if stored is None:
            return None
        try:
            record = _validate_projection(stored)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise _invalid() from None
        body = _value("association-disposition", record["value"])
        if (entity_ref(record) != reference or body["scope_id"] != self.scope_id
                or disposition_ref(self.scope_id, body["subject"], body["target"], body["relation"], body["capability"]) != reference
                or record["creation_receipt"]["scope_id"] != self.scope_id
                or record["watch_keys"] != list(_watches(body["subject"], body["target"]))
                or body["status"] != ("released" if body["kind"] == "release" else "blocked")):
            raise _invalid()
        receipt, detail = self._read_decision(view, body["decision"])
        expected = {key: deepcopy(body[key]) for key in (
            "scope_id", "subject", "target", "relation", "capability", "reason", "authority", "policy", "previous", "as_of")}
        expected.update(decision=body["kind"], proposal=None)
        if not _same(detail, expected):
            raise _invalid()
        if body["previous"] is not None and entity_ref(body["previous"]) != reference:
            raise _invalid()
        return record

    def _read_decision(self, view, reference):
        receipt, detail = _receipt(view, self.scope_id, reference, "association-decision", "decision")
        _scoped(self.scope_id, detail["subject"], "association_member_ref")
        _scoped(self.scope_id, detail["target"], "association_member_ref")
        _scoped(self.scope_id, detail["authority"], "receipt_ref")
        expected_disposition = disposition_ref(self.scope_id, detail["subject"], detail["target"],
                                                detail["relation"], detail["capability"])
        if detail["previous"] is not None:
            _scoped(self.scope_id, detail["previous"], "projection_dependency")
            if entity_ref(detail["previous"]) != expected_disposition:
                raise _invalid()
        if detail["proposal"] is not None:
            _scoped(self.scope_id, detail["proposal"], "association_proposal_dependency")
        if ((detail["decision"] == "accept") != (detail["proposal"] is not None)
                or (detail["decision"] == "accept" and detail["capability"] == "merge")
                or (detail["decision"] == "release" and detail["previous"] is None)):
            raise _invalid()
        parents = [detail["previous"]] if detail["previous"] is not None else []
        if detail["proposal"] is not None:
            parents.append(detail["proposal"])
        if (receipt["body"]["stage"] != "authority" or receipt["body"]["outcome"] != "matter:association_" + detail["decision"]
                or receipt["body"]["recorded_at"] != detail["as_of"]
                or receipt["provenance"] != {"origin": "host", "producer": _ENGINE,
                    "recorded_at": detail["as_of"], "parents": parents}
                or not _same(receipt["body"]["evidence"], parents)):
            raise _invalid()
        return receipt, detail

    def _verify_association_snapshot(self, view, stored):
        try:
            record = validate_record(stored)
            body = record["body"]
            if (record["record_type"] != "accepted_association" or len(body["members"]) != 2
                    or any(key not in body for key in ("capability", "decision", "candidate_set", "acceptance_policy"))
                    or body["capability"] not in {"attach", "relate"} or "supersedes" in record
                    or record["creation_receipt"]["scope_id"] != self.scope_id
                    or entity_ref(record) != association_ref(self.scope_id, *body["members"], body["relation"], body["capability"])):
                raise _invalid()
        except (ValueError, TypeError, KeyError, RecursionError):
            raise _invalid() from None
        proposal, _ = self._read_proposal(view, body["proposal"])
        _, decision = self._read_decision(view, body["decision"])
        if (proposal["body"]["outcome"] != "matched" or len(proposal["body"]["selected"]) != 1
                or not _same(body["members"], [proposal["body"]["subject"], proposal["body"]["selected"][0]])
                or not _same(body["candidate_set"], proposal["body"]["candidate_set"])
                or decision["subject"] != entity_ref(body["members"][0]) or decision["target"] != entity_ref(body["members"][1])
                or decision["relation"] != body["relation"] or decision["capability"] != body["capability"]
                or decision["authority"] != body["authority"] or decision["policy"] != body["acceptance_policy"]
                or (body["status"] == "active" and (decision["decision"] != "accept" or decision["proposal"] != body["proposal"]))
                or (body["status"] == "revoked" and decision["decision"] not in {"reject", "protect"})
                or body["status"] == "superseded"):
            raise _invalid()
        provenance = record["provenance"]
        if (provenance["origin"] != "host" or provenance["producer"] != _ENGINE
                or set(provenance) != {"origin", "producer", "recorded_at", "parents"}
                or len(provenance["parents"]) != 2):
            raise _invalid()
        original_proposal, _ = self._read_proposal(view, provenance["parents"][0])
        original_receipt, original_decision = self._read_decision(view, provenance["parents"][1])
        if (original_decision["decision"] != "accept" or original_decision["proposal"] != pin(original_proposal)
                or original_receipt["creation_receipt"] != record["creation_receipt"]
                or original_decision["as_of"] != provenance["recorded_at"]
                or original_decision["subject"] != entity_ref(body["members"][0])
                or original_decision["target"] != entity_ref(body["members"][1])
                or association_ref(self.scope_id, original_decision["subject"], original_decision["target"],
                    original_decision["relation"], original_decision["capability"]) != entity_ref(record)):
            raise _invalid()
        return record

    def _read_association(self, view, reference):
        stored = _lookup(view, reference)
        if stored is None:
            return None
        record = self._verify_association_snapshot(view, stored)
        body = record["body"]
        index = _lookup(view, _membership_ref(record))
        if index is None:
            raise _invalid()
        try:
            index = _validate_projection(index)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise _invalid() from None
        if (entity_ref(index) != _membership_ref(record) or index["revision"] != record["revision"]
                or index["creation_receipt"] != record["creation_receipt"]
                or not _same(index["value"], _membership(record))
                or index["watch_keys"] != list(_watches(*body["members"]))):
            raise _invalid()
        return record

    def _acceptance_state(self, view, command):
        body, scope = command["body"], self.scope_id
        self._policy.authorize(view, command)
        if any(key not in body for key in ("candidate_set", "relation", "capability")):
            raise _invalid("Acceptance requires the original candidate set and an explicit relationship capability.")
        if not _same(body["acceptance_policy"], self._policy.reference):
            raise StorageError("E_POLICY_INVALID", "Acceptance requires the configured current host policy.")
        proposal, detail = self._read_proposal(view, body["proposal"])
        self._policy.authorize(view, command, rule=detail["matching_rule"], relation=body["relation"],
                               capability=body["capability"], semantic=detail["mode"] == "semantic")
        if detail["outcome"] != "matched" or len(detail["selected"]) != 1:
            raise StorageError("E_ASSOCIATION_CONFLICT", "Only a matched, single-selection proposal can be accepted.")
        catalog = require_current_candidates(view, scope, detail["candidate_set"])
        if not matches(catalog, body["candidate_set"]):
            raise StorageError("E_REVISION_CONFLICT")
        # Matching receipt/proposal copies are insufficient by themselves.
        # Rebind their complete decision to the original catalog snapshot and
        # recompute exact nomination and evidence gates before accepting it.
        proof_command = deepcopy(command)
        proof_command["body"] = {key: deepcopy(detail[key]) for key in (
            "subject", "candidate_set", "candidates", "matching_rule", "evidence", "assessed_as_of")}
        if detail["mode"] == "semantic":
            proof_command["body"]["evaluation"] = deepcopy(detail["evaluation"])
        verified, _ = self._proposal_state(view, proof_command, new_identity=False)
        if not _same(verified, detail):
            raise _invalid("The frozen proposal does not describe its referenced candidate catalog.")
        _refs_match(view, scope, body["candidates"], [item["candidate"] for item in detail["candidates"]])
        subject, target = detail["subject"], detail["selected"][0]
        # Fresh deterministic lookup detects even a first rejection committed
        # after preparation. Nothing refreshes the proposal's candidate pins.
        disposition = self._read_disposition(view, subject, target, body["relation"], body["capability"])
        if disposition is not None and disposition["value"]["value"]["status"] == "blocked":
            raise StorageError("E_ASSOCIATION_CONFLICT", "A persistent host decision blocks this association.")
        reference = association_ref(scope, subject, target, body["relation"], body["capability"])
        current = self._read_association(view, reference)
        if current is None and _lookup(view, _membership_ref(reference)) is not None:
            raise _invalid()
        if _lookup(view, _record_ref(scope, command["command_id"], "decision")) is not None:
            raise StorageError("E_SOURCE_IDENTITY_CONFLICT")
        return proposal, disposition, current, reference

    def accept(self, command):
        return self._storage.execute(_command(command, "accept_association"), self._accept)

    def _decision_receipt(self, tx, detail):
        parents = [detail["previous"]] if detail["previous"] is not None else []
        if detail["proposal"] is not None:
            parents.append(detail["proposal"])
        return tx.insert({"schema_version": "1.0", **_record_ref(self.scope_id, tx.command["command_id"], "decision"),
            "provenance": {"origin": "host", "producer": deepcopy(_ENGINE), "recorded_at": detail["as_of"], "parents": parents},
            "body": {"stage": "authority", "operation_id": tx.command["command_id"], "recorded_at": detail["as_of"],
                     "outcome": "matter:association_" + detail["decision"], "evidence": parents,
                     "details": _domain("association-decision", detail)}})

    def _write_membership(self, tx, record):
        return tx.put_projection(_membership_ref(record), _membership(record),
                                 watch_keys=_watches(*record["body"]["members"]))

    def _accept(self, tx):
        proposal, disposition, current, reference = self._acceptance_state(tx, tx.command)
        command, body = tx.command, tx.command["body"]
        members = [proposal["body"]["subject"], proposal["body"]["selected"][0]]
        detail = {"scope_id": self.scope_id, "subject": entity_ref(members[0]), "target": entity_ref(members[1]),
                  "relation": body["relation"], "capability": body["capability"], "decision": "accept",
                  "reason": "Explicit host acceptance under the configured scoped policy.", "authority": command["authority"],
                  "policy": self._policy.reference, "previous": pin(disposition) if disposition else None,
                  "proposal": pin(proposal), "as_of": body.get("as_of") or _now()}
        receipt = self._decision_receipt(tx, detail)
        accepted_body = {"proposal": pin(proposal), "members": members, "relation": body["relation"], "status": "active",
                         "authority": command["authority"], "candidate_set": proposal["body"]["candidate_set"],
                         "acceptance_policy": self._policy.reference, "decision": pin(receipt), "capability": body["capability"]}
        if current is None:
            record = tx.insert({"schema_version": "1.0", **reference,
                "provenance": {"origin": "host", "producer": deepcopy(_ENGINE), "recorded_at": detail["as_of"],
                               "parents": [pin(proposal), pin(receipt)]}, "body": accepted_body})
        else:
            replacement = deepcopy(current)
            replacement["revision"] += 1
            replacement["body"] = accepted_body
            record = tx.replace(replacement)
        self._write_membership(tx, record)
        return tx.success("accepted", {"association": pin(record), "changes": [
            {"cause": "association_correction", "before": [pin(current)] if current else [], "after": [pin(record)]}]})

    def _decision_state(self, view, command):
        body, scope = command["body"], self.scope_id
        self._policy.authorize(view, command, relation=body["relation"], correction=body["decision"] == "release")
        if not _same(body["acceptance_policy"], self._policy.reference):
            raise StorageError("E_POLICY_INVALID")
        read_member(view, scope, body["subject"])
        read_member(view, scope, body["target"])
        key = _pair(scope, body["subject"], body["target"], body["relation"], body["capability"])
        current = self._read_disposition(view, key["subject"], key["target"], body["relation"], body["capability"])
        previous = body["previous"]
        if ((current is None and previous is not None)
                or (current is not None and (previous is None or not matches(current, previous)))):
            raise StorageError("E_REVISION_CONFLICT", "Decide against the current protected-disposition revision.")
        if body["decision"] == "release" and current is None:
            raise StorageError("E_ASSOCIATION_CONFLICT", "An explicit prior decision is required for correction.")
        reference = association_ref(scope, key["subject"], key["target"], body["relation"], body["capability"])
        association = self._read_association(view, reference) if body["capability"] != "merge" else None
        if _lookup(view, _record_ref(scope, command["command_id"], "decision")) is not None:
            raise StorageError("E_SOURCE_IDENTITY_CONFLICT")
        return key, current, association

    def decide(self, command):
        return self._storage.execute(_command(command, "decide_association"), self._decide)

    def _decide(self, tx):
        key, current, association = self._decision_state(tx, tx.command)
        command, body = tx.command, tx.command["body"]
        detail = {"scope_id": self.scope_id, "subject": key["subject"], "target": key["target"],
                  "relation": body["relation"], "capability": body["capability"], "decision": body["decision"],
                  "reason": body["reason"], "authority": command["authority"], "policy": self._policy.reference,
                  "previous": pin(current) if current else None, "proposal": None, "as_of": body["as_of"]}
        receipt = self._decision_receipt(tx, detail)
        value = {key: deepcopy(item) for key, item in detail.items() if key not in {"decision", "proposal"}}
        value.update(status="released" if body["decision"] == "release" else "blocked",
                     kind=body["decision"], decision=pin(receipt))
        disposition = tx.put_projection(disposition_ref(self.scope_id, key["subject"], key["target"], body["relation"], body["capability"]),
                                        _domain("association-disposition", value), watch_keys=_watches(key["subject"], key["target"]))
        changes = [{"cause": "disposition_change", "before": [pin(current)] if current else [], "after": [pin(disposition)]}]
        associations = []
        if association is not None and association["body"]["status"] == "active" and body["decision"] != "release":
            replacement = deepcopy(association)
            replacement["revision"] += 1
            replacement["body"].update(status="revoked", decision=pin(receipt), authority=command["authority"],
                                        acceptance_policy=self._policy.reference, relation=body["relation"])
            updated = tx.replace(replacement)
            self._write_membership(tx, updated)
            associations.append(pin(updated))
            changes.append({"cause": "association_correction", "before": [pin(association)], "after": [pin(updated)]})
        return tx.success("applied", {"disposition": pin(disposition), "decision": pin(receipt),
                                      "associations": associations, "changes": changes})

    def disposition(self, subject, target, relation, capability="attach"):
        with self._storage.snapshot() as snapshot:
            return self._read_disposition(snapshot, subject, target, relation, capability)

    def for_subject(self, subject, *, relation=None, status=None):
        reference = _scoped(self.scope_id, entity_ref(subject), "association_member_ref")
        if status is not None and status not in {"active", "revoked"}:
            raise StorageError("E_SCHEMA_INVALID")
        if relation is not None:
            relation = _validate_fragment(relation, "component_ref")
        found = []
        with self._storage.snapshot() as snapshot:
            read_member(snapshot, self.scope_id, reference)
            for watched in snapshot.watchers(_watch(reference, "subject")):
                if watched["namespace"] == DISPOSITION_NAMESPACE:
                    # Decision projections share pair watches but are not
                    # accepted edges. Verify them before ignoring their type.
                    body = _value("association-disposition", watched["value"])
                    checked = self._read_disposition(snapshot, body["subject"], body["target"], body["relation"], body["capability"])
                    if checked is None or checked != watched or body["subject"] != reference:
                        raise _invalid()
                    continue
                if watched["namespace"] != MEMBERSHIP_NAMESPACE:
                    raise _invalid()
                body = _value("association-membership", watched["value"])
                record = self._read_association(snapshot, entity_ref(body["association"]))
                if (record is None or not matches(record, body["association"]) or body["subject"] != reference
                        or entity_ref(watched) != _membership_ref(record)
                        or not _same(watched, _lookup(snapshot, _membership_ref(record)))):
                    raise _invalid()
                if ((status is None or record["body"]["status"] == status)
                        and (relation is None or _same(record["body"]["relation"], relation))):
                    found.append(record)
        return sorted(found, key=lambda item: canonical_bytes(entity_ref(item)))

    def history(self, association):
        reference = _scoped(self.scope_id, entity_ref(association), "accepted_association_ref")
        with self._storage.snapshot() as snapshot:
            current = self._read_association(snapshot, reference)
            if current is None:
                raise StorageError("E_NOT_FOUND")
            # Historical snapshots retain their own immutable receipts and
            # evidence pins; they are not forced to be current dependencies.
            history = snapshot.history(reference)
            if type(history) is not list or len(history) != current["revision"]:
                raise _invalid()
            verified = []
            for revision, raw in enumerate(history, start=1):
                record = self._verify_association_snapshot(snapshot, raw)
                if (record["revision"] != revision or entity_ref(record) != reference
                        or record["creation_receipt"] != current["creation_receipt"]
                        or record["provenance"] != current["provenance"]):
                    raise _invalid()
                verified.append(record)
            if not _same(verified[-1], current):
                raise _invalid()
            return verified
