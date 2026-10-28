"""MAT-022 optional, bounded host read proposals over existing controls/budgets.

No connector, model, retry scheduler, human question or external-write client is
constructed. Host readers ingest their result through ObservationIngestor and
return exact observation pins. Evidence acquisition is not claim truth.
"""
from copy import deepcopy
import time

from ._rule_values import FrozenValue, domain
from .budgets import BudgetService, _lookup, _value
from .canonical import canonical_bytes, canonical_digest, source_digest
from .contexts import _MutationService, _control_command, _namespace
from .contracts import ContractError, validate_record
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times, knowledge_eligible, known_time_key

MAX_OBSERVATIONS=128

def _fail(code='E_EVIDENCE_INVALID'):
    raise StorageError(code,'The bounded investigation or its original host context is invalid.')


def gap_ref(scope_id,definition):
    value=definition.value if isinstance(definition,InvestigationDefinition) else definition
    return {'scope_id':scope_id,'namespace':value['namespace'],'record_type':PROJECTION_TYPE,
        'id':'gap-'+canonical_digest({'id':value['id']},'matter.investigation-slot.v1')}


def _allocation_ref(scope_id,allocation):
    return {'scope_id':scope_id,'namespace':'matter.investigation','record_type':PROJECTION_TYPE,
        'id':'allocation-'+canonical_digest(allocation,'matter.investigation-allocation.v1')}


class InvestigationDefinition(FrozenValue):
    def __init__(self,value):
        if len(canonical_bytes(value))>262144:_fail('E_BUDGET_EXHAUSTED')
        value=domain('investigation-definition',value)['value'];_namespace(value['namespace'])
        requirements=[r['id'] for r in value['requirements']]
        if not requirements or len(set(requirements))!=len(requirements):_fail('E_POLICY_INVALID')
        candidates=[canonical_bytes(c['reference']) for c in value['candidates']]
        if len(set(candidates))!=len(candidates):_fail('E_POLICY_INVALID')
        for candidate in value['candidates']:
            if not candidate['requirements'] or not set(candidate['requirements'])<=set(requirements):_fail('E_POLICY_INVALID')
        if any(x['scope_id']!=value['matter']['scope_id'] for x in value['inputs']):_fail('E_SCOPE_FORBIDDEN')
        points=value['retry_at']
        if any(compare_times(a,b)!=-1 for a,b in zip(points,points[1:])):_fail('E_POLICY_INVALID')
        self._freeze(value)

    def work_key(self,at):
        value=self.value
        due=[t for t in value['retry_at'] if compare_times(t,at)<=0]
        # Budget/token renewal, a cosmetic version and speculation about gain do
        # not independently authorize another investigation of unchanged input.
        material={k:value[k] for k in ('matter','proposition','inputs','requirements','candidates')}
        material['retry_boundary']=max(due,key=known_time_key) if due else None
        return canonical_digest(material,'matter.investigation-work.v1')


class InvestigationService(_MutationService):
    mutation_schema='investigation-mutation'

    def __init__(self,storage,*,controls,budgets,payloads,candidates,clock,access=None):
        super().__init__(storage,controls=controls)
        if not isinstance(budgets,BudgetService) or budgets.storage is not storage or budgets.controls is not controls or not callable(clock):_fail('E_POLICY_INVALID')
        if payloads.scope_id!=storage.scope_id or not callable(payloads.read):_fail('E_SCOPE_FORBIDDEN')
        self.budgets,self.payloads,self.clock,self.access=budgets,payloads,clock,access
        # Exact host-installed read declarations; a nomination cannot add a URI,
        # source namespace or requirement to an admitted read's meaning.
        self.candidates={canonical_bytes(c['reference']):deepcopy(c) for c in candidates}
        if len(self.candidates)!=len(candidates) or len(candidates)>128:_fail('E_POLICY_INVALID')

    def _body(self,view,reference):
        row=view.get(reference)
        value=_value(row,'investigation-state')
        if entity_ref(row)!=gap_ref(self.scope_id,value['definition']):_fail()
        return row,value

    def _targets(self,definition,observations=()):
        refs=[entity_ref(definition['matter']),*[entity_ref(r) for r in definition['inputs']],*[entity_ref(r) for r in observations]]
        return sorted({canonical_bytes(r):r for r in refs}.values(),key=canonical_bytes)

    def _read_targets(self,view,payload):
        targets=[gap_ref(self.scope_id,payload['definition']),*self._targets(payload['definition'],payload['observations'])]
        if payload['previous'] is not None:
            _,old=self._body(view,payload['previous']);targets.extend(self._targets(old['definition'],old['observations']))
        return list({canonical_bytes(r):r for r in targets}.values())

    def _guard(self,view,value,*,references=()):
        definition=value['definition'];targets=self._targets(definition)
        self.controls.require_current(view,value['token'],capability='assessment',targets=targets)
        for ref in [definition['matter'],*definition['inputs']]:
            if pin(view.get(entity_ref(ref)))!=ref:_fail('E_DEPENDENCY_STALE')
        if self.access is not None:
            self.access.require_current(view,value['access_context'],references=[definition['matter'],*definition['inputs'],*references])
        elif value['access_context'] is not None:_fail('E_AUTHORITY_REQUIRED')

    def prepare(self,definition,*,token,command_id,idempotency_key,previous=None,action='nominate',
                allocation=None,candidate=None,observations=(),stop_reason=None,access_context=None):
        if not isinstance(definition,InvestigationDefinition):_fail('E_POLICY_INVALID')
        token=domain('control-token',token)['value']
        if hasattr(access_context,'value'):access_context=access_context.value
        payload={'definition':definition.value,'previous':previous,'action':action,'token':token,
            'allocation':allocation,'candidate':candidate,'observations':list(observations),'stop_reason':stop_reason,'access_context':access_context}
        return self._prepare(_control_command(self.controls,payload=payload,schema=self.mutation_schema,
            target=gap_ref(self.scope_id,definition),command_id=command_id,idempotency_key=idempotency_key,
            actor=token['actor'],authority=entity_ref(token['authority']),kind='decision'))

    def _state(self,view,command,payload,*,preparing):
        definition=InvestigationDefinition(payload['definition']);data=definition.value;address=gap_ref(self.scope_id,definition)
        if command['body']['control']['body']['control_kind']!='decision':_fail('E_AUTHORITY_REQUIRED')
        if data['matter']['scope_id']!=self.scope_id or command['body']['control']['body']['scope']['targets']!=[address]:_fail('E_SCOPE_FORBIDDEN')
        if payload['token']['actor']!=command['actor'] or entity_ref(payload['token']['authority'])!=command['authority']:_fail('E_AUTHORITY_REQUIRED')
        old,old_control=self._prior(view,command,payload,address,'investigation-state',preparing=preparing)
        prior=None if old is None else _value(old,'investigation-state')
        targets=self._read_targets(view,payload)
        if payload['action']=='nominate':
            if payload['candidate'] is not None or payload['allocation'] is not None or payload['observations'] or payload['stop_reason'] is not None:_fail()
            self._guard(view,payload)
            key=definition.work_key(self.clock())
            if prior is not None and prior['phase']=='started':_fail('E_DELIVERY_UNKNOWN')
            if prior is not None and key==prior['key']:
                value=deepcopy(prior) # unchanged gaps do not reset on renewed quota
            else:
                value={'definition':data,'key':key,'token':payload['token'],'access_context':payload['access_context'],
                    'phase':'ready' if data['candidates'] else 'stopped','stop_reason':None if data['candidates'] else 'no_eligible_source',
                    'fulfilled':[],'observations':[],'attempted':[],'allocation':None,'candidate':None,'control':None}
        else:
            if prior is None or prior['definition']!=data or prior['token']!=payload['token'] or prior['access_context']!=payload['access_context']:_fail('E_DEPENDENCY_STALE')
            value=deepcopy(prior)
            if payload['action']=='start':
                self._guard(view,payload)
                selected=next((c for c in data['candidates'] if c['reference']==payload['candidate']),None)
                if prior['phase']!='ready' or selected is None or selected['reference'] in prior['attempted']:_fail('E_IDEMPOTENCY_CONFLICT')
                if self.candidates.get(canonical_bytes(selected['reference']))!=selected:_fail('E_AUTHORITY_REQUIRED')
                allocated=self.budgets.require_committed(view,payload['allocation'])
                if allocated['token']['value']!=payload['token'] or entity_ref(data['matter']) not in allocated['targets']:_fail('E_AUTHORITY_REQUIRED')
                amounts=allocated['amounts']
                if (amounts.get('calls',0)<1 or amounts.get('output_bytes',0)<selected['max_bytes'] or amounts.get('elapsed_ms',0)<selected['timeout_ms']):_fail('E_BUDGET_EXHAUSTED')
                if _lookup(view,_allocation_ref(self.scope_id,payload['allocation'])) is not None:_fail('E_IDEMPOTENCY_CONFLICT')
                value.update(phase='started',candidate=selected['reference'],allocation=payload['allocation'],stop_reason=None)
                value['attempted'].append(selected['reference'])
            elif payload['action']=='stop':
                if prior['phase']!='ready' or payload['observations'] or payload['stop_reason'] in {None,'evidence_satisfied'}:_fail()
                value.update(phase='stopped',stop_reason=payload['stop_reason'])
            elif payload['action']=='finish':
                if prior['phase']!='started' or payload['candidate']!=prior['candidate'] or payload['allocation']!=prior['allocation']:_fail('E_DEPENDENCY_STALE')
                reason=payload['stop_reason']
                try:
                    self._guard(view,payload,references=payload['observations']);self.budgets.require_committed(view,prior['allocation'])
                except ContractError as error:
                    if payload['observations'] or reason not in {'cancelled','budget_exhausted','source_unavailable'}:raise
                    expected='cancelled' if error.code in {'E_CANCELLED','E_DEPENDENCY_STALE'} else ('budget_exhausted' if error.code=='E_BUDGET_EXHAUSTED' else 'source_unavailable')
                    if reason!=expected:_fail()
                selected=next(c for c in data['candidates'] if c['reference']==prior['candidate'])
                if payload['observations']:
                    if reason is not None and reason!='conflict_persists':_fail()
                    merged=prior['observations']+[r for r in payload['observations'] if r not in prior['observations']]
                    if len(merged)>MAX_OBSERVATIONS:_fail('E_BUDGET_EXHAUSTED')
                    total_bytes=0
                    for ref in payload['observations']:
                        record=validate_record(view.get(ref));body=record['body']
                        self.controls._audit(view,command,[entity_ref(ref)])
                        self.controls._view(view,actor=command['actor'],authority=command['authority'],capability='assessment',targets=[entity_ref(ref)],now=self.clock())
                        total_bytes+=body['content']['byte_length']
                        if total_bytes>selected['max_bytes']:_fail('E_BUDGET_EXHAUSTED')
                        if (ref['scope_id']!=self.scope_id or body['source_identity']['namespace']!=selected['source_namespace'] or
                            body['content']['locator']['uri']!=selected['uri'] or body['content']['byte_length']>selected['max_bytes'] or
                            knowledge_eligible(body['available_at'],self.clock()) is not True):_fail('E_EVIDENCE_INVALID')
                        source_payload=self.payloads.read(body['content'])
                        if (source_payload.status!='available' or type(source_payload.data) is not bytes or len(source_payload.data)!=body['content']['byte_length'] or
                            source_digest(source_payload.data)!=body['content']['digest']):_fail('E_EVIDENCE_UNAVAILABLE')
                    value['observations'].extend(r for r in payload['observations'] if r not in value['observations'])
                    value['fulfilled']=sorted(set(value['fulfilled'])|set(selected['requirements']))
                missing=set(r['id'] for r in data['requirements'])-set(value['fulfilled'])
                if reason=='evidence_satisfied' and missing:_fail()
                remaining=[c for c in data['candidates'] if c['reference'] not in value['attempted']]
                terminal=None if reason=='source_unavailable' and remaining else reason
                stop=terminal or ('evidence_satisfied' if not missing else ('no_eligible_source' if not remaining else None))
                value.update(phase='ready' if stop is None else 'stopped',stop_reason=stop)
            else:_fail()
        return {'old':old,'old_control':old_control,'targets':targets,'value':value}

    def _write(self,tx,payload,state,control):
        value=state['value'];value['control']=control
        tx.put_projection(gap_ref(self.scope_id,value['definition']),domain('investigation-state',value))
        if payload['action']=='start':
            tx.put_projection(_allocation_ref(self.scope_id,payload['allocation']),domain('investigation-allocation',
                {'gap':gap_ref(self.scope_id,value['definition']),'allocation':payload['allocation'],'control':control}))

    def inspect(self,reference,*,actor,authority):
        with self.storage.snapshot() as view:
            _,value=self._body(view,reference)
            self.controls._audit(view,{'actor':actor,'authority':authority},[entity_ref(reference),*self._targets(value['definition'],value['observations'])])
            if self.access is not None:
                self.access.require_history(view,value['access_context'],references=[value['definition']['matter'],*value['definition']['inputs'],*value['observations']])
            return {**value,'human_question':False,'satisfied':value['stop_reason']=='evidence_satisfied'}

    def execute_read(self,definition,*,previous,token,candidate,allocation,reader,command_id,idempotency_key,access_context=None):
        """Claim before host I/O. Exact replay never invokes the injected reader.

        The trusted host reader enforces its transport timeout/byte limit,
        ingests through the existing ObservationIngestor and returns source pins.
        This synchronous seam cannot preempt an arbitrary Python callback.
        """
        context=access_context.value if hasattr(access_context,'value') else access_context
        with self.storage.snapshot() as view:
            for suffix in ('','-stop'):
                try:journal=view.command_receipt(idempotency_key+suffix)
                except StorageError as error:
                    if error.code!='E_NOT_FOUND':raise
                    continue
                command,payload=self._payload(journal['command'])
                reason=payload['stop_reason'] if suffix else None
                if suffix and reason not in {'budget_exhausted','cancelled'}:_fail('E_IDEMPOTENCY_CONFLICT')
                expected={'definition':definition.value,'previous':previous,'action':'stop' if suffix else 'start','allocation':allocation,
                    'candidate':candidate,'token':token,'observations':[],'stop_reason':reason,'access_context':context}
                if payload!=expected or command['command_id']!=command_id+suffix:_fail('E_IDEMPOTENCY_CONFLICT')
                self._authorize(view,command,self._read_targets(view,payload))
                if self.access is not None:
                    self.access.require_history(view,context,references=[definition.value['matter'],*definition.value['inputs']])
                return {'stop' if suffix else 'start':journal['result'],'read_invoked':False,'outcome':reason if suffix else 'not_repeated'}
        try:
            prepared=self.prepare(definition,token=token,previous=previous,action='start',allocation=allocation,candidate=candidate,
                command_id=command_id,idempotency_key=idempotency_key,access_context=access_context)
        except ContractError as error:
            if error.code not in {'E_BUDGET_EXHAUSTED','E_CANCELLED','E_DEPENDENCY_STALE'}:raise
            reason='budget_exhausted' if error.code=='E_BUDGET_EXHAUSTED' else 'cancelled'
            stopped=self.prepare(definition,token=token,previous=previous,action='stop',allocation=allocation,candidate=candidate,
                command_id=command_id+'-stop',idempotency_key=idempotency_key+'-stop',stop_reason=reason,access_context=access_context)
            return {'stop':self.commit(stopped),'read_invoked':False,'outcome':reason}
        claimed=[]
        def handler(tx):
            result=self._commit(tx);claimed.append(True);return result
        def replay(view):self._authorize(view,prepared,self._read_targets(view,self._payload(prepared)[1]))
        result=self.storage.execute(prepared,handler,replay_guard=replay)
        if result['status']!='success' or not claimed:return {'start':result,'read_invoked':False,'outcome':'not_repeated'}
        address=gap_ref(self.scope_id,definition)
        invoked=False
        value={'definition':definition.value,'token':token,'access_context':context}
        try:
            with self.storage.snapshot() as view:
                row,value=self._body(view,address);self._guard(view,value);self.budgets.require_committed(view,allocation)
            selected=next(c for c in definition.value['candidates'] if c['reference']==candidate)
            invoked=True;began=time.monotonic()
            observations=reader(deepcopy(selected))
            if type(observations) not in (list,tuple) or len(observations)>32:_fail('E_BUDGET_EXHAUSTED')
            observations=list(observations)
            reason=None if observations else 'source_unavailable'
            if (time.monotonic()-began)*1000>selected['timeout_ms']:
                observations=[];reason='budget_exhausted'
        except ContractError as error:
            observations=[];reason='cancelled' if error.code in {'E_CANCELLED','E_DEPENDENCY_STALE'} else ('budget_exhausted' if error.code=='E_BUDGET_EXHAUSTED' else 'source_unavailable')
        except Exception:
            observations=[];reason='source_unavailable'
        # A transport exception must not skip the cancellation/budget recheck.
        # Current host state determines the terminal reason even when no bytes
        # returned, rather than stranding an already claimed read as unknown.
        try:
            with self.storage.snapshot() as view:
                self._guard(view,value,references=observations);self.budgets.require_committed(view,allocation)
        except ContractError as error:
            observations=[];reason='cancelled' if error.code in {'E_CANCELLED','E_DEPENDENCY_STALE'} else ('budget_exhausted' if error.code=='E_BUDGET_EXHAUSTED' else 'source_unavailable')
        with self.storage.snapshot() as view:row,value=self._body(view,address)
        try:
            finish=self.prepare(definition,token=token,previous=pin(row),action='finish',allocation=allocation,candidate=candidate,
                observations=observations,stop_reason=reason,command_id=command_id+'-finish',idempotency_key=idempotency_key+'-finish',access_context=access_context)
        except ContractError as error:
            if not observations or error.code not in {'E_EVIDENCE_UNAVAILABLE','E_EVIDENCE_INVALID','E_NOT_FOUND','E_SCHEMA_INVALID','E_SCOPE_FORBIDDEN','E_BUDGET_EXHAUSTED','E_CANCELLED','E_DEPENDENCY_STALE','E_AUTHORITY_REQUIRED'}:raise
            reason='budget_exhausted' if error.code=='E_BUDGET_EXHAUSTED' else ('cancelled' if error.code in {'E_CANCELLED','E_DEPENDENCY_STALE'} else 'source_unavailable')
            finish=self.prepare(definition,token=token,previous=pin(row),action='finish',allocation=allocation,candidate=candidate,
                observations=[],stop_reason=reason,command_id=command_id+'-finish',idempotency_key=idempotency_key+'-finish',access_context=access_context)
        completed=self.commit(finish)
        failed_finish=None
        if completed['status']!='success' and completed.get('error',{}).get('code') in {'E_REVISION_CONFLICT','E_DEPENDENCY_STALE','E_CANCELLED','E_BUDGET_EXHAUSTED','E_EVIDENCE_INVALID','E_EVIDENCE_UNAVAILABLE','E_AUTHORITY_REQUIRED'}:
            # One bounded bookkeeping recovery, never another read or a renewed
            # work token. Preserve the failed commit under its original key.
            failed_finish=completed
            prior_finish=self._payload(finish)[1]
            retained=prior_finish['observations'];reason=prior_finish['stop_reason']
            with self.storage.snapshot() as view:
                row,value=self._body(view,address)
                if value['phase']=='started':
                    try:self._guard(view,value,references=retained);self.budgets.require_committed(view,allocation)
                    except ContractError as error:
                        retained=[]
                        reason='cancelled' if error.code in {'E_CANCELLED','E_DEPENDENCY_STALE'} else ('budget_exhausted' if error.code=='E_BUDGET_EXHAUSTED' else 'source_unavailable')
            if value['phase']=='started':
                try:
                    recovery=self.prepare(definition,token=token,previous=pin(row),action='finish',allocation=allocation,candidate=candidate,
                        observations=retained,stop_reason=reason,command_id=command_id+'-finish-recover',idempotency_key=idempotency_key+'-finish-recover',access_context=access_context)
                except ContractError as error:
                    if not retained or error.code not in {'E_EVIDENCE_UNAVAILABLE','E_EVIDENCE_INVALID','E_NOT_FOUND','E_SCHEMA_INVALID','E_SCOPE_FORBIDDEN','E_BUDGET_EXHAUSTED','E_CANCELLED','E_DEPENDENCY_STALE','E_AUTHORITY_REQUIRED'}:raise
                    reason='budget_exhausted' if error.code=='E_BUDGET_EXHAUSTED' else ('cancelled' if error.code in {'E_CANCELLED','E_DEPENDENCY_STALE'} else 'source_unavailable')
                    recovery=self.prepare(definition,token=token,previous=pin(row),action='finish',allocation=allocation,candidate=candidate,
                        observations=[],stop_reason=reason,command_id=command_id+'-finish-recover',idempotency_key=idempotency_key+'-finish-recover',access_context=access_context)
                completed=self.commit(recovery)
        return {'start':result,'finish':completed,'failed_finish':failed_finish,'read_invoked':invoked,
            'outcome':'recorded' if completed['status']=='success' else 'pending_bookkeeping'}
