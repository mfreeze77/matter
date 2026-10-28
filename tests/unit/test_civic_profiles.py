"""MAT-046 integrity and authority boundaries over actual host controls."""
from copy import deepcopy
import subprocess
import sys
import unittest

from matter._rule_values import domain,runtime_schema
from matter.canonical import canonical_bytes
from matter.civic import CivicProfile,CivicRegistry
from matter.contracts import ContractError
from matter.controls import control_effect
from matter.storage import entity_ref,pin
from control_helpers import control_command
from integration.helpers import _in_scope
from rule_helpers import component
from unit import test_context_scopes as fixtures

AT={'state':'known','value':'2050-01-01T00:00:00Z','precision':'second'}
SELECTOR={'jurisdiction':'synthetic:region','body':'synthetic:board','category':'synthetic:school-policy','act':'synthetic:adopt'}


class CivicProfilesTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.ContextScopeTests('runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.f=self.h.fixture;self.sequence=0

    def value(self,identity='base',*,selector=None,status='unreviewed',allowed=True):
        selector=selector or SELECTOR
        period={'start':self.f.now,'end':{'state':'unknown','reason':'not_applicable'},'bounds':'closed_open'}
        return {'schema_version':'1.0','namespace':'synthetic:civic','id':identity,'version':'1.0',
            'schema':deepcopy(runtime_schema('civic-profile')[0]),'common_profile':self.f.profile.reference,
            'producer':component('synthetic-crawler'),'producer_code_sha256':'a'*64,
            'scope_id':self.f.storage.scope_id,'applies':selector,'effective':period,'available_at':self.f.now,
            'source_stages':['synthetic:recommendation','synthetic:parser-final'], 'parents':[],
            'assertions':[{'id':'power','selector':selector,'capability':'synthetic:final-adoption',
                'allowed':allowed,'effective':period,'disposition':status,
                'sources':[{'reference':pin(self.f.source),'sha256':self.f.source['body']['content']['digest']}],
                'attestation':None,'overrides':[]}]}

    def profile(self,value):return CivicProfile(value,profile=self.f.profile)

    def review(self,value,*,change=None):
        self.sequence+=1;draft=self.profile(value)
        payload={'scope_id':self.f.storage.scope_id,'assertion':draft.assertion_reference('power'),
            'common_profile':self.f.profile.reference,'disposition':'reviewed_host','reviewed_at':self.f.now}
        if change:change(payload)
        command=_in_scope(control_command('civic-review-'+str(self.sequence),self.f.authority,
            targets=[self.f.source],action='disposition',kind='decision',now=self.f.now),self.f.storage.scope_id)
        command['actor']=self.f.actor;command['body']['control']['body']['actor']=self.f.actor
        command['body']['control']['body']['effect']=control_effect('disposition','Explicit synthetic host authority review.',payload=domain('civic-review',payload))
        result=self.f.controls.apply(self.f.controls.prepare(command))
        self.assertEqual(result['status'],'success',result)
        reviewed=deepcopy(value);reviewed['assertions'][0].update(disposition='reviewed_host',attestation=result['body']['control'])
        return reviewed

    def resolve(self,profiles,*,selector=None,at=AT,as_of=AT,root=None):
        root=root or profiles[-1];targets=[entity_ref(s['reference']) for p in profiles for a in p.value['assertions'] for s in a['sources']]
        targets += [entity_ref(a['attestation']) for p in profiles for a in p.value['assertions'] if a['attestation']]
        targets=list({canonical_bytes(t):t for t in targets}.values())
        token=self.f.controls.capture(actor=self.f.actor,authority=entity_ref(self.f.authority),capability='read',targets=targets)
        with self.f.storage.snapshot() as view:
            return CivicRegistry(profiles).resolve(root.reference,selector=selector or SELECTOR,capability='synthetic:final-adoption',
                at=at,as_of=as_of,view=view,controls=self.f.controls,token=token)

    def test_parser_final_or_supported_source_does_not_replace_reviewed_host_authority(self):
        for status in ('unknown','unreviewed','supported_source','disputed','withdrawn'):
            result=self.resolve([self.profile(self.value(status=status))])
            self.assertFalse(result['eligible_for_host_proposal'],status)
        result=self.resolve([self.profile(self.review(self.value()))])
        self.assertTrue(result['eligible_for_host_proposal'],result)
        self.assertFalse(result['consequential_use']);self.assertEqual(result['proposed_actions'],[])

    def test_review_must_bind_exact_assertion_source_scope_and_time(self):
        wrong=self.review(self.value(),change=lambda p:p['assertion'].update(digest='b'*64))
        with self.assertRaises(ContractError):self.resolve([self.profile(wrong)])
        wrong=self.review(self.value('other'),change=lambda p:p.update(reviewed_at={'state':'known','value':'2080-01-01T00:00:00Z','precision':'second'}))
        self.assertFalse(self.resolve([self.profile(wrong)])['eligible_for_host_proposal'])
        mutated=self.review(self.value('mutated'));mutated['assertions'][0]['sources'][0]['sha256']='b'*64
        with self.assertRaises(ContractError):self.resolve([self.profile(mutated)])
        foreign=self.value();foreign['assertions'][0]['sources'][0]['reference']['scope_id']='foreign'
        with self.assertRaises(ContractError):self.profile(foreign)

    def test_explicit_narrow_override_is_order_independent_and_cannot_broaden(self):
        wide={k:'*' for k in SELECTOR};parent=self.profile(self.review(self.value('parent',selector=wide,allowed=False)))
        child=self.value('child');child['parents']=[parent.reference]
        child['assertions'][0]['overrides']=[parent.assertion_reference('power')]
        child=self.profile(self.review(child))
        first=self.resolve([parent,child]);self.assertTrue(first['eligible_for_host_proposal'],first)
        # Constructor order does not select a policy. Root is explicit.
        self.assertEqual(first,self.resolve([child,parent],root=child))
        bad=self.value('bad',selector=wide);bad['parents']=[child.reference]
        with self.assertRaises(ContractError):self.resolve([parent,child,self.profile(bad)])

    def test_equal_applicability_conflict_is_not_most_permissive_choice(self):
        p=self.profile(self.review(self.value('p',allowed=False)))
        child=self.value('c');child['parents']=[p.reference];child=self.profile(self.review(child))
        result=self.resolve([p,child]);self.assertEqual(result['state'],'conflict')
        self.assertFalse(result['eligible_for_host_proposal'])

    def test_missing_changed_parent_and_schema_or_common_profile_are_refused(self):
        parent=self.profile(self.value());v=self.value('child');v['parents']=[parent.reference]
        with self.assertRaises(ContractError):self.resolve([self.profile(v)])
        v['parents'][0]['digest']='b'*64
        with self.assertRaises(ContractError):self.resolve([parent,self.profile(v)])
        for field in ('schema','common_profile'):
            bad=self.value();bad[field]['digest']='b'*64
            with self.assertRaises(ContractError):self.profile(bad)

    def test_body_and_effective_period_boundaries_preserve_unknown(self):
        profile=self.profile(self.review(self.value()))
        result=self.resolve([profile],selector={**SELECTOR,'body':'synthetic:joint-session'})
        self.assertEqual(result['state'],'unknown');self.assertFalse(result['eligible_for_host_proposal'])
        v=self.value('period');v['effective']['end']={'state':'known','value':'2030-01-01T00:00:00Z','precision':'second'};v=self.review(v)
        self.assertFalse(self.resolve([self.profile(v)])['eligible_for_host_proposal'])

    def test_common_core_imports_without_civic_adapter(self):
        code="import sys; import matter, matter.profiles; assert 'matter.civic' not in sys.modules"
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_registered_withdrawal_or_unavailable_parent_never_reuses_old_review(self):
        value=self.review(self.value());profile=self.profile(value)
        old=value['assertions'][0]['attestation']
        command=_in_scope(control_command('withdraw-civic-review',self.f.authority,targets=[self.f.source],
            action='disposition',kind='decision',supersedes=[old],now=self.f.now),self.f.storage.scope_id)
        command['actor']=self.f.actor;command['body']['control']['body']['actor']=self.f.actor
        command['body']['control']['body']['effect']=control_effect('disposition','Withdraw synthetic review.',
            payload=domain('civic-review',{'scope_id':self.f.storage.scope_id,'assertion':profile.assertion_reference('power'),
                'common_profile':self.f.profile.reference,'disposition':'withdrawn','reviewed_at':self.f.now}))
        result=self.f.controls.apply(self.f.controls.prepare(command));self.assertEqual(result['status'],'success',result)
        self.assertFalse(self.resolve([profile])['eligible_for_host_proposal'])
        parent_value=self.value('future-parent');parent_value['available_at']={'state':'known','value':'2080-01-01T00:00:00Z','precision':'second'}
        parent=self.profile(parent_value);child=self.value('past-child');child['parents']=[parent.reference]
        child=self.profile(self.review(child))
        self.assertFalse(self.resolve([parent,child])['eligible_for_host_proposal'])

    def test_review_cannot_be_transplanted_to_changed_profile_applicability(self):
        value=self.review(self.value())
        value['effective']['start']={'state':'known','value':'2025-01-01T00:00:00Z','precision':'second'}
        with self.assertRaises(ContractError):self.resolve([self.profile(value)])
