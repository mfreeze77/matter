"""MAT-074 shared admission fixtures and actual native operation result roundtrip."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from matter.canonical import canonical_bytes, canonical_digest
from matter.contracts import ContractError, decode_result
from matter.storage import SQLiteStore, pin
from matter.versioning import make_envelope, read_envelope, migration_manifest, require_migration_manifest, semantic_fingerprint
from integration.helpers import create_command

ROOT = Path(__file__).resolve().parents[2]


class VersionCompatibility(unittest.TestCase):
    def cases(self):
        return json.loads((ROOT/'tests/fixtures/versioning/compatibility.json').read_text())['cases']

    def inspect(self,case):
        try:
            source=bytes.fromhex(case['source_hex']) if 'source_hex' in case else case['source']
            value=read_envelope(source,supported_features=case['supported_features'],known_semantics=case['known_semantics'],expected_semantics=case.get('expected_semantics'))
            return {'status':'accepted','canonical':canonical_bytes(value).decode(),'sha256':canonical_digest(value,'compatibility-envelope')}
        except ContractError as error:
            return {'status':'refused','code':error.code}

    def test_python_reads_shared_cases_without_normalization_or_semantic_guess(self):
        for case in self.cases():
            with self.subTest(case=case['name']):self.assertEqual(self.inspect(case),case['expected'])
        cases={c['name']:c for c in self.cases()}
        self.assertNotEqual(cases['offset_as_opaque_string']['expected']['sha256'],cases['utc_as_opaque_string']['expected']['sha256'])

    def node(self,cases):
        if shutil.which('node') is None:self.skipTest('Node.js is required for independent language conformance')
        result=subprocess.run(['node',str(ROOT/'conformance/clients/javascript.mjs')],input=json.dumps({'cases':cases}),text=True,capture_output=True,timeout=15,check=True)
        return json.loads(result.stdout)

    def test_javascript_agrees_on_bytes_hashes_and_refusal_outcomes(self):
        cases=self.cases()
        self.assertEqual(self.node(cases),[c['expected'] for c in cases])

    def test_actual_native_result_with_extensions_survives_both_readers(self):
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteStore(Path(tmp)/'native.sqlite',scope_id='synthetic:compatibility') as store:
                command=create_command('compatibility-create','matter',scope_id=store.scope_id)
                def create(tx):return tx.success('created',{'matter':pin(tx.insert(tx.command['body']['matter']))})
                result=store.execute(command,create)
                self.assertEqual(result['status'],'success')
                self.assertEqual(store.execute(command,create),result)
                envelope=make_envelope(result,required_features=['native.result/1'],extensions={'unknown:future':{'keep':None,'value':'0.001'}})
                case={'source':canonical_bytes(envelope).decode(),'supported_features':['native.result/1'],'known_semantics':[]}
                expected=self.inspect(case);self.assertEqual(self.node([case]),[expected])
                decoded=read_envelope(expected['canonical'],supported_features=['native.result/1'])
                self.assertEqual(decode_result(canonical_bytes(decoded['payload'])),result)
                self.assertEqual(decoded['extensions'],envelope['extensions'])
                decoded['extensions'].clear()
                self.assertTrue(envelope['extensions'])

    def test_raw_and_encoded_bounds_and_invalid_configuration_are_refused(self):
        with self.assertRaises(ContractError) as large:read_envelope(' '* (2*1024*1024+1))
        self.assertEqual(large.exception.code,'E_BUDGET_EXHAUSTED')
        case={'source':' '*(2*1024*1024+1),'supported_features':[],'known_semantics':[]}
        self.assertEqual(self.node([case]),[{'status':'refused','code':'E_BUDGET_EXHAUSTED'}])
        for config in (None,'a',{'a':True}):
            with self.subTest(config=config),self.assertRaises(ContractError):make_envelope({},required_features=config)
        with self.assertRaises(ContractError):read_envelope(canonical_bytes(make_envelope({})),supported_features=None)

    def test_migration_manifest_is_installed_registry_not_untrusted_sql(self):
        manifest=migration_manifest()
        self.assertEqual(require_migration_manifest(manifest),manifest)
        self.assertEqual(manifest['rollback'],'restore_pre_upgrade_backup_before_new_writes')
        for key,value in [('target_version',999),('rollback','drop_history')]:
            foreign=deepcopy(manifest);foreign[key]=value
            with self.assertRaises(ContractError) as refused:require_migration_manifest(foreign)
            self.assertEqual(refused.exception.code,'E_VERSION_UNSUPPORTED')
        manifest['steps'][0]['sha256']='0'*64
        with self.assertRaises(ContractError):require_migration_manifest(manifest)

    def test_same_output_shape_does_not_reuse_changed_rule_meaning_or_missing_context(self):
        rule={'namespace':'synthetic','id':'rule','version':'1.0','digest':'1'*64}
        old=semantic_fingerprint(rule)
        changed=semantic_fingerprint({**rule,'digest':'2'*64})
        self.assertNotEqual(old,changed)
        original=make_envelope({'outcome':'quiet'},required_semantics=[old])
        revised=make_envelope(original['payload'],required_semantics=[changed])
        self.assertEqual(original['payload'],revised['payload'])
        for value in (revised,make_envelope(original['payload'])):
            with self.subTest(value=value),self.assertRaises(ContractError) as refused:
                read_envelope(canonical_bytes(value),known_semantics=[old,changed],expected_semantics=[old])
            self.assertEqual(refused.exception.code,'E_VERSION_UNSUPPORTED')
        with self.assertRaises(ContractError):semantic_fingerprint({**rule,'digest':'bad'})
