"""Behavioral checks for the delivered scaffold, not future runtime claims."""

from copy import deepcopy
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from matter.demo import Walkthrough, run_fixture
from matter.jsonio import read, loads
from matter.tickets import readiness
from matter.validation import graph_errors, validate

ROOT = Path(__file__).resolve().parents[1]


class RepositoryIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.ticket = read(ROOT / 'tickets/records/MAT-002.json')
        self.ticket['depends_on'] = []
        self.requirements = [r for r in read(ROOT / 'docs/requirements.json') if r['id'] in self.ticket['requirements']]

    def test_complete_repository_is_valid(self):
        result = validate(ROOT)
        self.assertTrue(result['ok'], result['errors'])
        self.assertGreaterEqual(result['tickets'], 80)
        self.assertEqual(result['walkthroughs'], 3)

    def test_ticket_schema_rejects_incomplete_or_unknown_contract(self):
        schema = Draft202012Validator(read(ROOT / 'schemas/ticket.schema.json'))
        for mutate in [lambda t: t.pop('acceptance'), lambda t: t.update(status='probably_done'),
                       lambda t: t.update(priority=0), lambda t: t.update(undocumented_permission=True)]:
            with self.subTest(mutation=mutate):
                ticket = deepcopy(self.ticket)
                mutate(ticket)
                self.assertTrue(list(schema.iter_errors(ticket)))

    def test_missing_dependency_is_an_error(self):
        self.ticket['depends_on'] = ['MAT-999']
        self.assertTrue(any('missing dependency' in e for e in graph_errors([self.ticket], self.requirements)))

    def test_dependency_cycle_is_an_error(self):
        other = deepcopy(self.ticket)
        other['id'] = 'MAT-003'
        other['depends_on'] = [self.ticket['id']]
        self.ticket['depends_on'] = [other['id']]
        self.assertTrue(any('cycle' in e for e in graph_errors([self.ticket, other], self.requirements)))

    def test_phase_cannot_precede_its_dependency(self):
        other = deepcopy(self.ticket)
        other.update(id='MAT-003', phase=3)
        self.ticket.update(phase=2, depends_on=[other['id']])
        self.assertTrue(any('phase precedes dependency' in e for e in graph_errors([self.ticket, other], self.requirements)))
        self.ticket['phase'] = 3
        self.assertFalse(any('phase precedes dependency' in e for e in graph_errors([self.ticket, other], self.requirements)))

    def test_completion_requires_finished_dependencies_and_evidence(self):
        other = deepcopy(self.ticket)
        other['id'] = 'MAT-003'
        self.ticket.update(status='done', depends_on=[other['id']])
        errors = graph_errors([self.ticket, other], self.requirements)
        self.assertTrue(any('unfinished dependency' in e for e in errors))
        self.assertTrue(any('without passed evidence' in e for e in errors))

    def test_unknown_and_uncovered_requirements_are_errors(self):
        self.ticket['requirements'] = ['UNKNOWN-01']
        errors = graph_errors([self.ticket], self.requirements)
        self.assertTrue(any('unknown requirement' in e for e in errors))
        self.assertTrue(any('uncovered requirement' in e for e in errors))

    def test_duplicate_ids_and_acceptance_ids_are_errors(self):
        self.ticket['acceptance'][1]['id'] = self.ticket['acceptance'][0]['id']
        errors = graph_errors([self.ticket, deepcopy(self.ticket)], self.requirements)
        self.assertTrue(any('duplicate ticket ID' in e for e in errors))
        self.assertTrue(any('duplicate acceptance ID' in e for e in errors))

    def test_readiness_never_implies_completion(self):
        dep = deepcopy(self.ticket)
        dep.update(id='MAT-003', status='done')
        self.ticket['depends_on'] = [dep['id']]
        by_id = {self.ticket['id']: self.ticket, dep['id']: dep}
        self.assertEqual(readiness(self.ticket, by_id), 'ready')
        self.assertEqual(self.ticket['status'], 'planned')
        dep['status'] = 'planned'
        self.assertEqual(readiness(self.ticket, by_id), 'waiting')
        self.ticket['status'] = 'blocked'
        self.assertEqual(readiness(self.ticket, by_id), 'blocked')

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_literals(self):
        for source in ['{"id":1,"id":2}', '{"confidence":NaN}', '{"confidence":Infinity}']:
            with self.subTest(source=source), self.assertRaises(ValueError):
                loads(source)


class LifecycleWalkthroughTests(unittest.TestCase):
    def setUp(self):
        self.fixture = read(ROOT / 'examples/oil.json')
        self.first = self.fixture['events'][0]

    def test_independently_declared_scenarios(self):
        for name in ('oil', 'civic', 'diat'):
            with self.subTest(name=name):
                fixture = read(ROOT / f'examples/{name}.json')
                self.assertEqual(run_fixture(fixture), fixture['expected'])

    def test_identity_survives_context_changes(self):
        runner = Walkthrough(self.fixture['scope_id'], self.fixture['audience'])
        runner.apply(self.first)
        before = runner.matters[self.first['matter_key']].identity
        event = deepcopy(self.fixture['events'][8])
        runner.apply(event)
        self.assertEqual(runner.matters[self.first['matter_key']].identity, before)

    def test_foreign_scope_is_rejected_without_mutation(self):
        runner = Walkthrough(self.fixture['scope_id'], self.fixture['audience'])
        event = dict(self.first, scope_id='foreign-scope')
        before = deepcopy(runner.__dict__)
        with self.assertRaises(ValueError):
            runner.apply(event)
        self.assertEqual(runner.__dict__, before)

    def test_duplicate_content_conflict_is_rejected_without_mutation(self):
        runner = Walkthrough(self.fixture['scope_id'], self.fixture['audience'])
        runner.apply(self.first)
        before = deepcopy(runner.__dict__)
        event = dict(self.first, at='2026-10-01T09:01:00Z', classification='material')
        with self.assertRaises(ValueError):
            runner.apply(event)
        self.assertEqual(runner.__dict__, before)

    def test_audience_does_not_receive_another_audiences_pending_update(self):
        runner = Walkthrough(self.fixture['scope_id'], self.fixture['audience'])
        runner.apply(dict(self.first, classification='material'))
        boundary = deepcopy(self.fixture['events'][4])
        boundary['audience'] = 'different-audience'
        self.assertEqual(runner.apply(boundary), 'quiet')
        next_boundary = dict(boundary, id='boundary-for-agent', at='2026-10-01T09:05:00Z', audience=self.fixture['audience'])
        self.assertEqual(runner.apply(next_boundary), 'delivered')
        self.assertEqual(runner.delivered_updates, 1)

    def test_material_burst_coalesces_at_a_delivery_boundary(self):
        runner = Walkthrough(self.fixture['scope_id'], self.fixture['audience'])
        runner.apply(dict(self.first, classification='material'))
        runner.apply(dict(self.first, id='second-event', at='2026-10-01T09:01:00Z', occurrence_id='execution-2', effective_at='2026-10-01T09:01:00Z', classification='material'))
        self.assertEqual(runner.apply(self.fixture['events'][4]), 'delivered')
        self.assertEqual(runner.delivered_updates, 1)
        self.assertEqual(runner.apply(self.fixture['events'][6]), 'quiet')

    def test_old_success_cannot_resolve_a_later_condition(self):
        runner = Walkthrough(self.fixture['scope_id'], self.fixture['audience'])
        runner.apply(dict(self.first, at='2026-10-01T09:02:00Z', effective_at='2026-10-01T09:02:00Z'))
        recovery = dict(self.first, id='late-old-pass', at='2026-10-01T09:04:00Z', effective_at='2026-10-01T09:01:00Z', classification='resolution')
        self.assertEqual(runner.apply(recovery), 'resolution_unmatched')
        self.assertEqual(runner.matters[self.first['matter_key']].status, 'open')

    def test_unobserved_future_evidence_cannot_enter_a_trace(self):
        runner = Walkthrough(self.fixture['scope_id'], self.fixture['audience'])
        with self.assertRaises(ValueError):
            runner.apply(dict(self.first, effective_at='2026-10-01T09:01:00Z'))
        self.assertEqual(runner.matters, {})


if __name__ == '__main__':
    unittest.main()
