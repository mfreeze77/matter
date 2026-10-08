# Canonical JSON and content digests

This document specifies the executable `matter-json-v1` encoding introduced by
[MAT-002](../../tickets/MAT-002.md). It supplements
[core contract section 2](core.md#2-common-identifiers-revisions-and-encoding).
The reference implementation is [matter.canonical](../../src/matter/canonical.py).
Record shape, supported schema versions, permissions, and lifecycle semantics are
separate checks. A canonical byte sequence alone does not establish any of them.

## Accepted values and input

A value is an object, ordered array, string, interoperable integer, boolean, or
null. Integers range inclusively from `-9007199254740991` to
`9007199254740991`. Exact decimals, money, probabilities, and larger counts must
use a representation explicitly declared by the field's schema, such as a
decimal string. The encoder does not infer or convert these representations.

The decoder accepts one JSON value surrounded by optional JSON whitespace. It
rejects duplicate object names after escape decoding, non-finite constants, all
fraction/exponent number tokens, unsafe integers, malformed JSON, and trailing
data. For example, `1.0`, `1e0`, and `-0.0` are invalid even when a host could
convert them to an integer. The integer token `-0` is accepted and canonicalizes
to `0`: there is no distinct negative integer zero in this contract.

Byte input must be strict UTF-8 without a leading byte order mark. UTF-16 and
UTF-32 are refused, with or without a BOM. Text input must contain Unicode scalar
values. Raw surrogate code points are invalid; JSON escapes forming a valid
UTF-16 surrogate pair decode to the corresponding supplementary scalar. A lone
escaped surrogate is invalid. U+FEFF inside a JSON string is ordinary string
content and is preserved.

RFC 8259 discusses duplicate-name interoperability, exact integer range, UTF-8,
and surrogate hazards. Matter intentionally adopts stricter input rules than
general JSON and does not claim conformance to any other canonicalization
standard. See [RFC 8259, sections 4, 6, and 8](https://www.rfc-editor.org/rfc/rfc8259).

## Exact output bytes

The canonical output has these rules at every nesting level:

1. Encode as UTF-8 without a BOM, added whitespace, or a trailing newline.
2. Sort object names lexicographically by their sequences of Unicode scalar
   values. A proper prefix sorts before its extension. Do not sort by locale,
   rendered appearance, UTF-16 code units, or numeric interpretation of keys.
3. Preserve array order and duplicate array elements. A schema that declares set
   semantics must define and apply its ordering before encoding; the generic
   encoder never guesses that an array is a set.
4. Preserve strings exactly, without Unicode normalization or case folding.
5. Emit integers as ordinary base-10 digits, with a leading minus only for
   negative values. Do not add a plus sign, exponent, fractional part, or leading
   zero. Emit `true`, `false`, and `null` exactly as shown.
6. Use `,` between items and `:` between each object name and value.
7. Quote strings with ASCII double quotes. Use `\"` for a double quote and `\\`
   for a backslash. Use the two-character escapes `\b`, `\t`, `\n`, `\f`, and
   `\r` for U+0008, U+0009, U+000A, U+000C, and U+000D. Other U+0000–U+001F
   controls use lowercase six-character escapes `\u00xx`. Emit every other
   Unicode scalar directly, including `/`, U+007F, U+2028, and U+2029.

For the object with keys U+E000 and U+10000, U+E000 comes first. A default
JavaScript UTF-16 string comparison produces the opposite ordering. Likewise,
the key `"10"` sorts before `"2"`; the verifier renders members directly so
JavaScript's numeric property enumeration cannot reorder them afterwards.

Composed `é` and decomposed `e` followed by U+0301 remain distinct string values,
object names, canonical bytes, and digests. An escaped `"\u00e9"` and a literal
`"é"` represent the same value and have the same canonical bytes, while their
original source bytes have different digests.

## Digest framing

Contract digests are the lowercase, 64-character hexadecimal SHA-256 of this
exact preimage, with `||` denoting byte concatenation:

```text
ASCII("matter-json-v1") || 0x00 || ASCII(kind) || 0x00 || canonical_utf8
```

`kind` is 1 through 128 ASCII characters and must match the entire expression:

```text
[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*
```

Examples are `matter`, `observation`, `evidence_relation`, `operation-result`,
and `example.record_v1`. Names are case-sensitive and have no aliases or implicit
prefixes. The validated `record_digest` helper uses
`record.<record_type>.v1`; `command_digest` uses `command.<operation>.v1`.
These wrapper conventions bind the record or operation family as well as its
version. Low-level encoding examples below use a shorter illustrative kind.
An otherwise legal name need not name a supported schema: the encoding utility
does not maintain that registry.

Both the version and kind exclude NUL, so the two separators unambiguously bind
the framing. No newline, digest prefix, JSON quoting around the kind, or trailing
separator is added. The version binds the encoding rules, while the value's
`schema_version` remains part of the canonical JSON when the schema requires it.

For kind `observation` and value `{"a":1}`, the bytes before hashing are:

```text
6d61747465722d6a736f6e2d7631006f62736572766174696f6e007b2261223a317d
```

Original-source digests use `SHA256(original_bytes)` with **no framing or
normalization**. They accept arbitrary bytes, including binary data, UTF-16, BOMs,
or malformed JSON. A source digest and a contract digest identify different
things and must not be substituted for one another. Source digest calculation
does not claim that the source parses, is accessible later, or has authority.

## Python API and boundary use

```python
from matter.canonical import canonical_bytes, canonical_digest, loads, source_digest

original = b'{ "a": 1 }\n'
value = loads(original)                 # Strict parsing, before schema interpretation.
normalized = canonical_bytes(value)    # b'{"a":1}'
contract_hash = canonical_digest(value, "observation")
original_hash = source_digest(original)
```

`canonical_bytes` accepts exact built-in `dict`, `list`, `str`, `int`, `bool`, and
`None` values. Object keys must be exact `str` values. Floats, tuples, sets,
bytes, arbitrary objects, and custom subclasses are refused. There are no
custom serialization hooks. The API preserves the caller's values and ordering
without modifying them. Reference cycles are rejected; a non-cyclic subtree
reused in two places is encoded twice.

`loads` accepts exact `str` or `bytes`; `source_digest` accepts exact `bytes`.
`CanonicalError` derives from `ValueError` and uses fixed messages without source
values, key names, or custom object representations. Applications should map it
to their transport-neutral contract error without adding sensitive input data.

Use `loads` on the original input before another decoder can discard information.
An already-created dictionary cannot reveal whether its source had repeated
keys; an integer produced by a permissive decoder cannot reveal an earlier
`1e0` spelling. Python's default JSON decoder permits repeated names and
non-finite constants, and supports UTF-16/32 byte input, so the reference API
uses explicit decoding and parser hooks. See the
[Python JSON API](https://docs.python.org/3.11/library/json.html#json.loads) and
[interoperability notes](https://docs.python.org/3.11/library/json.html#standard-compliance-and-interoperability).

The scaffold's `matter.jsonio` serves repository tooling and retains its existing
finite-float behavior. It is not the `matter-json-v1` contract boundary.

This small reference implementation is in-memory. Python's nesting and memory
capacity limit input size. Recursion exhaustion becomes a safe `CanonicalError`;
there is no claim of unbounded nesting, a streaming parser, or production resource
isolation. A host must bound request size before parsing untrusted input. Those
operational limits do not silently truncate or alter canonical content.

## Portable fixtures and verification

[golden.json](../../tests/fixtures/canonical/golden.json) contains **26 positive
contract vectors** and **8 original-source vectors**. Each contract vector has
an input JSON string, readable expected canonical JSON, exact UTF-8 hex, framed
SHA-256, kind, and original-input SHA-256. Expected canonical texts were manually
declared from these rules. Their UTF-8 encodings and SHA-256 values were calculated
from those declared texts using standard byte encoding and hashing, without
importing or invoking the Matter implementation. The committed expectations are
static and are not regenerated by the tests.

[invalid.json](../../tests/fixtures/canonical/invalid.json) contains **53 rejection
vectors**, expressed as input JSON text or exact input-byte hex. Python tests also
construct invalid in-memory types, raw surrogate pairs, cycles, and deeply nested
values directly. A raw Python surrogate pair cannot be faithfully represented as
adjacent surrogate escapes inside a JSON fixture string: decoding the fixture
would produce a valid supplementary scalar.

Run the checks from the repository checkout after installing the package:

```bash
python -m unittest discover -s tests/contract -p test_canonical.py -v
node tests/fixtures/canonical/verify.mjs
```

The independent JavaScript verifier implements scalar sorting, canonical rendering,
and digest framing without importing the Python code. It checks all positive byte
and digest vectors. Its `JSON.parse` input path is deliberately used only on the
declared valid fixtures: it is **not** a strict second-language decoder, because
that parser discards duplicate names and numeric token spellings. This is portable
encoding evidence, not completion of MAT-074's broader cross-language runtime
conformance work.
