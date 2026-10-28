"""MAT-046 optional civic profile integrity/applicability adapter.

Opaque domain selectors describe declared powers. This module verifies source
and host-review evidence; it does not decide legal powers or grant action rights.
"""
from ._rule_values import FrozenValue, domain, fragment, runtime_schema
from .canonical import canonical_bytes, canonical_digest
from .contracts import ContractError
from .profiles import ProfileDefinition
from .storage import entity_ref, pin
from .time import compare_times, knowledge_eligible
from .controls import control_fence_ref,_fence,_control,_active as _control_active

FIELDS=('jurisdiction','body','category','act')


def _fail(reason,code='E_EVIDENCE_INVALID'):
    raise ContractError(code,reason)


def _within(selector,parent):
    return all(parent[k]=='*' or selector[k]==parent[k] for k in FIELDS)


def _period(value):
    if value['end']['state']=='unknown':
        if value['end']['reason']!='not_applicable':_fail('unknown_effective_end','E_POLICY_INVALID')
    elif compare_times(value['start'],value['end'])>=0:_fail('invalid_effective_period','E_POLICY_INVALID')


def _active(value,at):
    return compare_times(at,value['start'])>=0 and (value['end']['state']=='unknown' or compare_times(at,value['end'])<0)


def _reviews(view,scope,sources,remember):
    """Per-assertion history from existing registered source-control fences.

    A source can support many assertions. Generic fence dispositions overwrite
    each other, so their *history*, rather than just active_controls, is needed.
    This bounded scan also sees withdrawals on overlapping or scope-wide targets.
    It is metadata lookup, never a replacement control lane or review registry.
    """
    reviews={};seen=set();count=0
    for target in [None,*sources]:
        head=_fence(view,scope,target)
        if head is None:continue
        if head['revision']>256:_fail('review_history_limit','E_BUDGET_EXHAUSTED')
        address=control_fence_ref(scope,target)
        for revision in range(1,head['revision']+1):
            fence=view.get({**address,'revision':revision});remember(pin(fence))
            checked=domain('control-fence',fence['value']['value'])
            if fence['value']!=checked or checked['value']['target']!=target:_fail('review_fence_invalid')
            reference=checked['value']['last_control'];key=canonical_bytes(reference)
            if key in seen:continue
            seen.add(key);count+=1
            if count>4096:_fail('review_history_limit','E_BUDGET_EXHAUSTED')
            record=_control(view,reference);remember(pin(record))
            effect=record['body']['effect']['value'];payload=effect.get('payload')
            if payload is None or payload.get('schema',{}).get('id')!='civic-review':continue
            value=domain('civic-review',payload.get('value'))
            if payload!=value or record['provenance']['origin']!='host' or effect['action']!='disposition' or record['body']['control_kind']!='decision':
                _fail('host_review_binding_mismatch','E_AUTHORITY_REQUIRED')
            if value['value']['scope_id']!=scope:_fail('foreign_review','E_SCOPE_FORBIDDEN')
            reviews[key]=record
    return list(reviews.values())


class CivicProfile(FrozenValue):
    def __init__(self,value,*,profile):
        value=domain('civic-profile',value)['value']
        if not isinstance(profile,ProfileDefinition) or value['common_profile']!=profile.reference:
            _fail('common_profile_mismatch','E_POLICY_INVALID')
        if value['schema']!=runtime_schema('civic-profile')[0]:_fail('schema_digest_mismatch')
        _period(value['effective'])
        ids=set()
        for item in value['assertions']:
            if item['id'] in ids:_fail('duplicate_assertion')
            ids.add(item['id']);_period(item['effective'])
            if not _within(item['selector'],value['applies']):_fail('assertion_broadens_profile','E_SCOPE_FORBIDDEN')
            if item['disposition']=='reviewed_host' and (not item['attestation'] or not item['sources']):
                _fail('reviewed_assertion_requires_sources_and_attestation','E_AUTHORITY_REQUIRED')
            for source in item['sources']:
                if source['reference']['scope_id']!=value['scope_id']:_fail('foreign_source','E_SCOPE_FORBIDDEN')
            if item['attestation'] and item['attestation']['scope_id']!=value['scope_id']:_fail('foreign_review','E_SCOPE_FORBIDDEN')
        self._freeze(value)

    @property
    def reference(self):
        v=self.value
        return {'namespace':v['namespace'],'id':v['id'],'version':v['version'],
                'digest':canonical_digest(v,'matter.civic-profile.v1')}

    def assertion_reference(self,identity):
        v=self.value;matches=[a for a in v['assertions'] if a['id']==identity]
        if len(matches)!=1:_fail('missing_assertion')
        assertion={k:x for k,x in matches[0].items() if k not in {'attestation','disposition'}}
        declaration={k:x for k,x in v.items() if k!='assertions'}
        return {'namespace':v['namespace'],'id':v['id']+':'+identity,'version':v['version'],
                'digest':canonical_digest({'profile':declaration,'assertion':assertion},'matter.civic-assertion.v1')}


class CivicRegistry:
    def __init__(self,profiles):
        if not isinstance(profiles,(list,tuple)) or len(profiles)>256:_fail('profile_limit','E_BUDGET_EXHAUSTED')
        self.profiles={};identities=set()
        for profile in profiles:
            if not isinstance(profile,CivicProfile):_fail('invalid_profile','E_POLICY_INVALID')
            ref=profile.reference;identity=tuple(ref[k] for k in ('namespace','id','version'))
            if identity in identities:_fail('profile_version_collision')
            identities.add(identity);self.profiles[canonical_bytes(ref)]=profile
        if len(self.profiles)>256:_fail('profile_limit','E_BUDGET_EXHAUSTED')

    def _chain(self,reference):
        result=[];active=set();seen=set()
        def visit(ref):
            key=canonical_bytes(fragment(ref,'component_ref'))
            if key in active:_fail('parent_cycle')
            if key in seen:return
            if len(active)>32:_fail('parent_depth','E_BUDGET_EXHAUSTED')
            profile=self.profiles.get(key)
            if profile is None or profile.reference!=ref:_fail('missing_or_changed_parent')
            active.add(key)
            for parent in sorted(profile.value['parents'],key=canonical_bytes):
                visit(parent)
                p=self.profiles[canonical_bytes(parent)].value
                if (p['scope_id']!=profile.value['scope_id'] or
                    p['common_profile']!=profile.value['common_profile'] or
                    not _within(profile.value['applies'],p['applies'])):_fail('parent_scope_mismatch','E_SCOPE_FORBIDDEN')
            active.remove(key);seen.add(key);result.append(profile)
        visit(reference)
        return result

    def resolve(self,reference,*,selector,capability,at,as_of,view,controls,token):
        fragment(at,'known_time');fragment(as_of,'known_time');fragment(capability,'namespaced_name')
        if type(selector) is not dict or set(selector)!=set(FIELDS) or any(type(v) is not str or not v or v=='*' for v in selector.values()):
            _fail('exact_query_selector_required','E_SCHEMA_INVALID')
        chain=self._chain(reference);scope=chain[-1].value['scope_id']
        if controls.scope_id!=scope:_fail('foreign_profile','E_SCOPE_FORBIDDEN')
        entries={};ancestors={}
        for profile in chain:
            ancestors[canonical_bytes(profile.reference)]={canonical_bytes(p.reference) for p in self._chain(profile.reference)[:-1]}
            for assertion in profile.value['assertions']:
                ref=profile.assertion_reference(assertion['id']);entries[canonical_bytes(ref)]=(profile,assertion,ref)
        for profile,assertion,_ in entries.values():
            for target in assertion['overrides']:
                parent=entries.get(canonical_bytes(target))
                if parent is None or canonical_bytes(parent[0].reference) not in ancestors[canonical_bytes(profile.reference)]:_fail('override_not_parent_assertion')
                if (assertion['capability']!=parent[1]['capability'] or
                    not _within(assertion['selector'],parent[1]['selector']) or
                    assertion['selector']==parent[1]['selector']):_fail('override_must_be_narrow','E_SCOPE_FORBIDDEN')
        selected=[];overridden=set();dependencies={}
        def remember(ref):dependencies[canonical_bytes(ref)]=ref
        for profile,assertion,ref in entries.values():
            v=profile.value
            if (knowledge_eligible(v['available_at'],as_of) is not True or not _active(v['effective'],at)
                or not _active(assertion['effective'],at) or not _within(selector,v['applies'])
                or not _within(selector,assertion['selector']) or assertion['capability']!=capability):continue
            selected.append((profile,assertion,ref));overridden.update(canonical_bytes(x) for x in assertion['overrides'])
        candidates=[x for x in selected if canonical_bytes(x[2]) not in overridden]
        targets=[entity_ref(s['reference']) for _,a,_ in selected for s in a['sources']]
        targets.extend(entity_ref(a['attestation']) for _,a,_ in selected if a['attestation'])
        targets=sorted({canonical_bytes(t):t for t in targets}.values(),key=canonical_bytes)
        controls.require_current(view,token,capability='read',targets=targets or token['targets'])
        applicable=all(knowledge_eligible(p.value['available_at'],as_of) is True and
            _active(p.value['effective'],at) and _within(selector,p.value['applies']) for p in chain)
        if not applicable:candidates=[]
        source_available={}
        for _,assertion,ref in selected:
            available=True
            for declared in assertion['sources']:
                source=view.get(declared['reference']);remember(pin(source))
                if source['scope_id']!=scope or source['body']['content']['digest']!=declared['sha256']:_fail('source_hash_mismatch')
                available &= (source['body']['content']['availability']['status']=='available' and
                    knowledge_eligible(source['body']['available_at'],as_of) is True)
            source_available[canonical_bytes(ref)]=bool(available)
        review_history=_reviews(view,scope,sorted({canonical_bytes(entity_ref(s['reference'])):entity_ref(s['reference']) for _,a,_ in selected for s in a['sources']}.values(),key=canonical_bytes),remember)
        outcomes=[]
        for profile,assertion,ref in candidates:
            reason=assertion['disposition'];verified=False;available=source_available[canonical_bytes(ref)]
            if assertion['disposition']=='reviewed_host':
                review_ref=assertion['attestation'];review=view.get(review_ref);remember(pin(review))
                proof=view.receipt_for(review_ref);remember(pin(proof))
                effect=review['body']['effect']['value'];payload=effect.get('payload')
                if payload is None:_fail('missing_host_review','E_AUTHORITY_REQUIRED')
                checked=domain('civic-review',payload.get('value'))
                if (payload!=checked or checked['value']['scope_id']!=scope or checked['value']['assertion']!=ref
                    or checked['value']['common_profile']!=profile.value['common_profile']
                    or checked['value']['disposition']!='reviewed_host' or effect['action']!='disposition'
                    or review['provenance']['origin']!='host' or review['body']['control_kind']!='decision'
                    or {canonical_bytes(x) for x in review['body']['scope']['targets']} != {canonical_bytes(entity_ref(s['reference'])) for s in assertion['sources']}):
                    _fail('host_review_binding_mismatch','E_AUTHORITY_REQUIRED')
                matching=[r for r in review_history if r['body']['effect']['value']['payload']['value']['assertion']==ref]
                latest=max(matching,key=lambda r:r['body']['control_epoch']) if matching else None
                current=latest is not None and pin(latest)==review_ref and _control_active(latest,controls._time())
                known=all(knowledge_eligible(t,as_of) is True for t in (review['provenance']['recorded_at'],proof['provenance']['recorded_at'],checked['value']['reviewed_at']))
                verified=bool(current and known and available)
                if not verified:reason='review_not_current_or_available'
            outcomes.append({'assertion':ref,'allowed':assertion['allowed'],'disposition':assertion['disposition'],
                             'review_verified':verified,'source_available':bool(available),'reason':reason})
        meanings={(x['allowed'],x['disposition']) for x in outcomes}
        conflict=len(meanings)>1
        eligible=bool(outcomes) and not conflict and all(x['allowed'] and x['review_verified'] for x in outcomes)
        return {'schema_version':'1.0','profile':reference,'selector':selector,'capability':capability,
                'state':'conflict' if conflict else ('resolved' if outcomes else 'unknown'),
                'reason':'conflicting_applicable_assertions' if conflict else ('matched' if outcomes else 'no_applicable_assertion'),
                'outcomes':sorted(outcomes,key=canonical_bytes),'dependencies':[dependencies[k] for k in sorted(dependencies)],
                'eligible_for_host_proposal':eligible,'consequential_use':False,'proposed_actions':[]}
