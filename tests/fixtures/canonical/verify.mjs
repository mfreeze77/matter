// Independent portable-vector verifier. No Matter runtime code or Python bridge.
// This is not a second production decoder: JSON.parse loses duplicate-key and
// numeric-token spelling information. Only the declared positive vectors use it.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

const fixture = JSON.parse(await readFile(new URL("./golden.json", import.meta.url), "utf8"));
assert.equal(fixture.encoding_version, "matter-json-v1");

function scalarCompare(left, right) {
  const a = Array.from(left, (character) => character.codePointAt(0));
  const b = Array.from(right, (character) => character.codePointAt(0));
  const count = Math.min(a.length, b.length);
  for (let index = 0; index < count; index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function string(value) {
  for (const character of value) {
    const scalar = character.codePointAt(0);
    assert.ok(scalar < 0xd800 || scalar > 0xdfff, "invalid Unicode scalar");
  }
  return JSON.stringify(value);
}

function canonical(value) {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return string(value);
  if (typeof value === "number") {
    assert.ok(Number.isSafeInteger(value), "unsafe number");
    return String(value); // Integer -0 is deliberately rendered as 0.
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  assert.equal(typeof value, "object");
  // Render keys directly. Building a sorted object then JSON.stringify-ing it
  // would reorder integer-looking keys according to JS property enumeration.
  const members = Object.keys(value)
    .sort(scalarCompare)
    .map((key) => `${string(key)}:${canonical(value[key])}`);
  return `{${members.join(",")}}`;
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

for (const vector of fixture.vectors) {
  const actual = Buffer.from(canonical(JSON.parse(vector.input_json)), "utf8");
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

console.log(`Verified ${fixture.vectors.length} canonical vectors and ${fixture.source_vectors.length} exact-source vectors in JavaScript.`);
