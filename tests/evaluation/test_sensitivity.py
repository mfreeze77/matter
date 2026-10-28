"""MAT-041 semantic oracles and deliberate faults; no provider/network claims."""
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
import json
import sys
import tempfile
from unittest.mock import patch
import unittest

from matter.canonical import canonical_bytes,loads
from matter.contracts import ContractError
from matter.evaluation.sensitivity import prepare_sensitivity,sensitivity_report,ProbeObservation
from matter.semantic import Batch,normalize_response
from matter.semantic.questions import QuestionSpecification
from matter.semantic.providers.typesafe import TypeSafeHTTPExecutor,ADAPTER_VERSION
from rule_helpers import NOW,LATE

FIXTURE=Path(__file__).resolve().parents[1]/'fixtures/evaluation/question_variants.json'


def suite_inputs():
    fixture=loads(FIXTURE.read_bytes())
    context={'provider':'typesafe','transport':'http','adapter_version':ADAPTER_VERSION,'mode':'offline_fixture',
        'requested_model':'jev-1.14.0','deadline':LATE,'max_request_bytes':65536,'max_response_bytes':65536}
    return dict(identity='sensitivity-fixture',scope_id='synthetic:claims',state={'scope_id':'synthetic:claims','as_of':NOW,'facts':fixture['facts']},
        choice=QuestionSpecification(fixture['choice']),propositions={r:QuestionSpecification(v) for r,v in fixture['propositions'].items()},
        positive_choice=fixture['positive_choice'],references=fixture['references'],context=context,tolerance=fixture['tolerance'])


def oracle(job,*,first_option=False,stubborn=False,inconsistent=False):
    expected=loads(FIXTURE.read_bytes())['references'];answers=[]
    for role,head in job['heads'].items():
        question=head['rendered']['question'];id=question['id']
        if role=='choice':
            definition=next(o['description'] for o in loads(FIXTURE.read_bytes())['choice']['criteria'] if o['id']==expected[role]['outcome'])
            target=next(o['id'] for o in question['criteria'] if o['description']==definition)
            if first_option:target=question['criteria'][0]['id']
            rest=[o['id'] for o in question['criteria'] if o['id']!=target]
            probabilities={target:'0.9',**dict(zip(rest,('0.05','0.03','0.02')))}
            answers.append({'id':id,'primitive':'choice','choice':target,'confidence':'0.9','probabilities':probabilities})
        else:
            p='0.95' if expected[role]['outcome']=='true' else '0.05'
            if stubborn:p='0.95'
            if inconsistent and role in ('equivalent','complement'):p='0.8'
            answers.append({'id':id,'primitive':'proposition_probability','probability':p})
    return canonical_bytes({'answers':answers,'resolved_model':'jev-1.14.0'})


def observations(suite,**fault):
    rows=[]
    for job in suite.value['jobs']:
        batch=Batch(job['batch']);result=normalize_response(batch,oracle(job,**fault))
        rows.append(ProbeObservation(job['id'],batch,result,'synthetic-artifact:'+job['id']))
    return rows


class SensitivityTests(unittest.TestCase):
    def setUp(self):self.inputs=suite_inputs();self.suite=prepare_sensitivity(**self.inputs)

    def test_real_native_wire_repeats_and_order_changes_are_distinct(self):
        jobs=self.suite.value['jobs'];adapter=TypeSafeHTTPExecutor(model='jev-1.14.0',api_key='synthetic-only',timeout=2,max_calls=13)
        bodies=[]
        for job in jobs:
            value=deepcopy(job['batch']);value['context']['mode']='provider_shadow'
            bodies.append(adapter._request(Batch(value)))
        self.assertEqual(bodies[0],bodies[1])
        baseline=json.loads(bodies[0]);reverse=json.loads(bodies[2]);qid=jobs[2]['heads']['choice']['rendered']['question']['id']
        self.assertNotEqual(list(baseline['questions'][qid]['criteria']),list(reverse['questions'][qid]['criteria']))
        for ref in self.inputs['references'].values():self.assertNotIn(ref['artifact'],bodies[0].decode())
        self.assertEqual(len(jobs),13)

    def test_oracle_is_semantically_equal_after_order_neutral_and_name_swaps(self):
        report=sensitivity_report(self.suite,observations(self.suite))
        self.assertEqual(report['status'],'complete');self.assertEqual(report['independent_label_count'],0)
        self.assertEqual(report['counts']['valid'],25)
        self.assertFalse(any(c['status']=='review_required' for c in report['checks']),report['checks'])
        swapped=next(r for r in report['observations'] if r['kind']=='name_definition_swap')
        self.assertNotEqual(swapped['native_selected'],swapped['selected'])
        self.assertEqual(swapped['selected'],'same_topic_only')
        self.assertTrue(all(v['qualification_impact']=='no_incompatibility_observed' for v in report['per_family'].values()))
        self.assertEqual(report['qualification'],'not_run');self.assertFalse(report['consequential_use'])
        bundling=[c for c in report['checks'] if c['kind']=='separate_vs_bundled']
        self.assertEqual(len(bundling),7);self.assertTrue(any(c['roles']==['choice'] for c in bundling))

    def test_first_option_bias_and_stubborn_question_meaning_are_detected(self):
        bias=sensitivity_report(self.suite,observations(self.suite,first_option=True))
        self.assertTrue(any(c['status']=='review_required' for c in bias['checks'] if c['kind']=='mapped_invariance'))
        stubborn=sensitivity_report(self.suite,observations(self.suite,stubborn=True))
        controls=[c for c in stubborn['checks'] if c['kind']=='changed_meaning']
        self.assertEqual(len(controls),6);self.assertTrue(all(c['status']=='review_required' for c in controls))

    def test_bundling_effect_is_not_reported_as_order_or_label_sensitivity(self):
        rows=observations(self.suite)
        for index,job in enumerate(self.suite.value['jobs']):
            if job['kind']=='baseline' or 'choice' not in job['heads']:continue
            raw=json.loads(oracle(job));answer=raw['answers'][0];head=job['heads']['choice']
            probabilities={'same_topic_only':'0.5','same_matter':'0.35','different':'0.1','insufficient':'0.05'}
            answer['probabilities']={native:probabilities[original] for native,original in head['to_original'].items()}
            answer['confidence']='0.5'
            rows[index]=ProbeObservation(job['id'],rows[index].batch,normalize_response(rows[index].batch,canonical_bytes(raw)),'synthetic-bundling-effect')
        report=sensitivity_report(self.suite,rows)
        controls=[c for c in report['checks'] if c['kind']=='mapped_invariance']
        self.assertEqual(len(controls),4);self.assertTrue(all(c['status']=='within_declared_tolerance' for c in controls))
        self.assertTrue(all(c['comparison_context']=='single_choice_control' and c['control_job_id']=='probe-06' for c in controls))
        single=next(c for c in report['checks'] if c['kind']=='separate_vs_bundled' and c['roles']==['choice'])
        self.assertEqual(single['status'],'review_required')
        rows=[r for r in rows if r.job_id!='probe-06']
        self.assertTrue(all(c['status']=='not_evaluated' for c in sensitivity_report(self.suite,rows)['checks'] if c['kind']=='mapped_invariance'))

    def test_equivalence_complement_and_cross_primitive_conflicts_do_not_make_joint_probability(self):
        report=sensitivity_report(self.suite,observations(self.suite,inconsistent=True,stubborn=True))
        for kind in ('equivalent','complement','cross_primitive'):
            self.assertTrue(any(c['status']=='review_required' for c in report['checks'] if c['kind']==kind))
        self.assertNotIn('joint_probability',report)
        self.assertEqual(len({c['id'] for c in report['checks']}),len(report['checks']))

    def test_missing_fields_refuse_entire_schedule_and_expected_labels_never_enter_state(self):
        bad=suite_inputs();bad['state'].pop('facts')
        with self.assertRaises(ContractError) as refused:prepare_sensitivity(**bad)
        self.assertEqual(refused.exception.code,'E_EVIDENCE_UNAVAILABLE')
        sentinel='HOST_REFERENCE_NOT_MODEL_INPUT';changed=suite_inputs()
        for ref in changed['references'].values():ref['artifact']=sentinel
        suite=prepare_sensitivity(**changed)
        for job in suite.value['jobs']:
            self.assertNotIn(sentinel,canonical_bytes(job['batch']).decode())
        self.assertIn(sentinel,canonical_bytes(suite.value).decode())

    def test_missing_baseline_failed_response_and_method_change_remain_denominators(self):
        rows=observations(self.suite);missing=sensitivity_report(self.suite,rows[1:])
        self.assertEqual(missing['counts']['missing'],7);self.assertEqual(missing['status'],'incomplete')
        self.assertTrue(all(c['status']=='not_evaluated' for c in missing['checks']))
        bad=rows[0];failed=ProbeObservation(bad.job_id,bad.batch,normalize_response(bad.batch,b'not json'),bad.artifact)
        report=sensitivity_report(self.suite,[failed,*rows[1:]])
        self.assertEqual(report['counts']['failed'],7)
        result=normalize_response(rows[2].batch,oracle(self.suite.value['jobs'][2]).replace(b'jev-1.14.0',b'wrong-model'))
        changed=[*rows[:2],ProbeObservation(rows[2].job_id,rows[2].batch,result,'synthetic-wrong-model'),*rows[3:]]
        self.assertEqual(sensitivity_report(self.suite,changed)['counts']['method_mismatch'],1)
        with self.assertRaises(ContractError):sensitivity_report(self.suite,[rows[0],rows[0]])

    def test_two_failed_baselines_do_not_mislabel_successful_singletons_as_model_drift(self):
        rows=observations(self.suite)
        for index in (0,1):
            row=rows[index];rows[index]=ProbeObservation(row.job_id,row.batch,normalize_response(row.batch,b'bad json'),row.artifact)
        report=sensitivity_report(self.suite,rows)
        self.assertEqual(report['counts'],{'valid':11,'missing':0,'failed':14,'method_mismatch':0})
        self.assertTrue(all(c['status']=='not_evaluated' for c in report['checks']))

    def test_repeat_envelope_is_separate_from_larger_alteration(self):
        rows=observations(self.suite);jobs=self.suite.value['jobs'];raw=json.loads(oracle(jobs[1]))
        next(a for a in raw['answers'] if a['id']=='q2')['probability']='0.15' # matter baseline variation
        rows[1]=ProbeObservation(jobs[1]['id'],rows[1].batch,normalize_response(rows[1].batch,canonical_bytes(raw)),'synthetic-repeat')
        report=sensitivity_report(self.suite,rows)
        self.assertEqual(report['repeat_variation']['matter']['ranges']['true'],'0.1')
        comparison=next(c for c in report['checks'] if c['kind']=='separate_vs_bundled' and c['roles']==['matter'])
        self.assertEqual(comparison['excess_over_repeat_envelope'],'0')
        self.assertEqual(comparison['status'],'within_declared_tolerance')
        # The same cross-primitive gap is ordinary repeat variation here.
        cross=next(c for c in report['checks'] if c['id']=='cross-primitive:probe-01')
        self.assertEqual(cross['repeat_spread'],'0.1');self.assertEqual(cross['status'],'within_declared_tolerance')
        raw=json.loads(oracle(jobs[8]));raw['answers'][0]['probability']='0.4'
        rows[8]=ProbeObservation(jobs[8]['id'],rows[8].batch,normalize_response(rows[8].batch,canonical_bytes(raw)),'synthetic-alteration')
        comparison=next(c for c in sensitivity_report(self.suite,rows)['checks'] if c['kind']=='separate_vs_bundled' and c['roles']==['matter'])
        self.assertEqual(comparison['excess_over_repeat_envelope'],'0.25');self.assertEqual(comparison['status'],'review_required')

    def test_common_composition_boundary_refuses_undeclared_probability_products(self):
        from matter.conflicts import ConflictResolver
        with self.assertRaises(ContractError) as refused:
            ConflictResolver('example','joint','1.0',mode='multiply_probabilities')
        self.assertEqual(refused.exception.code,'E_POLICY_INVALID')
        result=ConflictResolver('example','retain','1.0').compose([
            {'node':'left','judgment':{'body':{'semantic_output':{'probability':'0.8'}}}},
            {'node':'right','judgment':{'body':{'semantic_output':{'probability':'0.7'}}}}])
        self.assertEqual(result['status'],'conflicting');self.assertIsNone(result['semantic_output'])


class RecordedSensitivityExampleTests(unittest.TestCase):
    def example(self):
        examples=Path(__file__).resolve().parents[2]/'examples'
        sys.path.insert(0,str(examples))
        try:
            import question_sensitivity as example
        finally:sys.path.pop(0)
        return example

    def test_retained_precision_decoder_reanalyzes_without_dispatch_and_pins_attempt(self):
        example=self.example()
        suite=prepare_sensitivity(**suite_inputs());job=suite.value['jobs'][0];batch=Batch(job['batch'])
        result=normalize_response(batch,oracle(job));started={'batch':batch.value}
        from matter.canonical import canonical_digest
        row={'index':0,'job_id':job['id'],'started_digest':canonical_digest(started,'matter.provider-start.v1'),'result':result.value}
        provider={'status':'completed','fresh_attempts':1,'observations':[row]}
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary);(output/'live').mkdir()
            (output/'live/0-started.json').write_bytes(canonical_bytes(started))
            (output/'live/0-result.json').write_bytes(canonical_bytes(row))
            with patch.object(example,'run_provider',side_effect=AssertionError('must not dispatch')):
                report,artifact=example.analyze_recorded(suite,provider,output)
                self.assertEqual(report['counts']['valid'],7);self.assertEqual(report['counts']['missing'],18)
                self.assertEqual(report['analysis_mode'],'recorded_validation_of_actual_live_responses')
                self.assertEqual(report['provider_execution']['fresh_attempts'],1)
                self.assertEqual(loads((output/artifact['reference']).read_bytes()),report)
                altered=deepcopy(row);altered['result']['precision_profile']['rounding']='unsupported'
                (output/'live/0-result.json').write_bytes(canonical_bytes(altered))
                with self.assertRaisesRegex(ValueError,'recorded_attempt_binding_changed'):
                    example.analyze_recorded(suite,provider,output)
                (output/'live/0-result.json').write_bytes(canonical_bytes(row))
                row['result']['precision_profile']['rounding']='unsupported'
                (output/'live/0-result.json').write_bytes(canonical_bytes(row))
                with self.assertRaisesRegex(ValueError,'recorded_precision_profile_changed'):
                    example.analyze_recorded(suite,provider,output)

    def test_recorded_execution_faults_cannot_be_erased_with_or_without_bytes(self):
        from matter.semantic import Capabilities,FixtureExecutor,execute_batch
        from matter.semantic.contracts import ExecutionFault
        from matter.canonical import canonical_digest
        example=self.example();suite=prepare_sensitivity(**suite_inputs());job=suite.value['jobs'][0];batch=Batch(job['batch'])
        adapter=TypeSafeHTTPExecutor(model='jev-1.14.0',api_key='synthetic-only',timeout=2,max_calls=1)
        caps=adapter.capabilities.value;caps['modes']=['offline_fixture']
        fixture=FixtureExecutor(Capabilities(caps),{batch.digest:oracle(job)})
        for no_bytes in (False,True):
            with self.subTest(no_bytes=no_bytes):
                times=iter([NOW,NOW if no_bytes else LATE])
                with patch.object(FixtureExecutor,'execute',side_effect=ExecutionFault('timeout')) if no_bytes else nullcontext():
                    result=execute_batch(fixture,batch,clock=lambda:next(times))
                self.assertEqual(result.value['execution_status'],'timed_out')
                self.assertEqual(result.value['raw_response']['state'],'unavailable' if no_bytes else 'available');self.assertFalse(result.primitive_valid)
                started={'batch':batch.value}
                row={'index':0,'job_id':job['id'],'started_digest':canonical_digest(started,'matter.provider-start.v1'),'result':result.value}
                with tempfile.TemporaryDirectory() as temporary:
                    output=Path(temporary);(output/'live').mkdir()
                    (output/'live/0-started.json').write_bytes(canonical_bytes(started))
                    (output/'live/0-result.json').write_bytes(canonical_bytes(row))
                    with patch.object(example,'run_provider',side_effect=AssertionError('must not dispatch')):
                        with self.assertRaisesRegex(ValueError,'recorded_execution_invalid'):
                            example.analyze_recorded(suite,{'observations':[row]},output)
                    self.assertFalse(list(output.glob('live-sensitivity-*')))
