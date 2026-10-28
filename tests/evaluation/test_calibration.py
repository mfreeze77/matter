"""Synthetic numerical/partition/certificate conformance; no provider qualification."""
from copy import deepcopy
from decimal import Decimal
import unittest
from unittest.mock import patch

from matter.canonical import canonical_bytes,source_digest
from matter.contracts import ContractError
from matter.evaluation.corpus import FrozenCorpus
from matter.evaluation.splits import make_splits,SplitManifest
from matter.evaluation.calibration import (CalibrationPlan,TrialObservation,partition_corpus,fit_thresholds,evaluate_thresholds,lower_accuracy)
from matter.evaluation.certificates import certificate_from_review
from matter.semantic import Batch,normalize_response
from matter.semantic.questions import QuestionSpecification
from matter.semantic.rendering import render_question
from matter.semantic.qualification import qualification_identity
from matter._rule_values import domain
from matter.storage import pin
from semantic import test_qualification as qualification_fixtures
from rule_helpers import component,EARLY,NOW,LATE


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.spec=QuestionSpecification({'schema_version':'1.0','namespace':'example','id':'synthetic-probability','family':'attention','revision':'1.0',
            'primitive':'proposition_probability','instructions':'Does the synthetic evidence support the declared proposition?',
            'criteria':{'true':'Supported.','false':'Unsupported.'},'required_fields':[],
            'renderer':{'id':'canonical-json-bindings','version':'1.0'}})
        episodes=[]
        for i in range(120):
            identity='e'+str(i);text='Synthetic distinct episode '+str(i)+'.';source={'id':identity+'-source','revision':1,'sha256':source_digest(text.encode())}
            obs={'id':identity+'-observation','source':source,'available_at':EARLY,'occurred_at':EARLY,
                 'occurrence_ids':[identity+'-event'],'provenance_groups':[identity+'-group'],'derivation':'root','parents':[]}
            episodes.append({'id':identity,'scope_id':'synthetic:calibration','boundary':{'start':EARLY,'end':LATE,'bounds':'closed'},
                'sources':[{'reference':source,'available_at':EARLY,'artifact':{'kind':'synthetic','text':text}}],
                'observations':[obs],'occurrences':[{'id':identity+'-event','observation_ids':[obs['id']]}],
                'cases':[{'id':'decision','family':'attention','target_observation_ids':[obs['id']],'eligibility':{'state':'eligible','reason':'Synthetic numerical fixture.'}}],
                'labels':[{'id':identity+'-label','revision':1,'case_id':'decision','origin':'independent','status':'accepted','outcome':'yes' if i%2==0 else 'no',
                    'reviewer':{'kind':'human','role':'synthetic-declared-reviewer-fixture'},'reviewed_at':NOW,
                    'evidence':[{'observation_id':obs['id'],'source':source}],'reason':'Synthetic test label, not an actual independent human or provider study.'}]})
        self.corpus=FrozenCorpus({'schema_version':'matter.episode-corpus.v1','id':'calibration-fixture','scope_id':'synthetic:calibration',
            'extraction_profile':component('fixture'),'episodes':episodes})
        self.split=make_splits(self.corpus,identity='fixture-split',revision=1,seed='fixed-qualification',weights={'tuning':70,'qualification':20,'final':10})
        self.identity=self.trial('e0','decision').value['identity']
        self.artifact={'scope_id':'synthetic:calibration','namespace':'example','record_type':'receipt','id':'artifact','digest':source_digest(b'fixture-artifact')}
        regions={'positive':{'minimum':'0.8','maximum':'1','choices':[]},'negative':{'minimum':'0','maximum':'0.2','choices':[]}}
        self.plan_value={'id':'predeclared-fixture','identity':self.identity,'family':'attention','corpus_digest':self.corpus.sha256,'split_digest':self.split.digest,
            'outcomes':{'positive':'yes','negative':'no'},'target_accuracy':{'positive':'0.5','negative':'0.5'},'minimum_episodes':{'positive':2,'negative':2},
            'confidence':'0.95','minimum_coverage':'0.5','maximum_failure_fraction':'0.1','candidate_regions':[regions],'artifacts':[self.artifact]}
        self.plan=CalibrationPlan(self.plan_value);self.reads=[]

    def trial(self,episode_id,case_id,*,value=None,model='synthetic-model'):
        episode=next(e for e in self.corpus.value['episodes'] if e['id']==episode_id)
        source=episode['sources'][0]
        state={'scope_id':'synthetic:calibration','as_of':NOW,'profile':component('packet'),'preparation':component('preparation'),
            'evidence':[{'text':source['artifact']['text'],'text_digest':source['reference']['sha256']}]}
        rendered=render_question(self.spec,state,'q')
        batch=Batch({'schema_version':'1.0','id':episode_id,'scope_id':'synthetic:calibration','run_id':'fixture','stage_id':'fixture',
            'state':state,'packet_digest':rendered.manifest['packet_digest'],'questions':[rendered.question.value],
            'context':{'provider':'synthetic','transport':'fixture','adapter_version':'1.0','requested_model':'synthetic-model','mode':'provider_shadow',
                'deadline':LATE,'max_request_bytes':65536,'max_response_bytes':65536}})
        probability=value or ('0.99' if episode['labels'][0]['outcome']=='yes' else '0.01')
        result=normalize_response(batch,canonical_bytes({'answers':[{'id':'q','primitive':'proposition_probability','probability':probability}],'resolved_model':model}))
        return TrialObservation(episode_id,case_id,batch=batch,rendered=rendered,result=result,domain_scope=component('domain'),
            model_resolution=component('model-resolution'),measure={'name':'probability','unit':'probability'})

    def reader(self,e,c):self.reads.append(e);return self.trial(e,c)
    def fit(self,plan=None):return fit_thresholds(plan or self.plan,partition=partition_corpus(self.corpus,self.split,'tuning'),read_trial=self.reader)
    def evaluate(self,fit=None,plan=None,reader=None,split=None):
        return evaluate_thresholds(plan or self.plan,fit or self.fit(plan),corpus=self.corpus,split=split or self.split,
            read_trial=reader or self.reader,artifacts=[self.artifact],at=NOW)

    def test_known_binomial_reference_and_tiny_zero_error_sample(self):
        # NIST TN 2119 §4.1 Example 8: 17/20, lower two-sided 95% ~0.621.
        lower=Decimal(lower_accuracy(17,20,alpha='0.025'))
        self.assertGreater(lower,Decimal('0.620'));self.assertLess(lower,Decimal('0.622'))
        self.assertEqual(lower_accuracy(0,20,alpha='0.025'),'0')
        self.assertLess(Decimal(lower_accuracy(1,1,alpha='0.025')),Decimal('0.1'))
        with self.assertRaises(ContractError):lower_accuracy(True,1,alpha='0.05')

    def test_small_lower_bounds_and_high_confidence_stay_exact_decimal_strings(self):
        from matter._rule_values import fragment
        lower=lower_accuracy(1,1,alpha='0.0000005')
        self.assertLessEqual(Decimal(lower),Decimal('0.0000005'))
        self.assertGreaterEqual(Decimal(lower),Decimal('0.000000499999'));fragment(lower,'decimal_string')
        value=self.plan.value;value['confidence']='0.999999';plan=CalibrationPlan(value)
        # Small support correctly fails this stricter plan, rather than raising
        # a serialization error when the internal tail level is below 1e-6.
        fitted=self.fit(plan)
        for tried in fitted.value['tried']:
            for support in tried['support'].values():
                if support is not None:fragment(support['lower_accuracy_bound'],'decimal_string')

    def test_fit_receives_only_tuning_partition_and_never_reads_held_out_trials(self):
        tuning=partition_corpus(self.corpus,self.split,'tuning')
        self.assertTrue(all(self.split.value['assignments'][e['id']]=='tuning' for e in tuning.value['episodes']))
        fitted=self.fit();self.assertEqual(fitted.value['status'],'fitted')
        self.assertTrue(all(self.split.value['assignments'][e]=='tuning' for e in self.reads))
        with self.assertRaises(ContractError):fit_thresholds(self.plan,partition=partition_corpus(self.corpus,self.split,'final'),read_trial=lambda *args:self.fail('Final read'))

    def test_held_out_support_counts_and_exposure_are_explicit(self):
        fitted=self.fit();self.reads=[];report=self.evaluate(fitted)
        self.assertEqual(report['evaluation']['status'],'passed',report['metrics'])
        self.assertTrue(all(self.split.value['assignments'][e]=='qualification' for e in self.reads))
        self.assertEqual(report['metrics']['counts']['errors'],0)
        for s in report['evaluation']['support'].values():self.assertGreaterEqual(s['accepted'],2)
        next_split=SplitManifest(report['next_split'],corpus=self.corpus,previous=self.split)
        values=self.plan.value;values['split_digest']=next_split.digest;plan=CalibrationPlan(values)
        fit=fit_thresholds(plan,partition=partition_corpus(self.corpus,next_split,'tuning'),read_trial=self.reader)
        with self.assertRaises(ContractError):self.evaluate(fit,plan=plan,split=next_split)

    def test_high_confidence_wrong_and_tiny_zero_error_support_never_pass(self):
        fitted=self.fit()
        wrong=self.evaluate(fitted,reader=lambda e,c:self.trial(e,c,value='0.99' if int(e[1:])%2 else '0.01'))
        self.assertEqual(wrong['evaluation']['status'],'failed');self.assertGreater(wrong['metrics']['counts']['errors'],0)
        values=self.plan.value;values['target_accuracy']={'positive':'0.9','negative':'0.9'};plan=CalibrationPlan(values)
        fit=self.fit(plan);self.assertEqual(fit.value['status'],'fitted')
        report=self.evaluate(fit,plan=plan);self.assertEqual(report['evaluation']['status'],'failed')

    def test_missing_provider_results_keep_denominators_and_fail_declared_coverage(self):
        fitted=self.fit();report=self.evaluate(fitted,reader=lambda e,c:None)
        self.assertEqual(report['evaluation']['status'],'failed')
        self.assertEqual(report['metrics']['counts']['failures']['missing'],report['metrics']['counts']['scheduled'])
        self.assertEqual(report['metrics']['counts']['accepted'],0)

    def test_changed_model_or_renderer_cannot_reuse_fitted_state(self):
        fitted=self.fit();report=self.evaluate(fitted,reader=lambda e,c:self.trial(e,c,model='different-model'))
        self.assertEqual(report['evaluation']['status'],'failed');self.assertGreater(report['metrics']['counts']['failures']['mismatched'],0)
        value=self.plan.value;value['identity']['renderer']['version']='2.0';plan=CalibrationPlan(value)
        with self.assertRaises(ContractError):self.evaluate(fitted,plan=plan)

    def test_duplicated_episode_does_not_double_independent_support(self):
        before=self.evaluate();value=self.corpus.value;original=value['episodes'][0];copy=deepcopy(original);copy['id']='copy-of-e0';value['episodes'].append(copy)
        corpus=FrozenCorpus(value);split=make_splits(corpus,identity='fixture-split',revision=1,seed='fixed-qualification',weights=self.split.value['weights'])
        values=self.plan.value;values.update(corpus_digest=corpus.sha256,split_digest=split.digest);plan=CalibrationPlan(values)
        self.corpus,self.split,self.plan=corpus,split,plan
        fitted=self.fit();after=self.evaluate(fitted)
        self.assertEqual(before['evaluation']['support'],after['evaluation']['support'])

    def test_teacher_only_references_fail_held_out_independence(self):
        value=self.corpus.value
        for e in value['episodes']:
            if self.split.value['assignments'][e['id']]=='qualification':e['labels'][0].update(origin='teacher',reviewer={'kind':'model','role':'synthetic-teacher'})
        self.corpus=FrozenCorpus(value);self.split=make_splits(self.corpus,identity='fixture-split',revision=1,seed='fixed-qualification',weights=self.split.value['weights'])
        value=self.plan.value;value.update(corpus_digest=self.corpus.sha256,split_digest=self.split.digest);self.plan=CalibrationPlan(value)
        report=self.evaluate();self.assertEqual(report['evaluation']['status'],'failed');self.assertEqual(report['evaluation']['labels'],'mixed')

    def test_certificate_requires_actual_exact_host_review_and_does_not_install(self):
        report=self.evaluate()
        h=qualification_fixtures.QualificationTests('runTest');h.setUp();self.addCleanup(h.doCleanups)
        artifact=h.record('calibration-artifact',{'schema':component('artifact'),'value':{'synthetic':True}})
        report['evaluation']['artifacts']=[pin(artifact)]
        review=h.record('calibration-review',domain('semantic-qualification-evaluation',report['evaluation']))
        kwargs=dict(review=pin(review),reviewers=[h.reviewer],namespace='example',identity='calibrated-fixture',version='1.0',description='Synthetic candidate only.',valid_from=EARLY,valid_until=LATE)
        with h.f.storage.snapshot() as view,patch.object(h.service,'commit') as install:
            candidate=certificate_from_review(view,report,**kwargs)
            self.assertEqual(candidate.value['identity'],self.plan.value['identity']);install.assert_not_called()
            wrong=deepcopy(report);wrong['evaluation']['identity']['renderer']['version']='2.0'
            with self.assertRaises(ContractError):certificate_from_review(view,wrong,**kwargs)
            with self.assertRaises(ContractError):certificate_from_review(view,report,**{**kwargs,'reviewers':[component('not-admitted')]})
            failed=deepcopy(report);failed['evaluation']['status']='failed'
            with self.assertRaises(ContractError):certificate_from_review(view,failed,**kwargs)
