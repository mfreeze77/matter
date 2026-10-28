"""MAT-039 explicitly selected, bounded TypeSafe shadow trials.

Uses the existing adapter, frozen offline packets and private append-only artifact
files. There is no accepted-state handle, action callback or delivery transport.
Interrupted starts consume reservations and are never silently resubmitted.
"""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from dataclasses import dataclass
import time
from .._rule_values import checked,fragment
from ..canonical import canonical_bytes,canonical_digest
from ..contracts import ContractError
from ..semantic import Batch,execute_batch
from ..semantic.contracts import ExecutionFault
from ..semantic.providers.typesafe import TypeSafeHTTPExecutor,ADAPTER_VERSION
from .artifacts import ArtifactDirectory
from .offline import OfflineReport,validate_jobs


def _now():
    return {'state':'known','value':datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z'),'precision':'microsecond'}


def _datetime(value):
    fragment(value,'known_time');return datetime.fromisoformat(value['value'].replace('Z','+00:00'))


def _fail(reason):raise ContractError('E_EVIDENCE_INVALID',reason)


def _provider_batch(frozen,config,deadline):
    data=frozen.value
    data['context'].update(provider='typesafe',transport='http',adapter_version=ADAPTER_VERSION,mode='provider_shadow',requested_model=config['model'],
        deadline=deadline,max_request_bytes=config['max_request_bytes'],max_response_bytes=config['max_response_bytes'])
    batch=Batch(data)
    if batch.value['state']!=frozen.value['state'] or batch.value['questions']!=frozen.value['questions']:_fail('provider_changed_frozen_meaning')
    return batch


def _limits(config,count):
    def unrun(reason):return {'status':'not_run','reason':reason,'attempts':0,'consequential_use':False}
    for key,minimum,maximum in [('max_calls',1,64),('timeout_seconds',1,120),('wall_seconds',1,3600),
        ('trials_per_case',1,3),('max_request_bytes',1,65536),('max_response_bytes',1,65536)]:
        if type(config[key]) is not int or not minimum<=config[key]<=maximum:return unrun('invalid_'+key)
    if count>config['max_calls']:return unrun('call_limit_below_schedule')
    price=config['price_basis'];checked(price,required={'model','source','checked_at','input_usd_per_million','output_usd_per_million','max_input_tokens_per_call'})
    fragment(price['checked_at'],'known_time')
    if (price['model']!=config['model'] or price['source']!='https://docs.typesafe.ai/models' or
        type(price['max_input_tokens_per_call']) is not int or price['max_input_tokens_per_call']<65536 or
        Decimal(price['input_usd_per_million'])<=0 or Decimal(price['output_usd_per_million'])!=0):return unrun('unsupported_or_unbounded_price_basis')
    maximum=Decimal(config['max_cost_usd']);reserve=Decimal(price['input_usd_per_million'])*price['max_input_tokens_per_call']/Decimal(1000000)
    if not maximum.is_finite() or not reserve.is_finite() or maximum<=0 or reserve*count>maximum:return unrun('cost_limit_below_worst_case_schedule')
    return {'status':'ready','reason':None,'attempts':0,'scheduled':count,
        'reserve_usd_per_attempt':str(reserve),'max_cost_usd':str(maximum),'concurrency':1,'retries':0,'consequential_use':False}


def provider_preflight(*,config,corpus,split,candidate,jobs,offline,credential,output):
    """No adapter execution, artifact writes, credential lookup or network calls."""
    def unrun(reason):return {'status':'not_run','reason':reason,'attempts':0,'consequential_use':False}
    if type(config) is not dict or config.get('mode')!='provider_shadow':return unrun('provider_not_selected')
    try:
        checked(config,required={'mode','provider','model','scope_id','credential_source','max_calls','timeout_seconds','wall_seconds',
            'max_cost_usd','price_basis','trials_per_case','max_request_bytes','max_response_bytes'})
        if config['provider']!='typesafe':return unrun('unsupported_provider')
        if not isinstance(credential,str) or not credential.strip():return unrun('credential_missing')
        if type(config['model']) is not str or not config['model']:return unrun('model_required')
        if config['scope_id']!=corpus.value['scope_id']:return unrun('scope_mismatch')
        if not config['credential_source'] or not output:return unrun('explicit_credential_source_and_destination_required')
        if any(s['artifact']['kind']!='synthetic' for e in corpus.value['episodes'] for s in e['sources']):
            return unrun('private_evidence_requires_existing_access_egress_dispatcher')
        split.report(corpus=corpus)
        if not isinstance(offline,OfflineReport) or not offline.value['passed']:return unrun('offline_conformance_not_passed')
        expected_episodes={(a,e['id']) for a in ('A','B') for e in corpus.value['episodes']}
        replayed=[(e['arm'],e['episode_id']) for e in offline.value['episodes']]
        if set(replayed)!=expected_episodes or len(replayed)!=len(expected_episodes):return unrun('offline_episode_coverage_incomplete')
        if offline.value['corpus_digest']!=corpus.sha256 or offline.value['split_digest']!=split.digest or candidate.value['kind']!='B' or len(offline.value['arms'])!=2 or offline.value['arms'][1]!=candidate.digest:
            return unrun('offline_inputs_mismatch')
        limits=_limits(config,0)
        if limits['status']!='ready':return limits
        prepared=validate_jobs(jobs,corpus=corpus,arm=candidate)
        if len(prepared)*config['trials_per_case']>config['max_calls']:return unrun('call_limit_below_schedule')
        if offline.value['scheduled_manifest_digest']!=canonical_digest([j for j,_ in prepared],'matter.offline-schedule.v1'):return unrun('offline_schedule_mismatch')
        limits=_limits(config,len(prepared)*config['trials_per_case'])
        if limits['status']!='ready':return limits
        # Validate supported adapter configuration without constructing a client
        # that could read ambient credentials. Constructor performs no requests.
        adapter=TypeSafeHTTPExecutor(model=config['model'],api_key=credential,timeout=config['timeout_seconds'],max_calls=config['max_calls'],max_retries=0,
            max_request_bytes=config['max_request_bytes'],max_response_bytes=config['max_response_bytes'])
        for _,frozen in prepared:
            batch=_provider_batch(frozen,config,{'state':'known','value':'2099-01-01T00:00:00.000000Z','precision':'microsecond'})
            if len(batch.canonical)>config['max_request_bytes'] or any(q['primitive'] not in adapter.capabilities.value['primitives'] for q in batch.value['questions']):return unrun('provider_request_unsupported_or_oversize')
            try:adapter._request(batch) # existing pure wire renderer, zero dispatch
            except ExecutionFault:return unrun('provider_request_unsupported_or_oversize')
        return {'status':'ready','reason':None,'attempts':0,'scheduled':len(prepared)*config['trials_per_case'],
            'reserve_usd_per_attempt':limits['reserve_usd_per_attempt'],'max_cost_usd':limits['max_cost_usd'],'concurrency':1,'retries':0,'consequential_use':False}
    except (ValueError,TypeError,KeyError,ArithmeticError):return unrun('invalid_provider_configuration')


def run_provider(*,config,corpus,split,candidate,jobs,offline,credential,output,live=False,resume=False,http=None,clock=_now,after_start=None):
    preflight=provider_preflight(config=config,corpus=corpus,split=split,candidate=candidate,jobs=jobs,offline=offline,credential=credential,output=output)
    if preflight['status']!='ready':return preflight
    if live is not True:return {**preflight,'status':'not_run','reason':'live_mode_not_selected'}
    prepared=validate_jobs(jobs,corpus=corpus,arm=candidate)
    # Source/meaning and arm hashes are stable. Only execution-instance deadline
    # metadata changes when dispatching a fresh trial.
    identity={'config':config,'corpus_digest':corpus.sha256,'split_digest':split.digest,'candidate':candidate.value,
        'offline_digest':offline.digest,'jobs':[j for j,_ in prepared]}
    return _run_prepared(config=config,prepared=prepared,identity=identity,preflight=preflight,credential=credential,
        output=output,resume=resume,http=http,clock=clock,after_start=after_start)


def _run_prepared(*,config,prepared,identity,preflight,credential,output,resume,http,clock,after_start,guards=None):
    artifacts=ArtifactDirectory(output,resume=resume)
    if resume:
        manifest=artifacts.read('manifest.json')
        if manifest['identity']!=identity:_fail('resume_configuration_mismatch')
    else:
        start=clock();deadline=_datetime(start)+timedelta(seconds=config['wall_seconds'])
        manifest={'identity':identity,'created_at':start,'wall_deadline':deadline.isoformat(),'mode':'provider_shadow'}
        artifacts.write('manifest.json',manifest)
    wall_deadline=datetime.fromisoformat(manifest['wall_deadline'])
    kwargs={} if http is None else {'transport':http}
    executor=TypeSafeHTTPExecutor(model=config['model'],api_key=credential,timeout=config['timeout_seconds'],max_calls=config['max_calls'],max_retries=0,
        max_request_bytes=config['max_request_bytes'],max_response_bytes=config['max_response_bytes'],clock=clock,**kwargs)
    observations=[];fresh=0;cached=0;unknown=0;non_dispatched=0;reserved=Decimal('0');started_monotonic=time.monotonic();stop_reason=None
    schedule=[(job,batch,trial) for job,batch in prepared for trial in range(config['trials_per_case'])]
    for index,(job,frozen,trial) in enumerate(schedule):
        name=str(index);started_name=name+'-started.json';result_name=name+'-result.json'
        if artifacts.exists(started_name):
            started=artifacts.read(started_name)
            if started['frozen_batch_digest']!=frozen.digest or started['trial']!=trial:_fail('attempt_identity_mismatch')
            reserved+=Decimal(started['reserved_cost_usd'])
            if artifacts.exists(result_name):
                row=artifacts.read(result_name)
                if row['started_digest']!=canonical_digest(started,'matter.provider-start.v1'):_fail('response_start_mismatch')
                kind='cached_replay' if row['transport_attempt_observed'] else 'cached_not_dispatched'
                observations.append({**row,'observation_kind':kind})
                if row['transport_attempt_observed']:cached+=1
                else:non_dispatched+=1
                prior=row['result'];prior_usage=prior['usage']['value'];prior_tokens=None if prior_usage is None else prior_usage.get('input_tokens')
                if prior['resolved_model'] is not None and prior['resolved_model']!=config['model']:
                    stop_reason='resolved_model_differs_from_price_binding';break
                if prior_tokens is not None and prior_tokens>config['price_basis']['max_input_tokens_per_call']:
                    stop_reason='observed_usage_exceeds_reserved_bound';break
            else:
                observations.append({'index':index,'job_id':job['id'],'trial':trial,'status':'outcome_unknown',
                    'observation_kind':'incomplete_attempt','reason':'started_without_terminal_receipt'})
                unknown+=1
            continue
        now=clock();remaining=(wall_deadline-_datetime(now)).total_seconds()
        if remaining<config['timeout_seconds'] or time.monotonic()-started_monotonic>=config['wall_seconds']:
            stop_reason='wall_limit';break
        reserve=Decimal(preflight['reserve_usd_per_attempt'])
        if reserved+reserve>Decimal(config['max_cost_usd']):stop_reason='cost_limit';break
        if fresh+cached+unknown+non_dispatched>=config['max_calls']:stop_reason='call_limit';break
        batch=_provider_batch(frozen,config,{'state':'known','value':(_datetime(now)+timedelta(seconds=config['timeout_seconds'])).isoformat(timespec='microseconds').replace('+00:00','Z'),'precision':'microsecond'})
        started={'index':index,'job_id':job['id'],'trial':trial,'frozen_batch_digest':frozen.digest,'batch':batch.value,
            'started_at':now,'reserved_cost_usd':str(reserve),'status':'started'}
        artifacts.write(started_name,started);reserved+=reserve
        if after_start is not None:after_start(index) # test interruption before any transport
        before=executor.calls_made
        if guards is None:
            result=execute_batch(executor,batch,clock=clock)
        else:
            case=guards[job['id']]
            result=case.access.dispatch(case.view,case.context,batch,executor,
                rendered_questions=case.rendered_questions,clock=clock)
        dispatched=executor.calls_made>before
        if dispatched:fresh+=1
        else:non_dispatched+=1
        value=result.value;usage=value['usage']['value'];tokens=None if usage is None else usage.get('input_tokens')
        estimated=None if tokens is None else str(Decimal(tokens)*Decimal(config['price_basis']['input_usd_per_million'])/Decimal(1000000))
        row={'index':index,'job_id':job['id'],'trial':trial,'status':value['execution_status'],'primitive_valid':result.primitive_valid,
            'frozen_batch_digest':frozen.digest,'started_digest':canonical_digest(started,'matter.provider-start.v1'),
            'result':value,'estimated_input_cost_usd':estimated,'billing_cost':'not_observed','reserved_cost_usd':str(reserve),
            'observation_kind':'fresh_provider_attempt' if dispatched else 'not_dispatched',
            'transport_attempt_observed':dispatched,'independence_unit':'episode_provenance_group',
            'qualification':'unknown','consequential_use':False}
        if credential.encode() in canonical_bytes(row):_fail('credential_echo_withheld')
        artifacts.write(result_name,row);observations.append(row)
        if value['resolved_model'] is not None and value['resolved_model']!=config['model']:
            stop_reason='resolved_model_differs_from_price_binding';break
        if tokens is not None and tokens>config['price_basis']['max_input_tokens_per_call']:
            stop_reason='observed_usage_exceeds_reserved_bound';break
    report={'schema_version':'1.0','mode':'provider_shadow','status':'completed' if len(observations)==len(schedule) and not unknown and not non_dispatched and stop_reason is None else 'incomplete',
        'corpus_digest':identity.get('corpus_digest'),'split_digest':identity.get('split_digest'),
        'candidate_digest':None if 'candidate' not in identity else canonical_digest(identity['candidate'],'matter.arm-manifest.v1'),'offline_digest':identity.get('offline_digest'),
        'scheduled':len(schedule),'fresh_attempts':fresh,'cached_replays':cached,'incomplete_attempts':unknown,'non_dispatched':non_dispatched,'not_attempted':len(schedule)-len(observations),
        'reserved_cost_usd':str(reserved),'billing_cost':'not_observed','stop_reason':stop_reason,'observations':observations,
        'qualification':'unknown','host_mutations':0,'real_deliveries':0,'consequential_use':False}
    artifact=artifacts.write('report-'+str(time.monotonic_ns())+'.json',report)
    return {**report,'artifact':artifact}


@dataclass(frozen=True)
class GuardedProviderCase:
    """Trusted host bindings; no alternative permission callback or executor."""
    id: str
    batch: Batch
    access: object
    context: object
    view: object
    rendered_questions: tuple
    expectations: dict


def run_guarded_diagnostic(*,config,cases,credential,output,provenance,live=False,resume=False,http=None,clock=_now,after_start=None):
    """Exploratory real-evidence calls through MAT-072, sharing runner receipts.

    This is deliberately separate from paired offline/provider evaluation: no
    fabricated OfflineReport, label accuracy, admission or qualification claim.
    All protected work requires actual detached inputs and fresh host reads.
    An access failure after a durable start leaves an incomplete attempt; resume
    never automatically resends it, including when a response was withheld.
    """
    from ..access import AccessService,AccessContext
    from ..assessments import FrozenAssessmentView
    from ..semantic.rendering import RenderedQuestion
    def unrun(reason):return {'status':'not_run','reason':reason,'attempts':0,'consequential_use':False}
    if type(config) is not dict or config.get('mode')!='provider_shadow':return unrun('provider_not_selected')
    try:
        checked(config,required={'mode','provider','model','scope_id','credential_source','max_calls','timeout_seconds','wall_seconds',
            'max_cost_usd','price_basis','trials_per_case','max_request_bytes','max_response_bytes'})
        if config['provider']!='typesafe':return unrun('unsupported_provider')
        if not isinstance(credential,str) or not credential.strip():return unrun('credential_missing')
        if not config['model'] or not config['credential_source'] or not output:return unrun('explicit_model_credential_source_and_destination_required')
        if type(cases) not in (list,tuple) or not 1<=len(cases)<=64:return unrun('invalid_guarded_schedule')
        limits=_limits(config,0)
        if limits['status']!='ready':return limits
        limits=_limits(config,len(cases)*config['trials_per_case'])
        if limits['status']!='ready':return limits
        adapter=TypeSafeHTTPExecutor(model=config['model'],api_key=credential,timeout=config['timeout_seconds'],max_calls=config['max_calls'],max_retries=0,
            max_request_bytes=config['max_request_bytes'],max_response_bytes=config['max_response_bytes'])
        prepared=[];guards={}
        for case in cases:
            if (not isinstance(case,GuardedProviderCase) or not isinstance(case.id,str) or not case.id or case.id in guards or
                not isinstance(case.access,AccessService) or not isinstance(case.context,AccessContext) or
                not isinstance(case.view,FrozenAssessmentView) or not isinstance(case.batch,Batch) or
                not case.rendered_questions or any(not isinstance(q,RenderedQuestion) for q in case.rendered_questions)):
                return unrun('invalid_guarded_bindings')
            batch=_provider_batch(case.batch,config,{'state':'known','value':'2099-01-01T00:00:00.000000Z','precision':'microsecond'})
            context=case.context
            if (batch.value['scope_id']!=config['scope_id'] or case.access.scope_id!=config['scope_id'] or
                context.value['token']['capability']!='assessment' or
                [q.question.value for q in case.rendered_questions]!=batch.value['questions'] or
                any(q.manifest.get('access_context')!=context.reference for q in case.rendered_questions)):
                return unrun('guarded_packet_mismatch')
            selected=next((p for p in case.access.policy.value['providers'] if p['reference']==context.value['provider']),None)
            if selected is None or selected['provider']!='typesafe' or selected['transport']!='http':return unrun('provider_access_mismatch')
            try:case.access.require_packet(case.view,context,batch.value['state'],_fresh=True)
            except ContractError:return unrun('access_or_packet_refused')
            if len(batch.canonical)>config['max_request_bytes']:return unrun('provider_request_unsupported_or_oversize')
            try:adapter._request(batch)
            except ExecutionFault:return unrun('provider_request_unsupported_or_oversize')
            job={'id':case.id,'expectations':case.expectations,'access_context':context.value,
                'rendered_manifests':[q.manifest for q in case.rendered_questions]}
            prepared.append((deepcopy(job),case.batch));guards[case.id]=case
        identity={'purpose':'exploratory_access_guarded','config':config,'provenance':provenance,
            'jobs':[j for j,_ in prepared]}
        # Reject noncanonical or oversized private audit declarations before writes.
        if len(canonical_bytes(identity))>1048576:return unrun('guarded_manifest_limit')
        if credential.encode() in canonical_bytes(identity):return unrun('credential_echo_withheld')
    except (ValueError,TypeError,KeyError,ArithmeticError):return unrun('invalid_provider_configuration')
    if live is not True:return {**limits,'status':'not_run','reason':'live_mode_not_selected'}
    return _run_prepared(config=config,prepared=prepared,identity=identity,preflight=limits,credential=credential,
        output=output,resume=resume,http=http,clock=clock,after_start=after_start,guards=guards)
