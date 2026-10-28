"""MAT-024 sequential core conformance, explicitly not provider qualification."""
from pathlib import Path
import unittest
from matter.canonical import loads
from matter.contracts import ContractError
from matter.evaluation.corpus import FrozenCorpus
from matter.replay import ReplayManifest,run_replay
import replay_helpers as helpers

ROOT=Path(__file__).resolve().parents[1]/'fixtures'/'conformance'


class ChronologicalReplayTests(unittest.TestCase):
    def manifest(self):return loads((ROOT/'late-cancellation.json').read_bytes())
    def run_case(self,value,corpus=None):
        driver=helpers.CoreReplayDriver();self.addCleanup(driver.close)
        corpus=corpus or FrozenCorpus(helpers.corpus_value())
        return run_replay(ReplayManifest(value,corpus=corpus),corpus=corpus,driver=driver)

    def test_fresh_stores_reproduce_frames_without_extra_delivery_records(self):
        first=self.run_case(self.manifest());second=self.run_case(self.manifest())
        self.assertTrue(first['passed'],first['failures']);self.assertEqual(first,second)
        self.assertTrue(all(x['frame']['delivery_count']==0 for x in first['frames']))
        self.assertTrue(all(x=='not_run' for x in first['gates'].values()))
        self.assertEqual(first['frames'][0]['frame'],first['frames'][1]['frame'])
        self.assertNotEqual(first['frames'][1]['frame'],first['frames'][2]['frame'])
        self.assertEqual(first['frames'][0]['frame']['conclusions'],['supported'])
        self.assertEqual(first['frames'][0]['frame']['transitions'],['applied:establish'])
        self.assertEqual(first['frames'][2]['frame']['transitions'],['applied:establish','applied:resolve'])

    def test_future_source_cannot_be_requested_at_earlier_cut(self):
        value=self.manifest();value['steps'][0]['requires'].append({'episode_id':'late-published','observation_id':'late-cancel'})
        with self.assertRaises(ContractError) as caught:self.run_case(value)
        self.assertEqual(caught.exception.code,'E_EVIDENCE_UNAVAILABLE')

    def test_no_labels_or_future_source_metadata_reach_driver(self):
        corpus=FrozenCorpus(helpers.corpus_value());value=self.manifest();value['steps']=value['steps'][:1]
        class Spy:
            reference=helpers.CoreReplayDriver.reference;mode='deterministic';capture_only=True
            def run_step(self,step):
                self_test.assertNotIn('expected',step)
                self_test.assertEqual([x['observation']['id'] for x in step['inputs']],['initial'])
                self_test.assertNotIn('cases',step);self_test.assertNotIn('labels',step)
                return value['steps'][0]['expected']
        self_test=self
        self.assertTrue(run_replay(ReplayManifest(value,corpus=corpus),corpus=corpus,driver=Spy())['passed'])

    def test_clock_regression_corrupt_corpus_and_provider_mode_refused(self):
        value=self.manifest();value['steps'][1]['as_of']=helpers.EARLY
        with self.assertRaises(ContractError):ReplayManifest(value,corpus=FrozenCorpus(helpers.corpus_value()))
        value=self.manifest();value['corpus_digest']='a'*64
        with self.assertRaises(ContractError):ReplayManifest(value,corpus=FrozenCorpus(helpers.corpus_value()))
        value=self.manifest();value['mode']='provider_shadow'
        with self.assertRaises(ContractError):ReplayManifest(value,corpus=FrozenCorpus(helpers.corpus_value()))

    def test_second_domain_uses_different_declared_edges_on_same_operations(self):
        driver=helpers.CoreReplayDriver(domain='maintenance');self.addCleanup(driver.close)
        value=self.manifest();self.assertNotEqual(value['profiles'],[driver.f.profile.reference])
        value['driver']=driver.reference;value['profiles']=[driver.f.profile.reference]
        corpus=FrozenCorpus(helpers.corpus_value())
        result=run_replay(ReplayManifest(value,corpus=corpus),corpus=corpus,driver=driver)
        self.assertTrue(result['passed'],result['failures'])
        self.assertEqual(driver.h.episode.current()['value']['value']['state'],'synthetic:maintenance:resolved')

    def test_recorded_judgment_cannot_declare_itself_qualified(self):
        value=self.manifest();value['mode']='recorded'
        value['steps'][0]['recorded_judgments']=[{'question':helpers.component('recorded'),
            'answer':{'label':'supported'},'qualification':'qualified'}]
        with self.assertRaises(ContractError):ReplayManifest(value,corpus=FrozenCorpus(helpers.corpus_value()))

    def test_recorded_answers_must_be_known_and_bound_to_required_observations(self):
        value=self.manifest();value['mode']='recorded';value['steps']=value['steps'][:1]
        judgment={'question':helpers.component('recorded'),'answer':{'label':'recovered'},'qualification':'unknown',
            'recorded_at':helpers.LATE,'observations':[{'episode_id':'late-published','observation_id':'late-cancel'}]}
        value['steps'][0]['recorded_judgments']=[judgment]
        with self.assertRaises(ContractError):ReplayManifest(value,corpus=FrozenCorpus(helpers.corpus_value()))
        judgment['recorded_at']=helpers.NOW
        with self.assertRaises(ContractError):ReplayManifest(value,corpus=FrozenCorpus(helpers.corpus_value()))
        judgment['observations']=[{'episode_id':'late-published','observation_id':'initial'}]
        manifest=ReplayManifest(value,corpus=FrozenCorpus(helpers.corpus_value()))
        class Recorded:
            reference=helpers.CoreReplayDriver.reference;mode='recorded';capture_only=True
            def run_step(self,step):
                self_test.assertEqual(step['recorded_judgments'][0]['qualification'],'unknown')
                return value['steps'][0]['expected']
        self_test=self
        output=run_replay(manifest,corpus=FrozenCorpus(helpers.corpus_value()),driver=Recorded())
        self.assertEqual(output['gates']['qualification'],'not_run')
