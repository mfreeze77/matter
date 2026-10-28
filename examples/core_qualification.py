"""MAT-025 receipt over existing unittest episodes, not a replacement test stack.

No network, provider construction, application deployment or runtime admission.
A run freezes its exact selected assertions, fixtures and runtime before tests.
"""
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time
import unittest

import matter
from matter.canonical import canonical_bytes, loads

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'tests/fixtures/conformance/core-qualification.json'
UNRUN=('provider_accuracy','live_usefulness','domain_acceptance','other_storage_backends','physical_power_loss')


def sha(data):return hashlib.sha256(data).hexdigest()


def validate_plan(plan):
    if set(plan)!={'schema_version','id','requirements','acceptance','limits'} or plan['schema_version']!='matter.core-qualification-plan.v1':raise ValueError('invalid_core_plan')
    if set(plan['requirements'])!={'CORE-'+str(i).zfill(2) for i in range(1,25)} or set(plan['acceptance'])!={'AC-'+str(i) for i in range(1,5)}:raise ValueError('incomplete_core_plan')
    for ids in [*plan['requirements'].values(),*plan['acceptance'].values()]:
        if type(ids)is not list or not ids or any(type(i)is not str or not i for i in ids) or len(set(ids))!=len(ids):raise ValueError('missing_core_checks')
    required={i for ids in plan['requirements'].values() for i in ids}
    if any(i not in required for ids in plan['acceptance'].values() for i in ids):raise ValueError('unmapped_acceptance_check')
    return sorted(required)


def freeze(plan):
    validate_plan(plan)
    runtime=Path(matter.__file__).resolve().parent
    inventory={}
    for p in runtime.rglob('*'):
        if p.is_file() and p.suffix in ('.py','.sql'):inventory['runtime/'+str(p.relative_to(runtime))]=sha(p.read_bytes())
    for p in files('matter._schemas').iterdir():
        if p.name.endswith('.schema.json'):inventory['schemas/'+p.name]=sha(p.read_bytes())
    for directory in (ROOT/'tests',ROOT/'examples'):
        for p in directory.rglob('*'):
            if p.is_file() and p.suffix in ('.py','.json','.jsonl'):inventory[str(p.relative_to(ROOT))]=sha(p.read_bytes())
    return {'plan_sha256':sha(canonical_bytes(plan)),'runtime_path':str(runtime),'files':inventory,
        'storage':{'backend':'sqlite','journal_mode':'DELETE','synchronous':'EXTRA','foreign_keys':True}}


def build_report(plan,manifest,results,*,unchanged,execution_successful=True):
    required=validate_plan(plan)
    if manifest['plan_sha256']!=sha(canonical_bytes(plan)):raise ValueError('plan_changed_after_freeze')
    def statuses(mapping):
        return {k:{'status':'passed' if unchanged and execution_successful and all(results.get(i,{}).get('status')=='passed' for i in ids) else 'failed','checks':ids} for k,ids in mapping.items()}
    requirements=statuses(plan['requirements']);acceptance=statuses(plan['acceptance'])
    passed=all(v['status']=='passed' for v in [*requirements.values(),*acceptance.values()])
    report={'schema_version':'matter.core-qualification-report.v1','plan_id':plan['id'],'mode':'synthetic_conformance',
        'status':'passed' if passed else 'failed','manifest':manifest,'unchanged':unchanged,'execution_successful':execution_successful,
        'checks':{i:results.get(i,{'status':'not_run','elapsed_seconds':'0'}) for i in required},
        'unmapped_checks':{i:v for i,v in results.items() if i not in required},
        'requirements':requirements,'acceptance':acceptance,'unrun_gates':{k:'not_run' for k in UNRUN},'limits':plan['limits']}
    # Load the selected checkout schema explicitly so an installed older runtime
    # can be measured without falsely claiming it already shipped this report.
    from jsonschema import Draft202012Validator
    Draft202012Validator(loads((ROOT/'schemas/qualification-report.schema.json').read_bytes())).validate(report)
    return report


class RecordingResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.records={};self.started={}
    def startTest(self,test):
        super().startTest(test);self.started[test.id()]=time.monotonic();self.records[test.id()]={'status':'not_run','elapsed_seconds':'0'}
    def _status(self,test,status):self.records.setdefault(test.id(),{'elapsed_seconds':'0'})['status']=status
    def addSuccess(self,test):super().addSuccess(test);self._status(test,'passed')
    def addFailure(self,test,err):super().addFailure(test,err);self._status(test,'failed')
    def addError(self,test,err):super().addError(test,err);self._status(test,'failed')
    def addSkip(self,test,reason):super().addSkip(test,reason);self._status(test,'skipped')
    def addExpectedFailure(self,test,err):super().addExpectedFailure(test,err);self._status(test,'failed')
    def addUnexpectedSuccess(self,test):super().addUnexpectedSuccess(test);self._status(test,'failed')
    def addSubTest(self,test,subtest,outcome):
        super().addSubTest(test,subtest,outcome)
        if outcome is not None:self._status(test,'failed')
    def stopTest(self,test):
        self.records[test.id()]['elapsed_seconds']=format(time.monotonic()-self.started[test.id()],'.6f');super().stopTest(test)


def run(output):
    if output.exists():raise ValueError('use_new_output_no_overwrite')
    output.mkdir(parents=True)
    plan=loads(PLAN.read_bytes());manifest=freeze(plan)
    (output/'frozen.json').write_bytes(canonical_bytes({'plan':plan,'manifest':manifest})+b'\n')
    sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
    suite=unittest.defaultTestLoader.loadTestsFromNames(validate_plan(plan))
    result=unittest.TextTestRunner(verbosity=2,resultclass=RecordingResult).run(suite)
    report=build_report(plan,manifest,result.records,unchanged=manifest==freeze(plan),execution_successful=result.wasSuccessful())
    report['recorded_at']=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    (output/'report.json').write_bytes(canonical_bytes(report)+b'\n')
    print(json.dumps({'status':report['status'],'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'report':str(output/'report.json'),'unrun_gates':report['unrun_gates']}),flush=True)
    return report['status']=='passed' and result.wasSuccessful()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(not run(parser.parse_args().output))
