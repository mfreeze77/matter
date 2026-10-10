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
from ..time import compare_times, knowledge_eligible
from .._rule_values import bounded, checked, domain, fragment, preparation_reference, same, unique
from .base import EvaluationInput, _PREPARED_INPUT


__all__ = ["prepare_input", "preparation_reference", "check_input_current", "requires_currentness_guard"]


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
                  coverage, as_of, subject=None, context=(), upstream=(), negative_dependencies=(), control_token=None):
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
    subject_pin = None
    if subject is not None:
        subject_pin = fragment(subject, "matter_dependency")
        subject_record = _current(reads, scope, subject_pin)
        if subject_record["record_type"] != "matter":
            raise ContractError("E_EVIDENCE_INVALID")
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
        if record["record_type"] in {"judgment", "assessment"}:
            intrinsic = [record["provenance"]["recorded_at"]]
            if record["record_type"] == "judgment":
                intrinsic.append(record["body"]["execution_interval"]["end"])
            if any(knowledge_eligible(time, boundary) is not True
                   or compare_times(available, time) == -1 for time in intrinsic):
                eligible = False
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
    watches, registrations = [], []
    conditions = deepcopy(definition["temporal_dependencies"])
    for declaration in bounded(upstream, 32):
        declaration = checked(declaration, required=("reference", "expected_input", "available_at"))
        reference = fragment(declaration["reference"], "judgment_dependency")
        record = validate_record(_current(reads, scope, reference))
        if record["record_type"] != "judgment":
            raise ContractError("E_EVIDENCE_INVALID", "A rule dependency must name an actual judgment.")
        original = checked(declaration["expected_input"], required=("rule_definition", "packet"))
        domain("rule-definition", original["rule_definition"])
        original_packet = domain("rule-evaluation-input", original["packet"])["value"]
        expected_digest = canonical_digest(original, "matter.evaluation-input.v1")
        if (original_packet["scope_id"] != scope or record["body"]["input_digest"] != expected_digest
                or original_packet["rule"] != record["body"]["rule"]
                or original_packet["binding"] != record["body"]["evaluator"]
                or original_packet["rule"] not in [item["rule"] for item in definition["dependencies"]]):
            raise ContractError("E_EVIDENCE_INVALID", "The host-selected predecessor does not bind its expected exact input.")
        if not same(record["body"]["dependency_manifest"], original_packet["dependencies"]):
            raise ContractError("E_EVIDENCE_INVALID", "The predecessor changed its bound dependency manifest.")
        from ..rules import RuleDefinition
        previous_rule = RuleDefinition(original["rule_definition"], schemas=schemas)
        if previous_rule.reference != original_packet["rule"]:
            raise ContractError("E_EVIDENCE_INVALID", "The predecessor's full rule meaning is inconsistent.")
        available = fragment(declaration["available_at"], "time_value")
        # No implicit backdating of a result produced after the knowledge cut.
        # A historical replay policy requires a separate explicit contract.
        produced = record["body"]["execution_interval"]["end"]
        recorded = record["provenance"]["recorded_at"]
        if (knowledge_eligible(available, boundary) is not True
                or knowledge_eligible(produced, boundary) is not True
                or knowledge_eligible(recorded, boundary) is not True
                or compare_times(available, produced) == -1):
            omit(reference, "upstream_not_available_at_knowledge_cut", True)
            continue
        for dependency in original_packet["dependencies"]["positive"]:
            _current(reads, scope, dependency)
        for dependency in original_packet["negative_registrations"]:
            registration = require_current_negative_dependency(reads, scope, dependency, as_of=boundary)
            if pin(registration) not in registrations:
                registrations.append(pin(registration))
                watches.append(deepcopy(registration["value"]["value"]["watch"]))
        for condition in original_packet["dependencies"]["time_conditions"]:
            if condition not in conditions:
                conditions.append(deepcopy(condition))
        predecessors.append({"judgment": record, "expected_input_digest": expected_digest,
            "expected_input": original,
            "subject": deepcopy(original_packet["subject"]), "context": deepcopy(original_packet["context"]),
            "available_at": available})
    unique([pin(item["judgment"]) for item in predecessors])
    for reference in unique(bounded(negative_dependencies, 32)):
        record = require_current_negative_dependency(reads, scope, reference, as_of=boundary)
        if pin(record) not in registrations:
            watches.append(deepcopy(record["value"]["value"]["watch"]))
            registrations.append(pin(record))
    epoch = 0 if control_token is None else control_token.get("control_epoch")
    token_digest = None if control_token is None else canonical_digest(control_token, "matter.evaluation-control.v1")
    manifest = {"positive": list(reads.references.values()), "negative": watches,
                "time_conditions": conditions, "context": contexts,
                "control_epoch": epoch}
    packet = {"schema_version": "1.0", "scope_id": scope, "rule": rule.reference,
              "binding": deepcopy(definition["evaluator_binding"]), "proposition": value,
              "evidence": included, "omitted": omissions, "coverage": coverage,
              "as_of": boundary, "context": contexts, "upstream": predecessors,
              "subject": subject_pin, "negative_registrations": registrations,
              "dependencies": manifest, "control_token_digest": token_digest}
    return EvaluationInput(rule, packet, control_token=control_token, _admission=_PREPARED_INPUT)


def requires_currentness_guard(prepared):
    """Mutable/time/absence inputs require a host gate at actual attempt time."""
    packet = prepared.value["packet"] if isinstance(prepared, EvaluationInput) else prepared["packet"]
    return bool(packet["negative_registrations"] or packet["dependencies"]["time_conditions"]
                or packet["upstream"]
                or any("revision" in ref for ref in packet["dependencies"]["positive"]))


def check_input_current(view, prepared, *, as_of, check_control_context=None):
    """Recheck a fixed input in a fresh host read view; never recapture it.

    This is a local admission check, not the atomic MAT-015 commit guard or
    transitive MAT-016 invalidation engine. The host supplies actual admission
    time, independently of the historical evidence knowledge cut.
    """
    material = prepared.value if isinstance(prepared, EvaluationInput) else checked(prepared, required=("rule_definition", "packet"))
    packet = domain("rule-evaluation-input", material["packet"])["value"]
    now = fragment(as_of, "known_time")
    for reference in packet["dependencies"]["positive"]:
        _current(view, packet["scope_id"], reference)
    for reference in packet["negative_registrations"]:
        require_current_negative_dependency(view, packet["scope_id"], reference, as_of=now)
    for condition in packet["dependencies"]["time_conditions"]:
        if (compare_times(now, condition["next_check_at"]) in {0, 1}
                or compare_times(now, condition["expires_at"]) in {0, 1}):
            raise StorageError("E_DEPENDENCY_STALE", "A declared time dependency requires reconsideration.")
    # The host retains original token contexts. A digest is not authority, and
    # equal epoch integers never substitute for those exact target contexts.
    pending = [material]
    while pending:
        original = pending.pop()
        original_packet = original["packet"]
        token_digest = original_packet["control_token_digest"]
        if token_digest is not None:
            if not callable(check_control_context):
                raise ContractError("E_POLICY_INVALID", "Original control context is required for admission.")
            check_control_context(input_digest=canonical_digest(original, "matter.evaluation-input.v1"),
                token_digest=token_digest, control_epoch=original_packet["dependencies"]["control_epoch"],
                as_of=deepcopy(now))
        pending.extend(item["expected_input"] for item in original_packet["upstream"])
    return {"status": "current", "input_digest": canonical_digest(material, "matter.evaluation-input.v1"), "checked_at": now}

