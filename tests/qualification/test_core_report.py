"""MAT-025 release receipt refusal checks, not provider/domain qualification."""
from copy import deepcopy
import importlib.util
import io
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('core_qualification_example',ROOT/'examples/core_qualification.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)


class CoreReportTests(unittest.TestCase):
    def inputs(self):
        plan=core.loads(core.PLAN.read_bytes());required=core.validate_plan(plan)
        manifest={'plan_sha256':core.sha(core.canonical_bytes(plan)),'runtime_path':'/synthetic/runtime','files':{'synthetic-fixture':'a'*64},
            'storage':{'backend':'sqlite','journal_mode':'DELETE','synchronous':'EXTRA','foreign_keys':True}}
        return plan,manifest,{i:{'status':'passed','elapsed_seconds':'0'} for i in required}

    def test_missing_skipped_failed_or_unrun_evidence_cannot_pass(self):
        plan,manifest,results=self.inputs();key=plan['requirements']['CORE-01'][0]
        self.assertEqual(core.build_report(plan,manifest,results,unchanged=True)['status'],'passed')
        for status in ('failed','skipped','not_run',None):
            changed=deepcopy(results)
            if status is None:del changed[key]
            else:changed[key]['status']=status
            report=core.build_report(plan,manifest,changed,unchanged=True)
            self.assertEqual(report['status'],'failed')
            self.assertEqual(report['requirements']['CORE-01']['status'],'failed')

    def test_report_keeps_unrun_gates_and_refuses_changed_manifest(self):
        plan,manifest,results=self.inputs()
        report=core.build_report(plan,manifest,results,unchanged=True)
        self.assertTrue(all(x=='not_run' for x in report['unrun_gates'].values()))
        self.assertEqual(core.build_report(plan,manifest,results,unchanged=False)['status'],'failed')
        plan['limits'].append('Changed after freezing.')
        with self.assertRaises(ValueError):core.build_report(plan,manifest,results,unchanged=True)

    def test_fixture_errors_are_recorded_and_cannot_leave_a_passing_report(self):
        class BrokenFixture(unittest.TestCase):
            @classmethod
            def setUpClass(cls):raise RuntimeError('Synthetic fixture failure')
            def test_case(self):self.fail('Fixture failure must prevent invocation')
        result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=core.RecordingResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(BrokenFixture))
        self.assertFalse(result.wasSuccessful());self.assertTrue(result.records)
        plan,manifest,records=self.inputs();records.update(result.records)
        report=core.build_report(plan,manifest,records,unchanged=True,execution_successful=result.wasSuccessful())
        self.assertEqual(report['status'],'failed');self.assertTrue(report['unmapped_checks'])
        plan,manifest,results=self.inputs();del plan['requirements']['CORE-09']
        with self.assertRaises(ValueError):core.build_report(plan,manifest,results,unchanged=True)
