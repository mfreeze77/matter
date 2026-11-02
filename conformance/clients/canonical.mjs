// Shared conformance codec, extracted from the original MAT-002 verifier.
import assert, { AssertionError } from "node:assert/strict";
import { createHash } from "node:crypto";

export const ENCODING_VERSION = "matter-json-v1";

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

export function canonical(value) {
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

export function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

export function canonicalDigest(value, kind) {
  if (typeof kind!=="string" || kind.length>128 || /^[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*/.exec(kind)?.[0]!==kind) {
    throw new CanonicalInputError();
  }
  return sha256(Buffer.concat([Buffer.from(ENCODING_VERSION+"\0"+kind+"\0","ascii"),Buffer.from(canonical(value),"utf8")]));
}


// Unlike JSON.parse alone, preserve duplicate-key and numeric-token checks.
export class CanonicalInputError extends Error {
  constructor() { super("invalid canonical input"); }
}

export function strictParse(source, maxDepth=Infinity) {
  try {
  const text = typeof source === "string" ? source : new TextDecoder("utf-8", {fatal:true, ignoreBOM:true}).decode(source);
  let at = 0;
  const bad = () => { throw new CanonicalInputError(); };
  const ws = () => { while (at < text.length && " \t\r\n".includes(text[at])) at++; };
  function quoted() {
    const start = at++;
    while (at < text.length) {
      const c = text[at++];
      if (c === '"') return JSON.parse(text.slice(start, at));
      if (c === "\\") at++;
    }
    return bad();
  }
  function value(depth=0) {
    ws();
    const c = text[at];
    if (c === '"') return quoted();
    if (c === "{") {
      if (depth>=maxDepth) return bad();
      at++; ws(); const result = Object.create(null); const seen = new Set();
      if (text[at] === "}") { at++; return result; }
      while (at < text.length) {
        ws(); if (text[at] !== '"') return bad();
        const key = quoted(); if (seen.has(key)) return bad(); seen.add(key);
        ws(); if (text[at++] !== ":") return bad(); result[key] = value(depth+1); ws();
        const end = text[at++]; if (end === "}") return result; if (end !== ",") return bad();
      }
      return bad();
    }
    if (c === "[") {
      if (depth>=maxDepth) return bad();
      at++; ws(); const result = [];
      if (text[at] === "]") { at++; return result; }
      while (at < text.length) {
        result.push(value(depth+1)); ws(); const end = text[at++];
        if (end === "]") return result; if (end !== ",") return bad();
      }
      return bad();
    }
    for (const [literal, decoded] of [["true",true],["false",false],["null",null]]) {
      if (text.startsWith(literal, at)) { at += literal.length; return decoded; }
    }
    const match = /^-?(?:0|[1-9][0-9]*)/.exec(text.slice(at));
    if (!match) return bad();
    at += match[0].length;
    const decoded = Number(match[0]); if (!Number.isSafeInteger(decoded)) return bad();
    return decoded;
  }
  const result = value(); ws(); if (at !== text.length) return bad();
  canonical(result); // Reject non-scalar strings, including object names.
  return result;
  } catch (error) {
    if (error instanceof CanonicalInputError) throw error;
    if (error instanceof SyntaxError || error instanceof AssertionError || error instanceof RangeError ||
        (error instanceof TypeError && ["ERR_ENCODING_INVALID_ENCODED_DATA","ERR_INVALID_ARG_TYPE"].includes(error.code))) {
      throw new CanonicalInputError();
    }
    throw error;
  }
}
