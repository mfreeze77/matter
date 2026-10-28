"""Explicit six-call synthetic interpretation diagnostic, not qualification.

Reuses PR18 inputs and MAT-033/034 specifications. These are authored frozen
JSON packets through the typed renderer/executor, not published assessments or
an integrated StateCivics run. The only sink is the specified artifact directory.
Default mode is preflight; --live is required to contact the selected provider.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import json
import shlex
import time

from matter.canonical import canonical_bytes, canonical_digest, source_digest
from matter.semantic import Batch, execute_batch
from matter.semantic.families import ShadowResult
from matter.semantic.families.evidence import claim_evidence_questions
from matter.semantic.families.attention import contribution_questions
from matter.semantic.providers.typesafe import TypeSafeHTTPExecutor, ADAPTER_VERSION
from matter.semantic.rendering import render_question


def instant(value):
    return {'state':'known','value':value,'precision':'second'}


def now():
    return instant(datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'))


def credential(path):
    found=[]
    for line in path.read_text().splitlines():
        name,sep,value=line.strip().removeprefix('export ').partition('=')
        if sep and name.strip()=='TYPESAFE_API_KEY':
            tokens=shlex.split(value,comments=True)
            if len(tokens)!=1: raise ValueError('invalid_credential_assignment')
            found.append(tokens[0])
    if len(found)!=1 or not found[0]: raise ValueError('missing_or_duplicate_credential')
    return found[0]


def packets(authored):
    contexts={x['id']:x for x in authored['contexts']}
    steps={x['id']:x for x in authored['steps']}
    chosen=[x for x in (*claim_evidence_questions(),*contribution_questions())
            if x.value['family'] in {'evidence.support','evidence.qualification','evidence.established',
                                     'attention.objective','attention.novelty'}]
    cases=[]
    for step_id,kind in [('s04','duplicate'),('s05','recommendation'),('s09','correction')]:
        cut=steps[step_id]['available_at']
        sources=[{'id':x['id'],'available_at':x['available_at'],'kind':x['input_kind'],**x['input']}
                 for x in authored['steps'] if x['available_at']<=cut and x['input_kind']=='source']
        for audience_id in ('privacy-advocacy','district-finance'):
            context=contexts[audience_id]
            prior=['s01','s02','s03'] if kind!='correction' else ['s01','s02','s03','s04','s05','s06','s07']
            state={'synthetic':True,'data_kind':'authored_diagnostic_not_core_record',
                'scope_id':'synthetic:pr18-diagnostic','as_of':instant(cut),
                'binding':{'kind':'claim','id':'synthetic:compound-claim','proposition':{
                    'claim':'An advisory committee recommended draft:1 AND the district adopted its biometric requirement as a binding rule.',
                    'components':{'recommendation':'The advisory committee recommended draft:1.',
                                  'adoption':'The district finally adopted mandatory facial recognition.'}}},
                'evidence':sources,'coverage':{'status':'synthetic_supplied_prefix','limits':'No final adopting act or funding record is supplied.'},
                'mechanical':{'available_source_ids':[x['id'] for x in sources],
                    'lineage':'s04 repeats s03; s09 corrects and retracts s05. Copies are not independent evidence.'},
                'comparison':{'cause':'new_evidence','current_input':steps[step_id]['input'],
                    'purpose':context['purpose'],'audience':context,
                    'last_observed_delivery':{'kind':'synthetic_capture_milestone','audience_id':audience_id,
                        'sources':[{'id':i,'text':steps[i]['input'].get('text','')} for i in prior],
                        'meaning':'These facts were already conveyed in this synthetic capture lane, even if no interruption was warranted.'},
                    'uncertainty':'Missing final authority is unknown; no source or model output grants action permission.'}}
            expected={'evidence.established':'no', 'evidence.qualification':'yes',
                'evidence.support':'no' if kind=='duplicate' else ('yes' if kind=='recommendation' else 'uncertain'),
                'attention.objective':'yes' if audience_id=='privacy-advocacy' else 'no',
                'attention.novelty':'yes' if audience_id=='privacy-advocacy' and kind!='duplicate' else 'no'}
            cases.append({'id':kind+'-'+audience_id,'state':state,'expected_direction':expected,
                'expected_silence':kind=='duplicate' or audience_id=='district-finance'})
    return chosen,cases


def run(args):
    root=args.output.resolve()
    root.mkdir(parents=True,exist_ok=False)
    secret=credential(args.env)
    def save(name,value):
        data=canonical_bytes(value)
        if secret.encode() in data: raise ValueError('credential_echo_withheld')
        (root/name).write_bytes(data+b'\n')
    executor=TypeSafeHTTPExecutor(model=args.model,api_key=secret,timeout=30,max_calls=6,max_retries=0,
        max_request_bytes=65536,max_response_bytes=65536)
    raw=args.scenario.read_bytes();specs,cases=packets(json.loads(raw))
    for case in cases:
        for specification in specs:
            render_question(specification,case['state'],case['id']+':'+specification.value['family'])
    preflight={'schema_version':'1.0','mode':'bounded_interpretation_diagnostic','live_selected':args.live,
        'model':args.model,'credential_present':True,'calls_limit':6,'timeout_seconds':30,'retries':0,
        'wall_limit_seconds':240,'max_request_bytes':65536,'max_response_bytes':65536,
        'source_sha256':source_digest(raw),'script_sha256':source_digest(Path(__file__).read_bytes()),
        'labels':'Agent-authored diagnostic directions; not independent qualification labels.',
        'cases':cases,'specifications':[s.value for s in specs],
        'delivery_sink':'capture_only','qualification':'unknown','consequential_use':False}
    save('preflight.json',preflight)
    if not args.live:
        print(json.dumps({'status':'preflight_only','cases':len(cases),'credential_present':True,'model':args.model}))
        return
    started=time.monotonic();observations=[];stop_reason=None
    for case in cases:
        if time.monotonic()-started>=240:
            stop_reason='wall_limit';break
        state=case['state']
        rendered=[render_question(s,state,case['id']+':'+s.value['family']) for s in specs]
        deadline=(datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat(timespec='seconds').replace('+00:00','Z')
        batch=Batch({'schema_version':'1.0','id':case['id'],'scope_id':state['scope_id'],
            'run_id':root.name,'stage_id':case['id'],'state':state,
            'packet_digest':canonical_digest(state,'matter.semantic.packet.v1'),
            'questions':[r.question.value for r in rendered],
            'context':{'provider':'typesafe','transport':'http','requested_model':args.model,
                'adapter_version':ADAPTER_VERSION,'mode':'provider_shadow','deadline':instant(deadline),
                'max_request_bytes':65536,'max_response_bytes':65536}})
        save(case['id']+'-started.json',{'status':'started','batch':batch.value,'expected':case['expected_direction']})
        result=execute_batch(executor,batch,clock=now)
        save(case['id']+'-response.json',result.value)
        shadow=ShadowResult(batch,result,specifications=specs).value
        row={'case':case['id'],'primitive_valid':result.primitive_valid,'expected_direction':case['expected_direction'],
            'expected_silence':case['expected_silence'],'shadow':shadow}
        observations.append(row);save('capture.json',observations)
        print(json.dumps({'case':case['id'],'primitive_valid':result.primitive_valid,
            'observed':{q['family']:q['answer'] for q in shadow['questions']}}),flush=True)
        if not result.primitive_valid:
            stop_reason='invalid_or_failed_attempt';break
    save('summary.json',{'attempted':executor.calls_made,'completed_cases':len(observations),
        'elapsed_seconds':str(round(time.monotonic()-started,3)),
        'status':'completed' if len(observations)==6 else 'incomplete','stop_reason':stop_reason,'real_deliveries':0,
        'accepted_state_mutations':0,'qualification':'unknown','consequential_use':False})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',type=Path,required=True)
    parser.add_argument('--env',type=Path,required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true')
    run(parser.parse_args())
