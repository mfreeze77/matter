"""MAT-022 real control/budget/intake operations, no network or human prompt."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from matter.investigation import InvestigationDefinition,InvestigationService,gap_ref
from matter.budgets import BudgetService
from matter.contracts import ContractError
from matter.storage import pin,entity_ref
from integration import test_timers_and_budgets as fixtures
from observation_helpers import observation_command
from rule_helpers import component,NOW,LATE
from control_helpers import control_command
from integration.helpers import _in_scope


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.TimerBudgetTests('runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.f=self.h.f
        self.source=self.f.observe('investigation-source',payload=b'Synthetic counterevidence.\n')
        self.uri=self.source['body']['content']['locator']['uri']
        self.candidate={'reference':component('approved-counter-read'),'source_namespace':self.source['body']['source_identity']['namespace'],
            'uri':self.uri,'requirements':['counter'],'max_bytes':1024,'timeout_ms':1000}
        self.definition=InvestigationDefinition({'schema_version':'1.0','namespace':'example','id':'funding-gap','version':'1.0',
            'matter':pin(self.f.subject),'proposition':{'schema':component('proposition'),'value':'Is the required counterevidence present?'},
            'inputs':[pin(self.source)],'requirements':[{'id':'counter','description':'Obtain the declared counterevidence source.','counterevidence':True}],
            'candidates':[self.candidate],'retry_at':[],'information_gain_hypothesis':'May fill the named acquisition requirement; not proof the claim is true.'})
        self.service=InvestigationService(self.f.storage,controls=self.f.controls,budgets=self.h.budgets,payloads=self.f.payloads,
            candidates=[self.candidate],clock=lambda:deepcopy(self.f.now))
        self.token=self.f.controls.capture(actor=self.f.actor,authority=entity_ref(self.f.authority),capability='assessment',
            targets=[entity_ref(self.f.subject),entity_ref(self.source)])
        self.serial=0

    def identity(self):self.serial+=1;return 'gap-'+str(self.serial)
    def nominate(self,definition=None,previous=None,token=None,access_context=None):
        definition=definition or self.definition;identity=self.identity()
        command=self.service.prepare(definition,token=token or self.token,command_id=identity,idempotency_key=identity,previous=previous,access_context=access_context)
        result=self.service.commit(command);self.assertEqual(result['status'],'success',result)
        return self.f.storage.get(gap_ref(self.f.storage.scope_id,definition))
    def inspect(self):return self.service.inspect(gap_ref(self.f.storage.scope_id,self.definition),actor=self.f.actor,authority=entity_ref(self.f.authority))
    def allocation(self,identity,amounts=None):
        if amounts is None:held,reserve,result=self.h.reserve(identity,token=self.token)
        else:
            command=self.h.command('reserve_budget',{'budget':self.h.resource.reference,'reservation_id':identity,'amounts':amounts,
                'expires_at':LATE,'targets':[entity_ref(self.f.subject)]})
            reserve=self.h.budgets.prepare(command,token=self.token);result=self.h.budgets.execute(reserve)
            self.assertEqual(result['outcome'],'reserved');held=self.f.storage.get(result['body']['reservation'])
        _,settled=self.h.settle(held,reserve,'commit');self.assertEqual(settled['outcome'],'committed')
        return settled['body']['reservation']
    def run_read(self,previous,allocation,reader=None,identity=None,access_context=None):
        identity=identity or self.identity()
        return self.service.execute_read(self.definition,previous=pin(previous),token=self.token,candidate=self.candidate['reference'],
            allocation=allocation,reader=reader or (lambda c:[pin(self.source)]),command_id=identity,idempotency_key=identity,access_context=access_context)

    def test_real_budget_and_observation_complete_requirement_without_resolving_claim(self):
        gap=self.nominate();allocation=self.allocation('one-read')
        result=self.run_read(gap,allocation)
        self.assertEqual(result['outcome'],'recorded',result)
        state=self.inspect();self.assertEqual(state['stop_reason'],'evidence_satisfied')
        self.assertEqual(state['observations'],[pin(self.source)]);self.assertFalse(state['human_question'])
        self.assertTrue(state['satisfied']);self.assertEqual(state['fulfilled'],['counter'])

    def test_renewed_budget_or_token_cannot_reset_unchanged_gap(self):
        gap=self.nominate();self.run_read(gap,self.allocation('unavailable'),reader=lambda c:[])
        prior=self.f.storage.get(gap_ref(self.f.storage.scope_id,self.definition))
        token=self.f.controls.capture(actor=self.f.actor,authority=entity_ref(self.f.authority),capability='assessment',
            targets=[entity_ref(self.f.subject),entity_ref(self.source)])
        self.nominate(previous=pin(prior),token=token)
        state=self.inspect();self.assertEqual(state['phase'],'stopped');self.assertEqual(state['stop_reason'],'source_unavailable')
        self.assertFalse(state['human_question'])

    def test_unapproved_candidate_never_starts(self):
        value=self.definition.value;value['candidates'][0]['uri']='urn:unapproved:source'
        self.definition=InvestigationDefinition(value);gap=self.nominate();allocation=self.allocation('denied')
        with self.assertRaises(ContractError):self.run_read(gap,allocation,reader=lambda c:self.fail('Denied read executed'))
        self.assertEqual(self.inspect()['phase'],'ready')

    def test_exhausted_or_expired_budget_does_not_satisfy_evidence(self):
        gap=self.nominate();allocation=self.allocation('expires');self.f.now=deepcopy(LATE)
        result=self.run_read(gap,allocation)
        self.assertFalse(result['read_invoked']);self.assertEqual(self.inspect()['stop_reason'],'budget_exhausted')
        self.assertFalse(self.inspect()['satisfied'])

    def test_counterevidence_requirement_cannot_be_displaced_by_agreeing_source(self):
        value=self.definition.value;value['requirements'].append({'id':'support','description':'Separate supporting document.','counterevidence':False})
        value['candidates'][0]['requirements']=['support'];self.definition=InvestigationDefinition(value)
        self.candidate=value['candidates'][0]
        self.service=InvestigationService(self.f.storage,controls=self.f.controls,budgets=self.h.budgets,payloads=self.f.payloads,candidates=[self.candidate],clock=lambda:deepcopy(self.f.now))
        gap=self.nominate();self.run_read(gap,self.allocation('support-only'))
        state=self.inspect();self.assertEqual(state['fulfilled'],['support']);self.assertEqual(state['stop_reason'],'no_eligible_source')
        self.assertFalse(state['satisfied']);self.assertFalse(state['human_question'])

    def test_exact_read_retry_and_restart_do_not_invoke_reader_again(self):
        gap=self.nominate();allocation=self.allocation('retry');calls=[]
        def read(c):calls.append(c);return [pin(self.source)]
        self.run_read(gap,allocation,reader=read,identity='exact-read')
        again=self.run_read(gap,allocation,reader=read,identity='exact-read')
        self.assertFalse(again['read_invoked']);self.assertEqual(len(calls),1)
        self.service=InvestigationService(self.f.storage,controls=self.f.controls,budgets=self.h.budgets,payloads=self.f.payloads,candidates=[self.candidate],clock=lambda:deepcopy(self.f.now))
        again=self.run_read(gap,allocation,reader=read,identity='exact-read')
        self.assertFalse(again['read_invoked']);self.assertEqual(len(calls),1)

    def test_cancellation_during_read_keeps_new_evidence_unresolved(self):
        gap=self.nominate();allocation=self.allocation('cancel')
        def read(c):
            command=_in_scope(control_command('cancel-gap',self.f.authority,targets=[self.f.subject],action='cancel',now=self.f.now),self.f.storage.scope_id)
            command['actor']=self.f.actor;command['body']['control']['body']['actor']=self.f.actor
            self.assertEqual(self.f.controls.apply(self.f.controls.prepare(command))['status'],'success')
            return [pin(self.source)]
        self.run_read(gap,allocation,reader=read)
        state=self.inspect();self.assertEqual(state['stop_reason'],'cancelled');self.assertFalse(state['satisfied'])
        self.assertEqual(state['observations'],[]);self.assertFalse(state['human_question'])

    def test_new_eligible_source_and_declared_time_boundary_can_resume(self):
        gap=self.nominate();self.run_read(gap,self.allocation('stopped'),reader=lambda c:[])
        prior=self.f.storage.get(gap_ref(self.f.storage.scope_id,self.definition))
        value=self.definition.value;value['retry_at']=[deepcopy(NOW)]
        self.definition=InvestigationDefinition(value)
        reopened=self.nominate(previous=pin(prior));self.assertEqual(self.inspect()['phase'],'ready')
        same=self.nominate(previous=pin(reopened));self.assertEqual(pin(same)['revision'],pin(reopened)['revision']+1)
        # The same ready work remains one nomination, not a new attempt.
        self.assertEqual(self.inspect()['attempted'],[])

    def test_a_shared_budget_cannot_be_reminted_for_another_gap(self):
        gap=self.nominate();allocation=self.allocation('shared')
        self.run_read(gap,allocation)
        value=self.definition.value;value['id']='other-gap';other=InvestigationDefinition(value)
        second=self.nominate(other)
        with self.assertRaises(ContractError):
            self.service.execute_read(other,previous=pin(second),token=self.token,candidate=self.candidate['reference'],allocation=allocation,
                reader=lambda c:self.fail('Shared allocation was spent twice'),command_id='second-read',idempotency_key='second-read')

    def test_a_new_eligible_source_can_resume_a_stopped_gap(self):
        gap=self.nominate();self.run_read(gap,self.allocation('missing'),reader=lambda c:[])
        prior=self.f.storage.get(gap_ref(self.f.storage.scope_id,self.definition))
        source=self.f.observe('new-eligible-source',payload=b'Synthetic new eligible counterexample.\n')
        value=self.definition.value;value['inputs']=[pin(source)];new=deepcopy(self.candidate)
        new.update(reference=component('new-read'),uri=source['body']['content']['locator']['uri'])
        value['candidates']=[new];self.definition=InvestigationDefinition(value)
        self.service=InvestigationService(self.f.storage,controls=self.f.controls,budgets=self.h.budgets,payloads=self.f.payloads,candidates=[self.candidate,new],clock=lambda:deepcopy(self.f.now))
        token=self.f.controls.capture(actor=self.f.actor,authority=entity_ref(self.f.authority),capability='assessment',targets=[entity_ref(self.f.subject),entity_ref(source)])
        self.nominate(previous=pin(prior),token=token)
        self.assertEqual(self.inspect()['phase'],'ready');self.assertFalse(self.inspect()['satisfied'])

    def test_acquisition_can_stop_with_downstream_conflict_still_unresolved(self):
        gap=self.nominate();allocation=self.allocation('conflict')
        command=self.service.prepare(self.definition,token=self.token,previous=pin(gap),action='start',allocation=allocation,candidate=self.candidate['reference'],command_id='manual-start',idempotency_key='manual-start')
        self.assertEqual(self.service.commit(command)['status'],'success')
        started=self.f.storage.get(gap_ref(self.f.storage.scope_id,self.definition))
        finish=self.service.prepare(self.definition,token=self.token,previous=pin(started),action='finish',allocation=allocation,candidate=self.candidate['reference'],observations=[pin(self.source)],stop_reason='conflict_persists',command_id='manual-finish',idempotency_key='manual-finish')
        self.assertEqual(self.service.commit(finish)['status'],'success')
        self.assertEqual(self.inspect()['fulfilled'],['counter']);self.assertEqual(self.inspect()['stop_reason'],'conflict_persists')
        self.assertFalse(self.inspect()['satisfied']);self.assertFalse(self.inspect()['human_question'])

    def test_missing_payload_cannot_be_satisfied_from_metadata_alone(self):
        from observation_helpers import UnavailablePayloads
        gap=self.nominate();allocation=self.allocation('missing-bytes');self.service.payloads=UnavailablePayloads(self.f.storage.scope_id)
        self.run_read(gap,allocation)
        self.assertEqual(self.inspect()['stop_reason'],'source_unavailable')
        self.assertFalse(self.inspect()['satisfied'])

    def test_interrupted_read_stays_started_and_is_not_automatically_repeated(self):
        gap=self.nominate();allocation=self.allocation('unknown')
        def interrupt(c):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_read(gap,allocation,reader=interrupt,identity='interrupted-read')
        result=self.run_read(gap,allocation,reader=lambda c:self.fail('An unknown read was repeated'),identity='interrupted-read')
        self.assertFalse(result['read_invoked']);self.assertEqual(self.inspect()['phase'],'started')
        self.assertFalse(self.inspect()['satisfied']);self.assertFalse(self.inspect()['human_question'])

    def test_manual_stop_or_empty_finish_cannot_forge_satisfied_evidence(self):
        gap=self.nominate()
        with self.assertRaises(ContractError):
            self.service.prepare(self.definition,token=self.token,previous=pin(gap),action='stop',stop_reason='evidence_satisfied',command_id='false-stop',idempotency_key='false-stop')
        allocation=self.allocation('manual-empty')
        start=self.service.prepare(self.definition,token=self.token,previous=pin(gap),action='start',allocation=allocation,candidate=self.candidate['reference'],command_id='empty-start',idempotency_key='empty-start')
        self.assertEqual(self.service.commit(start)['status'],'success')
        started=self.f.storage.get(gap_ref(self.f.storage.scope_id,self.definition))
        with self.assertRaises(ContractError):
            self.service.prepare(self.definition,token=self.token,previous=pin(started),action='finish',allocation=allocation,candidate=self.candidate['reference'],observations=[],stop_reason='evidence_satisfied',command_id='false-finish',idempotency_key='false-finish')
        self.assertFalse(self.inspect()['satisfied'])

    def test_accumulation_bound_stops_honestly_instead_of_stranding_started_read(self):
        gap=self.nominate();allocation=self.allocation('bounded-history')
        # Lower the production bound for a small actual source/control episode.
        with patch('matter.investigation.MAX_OBSERVATIONS',0):
            result=self.run_read(gap,allocation)
        self.assertEqual(result['finish']['status'],'success')
        state=self.inspect();self.assertEqual(state['phase'],'stopped')
        self.assertEqual(state['stop_reason'],'budget_exhausted');self.assertFalse(state['satisfied'])

    def test_reader_exception_after_cancellation_records_cancelled_not_unknown(self):
        gap=self.nominate();allocation=self.allocation('raising-cancel')
        def read(c):
            command=_in_scope(control_command('cancel-raising-reader',self.f.authority,targets=[self.f.subject],action='cancel',now=self.f.now),self.f.storage.scope_id)
            command['actor']=self.f.actor;command['body']['control']['body']['actor']=self.f.actor
            self.assertEqual(self.f.controls.apply(self.f.controls.prepare(command))['status'],'success')
            raise TimeoutError('Synthetic cancelled transport')
        result=self.run_read(gap,allocation,reader=read)
        self.assertEqual(result['finish']['status'],'success')
        self.assertEqual(self.inspect()['stop_reason'],'cancelled');self.assertFalse(self.inspect()['satisfied'])

    def test_reader_exception_after_budget_expiry_records_exhaustion(self):
        gap=self.nominate();allocation=self.allocation('raising-expiry')
        def read(c):
            self.f.now=deepcopy(LATE)
            raise TimeoutError('Synthetic expired transport')
        result=self.run_read(gap,allocation,reader=read)
        self.assertEqual(result['finish']['status'],'success')
        self.assertEqual(self.inspect()['stop_reason'],'budget_exhausted');self.assertFalse(self.inspect()['satisfied'])

    def test_wrong_source_return_stops_unavailable_without_stranding_read(self):
        gap=self.nominate();allocation=self.allocation('wrong-source')
        source=self.f.observe('unapproved-other-source',payload=b'Synthetic wrong source.\n')
        result=self.run_read(gap,allocation,reader=lambda c:[pin(source)])
        self.assertEqual(result['finish']['status'],'success')
        self.assertEqual(self.inspect()['stop_reason'],'source_unavailable');self.assertFalse(self.inspect()['satisfied'])

    def test_unknown_returned_pin_stops_unavailable_without_stranding_read(self):
        gap=self.nominate();allocation=self.allocation('unknown-pin')
        absent=pin(self.source);absent['id']='source-never-ingested'
        result=self.run_read(gap,allocation,reader=lambda c:[absent])
        self.assertEqual(result['finish']['status'],'success')
        self.assertEqual(self.inspect()['stop_reason'],'source_unavailable');self.assertFalse(self.inspect()['satisfied'])

    def test_unavailable_candidate_does_not_displace_another_approved_read(self):
        source=self.f.observe('alternative-source',payload=b'Synthetic alternative counterevidence.\n')
        alternative=deepcopy(self.candidate);alternative.update(reference=component('alternative-read'),uri=source['body']['content']['locator']['uri'])
        value=self.definition.value;value['candidates'].append(alternative);value['inputs'].append(pin(source))
        self.definition=InvestigationDefinition(value)
        limits=self.h.resource.value['limits'];limits['calls']=2
        self.h.resource=self.h.policy('resource',limits)
        self.h.budgets=BudgetService(self.f.storage,definitions=[self.h.resource,self.h.attention],controls=self.f.controls,clock=lambda:deepcopy(self.f.now))
        self.token=self.f.controls.capture(actor=self.f.actor,authority=entity_ref(self.f.authority),capability='assessment',targets=[entity_ref(self.f.subject),entity_ref(self.source),entity_ref(source)])
        self.service=InvestigationService(self.f.storage,controls=self.f.controls,budgets=self.h.budgets,payloads=self.f.payloads,candidates=[self.candidate,alternative],clock=lambda:deepcopy(self.f.now))
        amounts={'calls':1,'input_bytes':1024,'output_bytes':1024,'elapsed_ms':1000}
        gap=self.nominate();self.run_read(gap,self.allocation('first-unavailable',amounts),reader=lambda c:[])
        self.assertEqual(self.inspect()['phase'],'ready');self.assertFalse(self.inspect()['satisfied'])
        prior=self.f.storage.get(gap_ref(self.f.storage.scope_id,self.definition));allocation=self.allocation('alternative-available',amounts)
        result=self.service.execute_read(self.definition,previous=pin(prior),token=self.token,candidate=alternative['reference'],allocation=allocation,
            reader=lambda c:[pin(source)],command_id='read-alternative',idempotency_key='read-alternative')
        self.assertEqual(result['finish']['status'],'success');self.assertTrue(self.inspect()['satisfied'])

    def test_lost_budget_stop_acknowledgement_replays_without_a_read(self):
        gap=self.nominate();allocation=self.allocation('stop-retry');self.f.now=deepcopy(LATE)
        first=self.run_read(gap,allocation,identity='stopped-read')
        second=self.run_read(gap,allocation,reader=lambda c:self.fail('A stopped read was executed'),identity='stopped-read')
        self.assertEqual(first['stop'],second['stop']);self.assertEqual(second['outcome'],'budget_exhausted')
        self.assertFalse(second['read_invoked'])

    def test_cancellation_between_finish_prepare_and_commit_records_terminal_state(self):
        gap=self.nominate();allocation=self.allocation('finish-race');original=self.service.commit;injected=[]
        def commit(command):
            payload=self.service._payload(command)[1]
            if payload['action']=='finish' and payload['observations'] and not injected:
                injected.append(True)
                cancel=_in_scope(control_command('finish-race-cancel',self.f.authority,targets=[self.f.subject],action='cancel',now=self.f.now),self.f.storage.scope_id)
                cancel['actor']=self.f.actor;cancel['body']['control']['body']['actor']=self.f.actor
                self.assertEqual(self.f.controls.apply(self.f.controls.prepare(cancel))['status'],'success')
            return original(command)
        with patch.object(self.service,'commit',side_effect=commit):result=self.run_read(gap,allocation)
        self.assertEqual(result['failed_finish']['status'],'failure');self.assertEqual(result['finish']['status'],'success')
        self.assertEqual(self.inspect()['stop_reason'],'cancelled');self.assertFalse(self.inspect()['satisfied'])

    def test_reader_ingests_a_new_sourced_observation_before_returning_it(self):
        value=self.definition.value;new_id='acquired-during-investigation'
        self.candidate=deepcopy(self.candidate)
        self.candidate['uri']='urn:synthetic:source:'+self.candidate['source_namespace']+':'+new_id
        value['candidates']=[self.candidate];self.definition=InvestigationDefinition(value)
        self.service=InvestigationService(self.f.storage,controls=self.f.controls,budgets=self.h.budgets,payloads=self.f.payloads,candidates=[self.candidate],clock=lambda:deepcopy(self.f.now))
        gap=self.nominate();allocation=self.allocation('new-acquisition');returned=[]
        def read(c):
            source=self.f.observe(new_id,payload=b'Synthetic newly acquired counterevidence.\n');returned.append(pin(source));return returned
        self.run_read(gap,allocation,reader=read)
        self.assertEqual(self.inspect()['observations'],returned);self.assertTrue(self.inspect()['satisfied'])

    def test_installed_access_context_allows_local_read_and_revocation_prevents_it(self):
        from matter.access import AccessService,HostAccessPolicy
        audience=component('investigation-audience')
        def access(grants):
            return AccessService(policy=HostAccessPolicy(scope_id=self.f.storage.scope_id,audiences=[audience],providers=[],
                grants=[{'reference':r,'audiences':[audience],'providers':[]} for r in grants]),controls=self.f.controls,current_read=self.f.storage.snapshot)
        admitted=access([pin(self.f.subject),pin(self.source)]);self.service.access=admitted
        with self.f.storage.snapshot() as view:
            context=admitted.capture(view,token=self.token,audience=audience,references=[pin(self.f.subject),pin(self.source)])
        gap=self.nominate(access_context=context)
        allocation=self.allocation('access-read');self.service.access=access([pin(self.f.subject)])
        with self.assertRaises(ContractError) as refused:
            self.run_read(gap,allocation,reader=lambda c:self.fail('Revoked access executed a read'),identity='access-gated-read',access_context=context)
        self.assertEqual(refused.exception.code,'E_AUTHORITY_REQUIRED')
        self.service.access=admitted
        result=self.run_read(gap,allocation,identity='access-gated-read',access_context=context)
        self.assertEqual(result['finish']['status'],'success');self.assertTrue(self.inspect()['satisfied'])

    def test_unrelated_control_race_preserves_acquired_evidence_without_a_second_read(self):
        gap=self.nominate();allocation=self.allocation('unrelated-finish-race');original=self.service.commit;injected=[];calls=[]
        def commit(command):
            payload=self.service._payload(command)[1]
            if payload['action']=='finish' and payload['observations'] and not injected:
                injected.append(True);value=self.definition.value;value['id']='separate-gap-control'
                self.nominate(InvestigationDefinition(value))
            return original(command)
        def read(candidate):calls.append(candidate);return [pin(self.source)]
        with patch.object(self.service,'commit',side_effect=commit):result=self.run_read(gap,allocation,reader=read)
        self.assertEqual(len(calls),1);self.assertEqual(result['failed_finish']['status'],'failure')
        self.assertEqual(result['finish']['status'],'success');self.assertTrue(self.inspect()['satisfied'])
        self.assertEqual(self.inspect()['observations'],[pin(self.source)])

    def test_non_observation_return_stops_unavailable_before_source_field_access(self):
        gap=self.nominate();allocation=self.allocation('wrong-record-kind')
        result=self.run_read(gap,allocation,reader=lambda c:[pin(self.f.subject)])
        self.assertEqual(result['finish']['status'],'success')
        state=self.inspect();self.assertEqual(state['phase'],'stopped')
        self.assertEqual(state['stop_reason'],'source_unavailable');self.assertFalse(state['satisfied'])
