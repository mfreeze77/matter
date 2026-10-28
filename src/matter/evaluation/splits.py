"""MAT-037 episode/provenance grouped, reproducible evaluation partitions."""
from .._rule_values import FrozenValue,checked,fragment
from ..canonical import canonical_bytes,canonical_digest
from ..contracts import ContractError
from .corpus import FrozenCorpus,_text,_ids

PARTITIONS=('tuning','qualification','final')


def _fail(reason,code='E_EVIDENCE_INVALID'):raise ContractError(code,reason)


def lineage_groups(corpus):
    """Conservative connected components, including renamed byte-identical copies.

    Whole episodes move together. Shared source revisions, source bytes, observed
    identities, occurrence IDs and inherited provenance groups add cross-episode
    edges. No semantic model guesses independence from different wording.
    """
    if not isinstance(corpus,FrozenCorpus):_fail('frozen_corpus_required')
    episodes=corpus.value['episodes'];parent={e['id']:e['id'] for e in episodes};owners={}
    def root(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    for episode in episodes:
        tokens=[]
        for source in episode['sources']:
            ref=source['reference'];tokens.extend([('source',ref['id'],ref['revision']),('bytes',ref['sha256'])])
        for observation in episode['observations']:
            tokens.append(('observation',observation['id']))
            tokens.extend(('provenance',x) for x in observation['provenance_groups'])
            tokens.extend(('occurrence',x) for x in observation['occurrence_ids'])
        for token in tokens:
            previous=owners.setdefault(token,episode['id']);a,b=root(previous),root(episode['id'])
            if a!=b:parent[max(a,b)]=min(a,b)
    groups={}
    for episode in episodes:groups.setdefault(root(episode['id']),[]).append(episode['id'])
    return sorted((sorted(members) for members in groups.values()),key=canonical_bytes)


def _weights(value):
    if type(value) is not dict or set(value)!=set(PARTITIONS) or any(type(v) is not int or v<1 or v>10000 for v in value.values()):_fail('invalid_partition_weights','E_SCHEMA_INVALID')
    return value


def _assignment(corpus,seed,weights):
    total=sum(weights.values());result={}
    for members in lineage_groups(corpus):
        value=int(canonical_digest({'seed':seed,'members':members},'matter.grouped-split.v1'),16)%total
        for name in PARTITIONS:
            if value<weights[name]:break
            value-=weights[name]
        result.update({identity:name for identity in members})
    return result


class SplitManifest(FrozenValue):
    def __init__(self,value,*,corpus,previous=None):
        value=checked(value,required={'schema_version','id','revision','corpus_digest','seed','weights','assignments','exposures','previous_digest','ever_tuning'})
        if value['schema_version']!='1.0' or not isinstance(corpus,FrozenCorpus) or value['corpus_digest']!=corpus.sha256:_fail('split_corpus_mismatch')
        _text(value['id'],'split/id');_text(value['seed'],'split/seed');_weights(value['weights'])
        if type(value['revision']) is not int or value['revision']<1:_fail('invalid_split_revision','E_SCHEMA_INVALID')
        assignments=value['assignments'];identities={e['id'] for e in corpus.value['episodes']}
        if type(assignments) is not dict or set(assignments)!=identities or any(v not in PARTITIONS for v in assignments.values()):_fail('incomplete_partition_mapping')
        groups=lineage_groups(corpus)
        if any(len({assignments[i] for i in members})!=1 for members in groups):_fail('blocking_source_or_occurrence_leakage')
        if assignments!=_assignment(corpus,value['seed'],value['weights']):_fail('assignment_seed_mismatch')
        if type(value['exposures']) is not list or len(value['exposures'])>4096:_fail('exposure_limit','E_BUDGET_EXHAUSTED')
        for exposure in value['exposures']:
            checked(exposure,required={'episode_ids','reason','at','question'})
            if not set(_ids(exposure['episode_ids'],'exposure/episodes',nonempty=True))<=identities:_fail('unknown_exposure_episode')
            _text(exposure['reason'],'exposure/reason');fragment(exposure['at'],'known_time');fragment(exposure['question'],'component_ref')
        current_tuning={i for i,p in assignments.items() if p=='tuning'}
        if previous is None:
            if value['previous_digest'] is not None or value['revision']!=1:_fail('initial_split_must_be_revision_one')
            expected_tuning=current_tuning
        else:
            if not isinstance(previous,SplitManifest) or value['previous_digest']!=previous.digest:_fail('previous_split_mismatch')
            old=previous.value
            expected_tuning=set(old['ever_tuning'])|current_tuning|{i for i,p in old['assignments'].items() if p=='tuning'}
            if value['id']!=old['id'] or value['revision']<=old['revision']:_fail('explicit_new_manifest_revision_required')
            if not {canonical_bytes(e) for e in old['exposures']}<={canonical_bytes(e) for e in value['exposures']}:_fail('exposure_history_cannot_be_erased')
        if set(_ids(value['ever_tuning'],'split/ever_tuning'))!=expected_tuning:_fail('past_tuning_cannot_become_held_out')
        self._freeze(value)

    @property
    def digest(self):return canonical_digest(self.value,'matter.split-manifest.v1')

    def report(self,*,corpus):
        if corpus.sha256!=self.value['corpus_digest']:_fail('split_corpus_mismatch')
        value=self.value;exposed=set(value['ever_tuning'])|{i for e in value['exposures'] for i in e['episode_ids']}
        # Exposure is group-wide even if only one member was optimized against.
        for group in lineage_groups(corpus):
            if exposed.intersection(group):exposed.update(group)
        partitions={p:{'episodes':0,'groups':0,'case_categories':{},'independent_labels':0,'exposed_episodes':0} for p in PARTITIONS}
        for identity,p in value['assignments'].items():
            partitions[p]['episodes']+=1;partitions[p]['exposed_episodes']+=identity in exposed
        for group in lineage_groups(corpus):partitions[value['assignments'][group[0]]]['groups']+=1
        for case in corpus.denominators()['cases']:
            out=partitions[value['assignments'][case['episode_id']]]['case_categories'];name=case['category'];out[name]=out.get(name,0)+1
        for episode in corpus.value['episodes']:
            partitions[value['assignments'][episode['id']]]['independent_labels']+=sum(x['origin']=='independent' for x in episode['labels'])
        return {'digest':self.digest,'partitions':partitions,'lineage_groups':lineage_groups(corpus),
            'effective_tuning_episodes':sorted(exposed|{i for i,p in value['assignments'].items() if p=='tuning'}),
            'held_out_usable':{i:p!='tuning' and i not in exposed for i,p in value['assignments'].items()},
            'limits':['Declared human provenance is not independent verification that a reviewer actually adjudicated synthetic labels.']}


def make_splits(corpus,*,identity,revision,seed,weights=None,previous=None,exposures=()):
    weights=_weights(weights or {'tuning':60,'qualification':20,'final':20})
    value={'schema_version':'1.0','id':identity,'revision':revision,'corpus_digest':corpus.sha256,'seed':seed,
        'weights':weights,'assignments':_assignment(corpus,seed,weights),'exposures':list(exposures),
        'previous_digest':None if previous is None else previous.digest,'ever_tuning':sorted(
            {i for i,p in _assignment(corpus,seed,weights).items() if p=='tuning'}|
            (set(previous.value['ever_tuning'])|{i for i,p in previous.value['assignments'].items() if p=='tuning'} if previous else set()))}
    return SplitManifest(value,corpus=corpus,previous=previous)
