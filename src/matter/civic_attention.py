"""MAT-049 bounded civic source questions and unqualified projections.

Source questions receive no audience context. The host may use their diagnostic
projection only in an isolated capture experiment until separately qualified.
A source-reported action is never reviewed legal authority or permission to act.
"""
from decimal import Decimal

from .canonical import canonical_digest
from .contracts import ContractError
from .semantic.questions import QuestionSpecification
from .semantic.families import with_packet
from .semantic.families.evidence import claim_evidence_questions


def _choice(identity, instructions, options):
    return with_packet(QuestionSpecification({'schema_version':'1.0','namespace':'matter.civic',
        'id':identity,'family':'civic.'+identity,'revision':'1.0','primitive':'choice',
        'instructions':instructions+' Use {{civic}}. Classify only the named actor and provision. '
            'Missing evidence remains unknown. A selected label grants no authority or permission.',
        'criteria':[{'id':key,'description':description} for key,description in options],
        'required_fields':[{'name':'civic','path':['civic'],'description':'Exact actor, provision, source scope and question target; no client preferences.'}],
        'renderer':{'id':'canonical-json-bindings','version':'1.0'}}))


def source_questions():
    return (
        _choice('stage','What stage does this supplied source report for the named acting body and target act?',[
            ('pending','The named acting body has a proposal, agenda item or future action to consider. A prior recommendation by another body does not establish its final action.'),
            ('recommendation','The named acting body itself expressly recommends the target act to another decision maker.'),
            ('recorded_action','This source expressly records the named acting body completing the target act or vote; proposed language, signatures to obtain or an agenda do not establish completion.'),
            ('unknown','The source does not distinguish these stages, conflicts, or omits the required evidence.')]),
        _choice('stance','What position is expressly evidenced for the named stance actor on this specific provision?',[
            ('proponent','The named actor expressly supports or recommends this specific provision.'),
            ('opponent','The named actor expressly opposes this specific provision.'),
            ('neutral','The named actor expressly states a neutral position on this specific provision.'),
            ('unknown','No position is evidenced, the actor/provision is ambiguous, or evidence conflicts. Silence, mention, institutional role and a collective result do not assign positions to individual members.')]),
        *(s for s in claim_evidence_questions() if s.value['family'] in {'evidence.established','evidence.qualification'}),
    )


def project_source(shadow):
    """Separate reported stage/stance from legal effect and qualification."""
    if shadow.get('qualification_status') != 'unknown' or shadow.get('consequential_use') is not False:
        raise ContractError('E_EVIDENCE_INVALID','unqualified_shadow_required')
    if shadow.get('comparison') is not None:
        raise ContractError('E_POLICY_INVALID','source_question_must_not_use_audience_comparison')
    heads={q['family']:q for q in shadow['questions']}
    def selected(family):
        q=heads.get(family,{})
        answer=q.get('answer') if q.get('status')=='answered' else None
        if not answer:return 'unknown'
        chosen=answer['choice']
        return chosen if Decimal(answer['probabilities'][chosen]) >= Decimal('0.8') else 'unknown'
    probabilities={k:heads[k].get('answer') for k in ('evidence.established','evidence.qualification') if k in heads}
    value={'proposed_stage':selected('civic.stage'),'proposed_stance':selected('civic.stance'),
        'evidence_heads':probabilities,'legal_status':'unknown','authority':'unresolved',
        'qualification':'unknown','consequential_use':False,'proposed_actions':[],
        'source_batch_digest':shadow['batch_digest'],'source_result_digest':shadow['result_digest']}
    value['factual_projection_digest']=canonical_digest(value,'matter.civic-source-projection.v1')
    return value
