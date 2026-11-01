"""MAT-088/089 behavioral checks: real SQLite/control/access, synthetic host.

No StateCivics ORM, model, MCP tool, external send or provider qualification.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
import unittest
import sqlite3
from unittest.mock import patch

from matter.access import AccessService, HostAccessPolicy
from matter.assistant_review import (AssistantReviewService, ReviewHost, ReviewRequest, ReviewResult,
    host_artifact_reference, pressure_contribution, pressure_ref, review_ledger_digest)
from matter.canonical import canonical_bytes
from matter.contracts import ContractError
from matter.controls import ControlService
from matter.storage import SQLiteStore, entity_ref, pin
from rule_helpers import component


def message(kind, **value):
    return {"contract_version": "1.0", "message_type": kind, **value}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        from integration.test_assessment_commit import AssessmentCommitTests
        self.f = AssessmentCommitTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.now = {"state": "known", "value": "2050-01-01T00:00:00Z", "precision": "second"}
        self.lens = {"host": "synthetic-host", "user_id": "7", "workspace_id": "8", "client_id": "client-a",
                     "intent_id": "objective-a", "revision_id": "approved-1"}
        self.audience, self.provider = component('review-audience'), component('review-provider')
        self.other_audience = component('review-audience-b')
        self.native = [pin(self.f.subject), pin(self.f.source)]
        self.access = AccessService(policy=HostAccessPolicy(scope_id=self.f.storage.scope_id,
            audiences=[self.audience,self.other_audience], providers=[{"reference": self.provider, "provider": "synthetic", "transport": "fixture"}],
            grants=[{"reference": r, "audiences": [self.audience,self.other_audience], "providers": [self.provider]} for r in self.native]),
            controls=self.f.controls, current_read=self.f.storage.snapshot)
        self.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
            capability='assessment', targets=[entity_ref(r) for r in self.native])
        with self.f.storage.snapshot() as view:
            self.access_context = self.access.capture(view, token=self.token, audience=self.audience,
                provider=self.provider, references=self.native)
        self.artifacts, self.denied, self.stale = {}, set(), set()
        self.active, self.calls, self.serial, self.on_resolve = True, 0, 0, None
        self.host = ReviewHost(binding=self.lens['host'], require_current=self.current, require_read=self.read, resolve=self.read_artifact)
        self.service = self.make_service()
        self.source = self.artifact('evidence', 'source-1', 'source_quote', {'text': 'SYNTHETIC SOURCE BODY'})
        self.assessment = self.artifact('judgment', 'assessment-1', 'jev_judgment', {'judgment': 'unqualified'}, citations=[self.source])
        self.control = self.artifact('control', 'control-1', 'host_control', {'latest_control':'activated'})
        self.request = self.req()

    def make_service(self, storage=None, controls=None, access=None):
        return AssistantReviewService(storage or self.f.storage, controls=controls or self.f.controls,
            access=access or self.access, host=self.host, clock=lambda: deepcopy(self.f.now))

    def current(self, request, references, at):
        self.read(request, references, at)
        if (not self.active or request['lens'] != self.lens or request['matter'] != pin(self.f.subject)
                or request['host_control'] != self.control or request['audience'] != self.audience or request['provider'] != self.provider
                or any(canonical_bytes(r) in self.stale for r in references)):
            raise ContractError('E_DEPENDENCY_STALE')

    def read(self, request, references, at):
        if (request['lens']['host'] != self.lens['host'] or request['lens']['user_id'] != self.lens['user_id']
                or request['lens']['client_id'] != self.lens['client_id']
                or request['lens']['intent_id'] != self.lens['intent_id']
                or any(canonical_bytes(r) in self.denied for r in references)):
            raise ContractError('E_AUTHORITY_REQUIRED')

    def read_artifact(self, lens, reference, at):
        if self.on_resolve:
            self.on_resolve(reference)
        return deepcopy(self.artifacts[canonical_bytes(reference)])

    def artifact(self, kind, identity, classification, content, *, citations=(), parents=(), lens=None, at=None):
        reference = {'host': self.lens['host'], 'kind': kind, 'id': identity, 'digest': '0'*64}
        value = message('host_artifact', reference=reference, lens=deepcopy(lens or self.lens),
            available_at=deepcopy(at or self.f.now), classification=classification,
            citations=list(citations), derived_from=list(parents),
            communication_state="actually_conveyed" if classification == "communication" else None, content=content)
        reference = host_artifact_reference(value)
        value['reference'] = reference
        self.artifacts[canonical_bytes(reference)] = value
        return deepcopy(reference)

    def req(self, *, contributions=None, ledger=None, **updates):
        value = message('review_request', lens=deepcopy(self.lens), matter=pin(self.f.subject),
            dependencies=[pin(self.f.source)], audience=self.audience, provider=self.provider,
            host_control=self.control, assessment=self.assessment, contributions=contributions or [{'reference': self.source, 'lineage': 'source-lineage-1'}],
            ledger=ledger, trigger_routes=['immediate'], reason_code='adverse_development', as_of=deepcopy(self.f.now),
            limits={'max_tool_calls': 12, 'timeout_ms': 180000, 'max_reads': 128, 'max_bytes': 262144, 'cost_policy':'host_managed'})
        value.update(updates)
        value['contributions'] = [pressure_contribution(self.artifacts[canonical_bytes(c['reference'])], lineage=c['lineage'], material_version=c.get('material_version',c['reference']['id'])) for c in value['contributions']]
        return ReviewRequest(value)

    def ledger(self, **entries):
        return message('ledger', lens=deepcopy(self.lens), as_of=deepcopy(self.f.now),
                       **{key: list(entries.get(key, [])) for key in ('judgments', 'reviews', 'conveyed', 'feedback', 'findings')})

    def add(self, request=None):
        self.serial += 1
        return self.service.record_pressure(request or self.request, token=self.token,
            access_context=self.access_context, command_id='review-pressure-'+str(self.serial))

    def result(self, request=None, *, status='completed', proposal='quiet', reviewed=None, ledger=None, rules=()):
        request = request or self.request
        reviewed = ([c['reference'] for c in request.value['contributions']] if reviewed is None else reviewed)
        if status != 'completed':
            return message('review_result', wake_id=request.wake_id, status=status, proposal=None, review=None, session=None,
                reviewed=[], ledger=None, rule_changes=[], error_code='stopped_for_test')
        session = self.artifact('session', 'session-a', 'session', {})
        identity={'host':self.lens['host'],'kind':'review','id':'review-'+request.wake_id,'digest':'0'*64}
        content = {'wake_id': request.wake_id, 'status': status, 'proposal': proposal, 'reviewed': reviewed, 'rule_changes': list(rules),
                   'session':session,'ledger_binding':review_ledger_digest(ledger,identity)}
        review = self.artifact('review', 'review-'+request.wake_id, 'review', content)
        return message('review_result', wake_id=request.wake_id, status=status, proposal=proposal, review=review, session=session,
                       reviewed=reviewed, ledger=ledger, rule_changes=list(rules), error_code=None)

    def execute(self, request=None, reviewer=None):
        def callback(value, wake_id):
            self.calls += 1
            return self.result(ReviewRequest(value))
        return self.service.execute(request or self.request, token=self.token,
            access_context=self.access_context, reviewer=reviewer or callback)

    def pending(self, request=None):
        return self.service.pressure(request or self.request, token=self.token, access_context=self.access_context)['pending']

    def test_both_completed_proposals_clear_only_reviewed_pressure_without_delivery(self):
        for proposal in ('quiet', 'alert'):
            with self.subTest(proposal=proposal):
                request = self.req(reason_code=proposal)
                # Separate material is needed for a genuinely new wake, not a new reason or quota.
                if proposal == 'alert':
                    source = self.artifact('evidence', 'source-alert', 'source_fact', {'new': 'deadline'})
                    request = self.req(contributions=[{'reference': source, 'lineage': 'alert'}])
                before_matter = self.f.storage.get(pin(self.f.subject))
                added = self.add(request)
                completed = self.execute(request, reviewer=lambda value, key: self.result(request, proposal=proposal))
                self.assertEqual(completed['value']['value']['phase'], 'completed')
                self.assertEqual(self.pending(request), [])
                self.assertEqual(self.f.storage.get(pin(self.f.subject)), before_matter)
                self.assertEqual(self.f.storage.get(pin(added)), added)  # reset retains the association/history
                self.assertNotIn('delivery', completed['value']['value'])

    def test_duplicate_routes_time_and_limits_do_not_rerun_after_restart(self):
        self.add()
        first = self.execute()
        other = self.request.value
        other.update(trigger_routes=['immediate', 'accumulation'], reason_code='combined_context')
        other['limits']['max_tool_calls'] = 24
        self.assertEqual(ReviewRequest(other).wake_id, self.request.wake_id)
        store = SQLiteStore(self.f.database, scope_id=self.f.storage.scope_id)
        self.addCleanup(store.close)
        controls = ControlService(store, policy=self.f.controls.policy, clock=lambda: deepcopy(self.f.now))
        access = AccessService(policy=self.access.policy, controls=controls, current_read=store.snapshot)
        self.service = self.make_service(store, controls, access)
        second = self.execute(ReviewRequest(other))
        self.assertEqual(first, second)
        self.assertEqual(self.calls, 1)

    def test_claimed_crash_and_provider_exception_remain_unknown_never_retried(self):
        self.add()
        acquired, row = self.service.claim(self.request, token=self.token, access_context=self.access_context)
        self.assertTrue(acquired)
        self.assertEqual(self.execute()['value']['value']['phase'], 'started')
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.pending(), self.request.value['contributions'])
        with self.assertRaises(ContractError):
            extra = self.artifact('evidence', 'while-unknown', 'source_fact', {'new':'change'})
            newer = self.req(contributions=[{'reference':extra,'lineage':'while-unknown'}])
            self.add(newer); self.execute(newer)

    def test_provider_exception_is_unknown_and_never_retried(self):
        self.add()
        # A failed transport may have reached the host; it is unknown and no new claim is allowed.
        source = self.artifact('evidence', 'another', 'source_fact', {'new': 'change'})
        request = self.req(contributions=[{'reference': source, 'lineage': 'another'}])
        self.add(request)
        def failing(value, key):
            raise RuntimeError('SECRET MUST NOT ENTER JOURNAL')
        result = self.execute(request, reviewer=failing)
        self.assertEqual(result['value']['value']['phase'], 'unknown')
        self.assertEqual(self.execute(request)['value']['value']['phase'], 'unknown')
        self.assertNotIn('SECRET', str(result))

    def test_stopped_and_failed_never_clear_pressure_or_accept_quiet(self):
        for status in ('stopped', 'failed', 'unknown'):
            with self.subTest(status=status):
                source = self.artifact('evidence', status, 'source_fact', {'case': status})
                request = self.req(contributions=[{'reference': source, 'lineage': status}])
                self.add(request)
                row = self.execute(request, reviewer=lambda value, key: self.result(request, status=status))
                self.assertEqual(row['value']['value']['phase'], status)
                self.assertIn(request.value['contributions'][0], self.pending(request))
        invalid = self.result(status='failed'); invalid['proposal'] = 'quiet'
        with self.assertRaises(ContractError):
            ReviewResult(invalid)

    def test_new_arrival_and_correction_during_review_survive_old_completion(self):
        self.add()
        old = self.request
        newer = self.artifact('evidence', 'corrected', 'source_fact', {'new': 'correction'}, parents=[self.source])
        arrival = self.artifact('evidence', 'new-arrival', 'source_quote', {'new': 'deadline'})
        request = self.req(contributions=[{'reference': newer, 'lineage': 'source-lineage-1'},
                                         {'reference': arrival, 'lineage': 'new-arrival'}])
        def reviewer(value, key):
            self.add(request)
            return self.result(old)
        row = self.execute(reviewer=reviewer)
        self.assertEqual(row['value']['value']['phase'], 'completed')
        self.assertEqual(self.pending(request), sorted(request.value['contributions'], key=canonical_bytes))
        self.add(request)  # control lineage still permits a future pressure update after reset
        self.assertNotEqual(request.wake_id, old.wake_id)
        self.assertEqual(self.execute(request)['value']['value']['phase'], 'completed')

    def test_host_pause_or_edit_during_call_preserves_pressure(self):
        self.add()
        def reviewer(value, key):
            result = self.result()
            self.active = False
            return result
        row = self.execute(reviewer=reviewer)
        self.assertEqual(row['value']['value']['phase'], 'stopped')
        self.assertIsNone(row['value']['value']['result']['proposal'])
        self.active = True
        self.assertEqual(self.pending(), self.request.value['contributions'])

    def test_ledger_resolves_all_four_inputs_and_derived_context_without_body_copies(self):
        finding = self.artifact('finding', 'finding', 'interpretation', {'text': 'PRIVATE FINDING BODY'}, citations=[self.source])
        feedback = self.artifact('feedback', 'feedback', 'user_feedback', {'handled': True})
        conveyed = self.artifact('conveyed', 'actual-output', 'communication', {'status': 'actually_conveyed'})
        result = self.result()
        ledger = self.ledger(judgments=[self.assessment], reviews=[result['review']], conveyed=[conveyed],
                             feedback=[feedback], findings=[finding])
        request = self.req(ledger=ledger)
        self.add(request)
        resolved = self.service.resolve_ledger(request, token=self.token, access_context=self.access_context)
        self.assertEqual({a['reference']['kind'] for a in resolved}, {'judgment','review','conveyed','feedback','finding','evidence'})
        self.assertEqual(next(a for a in resolved if a['reference']==finding)['classification'], 'interpretation')
        stored = self.f.storage.get(pressure_ref(self.f.storage.scope_id, request))
        self.assertNotIn('PRIVATE FINDING BODY', str(stored))
        self.assertNotIn('SYNTHETIC SOURCE BODY', str(stored))
        self.assertEqual(stored['value']['value']['ledger'], ledger)
        self.assertEqual(len([a for a in resolved if a['reference']==self.source]), 1)

    def test_foreign_lens_stale_digest_future_evidence_and_revoked_ancestor_refuse(self):
        changed = self.request.value; changed['lens']['client_id'] = 'client-b'
        with self.assertRaises(ContractError):
            self.add(ReviewRequest(changed))
        original = self.artifacts[canonical_bytes(self.source)]['content']
        self.artifacts[canonical_bytes(self.source)]['content'] = {'forged': 'content'}
        with self.assertRaises(ContractError): self.add()
        self.artifacts[canonical_bytes(self.source)]['content'] = original
        future = {**self.f.now, 'value': '2050-01-02T00:00:00Z'}
        source = self.artifact('evidence', 'future', 'source_fact', {'text': 'future'}, at=future)
        with self.assertRaises(ContractError): self.add(self.req(contributions=[{'reference':source,'lineage':'future'}]))
        finding = self.artifact('finding', 'derived', 'interpretation', {'text':'note'}, citations=[self.source])
        request = self.req(ledger=self.ledger(findings=[finding]))
        self.denied.add(canonical_bytes(self.source))
        with self.assertRaises(ContractError):
            self.service.resolve_ledger(request, token=self.token, access_context=self.access_context)

    def test_reprints_share_one_lineage_and_old_versions_remain_in_history(self):
        first = self.add()
        reprint = self.artifact('evidence', 'reprint', 'source_quote', {'text':'SYNTHETIC SOURCE BODY'}, parents=[self.source])
        request = self.req(contributions=[{'reference':reprint,'lineage':'source-lineage-1','material_version':'source-1'}])
        self.add(request)
        self.assertEqual(len(self.pending(request)), 1)
        self.assertEqual(self.f.storage.get(pin(first)), first)
        bad = request.value; bad['contributions'].append({**bad['contributions'][0],'reference':self.source})
        with self.assertRaises(ContractError): ReviewRequest(bad)

    def test_completion_must_match_persisted_host_review_and_exact_reviewed_set(self):
        self.add()
        self.service.claim(self.request, token=self.token, access_context=self.access_context)
        result = self.result()
        result['proposal'] = 'alert'  # contradicts the persisted host review
        with self.assertRaises(ContractError):
            self.service.complete(self.request, result, token=self.token, access_context=self.access_context)
        result = self.result()
        alien = self.artifact('evidence', 'not-reviewed', 'source_fact', {'text':'other'})
        result['reviewed'].append(alien)
        with self.assertRaises(ContractError):
            self.service.complete(self.request, result, token=self.token, access_context=self.access_context)
        self.assertEqual(self.pending(), self.request.value['contributions'])


    def test_completed_material_cannot_reinflate_pressure_or_restart_with_a_new_wrapper(self):
        self.add(); self.execute()
        # Exact old material and a different source wrapper with identical material are both covered.
        self.add()
        self.assertEqual(self.pending(), [])
        source = self.artifact('evidence', 'same-source-reprinted', 'source_quote', {'text': 'SYNTHETIC SOURCE BODY'}, parents=[self.source])
        request = self.req(contributions=[{'reference': source, 'lineage': 'source-lineage-1','material_version':'source-1'}])
        self.add(request)
        self.assertEqual(self.pending(request), [])
        with self.assertRaises(ContractError): self.execute(request)
        self.assertEqual(self.calls, 1)

    def test_exact_completion_and_pressure_retries_do_not_touch_new_arrivals(self):
        self.add()
        self.service.record_pressure(self.request, token=self.token, access_context=self.access_context, command_id='review-pressure-1')
        self.service.claim(self.request, token=self.token, access_context=self.access_context)
        result = self.result()
        first = self.service.complete(self.request, result, token=self.token, access_context=self.access_context)
        new = self.artifact('evidence', 'new', 'source_fact', {'new': 'new deadline'})
        request = self.req(contributions=[{'reference': new, 'lineage': 'new'}]); self.add(request)
        again = self.service.complete(self.request, result, token=self.token, access_context=self.access_context)
        self.assertEqual(first, again)
        self.assertEqual(self.pending(request), request.value['contributions'])

    def test_two_real_sqlite_handles_cannot_launch_the_same_wake_twice(self):
        self.add()
        store = SQLiteStore(self.f.database, scope_id=self.f.storage.scope_id)
        self.addCleanup(store.close)
        controls = ControlService(store, policy=self.f.controls.policy, clock=lambda: deepcopy(self.f.now))
        access = AccessService(policy=self.access.policy, controls=controls, current_read=store.snapshot)
        other = self.make_service(store, controls, access)
        barrier = Barrier(2)
        for service in (self.service, other):
            original = service._action
            def gated(action, request, _original=original, **kwargs):
                if action == 'start': barrier.wait(timeout=10)
                return _original(action, request, **kwargs)
            service._action = gated
        def run(service):
            try:
                return service.execute(self.request, token=self.token, access_context=self.access_context,
                    reviewer=lambda value, key: self.counted_result())
            except ContractError as error:
                return error.code  # a losing stale preparation must fail closed, never call the assistant
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(run, (self.service, other)))
        self.assertEqual(self.calls, 1, rows)
        self.assertTrue(any(isinstance(row, dict) and row['value']['value']['phase']=='completed' for row in rows), rows)

    def counted_result(self):
        self.calls += 1
        return self.result()

    def test_native_control_revocation_in_flight_prevents_reset(self):
        from control_helpers import control_command
        from integration.helpers import _in_scope
        self.add()
        def reviewer(value, key):
            result = self.result()
            command = _in_scope(control_command('revoke-review', self.f.authority, targets=[self.f.source],
                action='deny', capabilities=['assessment'], now=self.f.now), self.f.storage.scope_id)
            command['actor'] = self.f.actor
            command['body']['control']['body']['actor'] = self.f.actor
            applied = self.f.controls.apply(self.f.controls.prepare(command))
            self.assertEqual(applied['status'], 'success', applied)
            return result
        row = self.execute(reviewer=reviewer)
        self.assertEqual(row['value']['value']['phase'], 'stale')
        pending = self.f.storage.get(pressure_ref(self.f.storage.scope_id, self.request))['value']['value']['pending']
        self.assertEqual(pending, self.request.value['contributions'])

    def test_resolver_rechecks_access_after_read_and_inspection_exposes_unknown_honestly(self):
        self.add()
        self.service.claim(self.request, token=self.token, access_context=self.access_context)
        state = self.service.inspect(self.request, actor=self.f.actor, authority=entity_ref(self.f.authority), access_context=self.access_context)
        self.assertTrue(state['outcome_unknown']); self.assertFalse(state['human_communicated'])
        self.on_resolve = lambda ref: self.denied.add(canonical_bytes(ref))
        with self.assertRaises(ContractError):
            self.service.resolve(self.request, [self.source], token=self.token, access_context=self.access_context)

    def test_foreign_and_changed_host_metadata_never_enter_matter(self):
        finding = self.artifact('finding', 'private', 'interpretation', {'text': 'PRIVATE_LEDGER_BODY_NEVER_IN_SQLITE'}, citations=[self.source])
        request = self.req(ledger=self.ledger(findings=[finding]))
        self.add(request); self.execute(request)
        with sqlite3.connect(self.f.database) as db:
            dump = '\n'.join(db.iterdump())
        self.assertNotIn('PRIVATE_LEDGER_BODY_NEVER_IN_SQLITE', dump)
        self.assertNotIn('SYNTHETIC SOURCE BODY', dump)
        rows = self.service.history(request, actor=self.f.actor, authority=entity_ref(self.f.authority), access_context=self.access_context)
        self.assertTrue(any(row['value']['value']['pending'] for row in rows))
        self.denied.add(canonical_bytes(self.source))
        with self.assertRaises(ContractError):
            self.service.history(request, actor=self.f.actor, authority=entity_ref(self.f.authority), access_context=self.access_context)


    def test_pause_then_resume_during_review_does_not_revive_old_host_control(self):
        self.add()
        def reviewer(value, key):
            result = self.result()
            self.control = self.artifact('control', 'control-3', 'host_control', {'latest_control':'resumed_after_pause'})
            return result
        row = self.execute(reviewer=reviewer)
        self.assertEqual(row['value']['value']['phase'], 'stopped')
        self.assertIsNone(row['value']['value']['result']['proposal'])
        request = self.req()
        self.assertEqual(request.wake_id, self.request.wake_id)  # a control renewal is not new evidence

    def test_unrelated_root_cannot_be_resolved_outside_the_bound_packet(self):
        other = self.artifact('evidence', 'outside-input', 'source_quote', {'text':'unbound source'})
        with self.assertRaises(ContractError):
            self.service.resolve(self.request, [other], token=self.token, access_context=self.access_context)


    def test_output_pointer_revocation_blocks_cached_reply_and_inspection(self):
        self.add(); completed = self.execute()
        review = completed['value']['value']['result']['review']
        self.denied.add(canonical_bytes(review))
        with self.assertRaises(ContractError): self.execute()
        with self.assertRaises(ContractError):
            self.service.inspect(self.request, actor=self.f.actor, authority=entity_ref(self.f.authority), access_context=self.access_context)

    def test_explicit_reader_byte_and_call_limits_refuse_instead_of_truncating(self):
        for name,value in (('max_reads',1),('max_bytes',10)):
            raw=self.request.value;raw['limits'][name]=value
            with self.assertRaises(ContractError):
                request=ReviewRequest(raw)
                self.service.resolve(request, [self.assessment], token=self.token, access_context=self.access_context)
        self.assertEqual(self.calls,0)

    def test_authorized_rule_revision_is_referenced_not_applied_from_model_text(self):
        self.add()
        rule=self.artifact('rule','approved-rule-2','rule',{'approved_control':'host-control-2','from':'v1','to':'v2'})
        row=self.execute(reviewer=lambda value,key:self.result(rules=[rule]))
        self.assertEqual(row['value']['value']['result']['rule_changes'],[rule])
        self.assertNotIn('approved_control',str(row))


    def test_partial_review_clears_only_its_actual_subset(self):
        extra=self.artifact('evidence','unreviewed','source_quote',{'text':'not covered by completed review'})
        request=self.req(contributions=[{'reference':self.source,'lineage':'source-lineage-1'},
                                       {'reference':extra,'lineage':'unreviewed'}])
        self.add(request)
        row=self.execute(request,reviewer=lambda value,key:self.result(request,reviewed=[self.source]))
        self.assertEqual(row['value']['value']['phase'],'completed')
        self.assertEqual([c['reference'] for c in self.pending(request)],[extra])

    def test_two_lenses_share_source_facts_but_not_pressure_or_findings(self):
        self.add()
        original=(deepcopy(self.lens),self.audience,self.source,self.assessment,self.control,self.access_context)
        self.lens={**self.lens,'client_id':'client-b','intent_id':'objective-b'}
        self.audience=self.other_audience
        self.source=self.artifact('evidence','source-1','source_quote',{'text':'SYNTHETIC SOURCE BODY'})
        self.assessment=self.artifact('judgment','assessment-b','jev_judgment',{'judgment':'unqualified'},citations=[self.source])
        self.control=self.artifact('control','control-b','host_control',{'latest_control':'activated'})
        other=self.req()
        with self.assertRaises(ContractError): self.add(other)  # audience A's egress is insufficient
        with self.f.storage.snapshot() as view:
            self.access_context=self.access.capture(view,token=self.token,audience=self.audience,provider=self.provider,references=self.native)
        self.add(other)
        row=self.execute(other,reviewer=lambda value,key:self.result(other,proposal='alert'))
        self.assertEqual(row['value']['value']['result']['proposal'],'alert')
        self.assertEqual(self.pending(other),[])
        self.lens,self.audience,self.source,self.assessment,self.control,self.access_context=original
        self.assertEqual(self.pending(),self.request.value['contributions'])
        row=self.execute()
        self.assertEqual(row['value']['value']['result']['proposal'],'quiet')


    def bump_unrelated_control(self, identity):
        from control_helpers import control_command
        from integration.helpers import _in_scope, projection_ref
        command = _in_scope(control_command(identity,self.f.authority,
            targets=[projection_ref('other-lens',self.f.storage.scope_id)],action='invalidate',now=self.f.now),self.f.storage.scope_id)
        command['actor']=self.f.actor;command['body']['control']['body']['actor']=self.f.actor
        result=self.f.controls.apply(self.f.controls.prepare(command))
        self.assertEqual(result['status'],'success',result)

    def conflict_once(self, prefix):
        original=self.f.storage.execute
        fired=[]
        def execute(command,handler,**kwargs):
            if command['command_id'].startswith(prefix) and not fired:
                fired.append(True)
                self.bump_unrelated_control('unrelated-'+prefix)
            return original(command,handler,**kwargs)
        return patch.object(self.f.storage,'execute',side_effect=execute)

    def test_recorded_pressure_refusal_stays_refused_on_exact_retry(self):
        self.add()
        source=self.artifact('evidence','pending-conflict','source_fact',{'new':'decisive change'})
        request=self.req(contributions=[{'reference':source,'lineage':'conflict'}])
        with self.conflict_once('pressure-conflict'):
            with self.assertRaises(ContractError) as error:
                self.service.record_pressure(request,token=self.token,access_context=self.access_context,command_id='pressure-conflict')
        self.assertEqual(error.exception.code,'E_REVISION_CONFLICT')
        with self.assertRaises(ContractError) as error:
            self.service.record_pressure(request,token=self.token,access_context=self.access_context,command_id='pressure-conflict')
        self.assertEqual(error.exception.code,'E_REVISION_CONFLICT')
        self.assertEqual(self.pending(),self.request.value['contributions'])
        self.service.record_pressure(request,token=self.token,access_context=self.access_context,command_id='pressure-conflict-fresh')
        self.assertIn(request.value['contributions'][0],self.pending(request))

    def test_start_and_finish_conflicts_allow_fresh_local_attempt_without_restarting_host(self):
        self.add()
        with self.conflict_once('assistant-start-'):
            with self.assertRaises(ContractError) as error:
                self.execute()
        self.assertEqual(error.exception.code,'E_REVISION_CONFLICT');self.assertEqual(self.calls,0)
        acquired,_=self.service.claim(self.request,token=self.token,access_context=self.access_context)
        self.assertTrue(acquired)
        self.calls+=1  # the one authorized host review, whose stored result can be retried locally
        result=self.result()
        with self.conflict_once('assistant-finish-'):
            with self.assertRaises(ContractError) as error:
                self.service.complete(self.request,result,token=self.token,access_context=self.access_context)
        self.assertEqual(error.exception.code,'E_REVISION_CONFLICT')
        completed=self.service.complete(self.request,result,token=self.token,access_context=self.access_context)
        self.assertEqual(completed['value']['value']['phase'],'completed');self.assertEqual(self.calls,1)

    def test_overlapping_lens_wakes_wait_for_first_review_instead_of_concurrent_callbacks(self):
        self.add()
        self.service.claim(self.request,token=self.token,access_context=self.access_context)
        new=self.artifact('evidence','new-while-reviewing','source_quote',{'text':'another event'})
        request=self.req(contributions=[{'reference':self.source,'lineage':'source-lineage-1'},{'reference':new,'lineage':'new'}])
        self.add(request)
        with self.assertRaises(ContractError):self.execute(request)
        self.service.complete(self.request,self.result(),token=self.token,access_context=self.access_context)
        pending=self.pending(request)
        self.assertEqual([c['reference'] for c in pending],[new])
        next_request=self.req(contributions=pending)
        self.assertEqual(self.execute(next_request)['value']['value']['phase'],'completed')

    def test_guard_loss_after_provider_exception_preserves_unknown_even_when_stale(self):
        self.add()
        def failing(value,key):
            self.active=False
            raise RuntimeError('may have reached host')
        row=self.execute(reviewer=failing)
        self.assertTrue(row['value']['value']['outcome_unknown'])
        state=self.service.inspect(self.request,actor=self.f.actor,authority=entity_ref(self.f.authority),access_context=self.access_context)
        self.assertTrue(state['outcome_unknown'])
        self.active=True
        self.assertEqual(self.pending(),self.request.value['contributions'])


    def test_explicit_reconciliation_releases_unknown_without_clearing_pressure_or_rerunning(self):
        self.add()
        def failing(value,key):raise RuntimeError('unknown')
        self.execute(reviewer=failing)
        witness=self.artifact('control','operator-reconcile','host_control',{
            'wake_id':self.request.wake_id,'inflight':False,'resolution':'failed'})
        row=self.service.reconcile(self.request,witness,actor=self.f.actor,authority=entity_ref(self.f.authority),
                                   access_context=self.access_context,command_id='reconcile-one')
        self.assertEqual(row['value']['value']['phase'],'reconciled')
        self.assertFalse(row['value']['value']['outcome_unknown'])
        self.assertEqual(self.pending(),self.request.value['contributions'])
        self.assertFalse(self.service.claim(self.request,token=self.token,access_context=self.access_context)[0])
        source=self.artifact('evidence','after-reconcile','source_fact',{'new':'deadline'})
        next_request=self.req(contributions=[{'reference':source,'lineage':'next'}]);self.add(next_request)
        self.assertEqual(self.execute(next_request)['value']['value']['phase'],'completed')

    def test_reconciliation_requires_real_no_inflight_host_witness(self):
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        for inflight in (True,None):
            witness=self.artifact('control','bad-reconcile-'+str(inflight),'host_control',{
                'wake_id':self.request.wake_id,'inflight':inflight,'resolution':'failed'})
            with self.assertRaises(ContractError):
                self.service.reconcile(self.request,witness,actor=self.f.actor,authority=entity_ref(self.f.authority),
                                       access_context=self.access_context,command_id='bad-reconcile')
        self.assertEqual(self.pending(),self.request.value['contributions'])

    def test_late_reprint_cannot_evict_unreviewed_correction_and_reversion_is_new_version(self):
        self.add()
        correction=self.artifact('evidence','corrected-version','source_fact',{'text':'changed'})
        corrected=self.req(contributions=[{'reference':correction,'lineage':'source-lineage-1'}]);self.add(corrected)
        self.add()  # old source arrives after the correction; both remain in the one lineage
        self.assertEqual({c['reference']['id'] for c in self.pending()},{'source-1','corrected-version'})
        full=self.req(contributions=self.pending());self.execute(full)
        reverted=self.artifact('evidence','reverted-version','source_quote',{'text':'SYNTHETIC SOURCE BODY'})
        request=self.req(contributions=[{'reference':reverted,'lineage':'source-lineage-1'}]);self.add(request)
        self.assertEqual([c['reference'] for c in self.pending(request)],[reverted])
        self.assertEqual(self.execute(request)['value']['value']['phase'],'completed')

    def test_result_verification_is_separate_from_assistant_read_budget(self):
        raw=self.request.value;raw['limits']['max_reads']=3
        request=ReviewRequest(raw);self.add(request)
        def reviewer(value,key):
            result=self.result(request)
            old=self.artifacts[canonical_bytes(result['review'])]
            result['review']=self.artifact('review','with-source-parents','review',old['content'],citations=[self.assessment,self.source],parents=[self.control])
            return result
        self.assertEqual(self.execute(request,reviewer=reviewer)['value']['value']['phase'],'completed')

    def test_transient_host_guard_failure_does_not_discard_finished_review(self):
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        result=self.result()
        with patch.object(self.service,'_host_guard',side_effect=RuntimeError('host unavailable')):
            with self.assertRaises(Exception):
                self.service.complete(self.request,result,token=self.token,access_context=self.access_context)
        row=self.service.complete(self.request,result,token=self.token,access_context=self.access_context)
        self.assertEqual(row['value']['value']['phase'],'completed')

    def test_stale_completion_retry_returns_original_terminal_result(self):
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        result=self.result();self.active=False
        first=self.service.complete(self.request,result,token=self.token,access_context=self.access_context)
        again=self.service.complete(self.request,result,token=self.token,access_context=self.access_context)
        self.assertEqual(first,again)

    def test_kind_classification_mismatch_cannot_mint_approved_rule_or_communication(self):
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        wrong=self.artifact('rule','model-proposed','interpretation',{'text':'not a host rule'},citations=[self.source])
        with self.assertRaises(ContractError):
            self.service.complete(self.request,self.result(rules=[wrong]),token=self.token,access_context=self.access_context)

    def test_quiet_review_findings_feed_later_context_without_communication(self):
        self.add()
        finding=self.artifact('finding','quiet-note','interpretation',{'text':'quiet but worth retaining'},citations=[self.source])
        ledger=self.ledger(judgments=[self.assessment],findings=[finding])
        row=self.execute(reviewer=lambda value,key:self.result(ledger=ledger))
        self.assertEqual(row['value']['value']['result']['proposal'],'quiet')
        later=self.artifact('evidence','later-event','source_fact',{'text':'new decision'})
        request=self.req(contributions=[{'reference':later,'lineage':'later'}],ledger=ledger)
        self.add(request)
        context=self.service.resolve_ledger(request,token=self.token,access_context=self.access_context)
        self.assertEqual(next(a for a in context if a['reference']==finding)['classification'],'interpretation')
        self.assertEqual(request.value['ledger']['conveyed'],[])


    def test_reconciliation_retry_is_idempotent_and_new_revision_cannot_bypass_unknown(self):
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        self.lens={**self.lens,'revision_id':'approved-2'}
        source=self.artifact('evidence','new-revision-source','source_fact',{'new':'event'})
        request=self.req(contributions=[{'reference':source,'lineage':'new'}]);self.add(request)
        with self.assertRaises(ContractError):self.execute(request)
        self.lens['revision_id']='approved-1'
        witness=self.artifact('control','reconciled-stop','host_control',{'wake_id':self.request.wake_id,'inflight':False,'resolution':'stopped'})
        first=self.service.reconcile(self.request,witness,actor=self.f.actor,authority=entity_ref(self.f.authority),
            access_context=self.access_context,command_id='reconcile-stop')
        again=self.service.reconcile(self.request,witness,actor=self.f.actor,authority=entity_ref(self.f.authority),
            access_context=self.access_context,command_id='reconcile-stop')
        self.assertEqual(first,again)
        self.denied.add(canonical_bytes(witness))
        with self.assertRaises(ContractError):
            self.service.inspect(self.request,actor=self.f.actor,authority=entity_ref(self.f.authority),access_context=self.access_context)

    def test_multiple_matters_have_separate_pressure_under_one_objective_session_lock(self):
        self.add()
        original=(self.f.subject,self.native,self.token,self.access_context,self.access,self.service)
        from integration.helpers import create_command
        command=create_command('another-matter','another-matter',scope_id=self.f.storage.scope_id)
        outcome=self.f.storage.execute(command,lambda tx:tx.success('created',{'matter':pin(tx.insert(tx.command['body']['matter']))}))
        self.assertEqual(outcome['status'],'success')
        self.f.subject=self.f.storage.get(outcome['body']['matter'])
        self.native=[pin(self.f.subject),pin(self.f.source)]
        self.access=AccessService(policy=HostAccessPolicy(scope_id=self.f.storage.scope_id,audiences=[self.audience],
            providers=[{'reference':self.provider,'provider':'synthetic','transport':'fixture'}],
            grants=[{'reference':r,'audiences':[self.audience],'providers':[self.provider]} for r in self.native]),
            controls=self.f.controls,current_read=self.f.storage.snapshot)
        self.token=self.f.controls.capture(actor=self.f.actor,authority=entity_ref(self.f.authority),capability='assessment',targets=[entity_ref(r) for r in self.native])
        with self.f.storage.snapshot() as view:
            self.access_context=self.access.capture(view,token=self.token,audience=self.audience,provider=self.provider,references=self.native)
        self.service=self.make_service(access=self.access)
        other=self.req();self.add(other)
        self.assertNotEqual(pressure_ref(self.f.storage.scope_id,other),pressure_ref(self.f.storage.scope_id,self.request))
        self.execute(other)
        self.f.subject,self.native,self.token,self.access_context,self.access,self.service=original
        self.assertEqual(self.pending(),self.request.value['contributions'])
        self.assertEqual(self.execute()['value']['value']['phase'],'completed')


    def test_pending_pressure_cap_refuses_explicitly_without_dropping_accepted_versions(self):
        for start in (0,60):
            contributions=[]
            for n in range(start,start+60):
                source=self.artifact('evidence',f'bounded-{n}','source_fact',{'n':n})
                contributions.append({'reference':source,'lineage':f'bounded-{n}'})
            self.add(self.req(contributions=contributions))
        self.assertEqual(len(self.pending()),120)
        extra=[]
        for n in range(120,129):
            source=self.artifact('evidence',f'bounded-{n}','source_fact',{'n':n})
            extra.append({'reference':source,'lineage':f'bounded-{n}'})
        with self.assertRaises(ContractError) as error:self.add(self.req(contributions=extra))
        self.assertEqual(error.exception.code,'E_BUDGET_EXHAUSTED')
        self.assertEqual(len(self.pending()),120)

    def test_stale_pending_pointer_is_readable_as_history_but_not_reusable(self):
        self.add();self.stale.add(canonical_bytes(self.source))
        self.assertEqual(self.pending(),self.request.value['contributions'])
        with self.assertRaises(ContractError):self.execute()

    def test_reconciliation_needs_correction_authority_not_just_read_access(self):
        from matter.authority import AuthorityPolicy,CAPABILITIES
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        restricted=ControlService(self.f.storage,policy=AuthorityPolicy(self.f.storage.scope_id,
            actors=[self.f.actor],authorities=[pin(self.f.authority)],capabilities=CAPABILITIES,control_kinds=['decision']),
            clock=lambda:deepcopy(self.f.now))
        access=AccessService(policy=self.access.policy,controls=restricted,current_read=self.f.storage.snapshot)
        service=self.make_service(controls=restricted,access=access)
        witness=self.artifact('control','privileged-reconcile','host_control',{'wake_id':self.request.wake_id,'inflight':False,'resolution':'failed'})
        with self.assertRaises(ContractError):
            service.reconcile(self.request,witness,actor=self.f.actor,authority=entity_ref(self.f.authority),
                              access_context=self.access_context,command_id='not-authorized-reconcile')
        self.assertTrue(self.service.inspect(self.request,actor=self.f.actor,authority=entity_ref(self.f.authority),
                                            access_context=self.access_context)['outcome_unknown'])


    def test_pre_dispatch_guard_refusal_is_known_not_called_not_transport_unknown(self):
        self.add();claim=self.service.claim
        def paused(*args,**kwargs):
            result=claim(*args,**kwargs);self.active=False;return result
        with patch.object(self.service,'claim',side_effect=paused):row=self.execute()
        self.assertEqual(self.calls,0);self.assertFalse(row['value']['value']['outcome_unknown'])
        self.assertEqual(row['value']['value']['phase'],'stopped')

    def test_completion_binds_the_exact_session_and_ledger_selection(self):
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        result=self.result();result['session']=self.artifact('session','other-session','session',{})
        with self.assertRaises(ContractError):
            self.service.complete(self.request,result,token=self.token,access_context=self.access_context)
        result=self.result();result['ledger']=self.ledger()
        with self.assertRaises(ContractError):
            self.service.complete(self.request,result,token=self.token,access_context=self.access_context)


    def revise_native_matter(self):
        from matter_helpers import metadata_command
        old=self.f.subject
        command=metadata_command('revise-native-matter',old,{'title':'Updated native metadata'})
        command['actor']=self.f.actor;command['authority']=entity_ref(self.f.authority)
        result=self.f.matters.update_metadata(self.f.matters.prepare(command))
        self.assertEqual(result['status'],'success',result)
        self.f.subject=self.f.storage.get(result['body']['matter'])
        return old

    def test_reconcile_under_native_cancellation_does_not_resume_monitoring(self):
        from control_helpers import control_command
        from integration.helpers import _in_scope
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        command=_in_scope(control_command('cancel-during-review',self.f.authority,
            targets=[self.f.source],action='cancel',now=self.f.now),self.f.storage.scope_id)
        command['actor']=self.f.actor;command['body']['control']['body']['actor']=self.f.actor
        applied=self.f.controls.apply(self.f.controls.prepare(command));self.assertEqual(applied['status'],'success')
        witness=self.artifact('control','cancelled-reconcile','host_control',{'wake_id':self.request.wake_id,'inflight':False,'resolution':'stopped'})
        row=self.service.reconcile(self.request,witness,actor=self.f.actor,authority=entity_ref(self.f.authority),
            access_context=self.access_context,command_id='reconcile-cancelled')
        self.assertEqual(row['value']['value']['phase'],'reconciled')
        self.assertEqual(self.pending(),self.request.value['contributions'])
        with self.assertRaises(ContractError):self.f.controls.check(self.token)

    def test_reconcile_survives_a_revised_native_pin_without_renewing_work(self):
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        old=self.revise_native_matter()
        self.assertNotEqual(pin(old),pin(self.f.subject))
        witness=self.artifact('control','revised-matter-reconcile','host_control',{'wake_id':self.request.wake_id,'inflight':False,'resolution':'stopped'})
        row=self.service.reconcile(self.request,witness,actor=self.f.actor,authority=entity_ref(self.f.authority),
            access_context=self.access_context,command_id='reconcile-revised-native')
        self.assertEqual(row['value']['value']['phase'],'reconciled')
        self.assertEqual(self.f.storage.get(pin(old)),old)

    def test_consumed_material_version_cannot_be_rewritten_with_contradictory_content(self):
        self.add();self.execute()
        contradictory=self.artifact('evidence','rewritten-source','source_fact',{'text':'contradictory bytes'})
        request=self.req(contributions=[{'reference':contradictory,'lineage':'source-lineage-1','material_version':'source-1'}])
        with self.assertRaises(ContractError) as error:self.add(request)
        self.assertEqual(error.exception.code,'E_SOURCE_IDENTITY_CONFLICT')
        self.assertEqual(self.pending(),[])

    def test_metadata_history_spans_native_revisions_with_present_snapshot_grants(self):
        self.add();old=self.revise_native_matter()
        self.native=[pin(self.f.subject),pin(self.f.source)]
        self.access=AccessService(policy=HostAccessPolicy(scope_id=self.f.storage.scope_id,
            audiences=[self.audience],providers=[{'reference':self.provider,'provider':'synthetic','transport':'fixture'}],
            grants=[{'reference':r,'audiences':[self.audience],'providers':[self.provider]} for r in [pin(old),*self.native]]),
            controls=self.f.controls,current_read=self.f.storage.snapshot)
        self.token=self.f.controls.capture(actor=self.f.actor,authority=entity_ref(self.f.authority),
            capability='assessment',targets=[entity_ref(r) for r in self.native])
        with self.f.storage.snapshot() as view:
            self.access_context=self.access.capture(view,token=self.token,audience=self.audience,provider=self.provider,references=self.native)
        self.service=self.make_service(access=self.access)
        request=self.req()
        # Reading old pointer metadata is allowed before a new pressure write.
        self.assertEqual(self.pending(request),self.request.value['contributions'])
        self.add(request)
        rows=self.service.history(request,actor=self.f.actor,authority=entity_ref(self.f.authority),access_context=self.access_context)
        self.assertEqual({row['value']['value']['matter']['revision'] for row in rows},{old['revision'],self.f.subject['revision']})

    def test_pressure_metadata_never_rereads_the_accepted_host_bodies(self):
        self.add()
        def unavailable(*args):raise RuntimeError('artifact bytes unavailable')
        host=ReviewHost(binding=self.host.binding,require_current=self.current,require_read=self.read,resolve=unavailable)
        service=AssistantReviewService(self.f.storage,controls=self.f.controls,access=self.access,host=host,clock=lambda:deepcopy(self.f.now))
        pending=service.pressure(self.request,token=self.token,access_context=self.access_context)['pending']
        self.assertEqual(pending,self.request.value['contributions'])
        with self.assertRaises(ContractError):service.resolve(self.request,[self.source],token=self.token,access_context=self.access_context)


    def test_history_uses_reader_grants_not_the_writer_for_omitted_dependencies(self):
        self.add()
        policy=HostAccessPolicy(scope_id=self.f.storage.scope_id,
            audiences=[self.audience,self.other_audience],
            providers=[{'reference':self.provider,'provider':'synthetic','transport':'fixture'}],
            grants=[{'reference':pin(self.f.subject),'audiences':[self.audience,self.other_audience],'providers':[self.provider]},
                    {'reference':pin(self.f.source),'audiences':[self.audience],'providers':[self.provider]}])
        access=AccessService(policy=policy,controls=self.f.controls,current_read=self.f.storage.snapshot)
        service=self.make_service(access=access)
        request=self.req(audience=self.other_audience,dependencies=[])
        context=service.history_context(request,actor=self.f.actor,authority=entity_ref(self.f.authority),audience=self.other_audience)
        for read in (lambda:service.pressure(request,token=context.value['token'],access_context=context),
                     lambda:service.history(request,actor=self.f.actor,authority=entity_ref(self.f.authority),access_context=context)):
            with self.subTest(read=read):
                with self.assertRaises(ContractError) as error:read()
                self.assertEqual(error.exception.code,'E_AUTHORITY_REQUIRED')

    def test_current_operator_can_reconcile_and_read_after_worker_provider_rotation_cancel_and_revision(self):
        from matter.authority import AuthorityPolicy,CAPABILITIES,CONTROL_KINDS
        from control_helpers import control_command
        from integration.helpers import _in_scope
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        old=self.revise_native_matter()
        command=_in_scope(control_command('cancel-before-operator-recovery',self.f.authority,
            targets=[self.f.source],action='cancel',now=self.f.now),self.f.storage.scope_id)
        command['actor']=self.f.actor;command['body']['control']['body']['actor']=self.f.actor
        self.assertEqual(self.f.controls.apply(self.f.controls.prepare(command))['status'],'success')
        operator={**self.f.actor,'id':'current-review-operator'}
        provider=component('retired-provider-replacement')
        controls=ControlService(self.f.storage,policy=AuthorityPolicy(self.f.storage.scope_id,
            actors=[operator],authorities=[pin(self.f.authority)],capabilities=CAPABILITIES,control_kinds=CONTROL_KINDS),
            clock=lambda:deepcopy(self.f.now))
        access=AccessService(policy=HostAccessPolicy(scope_id=self.f.storage.scope_id,
            audiences=[self.other_audience],providers=[{'reference':provider,'provider':'synthetic','transport':'fixture'}],
            grants=[{'reference':r,'audiences':[self.other_audience],'providers':[provider]} for r in [pin(old),pin(self.f.source)]]),
            controls=controls,current_read=self.f.storage.snapshot)
        service=self.make_service(controls=controls,access=access)
        context=service.history_context(self.request,actor=operator,authority=entity_ref(self.f.authority),audience=self.other_audience)
        self.assertIsNone(context.value['provider'])
        self.assertEqual(context.value['token']['capability'],'read')
        witness=self.artifact('control','rotated-operator-proof','host_control',{'wake_id':self.request.wake_id,'inflight':False,'resolution':'failed'})
        row=service.reconcile(self.request,witness,actor=operator,authority=entity_ref(self.f.authority),
            access_context=context,command_id='rotated-operator-reconcile')
        self.assertEqual(row['value']['value']['phase'],'reconciled')
        self.assertEqual(service.pressure(self.request,token=context.value['token'],access_context=context)['pending'],self.request.value['contributions'])
        self.assertTrue(service.history(self.request,actor=operator,authority=entity_ref(self.f.authority),access_context=context))
        self.assertEqual(self.calls,0)
        with self.assertRaises(ContractError):
            controls.capture(actor=operator,authority=entity_ref(self.f.authority),capability='assessment',targets=[entity_ref(r) for r in self.native])

    def test_metadata_reader_cannot_borrow_another_actors_context(self):
        self.add()
        actor={**self.f.actor,'id':'different-operator'}
        with self.assertRaises(ContractError) as error:
            self.service.history(self.request,actor=actor,authority=entity_ref(self.f.authority),access_context=self.access_context)
        self.assertEqual(error.exception.code,'E_AUTHORITY_REQUIRED')

    def test_reconciliation_requires_correction_capability_not_only_control_kind(self):
        from matter.authority import AuthorityPolicy,CAPABILITIES,CONTROL_KINDS
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        controls=ControlService(self.f.storage,policy=AuthorityPolicy(self.f.storage.scope_id,
            actors=[self.f.actor],authorities=[pin(self.f.authority)],capabilities=CAPABILITIES-{'correction'},control_kinds=CONTROL_KINDS),
            clock=lambda:deepcopy(self.f.now))
        access=AccessService(policy=self.access.policy,controls=controls,current_read=self.f.storage.snapshot)
        service=self.make_service(controls=controls,access=access)
        witness=self.artifact('control','no-correction-capability','host_control',{'wake_id':self.request.wake_id,'inflight':False,'resolution':'failed'})
        with self.assertRaises(ContractError) as error:
            service.reconcile(self.request,witness,actor=self.f.actor,authority=entity_ref(self.f.authority),
                access_context=self.access_context,command_id='reconcile-without-capability')
        self.assertEqual(error.exception.code,'E_AUTHORITY_REQUIRED')
        self.assertTrue(self.service.inspect(self.request,actor=self.f.actor,authority=entity_ref(self.f.authority),access_context=self.access_context)['outcome_unknown'])

    def test_reconciliation_honors_active_correction_denial(self):
        from control_helpers import control_command
        from integration.helpers import _in_scope
        self.add();self.service.claim(self.request,token=self.token,access_context=self.access_context)
        command=_in_scope(control_command('deny-reconcile',self.f.authority,targets=[self.f.source],action='deny',
            capabilities=['correction'],now=self.f.now),self.f.storage.scope_id)
        command['actor']=self.f.actor;command['body']['control']['body']['actor']=self.f.actor
        self.assertEqual(self.f.controls.apply(self.f.controls.prepare(command))['status'],'success')
        witness=self.artifact('control','denied-correction-proof','host_control',{'wake_id':self.request.wake_id,'inflight':False,'resolution':'failed'})
        with self.assertRaises(ContractError) as error:
            self.service.reconcile(self.request,witness,actor=self.f.actor,authority=entity_ref(self.f.authority),
                access_context=self.access_context,command_id='reconcile-while-denied')
        self.assertEqual(error.exception.code,'E_AUTHORITY_REQUIRED')
        self.assertEqual(self.pending(),self.request.value['contributions'])


    def test_reconciliation_honors_correction_denial_on_undeclared_provenance_parent(self):
        from integration.helpers import create_command,record_input,_in_scope
        from control_helpers import control_command
        derived=record_input('observation','review-derived-source',scope_id=self.f.storage.scope_id)
        derived['provenance'].update(origin='derived',parents=[pin(self.f.source)])
        command=create_command('insert-review-derived','derived-bootstrap-subject',scope_id=self.f.storage.scope_id,
            expected_revisions=[pin(self.f.source)])
        def insert(tx):
            tx.insert(derived);subject=tx.insert(tx.command['body']['matter'])
            return tx.success('created',{'matter':pin(subject)})
        self.assertEqual(self.f.storage.execute(command,insert)['status'],'success')
        derived=self.f.storage.get(entity_ref(derived));self.native=[pin(self.f.subject),pin(derived)]
        self.access=AccessService(policy=HostAccessPolicy(scope_id=self.f.storage.scope_id,audiences=[self.audience],
            providers=[{'reference':self.provider,'provider':'synthetic','transport':'fixture'}],
            grants=[{'reference':r,'audiences':[self.audience],'providers':[self.provider]} for r in [*self.native,pin(self.f.source)]]),
            controls=self.f.controls,current_read=self.f.storage.snapshot)
        self.token=self.f.controls.capture(actor=self.f.actor,authority=entity_ref(self.f.authority),capability='assessment',
            targets=[entity_ref(r) for r in [*self.native,pin(self.f.source)]])
        with self.f.storage.snapshot() as view:
            self.access_context=self.access.capture(view,token=self.token,audience=self.audience,provider=self.provider,references=self.native)
        self.service=self.make_service(access=self.access);request=self.req(dependencies=[pin(derived)])
        self.add(request);self.service.claim(request,token=self.token,access_context=self.access_context)
        self.assertNotIn(pin(self.f.source),request.value['dependencies'])
        self.assertIn(pin(self.f.source),self.access_context.value['dependencies'])
        command=_in_scope(control_command('deny-parent-correction',self.f.authority,targets=[self.f.source],action='deny',
            capabilities=['correction'],now=self.f.now),self.f.storage.scope_id)
        command['actor']=self.f.actor;command['body']['control']['body']['actor']=self.f.actor
        self.assertEqual(self.f.controls.apply(self.f.controls.prepare(command))['status'],'success')
        witness=self.artifact('control','parent-denial-proof','host_control',{'wake_id':request.wake_id,'inflight':False,'resolution':'failed'})
        with self.assertRaises(ContractError) as error:
            self.service.reconcile(request,witness,actor=self.f.actor,authority=entity_ref(self.f.authority),
                access_context=self.access_context,command_id='parent-denial-reconcile')
        self.assertEqual(error.exception.code,'E_AUTHORITY_REQUIRED')
        self.assertTrue(self.service.inspect(request,actor=self.f.actor,authority=entity_ref(self.f.authority),
            access_context=self.access_context)['outcome_unknown'])

    def test_new_pressure_write_cannot_hide_an_older_pending_native_selection(self):
        from control_helpers import control_command
        from integration.helpers import _in_scope
        self.add();old=self.revise_native_matter()
        policy=HostAccessPolicy(scope_id=self.f.storage.scope_id,audiences=[self.audience],
            providers=[{'reference':self.provider,'provider':'synthetic','transport':'fixture'}],
            grants=[{'reference':r,'audiences':[self.audience],'providers':[self.provider]} for r in [pin(old),pin(self.f.subject),pin(self.f.source)]])
        self.native=[pin(self.f.subject)]
        self.access=AccessService(policy=policy,controls=self.f.controls,current_read=self.f.storage.snapshot)
        self.token=self.f.controls.capture(actor=self.f.actor,authority=entity_ref(self.f.authority),capability='assessment',
            targets=[entity_ref(r) for r in self.native])
        with self.f.storage.snapshot() as view:
            self.access_context=self.access.capture(view,token=self.token,audience=self.audience,provider=self.provider,references=self.native)
        self.service=self.make_service(access=self.access)
        source=self.artifact('evidence','new-native-selection','source_fact',{'new':'distinct material'})
        request=self.req(dependencies=[],contributions=[{'reference':source,'lineage':'new-native-selection'}])
        row=self.add(request)
        self.assertEqual(len(row['value']['value']['pending']),2)
        for restriction in ('grant_removed','read_denied'):
            if restriction=='grant_removed':
                selected=HostAccessPolicy(scope_id=self.f.storage.scope_id,audiences=[self.audience],
                    providers=[{'reference':self.provider,'provider':'synthetic','transport':'fixture'}],
                    grants=[{'reference':pin(self.f.subject),'audiences':[self.audience],'providers':[self.provider]}])
            else:
                selected=policy
                command=_in_scope(control_command('deny-older-pending-read',self.f.authority,targets=[self.f.source],
                    action='deny',capabilities=['read'],now=self.f.now),self.f.storage.scope_id)
                command['actor']=self.f.actor;command['body']['control']['body']['actor']=self.f.actor
                self.assertEqual(self.f.controls.apply(self.f.controls.prepare(command))['status'],'success')
            access=AccessService(policy=selected,controls=self.f.controls,current_read=self.f.storage.snapshot)
            service=self.make_service(access=access)
            reads=[lambda:service.pressure(request,token=self.token,access_context=self.access_context),
                   lambda:service.history(request,actor=self.f.actor,authority=entity_ref(self.f.authority),access_context=self.access_context),
                   lambda:service.record_pressure(request,token=self.token,access_context=self.access_context,command_id='review-pressure-2')]
            for read in reads:
                with self.subTest(restriction=restriction,read=read):
                    with self.assertRaises(ContractError) as error:read()
                    self.assertEqual(error.exception.code,'E_AUTHORITY_REQUIRED')
