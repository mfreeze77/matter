"""Generate invented, unreviewed civic contracts; no authority or I/O adapters."""
from pathlib import Path
import json
from matter._rule_values import runtime_schema
from matter.canonical import source_digest
from matter.civic import CivicProfile
from matter.profiles import ProfileDefinition
from matter.rules import RuleRegistry,SchemaRegistry

root=Path(__file__).resolve().parent
limits={'max_calls':0,'max_input_bytes':0,'max_output_bytes':0,'max_evidence':0,'max_elapsed_ms':0}
component={'semantic_version':'1.0','description':'Invented civic contract settings; no rule executes.',
 'rules':[],'parameters':{},'dependencies':[],'outputs':[],'data_scopes':[],'capabilities':[],
 'conflict_resolvers':[],'resource_limits':limits,'lifecycle_extensions':[],
 'conformance_cases':[{'name':'contract-only','invariant':'No authority without actual host review.'}]}
common=ProfileDefinition({'schema_version':'1.0','namespace':'synthetic','profile_id':'civic-base','semantic_version':'1.0',
 'description':'Synthetic settings only.','components':{'evidence':component},'required_outputs':[],
 'resource_limits':limits,'incomplete_evaluation':'retain_unresolved'},rules=RuleRegistry(),schemas=SchemaRegistry())
def save(name,value):(root/name).write_text(json.dumps(value,indent=2)+'\n')
save('common-profile.json',common.value)
for identity,allowed,status,body in [('recommendation-only',False,'unreviewed','synthetic:advisory'),
 ('act-specific-final',True,'unreviewed','synthetic:board'),('unknown-capacity',False,'unknown','synthetic:unknown'),
 ('joint-body-change',False,'unreviewed','*')]:
 selector={'jurisdiction':'synthetic:region','body':body,'category':'synthetic:school-policy','act':'synthetic:adopt'}
 period={'start':{'state':'known','value':'2026-01-01T00:00:00Z','precision':'second'},
         'end':{'state':'unknown','reason':'not_applicable'},'bounds':'closed_open'}
 value={'schema_version':'1.0','namespace':'synthetic:civic','id':identity,'version':'1.0',
  'schema':runtime_schema('civic-profile')[0],'common_profile':common.reference,
  'producer':{'namespace':'synthetic','id':'contract-examples','version':'1.0','digest':source_digest(Path(__file__).read_bytes())},
  'producer_code_sha256':source_digest(Path(__file__).read_bytes()),'scope_id':'synthetic:civic','applies':selector,
  'effective':period,'available_at':period['start'],'source_stages':['synthetic:recommendation','synthetic:reported-final'],
  'parents':[],'assertions':[{'id':'power','selector':selector,'capability':'synthetic:final-adoption','allowed':allowed,
   'effective':period,'disposition':status,'sources':[{'reference':{'scope_id':'synthetic:civic','namespace':'synthetic:sources',
    'record_type':'observation','id':'authority-source','digest':'a'*64},'sha256':'a'*64}],'attestation':None,'overrides':[]}]}
 if identity=='joint-body-change':
  from copy import deepcopy
  first=deepcopy(value['assertions'][0]);first['selector']['body']='synthetic:advisory'
  first['effective']['end']={'state':'known','value':'2030-01-01T00:00:00Z','precision':'second'}
  second=deepcopy(value['assertions'][0]);second['id']='later-body';second['selector']['body']='synthetic:board'
  second['effective']['start']={'state':'known','value':'2030-01-01T00:00:00Z','precision':'second'}
  value['assertions']=[first,second]
 CivicProfile(value,profile=common);save(identity+'.json',value)
print('Four invented unreviewed civic manifests validated against the common profile.')
