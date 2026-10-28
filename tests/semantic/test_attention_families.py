"""MAT-034 conformance over actual lifecycle, host context and attention APIs.

Recorded model answers test binding/replay, not the accuracy of those answers.
"""
from copy import deepcopy
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from matter.canonical import canonical_bytes
from matter.citations import Utf8LineLocatorAdapter
from matter.contracts import ContractError
from matter.semantic.families import ShadowResult, render_questions
from matter.semantic.families.attention import CAUSES, change_question, contribution_questions, prepare_comparison
from matter.storage import entity_ref, pin
from matter.observations import source_index_ref
from matter.access import AccessService, HostAccessPolicy
from matter.semantic import Batch
from matter.semantic.questions import QuestionRegistry
from matter.semantic.receipts import ExecutionReceiptStore, _public_refs, _targets
from matter.semantic.rendering import RenderedQuestion
from matter.semantic.families.evidence import claim_evidence_questions
from matter.storage import SQLiteStore
from matter.matters import MatterService
from matter_helpers import identity_policy, metadata_command
from claim_helpers import claim_command
from semantic import family_helpers as h
from semantic import test_stages as stage_fixtures
from integration import test_audience_attention as attention_fixtures
from integration import delivery_helpers
from observation_helpers import observation_command
from rule_helpers import component

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/semantic'
EPISODE = json.loads((FIXTURES / 'recovery_episodes.json').read_text())


class AttentionFamiliesTests(unittest.TestCase):
    def setUp(self):
        self.a = attention_fixtures.AudienceAttentionTests('runTest'); self.a.setUp(); self.addCleanup(self.a.doCleanups)
        self.f, self.e = self.a.f, self.a.episode
        self.adapter = Utf8LineLocatorAdapter(self.f.payloads)

    def packet(self, original, sources, *, boundary=h.AS_OF):
        return h.packet(self.f.storage, self.f.payloads, self.adapter,
            {'kind': 'claim', 'claim': pin(original)}, sources, as_of=boundary)

    def compare(self, packet, original, assessment, **kw):
        args = dict(cause='new_evidence', after=pin(assessment), condition=pin(original),
                    purpose=pin(self.a.purpose), audience=pin(self.a.audience))
        args.update(kw)
        with self.f.storage.snapshot() as view:
            return prepare_comparison(view, packet, **args)

    def shadow(self, packet, answers=None):
        specs = (change_question(packet.state['comparison']['cause']), *contribution_questions())
        batch, rendered = h.batch(packet, specs)
        values = {spec.value['family']: '0.99' for spec in specs}
        values.update(answers or {})
        result = h.execute(batch, h.response(batch, values))
        return ShadowResult(batch, result, specifications=specs).value, batch, rendered

    def test_failure_other_success_then_matching_success_uses_existing_lifecycle(self):
        self.e.condition_a = deepcopy(EPISODE['original_condition'])
        original, _, first, _, _ = self.e.establish()
        original_bytes = canonical_bytes(self.f.storage.get(pin(original)))
        for case in EPISODE['cases']:
            with self.subTest(case=case['id']):
                source, occurrence = self.e.event(case['id'], at=self.f.now)
                success = self.e.claim(case['id'], case['condition'], 'recovered', source, effective=self.f.now)
                assessment = self.e.assess(success, occurrence)
                packet = self.packet(original, [source])
                compared = self.compare(packet, original, assessment, before=pin(first), result=pin(success))
                shadow, _, _ = self.shadow(compared, {'recovery.matching': case['recovery']})
                answer = next(q['answer'] for q in shadow['questions'] if q['family'] == 'recovery.matching')
                self.assertEqual(answer['probability'], case['recovery'])
                # Recording a very confident recovery proposal cannot mutate lifecycle.
                self.assertEqual(self.e.current()['value']['value']['state'], 'example:open')
                _, applied = self.e.apply('resolve', success, occurrence, assessment, condition=self.e.condition_a)
                self.assertEqual(applied.get('outcome'), case['transition'], applied)
                self.assertFalse(shadow['consequential_use'])
        self.assertEqual(self.e.current()['value']['value']['state'], 'example:resolved')
        self.assertEqual(canonical_bytes(self.f.storage.get(pin(original))), original_bytes)
        # A distinct late report of an old happening is not a new recurrence.
        source, occurrence = self.e.event('late-old-failure', at=original['body']['applicability']['start'],
                                          available_at=self.f.now)
        late = self.e.claim('late-old-failure', self.e.condition_a, 'present', source,
                            effective=original['body']['applicability']['start'])
        late_assessment = self.e.assess(late, occurrence)
        late_packet = self.compare(self.packet(original, [source]), original, late_assessment,
                                   before=pin(assessment), result=pin(late))
        again, _, _ = self.shadow(late_packet, {'recovery.matching': '0.01', 'attention.objective': '0.99'})
        _, refused = self.e.apply('recur', late, occurrence, late_assessment)
        self.assertEqual(refused.get('outcome'), 'held_for_evidence', refused)
        self.assertEqual(self.e.current()['value']['value']['state'], 'example:resolved')
        self.assertEqual(again['proposed_actions'], [])
        self.assertEqual(again['questions'][2]['answer']['probability'], '0.99')

    def test_explicit_causes_and_preferences_hold_source_facts_fixed(self):
        assessment, original, source, _ = self.a.assess('preference')
        packet = self.packet(original, [source]); original_packet = packet.value
        before, _, _, _ = self.a.evaluate(assessment)
        self.assertEqual(before['treatment'], 'update')
        preference, _, _ = self.a.contexts.publish(self.a.contexts.definition('preference', 'digest-preference',
            content={'preferred_treatment': 'digest', 'channels': [],
                     'interruption_budget': {'schema': self.a.policy.reference, 'value': {'limit': 0}}}))
        self.e.remember(preference)
        self.a.context_refs['preferences'] = [pin(preference)]
        selected = self.a.contexts.select([preference]).value['components'][0]['reference']
        after, _, _, _ = self.a.evaluate(assessment)
        self.assertEqual(after['treatment'], 'digest')
        causes = []
        for cause in CAUSES:
            compared = self.compare(packet, original, assessment, cause=cause, preferences=[pin(preference)])
            shadow, batch, _ = self.shadow(compared)
            self.assertEqual(compared.state['evidence'], packet.state['evidence'])
            self.assertEqual(compared.state['comparison']['cause'], cause)
            component = compared.state['comparison']['preferences'][0]['components'][0]
            self.assertEqual(component['reference'], selected)
            self.assertEqual(component['definition']['content']['preferred_treatment'], 'digest')
            causes.append(batch.value['questions'][0]['specification_digest'])
            self.assertEqual(shadow['proposed_actions'], [])
        self.assertEqual(len(set(causes)), 4)
        self.assertEqual(packet.value, original_packet)
        with self.assertRaises(ContractError):
            render_questions([change_question('new_evidence')], compared, prefix='wrong-cause')

    def test_existing_authored_scenario_contexts_bind_distinctly_without_runtime_claim(self):
        authored = json.loads((FIXTURES / 'civic_runtime_inputs.json').read_text())
        assessment, original, source, _ = self.a.assess('context-binding')
        packet = self.packet(original, [source]); facts = canonical_bytes(packet.state['evidence'])
        digests = []
        for context in authored['contexts']:
            purpose, _, _ = self.a.contexts.publish(self.a.contexts.definition('objective', context['id'],
                content={'statement': context['purpose'], 'constraints': [context['policy']]}))
            compared = self.compare(packet, original, assessment, cause='changed_policy', purpose=pin(purpose))
            rendered = render_questions(contribution_questions(), compared, prefix=context['id'])
            self.assertIn(context['purpose'], rendered[1].question.value['instructions'])
            self.assertEqual(canonical_bytes(compared.state['evidence']), facts)
            digests.append(compared.digest)
        self.assertEqual(len(set(digests)), 4)

    def test_uncertainty_and_observed_duplicate_remain_quiet_without_delivery_hook(self):
        assessment, original, source, _ = self.a.assess('unknown', status='unknown')
        decision, _, _, _ = self.a.evaluate(assessment)
        self.assertEqual(decision['treatment'], 'quiet')
        self.assertIsNone(decision['decision_request'])
        packet = self.compare(self.packet(original, [source]), original, assessment)
        shadow, _, _ = self.shadow(packet, {'attention.objective': '0.5', 'attention.novelty': '0.5'})
        self.assertEqual(shadow['comparison']['delivered'], {'state': 'not_supplied'})
        self.assertEqual(shadow['proposed_actions'], [])
        known, claim, source, _ = self.a.assess('known')
        _, receipt, _, _ = self.a.evaluate(known)
        queued = self.a.milestone(receipt, stage='queued')
        # Merely supplying a queued receipt cannot advance Matter's observed baseline.
        queued_packet = self.compare(self.packet(claim, [source]), claim, known, delivered=pin(queued))
        queued_shadow, _, _ = self.shadow(queued_packet)
        self.assertEqual(queued_shadow['comparison']['delivered']['record']['body']['stage'], 'queued')
        self.assertIsNone(self.a.baseline()['value']['value']['delivered'])
        milestone = self.a.milestone(receipt); self.a.deliver(known, milestone)
        repeated, _, _, _ = self.a.evaluate(known)
        self.assertEqual(repeated['treatment'], 'quiet')
        self.assertIn('already_delivered', repeated['reasons'])
        observed = self.compare(self.packet(claim, [source]), claim, known, delivered=pin(milestone))
        quiet, _, _ = self.shadow(observed, {'attention.novelty': '0.01'})
        self.assertFalse(quiet['consequential_use'])
        self.assertEqual(quiet['proposed_actions'], [])

    def test_context_availability_scope_binding_and_packet_limits_fail_closed(self):
        assessment, original, source, _ = self.a.assess('bounded')
        packet = self.packet(original, [source])
        future_time = {'state': 'known', 'value': '2080-01-01T00:00:00Z', 'precision': 'second'}
        # Even backdated host content cannot precede its actual committed snapshot.
        with patch('matter.storage.sqlite._now', return_value=future_time):
            unpublished_at_cut, _, _ = self.a.contexts.publish(self.a.contexts.definition('audience', 'future-receipt'))
        with self.assertRaises(ContractError) as error:
            self.compare(packet, original, assessment, audience=pin(unpublished_at_cut))
        self.assertEqual(error.exception.code, 'E_EVIDENCE_UNAVAILABLE')
        self.f.now = {'state': 'known', 'value': '2080-01-01T00:00:00Z', 'precision': 'second'}
        future, _, _ = self.a.contexts.publish(self.a.contexts.definition('audience', 'future'))
        with self.assertRaises(ContractError) as error:
            self.compare(packet, original, assessment, audience=pin(future))
        self.assertEqual(error.exception.code, 'E_EVIDENCE_UNAVAILABLE')
        foreign = pin(self.a.audience); foreign['scope_id'] = 'synthetic:other'
        for kw in ({'audience': foreign}, {'audience': pin(self.a.purpose)}, {'after': None},
                   {'condition': pin(source)}, {'cause': 'guess'}, {'result': pin(self.a.audience)},
                   {'preferences': [pin(source)]}, {'responsibilities': [pin(assessment)]},
                   {'preferences': pin(self.a.audience)}):
            with self.subTest(kw=kw), self.assertRaises(ContractError):
                self.compare(packet, original, assessment, **kw)
        compared = self.compare(packet, original, assessment)
        with self.assertRaises(ContractError): self.compare(compared, original, assessment)
        bounded = h.packet(self.f.storage, self.f.payloads, self.adapter,
            {'kind': 'claim', 'claim': pin(original)}, [source],
            max_packet_bytes=len(canonical_bytes(packet.state)) + 200)
        original_bytes = bounded.canonical
        with self.assertRaises(ContractError) as error:
            self.compare(bounded, original, assessment)
        self.assertEqual(error.exception.code, 'E_BUDGET_EXHAUSTED')
        self.assertEqual(bounded.canonical, original_bytes)

    def test_actual_source_correction_withholds_queued_advice_before_transport(self):
        f = delivery_helpers.DeliveryFixture('runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        # A consumer of current source meaning must declare the existing head index.
        index = f.f.storage.get(source_index_ref(f.f.storage.scope_id, f.source['body']['source_identity']))
        refs = [pin(f.claim), pin(f.occurrence), pin(index)]
        prepared = f.f.prepare(request=f.f.request(evidence=refs), extra=refs)
        command = f.f.command(prepared, interpretations=[{'node': 'evidence', 'claim': pin(f.claim),
            'labels': {'example:positive': 'supported'}, 'evidence_standard': f.f.profile.component_references['evidence']}])
        published = f.f.service.commit(command)
        self.assertEqual(published['status'], 'success', published)
        f.assessment = f.f.storage.get(published['body']['assessment'])
        f.a.episode.remember(f.assessment, *[f.f.storage.get(ref) for ref in f.assessment['body']['judgments']])
        _, f.decision, f.attention_command, _ = f.a.evaluate(f.assessment)
        f.token = f.f.controls.capture(actor=f.f.actor, authority=entity_ref(f.f.authority), capability='delivery',
            targets=[*f.a.targets(f.assessment), entity_ref(f.destination_permission)])
        _, _, authorization = f.authorize(identity='source-correction')
        original = f.source; identity = original['body']['source_identity']
        payload = b'SYNTHETIC CORRECTION: the earlier source report was withdrawn.\n'
        command = observation_command('family-correction', 'corrected-source', payload=payload,
            scope_id=f.f.storage.scope_id, source_namespace=identity['namespace'],
            event_id=identity['event_id'], revision_id=identity.get('revision_id'), available_at=f.f.now)
        command['body']['observation']['supersedes'] = [pin(original)]
        result = f.f.ingestor.ingest(f.f.ingestor.prepare(command), payload=payload)
        self.assertEqual(result['outcome'], 'committed', result)
        refused = f.service.send(authorization)
        self.assertEqual(refused['status'], 'failure', refused)
        self.assertEqual(refused['error']['code'], 'E_DEPENDENCY_STALE')
        self.assertEqual(f.transport.calls, [])
        self.assertIsNone(f.a.baseline()['value']['value']['delivered'])

    def test_context_scope_matches_assessed_matter_for_nonmatter_claim_subjects(self):
        _, original, source, occurrence = self.a.assess('scoped-subject')
        subjects = [entity_ref(source), {'schema': self.a.policy.reference, 'value': {'check': 'required'}}]
        for i, subject in enumerate(subjects):
            command = claim_command('nonmatter-'+str(i), 'nonmatter-'+str(i), self.f.subject, source,
                                    predicate='example:condition')
            body = command['body']['claim']['body']
            body.update(subject=subject, value=deepcopy(original['body']['value']),
                        applicability=deepcopy(original['body']['applicability']))
            result = self.f.claims.append(self.f.claims.prepare(command))
            self.assertEqual(result['status'], 'success', result)
            claim = self.f.storage.get(result['body']['claim'])
            assessment = self.e.assess(claim, occurrence)
            packet = self.packet(claim, [source])
            compared = self.compare(packet, claim, assessment)
            self.assertEqual(compared.state['comparison']['after']['record']['body']['matter'], pin(self.f.subject))
            wrong = self.a.contexts.definition('audience', 'subject-only-'+str(i)).value
            wrong['applies_to'] = [entity_ref(source)]
            from matter.contexts import ContextDefinition
            audience, _, _ = self.a.contexts.publish(ContextDefinition(wrong))
            with self.assertRaises(ContractError) as error:
                self.compare(packet, claim, assessment, audience=pin(audience))
            self.assertEqual(error.exception.code, 'E_SCOPE_FORBIDDEN')

    def test_public_and_protected_comparisons_use_actual_budgeted_receipt_store(self):
        assessment, claim, source, _ = self.a.assess('durable-comparison')
        base = self.packet(claim, [source]); compared = self.compare(base, claim, assessment)
        specs = (contribution_questions()[0], *claim_evidence_questions())
        stage = stage_fixtures.StageTests('runTest'); stage.setUp(); self.addCleanup(stage.doCleanups)
        stage.f = self.f; stage.questions = QuestionRegistry(specs)
        stage.targets = _targets(compared.value['dependencies'])
        stage.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
                                             capability='assessment', targets=stage.targets)
        stage.reserve(calls=4)

        def request_for(packet, specification, service, name, **options):
            batch, rendered = h.batch(packet, [specification], prefix=name, **options)
            value = batch.value
            value['context'].update(max_request_bytes=65536, max_response_bytes=65536,
                deadline={**self.f.now, 'value': self.f.now['value'].replace('00Z','01Z')})
            batch = Batch(value)
            request = service.request(batch, packet=packet, rendered_questions=rendered,
                token=stage.token, access_context=options.get('access_context'))
            return batch, request

        service = ExecutionReceiptStore(self.f.storage, payloads=self.f.payloads, controls=self.f.controls,
            questions=stage.questions, budgets=stage.budgets, clock=lambda:self.f.now)
        batch, request = request_for(compared, specs[0], service, 'public')
        result = service.run(request, executor=h.executor(batch,h.response(batch,{'recovery.matching':'0.5'})),
            token=stage.token, logical_request_id='public', attempt_id='one', allocation=stage.reservation)
        self.assertEqual(result['status'],'completed',result)
        self.assertTrue(result['result'].primitive_valid,result['result'].value)
        self.assertFalse(service.replay(result['execution']).value['admission']['consequential_use'])
        # Claim/evidence packets must satisfy the same real receipt rules too.
        batch, request = request_for(base, specs[1], service, 'claim')
        result = service.run(request, executor=h.executor(batch,h.response(batch,{'evidence.support':'0.5'})),
            token=stage.token, logical_request_id='claim', attempt_id='one', allocation=stage.reservation)
        self.assertEqual(result['status'],'completed',result)
        self.assertTrue(result['result'].primitive_valid,result['result'].value)

        provider = component('family-fixture-provider'); audience = self.a.audience_ref
        public = _public_refs(compared.value['dependencies'])
        policy = HostAccessPolicy(scope_id=self.f.storage.scope_id, audiences=[audience],
            providers=[{'reference':provider,'provider':'synthetic','transport':'fixture'}],
            grants=[{'reference':ref,'audiences':[audience],'providers':[provider]} for ref in public])
        reader = SQLiteStore(self.f.database,scope_id=self.f.storage.scope_id); self.addCleanup(reader.close)
        access = AccessService(policy=policy,controls=self.f.controls,current_read=reader.snapshot)
        with self.f.storage.snapshot() as view:
            context = access.capture(view,token=stage.token,audience=audience,provider=provider,references=public)
        protected_base = h.packet(self.f.storage,self.f.payloads,self.adapter,
            {'kind':'claim','claim':pin(claim)},[source],access=access,access_context=context)
        with self.f.storage.snapshot() as view:
            protected = prepare_comparison(view,protected_base,cause='new_evidence',after=pin(assessment),
                condition=pin(claim),purpose=pin(self.a.purpose),audience=pin(self.a.audience),access=access,access_context=context)
            options={'access':access,'access_context':context,'access_view':view}
            rendered = render_questions([specs[0]],protected,prefix='protected',**options)
        protected_service = ExecutionReceiptStore(self.f.storage,payloads=self.f.payloads,controls=self.f.controls,
            questions=stage.questions,budgets=stage.budgets,clock=lambda:self.f.now,access=access)
        # Rendering uses a current read view; the request/run open their own snapshots.
        value=batch.value; value.update(id='protected',state=protected.state,packet_digest=protected.digest,
            questions=[item.question.value for item in rendered])
        protected_batch=Batch(value)
        protected_request=protected_service.request(protected_batch,packet=protected,rendered_questions=rendered,
            token=stage.token,access_context=context)
        def guarded(**args):
            with self.f.storage.snapshot() as view:
                return access.dispatch(view,context,args['batch'],args['executor'],
                    rendered_questions=[RenderedQuestion(item,_factory=True) for item in args['stage_input']['rendered_questions']],
                    clock=args['clock'],precision=args['precision'])
        result=protected_service.run(protected_request,executor=h.executor(protected_batch,h.response(protected_batch,{'recovery.matching':'0.5'})),
            token=stage.token,logical_request_id='protected',attempt_id='one',allocation=stage.reservation,
            access_context=context,dispatch=guarded)
        self.assertEqual(result['status'],'completed',result)
        self.assertTrue(result['result'].primitive_valid,result['result'].value)
        self.assertFalse(protected_service.replay(result['execution']).value['admission']['consequential_use'])

    def test_original_cut_survives_later_matter_metadata_revision(self):
        assessment, claim, source, _ = self.a.assess('historical-subject')
        with self.f.storage.snapshot() as view:
            cut = view.receipt_for(pin(assessment))['provenance']['recorded_at']
        original = self.packet(claim,[source],boundary=cut)
        comparison = self.compare(original,claim,assessment)
        matters = MatterService(self.f.storage,identity_policy=identity_policy())
        command = metadata_command('after-cut-metadata',self.f.subject,{'title':'Later synthetic wording'})
        changed = matters.update_metadata(matters.prepare(command))
        self.assertEqual(changed['status'],'success',changed)
        later = self.f.storage.get(entity_ref(self.f.subject))
        self.assertNotEqual(pin(later),pin(self.f.subject))
        rebuilt = self.packet(claim,[source],boundary=cut)
        self.assertEqual(rebuilt.value,original.value)
        self.assertEqual(self.compare(rebuilt,claim,assessment).value,comparison.value)
        self.assertNotIn(pin(later),rebuilt.value['dependencies'])


if __name__ == '__main__': unittest.main()
