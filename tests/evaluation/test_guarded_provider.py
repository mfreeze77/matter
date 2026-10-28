"""Actual MAT-072 dispatch with injected provider responses; no live calls."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from matter.access import AccessService, HostAccessPolicy
from matter.canonical import canonical_digest
from matter.contracts import ContractError
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
        with self.assertRaises(ContractError):
            self.run_cases(after_start=lambda index:self.h.revoke())
        self.assertEqual(self.requests,[]);self.assertTrue((self.output/'0-started.json').exists())
        self.assertFalse((self.output/'0-result.json').exists())
        self.assertEqual(self.run_cases(resume=True)['reason'],'access_or_packet_refused')
        self.assertEqual(self.requests,[])

    def test_inflight_revocation_withholds_result_and_leaves_unknown_start(self):
        def revoke(**kwargs):
            result=self.http(**kwargs);self.h.revoke();return result
        with self.assertRaises(ContractError):self.run_cases(http=revoke)
        self.assertEqual(len(self.requests),1)
        self.assertTrue((self.output/'0-started.json').exists());self.assertFalse((self.output/'0-result.json').exists())
        self.assertEqual(self.run_cases(resume=True)['reason'],'access_or_packet_refused')
        self.assertEqual(len(self.requests),1)

    def test_policy_change_cost_and_provider_mismatch_do_not_dispatch(self):
        self.assertEqual(self.run_cases(config={**self.config,'max_cost_usd':'0.0001'})['reason'],'cost_limit_below_worst_case_schedule')
        policy=self.h.access.policy.value;policy['providers'][0]['provider']='other'
        other=AccessService(policy=HostAccessPolicy(**policy),controls=self.h.core.controls,current_read=self.h.live_reader.snapshot)
        self.assertEqual(self.run_cases(cases=[replace(self.case,access=other)])['reason'],'provider_access_mismatch')
        self.assertEqual(self.requests,[])

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
