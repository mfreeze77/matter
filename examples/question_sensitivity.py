"""MAT-041 bounded synthetic probes through existing offline/provider runners.

Checkout-only developer exercise: reuse the existing actual core replay driver.
The synthetic oracle is not independent ground truth. Default is offline only;
--live requires an explicit model, credential file and external artifact root.
No accepted semantic state, real delivery or qualification is produced.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import base64
import json
import os
import sys
import time

from matter.canonical import canonical_bytes,canonical_digest,loads,source_digest
from matter.evaluation.artifacts import ArtifactDirectory
from matter.evaluation.arms import ArmManifest
from matter.evaluation.corpus import FrozenCorpus
from matter.evaluation.offline import run_offline
from matter.evaluation.provider import run_provider
from matter.evaluation.sensitivity import prepare_sensitivity,sensitivity_report,ProbeObservation,ROLES
from matter.evaluation.splits import make_splits
from matter.replay import ReplayManifest,run_replay
from matter.semantic import Batch,Capabilities,normalize_response,PrecisionProfile
from matter.semantic.questions import QuestionSpecification
from matter.semantic.providers.typesafe import TypeSafeHTTPExecutor,ADAPTER_VERSION
from jev_interpretation_diagnostic import credential

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/evaluation/question_variants.json'
PRICE_BASIS={'model':'jev-1.14.0','source':'https://docs.typesafe.ai/models',
    'checked_at':{'state':'known','value':'2026-10-28T17:50:00Z','precision':'second'},
    'input_usd_per_million':'0.042','output_usd_per_million':'0','max_input_tokens_per_call':65536}


def inputs(model):
    # Reuse the existing actual SQLite/core replay recipe, not a new simulator.
    sys.path.insert(0,str(ROOT/'tests'))
    import replay_helpers as core
    fixture=loads(FIXTURE.read_bytes());text=canonical_bytes(fixture['facts']).decode()
    value=core.corpus_value();episode=value['episodes'][0]
    ref={'id':'probe-facts','revision':1,'sha256':source_digest(text.encode())}
    episode['sources'].insert(0,{'reference':ref,'available_at':core.EARLY,'artifact':{'kind':'synthetic','text':text}})
    episode['observations'].insert(0,{'id':'probe-facts','source':ref,'available_at':core.EARLY,'occurred_at':core.EARLY,
        'occurrence_ids':['probe-facts-event'],'provenance_groups':['synthetic-probe-facts'],'derivation':'root','parents':[]})
    episode['occurrences'].append({'id':'probe-facts-event','observation_ids':['probe-facts']})
    context={'provider':'typesafe','transport':'http','adapter_version':ADAPTER_VERSION,'mode':'offline_fixture',
        'requested_model':model,'deadline':core.LATE,'max_request_bytes':65536,'max_response_bytes':65536}
    state={'scope_id':value['scope_id'],'as_of':core.NOW,'facts':fixture['facts'],
        'source':{'id':'probe-facts','sha256':ref['sha256'],'available_at':core.EARLY,'kind':'synthetic'}}
    suite=prepare_sensitivity(identity='controlled-relationship-probes',scope_id=value['scope_id'],state=state,
        choice=QuestionSpecification(fixture['choice']),propositions={r:QuestionSpecification(fixture['propositions'][r]) for r in ROLES},
        positive_choice=fixture['positive_choice'],references=fixture['references'],context=context,tolerance=fixture['tolerance'])
    episode['cases']=[{'id':j['id'],'family':'association','target_observation_ids':['probe-facts'],
        'eligibility':{'state':'eligible','reason':'Synthetic authored shadow control; not independent labels.'}} for j in suite.value['jobs']]
    episode['labels']=[];corpus=FrozenCorpus(value);split=make_splits(corpus,identity='synthetic-sensitivity',revision=1,seed='controlled')
    jobs=[{'id':j['id'],'episode_id':episode['id'],'case_id':j['id'],'at':core.NOW,'batch':j['batch'],
        'scenario':j['kind'],'expected_status':'abstained'} for j in suite.value['jobs']]
    cases=[{'episode_id':j['episode_id'],'case_id':j['case_id'],'as_of':core.NOW,'packet_digest':j['batch']['packet_digest'],
        'packet_profile':core.component('structured-synthetic-facts')} for j in jobs]
    a={'schema_version':'1.0','id':'A','kind':'A','corpus_digest':corpus.sha256,'policy':core.component('shared-core-policy'),
        'semantic_families':[],'cases':cases,'retrieval_experiment':None}
    references={canonical_bytes(h['specification']):h['specification'] for j in suite.value['jobs'] for h in j['heads'].values()}
    b=deepcopy(a);b.update(id='B',kind='B',semantic_families=list(references.values()))
    adapter=TypeSafeHTTPExecutor(model=model,api_key='synthetic-offline-not-a-credential',timeout=30,max_calls=13,max_retries=0)
    caps=adapter.capabilities.value;caps['modes']=['offline_fixture']
    return fixture,core,suite,corpus,split,ArmManifest(a,corpus=corpus),ArmManifest(b,corpus=corpus),jobs,Capabilities(caps)


def oracle(fixture,job,model):
    answers=[]
    for role,head in job['heads'].items():
        q=head['rendered']['question'];expected=fixture['references'][role]['outcome']
        if role=='choice':
            definition=next(o['description'] for o in fixture['choice']['criteria'] if o['id']==expected)
            target=next(o['id'] for o in q['criteria'] if o['description']==definition)
            rest=[o['id'] for o in q['criteria'] if o['id']!=target]
            answers.append({'id':q['id'],'primitive':'choice','choice':target,'confidence':'0.9',
                'probabilities':{target:'0.9',**dict(zip(rest,('0.05','0.03','0.02')))}})
        else:answers.append({'id':q['id'],'primitive':'proposition_probability','probability':'0.95' if expected=='true' else '0.05'})
    return canonical_bytes({'answers':answers,'resolved_model':model})


def analyze_recorded(suite,result,output):
    """Revalidate retained neutral bytes, with zero provider calls or new tokens."""
    observations=[]
    for row in result.get('observations',[]):
        if row.get('result') is None:continue # Refused/outcome-unknown, not a returned execution.
        started=loads((output/'live'/(str(row['index'])+'-started.json')).read_bytes());batch=Batch(started['batch']);value=row['result']
        terminal=loads((output/'live'/(str(row['index'])+'-result.json')).read_bytes())
        if (any(terminal.get(k)!=v for k,v in row.items() if k!='observation_kind') or
            row['started_digest']!=canonical_digest(started,'matter.provider-start.v1') or
            value['batch_digest']!=batch.digest):raise ValueError('recorded_attempt_binding_changed')
        # Parsing successful bytes cannot erase an execution deadline/budget fault.
        # Leave the original provider report authoritative; do not publish a
        # successful analysis of an attempt the execution port rejected.
        if (value['execution_status']!='completed' or value['faults'] or
            value['admission']['primitive_status']!='valid' or not value['admission']['exact_numeric']):
            raise ValueError('recorded_execution_invalid_see_original_provider_report')
        if value['raw_response']['state']!='available':raise ValueError('recorded_response_unavailable')
        profile=value['precision_profile']
        precision=PrecisionProfile(profile['id'],profile['version'],probability_quantum=profile['probability_quantum'],score_quantum=profile['score_quantum'])
        if precision.value!=profile:raise ValueError('recorded_precision_profile_changed')
        replay=normalize_response(batch,base64.b64decode(value['raw_response']['base64']),precision=precision)
        observations.append(ProbeObservation(row['job_id'],batch,replay,str(output/'live'/(str(row['index'])+'-result.json'))))
    report=sensitivity_report(suite,observations)
    report['analysis_mode']='recorded_validation_of_actual_live_responses'
    report['provider_execution']={k:result.get(k) for k in ('status','fresh_attempts','cached_replays','incomplete_attempts','non_dispatched','not_attempted','reserved_cost_usd','billing_cost','stop_reason')}
    report['analysis_source_sha256']=source_digest((ROOT/'src/matter/evaluation/sensitivity.py').read_bytes())
    artifact=ArtifactDirectory(output,resume=True).write('live-sensitivity-'+str(time.monotonic_ns())+'.json',report)
    return report,artifact


def run(args):
    os.umask(0o077)
    if args.model!=PRICE_BASIS['model']:raise ValueError('explicit_model_has_no_verified_price_basis')
    output=args.output.resolve()
    if args.live and (output==ROOT or ROOT in output.parents):raise ValueError('live_receipts_must_remain_external')
    if args.live and args.env is None:raise ValueError('explicit_credential_file_required')
    # Read no credential for an offline exercise. Preflight never silently turns live.
    key=credential(args.env) if args.live else None
    fixture,core,suite,corpus,split,a,b,jobs,caps=inputs(args.model)
    output.mkdir(parents=True,exist_ok=False)
    (output/'suite.json').write_bytes(canonical_bytes(suite.value)+b'\n')
    (output/'corpus.json').write_bytes(canonical_bytes(corpus.value)+b'\n')
    recordings={Batch(j['batch']).digest:oracle(fixture,j,args.model) for j in suite.value['jobs']}
    def episode(arm,episode_id,observed):
        if arm.value['kind']=='B' and (len(observed)!=len(jobs) or any(o['status']!='abstained' for o in observed)):
            raise ValueError('unqualified_probe_must_remain_shadow')
        driver=core.CoreReplayDriver()
        try:
            manifest=loads((ROOT/'tests/fixtures/conformance/late-cancellation.json').read_bytes());manifest['corpus_digest']=corpus.sha256
            return run_replay(ReplayManifest(manifest,corpus=corpus),corpus=corpus,driver=driver)
        finally:driver.close()
    offline=run_offline(corpus=corpus,split=split,baseline=a,candidate=b,jobs=jobs,capabilities=caps,recordings=recordings,
        admit=lambda *args:{'status':'abstained','reason':'unqualified_shadow_probe'},run_episode=episode,output=output/'offline')
    if not offline.value['passed']:raise RuntimeError('actual_offline_conformance_failed')
    samples=[ProbeObservation(j['id'],Batch(j['batch']),normalize_response(Batch(j['batch']),recordings[Batch(j['batch']).digest]),
        str(output/'offline'/(str(i)+'-result.json'))) for i,j in enumerate(suite.value['jobs'])]
    offline_analysis=sensitivity_report(suite,samples)
    (output/'offline-sensitivity.json').write_bytes(canonical_bytes(offline_analysis)+b'\n')
    summary={'offline':'passed','offline_calls':0,'synthetic_controls':True,'qualification':'not_run','live_calls':0}
    if args.live:
        config={'mode':'provider_shadow','provider':'typesafe','model':args.model,'scope_id':corpus.value['scope_id'],
            'credential_source':'explicit-file:TYPESAFE_API_KEY','max_calls':13,'timeout_seconds':30,'wall_seconds':600,
            'max_cost_usd':'0.04','price_basis':PRICE_BASIS,'trials_per_case':1,'max_request_bytes':65536,'max_response_bytes':65536}
        (output/'protocol.json').write_bytes(canonical_bytes({'config':config,'suite_digest':suite.digest,'fixture_sha256':source_digest(FIXTURE.read_bytes()),
            'sink':'capture_only','independent_labels':0,'qualification':'not_run'})+b'\n')
        result=run_provider(config=config,corpus=corpus,split=split,candidate=b,jobs=jobs,offline=offline,credential=key,output=output/'live',live=True)
        report,analysis_artifact=analyze_recorded(suite,result,output)
        summary.update(live_status=result['status'],live_calls=result.get('fresh_attempts',0),review_required=sum(c['status']=='review_required' for c in report['checks']),analysis=analysis_artifact)
        if result['status']!='completed':
            (output/'summary.json').write_bytes(canonical_bytes(summary)+b'\n');raise RuntimeError('live_probe_run_incomplete_see_retained_receipts')
    (output/'summary.json').write_bytes(canonical_bytes(summary)+b'\n');print(json.dumps(summary),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--model',required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--env',type=Path)
    parser.add_argument('--live',action='store_true');run(parser.parse_args())
