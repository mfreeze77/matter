"""MAT-048: explicit read-only mapping of crawler source claims, never legal state.

The host reads its copied package, supplies exact text bytes/derivation hashes and
an issuer/year identity scope. This adapter never fetches, merges receiver rows,
infers authority, follows URLs, or treats a missing row as withdrawal. Line views
reuse the receiver's documented PDF-page-marker removal and whitespace comparison;
original text, producer quote and both hashes remain independently inspectable.
"""
from copy import deepcopy
import re

from .canonical import canonical_bytes, canonical_digest, source_digest
from .contracts import ContractError
from .identity_keys import ExactIdentityPolicy
from .matters import MatterService
from .observations import ObservationIngestor
from .claims import ClaimService
from .occurrences import OccurrenceService, ExactGroupingPolicy
from .storage import pin, entity_ref, StorageError
from ._rule_values import FrozenValue

VERSION = 'matter.civic-export/1.0'
NAMESPACE = 'matter.civic.exports'
SUBJECT_KEYS = NAMESPACE + ':subject'
KINDS = {'ordinance', 'charter_ordinance', 'resolution', 'charter_resolution', 'land_use_case'}
FAMILIES = {'prior_recommendation', 'applicant', 'agent', 'condition', 'term', 'expiry',
            'renewal_of', 'in_conjunction_with', 'draft_to_instrument', 'publication',
            'effective', 'codification', 'amends', 'repeals'}
SOURCE_FIELDS = {'sha256', 'file_id', 'publisher_path', 'page', 'source_lines', 'char_start', 'char_end', 'quote'}
PRODUCER = {'namespace': NAMESPACE, 'id': 'source-claim-mapper', 'version': '1.0',
            'digest': canonical_digest({'version': VERSION, 'identity': 'host-issuer-year-kind-opaque-number',
                'authority': 'unresolved', 'citation': 'declared-pdf-page-markers-then-LF-lines',
                'claims': 'source-assertions-only'}, 'matter.civic-export-contract.v1')}


def _fail(reason):
    raise ContractError('E_EVIDENCE_INVALID', reason)


def _text(value, reason, maximum=1024):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        _fail(reason)
    return value


def citation_text(raw, *, layout):
    """An explicit derived view; preserve raw bytes/hash outside this return value."""
    if type(raw) is not bytes or len(raw) > 524288:
        _fail('bounded_original_text_required')
    try:
        text = raw.decode('utf-8', errors='strict')
    except UnicodeError:
        _fail('invalid_source_utf8')
    if layout == 'publisher_lf':
        return text
    if layout == 'crawler_pdf_page_markers':
        return '\n'.join(line for line in text.split('\n')
                         if not re.fullmatch(r'<!-- page [1-9][0-9]* -->', line))
    _fail('undeclared_text_layout')


def _comparable(value):
    # Same comparison meaning as StateCivics core_import/minutes_citations.py.
    # Only matching is folded; producer wording and exact cited span are retained.
    return ' '.join(value.replace('\r', '').replace('•', '*').split())


class PreparedCivicExport(FrozenValue):
    def __init__(self, value, *, _prepared=False):
        if not _prepared:
            _fail('use_prepare_export')
        self._freeze(value)


def prepare_export(document, sources, *, jurisdiction, issuer, year, package_sha256,
                   producer_revision, available_at):
    """Validate the whole bounded input before producing any write operations.

    sources is keyed by original source SHA, each value declaring text bytes,
    their independent SHA, explicit layout, URI and completeness. Native source
    SHA often names a PDF, not its extracted text: those hashes are never equated.
    """
    if type(document) is not dict or document.get('schema_version') != 'civic-matter-source-claims.v1':
        _fail('unsupported_crawler_source_claims_version')
    if document.get('jurisdiction_key') != jurisdiction:
        _fail('jurisdiction_mismatch')
    _text(jurisdiction, 'jurisdiction_required'); _text(issuer, 'issuer_required')
    if type(year) is not int or not 1900 <= year <= 2200:
        _fail('explicit_identity_year_required')
    if not re.fullmatch('[0-9a-f]{64}', package_sha256):
        _fail('package_sha256_required')
    _text(producer_revision, 'producer_revision_required')
    if available_at.get('state') != 'known':
        _fail('actual_availability_required')
    if type(sources) is not dict or len(sources) > 64:
        _fail('bounded_source_map_required')
    if sum(len(v.get('bytes', b'')) for v in sources.values() if type(v) is dict and type(v.get('bytes')) is bytes) > 4194304:
        _fail('aggregate_source_byte_limit')
    rows = document.get('claims')
    identities = document.get('identities')
    if type(rows) is not list or type(identities) is not list or len(rows) > 4096 or len(identities) > 4096:
        _fail('bounded_claims_and_identities_required')
    if len(canonical_bytes(document)) > 2097152:
        _fail('export_byte_limit')
    prepared, refusals, normalized, used = [], [], {}, set()
    for n, row in enumerate(rows):
        reason = None
        if type(row) is not dict:
            refusals.append({'index': n, 'reason': 'invalid_claim', 'original': deepcopy(row)}); continue
        matter, source = row.get('matter'), row.get('source')
        if type(matter) is not dict or matter.get('kind') not in KINDS or type(matter.get('number')) is not str or not matter['number'].strip():
            reason = 'unscoped_or_invalid_matter'
        elif set(row) - {'matter', 'family', 'value', 'value_as_written', 'null_reason', 'disposition', 'source'}:
            reason = 'unsupported_claim_fields'
        elif row.get('family') not in FAMILIES:
            reason = 'unsupported_claim_family'
        elif row.get('disposition') not in {'stated', 'ambiguous', 'unresolved'}:
            reason = 'unsupported_claim_disposition'
        elif type(source) is not dict or set(source) - SOURCE_FIELDS:
            reason = 'unsupported_source_fields'
        if reason:
            refusals.append({'index': n, 'reason': reason, 'original': deepcopy(row)}); continue
        sha = source.get('sha256')
        material = sources.get(sha)
        if material is None:
            refusals.append({'index': n, 'reason': 'source_bytes_unavailable', 'original': deepcopy(row)}); continue
        if sha not in normalized:
            raw = material.get('bytes')
            if type(raw) is not bytes or source_digest(raw) != material.get('text_sha256'):
                _fail('source_text_hash_mismatch')
            view = citation_text(raw, layout=material.get('layout'))
            uri = _text(material.get('uri'), 'source_uri_required', 4096)
            normalized[sha] = {'source_sha256': sha, 'original_text_sha256': source_digest(raw),
                'text': view, 'original_text': raw.decode('utf-8'), 'text_sha256': source_digest(view.encode()), 'layout': material['layout'],
                'uri': uri, 'complete': material.get('complete') is True,
                'appearance_keys': deepcopy(material.get('appearance_keys', []))}
            if (type(normalized[sha]['appearance_keys']) is not list or len(normalized[sha]['appearance_keys']) > 32
                    or any(type(k) is not str or not 1 <= len(k) <= 2048 for k in normalized[sha]['appearance_keys'])):
                _fail('bounded_host_appearance_keys_required')
        data = normalized[sha]
        lines, quote = source.get('source_lines'), source.get('quote')
        if (type(lines) is not list or len(lines) != 2 or any(type(i) is not int for i in lines)
                or not 1 <= lines[0] <= lines[1] <= len(data['text'].split('\n'))):
            reason = 'exact_source_lines_required'
        elif type(quote) is not str or not quote.strip():
            reason = 'source_quote_required'
        else:
            span = '\n'.join(data['text'].split('\n')[lines[0]-1:lines[1]])
            if _comparable(quote) not in _comparable(span):
                reason = 'quotation_not_in_declared_lines'
        if reason:
            refusals.append({'index': n, 'reason': reason, 'original': deepcopy(row)}); continue
        key = canonical_digest({'jurisdiction': jurisdiction, 'issuer': issuer, 'year': year,
            'kind': matter['kind'], 'number': matter['number']}, 'matter.civic-subject.v1')
        identity = canonical_digest({'row': row, 'subject_key': key, 'text_sha256': data['text_sha256']}, 'matter.civic-source-claim.v1')
        if identity in used:
            refusals.append({'index': n, 'reason': 'duplicate_claim_row', 'original': deepcopy(row)}); continue
        used.add(identity)
        prepared.append({'id': identity, 'subject_key': key, 'source_sha256': sha,
            'original': deepcopy(row), 'exact_passage': span,
            'source_assertion': {'state': row['disposition'], 'family': row['family'],
                'value': deepcopy(row.get('value')), 'stage': 'recommendation_reported' if row['family']=='prior_recommendation' else 'not_inferred',
                'authority': 'unresolved', 'established_legal_state': False}})
    return PreparedCivicExport({'version': VERSION, 'jurisdiction': jurisdiction, 'issuer': issuer, 'year': year,
        'package_sha256': package_sha256, 'producer_revision': producer_revision,
        'available_at': deepcopy(available_at), 'claims': prepared, 'sources': normalized,
        'refusals': refusals, 'native_identities': deepcopy(identities),
        'unmapped_top_fields': sorted(set(document)-{'schema_version','jurisdiction_key','identities','claims','note'}),
        'identity_policy': 'native aliases/conflicts retained as proposals; no alias binding or merge',
        'withdrawals': 'not inferred from absent rows', 'authority': 'unresolved',
        'qualification': 'unknown', 'consequential_use': False}, _prepared=True)


class CivicImportService:
    """Install prepared source assertions through existing neutral core services.

    A bounded import is resumable via deterministic command IDs; individual core
    commands are atomic. It is not an atomic replacement snapshot or withdrawal.
    """
    def __init__(self, storage, payloads, *, actor, authority):
        self.storage, self.payloads = storage, payloads
        self.actor, self.authority = deepcopy(actor), deepcopy(authority)
        self.policy = ExactIdentityPolicy(key_namespaces=[SUBJECT_KEYS])
        self.matters = MatterService(storage, identity_policy=self.policy)
        self.intake = ObservationIngestor(storage, payloads)
        self.claims = ClaimService(storage)
        self.grouping = ExactGroupingPolicy(key_namespaces=[NAMESPACE+':appearance'], group_namespaces=[NAMESPACE+':lineage'])
        self.occurrences = OccurrenceService(storage, grouping_policy=self.grouping)

    def import_export(self, prepared):
        if not isinstance(prepared, PreparedCivicExport):
            _fail('prepared_export_required')
        prepared = prepared.value
        scope, at = self.storage.scope_id, prepared['available_at']
        def command(label, operation, body):
            return {'schema_version':'1.0','operation':operation,'scope_id':scope,
                'command_id':label,'idempotency_key':label,'actor':self.actor,'authority':self.authority,
                'expected_revisions':[],'body':body}
        def record(kind, identity, body, *, origin='host', parents=()):
            return {'schema_version':'1.0','record_type':kind,'scope_id':scope,'namespace':NAMESPACE,'id':identity,
                'provenance':{'origin':origin,'producer':PRODUCER,'recorded_at':at,'parents':list(parents)},'body':body}
        def require(result):
            if result['status'] != 'success':
                raise ContractError(result['error']['code'], 'civic_import_core_refused')
            return result
        def existing(kind, identity):
            try:
                return self.storage.get({'scope_id':scope,'namespace':NAMESPACE,'record_type':kind,'id':identity})
            except StorageError as error:
                if error.code != 'E_NOT_FOUND':
                    raise
                return None
        source_refs, subjects, claim_refs = {}, {}, []
        for sha, data in prepared['sources'].items():
            raw = data['text'].encode()
            body={'source_identity':{'namespace':NAMESPACE+':source','event_id':sha,'revision_id':data['text_sha256']},
                'content':{'digest':data['text_sha256'],'byte_length':len(raw),'media_type':'text/plain',
                    'locator':{'kind':'whole_artifact','uri':data['uri']},'availability':{'status':'available','checked_at':at}},
                'occurred_at':{'state':'unknown','reason':'not_reported'},
                'source_published_at':{'state':'unknown','reason':'not_reported'},
                'available_at':at,'ingested_at':at,'extraction':PRODUCER}
            # The source SHA names the original artifact; the retained payload is explicitly its derived citation view.
            identity='source-'+sha+'-'+data['text_sha256']
            old=existing('observation',identity)
            if old is not None:
                if (old['body']['content']['digest'] != data['text_sha256'] or old['body']['content']['locator'] != body['content']['locator']):
                    _fail('existing_source_identity_conflict')
                source_refs[sha]=pin(old)
                continue
            # Retain the exact exported extraction before its declared citation-view derivation.
            original=data['original_text'].encode()
            original_body=deepcopy(body)
            original_body['source_identity']['namespace']=NAMESPACE+':exported-text'
            original_body['source_identity']['revision_id']=data['original_text_sha256']
            original_body['content'].update(digest=data['original_text_sha256'],byte_length=len(original),media_type='text/markdown')
            original_id='exported-'+sha+'-'+data['original_text_sha256']
            parent=existing('observation',original_id)
            if parent is None:
                parent_input=record('observation',original_id,original_body,origin='source')
                parent_result=require(self.intake.ingest(self.intake.prepare(command(original_id,'ingest_observation',{'observation':parent_input})),payload=original))
                parent=self.storage.get(parent_result['body']['observation'])
            obs=record('observation',identity,body,origin='derived',parents=[pin(parent)])
            c=self.intake.prepare(command('source-'+sha+'-'+data['text_sha256'],'ingest_observation',{'observation':obs}))
            result=require(self.intake.ingest(c,payload=raw));source_refs[sha]=result['body']['observation']
        appearances={}
        for sha,data in prepared['sources'].items():
            for key in data['appearance_keys']:
                appearances.setdefault(key,[]).append(source_refs[sha])
        occurrence_refs=[]
        for key,observations in appearances.items():
            identity=canonical_digest({'jurisdiction':prepared['jurisdiction'],'appearance':key},'matter.civic-appearance.v1')
            old=existing('occurrence','appearance-'+identity)
            if old is not None:
                observations=list({canonical_bytes(x):x for x in old['body']['observations']+observations}.values())
                if {canonical_bytes(x) for x in observations} == {canonical_bytes(x) for x in old['body']['observations']}:
                    occurrence_refs.append(pin(old));continue
            proposed=record('occurrence','appearance-'+identity,{'kind':'civic:source_appearance',
                'identity_keys':[{'namespace':NAMESPACE+':appearance','value':key}],
                'observations':observations,'provenance_groups':[], 'occurred_at':{'state':'unknown','reason':'not_reported'}})
            body={'creates':[proposed] if old is None else [],
                'replacements':[] if old is None else [{'occurrence':pin(old),'observations':observations}],
                'provenance_assignments':[], 'grouping_policy':self.grouping.reference,
                'basis':{'schema':PRODUCER,'value':{'appearance_key':key,'meaning':'source appearance, not every historical action mentioned'}}}
            label='appearance-'+identity+'-'+canonical_digest(observations,'matter.civic-appearance-members.v1')
            result=require(self.occurrences.commit(self.occurrences.prepare(command(label,'commit_occurrence_grouping',body))))
            occurrence_refs.extend(result['body']['occurrences'])
        for row in prepared['claims']:
            key=row['subject_key'];native=row['original']['matter']
            if key not in subjects:
                proposed=record('matter','subject-'+key,{'domain_kind':'civic:'+native['kind'],
                    'identity_keys':[{'namespace':SUBJECT_KEYS,'value':key}], 'title':native['number']})
                old=existing('matter','subject-'+key)
                if old is None:
                    result=require(self.matters.create(self.matters.prepare(command('subject-'+key,'create_matter',
                        {'matter':proposed,'identity_policy':self.policy.reference}))));subjects[key]=result['body']['matter']
                else:
                    if old['body']['identity_keys'] != proposed['body']['identity_keys'] or old['body']['domain_kind'] != proposed['body']['domain_kind']:
                        _fail('existing_subject_conflict')
                    subjects[key]=pin(old)
            body={'subject':entity_ref(subjects[key]), 'predicate':'civic:source:'+row['original']['family'],
                'value':{'schema':PRODUCER,'value':row['source_assertion']},
                'qualifiers':[{'schema':PRODUCER,'value':{'original':row['original'],'exact_passage':row['exact_passage'],
                    'source_derivation':{k:v for k,v in prepared['sources'][row['source_sha256']].items() if k not in {'text','original_text','appearance_keys'}}}}],
                'applicability':{'start':{'state':'unknown','reason':'not_reported'},'end':{'state':'unknown','reason':'not_reported'},'bounds':'closed'},
                'attribution':[source_refs[row['source_sha256']]],'proposition_version':row['id']}
            old=existing('claim','claim-'+row['id'])
            if old is not None:
                if old['body'] != body:
                    _fail('existing_claim_conflict')
                claim_refs.append(pin(old));continue
            c=self.claims.prepare(command('claim-'+row['id'],'append_claim',{'claim':record('claim','claim-'+row['id'],body,
                parents=[source_refs[row['source_sha256']]])}))
            result=require(self.claims.append(c));claim_refs.append(result['body']['claim'])
        return {'matters':list(subjects.values()),'observations':list(source_refs.values()),'claims':claim_refs,'occurrences':occurrence_refs,
            'refusals':deepcopy(prepared['refusals']),'package_sha256':prepared['package_sha256'], 'producer_revision':prepared['producer_revision'], 'authority':'unresolved','qualification':'unknown','consequential_use':False}
