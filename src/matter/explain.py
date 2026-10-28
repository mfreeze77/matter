"""MAT-023 receipt-derived explanations; no generated rationale or essay."""
from .canonical import source_digest
from .storage import pin
from .time import knowledge_eligible


def explain_records(assessment,decision,records,*,payloads=None,include_payload=False):
    result={'assessment':None if assessment is None else pin(assessment),
        'profile':None if assessment is None else assessment['body']['profile'],
        'knowledge_cut':None if assessment is None else assessment['body']['assessed_as_of'],
        'treatment':None if decision is None else decision['treatment'],
        'reasons':[] if decision is None else decision['reasons'],
        'propositions':[] if assessment is None else assessment['body']['propositions'],
        'limitations':[] if assessment is None else assessment['body']['limitations'],
        'evidence_gaps':[] if assessment is None else assessment['body']['evidence_gaps'],
        'sources':[],'judgments':[{'reference':pin(r),'rule':r['body']['rule'],
            'execution_status':r['body']['execution_status'],'evaluation_status':r['body']['evaluation_status'],
            'qualification':r['body']['qualification'],'semantic_output':r['body']['semantic_output']} for r in records if r['record_type']=='judgment'],
        'citations':[{'reference':pin(r),**r['body']} for r in records if r['record_type']=='evidence_relation'],
        'reconstruction':'not_requested' if not include_payload else 'available'}
    for record in records:
        if record['record_type']!='observation':continue
        body=record['body'];content=body['content'];cut=result['knowledge_cut']
        available=cut is None or knowledge_eligible(body['available_at'],cut) is True
        item={'reference':pin(record),'locator':content['locator'],'sha256':content['digest'],
              'available_at':body['available_at'],'status':'eligible' if available else 'unavailable_at_assessment_cut'}
        if include_payload:
            read=payloads.read(content) if payloads is not None and available else None
            if read is None or read.status!='available' or source_digest(read.data)!=content['digest']:
                item['reconstruction']='unavailable';result['reconstruction']='unavailable'
            else:
                try:item['text']=read.data.decode('utf-8');item['reconstruction']='available'
                except UnicodeDecodeError:item['reconstruction']='unavailable';result['reconstruction']='unavailable'
        result['sources'].append(item)
    return result
