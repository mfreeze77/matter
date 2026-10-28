"""MAT-048 invented source claims through actual neutral persistence services."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
import unittest

from matter.canonical import source_digest
from matter.civic_exports import prepare_export, CivicImportService, citation_text
from matter.contracts import ContractError
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, pin

AT={'state':'known','value':'2026-10-28T20:00:00Z','precision':'second'}
RAW=b'<!-- page 1 -->\nDraft R2026001.\nThe planning board recommends\napproval, subject to conditions.\nNo final vote is supplied.\n'
SHA='a'*64


def fixture():
    source={'sha256':SHA,'file_id':1,'publisher_path':'/public/1','page':None,'source_lines':[2,3],
            'char_start':None,'char_end':None,'quote':'The planning board recommends approval, subject to conditions.'}
    doc={'schema_version':'civic-matter-source-claims.v1','jurisdiction_key':'ks:county:example',
         'identities':[], 'claims':[{'matter':{'kind':'resolution','number':'R2026001','subtype':None},
            'family':'prior_recommendation','value':{'recommendation':'approval'},'value_as_written':source['quote'],
            'null_reason':None,'disposition':'stated','source':source}]}
    sources={SHA:{'bytes':RAW,'text_sha256':source_digest(RAW),'layout':'crawler_pdf_page_markers',
                  'uri':'https://example.gov/attachment/1','complete':False,'appearance_keys':['publisher:example:meeting-1']}}
    return doc,sources


def prepare(doc=None,sources=None,**kwargs):
    d,s=fixture();options={'jurisdiction':'ks:county:example','issuer':'example:board','year':2026,
        'package_sha256':'b'*64,'producer_revision':'test-revision','available_at':AT}
    options.update(kwargs)
    return prepare_export(doc if doc is not None else d,sources if sources is not None else s,**options)


class CivicExportTests(unittest.TestCase):
    def test_mapper_retains_original_quote_and_derived_span_without_final_authority(self):
        p=prepare().value
        self.assertEqual(len(p['claims']),1,p['refusals'])
        c=p['claims'][0]
        self.assertEqual(c['original']['source']['quote'],'The planning board recommends approval, subject to conditions.')
        self.assertIn('\n',c['exact_passage'])
        self.assertEqual(c['source_assertion']['stage'],'recommendation_reported')
        self.assertFalse(c['source_assertion']['established_legal_state'])
        self.assertEqual(c['source_assertion']['authority'],'unresolved')
        self.assertNotEqual(p['sources'][SHA]['text_sha256'],p['sources'][SHA]['original_text_sha256'])

    def test_missing_unknown_or_wrongly_cited_fields_are_explicit_refusals(self):
        for change,reason in [({'family':'new_unreviewed_family'},'unsupported_claim_family'),
                              ({'disposition':'approved'},'unsupported_claim_disposition'),
                              ({'new_field':'retain me'},'unsupported_claim_fields')]:
            doc,s=fixture();doc['claims'][0].update(change);p=prepare(doc,s).value
            self.assertFalse(p['claims']);self.assertEqual(p['refusals'][0]['reason'],reason)
            self.assertEqual(p['refusals'][0]['original'],doc['claims'][0])
        doc,s=fixture();doc['claims'][0]['source']['source_lines']=[1,1]
        self.assertEqual(prepare(doc,s).value['refusals'][0]['reason'],'quotation_not_in_declared_lines')
        self.assertEqual(prepare(sources={}).value['refusals'][0]['reason'],'source_bytes_unavailable')

    def test_hash_version_scope_and_layout_refuse_before_any_write(self):
        doc,s=fixture();s[SHA]['bytes']=b'altered'
        with self.assertRaisesRegex(ContractError,'source_text_hash_mismatch'):prepare(doc,s)
        for options in ({'year':None},{'year':True},{'jurisdiction':'ks:county:other'}):
            with self.assertRaises(ContractError):prepare(**options)
        with self.assertRaises(ContractError):citation_text(RAW,layout='guess')
        doc,s=fixture();doc['schema_version']='next-version'
        with self.assertRaises(ContractError):prepare(doc,s)

    def test_identity_does_not_join_different_issuer_year_kind_or_number(self):
        original=prepare().value['claims'][0]['subject_key']
        for options in ({'year':2025},{'issuer':'example:other'}):
            self.assertNotEqual(original,prepare(**options).value['claims'][0]['subject_key'])
        doc,s=fixture();doc['claims'][0]['matter']['kind']='ordinance'
        self.assertNotEqual(original,prepare(doc,s).value['claims'][0]['subject_key'])

    def test_actual_core_intake_claims_and_restart_replay_preserve_source_and_subject(self):
        with TemporaryDirectory() as d:
            scope='synthetic:civic-export';root=Path(d);plan=prepare()
            payloads=FilePayloadStore(root/'payloads',scope_id=scope)
            actor={'scope_id':scope,'namespace':'test','id':'host'}
            authority={'scope_id':scope,'namespace':'test','record_type':'receipt','id':'host-grant'}
            with SQLiteStore(root/'state.sqlite',scope_id=scope) as store:
                service=CivicImportService(store,payloads,actor=actor,authority=authority)
                first=service.import_export(plan)
                self.assertEqual((len(first['matters']),len(first['claims']),len(first['occurrences'])),(1,1,1))
                claim=store.get(first['claims'][0]);obs=store.get(first['observations'][0])
                self.assertFalse(claim['body']['value']['value']['established_legal_state'])
                self.assertEqual(service.intake.read_payload(pin(obs)).data,citation_text(RAW,layout='crawler_pdf_page_markers').encode())
                parent=store.get(obs['provenance']['parents'][0]);self.assertEqual(service.intake.read_payload(pin(parent)).data,RAW)
                self.assertEqual(service.import_export(plan),first)
            with SQLiteStore(root/'state.sqlite',scope_id=scope) as store:
                service=CivicImportService(store,payloads,actor=actor,authority=authority)
                self.assertEqual(service.import_export(plan),first)
                newer=prepare(package_sha256='c'*64,producer_revision='new-exporter',available_at={**AT,'value':'2026-10-29T20:00:00Z'})
                reused=service.import_export(newer)
                self.assertEqual(first['claims'],reused['claims']);self.assertEqual(first['observations'],reused['observations'])
                self.assertEqual(first['matters'],reused['matters'])
                self.assertEqual(store.get(first['claims'][0]),claim)
                doc,sources=fixture();sources[SHA]['appearance_keys']=['publisher:example:meeting-2']
                another=service.import_export(prepare(doc,sources))
                self.assertEqual(first['matters'],another['matters'])
                self.assertNotEqual(first['occurrences'],another['occurrences'])

    def test_malformed_rows_refuse_without_losing_valid_rows(self):
        for path in ('kind','family','disposition','sha256'):
            for bad in ([], {}):
                doc,sources=fixture(); row=deepcopy(doc['claims'][0])
                target=row['matter'] if path=='kind' else row['source'] if path=='sha256' else row
                target[path]=bad;doc['claims'].append(row)
                result=prepare(doc,sources).value
                self.assertEqual(len(result['claims']),1)
                self.assertEqual(len(result['refusals']),1)
        doc,sources=fixture();sources[SHA]['appearance_keys']*=2
        with self.assertRaisesRegex(ContractError,'bounded_host_appearance_keys_required'):prepare(doc,sources)

    def test_scoped_appearance_union_and_changed_derivation(self):
        with TemporaryDirectory() as directory:
            scope='synthetic:civic-export';root=Path(directory)
            with SQLiteStore(root/'state.sqlite',scope_id=scope) as store:
                service=CivicImportService(store,FilePayloadStore(root/'payloads',scope_id=scope),
                    actor={'scope_id':scope,'namespace':'test','id':'host'},
                    authority={'scope_id':scope,'namespace':'test','record_type':'receipt','id':'host-grant'})
                first=service.import_export(prepare())
                doc,sources=fixture();other='d'*64
                doc['claims'][0]['source']['sha256']=other
                sources[other]=sources.pop(SHA)
                sources[other]['bytes']+=b'Second report.\n'
                sources[other]['text_sha256']=source_digest(sources[other]['bytes'])
                second=service.import_export(prepare(doc,sources))
                self.assertEqual(first['occurrences'][0]['id'],second['occurrences'][0]['id'])
                self.assertNotEqual(first['occurrences'],second['occurrences'])
                self.assertEqual(len(store.get(second['occurrences'][0])['body']['observations']),2)
                self.assertEqual(service.import_export(prepare(doc,sources)),second)
                doc['jurisdiction_key']='ks:county:other'
                third=service.import_export(prepare(doc,sources,jurisdiction='ks:county:other'))
                self.assertNotEqual(second['occurrences'][0]['id'],third['occurrences'][0]['id'])
                doc,sources=fixture();sources[SHA]['complete']=True
                changed=service.import_export(prepare(doc,sources))
                self.assertNotEqual(first['claims'],changed['claims'])
                self.assertEqual(service.import_export(prepare(doc,sources)),changed)
                self.assertFalse(store.get(first['claims'][0])['body']['qualifiers'][0]['value']['source_derivation']['complete'])

    def test_unmapped_scope_and_noncanonical_document_refuse(self):
        for field,value in (('subtype','special'),('issuer','different')):
            doc,sources=fixture();doc['claims'][0]['matter'][field]=value
            self.assertEqual(prepare(doc,sources).value['refusals'][0]['reason'],'unsupported_matter_scope')
        doc,sources=fixture();doc['claims'][0]['value']=0.5
        with self.assertRaisesRegex(ContractError,'non_canonical_export'):prepare(doc,sources)

    def test_checkpoint_retains_package_identity_proposals_refusals_and_old_links(self):
        with TemporaryDirectory() as directory:
            scope='synthetic:checkpoint';root=Path(directory)
            doc,sources=fixture();doc['identities']=[{'alias':'R2026001','status':'proposal'}]
            doc['future_contract']='unmapped';bad=deepcopy(doc['claims'][0]);bad['family']='future_family';doc['claims'].append(bad)
            plan=prepare(doc,sources)
            with SQLiteStore(root/'state.sqlite',scope_id=scope) as store:
                service=CivicImportService(store,FilePayloadStore(root/'payloads',scope_id=scope),
                    actor={'scope_id':scope,'namespace':'test','id':'host'},
                    authority={'scope_id':scope,'namespace':'test','record_type':'receipt','id':'host-grant'})
                result=service.import_export(plan)
                checkpoint=json.loads(service.intake.read_payload(result['checkpoint']).data)
                self.assertEqual(checkpoint['native_identities'],doc['identities'])
                self.assertEqual(checkpoint['refusals'][0]['reason'],'unsupported_claim_family')
                self.assertEqual(checkpoint['unmapped_top_fields'],['future_contract'])
                self.assertEqual(checkpoint['committed_references']['claims'],result['claims'])
                self.assertEqual(service.import_export(plan),result)


if __name__=='__main__':unittest.main()
