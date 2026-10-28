"""Actual MAT-072 dispatch with injected provider responses; no live calls."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from matter.access import AccessService, HostAccessPolicy
from matter.canonical import canonical_bytes
from matter.evaluation.provider import GuardedProviderCase, run_guarded_diagnostic
from matter.semantic.providers.typesafe import HTTPResponse
from matter.storage import pin
from security import test_scope_and_egress as access_fixtures
from rule_helpers import NOW

KEY='SYNTHETIC-NOT-A-CREDENTIAL'


class GuardedProviderTests(unittest.TestCase):
    def setUp(self):
        self.h=access_fixtures.ScopeAndEgressTests('runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)
        h=self.h
        h.access=AccessService(policy=HostAccessPolicy(scope_id=h.core.storage.scope_id,audiences=[h.audience],
            providers=[{'reference':h.provider,'provider':'typesafe','transport':'http'}],
            grants=[{'reference':pin(s),'audiences':[h.audience],'providers':[h.provider]} for s in (h.core.subject,h.core.source)]),
            controls=h.core.controls,current_read=h.live_reader.snapshot)
        self.context=h.context();packet=h.packet(self.context);rendered=h.render(self.context,packet)
        self.case=GuardedProviderCase('one',h.batch(packet,rendered),h.access,self.context,
            h.prepare_assessment(self.context).view,(rendered,),{'expected_silence':True})
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.output=Path(self.tmp.name)/'run';self.requests=[]
        self.config={'mode':'provider_shadow','provider':'typesafe','model':'jev-1.14.0','scope_id':h.core.storage.scope_id,
            'credential_source':'synthetic-injected','max_calls':1,'timeout_seconds':2,'wall_seconds':30,'max_cost_usd':'0.003',
            'price_basis':{'model':'jev-1.14.0','source':'https://docs.typesafe.ai/models','checked_at':NOW,
                'input_usd_per_million':'0.042','output_usd_per_million':'0','max_input_tokens_per_call':65536},
            'trials_per_case':1,'max_request_bytes':65536,'max_response_bytes':65536}

    def http(self,**kwargs):
        request=json.loads(kwargs['body']);self.requests.append(request)
        return HTTPResponse(200,json.dumps({'model':'jev-1.14.0',
            'answers':{k:{'type':'noul','noul':0.1} for k in request['questions']},
            'usage':{'input_tokens':100,'output_tokens':0}}).encode())

    def run_cases(self,**overrides):
        args=dict(config=self.config,cases=[self.case],credential=KEY,output=self.output,
            provenance={'synthetic':True},live=True,http=self.http,clock=lambda:NOW)
        args.update(overrides);return run_guarded_diagnostic(**args)

    def test_live_selection_and_exact_guarded_question_are_required(self):
        for live in (False,1,'false','0',None):
            self.assertEqual(self.run_cases(live=live)['reason'],'live_mode_not_selected')
        self.assertEqual(self.run_cases(credential=None)['reason'],'credential_missing')
        wrong=self.case.batch.value;wrong['questions'][0]['instructions']='Substituted unsupported source.'
        from matter.semantic import Batch
        self.assertEqual(self.run_cases(cases=[replace(self.case,batch=Batch(wrong))])['reason'],'guarded_packet_mismatch')
        self.assertEqual(self.requests,[]);self.assertFalse(self.output.exists())

    def test_guarded_calls_use_shared_receipts_without_admission_or_delivery(self):
        with patch.object(self.h.access,'dispatch',wraps=self.h.access.dispatch) as dispatch, \
             patch('matter.assessments.AssessmentService.commit') as publish, \
             patch('matter.delivery.DeliveryService.send') as delivery:
            report=self.run_cases()
            self.assertEqual(report['status'],'completed',report)
            dispatch.assert_called_once();publish.assert_not_called();delivery.assert_not_called()
        self.assertEqual(report['fresh_attempts'],1);self.assertEqual(len(self.requests),1)
        self.assertEqual(report['qualification'],'unknown');self.assertEqual(report['real_deliveries'],0)
        row=report['observations'][0];self.assertTrue(row['primitive_valid'])
        self.assertEqual(row['estimated_input_cost_usd'],'0.0000042')
        self.assertNotIn(KEY,(self.output/'manifest.json').read_text())
        replay=self.run_cases(resume=True)
        self.assertEqual(replay['fresh_attempts'],0);self.assertEqual(replay['cached_replays'],1);self.assertEqual(len(self.requests),1)

    def test_revocation_after_preflight_before_dispatch_refuses_with_zero_http(self):
        report=self.run_cases(after_start=lambda index:self.h.revoke())
        self.assertEqual(report['status'],'incomplete');self.assertEqual(report['stop_reason'],'access_refused')
        self.assertEqual(report['fresh_attempts'],0);self.assertEqual(report['non_dispatched'],1)
        self.assertEqual(report['incomplete_attempts'],0);self.assertEqual(self.requests,[])
        self.assertTrue((self.output/'0-started.json').exists());self.assertTrue((self.output/'0-refused.json').exists())
        self.assertFalse((self.output/'0-result.json').exists())
        resumed=self.run_cases(resume=True)
        self.assertEqual(resumed['purpose'],'access_refused_accounting_only')
        self.assertEqual(resumed['non_dispatched'],1);self.assertEqual(resumed['incomplete_attempts'],0)
        self.assertEqual(resumed['observed_transport_attempts'],0);self.assertEqual(self.requests,[])
        self.assertEqual(resumed['reserved_cost_usd'],report['reserved_cost_usd'])

    def test_inflight_revocation_withholds_result_and_retains_observed_unknown_attempt(self):
        def revoke(**kwargs):
            result=self.http(**kwargs);self.h.revoke();return result
        report=self.run_cases(http=revoke)
        self.assertEqual(len(self.requests),1);self.assertEqual(report['fresh_attempts'],1)
        self.assertEqual(report['observed_transport_attempts'],1);self.assertEqual(report['incomplete_attempts'],1)
        self.assertEqual(report['non_dispatched'],0);self.assertEqual(report['stop_reason'],'access_refused')
        self.assertTrue((self.output/'0-started.json').exists());self.assertFalse((self.output/'0-result.json').exists())
        self.assertTrue((self.output/'0-refused.json').exists())
        resumed=self.run_cases(resume=True)
        self.assertEqual(resumed['fresh_attempts'],0);self.assertEqual(resumed['incomplete_attempts'],1)
        self.assertEqual(resumed['observed_transport_attempts'],1);self.assertEqual(len(self.requests),1)
        self.assertEqual(resumed['reserved_cost_usd'],report['reserved_cost_usd'])
        self.assertNotIn('result',report['observations'][0]);self.assertNotIn('result',resumed['observations'][0])

    def test_later_revocation_withholds_prior_results_and_reconciles_entire_prefix(self):
        self.config.update(max_calls=3,max_cost_usd='0.009')
        cases=[replace(self.case,id=str(i)) for i in range(3)]
        def second_revokes(**kwargs):
            result=self.http(**kwargs)
            if len(self.requests)==2:self.h.revoke()
            return result
        report=self.run_cases(cases=cases,http=second_revokes)
        self.assertEqual(report['fresh_attempts'],2);self.assertEqual(report['incomplete_attempts'],1)
        self.assertEqual(report['not_attempted'],1);self.assertEqual(len(self.requests),2)
        self.assertTrue((self.output/'0-result.json').exists());self.assertFalse((self.output/'1-result.json').exists())
        resumed=self.run_cases(cases=cases,resume=True)
        self.assertEqual(resumed['observed_transport_attempts'],2);self.assertEqual(resumed['recorded_terminal_attempts'],1)
        self.assertEqual(resumed['incomplete_attempts'],1);self.assertEqual(resumed['not_attempted'],1)
        self.assertEqual(resumed['fresh_attempts'],0);self.assertEqual(resumed['cached_replays'],0)
        self.assertEqual(resumed['reserved_cost_usd'],report['reserved_cost_usd']);self.assertEqual(len(self.requests),2)
        for summary in (report,resumed):
            self.assertTrue(all('result' not in row and 'job_id' not in row for row in summary['observations']))
            self.assertNotIn(access_fixtures.MARKER.encode(),canonical_bytes(summary))
            self.assertNotIn(self.h.core.source['id'].encode(),canonical_bytes(summary))

    def test_interrupted_start_then_revoked_resume_is_unknown_not_zero_attempts(self):
        def interrupt(index):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_cases(after_start=interrupt)
        self.h.revoke()
        resumed=self.run_cases(resume=True)
        self.assertEqual(resumed['incomplete_attempts'],1);self.assertEqual(resumed['not_attempted'],0)
        self.assertEqual(resumed['observed_transport_attempts'],0)
        self.assertIsNone(resumed['observations'][0]['transport_attempt_observed'])
        self.assertEqual(self.requests,[])

    def test_policy_change_cost_and_provider_mismatch_do_not_dispatch(self):
        self.assertEqual(self.run_cases(config={**self.config,'max_cost_usd':'0.0001'})['reason'],'cost_limit_below_worst_case_schedule')
        policy=self.h.access.policy.value;policy['providers'][0]['provider']='other'
        other=AccessService(policy=HostAccessPolicy(**policy),controls=self.h.core.controls,current_read=self.h.live_reader.snapshot)
        self.assertEqual(self.run_cases(cases=[replace(self.case,access=other)])['reason'],'provider_access_mismatch')
        self.assertEqual(self.requests,[])
        self.assertEqual(self.run_cases()['status'],'completed')
        resumed=self.run_cases(cases=[replace(self.case,access=other)],resume=True)
        self.assertEqual(resumed['reason'],'provider_access_mismatch')
        self.assertEqual(resumed['recorded_terminal_attempts'],1)
        self.assertEqual(resumed['observed_transport_attempts'],1);self.assertEqual(resumed['fresh_attempts'],0)
        self.assertEqual(len(self.requests),1)

    def test_invalid_trial_count_does_not_create_artifacts(self):
        for value in (0,'2',True,4):
            result=self.run_cases(config={**self.config,'trials_per_case':value})
            self.assertEqual(result['reason'],'invalid_trials_per_case')
        self.assertEqual(self.requests,[]);self.assertFalse(self.output.exists())

    def test_configuration_errors_are_distinct_from_access_refusal(self):
        for config in ({**self.config,'unknown_key':True},{k:v for k,v in self.config.items() if k!='max_calls'},
                       {**self.config,'price_basis':{}}):
            self.assertEqual(self.run_cases(config=config)['reason'],'invalid_provider_configuration')
        self.assertEqual(self.requests,[]);self.assertFalse(self.output.exists())

    def test_invalid_adapter_credentials_are_configuration_errors(self):
        self.assertEqual(self.run_cases(credential=KEY+'\n')['reason'],'invalid_provider_configuration')
        self.assertEqual(self.requests,[]);self.assertFalse(self.output.exists())
