"""MAT-074 shared admission fixtures and actual native operation result roundtrip."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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

    def native_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteStore(Path(tmp)/'native.sqlite',scope_id='synthetic:compatibility') as store:
                command=create_command('compatibility-create','matter',scope_id=store.scope_id)
                def create(tx):return tx.success('created',{'matter':pin(tx.insert(tx.command['body']['matter']))})
                result=store.execute(command,create)
                self.assertEqual(result['status'],'success')
                self.assertEqual(store.execute(command,create),result)
                envelope=make_envelope(result,required_features=['native.result/1'],extensions={'unknown:future':{'keep':None,'value':'0.001'}})
                case={'source':canonical_bytes(envelope).decode(),'supported_features':['native.result/1'],'known_semantics':[]}
                return result,envelope,case

    def test_actual_native_result_with_extensions_survives_python_reader(self):
        result,envelope,case=self.native_case()
        expected=self.inspect(case)
        decoded=read_envelope(expected['canonical'],supported_features=['native.result/1'])
        self.assertEqual(decode_result(canonical_bytes(decoded['payload'])),result)
        self.assertEqual(decoded['extensions'],envelope['extensions'])
        decoded['extensions'].clear()
        self.assertTrue(envelope['extensions'])

    def test_actual_native_result_survives_javascript_reader(self):
        _,_,case=self.native_case()
        self.assertEqual(self.node([case]),[self.inspect(case)])

    def test_raw_and_encoded_bounds_and_invalid_configuration_are_refused(self):
        with self.assertRaises(ContractError) as large:read_envelope(' '* (2*1024*1024+1))
        self.assertEqual(large.exception.code,'E_BUDGET_EXHAUSTED')
        for config in (None,'a',{'a':True}):
            with self.subTest(config=config),self.assertRaises(ContractError):make_envelope({},required_features=config)
        with self.assertRaises(ContractError):read_envelope(canonical_bytes(make_envelope({})),supported_features=None)
        with self.assertRaises(ContractError) as oversized:read_envelope('\ud800'+' '*(2*1024*1024))
        self.assertEqual(oversized.exception.code,'E_BUDGET_EXHAUSTED')
        with self.assertRaises(ContractError) as invalid:read_envelope('\ud800')
        self.assertEqual(invalid.exception.code,'E_SCHEMA_INVALID')

    def test_javascript_raw_bound_is_refused(self):
        case={'source':' '*(2*1024*1024+1),'supported_features':[],'known_semantics':[]}
        self.assertEqual(self.node([case]),[{'status':'refused','code':'E_BUDGET_EXHAUSTED'}])

    def test_producer_enforces_portable_container_depth(self):
        payload=None
        for _ in range(127):payload=[payload]
        make_envelope(payload) # root plus 127 payload containers = 128
        with self.assertRaises(ContractError) as refused:make_envelope([payload])
        self.assertEqual(refused.exception.code,'E_SCHEMA_INVALID')
        middle=None
        for _ in range(600):middle=[middle]
        with self.assertRaises(ContractError):make_envelope(middle)
        for _ in range(1500):payload=[payload]
        with self.assertRaises(ContractError):make_envelope(payload)
        cycle=[];cycle.append(cycle)
        with self.assertRaises(ContractError):make_envelope(cycle)

    def test_javascript_symlink_entry_and_unexpected_errors_are_not_silent(self):
        if shutil.which('node') is None:self.skipTest('Node.js is required')
        client=ROOT/'conformance/clients/javascript.mjs'
        with tempfile.TemporaryDirectory() as tmp:
            link=Path(tmp)/'client.mjs';link.symlink_to(client)
            result=subprocess.run(['node',str(link)],input='{"cases":[]}',text=True,capture_output=True,timeout=15,check=True)
            self.assertEqual(json.loads(result.stdout),[])
        script='import assert from "node:assert/strict"; import {inspect} from '+json.dumps(client.as_uri())+'; assert.throws(()=>inspect({get source(){throw new ReferenceError("synthetic internal bug")}}),ReferenceError);'
        subprocess.run(['node','--input-type=module','-e',script],check=True,capture_output=True,timeout=15)

    def test_javascript_import_modes_and_exported_reader_refusals(self):
        if shutil.which('node') is None:self.skipTest('Node.js is required')
        client=ROOT/'conformance/clients/javascript.mjs'
        script='import assert from "node:assert/strict"; import {readEnvelope,CompatibilityError} from '+json.dumps(client.as_uri())+'; for (const value of ["{",Buffer.from([255])]) assert.throws(()=>readEnvelope(value),e=>e instanceof CompatibilityError && e.code==="E_SCHEMA_INVALID"); const large=String.fromCharCode(0xd800)+" ".repeat(2*1024*1024); assert.throws(()=>readEnvelope(large),e=>e.code==="E_BUDGET_EXHAUSTED"); console.log("reader-import-ok");'
        with tempfile.TemporaryDirectory() as tmp:
            for args,input_ in ((['--input-type=module','-'],script),(['--input-type=module','-e',script,'nonexistent-argument'],None)):
                result=subprocess.run(['node',*args],input=input_,text=True,capture_output=True,cwd=tmp,timeout=15,check=True)
                self.assertEqual(result.stdout.strip(),'reader-import-ok')

    def test_internal_python_failures_are_not_relabelled_as_client_refusals(self):
        with patch('matter.versioning.loads',side_effect=TypeError('synthetic internal decoder bug')):
            with self.assertRaises(TypeError):read_envelope('{}')
        with patch('matter.versioning.migration_manifest',side_effect=ValueError('synthetic internal registry bug')):
            with self.assertRaises(ValueError) as internal:require_migration_manifest({})
            self.assertIs(type(internal.exception),ValueError)

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
