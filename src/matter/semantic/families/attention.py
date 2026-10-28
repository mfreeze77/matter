"""MAT-034 explicit comparison causes, recovery and audience contribution.

The small context transform reuses packet snapshot/availability/access readers.
It does not discover context, renew controls, infer a disposition or send advice.
"""

from ..._rule_values import bounded, descriptor, fragment
from ...canonical import canonical_bytes
from ...contracts import ContractError
from ...storage import PROJECTION_TYPE, entity_ref, pin
from ...contexts import _binding, ContextSelection
from ..packets import MAX_PACKET_BYTES, PreparedPacket, _Reads, _known_record as _known_snapshot, _pin_references
from ..questions import QuestionSpecification
from . import with_packet

CAUSES = ("new_evidence", "corrected_association", "changed_policy", "timer")
_TYPES = {"before": {"assessment"}, "after": {"assessment"}, "condition": {"claim"},
          "result": {"observation", "claim"}, "purpose": {PROJECTION_TYPE},
          "audience": {PROJECTION_TYPE}, "delivered": {"receipt"}}


def _record_view(record):
    """Select assessment meaning; omit bulky publication/replay machinery explicitly."""
    body = record['body']
    if record['record_type'] == 'assessment':
        fields = {'matter', 'profile', 'purpose', 'audience', 'assessed_as_of', 'propositions',
                  'causes', 'evaluation_state', 'evidence_gaps', 'limitations', 'stop_reason',
                  'evidence_selection', 'judgments', 'prior_assessment'}
        selected = {key: value for key, value in body.items() if key in fields}
    else:
        selected = body
    return {'reference': pin(record), 'provenance': record['provenance'], 'body': selected,
            'selection': {'omitted_body_fields': sorted(set(body) - set(selected)),
                          'envelope_extensions': 'not_selected'}}


def _context_selection(reads, state, reference, kinds, matter):
    context = _binding(reads.view, state['scope_id'], reference)
    definition = context['definition']
    if definition['kind'] not in kinds:
        raise ContractError('E_POLICY_INVALID', 'A context is in the wrong semantic slot.')
    if definition['applies_to'] and entity_ref(matter) not in definition['applies_to']:
        raise ContractError('E_SCOPE_FORBIDDEN', 'The context does not apply to the assessed matter.')
    for dependency in (context['version'], context['control']):
        exact = dependency if 'digest' in dependency or 'revision' in dependency else pin(reads.view.get(dependency))
        _, available = _known_snapshot(reads, exact, state['as_of'])
        if available is not True:
            raise ContractError('E_EVIDENCE_UNAVAILABLE', 'Context authority was unavailable at the cut.')
    selection = ContextSelection([context], state['as_of']).value
    for item in selection['components']:
        item.pop('public_targets')  # Control bookkeeping is not semantic evidence.
    return selection


def comparison_preparation_reference(base):
    return descriptor("matter", "semantic-comparison-context", "1.0",
        {"base": base, "context": "exact-scoped-known-snapshots", "missing": "not-supplied-is-not-covered-absence",
         "assessment_selection": "propositions-causes-status-evidence-gaps-with-explicit-omissions",
         "auxiliary_contexts": "explicit-pinned-preferences-and-responsibilities",
         "overflow": "refuse-without-truncation", "authority": "none"}, "matter.semantic.comparison-context.v1")


def prepare_comparison(view, packet, *, cause, after, condition, purpose, audience,
                       before=None, result=None, delivered=None, preferences=(), responsibilities=(),
                       access=None, access_context=None):
    """Append actual as-of host records without altering the source packet."""
    if not isinstance(packet, PreparedPacket) or type(cause) is not str or cause not in CAUSES:
        raise ContractError("E_POLICY_INVALID")
    state = packet.state
    if any(item is None for item in (after, condition, purpose, audience)):
        raise ContractError('E_POLICY_INVALID', 'The current assessment, original condition and named contexts are required.')
    if state['binding'].get('kind') != 'claim' or state['binding'].get('claim') != condition:
        raise ContractError('E_POLICY_INVALID', 'Recovery must remain bound to the original claim.')
    if "comparison" in state:
        raise ContractError("E_POLICY_INVALID", "A comparison transform cannot overwrite an earlier comparison.")
    if access is not None:
        access.require_packet(view, access_context, state)
        view = access.view(view, access_context)
    elif access_context is not None or "access_context" in state:
        raise ContractError("E_AUTHORITY_REQUIRED")
    reads = _Reads(view, state["scope_id"])
    comparison = {"cause": cause}
    for name, reference in (("before", before), ("after", after), ("condition", condition),
                            ("result", result), ("purpose", purpose), ("audience", audience), ("delivered", delivered)):
        if reference is None:
            comparison[name] = {"state": "not_supplied"}
            continue
        exact = fragment(reference, "pinned_ref")
        if exact["record_type"] not in _TYPES[name]:
            raise ContractError("E_SCHEMA_INVALID", "The comparison slot has an incompatible record type.")
        record, known = _known_snapshot(reads, exact, state["as_of"])
        if known is not True:
            raise ContractError("E_EVIDENCE_UNAVAILABLE", "A comparison snapshot was unavailable at the original cut.")
        if name in {'purpose', 'audience'}:
            kinds = {'purpose', 'objective'} if name == 'purpose' else {'audience'}
            comparison[name] = {'state': 'available', 'reference': exact,
                                'selection': _context_selection(reads, state, exact, kinds,
                                    comparison['after']['record']['body']['matter'])}
        else:
            comparison[name] = {"state": "available", "reference": exact, "record": _record_view(record)}
    for name, references in (('preferences', preferences), ('responsibilities', responsibilities)):
        comparison[name] = []
        for reference in bounded(references, 32):
            exact = fragment(reference, 'pinned_ref')
            if exact['record_type'] != PROJECTION_TYPE:
                raise ContractError('E_SCHEMA_INVALID', 'The comparison slot has an incompatible record type.')
            _, available = _known_snapshot(reads, exact, state['as_of'])
            if available is not True:
                raise ContractError('E_EVIDENCE_UNAVAILABLE')
            comparison[name].append(_context_selection(reads, state, exact,
                {'preference' if name == 'preferences' else 'responsibility'},
                comparison['after']['record']['body']['matter']))
    value = packet.value
    value["state"]["comparison"] = _pin_references(reads, comparison, state['as_of'])
    value["state"]["preparation"] = comparison_preparation_reference(state["preparation"])
    dependencies = {canonical_bytes(ref): ref for ref in value["dependencies"]}
    dependencies.update(reads.pins)
    value["dependencies"] = [dependencies[key] for key in sorted(dependencies)]
    maximum = packet.source_manifest["truncation"]["max_packet_bytes"]
    if len(canonical_bytes(value["state"])) > maximum or len(canonical_bytes(value)) > 4 * MAX_PACKET_BYTES:
        raise ContractError("E_BUDGET_EXHAUSTED", "Comparison metadata exceeds the declared packet budget.")
    if access is not None:
        access.require_packet(view._view, access_context, value["state"])
    return PreparedPacket(value, _prepared=True)


def _spec(identity, instruction, yes, no):
    return with_packet(QuestionSpecification({
        "schema_version": "1.0", "namespace": "matter", "id": identity,
        "family": identity.replace("-", "."), "revision": "1.0", "primitive": "proposition_probability",
        "instructions": instruction + " Use {{comparison}} and the original claim {{claim}}. "
            "A missing comparison is unknown, not proof of absence. Judgments cannot change facts, "
            "resolve a condition, grant authority or notify anyone. Do not multiply proposition probabilities.",
        "criteria": {"true": yes, "false": no},
        "required_fields": [
            {"name": "comparison", "path": ["comparison"], "description": "Explicit cause and exact as-of assessment/context/delivery snapshots."},
            {"name": "claim", "path": ["binding"], "description": "Original unresolved claim or candidate relation, never the latest unrelated success."},
        ], "renderer": {"id": "canonical-json-bindings", "version": "1.0"},
    }))


def change_question(cause):
    if type(cause) is not str or cause not in CAUSES:
        raise ContractError("E_POLICY_INVALID")
    meanings = {
        "new_evidence": "Compare new source evidence with the prior supported understanding.",
        "corrected_association": "Compare the interpretation changed by a corrected association; do not invent a new event.",
        "changed_policy": "Compare interpretation under the changed policy/context while holding source facts fixed.",
        "timer": "Compare a declared time boundary becoming due; elapsed time alone is not a new source observation.",
    }
    return _spec("change-" + cause, meanings[cause] + " Is there a supported relevant change in this comparison?",
                 "A supported fact, relationship or interpretation changed for the declared cause.",
                 "No supported relevant change is established; new wording or uncertainty alone is insufficient.")


def contribution_questions():
    return (
        _spec("recovery-matching", "Does the result support recovery of the ORIGINAL unresolved condition? "
            "Match its required target, revision, check and environment. An unrelated success, stale result "
            "or a passing unit check cannot satisfy a failed required integration check.",
            "The required condition has matching success evidence for its target/revision/environment.",
            "The success concerns another condition or lacks the required matching evidence; the condition remains unresolved."),
        _spec("attention-objective", "Does the supported change affect this audience's named purpose, objective or next step? "
            "Use the pinned audience and purpose. A preference changes consequences, never source facts or authority. "
            "Resolved and still relevant are separate dimensions.",
            "An identified supported change contributes to the declared objective or next step.",
            "No supported contribution to this objective is established; topic overlap alone is insufficient."),
        _spec("attention-novelty", "Does this supported contribution add information beyond the last applicable OBSERVED delivery "
            "to the same audience and purpose? Eligibility or a queued attempt is not delivery. Respect current ownership "
            "and already handled work. New uncertainty does not require a human question.",
            "There is a supported contribution not already conveyed by the applicable observed delivery.",
            "The contribution was already delivered, is handled, or novelty cannot be established from available history."),
    )
