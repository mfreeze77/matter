# Matter v1 compatibility and validation boundary

MAT-002 implements the structural contract version `1.0` and the independent
encoding version `matter-json-v1`. MAT-003 adds the separate
[durable storage and migration boundary](../storage.md) without changing those
wire versions. MAT-004 adds the [observation intake handler](../observations.md)
and the result field described below. Schema negotiation, later business
operations, and semantic evaluator qualification retain their own tickets, including
[MAT-012](../../tickets/MAT-012.md) and [MAT-074](../../tickets/MAT-074.md).

The authoritative field inventory is [schema-inventory.md](schema-inventory.md).
The exact byte encoding and digest preimage are in [canonical.md](canonical.md).
The governing [core](core.md), [rule](rules.md), and [lifecycle](lifecycle.md)
contracts continue to define the behavior that later implementations must prove.

## Reader and writer compatibility

| Incoming value or change | v1 reader behavior | Required producer behavior |
|---|---|---|
| Supported record, command, or result with `schema_version: "1.0"` | Validate encoding and the appropriate schema | Supply every required field and the correct discriminated body |
| Missing version or wrong version type | Reject with `E_SCHEMA_INVALID` | Supply the exact version string |
| Another version, including `"1.1"` or `"2.0"` | Reject with `E_VERSION_UNSUPPORTED` | Do not silently downcast or relabel the value |
| Unknown record type or operation in version 1.0 | Reject with `E_SCHEMA_INVALID` | Introduce a reviewed contract revision before using the new kind |
| Undeclared core field | Reject with `E_SCHEMA_INVALID` | Keep specialized data in the declared extension or schema-linked payload field |
| Unknown optional metadata under a valid extension namespace | Preserve its value through decode, validation, and canonical encoding | Treat it as opaque metadata until an appropriate profile understands it |
| New required semantic feature | No automatic negotiation or execution | Use an explicit supported profile/binding, or a future compatible reader and contract version |
| Reordered object keys or different valid JSON escaping | Decode to the same value and produce the same canonical bytes | Hash normalized contract bytes with the declared digest kind |
| Reordered arrays | Preserve the new order; the digest can change | Do not sort evidence, candidates, dependencies, or other arrays implicitly |
| Unicode composed/decomposed forms | Preserve each form; their digests can differ | Do not normalize original source bytes or normalized envelopes silently |
| Floating token, unsafe integer, duplicate key, or invalid Unicode | Reject before interpreting the schema | Encode an exact decimal using a schema-declared string field |
| Non-UTC timestamp or a precision/value mismatch | Reject rather than normalize | Supply the supported UTC representation with explicit precision |
| Unknown event time | Preserve its reason and absence of a timestamp | Do not copy ingestion or publication time into the event time |
| Rule meaning changes while result JSON shape stays the same | Shape validation alone cannot detect the changed meaning | Change the rule/binding version and requalify when the rule contract requires it |

An optional extension must not redefine core fields, claim host authentication,
grant cross-scope access, or establish a conclusion. A producer needing one of
those semantics must use the corresponding explicit contract and host checks.
Accepting an extension's structure does not mean the reader understood it.

MAT-004 adds optional `body.observation_receipt` to the `committed` and
`duplicate` results of `ingest_observation`, retaining schema version `1.0`.
The updated reader accepts earlier v1 result bodies without this field, so
existing journals and structural fixtures remain valid. Earlier closed-schema
readers reject the new field until their bundled result schema is updated;
this addition does not provide automatic forward compatibility. The built-in
ingest handler always emits it to identify the observation's original creation
receipt separately from the current command's top-level `receipt`.

MAT-005 adds `update_matter_metadata` as the seventeenth operation under the
same `1.0` envelope version, with `updated` and `unchanged` success outcomes.
The updated command and result schemas continue to accept all earlier v1
fixtures. Earlier readers reject this unknown operation until their bundled
schemas are updated; there is no silent fallback to `create_matter` or
automatic operation negotiation. No stored record kind or encoding changes.
The new operation's required `metadata` object completely replaces only the
optional title, description, and namespaced extensions. Omitted fields are
removed, including when the supplied object is empty. Identity and lifecycle
fields cannot be written through this operation.

MAT-006 adds `commit_occurrence_grouping` as the eighteenth operation, with
`committed` and `unchanged` success outcomes and the shared
`occurrence_grouping_assignment` definition. It retains the twelve stored core
record kinds, the `1.0` envelope version, and the existing encoding. Its closed
command batches occurrence creation, membership replacement, and explicit root
dependence assignments. Created occurrences must supply an empty computed-group
placeholder; the runtime determines their stored provenance groups. Earlier
readers must update their bundled command and result schemas before accepting
this operation. Updated readers continue to admit all earlier v1 fixtures.
This shape extension does not implement automatic operation negotiation,
semantic association, independent-source qualification, or an assessment engine.

MAT-007 adds `revise_evidence_acceptance` as the nineteenth operation, with
`updated` and `unchanged` outcomes, while retaining twelve core record kinds
and both existing wire and encoding versions. It also adds optional named
claim components, exact relation quotation and pinned locator-validation
receipt fields, a schema-bound `relate_evidence.body.validation` declaration,
and dependency notices in claim/relation results. Updated readers continue to
accept earlier records, commands, and result fixtures without the optional
fields. Earlier closed-schema readers must update before receiving them or
the new operation; no automatic negotiation or silent operation fallback is
introduced.

The MAT-007 runtime computes the relation's immutable validation receipt from
the frozen adapter declaration and commits it with the relation. Invalid or
unavailable validation produces an explicit failure. Its declaration remains
in the failed command journal; transaction rollback means no newly inserted
validation receipt or relation was committed. Structural admission of a receipt
pin, quotation, or validation payload establishes neither citation validity,
source truth, applicable authority, nor current source availability.

Acceptance revisions change only the relation's acceptance descriptor and
preserve its cited proposition, source, and original wording. Claim corrections
append new immutable IDs through explicit predecessor pins, retaining branches
and their source history. Exact scoped ID and canonical input determine a
duplicate; common wording does not. Dependency notices describe changed model
records, not newly established external observations or independent support,
and do not execute MAT-016 assessment invalidation. See the
[field inventory](schema-inventory.md) for result-array and receipt distinctions.

MAT-008 adds `publish_association_candidates` and `decide_association`, bringing
the portable inventory to twenty-one operations and forty-two successful
operation/outcome pairs. It adds an explicit `evaluation_failed` result for
`propose_association`. The twelve core record kinds, `1.0` envelope version and
`matter-json-v1` encoding remain unchanged. The package also adds five private
schemas for candidate catalogs, evaluation/decision receipts, persistent
dispositions and membership projections; those are separately digest-bound
resources, not additional core record kinds.

Existing proposal/acceptance commands, records and success bodies gain optional
catalog, evaluation, policy, decision and capability fields. Updated structural
readers still accept earlier v1 fixtures without those fields. Earlier closed
readers must update their bundled schemas before accepting the new fields,
operations or result outcome. There is no automatic operation negotiation,
downcast, or fallback from a failed evaluation to no match.

The runtime's stronger acceptance boundary does not make old structural
fixtures executable associations. `AssociationService` requires its published
candidate-set snapshot and verified receipt/index bindings; it checks current
catalog members, the host-injected actor/authority allowlist, relationship
capability and persisted pair dispositions. The admitted authority must be an
actual host-origin receipt at the authority stage. Semantic acceptance means
explicit host review when allowed by policy, not qualification inferred from
a reported score or certificate. An explicit release additionally requires
correction permission. New proposal IDs and relationship versions do not erase
rejection/protection history, and replaying a historical success never undoes
a later revocation. Matter merges, general control epochs and transitive
invalidation remain separate work. The [association API](../associations.md)
defines the executable boundary.

## Four independent versions and identities

The schema version identifies the structure and interpretation of an envelope.
The encoding version identifies how a normalized value becomes bytes. A rule
version identifies what a question and its outputs mean. A record revision or
immutable digest identifies the exact state read by a later operation. None is
an interchangeable substitute for another.

Record references carry `scope_id`, `namespace`, `record_type`, and `id` so
identical IDs in different namespaces do not alias. A revision-pinned reference
adds exactly one bounded positive `revision` or an immutable `digest`. Immutable
core kinds require a digest pin; mutable kinds may use a revision or a digest of
an immutable snapshot. A pinned reference does not prove that the target exists,
is readable, or is current.

Mutable record kinds require revisions. Immutable record kinds reject a mutable
revision field; later correction must produce a new record and an explicit
relationship. Structural validation cannot enforce append-only storage or
monotonic updates across multiple operations. Those are runtime responsibilities.

The helper `record_digest` binds the kind `record.<record_type>.v1` and the full
validated record. `command_digest` binds `command.<operation>.v1` and the full
validated command. Both use `matter-json-v1` framing. They provide hashable
identities for later persistence work; they do not create a command journal or
establish that an operation was committed.

## Timestamp interoperability

A known time carries a UTC `Z` timestamp and a precision of `second`,
`millisecond`, `microsecond`, or `nanosecond`. These require zero, three, six,
or nine fractional digits respectively. Values are never rounded on decode.
An unknown time has `state: "unknown"` and a reason, with no invented `value`.

Version 1.0 supports Gregorian years 0001 through 9999 and seconds 00 through
59. Leap-second timestamps and offsets such as `+00:00` are rejected at this
normalized boundary. An adapter can retain them in its original source bytes
and apply a separately specified conversion before constructing an envelope.
Unknown time is different from a known instant with low precision.

The schemas carry a `matter-utc-time` format annotation and precision-specific
patterns. The Python validator enables a calendar-aware checker for that format.
Consumers in another language must implement the same check: a regular
expression alone does not reject an impossible date such as February 30.
JSON Schema's default format behavior is an annotation, so merely loading the
schema into a generic validator is insufficient for this check. See the
[Draft 2020-12 validation specification](https://json-schema.org/draft/2020-12/json-schema-validation).

The Python entry points enable only `matter-utc-time` so optional format
libraries cannot silently change validation across installations. Locator `uri`
annotations remain metadata at this boundary; exact URI/selector validation and
source availability checks belong to the adapter boundary in MAT-007.

## Success, uncertainty, and failure

An operation result has an explicit `success` or `failure` branch. A success has
an operation-specific outcome and body plus a receipt reference. A failure has
an error code, operation identity, retriable flag, affected readable references,
and safe detail. A failure cannot carry a success outcome or successful body.

For judgments, completed execution, evaluation status, semantic output, and
qualification are separate fields. A completed evaluation may remain unknown,
ambiguous, or unsupported by sufficient evidence. Failed execution cannot carry
a completed semantic answer. A structurally valid qualification reference is
not a verified certificate; the binding and certificate checks belong to the
rule engine.

`E_STORAGE_UNAVAILABLE` means durable persistence could not be established. It
does not mean no record matched. `E_SCOPE_FORBIDDEN` does not disclose whether a
restricted record exists. `E_DELIVERY_UNKNOWN` does not mean delivery succeeded
or failed. A host must keep these distinctions when mapping errors to HTTP,
exceptions, CLI exit codes, or user-facing behavior.

`error_result` uses static, safe default detail strings. The host remains
responsible for filtering affected references to the caller's readable scope
and for sanitizing any custom detail. The helper does not inspect credentials,
authorize access, retry an operation, or send a message.

## Python API and portable consumption

`matter.contracts` exports `validate_record`, `validate_command`,
`validate_result`, their strict `decode_*` JSON entry points, `schema_for`,
`record_digest`, `command_digest`, and `error_result`. Validation returns a
defensive copy without altering source values. Invalid input raises
`ContractError` with a stable `code` and safe `detail`; rejected payloads are
not inserted into the error message.

Use `decode_*` on the original JSON bytes at an untrusted boundary. A permissive
parser can discard duplicate keys or turn exponent notation into an integer
before `validate_*` ever sees the value. In-memory validation cannot recover
syntax that another parser already discarded.

The inner `error.operation_id` must equal the result envelope's `operation_id`.
The Python API checks this relationship after schema validation. Other-language
consumers must perform the same explicit comparison: standard Draft 2020-12
schemas cannot compare arbitrary sibling values for equality.

All three schemas are included in the Python distribution from the canonical
`schemas/` directory. Validation works outside a repository checkout. The
existing ticket, render, and demo CLI commands still require repository assets.
No second generated copy of the schemas is maintained in the source tree.

Other implementations should register the three bundled schemas by their
`$id` values in an offline Draft 2020-12 registry and apply the strict value
and timestamp rules before admitting records. `$id` and evidence locator URLs
are identifiers; validation does not fetch them. The Python implementation
uses the supported [jsonschema referencing registry](https://python-jsonschema.readthedocs.io/en/stable/referencing/).

Passing schema vectors and matching canonical hashes establish this structural
and encoding boundary. They do not establish durable idempotency, correct
association, authorization, fresh assessment commits, provider accuracy, or
safe external delivery. Each of those claims needs its own implementation and
acceptance evidence.
