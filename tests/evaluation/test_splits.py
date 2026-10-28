"""MAT-037 deliberate cross-episode leakage, frozen revisions and paired arms."""
from copy import deepcopy
from pathlib import Path
import unittest
from matter.canonical import canonical_digest
from matter.contracts import ContractError
from matter.evaluation.corpus import load_jsonl,FrozenCorpus
from matter.evaluation.splits import lineage_groups,make_splits,SplitManifest
from matter.evaluation.arms import ArmManifest,compare_arms
from rule_helpers import component,LATE

ROOT=Path(__file__).resolve().parents[1]/'fixtures'/'evaluation'


class SplitTests(unittest.TestCase):
    def setUp(self):self.corpus=load_jsonl((ROOT/'episodes.jsonl').read_bytes())
    def splits(self,**kwargs):return make_splits(self.corpus,identity='synthetic-splits',revision=1,seed='frozen-seed',**kwargs)
    def arms(self):
        cases=[]
        for episode in self.corpus.value['episodes']:
            for case in episode['cases']:
                if case['eligibility']['state']=='eligible':
                    cases.append({'episode_id':episode['id'],'case_id':case['id'],'as_of':episode['boundary']['end'],
                        'packet_digest':canonical_digest({'case':case['id']},'synthetic.packet.v1'),'packet_profile':component('packet')})
        a={'schema_version':'1.0','id':'baseline','kind':'A','corpus_digest':self.corpus.sha256,'policy':component('same-policy'),
            'semantic_families':[],'cases':cases,'retrieval_experiment':None}
        b=deepcopy(a);b.update(id='candidate',kind='B',semantic_families=[component('semantic')]);return a,b

    def test_reproducible_groups_counts_and_explicit_new_seed_revision(self):
        first=self.splits();self.assertEqual(first.digest,self.splits().digest)
        report=first.report(corpus=self.corpus)
        self.assertEqual(sum(p['episodes'] for p in report['partitions'].values()),len(self.corpus.value['episodes']))
        value=first.value;value['seed']='new';value['previous_digest']=first.digest
        with self.assertRaises(ContractError):SplitManifest(value,corpus=self.corpus,previous=first)
        second=make_splits(self.corpus,identity='synthetic-splits',revision=2,seed='new',previous=first)
        self.assertNotEqual(first.digest,second.digest);self.assertEqual(second.value['previous_digest'],first.digest)

    def test_renamed_copy_same_bytes_cannot_cross_a_partition(self):
        value=self.corpus.value;copy=deepcopy(value['episodes'][0]);copy['id']='renamed-copy'
        # Sharing source snapshots and occurrence groups is legitimate corpus
        # input. The attempted split itself must refuse that leakage.
        value['episodes'].append(copy);corpus=FrozenCorpus(value)
        splits=make_splits(corpus,identity='leak',revision=1,seed='a')
        members=next(g for g in lineage_groups(corpus) if copy['id'] in g)
        self.assertIn(value['episodes'][0]['id'],members)
        bad=splits.value;original=bad['assignments'][members[0]]
        bad['assignments'][copy['id']]=next(p for p in ('tuning','qualification','final') if p!=original)
        with self.assertRaises(ContractError) as caught:SplitManifest(bad,corpus=corpus)
        self.assertIn('leakage',caught.exception.detail)

    def test_held_out_exposure_is_retained_and_group_wide(self):
        first=self.splits();identity=next(iter(first.value['assignments']))
        exposure={'episode_ids':[identity],'reason':'Question rewritten after inspecting this episode.',
            'at':LATE,'question':component('rewritten-question')}
        second=make_splits(self.corpus,identity=first.value['id'],revision=2,seed=first.value['seed'],previous=first,exposures=[exposure])
        report=second.report(corpus=self.corpus);self.assertFalse(report['held_out_usable'][identity])
        with self.assertRaises(ContractError):make_splits(self.corpus,identity=first.value['id'],revision=3,seed='x',previous=second)

    def test_equal_principal_packets_and_hidden_attachment_refusal(self):
        a,b=self.arms();first=ArmManifest(a,corpus=self.corpus);second=ArmManifest(b,corpus=self.corpus)
        self.assertEqual(compare_arms(first,second)['comparison'],'principal')
        b['cases'][0]['packet_digest']='a'*64
        with self.assertRaises(ContractError):compare_arms(first,ArmManifest(b,corpus=self.corpus))
        a['retrieval_experiment']=b['retrieval_experiment']='retrieval-ablation-v1'
        result=compare_arms(ArmManifest(a,corpus=self.corpus),ArmManifest(b,corpus=self.corpus))
        self.assertEqual(result['comparison'],'separate_retrieval');self.assertFalse(result['matched_packets'])

    def test_missing_case_and_unavailable_target_refused(self):
        a,b=self.arms();a['cases'].pop()
        with self.assertRaises(ContractError):ArmManifest(a,corpus=self.corpus)
        a,b=self.arms();a['cases'][0]['as_of']={'state':'known','value':'2000-01-01T00:00:00Z','precision':'second'}
        with self.assertRaises(ContractError):ArmManifest(a,corpus=self.corpus)

    def test_reseed_never_relabels_former_tuning_as_clean_held_out(self):
        first=self.splits()
        second=make_splits(self.corpus,identity=first.value['id'],revision=2,seed='different-seed',previous=first)
        for identity,partition in first.value['assignments'].items():
            if partition=='tuning':self.assertFalse(second.report(corpus=self.corpus)['held_out_usable'][identity])
        erased=second.value;erased['ever_tuning']=[]
        with self.assertRaises(ContractError):SplitManifest(erased,corpus=self.corpus,previous=first)
        orphan=first.value;orphan['revision']=5
        with self.assertRaises(ContractError):SplitManifest(orphan,corpus=self.corpus)
