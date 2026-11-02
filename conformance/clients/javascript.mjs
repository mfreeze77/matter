// MAT-074 compatibility client. It does not execute the Matter core or grant authority.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { canonical, sha256, strictParse } from "../../tests/fixtures/canonical/codec.mjs";

const MAX_BYTES = 2 * 1024 * 1024;
const feature = /^[a-z][a-z0-9]*(?:[._/-][a-z0-9]+)*$/;
const digest = /^[0-9a-f]{64}$/;
function fail(code="E_SCHEMA_INVALID") { const error=new Error(code); error.code=code; throw error; }
function list(value, pattern) {
  if (!Array.isArray(value) || value.length > 64 || value.some(x => typeof x!=="string" || x.length>128 || pattern.exec(x)?.[0]!==x) || new Set(value).size!==value.length) fail();
  return value;
}
export function readEnvelope(source, supportedFeatures=[], knownSemantics=[], expectedSemantics=null) {
  if (Buffer.byteLength(source,"utf8") > MAX_BYTES) fail("E_BUDGET_EXHAUSTED");
  const value = strictParse(source);
  const fields=["schema_version","encoding","required_features","required_semantics","payload","extensions"].sort();
  if (value===null || Array.isArray(value) || typeof value!=="object" || JSON.stringify(Object.keys(value).sort())!==JSON.stringify(fields)) fail();
  if (value.schema_version!=="1.0" || value.encoding!=="matter-json-v1") fail("E_VERSION_UNSUPPORTED");
  list(value.required_features,feature); list(value.required_semantics,digest);
  if (value.extensions===null || Array.isArray(value.extensions) || typeof value.extensions!=="object") fail();
  if (Buffer.byteLength(canonical(value),"utf8") > MAX_BYTES) fail("E_BUDGET_EXHAUSTED");
  list(supportedFeatures,feature); list(knownSemantics,digest);
  if (value.required_features.some(x=>!supportedFeatures.includes(x)) || value.required_semantics.some(x=>!knownSemantics.includes(x))) fail("E_VERSION_UNSUPPORTED");
  if (expectedSemantics!==null) {
    list(expectedSemantics,digest);
    if (expectedSemantics.length!==value.required_semantics.length || expectedSemantics.some(x=>!value.required_semantics.includes(x))) fail("E_VERSION_UNSUPPORTED");
  }
  return value;
}
export function inspect(test) {
  try {
    const source=Object.hasOwn(test,"source_hex") ? Buffer.from(test.source_hex,"hex") : test.source;
    const features=Object.hasOwn(test,"supported_features") ? test.supported_features : [];
    const semantics=Object.hasOwn(test,"known_semantics") ? test.known_semantics : [];
    const value=readEnvelope(source,features,semantics,test.expected_semantics??null);
    const encoded=canonical(value);
    const hash=sha256(Buffer.concat([Buffer.from("matter-json-v1\0compatibility-envelope\0"),Buffer.from(encoded,"utf8")]));
    return {status:"accepted",canonical:encoded,sha256:hash};
  } catch(error) {
    return {status:"refused",code:["E_SCHEMA_INVALID","E_VERSION_UNSUPPORTED","E_BUDGET_EXHAUSTED"].includes(error.code)?error.code:"E_SCHEMA_INVALID"};
  }
}
if (process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
  const request=strictParse(readFileSync(0));
  console.log(JSON.stringify(request.cases.map(inspect)));
}
