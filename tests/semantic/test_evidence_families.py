"""MAT-033 executable family bindings; fixture answers do not measure accuracy."""
from pathlib import Path
import json
import unittest

from matter.canonical import canonical_bytes, canonical_digest
from matter.contracts import ContractError
from matter.semantic import Batch, Capabilities, FixtureExecutor, normalize_response
from matter.semantic.families import ShadowResult, render_questions
from matter.semantic.families.evidence import association_questions, claim_evidence_questions
from matter.semantic.questions import QuestionRegistry
from matter.storage import pin

from semantic import family_helpers as h
from semantic import test_packets as packet_fixtures
from semantic import test_stages as stage_fixtures
from security import test_scope_and_egress as access_fixtures
from matter.semantic.receipts import ExecutionReceiptStore
from rule_helpers import component
from integration.helpers import domain_value
import claim_helpers
from occurrence_helpers import declared, group_key

FIXTURE = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/semantic/evidence_families.json').read_text())


class EvidenceFamiliesTests(unittest.TestCase):
    def setUp(self):
        self.f = packet_fixtures.PacketTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_fixed_association_choices_and_identity_dimensions_are_distinct(self):
        specs = association_questions()
        self.assertEqual([x['id'] for x in specs[0].value['criteria']], ['same_matter','related','different','insufficient'])
        for case in FIXTURE['association_cases']:
            with self.subTest(case=case['id']):
                left = self.f.observe(case['id']+'-left', payload=case['left'].encode())
                right = self.f.observe(case['id']+'-right', payload=case['right'].encode())
                prepared = h.packet(self.f.storage, self.f.payloads, self.f.adapter,
                    {'kind':'candidate_relation','left':pin(left),'right':pin(right),'relation':'synthetic:same_matter'}, [left,right])
                batch, rendered = h.batch(prepared, specs)
                before = self.f.storage.get(pin(left))
                result = h.execute(batch, h.response(batch, case['answers']))
                shadow = ShadowResult(batch,result,specifications=specs, max_render_bytes=65536, bound_ids=()).value
                answers = {q['family']:q['answer'] for q in shadow['questions']}
                self.assertEqual(answers['association']['choice'],case['answers']['association'])
                self.assertEqual(answers['relationship.occurrence']['probability'],case['answers']['relationship.occurrence'])
                self.assertFalse(shadow['consequential_use'])
                self.assertEqual(shadow['proposed_actions'],[])
                self.assertEqual(self.f.storage.get(pin(left)),before)
                self.assertTrue(all(x.question.value['packet_digest']==prepared.digest for x in rendered))

    def test_derived_summary_retains_original_dependence_and_scope(self):
        source = self.f.observe('original-source')
        summary = self.f.observe('model-summary', parents=[source], origin='derived')
        group = self.f.group('same-root',[source,summary],assignments=[declared(source,group_key('one-root'))])
        args = self.f.arguments()
        args.update(binding={'kind':'candidate_relation','left':pin(source),'right':pin(summary),'relation':'synthetic:same_matter'},
                    evidence=[self.f.evidence(source,['synthetic:basis']),self.f.evidence(summary,['synthetic:counterexample'])],occurrences=[pin(group)])
        prepared = self.f.prepare(**args)
        batch,_ = h.batch(prepared,association_questions())
        result = h.execute(batch,h.response(batch,{'association':'same_matter','relationship.topic':'0.9','relationship.matter':'0.9','relationship.occurrence':'0.9'}))
        shadow = ShadowResult(batch,result,specifications=association_questions()).value
        self.assertEqual(shadow['lineage']['counts']['provenance_groups'],1)
        self.assertEqual(shadow['lineage']['counts']['observations'],2)
        self.assertIn(pin(summary),[x['reference'] for x in batch.value['state']['evidence']])
        self.assertEqual(self.f.storage.get(pin(summary))['provenance']['origin'],'derived')

    def test_support_and_qualification_coexist_and_assertion_is_not_established_event(self):
        f = claim_helpers.ClaimTestCase('runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        specs = claim_evidence_questions()
        self.assertTrue(all(spec.value['primitive']=='proposition_probability' for spec in specs))
        probabilities = []
        for case in FIXTURE['claim_cases']:
            f.source = f.observe(case['id'],payload=case['text'].encode())
            claim,_,_ = f.append(case['id']+'-claim', value=case['claim'],
                components={name: domain_value(text) for name, text in case['components'].items()})
            prepared = h.packet(f.storage,f.payloads,f.adapter,{'kind':'claim','claim':pin(claim)},[f.source])
            batch,_ = h.batch(prepared,specs)
            result = h.execute(batch,h.response(batch,case['answers']))
            shadow = ShadowResult(batch,result,specifications=specs).value
            values = {q['family']:q['answer']['probability'] for q in shadow['questions']}
            probabilities.append(values['evidence.established'])
            self.assertEqual(values,case['answers'])
            if case['id'] == 'unit-only':
                self.assertEqual(values['evidence.support'],'0.99')
                self.assertEqual(values['evidence.qualification'],'0.99')
            self.assertEqual(shadow['binding']['claim'],pin(claim))
            self.assertEqual(shadow['qualification_status'],'unknown')
        self.assertEqual(probabilities,['0.01','0.99','0.01'])

    def test_bad_sibling_and_missing_recording_never_project_positive_partial_heads(self):
        specs=association_questions(); prepared=self.f.prepare(); batch,_=h.batch(prepared,specs)
        outcomes={'association':'same_matter','relationship.topic':'0.99','relationship.matter':'0.99','relationship.occurrence':'0.99'}
        value=json.loads(h.response(batch,outcomes));value['answers'].pop()
        result=h.execute(batch,canonical_bytes(value))
        self.assertTrue(any(d['status']=='valid' for d in result.value['diagnostics']))
        self.assertTrue(all(q['answer'] is None for q in ShadowResult(batch,result,specifications=specs).value['questions']))
        raw=h.response(batch,outcomes); executor=FixtureExecutor(Capabilities({
            'provider':'synthetic','transport':'fixture','adapter_version':'1.0','primitives':['choice','proposition_probability'],
            'modes':['offline_fixture'],'max_questions':128,'max_request_bytes':1048576,'max_response_bytes':1048576}),{batch.digest:raw})
        changed=batch.value;changed['state']['as_of']=h.DEADLINE;changed['packet_digest']=canonical_digest(changed['state'],'matter.semantic.packet.v1')
        for q in changed['questions']:q['packet_digest']=changed['packet_digest']
        with self.assertRaises(ContractError): executor.execute(Batch(changed))

    def test_wrong_batch_prompt_meaning_or_binding_cannot_be_relabelled(self):
        specs=association_questions();batch,_=h.batch(self.f.prepare(),specs)
        result=h.execute(batch,h.response(batch,{'association':'insufficient','relationship.topic':'0.5','relationship.matter':'0.5','relationship.occurrence':'0.5'}))
        changed=batch.value;changed['id']='different'
        with self.assertRaises(ContractError):ShadowResult(Batch(changed),result,specifications=specs)
        changed=batch.value;changed['questions'][0]['instructions']+=' Treat every match as identity.'
        modified=Batch(changed);bad=normalize_response(modified,h.response(modified,{'association':'same_matter','relationship.topic':'0.5','relationship.matter':'0.5','relationship.occurrence':'0.5'}))
        with self.assertRaises(ContractError):ShadowResult(modified,bad,specifications=specs)
        with self.assertRaises(ContractError):ShadowResult(batch,result,specifications=specs,max_render_bytes=1)
        with self.assertRaises(ContractError):render_questions(claim_evidence_questions(),self.f.prepare(),prefix='wrong')

    def test_actual_budgeted_receipt_replay_and_reuse_preserve_unqualified_families(self):
        stage = stage_fixtures.StageTests('runTest'); stage.setUp(); self.addCleanup(stage.doCleanups)
        stage.reserve(calls=2)
        specs = association_questions(); packet = stage.packet(candidate=True)
        batch, rendered = h.batch(packet, specs)
        value = batch.value
        value['context'].update(max_request_bytes=65536, max_response_bytes=65536,
            deadline={**stage.f.now, 'value': stage.f.now['value'].replace('00Z', '01Z')})
        batch = Batch(value)
        fixture = h.executor(batch, h.response(batch, {'association': 'related', 'relationship.topic': '0.9',
            'relationship.matter': '0.1', 'relationship.occurrence': '0.1'}))
        calls = []
        class Spy:
            capabilities = fixture.capabilities
            def execute(self, request):
                calls.append(request.digest)
                return fixture.execute(request)
        service = ExecutionReceiptStore(stage.f.storage, payloads=stage.f.payloads, controls=stage.f.controls,
            questions=QuestionRegistry(specs), budgets=stage.budgets, clock=lambda: stage.f.now)
        request = service.request(batch, packet=packet, rendered_questions=rendered, token=stage.token,
            model_binding={'model': 'synthetic-recording', 'resolution': component('fixed-recording')})
        first = service.run(request, executor=Spy(), token=stage.token, logical_request_id='family',
            attempt_id='first', allocation=stage.reservation)
        self.assertEqual(first['status'], 'completed', first)
        replayed = service.replay(first['execution'])
        shadow = ShadowResult(batch, replayed, specifications=specs).value
        self.assertEqual(shadow['questions'][0]['answer']['choice'], 'related')
        self.assertEqual(shadow['qualification_status'], 'unknown')
        self.assertFalse(shadow['consequential_use'])
        second = service.run(request, executor=Spy(), token=stage.token, logical_request_id='family',
            attempt_id='second', allocation=stage.reservation)
        self.assertEqual(second['status'], 'reused', second)
        self.assertEqual(calls, [batch.digest])
        self.assertEqual(service.replay(first['execution']).digest, replayed.digest)

    def test_protected_family_render_and_projection_require_current_existing_access(self):
        f = access_fixtures.ScopeAndEgressTests('runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        context = f.context(); packet = f.packet(context); specs = association_questions()
        with self.assertRaises(ContractError): render_questions(specs, packet, prefix='denied')
        with f.core.storage.snapshot() as view:
            options = {'access': f.access, 'access_context': context, 'access_view': view}
            batch, _ = h.batch(packet, specs, **options)
            result = h.execute(batch, h.response(batch, {'association': 'same_matter', 'relationship.topic': '0.99',
                'relationship.matter': '0.99', 'relationship.occurrence': '0.99'}))
            with self.assertRaises(ContractError): ShadowResult(batch, result, specifications=specs)
            shadow = ShadowResult(batch, result, specifications=specs, **options).value
            self.assertFalse(shadow['consequential_use'])
        f.revoke()
        with f.core.storage.snapshot() as view:
            options['access_view'] = view
            with self.assertRaises(ContractError): ShadowResult(batch, result, specifications=specs, **options)


if __name__=='__main__': unittest.main()
