"""MAT-038 paired complete-episode offline runner; no credential or network lane.

Fixture bytes are keyed by the exact batch digest, independently authored from
policy decisions. Trusted host callbacks reuse the actual core replay/admission
services; they receive observations, not expected answers. No fallback guesses.
"""
from copy import deepcopy
from .._rule_values import FrozenValue,checked,fragment
from ..canonical import canonical_bytes,canonical_digest,source_digest
from ..contracts import ContractError
from ..semantic import Batch,Capabilities,FixtureExecutor,execute_batch
from ..semantic.contracts import ExecutionFault
from .arms import ArmManifest,compare_arms
from .artifacts import ArtifactDirectory
from .splits import SplitManifest
from .corpus import FrozenCorpus,MAX_CORPUS_BYTES

TERMINAL=('successful','abstained','failed','stale')
GATES={'provider_accuracy':'not_run','live_delivery':'not_run','qualification':'not_run'}


def _fail(reason,code='E_EVIDENCE_INVALID'):raise ContractError(code,reason)


def validate_jobs(jobs,*,corpus,arm):
    if type(jobs) not in (list,tuple) or len(jobs)>4096 or len(canonical_bytes(list(jobs)))>MAX_CORPUS_BYTES:_fail('offline_job_limit','E_BUDGET_EXHAUSTED')
    cases={(x['episode_id'],x['case_id']):x for x in arm.value['cases']};seen=set();ids=set();validated=[]
    for job in jobs:
        checked(job,required={'id','episode_id','case_id','at','batch','scenario','expected_status'},optional={'fault'})
        key=(job['episode_id'],job['case_id']);batch=Batch(job['batch']);fragment(job['at'],'known_time')
        if key not in cases or key in seen or job['id'] in ids:_fail('duplicate_or_unknown_scheduled_case')
        seen.add(key);ids.add(job['id'])
        if (batch.value['scope_id']!=corpus.value['scope_id'] or batch.value['packet_digest']!=cases[key]['packet_digest'] or job['at']!=cases[key]['as_of']):_fail('scheduled_packet_mismatch')
        if job['expected_status'] not in TERMINAL or job.get('fault') not in (None,'timeout'):_fail('invalid_fixture_schedule')
        if type(job['scenario']) is not str or not job['scenario'] or type(job['id']) is not str or not job['id']:_fail('invalid_fixture_identity')
        validated.append((deepcopy(job),batch))
    if seen!=set(cases):_fail('unscheduled_eligible_case')
    return validated


class OfflineReport(FrozenValue):
    def __init__(self,value):
        value=checked(value,required={'schema_version','mode','corpus_digest','split_digest','arms','fixture_digest','scheduled_manifest_digest','scheduled','counts','attempts','episodes','passed','gates','consequential_use'})
        if value['schema_version']!='1.0' or value['mode']!='offline_fixture' or value['gates']!=GATES or value['consequential_use'] is not False:_fail('offline_cannot_claim_live_or_qualification')
        if set(value['counts'])!=set(TERMINAL) or any(type(v) is not int or v<0 for v in value['counts'].values()):_fail('invalid_offline_counts')
        if type(value['scheduled']) is not int or sum(value['counts'].values())!=value['scheduled'] or len(value['attempts'])!=value['scheduled']:_fail('scheduled_denominator_mismatch')
        if any(a.get('status') not in TERMINAL for a in value['attempts']):_fail('invalid_terminal_outcome')
        if {s:sum(a['status']==s for a in value['attempts']) for s in TERMINAL}!=value['counts']:_fail('terminal_counts_mismatch')
        if value['passed'] is not (all(a['matches_expected_status'] for a in value['attempts']) and all(e['replay']['passed'] for e in value['episodes'])):_fail('offline_pass_mismatch')
        self._freeze(value)
    @property
    def digest(self):return canonical_digest(self.value,'matter.offline-report.v1')


def run_offline(*,corpus,split,baseline,candidate,jobs,capabilities,recordings,admit,run_episode,output):
    """Run every complete episode for A/B, including failed/abstained schedules.

    `admit(job, batch, result)` is a trusted configured admission reader returning
    successful/abstained/stale and an observed reason. It is not given expected
    status. `run_episode(arm, episode_id, observations)` executes the existing
    core recipe on a fresh store and returns its replay report. Synthetic test
    certificates/admission remain offline evidence, never provider qualification.
    """
    if not isinstance(corpus,FrozenCorpus) or not isinstance(split,SplitManifest):_fail('frozen_inputs_required')
    split.report(corpus=corpus)
    if compare_arms(baseline,candidate)['comparison']!='principal':_fail('principal_comparison_required')
    prepared=validate_jobs(jobs,corpus=corpus,arm=candidate)
    if not isinstance(capabilities,Capabilities) or capabilities.value['modes']!=['offline_fixture']:_fail('offline_capabilities_required')
    if any(batch.value['context']['mode']!='offline_fixture' for _,batch in prepared):_fail('offline_mode_required')
    executor=FixtureExecutor(capabilities,recordings);artifacts=ArtifactDirectory(output)
    fixture_digest=canonical_digest({k:source_digest(v) for k,v in recordings.items()},'matter.fixture-recordings.v1')
    config={'corpus_digest':corpus.sha256,'split_digest':split.digest,'arms':[baseline.value,candidate.value],
        'jobs':[j for j,_ in prepared],'capabilities':capabilities.value,'fixture_digest':fixture_digest}
    artifacts.write('manifest.json',config)
    attempts=[];counts={s:0 for s in TERMINAL}
    for index,(job,batch) in enumerate(prepared):
        artifacts.write(str(index)+'-started.json',{'job_id':job['id'],'batch':batch.value,'scenario':job['scenario']})
        selected=executor
        if job.get('fault')=='timeout':
            class Timeout:
                capabilities=executor.capabilities
                def execute(self,batch):raise ExecutionFault('timeout')
            selected=Timeout()
        result=execute_batch(selected,batch,clock=lambda:deepcopy(job['at']))
        visible={k:v for k,v in job.items() if k not in ('expected_status','fault')}
        if not result.primitive_valid:status,reason='failed','primitive_or_execution_failed'
        else:
            decision=admit(visible,batch,result)
            checked(decision,required={'status','reason'})
            status,reason=decision['status'],decision['reason']
            if status not in ('successful','abstained','stale') or type(reason) is not str or not reason:_fail('invalid_observed_admission')
        row={'job_id':job['id'],'episode_id':job['episode_id'],'case_id':job['case_id'],'scenario':job['scenario'],
            'status':status,'reason':reason,'matches_expected_status':status==job['expected_status'],
            'batch_digest':batch.digest,'result':result.value}
        counts[status]+=1;attempts.append(row);artifacts.write(str(index)+'-result.json',row)
    episodes=[]
    for arm in (baseline,candidate):
        for episode in corpus.value['episodes']:
            observed=[] if arm.value['kind']=='A' else [deepcopy(x) for x in attempts if x['episode_id']==episode['id']]
            # The callback never sees reference labels, expected statuses or
            # golden frames through this observation channel.
            for row in observed:row.pop('matches_expected_status')
            replay=run_episode(arm,episode['id'],observed)
            if type(replay) is not dict or type(replay.get('passed')) is not bool:_fail('invalid_episode_report')
            episodes.append({'arm':arm.value['kind'],'episode_id':episode['id'],'replay':replay})
    report=OfflineReport({'schema_version':'1.0','mode':'offline_fixture','corpus_digest':corpus.sha256,'split_digest':split.digest,
        'arms':[baseline.digest,candidate.digest],'fixture_digest':fixture_digest,
        'scheduled_manifest_digest':canonical_digest([j for j,_ in prepared],'matter.offline-schedule.v1'),'scheduled':len(prepared),'counts':counts,
        'attempts':attempts,'episodes':episodes,'passed':all(a['matches_expected_status'] for a in attempts) and all(e['replay']['passed'] for e in episodes),
        'gates':GATES,'consequential_use':False})
    artifacts.write('report.json',report.value);return report
