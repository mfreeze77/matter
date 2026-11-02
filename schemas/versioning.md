# MAT-074 compatibility and migration policy

The opt-in `compatibility-envelope/1.0` boundary adds explicit requirements
around an existing payload. It does not replace or modify frozen monitoring
1.0/1.1, assistant-review 1.0, native commands/results or access contexts.
Its [schema](compatibility-envelope.schema.json) specifies shape; strict
[matter-json-v1](../docs/contracts/canonical.md) parsing and the 2 MiB raw and
canonical byte limits apply before consuming the value. The portable maximum
is 128 nested containers, counting the root object as one; excessive depth
yields `E_SCHEMA_INVALID` in both readers.

## Structural versus semantic compatibility

`matter.versioning.make_envelope` declares `required_features` (at most 64
explicit feature identifiers) and `required_semantics` (at most 64 exact
fingerprints), plus `payload` and an opaque `extensions` map. Unknown optional
extensions round-trip unchanged. Required features are never inferred from a
model answer, output shape or an extension name. The host must declare the
actual requirements and validate the native payload with its existing reader.

`read_envelope(source, supported_features=..., known_semantics=...,
expected_semantics=...)` rejects unsupported versions/encoding, unknown required
features or semantics with `E_VERSION_UNSUPPORTED`. Malformed input yields
`E_SCHEMA_INVALID`; input bounds yield `E_BUDGET_EXHAUSTED`. Explicit consumer
`expected_semantics` requires the exact declared set, detecting removed or
substituted context declarations. Omitting that parameter permits inspection of
known historical semantics; it is not current evaluation admission.

`semantic_fingerprint(component_ref)` binds the full exact namespace, ID,
version and content digest. Changing a rule's meaning while leaving its output
shape unchanged does not match its old fingerprint. The envelope is a declaration,
not proof that its payload actually used those components. Native policy/profile,
assessment, access, availability, control and qualification guards still apply.
No accepted envelope grants permission, source authority or a certificate.

Exact decimals remain declared strings; fractional/exponent JSON numbers are
refused, and integer `-0` canonicalizes to `0`. Generic payload strings are
preserved, including timestamp-offset spellings; two spellings of an instant
need not have equal hashes. Native known-time fields still require their existing
UTC/precision contract. No timestamp rounding or implicit offset conversion occurs.

## Existing storage migrations and rollback

`migration_manifest()` describes the installed SQLite registry: backend identity,
application ID, target schema, canonical encoding and every packaged SQL
resource's SHA-256 and from/to version. `require_migration_manifest` compares
that whole declaration to the installed registry. Foreign/altered manifests
are refused; caller-supplied SQL is never executed. This exposes the existing
checksummed transactional engine, not a replacement migration or storage system.

The current physical schema remains version 1; this SDK introduces no SQL
upgrade. The migration fixture exercises a declared future version 2 through
the existing registry seam. Interrupted upgrades roll back atomically. A committed
upgrade is **one-way**: a reader that does not support the new version refuses.
Rollback means restoring a verified pre-upgrade backup to a new destination
only when no writes have occurred since that backup. Hosts must quiesce writers
and account for original external attempts; restoring a file cannot prove those
workers stopped. Rollback does not merge later writes or edit ledger rows.
The original upgraded database is preserved. The fixture proves exact application
rows, source correction, unresolved proposal, command history and unknown-delivery
receipt survival and uses the existing backup/restore port.

SQL format and data semantics are separate. In particular, dev20-written state
still cannot be downgraded to dev19 even though both use SQL schema 1. This optional
envelope does not retrofit old executables or add an automatic per-database
semantic-feature floor. Hosts must enforce their pinned SDK/data compatibility
before opening a store and never treat a physical schema match as sufficient.

## Python and independent JavaScript client

[Shared compatibility cases](../tests/fixtures/versioning/compatibility.json)
exercise accepted bytes/digests and explicit refusal outcomes. The
[JavaScript client](../conformance/clients/javascript.mjs) uses the existing
portable encoder extracted into a shared conformance codec, with a strict
parser that retains duplicate-key and numeric-token checks. It uses only Node
built-ins. Both clients round-trip an actual SQLite create result with exact
retry identity, references, extensions and observable outcome preserved.

This is a compatibility reader/conformance client, not a second native Matter
runtime, host integration, provider evaluation or qualification. Node is required
for the second-language checks; its absence is a skip, not a language-conformance
pass. Run from the checkout:

```sh
node tests/fixtures/canonical/verify.mjs
PYTHONPATH=tests python -m unittest contract.test_versioning integration.test_version_migration -v
```
