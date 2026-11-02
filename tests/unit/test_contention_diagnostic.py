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
        with patch.object(module.sys, 'version_info', (3, 12, 0)):
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
