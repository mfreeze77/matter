"""MAT-037 comparable paired arms; retrieval differences are separate experiments."""
from .._rule_values import FrozenValue,checked,fragment
from ..canonical import canonical_bytes,canonical_digest
from ..contracts import ContractError
from .corpus import FrozenCorpus,_text


def _fail(reason):raise ContractError('E_EVIDENCE_INVALID',reason)


class ArmManifest(FrozenValue):
    def __init__(self,value,*,corpus):
        value=checked(value,required={'schema_version','id','kind','corpus_digest','policy','semantic_families','cases','retrieval_experiment'})
        if not isinstance(corpus,FrozenCorpus) or value['corpus_digest']!=corpus.sha256 or value['schema_version']!='1.0':_fail('arm_corpus_mismatch')
        _text(value['id'],'arm/id');fragment(value['policy'],'component_ref')
        if value['kind'] not in ('A','B') or type(value['semantic_families']) is not list or len(value['semantic_families'])>64:_fail('invalid_arm_kind')
        for family in value['semantic_families']:fragment(family,'component_ref')
        if value['kind']=='A' and value['semantic_families']:_fail('baseline_cannot_add_semantics')
        if value['kind']=='B' and not value['semantic_families']:_fail('candidate_must_declare_semantics')
        if value['retrieval_experiment'] is not None:_text(value['retrieval_experiment'],'arm/retrieval_experiment')
        if type(value['cases']) is not list or len(value['cases'])>4096:_fail('invalid_arm_cases')
        eligible={(e['id'],c['id']) for e in corpus.value['episodes'] for c in e['cases'] if c['eligibility']['state']=='eligible'}
        seen=set()
        for case in value['cases']:
            checked(case,required={'episode_id','case_id','as_of','packet_digest','packet_profile'})
            key=(case['episode_id'],case['case_id']);fragment(case['as_of'],'known_time');fragment(case['packet_digest'],'sha256');fragment(case['packet_profile'],'component_ref')
            if key not in eligible or key in seen:_fail('unknown_or_duplicate_arm_case')
            seen.add(key)
            episode=next(e for e in corpus.value['episodes'] if e['id']==key[0]);target=next(c for c in episode['cases'] if c['id']==key[1])
            admitted={x['observation']['id'] for x in corpus.prefix(as_of=case['as_of'])['included'] if x['episode_id']==key[0]}
            if not set(target['target_observation_ids'])<=admitted:_fail('arm_target_not_available')
        if seen!=eligible:_fail('arm_missing_eligible_cases')
        value['cases']=sorted(value['cases'],key=canonical_bytes);self._freeze(value)

    @property
    def digest(self):return canonical_digest(self.value,'matter.arm-manifest.v1')


def compare_arms(a,b):
    if not isinstance(a,ArmManifest) or not isinstance(b,ArmManifest):_fail('validated_arms_required')
    a,b=a.value,b.value
    if a['kind']!='A' or b['kind']!='B' or a['corpus_digest']!=b['corpus_digest'] or a['policy']!=b['policy']:_fail('incomparable_policy_or_corpus')
    paired=[{'episode_id':x['episode_id'],'case_id':x['case_id'],'A':x,'B':y} for x,y in zip(a['cases'],b['cases'])]
    if a['retrieval_experiment'] is None and b['retrieval_experiment'] is None:
        if a['cases']!=b['cases']:_fail('hidden_candidate_evidence_or_packet_change')
        return {'comparison':'principal','paired_cases':paired,'matched_packets':True}
    if not a['retrieval_experiment'] or a['retrieval_experiment']!=b['retrieval_experiment']:_fail('separate_retrieval_experiment_required_on_both_arms')
    if [(x['episode_id'],x['case_id']) for x in a['cases']]!=[(x['episode_id'],x['case_id']) for x in b['cases']]:_fail('retrieval_cases_do_not_match')
    return {'comparison':'separate_retrieval','experiment':a['retrieval_experiment'],'paired_cases':paired,'matched_packets':a['cases']==b['cases']}
