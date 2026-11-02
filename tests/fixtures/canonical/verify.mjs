// Independent portable-vector verifier. No Matter runtime code or Python bridge.
// MAT-074 adds the strict decoder; native record schemas remain separate.
import assert from "node:assert/strict";
import { canonical, sha256, strictParse } from "./codec.mjs";
import { readFile } from "node:fs/promises";

const fixture = JSON.parse(await readFile(new URL("./golden.json", import.meta.url), "utf8"));
assert.equal(fixture.encoding_version, "matter-json-v1");

for (const vector of fixture.vectors) {
  const actual = Buffer.from(canonical(strictParse(vector.input_json)), "utf8");
  assert.equal(actual.toString("hex"), vector.canonical_utf8_hex, `${vector.name}: bytes`);
  assert.equal(Buffer.from(vector.canonical_json, "utf8").toString("hex"), vector.canonical_utf8_hex);
  assert.match(vector.kind, /^[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*$/);
  assert.ok(vector.kind.length <= 128);
  const preimage = Buffer.concat([
    Buffer.from("matter-json-v1\0", "ascii"),
    Buffer.from(vector.kind, "ascii"),
    Buffer.from([0]),
    actual,
  ]);
  assert.equal(sha256(preimage), vector.sha256, `${vector.name}: contract digest`);
  assert.equal(sha256(Buffer.from(vector.input_json, "utf8")), vector.source_sha256, `${vector.name}: source digest`);
}

for (const vector of fixture.source_vectors) {
  assert.equal(sha256(Buffer.from(vector.source_hex, "hex")), vector.sha256, `${vector.name}: source bytes`);
}

const invalid=JSON.parse(await readFile(new URL("./invalid.json",import.meta.url),"utf8"));
for (const vector of invalid.vectors) {
  const source=Object.hasOwn(vector,"input_hex") ? Buffer.from(vector.input_hex,"hex") : vector.input_json;
  assert.throws(()=>strictParse(source),undefined,vector.name);
}
console.log(`Verified ${fixture.vectors.length} canonical vectors, ${fixture.source_vectors.length} exact-source vectors and ${invalid.vectors.length} strict refusals in JavaScript.`);
