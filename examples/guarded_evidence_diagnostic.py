"""Bounded exploratory evidence diagnostic through existing MAT-072 ports.

External input: provenance.json, source.pdf and saved source.md. No corpus bytes
are checked in. This is a small isolated host over the existing store, intake,
packet renderer, access dispatcher and provider runner; not StateCivics delivery,
held-out evaluation, an extraction benchmark or qualification. External plan
syntax is checked before reading credentials or creating per-run artifacts.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import json
import os
import re

from matter.access import AccessService, HostAccessPolicy
from matter.assessments import FrozenAssessmentView
from matter.authority import AuthorityPolicy
from matter.canonical import canonical_bytes, canonical_digest, source_digest, loads
from matter.citations import Utf8LineLocatorAdapter
from matter.controls import ControlService
from matter.evaluation.provider import GuardedProviderCase, run_guarded_diagnostic
from matter.identity_keys import ExactIdentityPolicy
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.semantic import Batch
from matter.semantic.families import with_packet
from matter.semantic.families.attention import contribution_questions
from matter.semantic.packets import PacketProfile, prepare_packet
from matter.semantic.providers.typesafe import ADAPTER_VERSION
from matter.semantic.questions import QuestionSpecification
from matter.semantic.rendering import render_question
from matter.storage import SQLiteStore, entity_ref, pin
from jev_interpretation_diagnostic import credential


# Verified against the official reference at this fixed time. A future run
# cannot assert a new price check or silently price another selected model.
PRICE_BASIS={'model':'jev-1.14.0','source':'https://docs.typesafe.ai/models',
    'checked_at':{'state':'known','value':'2026-10-28T13:59:12Z','precision':'second'},
    'input_usd_per_million':'0.042','output_usd_per_million':'0','max_input_tokens_per_call':65536}


def now():
    return {'state':'known','value':datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z'),'precision':'microsecond'}


def component(identity, value):
    return {'namespace':'matter.diagnostic','id':identity,'version':'1.0',
            'digest':canonical_digest(value,'matter.diagnostic-component.v1')}


def specifications():
    heads=[]
    for name,wording,yes,no in [
        ('proposal','Does the evidence support that the county Public Works memorandum asks commissioners to consider an amendment to close out an existing completed planning grant?',
         'The memorandum proposes this close-out amendment.','The selected text does not support that request.'),
        ('executed','Does the supplied evidence establish that BOTH parties signed and finally executed the close-out amendment?',
         'The supplied text proves completed execution by both parties.','Proposed terms, legal-form approval, unsigned signature fields or instructions to obtain signatures do not prove execution.')]:
        heads.append(with_packet(QuestionSpecification({'schema_version':'1.0','namespace':'matter.diagnostic','id':name,
            'family':'diagnostic.'+name,'revision':'1.0','primitive':'proposition_probability',
            'instructions':wording+' Use {{meaning}}. Preserve uncertainty and source authority; this diagnostic grants no permission to act.',
            'criteria':{'true':yes,'false':no},
            'required_fields':[{'name':'meaning','path':['diagnostic'],'description':'Explicit experiment context; not government publication history.'}],
            'renderer':{'id':'canonical-json-bindings','version':'1.0'}})))
    return heads+[s for s in contribution_questions() if s.value['family'] in ('attention.objective','attention.novelty')]


def experiment_plan(raw):
    from matter.semantic.contracts import MAX_QUESTIONS
    if type(raw)is not dict or set(raw)!={'id','audiences','cases','specifications'}:raise ValueError('invalid_experiment_plan')
    if type(raw['audiences'])is not dict or len(raw['audiences'])!=2 or type(raw['cases'])is not list or len(raw['cases'])!=3:raise ValueError('bounded_plan_requires_two_audiences_and_three_cases')
    if any(type(k)is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',k) or type(v)is not dict or type(v.get('purpose'))is not str or not v['purpose'] for k,v in raw['audiences'].items()):raise ValueError('invalid_audience_declaration')
    if type(raw['specifications'])is not list or not 1<=len(raw['specifications'])<=MAX_QUESTIONS:raise ValueError('bounded_specifications_required')
    specs=[QuestionSpecification(v) for v in raw['specifications']]
    if len({s.value['family'] for s in specs})!=len(specs):raise ValueError('duplicate_question_family')
    for case in raw['cases']:
        if type(case)is not dict or set(case)!={'id','cause','prior_capture','expectations'}:raise ValueError('invalid_experiment_case')
        if type(case['id'])is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',case['id']):raise ValueError('invalid_case_identity')
        if any(type(case[k])is not str or not case[k] for k in ('cause','prior_capture')):raise ValueError('invalid_case_history')
        if type(case['expectations'])is not dict or set(case['expectations'])!=set(raw['audiences']):raise ValueError('missing_audience_expectations')
    if len({c['id'] for c in raw['cases']})!=3:raise ValueError('duplicate_case_identity')
    return specs


def run(args):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.run_id):raise ValueError('invalid_run_id')
    if args.model!=PRICE_BASIS['model']:raise ValueError('model_has_no_verified_price_basis')
    os.umask(0o077)
    root=args.evidence.resolve(); repo=Path(__file__).resolve().parents[1]
    if root==repo or repo in root.parents:raise ValueError('real_evidence_must_remain_external')
    provenance=json.loads((root/'provenance.json').read_text())
    pdf=(root/'source.pdf').read_bytes();text=(root/'source.md').read_bytes()
    if source_digest(pdf)!=provenance['public_fetch_sha256'] or source_digest(text)!=provenance['row']['text']['sha256']:
        raise ValueError('source_hash_mismatch')
    if provenance['public_fetch_status']!=200 or not provenance['permission_basis']:raise ValueError('public_permission_required')
    plan_path=getattr(args,'plan',None)
    plan_bytes=None if plan_path is None else plan_path.read_bytes()
    plan=None if plan_bytes is None else loads(plan_bytes)
    specs=specifications() if plan is None else experiment_plan(plan)
    secret=credential(args.env)
    scope='exploratory:public-civic-'+source_digest(provenance['custody']['citation_url'].encode())[:16];at=now()
    producer=component('public-crawler-reuse',{'provenance_digest':source_digest((root/'provenance.json').read_bytes())})
    actor={'scope_id':scope,'namespace':'matter.diagnostic','id':'authorized-operator'}
    authority={'scope_id':scope,'namespace':'matter.diagnostic','record_type':'receipt','id':'host-grant'}
    def record(kind,identity,body,*,origin='host',parents=()):
        return {'schema_version':'1.0','record_type':kind,'scope_id':scope,'namespace':'matter.diagnostic','id':identity,
                'provenance':{'origin':origin,'producer':producer,'recorded_at':at,'parents':list(parents)},'body':body}
    def command(identity,operation,body):
        return {'schema_version':'1.0','operation':operation,'command_id':identity,'idempotency_key':identity,
                'scope_id':scope,'actor':actor,'authority':authority,'expected_revisions':[],'body':body}
    database=root/('host-'+args.run_id+'.sqlite')
    if database.exists():raise ValueError('use_a_new_run_id_no_implicit_resubmission')
    payloads=FilePayloadStore(root/('payloads-'+args.run_id),scope_id=scope)
    with SQLiteStore(database,scope_id=scope) as store, SQLiteStore(database,scope_id=scope) as reader:
        identity=ExactIdentityPolicy(key_namespaces=['matter.diagnostic:subject'])
        bootstrap=command('bootstrap','create_matter',{'identity_policy':identity.reference,
            'matter':record('matter','setup',{'domain_kind':'matter.diagnostic:public-source','title':'Isolated public evidence diagnostic',
                'identity_keys':[{'namespace':'matter.diagnostic:subject','value':'setup'}]})})
        def initialize(tx):
            tx.insert(record('receipt','host-grant',{'stage':'authority','operation_id':'bootstrap','recorded_at':at,
                'outcome':'matter.diagnostic:authorized','evidence':[],
                'details':{'schema':producer,'value':provenance['permission_basis']}}))
            subject=tx.insert(tx.command['body']['matter']);return tx.success('created',{'matter':pin(subject)})
        bootstrapped=store.execute(bootstrap,initialize)
        if bootstrapped['status']!='success':raise RuntimeError('bootstrap_failed')
        controls=ControlService(store,policy=AuthorityPolicy(scope,actors=[actor],authorities=[pin(store.get(authority))],
            capabilities=['read','assessment'],control_kinds=[]),clock=now)
        intake=ObservationIngestor(store,payloads)
        def ingest(identity,data,media,*,origin='source',parents=()):
            body={'source_identity':{'namespace':'matter.diagnostic:public-crawler','event_id':identity,'revision_id':source_digest(data)},
                'content':{'digest':source_digest(data),'byte_length':len(data),'media_type':media,
                    'locator':{'kind':'whole_artifact','uri':provenance['custody']['citation_url']+('#saved-machine-extraction' if parents else '')},
                    'availability':{'status':'available','checked_at':at}},
                'occurred_at':{'state':'unknown','reason':'not_reported'},
                'source_published_at':{'state':'unknown','reason':'not_reported'},
                'available_at':at,'ingested_at':at,'extraction':producer}
            proposed=command(identity,'ingest_observation',{'observation':record('observation',identity,body,origin=origin,parents=parents)})
            result=intake.ingest(intake.prepare(proposed),payload=data)
            if result.get('outcome')!='committed':raise RuntimeError('source_ingestion_failed')
            return store.get(result['body']['observation']),proposed
        original,_=ingest('public-original',pdf,'application/pdf')
        source,first=ingest('saved-machine-extraction',text,'text/markdown',origin='derived',parents=[pin(original)])
        duplicate=deepcopy(first);duplicate.update(command_id='redelivery',idempotency_key='redelivery')
        duplicate['body']['observation']['id']='duplicate-proposed-id'
        duplicate_result=intake.ingest(intake.prepare(duplicate),payload=text)
        if duplicate_result.get('outcome')!='duplicate':raise RuntimeError('redelivery_not_duplicate')
        if duplicate_result['body']['observation']!=pin(source):raise RuntimeError('duplicate_pin_changed')
        audiences={
            'grant-oversight':{'purpose':'Track the completion and financial close-out of county roadway safety planning grants, and identify the next oversight step.',
                'responsibility':'Public grant oversight; a proposed close-out is relevant even before final execution.'},
            'school-procurement':{'purpose':'Find currently open school-district classroom technology procurements to bid on.',
                'responsibility':'School technology vendor; a completed county roadway safety planning grant is outside this objective.'}}
        if plan is not None:audiences=plan['audiences']
        refs={name:component(name,value) for name,value in audiences.items()};provider=component('typesafe',{'model':args.model,'transport':'http'})
        access=AccessService(policy=HostAccessPolicy(scope_id=scope,audiences=list(refs.values()),
            providers=[{'reference':provider,'provider':'typesafe','transport':'http'}],
            grants=[{'reference':pin(s),'audiences':list(refs.values()),'providers':[provider]} for s in (original,source)]),
            controls=controls,current_read=reader.snapshot)
        adapter=Utf8LineLocatorAdapter(payloads)
        profile=PacketProfile({'namespace':'matter.diagnostic','id':'public-extraction','version':'1.0','required_roles':['diagnostic:basis'],
            'allowed_origins':['derived'],'locator_adapters':[adapter.reference],'max_sources':2,'max_source_bytes':8192,'max_packet_bytes':32768})
        evidence={'reference':pin(source),'roles':['diagnostic:basis'],'locator':source['body']['content']['locator'],
            'quotation':None,'validation':adapter.validate(source,source['body']['content']['locator'],checked_at=at)}
        cases=[];checks={'duplicate_outcome':duplicate_result['outcome'],'duplicate_pin_unchanged':True,'availability':at,
            'correction_kind':'Experimental analyst interpretation correction; no fabricated publication or source revision.'}
        selected_cases=[{'id':kind} for kind in ('proposal','duplicate','correction')] if plan is None else plan['cases']
        for case in selected_cases:
            kind=case['id']
            for audience_name,audience in audiences.items():
                token=controls.capture(actor=actor,authority=authority,capability='assessment',targets=[entity_ref(original),entity_ref(source)])
                with store.snapshot() as view:
                    context=access.capture(view,token=token,audience=refs[audience_name],provider=provider,references=[pin(source)])
                    packet=prepare_packet(view,profile,payloads=payloads,scope_id=scope,
                        binding={'kind':'candidate_relation','left':pin(source),'right':pin(source),'relation':'diagnostic:same-source'},
                        as_of=now(),evidence=[evidence],coverage={'status':'complete','snapshot':component('explicit-single-document',{'count':1})},
                        access=access,access_context=context)
                    if len(packet.state['evidence'])!=1:raise RuntimeError('selected_source_missing')
                    if not checks.get('before_cut_refused'):
                        before={**at,'value':(datetime.fromisoformat(at['value'].replace('Z','+00:00'))-timedelta(seconds=1)).isoformat(timespec='microseconds').replace('+00:00','Z')}
                        # A real current record cannot be used by an earlier cut.
                        from matter.contracts import ContractError
                        try:
                            prepare_packet(view,profile,payloads=payloads,scope_id=scope,
                                binding={'kind':'candidate_relation','left':pin(source),'right':pin(source),'relation':'diagnostic:same-source'},
                                as_of=before,evidence=[evidence],coverage={'status':'complete','snapshot':component('coverage',{})},
                                access=access,access_context=context)
                        except ContractError as error:
                            checks['before_cut_refused']=error.code
                        else:raise AssertionError('future-bound source entered earlier packet')
                    state=packet.state
                    prior={'proposal':'No earlier applicable capture is supplied; this is the first experimental observation.',
                        'duplicate':'The same audience/purpose experimental capture already conveyed this exact memo, its close-out request and lack of proof of both signatures.',
                        'correction':'The experimental prior analyst capture described this as a NEW open grant award. Compare that prior interpretation with the source itself; any correction must be source-supported.'}.get(kind,'No prior capture is supplied.') if plan is None else case['prior_capture']
                    state['diagnostic']={'kind':kind,'source_origin':'Saved machine extraction of the hash-verified public attachment; OCR errors remain possible.',
                        'coverage_limit':'One public attachment, not complete meeting minutes, signed final agreement or historical client context.',
                        'correction_kind':checks['correction_kind']}
                    state['comparison']={'cause':'corrected_association' if kind=='correction' else 'new_evidence',
                        'audience':audience,'purpose':audience['purpose'],'current_input':'Read the selected source bytes to determine their meaning; no current interpretation is supplied here.',
                        'last_observed_delivery':{'kind':'explicit_experimental_capture_context','real_audience_delivery':False,'meaning':prior},
                        'uncertainty':'No current procurement, actual client action or completed execution is established.'}
                    if plan is not None:
                        state['comparison']['cause']=case['cause']
                        state['diagnostic']={'source_origin':'Hash-verified saved public-source extraction; extraction errors remain possible.',
                            'coverage_limit':'Explicit supplied documents only; missing facts remain unresolved.',
                            'correction_kind':checks['correction_kind']}
                        state['comparison']['last_observed_delivery']={'kind':'explicit_experimental_capture_context',
                            'real_audience_delivery':False,'meaning':prior}
                        state['comparison']['uncertainty']='Preserve missing evidence and authority. This experiment grants no permission to act.'
                    rendered=tuple(render_question(s,state,kind+'-'+audience_name+':'+s.value['family'],source_manifest=packet.source_manifest,
                        access=access,access_context=context,access_view=view) for s in specs)
                    # Reuse the existing detached read format, capturing only actual
                    # admitted sources/authority and token fence absence under this snapshot.
                    detached=FrozenAssessmentView({'records':[view.get(r) for r in [token['authority'],*context.value['dependencies']]],
                        'absent':[f['reference'] for f in token['fences'] if f['pin'] is None],'watch_queries':{}})
                batch=Batch({'schema_version':'1.0','id':kind+'-'+audience_name,'scope_id':scope,'run_id':args.run_id,'stage_id':kind,
                    'state':state,'packet_digest':canonical_digest(state,'matter.semantic.packet.v1'),'questions':[r.question.value for r in rendered],
                    'context':{'provider':'typesafe','transport':'http','requested_model':args.model,'adapter_version':ADAPTER_VERSION,
                        'mode':'provider_shadow','deadline':now(),'max_request_bytes':65536,'max_response_bytes':65536}})
                cases.append(GuardedProviderCase(batch.value['id'],batch,access,context,detached,rendered,
                    (case['expectations'][audience_name] if plan is not None else {'proposal':'high','executed':'low','objective':'high' if audience_name=='grant-oversight' else 'low',
                     'novelty':'low' if kind=='duplicate' else ('high' if audience_name=='grant-oversight' else 'uncertain'),
                     'expected_silence':kind=='duplicate' or audience_name=='school-procurement',
                     'labels':'Authored exploratory expectations, not independent ground truth.'})))
        (root/(args.run_id+'-source-checks.json')).write_bytes(canonical_bytes(checks)+b'\n')
        config={'mode':'provider_shadow','provider':'typesafe','model':args.model,'scope_id':scope,'credential_source':'.env:TYPESAFE_API_KEY',
            'max_calls':6,'timeout_seconds':30,'wall_seconds':300,'max_cost_usd':'0.02',
            'price_basis':deepcopy(PRICE_BASIS),
            'trials_per_case':1,'max_request_bytes':65536,'max_response_bytes':65536}
        report=run_guarded_diagnostic(config=config,cases=cases,credential=secret,output=root/args.run_id,
            provenance={'external_provenance_sha256':source_digest((root/'provenance.json').read_bytes()),'source_checks':checks,
                'plan_digest':None if plan is None else source_digest(plan_bytes),'audiences':audiences,'delivery_sink':'isolated_private_artifacts','no_independent_labels':True},live=args.live)
        print(json.dumps({k:v for k,v in report.items() if k!='observations'}),flush=True)
        if args.live and report['status']!='completed':raise RuntimeError('live_diagnostic_incomplete')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--env',type=Path,required=True)
    parser.add_argument('--model',required=True);parser.add_argument('--run-id',required=True)
    parser.add_argument('--plan',type=Path,help='External bounded source-grounded experiment plan; no expected outcomes enter model state.')
    parser.add_argument('--live',action='store_true');run(parser.parse_args())
