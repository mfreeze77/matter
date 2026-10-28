"""MAT-024 bounded chronological orchestration over registered core drivers.

A driver is trusted host code using existing service ports, never a provider or
transport selected by the manifest. Only the admitted prefix, original policy
references and recorded judgments reach it; reference labels/expected frames do
not. Sequential results establish neither provider accuracy nor race safety.
"""
from copy import deepcopy
from ._rule_values import FrozenValue,domain
from .canonical import canonical_bytes,canonical_digest
from .contracts import ContractError
from .evaluation.corpus import FrozenCorpus,MAX_CORPUS_BYTES
from .time import compare_times


def _fail(reason,code='E_EVIDENCE_INVALID'):raise ContractError(code,reason)


class ReplayManifest(FrozenValue):
    def __init__(self,value,*,corpus):
        if not isinstance(corpus,FrozenCorpus):_fail('frozen_corpus_required')
        if len(canonical_bytes(value))>MAX_CORPUS_BYTES:_fail('replay_manifest_limit','E_BUDGET_EXHAUSTED')
        value=domain('replay-manifest',value)['value']
        if value['scope_id']!=corpus.value['scope_id'] or value['corpus_digest']!=corpus.sha256:_fail('corpus_mismatch')
        if not set(value['episode_ids'])<={e['id'] for e in corpus.value['episodes']}:_fail('unknown_replay_episode')
        ids=set();previous=None
        known={(e['id'],o['id']) for e in corpus.value['episodes'] if e['id'] in value['episode_ids'] for o in e['observations']}
        for step in value['steps']:
            if step['id'] in ids:_fail('duplicate_replay_step')
            ids.add(step['id'])
            if previous and compare_times(step['as_of'],previous)<0:_fail('replay_clock_regression')
            previous=step['as_of']
            required={(x['episode_id'],x['observation_id']) for x in step['requires']}
            for judgment in step['recorded_judgments']:
                if compare_times(judgment['recorded_at'],step['as_of'])>0 or not {(x['episode_id'],x['observation_id']) for x in judgment['observations']}<=required:_fail('recorded_judgment_outside_knowledge_cut','E_EVIDENCE_UNAVAILABLE')
            if not {(x['episode_id'],x['observation_id']) for x in step['requires']}<=known:_fail('unknown_required_observation')
        self._freeze(value)

    @property
    def digest(self):return canonical_digest(self.value,'matter.replay-manifest.v1')


def run_replay(manifest,*,corpus,driver):
    """Run one fresh driver/store. Driver owns actual service composition.

    A frame has explicitly observed conclusions, receipts, quiet reasons,
    transitions and delivery count. Golden comparisons use that portable frame,
    while exact core records remain the driver's local artifacts. Golden frames
    must not include storage execution-instance timestamps/digests.
    """
    if not isinstance(manifest,ReplayManifest):_fail('validated_manifest_required')
    value=manifest.value
    # Rebind on entry: a caller cannot swap the corpus after validation.
    ReplayManifest(value,corpus=corpus)
    if driver.reference!=value['driver'] or driver.mode!=value['mode'] or driver.capture_only is not True:_fail('replay_driver_mismatch','E_POLICY_INVALID')
    sources={(e['id'],s['reference']['id'],s['reference']['revision']):s for e in corpus.value['episodes'] for s in e['sources']}
    frames=[];failures=[]
    for step in value['steps']:
        prefix=corpus.prefix(as_of=step['as_of'])
        prefix['included']=[x for x in prefix['included'] if x['episode_id'] in value['episode_ids']]
        available={(x['episode_id'],x['observation']['id']) for x in prefix['included']}
        if not {(x['episode_id'],x['observation_id']) for x in step['requires']}<=available:
            _fail('required_observation_unavailable','E_EVIDENCE_UNAVAILABLE')
        if any(not {(x['episode_id'],x['observation_id']) for x in judgment['observations']}<=available for judgment in step['recorded_judgments']):
            _fail('recorded_judgment_source_unavailable','E_EVIDENCE_UNAVAILABLE')
        admitted=[]
        for item in prefix['included']:
            source=item['observation']['source']
            admitted.append({**item,'source':deepcopy(sources[(item['episode_id'],source['id'],source['revision'])])})
        request={k:deepcopy(step[k]) for k in ('id','as_of','operation','input','recorded_judgments')}
        request.update(profiles=value['profiles'],controls=value['controls'],inputs=admitted)
        output=driver.run_step(request)
        canonical_bytes(output)
        required={'conclusions','receipts','quiet_reasons','transitions','delivery_count','sources_used'}
        if type(output) is not dict or set(output)!=required:_fail('invalid_replay_frame','E_SCHEMA_INVALID')
        if any(type(output[k]) is not list for k in required-{'delivery_count'}):_fail('invalid_replay_frame','E_SCHEMA_INVALID')
        if type(output['delivery_count']) is not int or output['delivery_count']<0:_fail('invalid_delivery_count')
        used={(x['episode_id'],x['observation_id']) for x in output['sources_used']}
        if not used<=available:_fail('driver_used_unavailable_source')
        if output!=step['expected']:failures.append({'step':step['id'],'reason':'golden_frame_mismatch'})
        frames.append({'step':step['id'],'as_of':step['as_of'],'frame':output})
    logical={'manifest':manifest.digest,'mode':value['mode'],'frames':frames,'failures':failures}
    return {**logical,'logical_digest':canonical_digest(logical,'matter.replay-output.v1'),
        'passed':not failures,'gates':{'provider_accuracy':'not_run','concurrency':'not_run','live_delivery':'not_run','qualification':'not_run'},
        'limits':['Input gating does not establish model ignorance of later facts.',
                  'Sequential replay does not reproduce concurrent completion or live transport safety.']}
