"""MAT-023 consistent, current-READ-authorized inspection projections.

Existing identity, assessment, attention and delivery readers retain semantics.
This module owns snapshot/pagination assembly, never an action or UI policy.
"""
import base64
from copy import deepcopy

from ._rule_values import fragment
from .canonical import canonical_bytes,canonical_digest,loads
from .contracts import ContractError
from .identity_groups import read_group
from ._identity_children import collect_children
from .assessments import assessment_current_ref
from .identity_dependencies import _value
from .storage import PROJECTION_TYPE,StorageError,entity_ref,pin
from .semantic.packets import _Reads,_pin_references
from .time import knowledge_eligible


def _fail(reason,code='E_EVIDENCE_INVALID'):raise ContractError(code,reason)


class _ReadView:
    def __init__(self,raw,service,actor,authority,cut,access_context):
        self.raw,self.service,self.actor,self.authority,self.cut,self.context=raw,service,actor,authority,cut,access_context
        self.references={};self._authorized=set();self._records={}

    def _authorize(self,ref):
        ref=entity_ref(ref)
        if ref['scope_id']!=self.service.scope_id:_fail('foreign_query_reference','E_SCOPE_FORBIDDEN')
        if ref['record_type']==PROJECTION_TYPE and ref['namespace'].startswith('matter.'):return
        key=canonical_bytes(ref)
        if key not in self._authorized:
            self.service.controls._audit(self.raw,{'actor':self.actor,'authority':self.authority},[ref])
            self._authorized.add(key)

    def get(self,ref):
        self._authorize(ref)
        key=canonical_bytes(ref)
        if key in self._records:return deepcopy(self._records[key])
        if 'revision' not in ref and 'digest' not in ref:
            # The existing packet metadata resolver provides bounded historical
            # selection. Its raw view still receives current principal audits.
            try:exact=_pin_references(_Reads(_RawRead(self),self.service.scope_id),ref,self.cut)
            except ContractError as error:
                if error.code=='E_EVIDENCE_UNAVAILABLE':raise StorageError('E_NOT_FOUND') from None
                raise
        else:exact=fragment(ref,'pinned_ref')
        record=self.raw.get(exact)
        committed=self.raw.receipt_for(exact)
        if knowledge_eligible(committed['provenance']['recorded_at'],self.cut) is not True:
            _fail('record_not_known_at_query_cut','E_EVIDENCE_UNAVAILABLE')
        if self.service.access is not None:
            self.service.access.require_history(self.raw,self.context,references=[exact])
        self.references[canonical_bytes(exact)]=exact
        self._records[key]=record;self._records[canonical_bytes(pin(record))]=record
        return deepcopy(record)

    def receipt_for(self,ref):
        record=self.get(ref)
        return self.raw.receipt_for(pin(record))

    def lookup_identity(self,ref):return self.get(ref)

    def watchers(self,key):
        # Only used for a current inventory. Historical membership discovery is
        # deliberately not guessed from today's reverse watch table.
        return [self.get(pin(x)) for x in self.raw.watchers(key)]


class _RawRead:
    def __init__(self,owner):self.owner=owner
    def get(self,ref):
        self.owner._authorize(ref)
        return self.owner.raw.get(ref)
    def receipt_for(self,ref):return self.owner.raw.receipt_for(ref)


class QueryService:
    def __init__(self,storage,*,controls,assessments=None,delivery=None,payloads=None,access=None):
        if controls.scope_id!=storage.scope_id:_fail('query_service_scope','E_SCOPE_FORBIDDEN')
        self.storage,self.controls,self.scope_id=storage,controls,storage.scope_id
        self.assessments,self.delivery,self.payloads,self.access=assessments,delivery,payloads,access

    def project(self,matter,*,actor,authority,profile=None,purpose=None,audience=None,
                assessment=None,attention=None,authorizations=(),as_of=None,cursor=None,limit=100,
                include_payload=False,access_context=None):
        actor=fragment(actor,'actor_ref');authority=fragment(authority,'receipt_ref')
        if type(limit) is not int or not 1<=limit<=1000 or type(include_payload) is not bool:_fail('invalid_query_bounds','E_SCHEMA_INVALID')
        if not isinstance(authorizations,(tuple,list)):_fail('invalid_authorizations','E_SCHEMA_INVALID')
        if cursor is not None and (type(cursor) is not str or len(cursor)>8192):_fail('invalid_cursor','E_SCHEMA_INVALID')
        if len(authorizations)>128:_fail('delivery_query_limit','E_BUDGET_EXHAUSTED')
        if self.access is not None and access_context is None:_fail('query_access_context_required','E_AUTHORITY_REQUIRED')
        if self.access is None and access_context is not None:_fail('query_access_boundary_missing','E_AUTHORITY_REQUIRED')
        cut=fragment(as_of,'known_time') if as_of is not None else self.controls._time()
        # Metadata uses the storage knowledge clock. An injected domain clock
        # may predate system receipts; current reads use an unbounded metadata
        # cut while owners retain their actual domain/currentness clocks.
        if as_of is None:
            from datetime import datetime,timezone
            cut={'state':'known','value':datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z'),'precision':'microsecond'}
        with self.storage.snapshot() as raw:
            view=_ReadView(raw,self,actor,authority,cut,access_context)
            original=view.get(entity_ref(matter));group=read_group(view,self.scope_id,entity_ref(original))
            survivor=group['survivor'];members={canonical_bytes(entity_ref(x)) for x in group['members']}
            incomplete=[];records={};lane=None
            def add(ref):
                record=view.get(ref);records[canonical_bytes(pin(record))]=record;return record
            if assessment is None and profile is not None:
                if purpose is None:_fail('purpose_required','E_SCHEMA_INVALID')
                try:
                    lane=view.get(assessment_current_ref(self.scope_id,survivor,profile=profile,purpose=purpose,audience=audience))
                    assessment=lane['value']['value']['assessment']
                    if lane['value']['value']['status']!='current':incomplete.append('assessment_not_current')
                except StorageError as error:
                    if error.code!='E_NOT_FOUND':raise
                    incomplete.append('assessment_missing')
            assessed=add(assessment) if assessment is not None else None
            if assessed is not None:
                if assessed['record_type']!='assessment' or canonical_bytes(entity_ref(assessed['body']['matter'])) not in members:_fail('assessment_outside_matter')
                if as_of is None:
                    if self.assessments is None:incomplete.append('current_assessment_validator_not_configured')
                    else:
                        try:self.assessments.read_current(view,pin(assessed),assessed['body']['profile'])
                        except (ContractError,StorageError) as error:
                            if getattr(error,'code',None) not in {'E_DEPENDENCY_STALE','E_NOT_FOUND'}:raise
                            incomplete.append('assessment_stale')
                for ref in assessed['body']['judgments']:add(ref)
                for proposition in assessed['body']['propositions']:
                    claim=add(proposition['claim'])
                    for ref in claim['body']['attribution']:add(ref)
                for ref in assessed['body']['evidence_selection']['references']:add(ref)
            if as_of is None:
                inventory=collect_children(view,self.scope_id,group['members'])
                for item in inventory['children']:
                    if item['reference']['record_type']!=PROJECTION_TYPE:add(item['reference'])
                inventory_coverage='registered_current_inventory'
            else:
                inventory_coverage='explicit_assessment_references'
                incomplete.append('historical_full_child_catalog_not_claimed')
            decision=None
            if attention is not None:
                receipt=add(attention);decision=_value('attention-decision',receipt['body']['details'])
                if canonical_bytes(entity_ref(decision['matter'])) not in members or (assessed is not None and decision['assessment']!=pin(assessed)):_fail('attention_outside_selected_assessment')
            deliveries=[]
            for ref in authorizations:
                if self.delivery is None:_fail('delivery_reader_not_configured','E_POLICY_INVALID')
                from .outbox import authorization_value
                authorization=add(ref);auth=authorization_value(authorization)
                intent=self.delivery._intent(view.get(auth['intent']))
                if canonical_bytes(entity_ref(auth['matter'])) not in members:_fail('delivery_outside_matter')
                self.delivery._audit(view,intent)
                attempt=_value('delivery-attempt',view.get(self.delivery._attempt_ref(ref))['value'])
                deliveries.append({'authorization':pin(authorization),'status':'delivery_unknown' if attempt['status']=='authorized' else attempt['status'],
                    'observations':[add(x) for x in attempt['observations']]})
            ordered=sorted(records.values(),key=lambda r:canonical_bytes(pin(r)))
            query=canonical_digest({'scope':self.scope_id,'matter':entity_ref(matter),'profile':profile,'purpose':purpose,
                'audience':audience,'assessment':assessment,'attention':attention,'authorizations':list(authorizations),
                'as_of':as_of,'include_payload':include_payload,'actor':actor,'authority':authority},'matter.query.v1')
            snapshot=canonical_digest({'members':[pin(x) for x in group['members']],
                'indexes':[pin(x) for x in group['indexes']],'records':[pin(x) for x in ordered],
                'lane':None if lane is None else pin(lane),'incomplete':sorted(incomplete),
                'read_pins':sorted(view.references.values(),key=canonical_bytes),'deliveries':deliveries},'matter.query-snapshot.v1')
            offset=0
            if cursor is not None:
                try:
                    page=loads(base64.urlsafe_b64decode(cursor.encode('ascii')))
                    if set(page)!={'query','snapshot','offset'} or page['query']!=query or page['snapshot']!=snapshot:_fail('stale_or_foreign_cursor','E_DEPENDENCY_STALE')
                    offset=page['offset']
                    if type(offset) is not int or not 0<=offset<=len(ordered):_fail('invalid_cursor','E_SCHEMA_INVALID')
                except ContractError:raise
                except (ValueError,UnicodeError,TypeError,AttributeError):_fail('invalid_cursor','E_SCHEMA_INVALID')
            next_offset=offset+limit
            next_cursor=None if next_offset>=len(ordered) else base64.urlsafe_b64encode(canonical_bytes({'query':query,'snapshot':snapshot,'offset':next_offset})).decode('ascii')
            from .explain import explain_records
            explanation=explain_records(assessed,decision,ordered,payloads=self.payloads,include_payload=include_payload)
            if explanation['reconstruction']=='unavailable':incomplete.append('retained_material_unavailable')
            return {'schema_version':'1.0','scope_id':self.scope_id,'requested':pin(original),'resolved':pin(survivor),
                'redirected':entity_ref(original)!=entity_ref(survivor),'identity_members':[pin(x) for x in group['members']],
                'as_of':cut,'historical':as_of is not None,'inventory_coverage':inventory_coverage,
                'snapshot_digest':snapshot,'records':ordered[offset:next_offset],'next_cursor':next_cursor,
                'explanation':explanation,'deliveries':deliveries,'incomplete_reasons':sorted(set(incomplete)),
                'consequential_use':False}
