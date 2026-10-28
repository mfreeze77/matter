"""MAT-040 construct candidates only from exact, actual host-reviewed reports.

Installation, applicability, revocation and permission remain MAT-031 duties.
This does not create a review receipt or admit its own unreviewed measurements.
"""
from .._rule_values import domain
from ..contracts import ContractError,validate_record
from ..semantic.qualification import SemanticCertificate
from ..storage import pin


def certificate_from_review(view,report,*,review,reviewers,namespace,identity,version,description,valid_from,valid_until):
    evaluation=report['evaluation']
    domain('semantic-qualification-evaluation',evaluation)
    if evaluation['status']!='passed' or evaluation['labels']!='independent':raise ContractError('E_EVIDENCE_INVALID','Held-out support and independent review are required.')
    record=validate_record(view.get(review))
    if (pin(record)!=review or record['record_type']!='receipt' or record['provenance']['origin']!='host' or record['provenance']['producer'] not in reviewers or
        record['body']['stage']!='evaluation' or record['body']['details']!=domain('semantic-qualification-evaluation',evaluation)):
        raise ContractError('E_AUTHORITY_REQUIRED','An exact admitted host review of this evaluation is required.')
    for artifact in evaluation['artifacts']:
        if pin(view.get(artifact))!=artifact:raise ContractError('E_EVIDENCE_UNAVAILABLE')
    for p,region in evaluation['regions'].items():
        if region is None:continue
        s=evaluation['support'][p]
        if s is None or not s['passed'] or not 1<=s['minimum_episodes']<=s['accepted']<=s['episodes'] or s['errors']>s['accepted']:
            raise ContractError('E_EVIDENCE_INVALID','Independent accepted support is insufficient.')
        from decimal import Decimal
        from fractions import Fraction
        lower=Decimal(s['lower_accuracy_bound']);target=Decimal(s['target_accuracy'])
        if not 0<=target<=lower<=1 or Fraction(lower)>Fraction(s['accepted']-s['errors'],s['accepted']):raise ContractError('E_EVIDENCE_INVALID','The reviewed bound is inconsistent.')
    return SemanticCertificate({'schema_version':'1.0','namespace':namespace,'id':identity,'semantic_version':version,'description':description,
        'identity':evaluation['identity'],'regions':evaluation['regions'],'evaluation':review,'valid_from':valid_from,'valid_until':valid_until})
