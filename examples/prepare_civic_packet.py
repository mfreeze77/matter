"""Read selected members of an existing processed ZIP; no extraction or crawling.

Public real bytes stay in an external private study directory. Original PDF
hashes are producer metadata, not a claim that this tool verified PDF bytes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from matter.canonical import canonical_bytes, source_digest, loads
from matter.civic_exports import prepare_export


def metadata(raw):
    # Producer inventories include decimal timing metrics. Preserve their exact
    # lexemes as explicitly tagged metadata, never claim probabilities/numbers.
    # The native claim contract itself still uses strict matter-json-v1 loads.
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate_producer_metadata_key')
            result[key]=value
        return result
    def nonfinite(_):raise ValueError('nonfinite_producer_metadata')
    return json.loads(raw,object_pairs_hook=unique,parse_float=lambda token:{'json_decimal_lexeme':token},parse_constant=nonfinite)


def prepare(package, output):
    output=output.resolve();repo=Path(__file__).resolve().parents[1]
    if output==repo or repo in output.parents:raise ValueError('external_output_required')
    sha=hashlib.sha256()
    with package.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):sha.update(block)
    def member(z,name,limit):
        info=z.getinfo(name)
        if info.file_size>limit:raise ValueError('member_exceeds_bound')
        return z.read(info)
    with ZipFile(package) as z:
        native=loads(member(z,'bundle/matter_source_claims.json',2097152))
        documents=metadata(member(z,'bundle/document_text.json',8388608))
        manifest=metadata(member(z,'bundle/capture_manifest.json',8388608))
        # This is an explicit one-case exploratory selection, not discovery.
        claims=[r for r in native['claims'] if r['matter']['number']=='R2026005']
        if not claims:raise ValueError('selected_case_missing')
        sha_pdf=claims[0]['source']['sha256']
        if any(r['source']['file_id']!=8751 or r['source']['sha256']!=sha_pdf for r in claims):
            raise ValueError('selected_attachment_changed_requires_explicit_reselection')
        rows=documents if type(documents)is list else documents['documents']
        row=next(r for r in rows if r['sha256']==sha_pdf)
        if row['year']!=2026 or not any(m.get('event_id')==1283 for m in row['meetings']):
            raise ValueError('selected_publisher_appearance_changed')
        path='derived/pdf_text_layer/'+sha_pdf[:2]+'/'+sha_pdf+'.md'
        raw=member(z,path,524288)
        if source_digest(raw)!=row['text']['sha256']:raise ValueError('text_digest_mismatch')
    at={'state':'known','value':datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z'),'precision':'microsecond'}
    source={'bytes':raw,'text_sha256':source_digest(raw),'layout':'crawler_pdf_page_markers',
        'uri':'https://shawneecoks.api.civicclerk.com/v1/Meetings/GetAttachmentFile(fileId=8751)',
        'complete':row['text']['complete'],'appearance_keys':['civicclerk:shawneecoks:event:1283']}
    native={**native,'claims':claims}
    plan=prepare_export(native,{sha_pdf:source},jurisdiction=native['jurisdiction_key'],
        issuer='civicclerk:shawneecoks:board-of-county-commissioners',year=2026,
        package_sha256=sha.hexdigest(),producer_revision=manifest['crawler_commit'],available_at=at)
    value=plan.value
    output.mkdir(parents=True,exist_ok=False,mode=0o700)
    source.pop('bytes');source['text']=raw.decode()
    (output/'packet.json').write_bytes(canonical_bytes({'native':native,'sources':{sha_pdf:source},
        'jurisdiction':value['jurisdiction'],'issuer':value['issuer'],'year':value['year'],
        'package_sha256':sha.hexdigest(),'producer_revision':manifest['crawler_commit'],'available_at':at,
        'producer_worktree_files':manifest.get('exporter_code',{}).get('worktree_files'),
        'public_permission':'Official public county attachment; existing owner-authorized bounded capture-only study.',
        'pdf_bytes_verified':False})+b'\n')
    (output/'preparation.json').write_bytes(canonical_bytes({'accepted':len(value['claims']),
        'refusals':value['refusals'],'package_sha256':sha.hexdigest(),'text_sha256':source['text_sha256'],
        'coverage':source['complete'],'pdf_bytes_verified':False,'qualification':'unknown'})+b'\n')
    print(json.dumps({'accepted':len(value['claims']),'refusals':len(value['refusals']),'output':str(output)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();prepare(args.package,args.output)
