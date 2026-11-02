"""MAT-083 diagnostics observe the real race without leaking process patches."""
import importlib.util
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from matter.storage import SQLiteStore
import matter._validation as validation


class ContentionDiagnosticTests(unittest.TestCase):
    def diagnostic(self):
        path = Path(__file__).resolve().parents[2] / 'conformance/sqlite_contention.py'
        spec = importlib.util.spec_from_file_location('mat083_diagnostic', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_unsupported_concurrent_profiler_refuses_before_fixture_or_patch(self):
        module = self.diagnostic()
        original = SQLiteStore.execute, sqlite3.connect, validation._SUCCESSFUL
        with patch.object(module.sys, 'version_info', (3, 12, 0)), \
                patch.object(module, 'ExitStack', side_effect=AssertionError('patched before refusal')), \
                patch.object(module.unittest, 'TextTestRunner', side_effect=AssertionError('fixture before refusal')):
            with self.assertRaises(module.ProfileUnavailable):
                module.run(profile=True, disable_validation_cache=True)
        self.assertEqual((SQLiteStore.execute, sqlite3.connect, validation._SUCCESSFUL), original)

    def test_real_unprofiled_race_preserves_assertion_and_restores_observers(self):
        module = self.diagnostic()
        original = SQLiteStore.execute, sqlite3.connect, validation._SUCCESSFUL
        result = module.run()
        self.assertTrue(result['success'], result)
        self.assertEqual((SQLiteStore.execute, sqlite3.connect, validation._SUCCESSFUL), original)
        self.assertFalse(result['profiled'])
        self.assertFalse(result['validation_cache_disabled'])
        results = [event for event in result['events'] if event['event'] == 'execute_result']
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(event['outcome'] == 'ready' for event in results), 1)
        self.assertTrue(any(event['error'] == 'E_DEPENDENCY_STALE' or event['outcome'] == 'withheld' for event in results))
        for event in result['events']:
            self.assertLessEqual(set(event), {'at', 'command', 'event', 'verb', 'code', 'name', 'seconds', 'outcome', 'error', 'function_calls'})


    def test_errors_assertions_and_skips_have_distinct_receipts(self):
        from integration.test_dispatch_races import DispatchRaces
        module = self.diagnostic()
        for exception, outcome, exit_code in ((RuntimeError('synthetic diagnostic error'), 'error', 2),
                                             (AssertionError('synthetic fixture failure'), 'assertion_failure', 1),
                                             (unittest.SkipTest('synthetic unavailable fixture'), 'not_executed', 3)):
            with self.subTest(outcome=outcome), patch.object(DispatchRaces, 'setUp', side_effect=exception):
                report = module.run()
                self.assertEqual(report['outcome'], outcome)
                self.assertFalse(report['success'])
                self.assertEqual(module.exit_status(report), exit_code)
                self.assertEqual(report['errors'], int(outcome == 'error'))
                self.assertEqual(report['assertion_failures'], int(outcome == 'assertion_failure'))
                self.assertEqual(report['skipped'], int(outcome == 'not_executed'))
                self.assertEqual(report['events'], [])

    def test_native_commit_fault_is_traced_and_never_called_committed(self):
        from integration.test_dispatch_races import DispatchRaces
        module = self.diagnostic()
        fault = {'on': False}
        original_connection = sqlite3.Connection

        class FaultConnection(original_connection):
            def commit(self):
                if fault['on']:
                    fault['on'] = False
                    error = sqlite3.OperationalError('synthetic commit fault')
                    error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                    error.sqlite_errorname = 'SQLITE_IOERR'
                    raise error
                return super().commit()

        def commit_case(case):
            command = case.prepare('intent-a')
            fault['on'] = True
            result = case.service.execute(command)
            case.assertEqual(result['error']['code'], 'E_STORAGE_UNAVAILABLE')
            case.assertEqual(case.transport.calls, [])

        name = 'test_distinct_equivalent_intents_compete_across_real_sqlite_handles'
        with patch.object(module.sqlite3, 'Connection', FaultConnection), patch.object(DispatchRaces, name, commit_case):
            report = module.run()
        self.assertTrue(report['success'], report)
        errors = [event for event in report['events'] if event['event'] == 'sqlite_error']
        self.assertEqual(len(errors), 1)
        self.assertEqual((errors[0]['verb'], errors[0]['code'], errors[0]['name']), ('COMMIT', sqlite3.SQLITE_IOERR, 'SQLITE_IOERR'))
        self.assertFalse(any(event['event'] == 'commit_exit' for event in report['events']))
        self.assertTrue(any(event.get('error') == 'E_STORAGE_UNAVAILABLE' for event in report['events']))
