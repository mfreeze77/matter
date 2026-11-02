// MAT-074 compatibility client. It does not execute the Matter core or grant authority.
import { readFileSync, realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { canonical, canonicalDigest, ENCODING_VERSION, strictParse, CanonicalInputError } from "./canonical.mjs";

const MAX_BYTES = 2 * 1024 * 1024;
const MAX_DEPTH = 128;
const feature = /^[a-z][a-z0-9]*(?:[._/-][a-z0-9]+)*$/;
const digest = /^[0-9a-f]{64}$/;
export class CompatibilityError extends Error {
  constructor(code) { super(code); this.code=code; }
}
function fail(code="E_SCHEMA_INVALID") { throw new CompatibilityError(code); }
function list(value, pattern) {
  if (!Array.isArray(value) || value.length > 64 || value.some(x => typeof x!=="string" || x.length>128 || pattern.exec(x)?.[0]!==x) || new Set(value).size!==value.length) fail();
  return value;
}
export function readEnvelope(source, supportedFeatures=[], knownSemantics=[], expectedSemantics=null) {
  if (typeof source!=="string" && !(source instanceof Uint8Array)) fail();
  if (Buffer.byteLength(source,"utf8") > MAX_BYTES) fail("E_BUDGET_EXHAUSTED");
  let value;
  try { value=strictParse(source,MAX_DEPTH); }
  catch (error) { if (error instanceof CanonicalInputError) fail(); throw error; }
  const fields=["schema_version","encoding","required_features","required_semantics","payload","extensions"].sort();
  if (value===null || Array.isArray(value) || typeof value!=="object" || JSON.stringify(Object.keys(value).sort())!==JSON.stringify(fields)) fail();
  if (value.schema_version!=="1.0" || value.encoding!==ENCODING_VERSION) fail("E_VERSION_UNSUPPORTED");
  list(value.required_features,feature); list(value.required_semantics,digest);
  if (value.extensions===null || Array.isArray(value.extensions) || typeof value.extensions!=="object") fail();
  if (Buffer.byteLength(canonical(value),"utf8") > MAX_BYTES) fail("E_BUDGET_EXHAUSTED");
  list(supportedFeatures,feature); list(knownSemantics,digest);
  if (expectedSemantics!==null) list(expectedSemantics,digest);
  if (value.required_features.some(x=>!supportedFeatures.includes(x)) || value.required_semantics.some(x=>!knownSemantics.includes(x))) fail("E_VERSION_UNSUPPORTED");
  if (expectedSemantics!==null) {
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
    const hash=canonicalDigest(value,"compatibility-envelope");
    return {status:"accepted",canonical:encoded,sha256:hash};
  } catch(error) {
    if (error instanceof CompatibilityError) return {status:"refused",code:error.code};
    throw error;
  }
}
function isMain() {
  if (!process.argv[1]) return false;
  try { return realpathSync(fileURLToPath(import.meta.url))===realpathSync(process.argv[1]); }
  catch(error) {
    if (["ENOENT","ENOTDIR","EACCES","ELOOP"].includes(error.code)) return false;
    throw error;
  }
}
if (isMain()) {
  const request=strictParse(readFileSync(0));
  console.log(JSON.stringify(request.cases.map(inspect)));
}
