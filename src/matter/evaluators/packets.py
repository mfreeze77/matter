"""Prepare bounded evaluator inputs from a host-authorized consistent read view.

Preparation reads supplied pins only. It discovers no sources, follows no URI,
and grants no source or control authority. Locator declarations must come from
adapters admitted in the immutable rule. Their authenticity is host-owned.
"""

from copy import deepcopy

from ..canonical import canonical_bytes, canonical_digest
from ..citations import verify_locator_validation
from ..contracts import ContractError, validate_record
from ..negative_dependencies import require_current_negative_dependency
from ..storage import StorageError, entity_ref, pin
from ..time import knowledge_eligible
from .._rule_values import bounded, checked, fragment, preparation_reference, same, unique
from .base import EvaluationInput, _PREPARED_INPUT


__all__ = ["prepare_input", "preparation_reference"]


class _Reads:
    def __init__(self, view, scope):
        self.view, self.scope, self.references = view, scope, {}

    def remember(self, value):
        reference = pin(value)
        if reference["scope_id"] != self.scope:
            raise StorageError("E_SCOPE_FORBIDDEN")
        self.references[canonical_bytes(reference)] = reference
        return value

    def get(self, reference):
        if reference["scope_id"] != self.scope:
            raise StorageError("E_SCOPE_FORBIDDEN")
        return self.remember(self.view.get(reference))

    def lookup_identity(self, reference):
        if reference["scope_id"] != self.scope:
            raise StorageError("E_SCOPE_FORBIDDEN")
        return self.remember(self.view.lookup_identity(reference))

    def __getattr__(self, name):
        # Negative registration verification owns additional structural reads.
        return getattr(self.view, name)


def _current(view, scope, reference):
    ref = fragment(reference, "pinned_ref")
    if ref["scope_id"] != scope:
        raise StorageError("E_SCOPE_FORBIDDEN")
    value = view.get(ref)
    if not same(pin(value), ref):
        raise StorageError("E_EVIDENCE_INVALID", "The read view returned a different snapshot.")
    current = view.get(entity_ref(ref))
    if not same(pin(current), ref):
        raise StorageError("E_DEPENDENCY_STALE", "The packet reference is no longer current.")
    return value


def prepare_input(view, rule, *, schemas, scope_id, proposition, evidence=(), omitted=(),
                  coverage, as_of, context=(), upstream=(), negative_dependencies=(), control_token=None):
    """Return a detached exact packet; keep the view's snapshot context open.

    Evidence entries require reference, locator, quotation, roles and an
    admitted locator validation. Non-observation inputs additionally require a
    host-declared available_at; no availability is inferred from event time.
    Future/unknown/ineligible content is omitted with a reason, not delivered
    to the evaluator. Explicit omitted refs are audit declarations, not reads.
    """
    scope = fragment(scope_id, "identifier")
    definition = rule.value
    if definition["evidence_preparation"] != preparation_reference():
        raise ContractError("E_POLICY_INVALID", "This exact evidence preparation is not installed.")
    boundary = fragment(as_of, "known_time")
    value = schemas.validate(proposition)
    if value["schema"] != definition["input_schema"]:
        raise ContractError("E_POLICY_INVALID", "The proposition uses the wrong input schema.")
    coverage = fragment(coverage, "coverage")
    contexts = unique([fragment(item, "component_ref") for item in bounded(context, 32)])
    limits = definition["resource_limits"]
    raw_evidence = bounded(evidence, limits["max_evidence"])
    raw_omitted = bounded(omitted, 128)
    if len(canonical_bytes({"proposition": value, "evidence": raw_evidence, "omitted": raw_omitted})) > limits["max_input_bytes"]:
        raise ContractError("E_BUDGET_EXHAUSTED")
    requirements = definition["evidence_requirements"]
    reads = _Reads(view, scope)
    included, omissions, seen = [], [], set()

    def omit(reference, reason, mandatory):
        omissions.append({"reference": deepcopy(reference), "reason": reason, "mandatory": mandatory})

    for raw in raw_omitted:
        item = checked(raw, required=("reference", "reason", "mandatory"))
        reference = fragment(item["reference"], "pinned_ref")
        if reference["scope_id"] != scope or type(item["mandatory"]) is not bool:
            raise ContractError("E_SCOPE_FORBIDDEN" if reference["scope_id"] != scope else "E_SCHEMA_INVALID")
        fragment(item["reason"], "text")
        key = canonical_bytes(reference)
        if key in seen:
            raise ContractError("E_SCHEMA_INVALID", "An evidence reference appears more than once.")
        seen.add(key)
        omissions.append(item)

    for raw in raw_evidence:
        item = checked(raw, required=("reference", "locator", "quotation", "roles", "validation"),
                       optional=("available_at",))
        reference = fragment(item["reference"], "pinned_ref")
        key = canonical_bytes(reference)
        if key in seen:
            raise ContractError("E_SCHEMA_INVALID", "An evidence reference appears more than once.")
        seen.add(key)
        record = validate_record(_current(reads, scope, reference))
        roles = unique([fragment(role, "namespaced_name") for role in bounded(item["roles"], 32)])
        mandatory = bool(set(roles) & set(requirements["required_roles"]))
        if record["record_type"] not in requirements["allowed_kinds"] or record["provenance"]["origin"] not in requirements["allowed_origins"]:
            omit(reference, "ineligible_source", mandatory)
            continue
        available = item.get("available_at")
        if record["record_type"] == "observation":
            original = record["body"]["available_at"]
            if available is not None and not same(available, original):
                raise ContractError("E_EVIDENCE_INVALID", "Observation availability cannot be replaced by the packet.")
            available = original
        if available is None:
            raise ContractError("E_EVIDENCE_UNAVAILABLE", "This evidence kind requires explicit host availability.")
        available = fragment(available, "time_value")
        eligible = knowledge_eligible(available, boundary)
        if eligible is not True:
            omit(reference, "not_yet_available" if eligible is False else "unknown_availability", mandatory)
            continue
        validation = fragment(item["validation"], "domain_value")
        try:
            adapter = validation["value"]["adapter"]
        except (TypeError, KeyError):
            raise ContractError("E_EVIDENCE_INVALID") from None
        if adapter not in requirements["locator_adapters"]:
            raise ContractError("E_EVIDENCE_INVALID", "The locator adapter was not admitted by this rule.")
        declaration = verify_locator_validation(validation, evidence=record, locator=item["locator"],
                quotation=item["quotation"], adapter=adapter)
        for dependency in declaration["dependencies"]:
            _current(reads, scope, dependency)
        if declaration["result"]["status"] != "valid":
            omit(reference, "locator_" + declaration["result"]["status"], mandatory)
            continue
        included.append({"record": record, "reference": reference, "locator": deepcopy(item["locator"]),
                         "quotation": item["quotation"], "roles": roles, "available_at": available,
                         "validation": validation})
        if len(canonical_bytes(included)) > limits["max_input_bytes"]:
            raise ContractError("E_BUDGET_EXHAUSTED")

    predecessors = []
    for reference in unique(bounded(upstream, 32)):
        record = validate_record(_current(reads, scope, reference))
        if record["record_type"] != "judgment":
            raise ContractError("E_EVIDENCE_INVALID", "A rule dependency must name an actual judgment.")
        predecessors.append(record)
    watches = []
    for reference in unique(bounded(negative_dependencies, 32)):
        record = require_current_negative_dependency(reads, scope, reference, as_of=boundary)
        watches.append(deepcopy(record["value"]["value"]["watch"]))
    epoch = 0 if control_token is None else control_token.get("control_epoch")
    token_digest = None if control_token is None else canonical_digest(control_token, "matter.evaluation-control.v1")
    manifest = {"positive": list(reads.references.values()), "negative": watches,
                "time_conditions": deepcopy(definition["temporal_dependencies"]), "context": contexts,
                "control_epoch": epoch}
    packet = {"schema_version": "1.0", "scope_id": scope, "rule": rule.reference,
              "binding": deepcopy(definition["evaluator_binding"]), "proposition": value,
              "evidence": included, "omitted": omissions, "coverage": coverage,
              "as_of": boundary, "context": contexts, "upstream": predecessors,
              "dependencies": manifest, "control_token_digest": token_digest}
    return EvaluationInput(rule, packet, control_token=control_token, _admission=_PREPARED_INPUT)

