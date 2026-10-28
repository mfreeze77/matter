"""MAT-038 full core replay plus frozen typed faults, never provider accuracy."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from matter.canonical import loads,canonical_digest
from matter.contracts import ContractError
from matter.evaluation.corpus import FrozenCorpus
from matter.evaluation.arms import ArmManifest
from matter.evaluation.splits import make_splits
from matter.evaluation.offline import run_offline,OfflineReport
from matter.replay import ReplayManifest,run_replay
from matter.semantic import Batch
from semantic import test_contracts as wires
import replay_helpers as core

ROOT=Path(__file__).resolve().parents[1]/'fixtures'
SCENARIOS={'positive':'successful','abstain':'abstained','timeout':'failed','malformed':'failed','partial':'failed',
    'conflicting':'abstained','changed-source':'stale','missing-certificate':'abstained'}


class OfflineHarnessTests(unittest.TestCase):
    def inputs(self):
        value=core.corpus_value();episode=value['episodes'][0]
        episode['cases']=[{'id':name,'family':'attention','target_observation_ids':['initial'],
            'eligibility':{'state':'eligible','reason':'Synthetic fault/conformance case.'}} for name in SCENARIOS]
        corpus=FrozenCorpus(value);jobs=[];cases=[];recordings={}
        raw=loads((ROOT/'evaluation/provider_responses.json').read_bytes())['responses']
        for name,status in SCENARIOS.items():
            # The frozen state explicitly binds the same eligible first prefix;
            # no source labels or golden expectations go into the batch.
            state={'synthetic':True,'evidence':[s for s in episode['sources'] if s['reference']['id']=='initial-source'],'scenario':name}
            digest=canonical_digest(state,'matter.semantic.packet.v1')
            questions=[{**wires.make_question(identity=head,state=state),'family':'synthetic:'+head} for head in ('support','contradiction')]
            batch=wires.make_batch().value
            batch.update(id=name,scope_id=corpus.value['scope_id'],state=state,packet_digest=digest,questions=questions)
            batch['context']['deadline']=core.LATE
            job={'id':name,'episode_id':episode['id'],'case_id':name,'at':core.NOW,'batch':batch,'scenario':name,'expected_status':status}
            if name=='timeout':job['fault']='timeout'
            jobs.append(job);cases.append({'episode_id':episode['id'],'case_id':name,'as_of':core.NOW,
                'packet_digest':digest,'packet_profile':core.component('frozen-offline-prefix')})
            source=raw[name if name in raw else 'positive'];recordings[Batch(batch).digest]=source.encode()
        a={'schema_version':'1.0','id':'A','kind':'A','corpus_digest':corpus.sha256,'policy':core.component('shared-core-policy'),
            'semantic_families':[],'cases':cases,'retrieval_experiment':None}
        b=deepcopy(a);b.update(id='B',kind='B',semantic_families=[core.component('synthetic-shadow-family')])
        return corpus,make_splits(corpus,identity='offline',revision=1,seed='frozen'),ArmManifest(a,corpus=corpus),ArmManifest(b,corpus=corpus),jobs,recordings

    def admit(self,job,batch,result):
        # Deliberately declared offline admission fixture; no empirical method
        # certificate is issued. Positive/negative heads are separate predicates.
        if job['scenario']=='changed-source':return {'status':'stale','reason':'fixture:source_changed_after_packet'}
        if job['scenario']=='missing-certificate':return {'status':'abstained','reason':'certificate_missing'}
        values={d['id']:d['answer']['probability'] for d in result.value['diagnostics']}
        if values=={'support':'0.99','contradiction':'0.01'}:return {'status':'successful','reason':'fixture:synthetic_admitted'}
        return {'status':'abstained','reason':'fixture:ambiguous_or_conflicting_predicates'}

    def run_suite(self,*,recordings_override=None,silent=False):
        corpus,split,a,b,jobs,recordings=self.inputs()
        if recordings_override is not None:recordings=recordings_override
        if silent:
            raw=loads((ROOT/'evaluation/provider_responses.json').read_bytes())['responses']['abstain'].encode()
            recordings={key:raw for key in recordings}
        outputs=TemporaryDirectory();self.addCleanup(outputs.cleanup)
        def episode(arm,episode_id,observations):
            driver=core.CoreReplayDriver()
            try:
                self.assertNotIn('matches_expected_status',str(observations))
                if arm.value['kind']=='A':self.assertEqual(observations,[])
                else:
                    self.assertEqual({o['job_id'] for o in observations},set(SCENARIOS))
                    self.assertTrue(all(o['episode_id']==episode_id for o in observations))
                    if recordings_override is None and not silent:
                        self.assertEqual({o['job_id']:o['status'] for o in observations},SCENARIOS)
                    expected=[j for j in jobs if j['episode_id']==episode_id]
                    self.assertEqual(len(observations),len(expected))
                    for o in observations:
                        self.assertIn(o['status'],('successful','abstained','failed','stale'))
                        self.assertNotIn('expected_status',o)
                manifest=loads((ROOT/'conformance/late-cancellation.json').read_bytes())
                manifest['corpus_digest']=corpus.sha256
                # The principal arms see the same complete chronological core
                # recipe. No unqualified raw result publishes a learned judgment.
                return run_replay(ReplayManifest(manifest,corpus=corpus),corpus=corpus,driver=driver)
            finally:driver.close()
        return run_offline(corpus=corpus,split=split,baseline=a,candidate=b,jobs=jobs,capabilities=wires.capabilities(),
            recordings=recordings,admit=self.admit,run_episode=episode,output=Path(outputs.name)/'run')

    def test_full_episodes_reproduce_and_fault_denominators_reconcile(self):
        first=self.run_suite();second=self.run_suite()
        self.assertEqual(first.digest,second.digest);self.assertTrue(first.value['passed'])
        self.assertEqual(first.value['scheduled'],8)
        self.assertEqual(first.value['counts'],{'successful':1,'abstained':3,'failed':3,'stale':1})
        partial=next(x for x in first.value['attempts'] if x['scenario']=='partial')
        self.assertTrue(any(x['answer'] is not None for x in partial['result']['diagnostics']))
        self.assertEqual(partial['status'],'failed')
        self.assertTrue(all(x=='not_run' for x in first.value['gates'].values()))
        with self.assertRaises(ContractError):OfflineReport({**first.value,'gates':{**first.value['gates'],'qualification':'passed'}})

    def test_missing_recording_is_failed_not_guessed_and_all_silent_fails(self):
        report=self.run_suite(recordings_override={})
        self.assertFalse(report.value['passed']);self.assertEqual(report.value['counts']['failed'],8)
        self.assertTrue(all(x['replay']['passed'] for x in report.value['episodes']))
        quiet=self.run_suite(silent=True)
        self.assertFalse(quiet.value['passed'])
        important=next(a for a in quiet.value['attempts'] if a['scenario']=='positive')
        self.assertEqual(important['status'],'abstained');self.assertFalse(important['matches_expected_status'])
