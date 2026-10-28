"""Synthetic plan isolation checks; no HTTP or actual credentials."""
from argparse import Namespace
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from matter.canonical import canonical_bytes, source_digest
from matter.semantic.families import with_packet
from matter.semantic.questions import QuestionSpecification

EXAMPLES=Path(__file__).resolve().parents[2]/'examples'
sys.path.insert(0,str(EXAMPLES))
try:
    spec=importlib.util.spec_from_file_location('guarded_diagnostic_example',EXAMPLES/'guarded_evidence_diagnostic.py')
    diagnostic=importlib.util.module_from_spec(spec);spec.loader.exec_module(diagnostic)
finally:sys.path.pop(0)


class DiagnosticPlanTests(unittest.TestCase):
    def test_external_plan_labels_stay_out_of_wire_and_digest_uses_executed_bytes(self):
        question=with_packet(QuestionSpecification({'schema_version':'1.0','namespace':'example','id':'synthetic-source','family':'diagnostic.source',
            'revision':'1.0','primitive':'proposition_probability','instructions':'Does the supplied synthetic source establish the proposition?',
            'criteria':{'true':'Established.','false':'Not established.'},'required_fields':[],
            'renderer':{'id':'canonical-json-bindings','version':'1.0'}}))
        sentinel='EXPECTATION_MUST_NOT_ENTER_PROVIDER_INPUT'
        plan={'id':'synthetic-source-plan','audiences':{'alpha':{'purpose':'Synthetic purpose A.'},'beta':{'purpose':'Synthetic purpose B.'}},
            'cases':[{'id':'p'+str(i),'cause':'new_evidence','prior_capture':'Declared synthetic history '+str(i),
                'expectations':{'alpha':{'note':sentinel},'beta':{'note':sentinel}}} for i in range(3)],
            'specifications':[question.value]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pdf=b'Synthetic PDF bytes, not a real document.';text=b'Synthetic source evidence.\n'
            (root/'source.pdf').write_bytes(pdf);(root/'source.md').write_bytes(text)
            (root/'provenance.json').write_text(json.dumps({'public_fetch_sha256':source_digest(pdf),'row':{'text':{'sha256':source_digest(text)}},
                'public_fetch_status':200,'permission_basis':'Synthetic unit fixture only.','custody':{'citation_url':'https://example.invalid/synthetic-source'}}))
            path=root/'plan.json';raw=canonical_bytes(plan);path.write_bytes(raw);seen=[]
            render=diagnostic.render_question
            def render_and_replace(*args,**kwargs):
                path.write_bytes(b'{}') # A changed file must not change the run's recorded plan digest.
                return render(*args,**kwargs)
            def capture(**kwargs):
                seen.append(kwargs)
                self.assertFalse(kwargs['live']);self.assertEqual(len(kwargs['cases']),6)
                self.assertEqual(kwargs['provenance']['plan_digest'],source_digest(raw))
                for case in kwargs['cases']:
                    wire=canonical_bytes(case.batch.value).decode()
                    self.assertNotIn(sentinel,wire)
                return {'status':'ready'}
            args=Namespace(evidence=root,env=root/'absent.env',model='jev-1.14.0',run_id='synthetic-plan',plan=path,live=False)
            with patch.object(diagnostic,'credential',return_value='synthetic-not-a-secret'),patch.object(diagnostic,'render_question',side_effect=render_and_replace),patch.object(diagnostic,'run_guarded_diagnostic',side_effect=capture),redirect_stdout(io.StringIO()):
                diagnostic.run(args)
            self.assertEqual(len(seen),1)

    def test_bad_plan_does_not_burn_run_id_and_legacy_small_input_stays_supported(self):
        from matter.semantic.providers.typesafe import TypeSafeHTTPExecutor
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pdf=b'Synthetic PDF.';text=b'Synthetic source.\n'
            (root/'source.pdf').write_bytes(pdf);(root/'source.md').write_bytes(text)
            (root/'provenance.json').write_text(json.dumps({'public_fetch_sha256':source_digest(pdf),'row':{'text':{'sha256':source_digest(text)}},
                'public_fetch_status':200,'permission_basis':'Synthetic unit fixture.','custody':{'citation_url':'https://example.invalid/synthetic'}}))
            path=root/'plan.json';path.write_bytes(canonical_bytes({'id':'bad-plan','audiences':{'alpha':{'purpose':'A'},'beta':{'purpose':'B'}},
                'cases':[{'id':'duplicate','cause':'new_evidence','prior_capture':'No prior synthetic capture.','expectations':{'alpha':{},'beta':{}}} for _ in range(3)],
                'specifications':[s.value for s in diagnostic.specifications()]}))
            args=Namespace(evidence=root,env=root/'absent.env',model='jev-1.14.0',run_id='reusable-id',plan=path,live=False)
            with patch.object(diagnostic,'credential') as secret,patch.object(diagnostic,'SQLiteStore') as store:
                with self.assertRaises(ValueError):diagnostic.run(args)
                secret.assert_not_called();store.assert_not_called()
            self.assertFalse((root/'host-reusable-id.sqlite').exists())
            args.plan=None;seen=[]
            def capture(**kwargs):
                adapter=TypeSafeHTTPExecutor(model='jev-1.14.0',api_key='synthetic-not-a-secret',timeout=30,max_calls=6,max_retries=0)
                for case in kwargs['cases']:
                    self.assertLessEqual(len(case.batch.canonical),65536)
                    self.assertLessEqual(len(adapter._request(case.batch)),65536)
                seen.extend(kwargs['cases']);return {'status':'ready'}
            with patch.object(diagnostic,'credential',return_value='synthetic-not-a-secret'),patch.object(diagnostic,'run_guarded_diagnostic',side_effect=capture),redirect_stdout(io.StringIO()):
                diagnostic.run(args)
            self.assertEqual(len(seen),6)
