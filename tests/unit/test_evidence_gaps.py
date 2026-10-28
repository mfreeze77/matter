"""MAT-022 unchanged-work suppression and explicit bounded retry declarations."""
from copy import deepcopy
import unittest
from matter.investigation import InvestigationDefinition
from matter.contracts import ContractError
from rule_helpers import component,EARLY,NOW,LATE

class EvidenceGapTests(unittest.TestCase):
    def value(self):
        matter={'scope_id':'synthetic:gap','namespace':'example','record_type':'matter','id':'subject','revision':1}
        return {'schema_version':'1.0','namespace':'example','id':'gap','version':'1.0','matter':matter,
            'proposition':{'schema':component('proposition'),'value':'Required source is missing.'},'inputs':[],
            'requirements':[{'id':'counter','description':'Obtain a required counterexample.','counterevidence':True}],
            'candidates':[],'retry_at':[NOW],'information_gain_hypothesis':'Unverified hypothesis only.'}
    def test_cosmetic_changes_and_budgetless_time_do_not_create_new_work(self):
        value=self.value();one=InvestigationDefinition(value);value['version']='2.0';value['information_gain_hypothesis']='A different hypothesis.'
        two=InvestigationDefinition(value);self.assertEqual(one.work_key(EARLY),two.work_key(EARLY))
        self.assertEqual(one.work_key(NOW),one.work_key(LATE));self.assertNotEqual(one.work_key(EARLY),one.work_key(NOW))
    def test_changed_actual_input_and_proposition_are_explicit_new_work(self):
        value=self.value();one=InvestigationDefinition(value)
        value['inputs']=[{'scope_id':'synthetic:gap','namespace':'example','record_type':'observation','id':'new-source','digest':'a'*64}]
        self.assertNotEqual(one.work_key(NOW),InvestigationDefinition(value).work_key(NOW))
    def test_no_requirements_and_unordered_retry_points_are_rejected(self):
        for update in ({'requirements':[]},{'retry_at':[LATE,EARLY]},{'namespace':'matter.internal'}):
            with self.assertRaises(ContractError):InvestigationDefinition({**self.value(),**update})
