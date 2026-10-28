"""MAT-039 injected HTTP-shaped runner checks; none contact a provider."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch
from matter.canonical import canonical_digest
from matter.evaluation.offline import OfflineReport
from matter.evaluation.provider import provider_preflight,run_provider
from matter.semantic.providers.typesafe import HTTPResponse
from evaluation import test_offline_harness as offline_fixture
import replay_helpers as core

KEY='SYNTHETIC-ONLY-NOT-A-CREDENTIAL'


class ProviderRunnerTests(unittest.TestCase):
    def setUp(self):
        h=offline_fixture.OfflineHarnessTests('runTest')
        self.corpus,self.split,self.a,self.b,self.jobs,_=h.inputs()
        # A synthetic schema fixture isolates provider preflight. The separate
        # offline suite actually runs the core episodes and fault matrix.
        attempts=[{'status':j['expected_status'],'matches_expected_status':True} for j in self.jobs]
        self.offline=OfflineReport({'schema_version':'1.0','mode':'offline_fixture','corpus_digest':self.corpus.sha256,'split_digest':self.split.digest,
            'arms':[self.a.digest,self.b.digest],'fixture_digest':'a'*64,
            'scheduled_manifest_digest':canonical_digest(self.jobs,'matter.offline-schedule.v1'),'scheduled':len(attempts),
            'counts':{s:sum(a['status']==s for a in attempts) for s in ('successful','abstained','failed','stale')},
            'attempts':attempts,'episodes':[],'passed':True,
            'gates':{'provider_accuracy':'not_run','live_delivery':'not_run','qualification':'not_run'},'consequential_use':False})
        self.config={'mode':'provider_shadow','provider':'typesafe','model':'jev-1.14.0','scope_id':self.corpus.value['scope_id'],
            'credential_source':'synthetic-injected-test','max_calls':8,'timeout_seconds':2,'wall_seconds':120,'max_cost_usd':'0.03',
            'price_basis':{'model':'jev-1.14.0','source':'https://docs.typesafe.ai/models','checked_at':core.NOW,
                'input_usd_per_million':'0.042','output_usd_per_million':'0','max_input_tokens_per_call':65536},
            'trials_per_case':1,'max_request_bytes':65536,'max_response_bytes':65536}
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.destination=Path(self.tmp.name)/'run';self.requests=[]

    def arguments(self):
        return dict(config=self.config,corpus=self.corpus,split=self.split,candidate=self.b,jobs=self.jobs,
            offline=self.offline,credential=KEY,output=self.destination)
    def transport(self,*,model=None,timeout=False):
        def http(**kwargs):
            request=json.loads(kwargs['body']);self.requests.append(request)
            if timeout:raise TimeoutError('A synthetic timeout.')
            answers={k:{'type':'noul','noul':1} for k in request['questions']}
            return HTTPResponse(200,json.dumps({'model':model or self.config['model'],'answers':answers,'usage':{'input_tokens':12,'output_tokens':2}}).encode())
        return http

    def test_preflight_missing_unselected_and_changed_inputs_never_dispatch(self):
        args=self.arguments();args['credential']=None
        self.assertEqual(run_provider(**args,live=True,http=self.transport())['reason'],'credential_missing')
        args=self.arguments();args['config']={**self.config,'mode':'offline_fixture'}
        self.assertEqual(run_provider(**args,live=True,http=self.transport())['reason'],'provider_not_selected')
        self.assertEqual(run_provider(**self.arguments(),http=self.transport())['reason'],'live_mode_not_selected')
        args=self.arguments();args['jobs']=deepcopy(self.jobs);args['jobs'][0]['batch']['questions'][0]['instructions']='A changed question.'
        self.assertEqual(run_provider(**args,live=True,http=self.transport())['reason'],'offline_schedule_mismatch')
        self.assertEqual(self.requests,[]);self.assertFalse(self.destination.exists())

    def test_actual_adapter_receipts_resolved_model_and_capture_only(self):
        with patch('matter.assessments.AssessmentService.commit') as publish,patch('matter.delivery.DeliveryService.send') as delivery:
            report=run_provider(**self.arguments(),live=True,http=self.transport(),clock=lambda:core.NOW)
            self.assertEqual(report['status'],'completed',report)
            publish.assert_not_called();delivery.assert_not_called()
        self.assertEqual(report['fresh_attempts'],8);self.assertEqual(len(self.requests),8)
        self.assertTrue(all(x['primitive_valid'] for x in report['observations']))
        self.assertEqual(report['qualification'],'unknown');self.assertEqual(report['real_deliveries'],0)
        self.assertTrue(all(x['result']['resolved_model']=='jev-1.14.0' for x in report['observations']))
        self.assertNotIn(KEY,(self.destination/'manifest.json').read_text())
        before=len(self.requests)
        again=run_provider(**self.arguments(),live=True,resume=True,http=self.transport(),clock=lambda:core.NOW)
        self.assertEqual(len(self.requests),before);self.assertEqual(again['fresh_attempts'],0);self.assertEqual(again['cached_replays'],8)
        self.assertTrue(all(x['observation_kind']=='cached_replay' for x in again['observations']))

    def test_interrupted_start_is_unknown_and_never_resubmitted(self):
        def interrupt(index):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):run_provider(**self.arguments(),live=True,http=self.transport(),clock=lambda:core.NOW,after_start=interrupt)
        self.assertEqual(self.requests,[])
        report=run_provider(**self.arguments(),live=True,resume=True,http=self.transport(),clock=lambda:core.NOW)
        self.assertEqual(report['incomplete_attempts'],1);self.assertEqual(report['fresh_attempts'],7)
        self.assertEqual(len(self.requests),7);self.assertEqual(report['status'],'incomplete')
        self.assertEqual(report['observations'][0]['status'],'outcome_unknown')

    def test_timeout_and_alias_mismatch_remain_attempts_not_successes(self):
        report=run_provider(**self.arguments(),live=True,http=self.transport(timeout=True),clock=lambda:core.NOW)
        self.assertEqual(report['fresh_attempts'],8)
        self.assertTrue(all(x['result']['execution_status']=='timed_out' for x in report['observations']))
        self.assertTrue(all(x['billing_cost']=='not_observed' for x in report['observations']))
        self.destination=Path(self.tmp.name)/'alias'
        report=run_provider(**self.arguments(),live=True,http=self.transport(model='another-resolved-model'),clock=lambda:core.NOW)
        self.assertEqual(report['fresh_attempts'],1);self.assertEqual(report['status'],'incomplete')
        self.assertEqual(report['observations'][0]['result']['resolved_model'],'another-resolved-model')
        self.assertEqual(report['stop_reason'],'resolved_model_differs_from_price_binding')

    def test_declared_cost_and_scope_are_checked_before_any_request(self):
        args=self.arguments();args['config']={**self.config,'max_cost_usd':'0.00001'}
        self.assertEqual(run_provider(**args,live=True,http=self.transport())['reason'],'cost_limit_below_worst_case_schedule')
        args=self.arguments();args['config']={**self.config,'scope_id':'foreign'}
        self.assertEqual(run_provider(**args,live=True,http=self.transport())['reason'],'scope_mismatch')
        self.assertFalse(self.requests)
