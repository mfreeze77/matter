"""Portable review shapes and semantic identity; no provider or receiving proof."""
import unittest
from matter.assistant_review import ReviewRequest, ReviewResult
from matter.contracts import ContractError
from integration import test_assistant_review_memory as fixtures


class ReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReviewTests('runTest'); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.request = self.fixture.request

    def test_unknown_and_stopped_cannot_appear_as_quiet_or_clear_any_input(self):
        for status in ('stopped','failed','unknown'):
            for field, value in (('proposal','quiet'),('reviewed',[self.fixture.source]),('ledger',self.fixture.ledger())):
                with self.subTest(status=status, field=field):
                    raw = self.fixture.result(status=status); raw[field] = value
                    with self.assertRaises(ContractError): ReviewResult(raw)

    def test_raw_reply_unversioned_body_and_unbounded_limits_are_rejected(self):
        for field,value in (('reply','model text'),('contract_version','9.0'),('limits',{**self.request.value['limits'],'max_tool_calls':0})):
            with self.subTest(field=field):
                raw = self.request.value; raw[field] = value
                with self.assertRaises(ContractError): ReviewRequest(raw)

    def test_material_context_and_ledger_revisions_change_wake_but_cosmetic_routes_do_not(self):
        for field,value in (('trigger_routes',['accumulation']),('reason_code','another_wrapper')):
            raw=self.request.value;raw[field]=value
            self.assertEqual(ReviewRequest(raw).wake_id,self.request.wake_id)
        raw=self.request.value;raw['lens']['revision_id']='approved-2'
        self.assertNotEqual(ReviewRequest(raw).wake_id,self.request.wake_id)
        source=self.fixture.artifact('evidence','later','source_fact',{'new':'correction'})
        changed=self.fixture.req(contributions=[{'reference':source,'lineage':'source-lineage-1'}])
        self.assertNotEqual(changed.wake_id,self.request.wake_id)

    def test_mixed_or_foreign_ledger_slots_and_future_cut_are_refused(self):
        for ledger in (self.fixture.ledger(conveyed=[self.fixture.assessment]), self.fixture.ledger()):
            raw=self.request.value
            if not ledger['conveyed']: ledger['lens']['client_id']='other-client'
            raw['ledger']=ledger
            with self.assertRaises(ContractError): ReviewRequest(raw)
        raw=self.request.value;raw['ledger']=self.fixture.ledger();raw['ledger']['as_of']['value']='2051-01-01T00:00:00Z'
        with self.assertRaises(ContractError): ReviewRequest(raw)

    def test_no_model_body_or_delivery_permission_is_part_of_a_review_result(self):
        raw=self.fixture.result();raw['send_now']=True
        with self.assertRaises(ContractError): ReviewResult(raw)
        raw=self.fixture.result();raw['reply']='raw assistant reply'
        with self.assertRaises(ContractError): ReviewResult(raw)

    def test_detached_values_cannot_mutate_retry_identity(self):
        raw=self.request.value;raw['lens']['client_id']='changed'
        self.assertEqual(self.request.value['lens']['client_id'],'client-a')
        with self.assertRaises(AttributeError): self.request.value=raw


    def test_portable_recorded_vectors_round_trip_without_provider_execution(self):
        import json
        from pathlib import Path
        path=Path(__file__).resolve().parents[1]/'fixtures/assistant-review/vectors.json'
        cases=json.loads(path.read_text())['cases']
        self.assertEqual(len(cases),6)
        for case in cases:
            request,result=ReviewRequest(case['request']),ReviewResult(case['result'])
            self.assertEqual(request.wake_id,case['expected_wake_id'])
            self.assertEqual(result.value['wake_id'],request.wake_id)


    def test_wire_codes_and_digests_reject_trailing_newline(self):
        for mutate in (lambda raw:raw.update(reason_code='quiet\n'),
                       lambda raw:raw['assessment'].update(digest='a'*64+'\n')):
            raw=self.request.value;mutate(raw)
            with self.assertRaises(ContractError):ReviewRequest(raw)
        raw=self.fixture.result(status='failed');raw['error_code']='failed\n'
        with self.assertRaises(ContractError):ReviewResult(raw)


    def test_noncanonical_numbers_raise_coded_contract_error(self):
        raw=self.request.value;raw['limits']['timeout_ms']=1.5
        with self.assertRaises(ContractError) as error:ReviewRequest(raw)
        self.assertEqual(error.exception.code,'E_SCHEMA_INVALID')
