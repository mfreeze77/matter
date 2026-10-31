"""MAT-049 source questions keep actor/provision and client context separate."""
from copy import deepcopy
import unittest

from matter.civic_attention import source_questions, project_source
from matter.contracts import ContractError


class CivicAttentionTests(unittest.TestCase):
    def projection(self):
        return {'qualification_status':'unknown','consequential_use':False,'comparison':None,
            'batch_digest':'a'*64,'result_digest':'b'*64,'questions':[
              {'family':'civic.stage','status':'answered','answer':{'choice':'pending','probabilities':{'pending':'0.98','recommendation':'0.01','recorded_action':'0','unknown':'0.01'}}},
              {'family':'civic.stance','status':'answered','answer':{'choice':'proponent','probabilities':{'proponent':'0.9','opponent':'0','neutral':'0','unknown':'0.1'}}}]}

    def test_stage_and_stance_are_explicit_distinct_questions_without_client_inputs(self):
        specs=source_questions();self.assertEqual(len(specs),4)
        for spec in specs:
            paths=[f['path'] for f in spec.value['required_fields']]
            self.assertNotIn(['comparison'],paths)
        stance=next(s for s in specs if s.value['family']=='civic.stance')
        unknown=next(x for x in stance.value['criteria'] if x['id']=='unknown')
        self.assertIn('individual members',unknown['description'])
        neutral=next(x for x in stance.value['criteria'] if x['id']=='neutral')
        self.assertIn('expressly',neutral['description'])

    def test_even_reported_completed_action_never_grants_legal_authority(self):
        value=self.projection();value['questions'][0]['answer']={'choice':'recorded_action','probabilities':{'recorded_action':'0.99'}}
        p=project_source(value)
        self.assertEqual(p['proposed_stage'],'recorded_action')
        self.assertEqual(p['legal_status'],'unknown');self.assertFalse(p['consequential_use'])
        self.assertEqual(p['proposed_actions'],[])

    def test_low_probability_or_missing_stance_is_unknown_not_neutral(self):
        value=self.projection();value['questions'][1]['answer']['probabilities']['proponent']='0.79'
        self.assertEqual(project_source(value)['proposed_stance'],'unknown')
        value['questions'][1]['answer']=None
        self.assertEqual(project_source(value)['proposed_stance'],'unknown')

    def test_source_projection_refuses_audience_contamination_or_forged_qualification(self):
        for field,value in [('comparison',{'audience':'client'}),('qualification_status','qualified')]:
            s=self.projection();s[field]=value
            with self.assertRaises(ContractError):project_source(s)
