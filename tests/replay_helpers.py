"""Synthetic portable recipes driving existing Matter services, not toy rules."""
from copy import deepcopy
from pathlib import Path
from matter.canonical import source_digest
from matter.evaluation.corpus import FrozenCorpus
from matter.queries import QueryService
from matter.storage import entity_ref,pin
from integration import test_audience_attention as fixtures
from rule_helpers import NOW,EARLY,LATE,component


class CoreReplayDriver:
    mode='deterministic';capture_only=True
    reference=component('actual-core-replay-v1')
    def __init__(self,*,domain='standard'):
        self.h=fixtures.AudienceAttentionTests('runTest');self.h.setUp()
        self.f=self.h.f
        if domain!='standard':
            from matter.lifecycle import LifecycleDefinition
            from unit.test_attention_deltas import policy_value
            value=self.h.episode.definition.value
            value['namespace']='synthetic:'+domain;value['id']='alternate-lifecycle'
            def rename(x):
                if type(x) is str:return x.replace('example:','synthetic:'+domain+':')
                if type(x) is list:return [rename(i) for i in x]
                if type(x) is dict:return {k:rename(v) if k in ('name','from_states','to_state','initial_state','states','edges') else v for k,v in x.items()}
                return x
            # State and edge labels are opaque declarations; core contracts and
            # operations remain identical across the two synthetic domains.
            for state in value['states']:state['name']=state['name'].replace('example:','synthetic:'+domain+':')
            value['initial_state']=value['initial_state'].replace('example:','synthetic:'+domain+':')
            for edge in value['edges']:
                edge['from_states']=[s.replace('example:','synthetic:'+domain+':') for s in edge['from_states']]
                edge['to_state']=edge['to_state'].replace('example:','synthetic:'+domain+':')
            self.h.episode.install_profile(LifecycleDefinition(value,schemas=self.f.schemas))
            self.h.install_policy(policy_value(self.h.episode.claim_schema.reference,self.f.profile.reference))
            self.reference=component('actual-core-replay-'+domain+'-v1')
        self.events={};self.last=None;self.transitions=[];self.receipts=[]
        self.queries=QueryService(self.f.storage,controls=self.f.controls,assessments=self.f.service)
    def close(self):self.h.doCleanups()
    def run_step(self,step):
        if step['profiles']!=[self.f.profile.reference]:raise AssertionError('Replay changed its actual core profile')
        if 'expected' in step:raise AssertionError('Golden outcome leaked into driver')
        self.f.now=deepcopy(step['as_of']);data=step['input']
        if step['operation']=='synthetic:apply':
            item=next(x for x in step['inputs'] if x['observation']['id']==data['observation_id'])
            observation=item['observation'];identity=observation['id']
            source,occurrence=self.h.episode.event(identity,at=observation['occurred_at'],available_at=observation['available_at'])
            # Source hash comparison proves the actual ingested payload agrees
            # with the frozen bytes, not only a declaration of source usage.
            if source['body']['content']['digest']!=observation['source']['sha256']:raise AssertionError('source bytes changed')
            claim=self.h.episode.claim(identity,self.h.episode.condition_a,data['signal'],source,
                effective=observation['occurred_at'],supersedes=[self.last[1]] if data.get('corrects') and self.last else [])
            assessment=self.h.episode.assess(claim,occurrence,status=data['status'],purpose=self.h.purpose_ref)
            if data.get('edge'):
                _,result=self.h.episode.apply(data['edge'],claim,occurrence,assessment)
                if result.get('outcome')!='applied':raise AssertionError(result)
                self.transitions.append(result['outcome']+':'+data['edge'])
            value,decision,_,_=self.h.evaluate(assessment)
            self.last=(assessment,claim,decision,value)
            self.events[identity]=item
            # Logical receipt identifiers and outcomes are stable; exact native
            # records stay in this fresh SQLite store. No physical clock erasure
            # is applied to the stored records themselves.
            self.receipts.extend([{'id':assessment['id'],'kind':'assessment'},
                {'id':step['id']+':attention','kind':'attention','stage':decision['body']['stage'],
                 'outcome':decision['body']['outcome'],'treatment':value['treatment']}])
        elif step['operation']!='synthetic:inspect':raise AssertionError('unsupported fixture operation')
        assessment,claim,decision,value=self.last
        projection=self.queries.project(entity_ref(self.f.subject),actor=self.f.actor,authority=entity_ref(self.f.authority),
            assessment=pin(assessment),attention=pin(decision))
        return {'conclusions':[p['status'] for p in projection['explanation']['propositions']],
            'receipts':deepcopy(self.receipts),'quiet_reasons':value['reasons'] if value['treatment']=='quiet' else [],
            'transitions':list(self.transitions),'delivery_count':0,
            'sources_used':[{'episode_id':v['episode_id'],'observation_id':k} for k,v in sorted(self.events.items())]}


def corpus_value():
    sources=[];observations=[];occurrences=[]
    for identity,available in [('initial',EARLY),('late-cancel',LATE)]:
        ref={'id':identity+'-source','revision':1,'sha256':source_digest(('Synthetic episode '+identity+'.\n').encode())}
        sources.append({'reference':ref,'available_at':available,'artifact':{'kind':'synthetic','text':'Synthetic episode '+identity+'.\n'}})
        observations.append({'id':identity,'source':ref,'available_at':available,'occurred_at':EARLY,
            'occurrence_ids':[identity+'-event'],'provenance_groups':[identity+'-lineage'],'derivation':'root','parents':[]})
        occurrences.append({'id':identity+'-event','observation_ids':[identity]})
    return {'schema_version':'matter.episode-corpus.v1','id':'late-published-cancellation','scope_id':'synthetic:claims',
        'extraction_profile':component('synthetic-replay-input'), 'episodes':[{'id':'late-published','scope_id':'synthetic:claims',
            'boundary':{'start':EARLY,'end':LATE,'bounds':'closed'},'sources':sources,'observations':observations,'occurrences':occurrences,
            'cases':[{'id':'important-change','family':'attention','target_observation_ids':['initial'],
                'eligibility':{'state':'eligible','reason':'Synthetic conformance only.'}}],'labels':[]}]}
