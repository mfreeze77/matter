"""MAT-041 controlled semantic probes over existing typed batches/results.

No executor, credential, source reader, certificate mutation or delivery is
constructed. A probe's intended invariance never transfers qualification.
"""
from copy import deepcopy
from decimal import Decimal, localcontext
from dataclasses import dataclass

from .._rule_values import FrozenValue, checked
from ..canonical import canonical_bytes, canonical_digest
from ..contracts import ContractError
from ..semantic import Batch, BatchResult
from ..semantic.contracts import _number, _decimal_string
from ..semantic.questions import QuestionSpecification
from ..semantic.rendering import render_question

ROLES=('topic','matter','recurring_matter','occurrence','equivalent','complement')


def _fail(reason):raise ContractError('E_EVIDENCE_INVALID',reason)


class SensitivitySuite(FrozenValue):
    def __init__(self,value,*,_factory=False):
        if not _factory:_fail('use_prepare_sensitivity')
        self._freeze(value)
    @property
    def digest(self):return canonical_digest(self.value,'matter.sensitivity-suite.v1')


def choice_variants(specification):
    """Preserve definitions with explicit label -> original-outcome mappings."""
    if not isinstance(specification,QuestionSpecification) or specification.value['primitive']!='choice':_fail('choice_specification_required')
    data=specification.value;options=data['criteria'];count=len(options)
    if count<2:_fail('multiple_choice_outcomes_required')
    definitions={o['id']:o['description'] for o in options}
    variants=[]
    for kind,indices,labels in (
        ('reverse',list(reversed(range(count))),[o['id'] for o in options]),
        ('rotate',list(range(1,count))+[0],[o['id'] for o in options]),
        ('neutral_labels',list(range(count)),['opt_'+str(i) for i in range(count)]),
        ('name_definition_swap',list(range(1,count))+[0],[o['id'] for o in options])):
        value=deepcopy(data)
        value.update(id='probe-'+canonical_digest({'source':specification.reference,'kind':kind},'matter.sensitivity-id.v1')[:24],
            family='sensitivity.'+data['family'],revision='probe-1')
        if kind in ('reverse','rotate'):
            value['criteria']=[options[i] for i in indices];mapping={o['id']:o['id'] for o in options}
        else:
            value['criteria']=[{'id':labels[i],'description':options[j]['description']} for i,j in enumerate(indices)]
            mapping={labels[i]:options[j]['id'] for i,j in enumerate(indices)}
        if any(definitions[mapping[o['id']]]!=o['description'] for o in value['criteria']):_fail('invalid_semantic_remapping')
        variants.append({'kind':kind,'specification':QuestionSpecification(value).value,'to_original':mapping})
    return variants


def prepare_sensitivity(*,identity,scope_id,state,choice,propositions,positive_choice,references,context,tolerance):
    """Two identical bundled baselines, four choice controls, seven singletons.

    Required packet fields are rendered for the ENTIRE schedule before returning
    any executable jobs. Host reference labels remain outside all model inputs.
    The host supplies a frozen, eligible packet; this port does no retrieval.
    """
    if not isinstance(choice,QuestionSpecification) or set(propositions)!=set(ROLES):_fail('complete_probe_questions_required')
    specs={'choice':choice,**{r:propositions[r] for r in ROLES}}
    if any(not isinstance(s,QuestionSpecification) for s in specs.values()):_fail('typed_questions_required')
    if choice.value['primitive']!='choice' or any(propositions[r].value['primitive']!='proposition_probability' for r in ROLES):_fail('probe_primitive_mismatch')
    labels=[x['id'] for x in choice.value['criteria']]
    if positive_choice not in labels or not 0<=_number(tolerance)<=1:_fail('invalid_probe_policy')
    if type(identity)is not str or not identity or len(identity)>128:_fail('bounded_probe_identity_required')
    if type(references)is not dict or set(references)-set(specs):_fail('unknown_reference_role')
    for role,ref in references.items():
        checked(ref,required={'origin','outcome','artifact'})
        if ref['origin'] not in {'synthetic','independent','teacher','unresolved'} or type(ref['artifact'])is not str or not ref['artifact']:_fail('explicit_reference_origin_required')
        if ref['outcome'] not in (labels if role=='choice' else ['true','false',None]):_fail('reference_outcome_mismatch')
    state=deepcopy(state);digest=canonical_digest(state,'matter.semantic.packet.v1');jobs=[]
    def append(kind,selected,mapping=None):
        number=len(jobs);rendered={role:render_question(spec,state,'q'+str(list(specs).index(role))) for role,spec in selected.items()}
        name='probe-'+str(number).zfill(2)
        batch=Batch({'schema_version':'1.0','id':name,'scope_id':scope_id,'run_id':identity,'stage_id':name,
            'state':state,'packet_digest':digest,'questions':[r.question.value for r in rendered.values()],'context':context})
        jobs.append({'id':name,'kind':kind,'batch':batch.value,'heads':{role:{'specification':selected[role].reference,
            'rendered':r.value,'to_original':mapping if role=='choice' and mapping is not None else ({x:x for x in labels} if role=='choice' else {'true':'true','false':'false'})} for role,r in rendered.items()}})
    append('baseline',specs);append('baseline',specs)
    for variant in choice_variants(choice):append(variant['kind'],{'choice':QuestionSpecification(variant['specification'])},variant['to_original'])
    for role,spec in specs.items():append('single-'+role,{role:spec})
    value={'schema_version':'matter.sensitivity-suite.v1','id':identity,'scope_id':scope_id,'state_digest':digest,
        'as_of':state.get('as_of'),'specifications':{r:s.reference for r,s in specs.items()},'families':{r:s.value['family'] for r,s in specs.items()},'positive_choice':positive_choice,
        'references':references,'tolerance':tolerance,'jobs':jobs}
    if len(canonical_bytes(value))>1048576:_fail('probe_suite_byte_limit')
    return SensitivitySuite(value,_factory=True)


@dataclass(frozen=True)
class ProbeObservation:
    job_id: str
    batch: Batch
    result: BatchResult
    artifact: str


def sensitivity_report(suite,observations):
    """Compare typed, bound observations; no ground-truth or qualification claim.

    Provider/transport/model/precision changes are confounds. Original raw
    receipts stay in the host's existing artifact store, referenced by digest.
    """
    if not isinstance(suite,SensitivitySuite) or type(observations) not in (list,tuple):_fail('typed_probe_inputs_required')
    data=suite.value;jobs={j['id']:j for j in data['jobs']};seen={};rows=[]
    for observation in observations:
        if not isinstance(observation,ProbeObservation) or not isinstance(observation.batch,Batch) or not isinstance(observation.result,BatchResult):_fail('typed_probe_observation_required')
        if observation.job_id not in jobs or observation.job_id in seen or type(observation.artifact)is not str or not observation.artifact:_fail('duplicate_or_unknown_probe_observation')
        expected=Batch(jobs[observation.job_id]['batch']).value;actual=observation.batch.value;result=observation.result.value
        if any(actual[k]!=expected[k] for k in ('id','scope_id','run_id','stage_id','state','packet_digest','questions')) or result['batch_digest']!=observation.batch.digest:_fail('probe_result_binding_mismatch')
        seen[observation.job_id]=observation
    for job in data['jobs']:
        observation=seen.get(job['id']);planned=Batch(job['batch']).value
        for role,head in job['heads'].items():
            row={'job_id':job['id'],'kind':job['kind'],'role':role,'specification':head['specification'],
                'status':'missing','selected':None,'native_selected':None,'probabilities':None,'artifact':None,
                'batch_digest':None,'result_digest':None,'raw_response_digest':None,'method':None}
            if observation is not None:
                batch=observation.batch.value;result=observation.result.value;context=batch['context']
                method={k:context[k] for k in ('provider','transport','adapter_version','requested_model','mode')}
                method.update(resolved_model=result['resolved_model'],precision=result['precision_profile'])
                row.update(method=method,artifact=observation.artifact,batch_digest=observation.batch.digest,
                    result_digest=observation.result.digest,raw_response_digest=canonical_digest(result['raw_response'],'matter.probe-raw-receipt.v1'))
                diagnostic=next((d for d in result['diagnostics'] if d['id']==head['rendered']['question']['id']),None)
                row['status']='failed'
                if observation.result.primitive_valid and result['admission']['exact_numeric'] and diagnostic is not None and diagnostic['status']=='valid':
                    row['status']='valid';answer=diagnostic['answer']
                    if role=='choice':
                        row.update(selected=head['to_original'][answer['choice']],native_selected=answer['choice'],
                            probabilities={head['to_original'][k]:v for k,v in answer['probabilities'].items()})
                    else:
                        with localcontext() as ctx:
                            ctx.prec=512;p=_number(answer['probability'])
                            row.update(selected='true' if p>=Decimal('0.5') else 'false',probabilities={'true':_decimal_string(p),'false':_decimal_string(1-p)})
                expected_context=planned['context']
                if row['status']=='valid' and (any(context[k]!=expected_context[k] for k in ('provider','transport','adapter_version','requested_model')) or result['resolved_model']!=expected_context['requested_model']):
                    row['status']='method_mismatch'
            rows.append(row)
    methods=[r['method'] for r in rows if r['kind']=='baseline' and r['status']=='valid']
    anchor=methods[0] if methods else None
    for row in rows:
        if anchor is not None and row['status']=='valid' and row['method']!=anchor:row['status']='method_mismatch'
    with localcontext() as ctx:
        ctx.prec=512
        report=_compare(data,rows)
    return {'schema_version':'matter.sensitivity-report.v1','suite_digest':suite.digest,'state_digest':data['state_digest'],
        'status':'complete' if all(r['status']=='valid' for r in rows) else 'incomplete','scheduled_calls':len(jobs),'scheduled_heads':len(rows),'counts':{s:sum(r['status']==s for r in rows) for s in ('valid','missing','failed','method_mismatch')},
        'observations':rows,**report,'reference_origins':{r:v['origin'] for r,v in data['references'].items()},
        'qualification':'not_run','provider_accuracy':'not_run','consequential_use':False,
        'limits':['Two within-snapshot repeats are descriptive, not a population variation estimate.',
            'Choice alteration controls share the single-question context; their repeat envelope is measured on bundled baselines, not repeated singleton calls.',
            'Agreement or consistency is not correctness; reference origins are host declarations, not verified adjudication.',
            'A probe changes exact semantic identity even when invariance is intended; no certificate transfers.',
            'No joint probability is constructed, no certificate is revoked/installed, and no delivery occurs.']}


def _compare(data,rows):
    tolerance=_number(data['tolerance']);baselines={r:[x for x in rows if x['role']==r and x['kind']=='baseline' and x['status']=='valid'] for r in ('choice',*ROLES)}
    repeats={};checks=[]
    for role,values in baselines.items():
        labels=list(values[0]['probabilities']) if values else []
        ranges={label:_decimal_string(max(_number(v['probabilities'][label]) for v in values)-min(_number(v['probabilities'][label]) for v in values)) for label in labels}
        repeats[role]={'observed':len(values),'expected':2,'ranges':ranges,'selected':[v['selected'] for v in values]}
    for row in rows:
        if row['kind']=='baseline':continue
        baseline=baselines[row['role']];valid=row['status']=='valid' and len(baseline)==2
        alteration=row['role']=='choice' and not row['kind'].startswith('single-')
        control=next((r for r in rows if r['kind']=='single-choice'),None) if alteration else None
        valid=valid and (not alteration or control is not None and control['status']=='valid')
        excess=None;selected=[b['selected'] for b in baseline]
        if valid:
            if alteration:
                selected=[control['selected']]
                excess=max(max(Decimal(0),abs(_number(p)-_number(control['probabilities'][k]))-_number(repeats['choice']['ranges'][k])) for k,p in row['probabilities'].items())
            else:
                excess=max(max(Decimal(0),min(_number(v['probabilities'][k]) for v in baseline)-_number(p),
                    _number(p)-max(_number(v['probabilities'][k]) for v in baseline)) for k,p in row['probabilities'].items())
        status='not_evaluated' if not valid else ('review_required' if excess>tolerance or row['selected'] not in selected else 'within_declared_tolerance')
        checks.append({'id':row['job_id']+':'+row['role'],'kind':'separate_vs_bundled' if row['kind'].startswith('single-') else 'mapped_invariance',
            'roles':[row['role']],'status':status,'excess_over_repeat_envelope':None if excess is None else _decimal_string(excess),
            'observed_selected':row['selected'],'baseline_selected':selected,
            'comparison_context':'single_choice_control' if alteration else 'bundled_baselines',
            'control_job_id':None if control is None else control['job_id'],'repeat_source':'bundled_baselines'})
    def pair(kind,left,right,values):
        a=values.get(left);b=values.get(right);valid=a is not None and b is not None and a['status']==b['status']=='valid' and len(baselines[left])==len(baselines[right])==2
        residual=None;status='not_evaluated';ref_origins=[]
        if valid:
            p=_number(a['probabilities']['true']);q=_number(b['probabilities']['true'])
            if kind=='changed_meaning':
                refs=[data['references'].get(r) for r in (left,right)]
                if all(r is not None and r['origin'] in ('synthetic','independent') and r['outcome'] in ('true','false') for r in refs) and refs[0]['outcome']!=refs[1]['outcome']:
                    ref_origins=[r['origin'] for r in refs]
                    status='matches_declared_control' if [a['selected'],b['selected']]==[r['outcome'] for r in refs] else 'review_required'
            else:
                residual=abs(p-q) if kind=='equivalent' else abs(p+q-1)
                spread=max((_number(v) for r in (left,right) for v in repeats[r]['ranges'].values()),default=Decimal(0))
                status='review_required' if residual>tolerance+spread else 'within_declared_tolerance'
        checks.append({'id':kind+':'+left+':'+right+':'+(a['job_id'] if a is not None else 'missing'),'kind':kind,'roles':[left,right],
            'status':status,'residual':None if residual is None else _decimal_string(residual),'reference_origins':ref_origins})
    for kind in ('baseline','single'):
        groups=[{r:next((x for x in rows if x['role']==r and x['job_id']==j['id']),None) for r in ROLES} for j in data['jobs'] if j['kind']=='baseline'] if kind=='baseline' else [{r:next((x for x in rows if x['role']==r and x['kind']=='single-'+r),None) for r in ROLES}]
        for values in groups:
            pair('changed_meaning','topic','matter',values);pair('changed_meaning','recurring_matter','occurrence',values)
            pair('equivalent','matter','equivalent',values);pair('complement','matter','complement',values)
    for choice in [x for x in rows if x['role']=='choice' and x['kind']=='baseline']:
        noul=next(x for x in rows if x['job_id']==choice['job_id'] and x['role']=='matter')
        valid=choice['status']==noul['status']=='valid' and len(baselines['choice'])==len(baselines['matter'])==2;delta=None if not valid else abs(_number(choice['probabilities'][data['positive_choice']])-_number(noul['probabilities']['true']))
        spread=None if not valid else max(_number(repeats['choice']['ranges'][data['positive_choice']]),_number(repeats['matter']['ranges']['true']))
        checks.append({'id':'cross-primitive:'+choice['job_id'],'kind':'cross_primitive','roles':['choice','matter'],
            'status':'not_evaluated' if delta is None else ('review_required' if delta>tolerance+spread else 'within_declared_tolerance'),
            'residual':None if delta is None else _decimal_string(delta),'repeat_spread':None if spread is None else _decimal_string(spread)})
    affected={}
    for check in checks:
        for role in check['roles']:
            family=canonical_digest(data['specifications'][role],'matter.sensitivity-family.v1')
            item=affected.setdefault(family,{'family':data['families'][role],'source':data['specifications'][role],'executed_specifications':[], 'checks':[],'qualification_impact':'no_incompatibility_observed'})
            item['checks'].append(check['id'])
            if check['status']=='review_required':item['qualification_impact']='review_required'
            elif check['status']=='not_evaluated' and item['qualification_impact']!='review_required':item['qualification_impact']='incomplete'
    for row in rows:
        key=canonical_digest(data['specifications'][row['role']],'matter.sensitivity-family.v1')
        if key in affected and row['specification'] not in affected[key]['executed_specifications']:affected[key]['executed_specifications'].append(row['specification'])
    return {'tolerance':data['tolerance'],'tolerance_role':'exploratory_diagnostic_only','repeat_variation':repeats,'checks':checks,'per_family':affected,
        'independent_label_count':sum(r['origin']=='independent' for r in data['references'].values())}
