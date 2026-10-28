"""MAT-040 predeclared tuning and source-grouped held-out measurement.

The corpus preserves reviewer declarations, not proof that a human reviewed it.
Reports are data for explicit host review, never automatic runtime admission.
No network, file fetch, label inference or provider construction occurs here.
"""
from copy import deepcopy
from decimal import Decimal, localcontext, ROUND_FLOOR
from math import comb

from .._rule_values import FrozenValue, checked, descriptor, domain, fragment
from ..canonical import canonical_bytes, canonical_digest
from ..contracts import ContractError
from ..semantic import Batch, BatchResult
from ..semantic.rendering import RenderedQuestion
from ..semantic.qualification import SemanticCertificate
from ..time import knowledge_eligible
from .corpus import FrozenCorpus
from .splits import SplitManifest, lineage_groups, make_splits

POLARITIES=('positive','negative')


def _fail(reason):raise ContractError('E_EVIDENCE_INVALID',reason)


def _number(value):
    fragment(value,'decimal_string');number=Decimal(value)
    if not number.is_finite() or len(value)>1024:_fail('invalid_exact_measure')
    return number


def lower_accuracy(correct,total,*,alpha):
    """One-sided Clopper-Pearson inversion, rounded downward to 12 decimals.

    NIST TN 2119 §4.1, binomial-test inversion. Input trials here are whole
    connected provenance groups, marked correct only if every accepted case is
    correct. This assumes independent, representative groups; it cannot prove
    population representativeness or remove unrecorded dependence.
    """
    if type(total) is not int or type(correct) is not int or not 0<=correct<=total<=4096:_fail('invalid_support')
    alpha=_number(alpha)
    if not 0<alpha<1:_fail('invalid_confidence')
    if not correct:return '0'
    with localcontext() as context:
        context.prec=80
        low=Decimal(0);high=Decimal(correct)/total
        for _ in range(100):
            p=(low+high)/2
            term=Decimal(comb(total,correct))*(p**correct)*((1-p)**(total-correct));tail=term
            for j in range(correct,total):
                term*=Decimal(total-j)/(j+1)*p/(1-p);tail+=term
            if tail>alpha:high=p
            else:low=p
        return format(low.quantize(Decimal('0.000000000001'),rounding=ROUND_FLOOR),'f')


class CalibrationPlan(FrozenValue):
    def __init__(self,value):
        data=checked(value,required={'id','identity','family','corpus_digest','split_digest','outcomes','target_accuracy','minimum_episodes','confidence','minimum_coverage','maximum_failure_fraction','candidate_regions','artifacts'})
        fragment(data['id'],'identifier')
        for key in ('corpus_digest','split_digest'):fragment(data[key],'sha256')
        if data['family'] not in {'association','recovery','attention'}:_fail('unsupported_reference_family')
        checked(data['outcomes'],required=POLARITIES)
        if any(type(x) is not str or not x for x in data['outcomes'].values()) or len(set(data['outcomes'].values()))!=2:_fail('distinct_reference_outcomes_required')
        for key in ('target_accuracy','minimum_episodes'):checked(data[key],required=POLARITIES)
        if not 0<_number(data['confidence'])<1:_fail('invalid_confidence')
        for key in ('minimum_coverage','maximum_failure_fraction'):
            if not 0<=_number(data[key])<=1:_fail('invalid_predeclared_coverage')
        if type(data['artifacts']) is not list or not data['artifacts']:_fail('pinned_artifacts_required')
        for artifact in data['artifacts']:fragment(artifact,'pinned_ref')
        for p in POLARITIES:
            if not 0<_number(data['target_accuracy'][p])<=1 or type(data['minimum_episodes'][p]) is not int or not 1<=data['minimum_episodes'][p]<=4096:_fail('invalid_predeclared_target')
        if type(data['candidate_regions']) is not list or not 1<=len(data['candidate_regions'])<=64:_fail('bounded_predeclared_regions_required')
        if len({canonical_bytes(x) for x in data['candidate_regions']})!=len(data['candidate_regions']):_fail('duplicate_candidate_regions')
        for regions in data['candidate_regions']:
            # Reuse the existing runtime certificate region/identity validator.
            SemanticCertificate({'schema_version':'1.0','namespace':'calibration.plan','id':'validation','semantic_version':'1.0','description':'Structural plan validation only.',
                'identity':data['identity'],'regions':regions,'evaluation':data['artifacts'][0],
                'valid_from':{'state':'known','value':'2000-01-01T00:00:00Z','precision':'second'},
                'valid_until':{'state':'known','value':'2000-01-02T00:00:00Z','precision':'second'}})
        if data['identity']['mode']!='provider_shadow':_fail('actual_provider_mode_required')
        self._freeze(data)
    @property
    def digest(self):return canonical_digest(self.value,'matter.calibration-plan.v1')


class TrialObservation(FrozenValue):
    """Measurement from an actual typed batch/result and guarded render manifest."""
    def __init__(self,episode_id,case_id,*,batch,rendered,result,domain_scope,model_resolution,measure):
        if not isinstance(batch,Batch) or not isinstance(rendered,RenderedQuestion) or not isinstance(result,BatchResult):_fail('typed_provider_observation_required')
        for value in (episode_id,case_id):fragment(value,'identifier')
        b=batch.value;r=result.value;m=rendered.manifest
        if r['batch_digest']!=batch.digest or rendered.question.value not in b['questions'] or m['packet_digest']!=b['packet_digest']:_fail('provider_observation_binding_mismatch')
        identity={k:b['context'][k] for k in ('provider','transport','adapter_version','mode','requested_model')}
        identity.update(resolved_model=r['resolved_model'],model_resolution=fragment(model_resolution,'component_ref'),question=m['specification'],
            criteria_digest=m['criteria_digest'],renderer=m['renderer'],packet_profile=b['state'].get('profile'),preparation=b['state'].get('preparation'),
            domain=fragment(domain_scope,'component_ref'),measure=deepcopy(measure),precision=r['precision_profile'])
        head=next((h for h in r['diagnostics'] if h['id']==rendered.question.value['id']),None)
        status='valid' if result.primitive_valid and r['admission']['exact_numeric'] and head is not None and head['status']=='valid' else 'failed'
        answer=None if status!='valid' else head['answer'];number=None;choice=None
        if answer is not None:
            name=measure['name'];primitive=answer['primitive']
            if (name=='probability' and primitive=='proposition_probability' or name=='score' and primitive=='score' or name in {'confidence','choice_probability'} and primitive=='choice'):
                number=answer['probabilities'][answer['choice']] if name=='choice_probability' else answer[name]
                choice=answer.get('choice');_number(number)
            else:status='failed'
        self._freeze({'episode_id':episode_id,'case_id':case_id,'identity':identity,'status':status,'value':number,'choice':choice,
            'as_of':b['state'].get('as_of'),'source_hashes':[e['text_digest'] for e in b['state'].get('evidence',[])],
            'batch_digest':batch.digest,'result_digest':result.digest,'rendered_digest':rendered.rendered_digest})


class CalibrationPartition(FrozenValue):
    def __init__(self,value,*,_factory=False):
        if not _factory:_fail('use_partition_corpus')
        self._freeze(value)


def partition_corpus(corpus,split,name):
    """Trusted preparation strips other partitions' labels before fitting."""
    if not isinstance(corpus,FrozenCorpus) or not isinstance(split,SplitManifest) or name not in {'tuning','qualification','final'}:_fail('frozen_partition_required')
    if split.value['corpus_digest']!=corpus.sha256:_fail('partition_inputs_mismatch')
    selected=[e for e in corpus.value['episodes'] if split.value['assignments'][e['id']]==name]
    ids={e['id'] for e in selected}
    exposed=set(split.value['ever_tuning'])|{i for e in split.value['exposures'] for i in e['episode_ids']}
    for group in lineage_groups(corpus):
        if exposed.intersection(group):exposed.update(group)
    return CalibrationPartition({'partition':name,'corpus_digest':corpus.sha256,'split_digest':split.digest,'episodes':selected,
        'source_verification':[x for x in corpus.source_verification if x['episode_id'] in ids],
        'groups':{i:g for g in lineage_groups(corpus) for i in g if i in ids},'held_out_usable':name!='tuning' and not bool(ids.intersection(exposed))},_factory=True)


def _inputs(plan,partition,name):
    if not isinstance(plan,CalibrationPlan) or not isinstance(partition,CalibrationPartition):_fail('frozen_calibration_inputs_required')
    data=plan.value;p=partition.value
    if p['partition']!=name or data['corpus_digest']!=p['corpus_digest'] or data['split_digest']!=p['split_digest']:_fail('predeclared_inputs_changed')
    return data


def _references(partition,episode):
    # Inspect labels only AFTER the caller selected the partition. In particular,
    # tuning does not call corpus.denominators(), which reads held-out labels.
    verification={(x['source']['id'],x['source']['revision']):x['status']=='verified' for x in partition['source_verification'] if x['episode_id']==episode['id']}
    observations={x['id']:x for x in episode['observations']}
    for case in episode['cases']:
        labels=[l for l in episode['labels'] if l['case_id']==case['id']]
        independent=[l for l in labels if l['origin']=='independent']
        eligible=(case['eligibility']['state']=='eligible' and bool(independent) and all(l['status']=='accepted' for l in independent) and len({l['outcome'] for l in independent})==1)
        refs=[observations[i]['source'] for i in case['target_observation_ids']]+[e['source'] for l in independent for e in l['evidence']]
        eligible=eligible and all(verification.get((r['id'],r['revision']),False) for r in refs)
        yield case,(independent[0]['outcome'] if eligible else None),[observations[i] for i in case['target_observation_ids']]


def _rows(plan,partition,read_trial):
    if not callable(read_trial):_fail('trial_reader_required')
    selected=partition.value;groups={i:tuple(g) for i,g in selected['groups'].items()}
    rows=[]
    for episode in selected['episodes']:
        for case,outcome,targets in _references(selected,episode):
            if case['family']!=plan['family']:continue
            excluded=case['eligibility']['state']=='excluded'
            raw=None if excluded else read_trial(episode['id'],case['id'])
            if raw is not None and (not isinstance(raw,TrialObservation) or raw.value['episode_id']!=episode['id'] or raw.value['case_id']!=case['id']):_fail('trial_routing_mismatch')
            trial=None if raw is None else raw.value
            status='excluded' if excluded else ('missing' if trial is None else trial['status'])
            if trial is not None and trial['identity']!=plan['identity']:status='mismatched'
            if trial is not None and status=='valid':
                if any(t['source']['sha256'] not in trial['source_hashes'] or knowledge_eligible(t['available_at'],trial['as_of']) is not True for t in targets):status='unavailable'
            reference=next((p for p,v in plan['outcomes'].items() if v==outcome),None)
            rows.append({'episode_id':episode['id'],'case_id':case['id'],'group':list(groups[episode['id']]),
                'reference':reference,'status':status,'value':None if trial is None else trial['value'],
                'choice':None if trial is None else trial['choice'],'trial_digest':None if raw is None else canonical_digest(raw.value,'matter.calibration-trial.v1')})
    return rows


def _decision(row,regions):
    if row['status']!='valid' or row['reference'] is None:return None
    value=_number(row['value'])
    for polarity,region in regions.items():
        if region is None:continue
        if region['choices'] and row['choice'] not in region['choices']:continue
        if (region['minimum'] is None or value>=_number(region['minimum'])) and (region['maximum'] is None or value<=_number(region['maximum'])):return polarity
    return None


def _metrics(plan,rows,regions):
    support={};decisions=[(row,_decision(row,regions)) for row in rows]
    with localcontext() as context:
        context.prec=80;alpha=format((1-_number(plan['confidence']))/sum(r is not None for r in regions.values()),'f')
    for p in POLARITIES:
        if regions[p] is None:support[p]=None;continue
        # All accepted cases within a connected source lineage must be correct.
        # Repeated messages/runs never create additional independent support.
        accepted={};eligible={}
        for row,decision in decisions:
            if row['reference'] is not None:eligible[tuple(row['group'])]=True
            if decision==p:accepted.setdefault(tuple(row['group']),[]).append(row['reference']==p)
        n=len(accepted);errors=sum(not all(v) for v in accepted.values());lower=lower_accuracy(n-errors,n,alpha=alpha)
        support[p]={'episodes':len(eligible),'minimum_episodes':plan['minimum_episodes'][p],'accepted':n,'errors':errors,
            'target_accuracy':plan['target_accuracy'][p],'lower_accuracy_bound':lower,
            'passed':n>=plan['minimum_episodes'][p] and _number(lower)>=_number(plan['target_accuracy'][p])}
    counts={'scheduled':len(rows),'eligible':sum(r['reference'] is not None for r in rows),
        'explicitly_excluded':sum(r['status']=='excluded' for r in rows),'unlabeled_or_ineligible':sum(r['reference'] is None and r['status']!='excluded' for r in rows),'accepted':sum(d is not None for _,d in decisions),
        'errors':sum(d is not None and d!=r['reference'] for r,d in decisions),'abstained':sum(r['reference'] is not None and r['status']=='valid' and d is None for r,d in decisions)}
    counts['failures']={s:sum(r['status']==s for r in rows) for s in ('failed','missing','mismatched','unavailable')}
    eligible_groups={tuple(r['group']) for r in rows if r['reference'] is not None}
    accepted_groups={tuple(r['group']) for r,d in decisions if d is not None}
    failed_groups={tuple(r['group']) for r in rows if r['reference'] is not None and r['status'] in counts['failures']}
    counts['independent_eligible_groups']=len(eligible_groups);counts['independent_accepted_groups']=len(accepted_groups);counts['independent_failed_groups']=len(failed_groups)
    coverage_ok=bool(eligible_groups) and Decimal(len(accepted_groups))>=_number(plan['minimum_coverage'])*len(eligible_groups)
    failures_ok=bool(eligible_groups) and Decimal(len(failed_groups))<=_number(plan['maximum_failure_fraction'])*len(eligible_groups)
    counts['reference_classes']={p:{'cases':sum(r['reference']==p for r in rows),'errors':sum(r['reference']==p and d is not None and d!=p for r,d in decisions),
        'accepted':sum(r['reference']==p and d is not None for r,d in decisions)} for p in POLARITIES}
    return {'support':support,'counts':counts,'coverage_passed':coverage_ok,'failure_limit_passed':failures_ok,
        'passed':coverage_ok and failures_ok and all(v is None or v['passed'] for v in support.values())}


class FittedThresholds(FrozenValue):
    def __init__(self,value,*,_factory=False):
        if not _factory:_fail('use_fit_thresholds')
        self._freeze(value)


def fit_thresholds(plan,*,partition,read_trial):
    data=_inputs(plan,partition,'tuning')
    rows=_rows(data,partition,read_trial)
    tried=[{'regions':r,**_metrics(data,rows,r)} for r in data['candidate_regions']]
    passing=[r for r in tried if r['passed']]
    selected=max(passing,key=lambda r:(r['counts']['accepted'],-r['counts']['errors'],canonical_bytes(r['regions']))) if passing else None
    return FittedThresholds({'plan_digest':plan.digest,'corpus_digest':partition.value['corpus_digest'],'split_digest':partition.value['split_digest'],
        'status':'fitted' if selected else 'insufficient','regions':None if selected is None else selected['regions'],
        'tried':tried,'tuning_trials':rows},_factory=True)


def evaluate_thresholds(plan,fitted,*,corpus,split,read_trial,artifacts,at):
    partition=partition_corpus(corpus,split,'qualification');data=_inputs(plan,partition,'qualification');fragment(at,'known_time')
    if not isinstance(fitted,FittedThresholds) or fitted.value['plan_digest']!=plan.digest:_fail('fitted_method_mismatch')
    if fitted.value['status']!='fitted':_fail('no_tuning_selection')
    selected=[e['id'] for e in corpus.value['episodes'] if split.value['assignments'][e['id']]=='qualification']
    if not partition.value['held_out_usable']:_fail('held_out_exposed')
    rows=_rows(data,partition,read_trial);regions=fitted.value['regions'];metrics=_metrics(data,rows,regions)
    method=descriptor('matter','grouped-clopper-pearson','1.0',{'confidence':data['confidence'],'polarity_adjustment':'bonferroni',
        'unit':'connected-episode-provenance-group-all-accepted-correct','numeric':'80-digit-binomial-inversion-floor-12-decimals'},'matter.calibration-interval.v1')
    evaluation={'schema_version':'1.0','identity':data['identity'],'regions':regions,'status':'passed' if metrics['passed'] else 'failed',
        'labels':'independent' if metrics['counts']['eligible'] and not metrics['counts']['unlabeled_or_ineligible'] else 'mixed',
        'support':metrics['support'],'interval_method':method,'artifacts':artifacts,
        'reason':'Source-grouped held-out assessment; independent labels are host declarations pending actual host review.'}
    if evaluation['labels']!='independent':evaluation['status']='failed'
    domain('semantic-qualification-evaluation',evaluation)
    exposure={'episode_ids':selected,'reason':'Held-out results inspected; further question/threshold selection makes these exposed material.',
        'at':at,'question':data['identity']['question']}
    next_split=make_splits(corpus,identity=split.value['id'],revision=split.value['revision']+1,seed=split.value['seed'],weights=split.value['weights'],previous=split,
        exposures=[*split.value['exposures'],exposure] if selected else split.value['exposures'])
    return {'evaluation':evaluation,'plan_digest':plan.digest,'fitted_digest':canonical_digest(fitted.value,'matter.fitted-thresholds.v1'),
        'metrics':metrics,'trials':rows,'evaluated_split_digest':split.digest,'next_split':next_split.value,
        'limits':['One family at a time; no universal accuracy or representativeness claim.',
            'Group all-accepted-correct bounds are not per-message accuracy intervals.',
            'Host must retain next_split and exposure history before any further experiment.',
            'No runtime certificate is installed or action authority granted.']}
