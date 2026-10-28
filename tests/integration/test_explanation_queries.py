"""MAT-023 actual SQLite projection/explanation checks; no generated rationale."""
from copy import deepcopy
from datetime import datetime,timezone
import unittest

from matter.contracts import ContractError
from matter.queries import QueryService
from matter.storage import entity_ref,pin,StorageError
from integration import test_audience_attention as fixtures


def now():
    return {'state':'known','value':datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z'),'precision':'microsecond'}


class ExplanationQueriesTests(unittest.TestCase):
    def setUp(self):
        self.a=fixtures.AudienceAttentionTests('runTest');self.a.setUp();self.addCleanup(self.a.doCleanups)
        self.f=self.a.f
        self.query=QueryService(self.f.storage,controls=self.f.controls,assessments=self.f.service,payloads=self.f.payloads)

    def project(self,assessment=None,decision=None,**kwargs):
        return self.query.project(entity_ref(self.f.subject),actor=self.f.actor,authority=entity_ref(self.f.authority),
            assessment=None if assessment is None else pin(assessment),attention=None if decision is None else pin(decision),**kwargs)

    def test_quiet_reasons_retain_delivered_vs_inadequate_evidence(self):
        first,*_=self.a.assess('first');_,decision,*_=self.a.evaluate(first)
        self.a.deliver(first,self.a.milestone(decision))
        second,*_=self.a.assess('second');value,receipt,*_=self.a.evaluate(second)
        shown=self.project(second,receipt)
        self.assertEqual(shown['explanation']['treatment'],'quiet')
        self.assertIn('already_delivered',shown['explanation']['reasons'])
        unknown,*_=self.a.assess('unknown',status='unknown',confidence='0.01')
        _,receipt,*_=self.a.evaluate(unknown)
        self.assertIn('insufficient_evidence',self.project(unknown,receipt)['explanation']['reasons'])

    def test_historical_projection_retains_original_policy_and_knowable_sources(self):
        first,claim,source,occurrence=self.a.assess('original');_,decision,*_=self.a.evaluate(first)
        cut=now();original=self.project(first,decision,as_of=cut,include_payload=True)
        correction=self.a.episode.claim('correction',self.a.episode.condition_a,'retracted',source,supersedes=[claim])
        latest=self.a.episode.assess(correction,occurrence,status='unknown',purpose=self.a.purpose_ref)
        again=self.project(first,decision,as_of=cut,include_payload=True)
        self.assertEqual(original,again)
        self.assertEqual(again['explanation']['profile'],first['body']['profile'])
        self.assertNotIn(pin(correction),[pin(r) for r in again['records']])
        with self.assertRaises((ContractError,StorageError)):
            self.project(latest,as_of=cut)
        self.assertIn('assessment_stale',self.project(first,decision)['incomplete_reasons'])

    def test_missing_blob_is_unavailable_without_manufactured_text(self):
        assessment,_,source,_=self.a.assess('missing');_,decision,*_=self.a.evaluate(assessment)
        self.assertEqual(self.project(assessment,decision,include_payload=True)['explanation']['reconstruction'],'available')
        digest=source['body']['content']['digest']
        for path in self.f.payloads._directory.rglob('*'):
            if path.is_file() and path.read_bytes()==b'Synthetic episode missing.\n':path.unlink()
        result=self.project(assessment,decision,include_payload=True)
        item=next(s for s in result['explanation']['sources'] if s['sha256']==digest)
        self.assertEqual(item['reconstruction'],'unavailable');self.assertNotIn('text',item)
        self.assertIn('retained_material_unavailable',result['incomplete_reasons'])

    def test_pagination_binds_scope_selection_and_changed_snapshot(self):
        assessment,*_=self.a.assess('page');first=self.project(assessment,limit=1)
        cursor=first['next_cursor'];self.assertIsNotNone(cursor)
        second=self.project(assessment,limit=1,cursor=cursor)
        self.assertNotEqual(first['records'],second['records'])
        other,*_=self.a.assess('other')
        with self.assertRaises(ContractError):self.project(other,limit=1,cursor=cursor)
        with self.assertRaises(ContractError):self.project(assessment,limit=1,cursor=cursor)
        foreign=entity_ref(self.f.subject);foreign['scope_id']='foreign'
        with self.assertRaises(ContractError):self.query.project(foreign,actor=self.f.actor,authority=entity_ref(self.f.authority),cursor=cursor)

    def test_original_attention_cannot_be_relabelled_as_other_assessment(self):
        first,*_=self.a.assess('one');_,decision,*_=self.a.evaluate(first)
        second,*_=self.a.assess('two')
        with self.assertRaises(ContractError):self.project(second,decision)

    def test_delivery_authorized_is_unknown_until_observed_success(self):
        from integration import delivery_helpers
        from matter.outbox import RESULT_EXTENSION
        h=delivery_helpers.DeliveryFixture('runTest');h.setUp();self.addCleanup(h.doCleanups)
        _,_,command=h.authorize();result=h.service.execute(command)
        self.assertEqual(result['status'],'success',result)
        authorization=result['extensions'][RESULT_EXTENSION]['value']['authorization']
        q=QueryService(h.f.storage,controls=h.f.controls,assessments=h.f.service,delivery=h.service)
        projection=q.project(entity_ref(h.f.subject),actor=h.f.actor,authority=entity_ref(h.f.authority),
            assessment=pin(h.assessment),attention=pin(h.decision),authorizations=[authorization])
        self.assertEqual(projection['deliveries'][0]['status'],'delivery_unknown')
        self.assertEqual(projection['deliveries'][0]['observations'],[])
        self.assertEqual(h.transport.calls,[])

    def test_loser_redirect_and_concurrent_split_use_one_consistent_snapshot(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        import identity_helpers
        from matter.authority import AuthorityPolicy,CAPABILITIES,CONTROL_KINDS
        from matter.controls import ControlService
        from matter.identity_corrections import IdentityCorrectionService
        from matter.storage import SQLiteStore
        h=identity_helpers.IdentityTestCase('runTest');h.setUp();self.addCleanup(h.doCleanups)
        a,b=h.matter('query-a'),h.matter('query-b');h.attach(b,label='query-child')
        policy=AuthorityPolicy(h.storage.scope_id,actors=[identity_helpers.ACTOR],authorities=[pin(h.authority)],
            capabilities=CAPABILITIES,control_kinds=CONTROL_KINDS)
        controls=ControlService(h.storage,policy=policy)
        q=QueryService(h.storage,controls=controls)
        def project(**kwargs):return q.project(entity_ref(b),actor=identity_helpers.ACTOR,authority=entity_ref(h.authority),**kwargs)
        before=now();_,merged=h.merge(a,[b])
        result=project(limit=1);self.assertTrue(result['redirected']);self.assertEqual(result['resolved']['id'],a['id'])
        historical=project(as_of=before);self.assertFalse(historical['redirected'])
        correction=h.prepare_correction(merged['body']['merge_receipt'])
        original=h.storage.snapshot;triggered=[]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool, SQLiteStore(h.database,scope_id=h.storage.scope_id) as writer:
            service=IdentityCorrectionService(writer,policy=h.merge_policy)
            class Wrapped:
                def __init__(self,view):self.view=view
                def __getattr__(self,key):return getattr(self.view,key)
                def get(self,ref):
                    record=self.view.get(ref)
                    if ref['record_type']=='matter' and ref['id']==b['id'] and not triggered:
                        triggered.append(pool.submit(service.correct,correction))
                    return record
            self_test=self
            @contextmanager
            def snapshot():
                with original() as view:yield Wrapped(view)
            with patch.object(h.storage,'snapshot',snapshot):during=project()
            committed=triggered[0].result(timeout=20)
            self.assertEqual(committed['status'],'success',committed)
        self.assertTrue(triggered);self.assertTrue(during['redirected'])
        self.assertEqual(len(during['identity_members']),2)
        self.assertFalse(project()['redirected'])
        with self.assertRaises(ContractError):project(limit=1,cursor=result['next_cursor'])

    def test_explanation_excludes_other_assessments_and_refuses_future_cut(self):
        first,_,source,_=self.a.assess('selected');_,decision,*_=self.a.evaluate(first)
        second,_,other,_=self.a.assess('unrelated',status='unknown')
        # Another source's missing bytes must not break the selected explanation.
        for path in self.f.payloads._directory.rglob('*'):
            if path.is_file() and path.read_bytes()==b'Synthetic episode unrelated.\n':path.unlink()
        result=self.project(first,decision,include_payload=True)
        refs=[s['reference'] for s in result['explanation']['sources']]
        self.assertIn(pin(source),refs);self.assertNotIn(pin(other),refs)
        self.assertEqual(result['explanation']['reconstruction'],'available')
        self.assertNotIn('retained_material_unavailable',result['incomplete_reasons'])
        page=self.project(first,decision,include_payload=True,limit=1)
        self.assertLessEqual(len(page['explanation']['sources']),1)
        self.assertFalse(page['explanation']['records_complete'])
        with self.assertRaises(ContractError) as caught:
            self.project(first,as_of={'state':'known','value':'2099-01-01T00:00:00Z','precision':'second'})
        self.assertEqual(caught.exception.detail,'future_query_cut')
