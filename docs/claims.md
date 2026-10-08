# Scoped claims and cited evidence

MAT-007 implements immutable source assertions, their explicit correction
histories, and revisioned evidence acceptance through the existing storage
port. Its runtime lives in `matter.claims`, `matter.evidence_relations`, and
`matter.citations`. The [core contract](contracts/core.md) remains governing.
The [acceptance receipt](validation/MAT-007.md) records executed verification.

A claim says what a source asserts about a declared subject. A relation says
which exact claim or named component a cited artifact supports, contradicts,
qualifies, reports, contextualizes, or leaves unresolved. Neither operation
changes a matter's lifecycle, assigns semantic identity, establishes an outcome,
or resolves conflicting evidence.

## Run the installed example

Install the package, then run this synthetic example from the checkout:

```bash
python examples/claim_evidence.py
```

The example ingests exact source bytes, creates a continuing matter and a
conditional funding forecast, and records support and qualification from the
same passage. It distinguishes a selected passage from a deliberate whole
artifact, refuses a quotation found on another line, revisions one acceptance,
appends a claim correction, and verifies that the source stays unchanged while
matter and citation history survive retry and database backup/restore. It calls
no evaluator or external source service.

## Immutable assertions

Construct `ClaimService(storage)` in the host's authorized scope. The existing
`append_claim` command body contains `claim`, a core claim input. Its body retains:

| Field | Runtime meaning |
|---|---|
| `subject` | An exact scoped entity reference or schema-bound domain value |
| `predicate` | Adapter-owned namespaced proposition kind |
| `value` | The asserted value, with its domain schema |
| `qualifiers` | Ordered domain values that preserve stated limitations |
| `applicability` | Explicit known or unknown temporal boundaries |
| `attribution` | Exact pinned references to the declared attribution records |
| `proposition_version` | Source/adapter version text; not a sortable truth rank |
| `components` | Optional nonempty map of namespaced component names to domain values |

The host submits complete source wording and structured meaning in these
declared fields; the service does not extract propositions or normalize them.
Original observations and payload bytes remain immutable. A relation can
retain an exact quotation separately from a claim's structured representation.

Prepare a command once, save that exact command, and execute it:

```python
from matter.claims import ClaimService

claims = ClaimService(storage)
prepared = claims.prepare(command)
result = claims.append(prepared)
assert claims.append(prepared) == result
```

Preparation captures a consistent snapshot of dependencies while preserving
caller-supplied pins. Existing attribution and provenance references must be
readable in the same scope. A bare entity subject is read and its current
snapshot becomes a command precondition. Arbitrary data inside a domain value
does not implicitly become another storage reference or permission.

Each new claim and its subject/correction lookup projection commit atomically
with the operation receipt and result. An already occupied claim ID returns
`duplicate` only for the same canonical input, including provenance, qualifiers,
array order and any namespaced extensions. It keeps the original claim pin and
creation receipt and emits no new dependency notice. Changed input under that
ID yields `E_SOURCE_IDENTITY_CONFLICT`. Distinct IDs remain distinct assertions
even when their text matches.

### Corrections preserve branches

A correction uses a new claim ID, a different `proposition_version`, and a
nonempty `supersedes` array of exact earlier claim pins. Each predecessor must
have the same declared subject and predicate. A correction may change the
asserted value, qualifiers, applicability, component declarations, or attribution.
It never overwrites the old claim or moves an old citation to the new claim.

Multiple corrections can explicitly supersede the same predecessor. Both
branches remain. A later claim may name both branch tips as its predecessors
without selecting one as true. A retraction is represented by the host's new
assertion or acceptance decision; it does not generate the logical opposite of
the original claim.

| Query | Returned records |
|---|---|
| `claims.for_subject(subject, predicate=None)` | All claims with that exact declared subject, optionally filtered by predicate |
| `claims.revisions(claim_ref)` | The connected correction graph, in deterministic parent-before-child order |
| `claims.heads(claim_ref)` | Every unsuperseded branch tip in that graph |

These return detached full records. The history query follows explicit
predecessor links and verified descendant watches in one snapshot, with a
4,096-claim traversal budget. Branch ordering is deterministic and carries no
authority or chronological interpretation. An unrelated claim using the same
subject and predicate is not silently joined to this correction history.

## Scope each evidence relation

Configure an explicit adapter and construct the relation service:

```python
from matter.citations import Utf8LineLocatorAdapter, line_selector
from matter.evidence_relations import EvidenceRelationService

adapter = Utf8LineLocatorAdapter(payloads)
relations = EvidenceRelationService(storage, locator_adapter=adapter)
prepared = relations.prepare(relation_command)
result = relations.relate(prepared)
```

The existing `relate_evidence` command body contains a core relation input and,
after preparation, a frozen `validation` domain value. The input specifies an
exact claim pin, exact evidence pin, one of the six core relation kinds, its
applicability, locator, optional exact quotation, and acceptance rationale.
`target` is either `{"kind": "whole"}` or a component target such as
`{"kind": "component", "component": "example:timing"}`. Component names must
exist on the exact pinned claim's `components` map.

One source passage may support `example:funding` and qualify `example:timing` in
two separate relation records. Support for one component creates no support
for another component or another claim. The service does not deduplicate
different relation IDs by source text or collapse the six relation kinds into
one exclusive label.

### Exact original-byte validation

The included adapter supports observation records whose retained payload has
a whole-artifact source locator. It reads through the existing `PayloadStore`;
it never follows the declared URI or calls an external service. The requested
URI must exactly match the observation's declared URI.

| Citation | Required input and validation |
|---|---|
| Selected passage | `selected_span`, a selector from `line_selector(start, end)`, and a nonempty quotation found exactly within those selected lines |
| Whole artifact | Explicit `whole_artifact` with no quotation; exact content digest and optional byte length must match |
| Unavailable locator | Explicit failure; no guessed span or whole-artifact fallback |

Line numbers are one-based and inclusive. LF delimits physical lines; CRLF,
BOM characters, Unicode normalization, whitespace and punctuation remain
unchanged. A trailing LF does not create an additional empty line, and an empty
artifact contains no selectable line. The selected-byte digest includes the
original line terminators. Passage citations require strict UTF-8; whole-artifact
citations can validate binary payloads without inventing text coordinates.

Missing or withheld bytes produce `E_EVIDENCE_UNAVAILABLE`. Reversed or
out-of-bounds line ranges, wrong URIs, digest/length mismatch, or a quotation
absent from the selected lines produce `E_EVIDENCE_INVALID`. Unsupported text
encoding, source-relative coordinates, or evidence kinds require another
explicitly configured adapter and remain unavailable to the default adapter.

`judgment`, `assessment`, and `claim` remain legal evidence record kinds in the
portable contract. The included adapter does not guess which nested field is
their source artifact. A custom adapter must explicitly declare its content,
coordinates and exact dependencies through the same validation contract.

### Frozen declarations and receipts

The adapter runs outside write transactions. Its schema-bound declaration
contains the scope, exact evidence pin, source content manifest, requested
locator and quotation, versioned adapter descriptor, sorted unique dependency
pins, validation time, and either a valid citation kind plus selected-byte
digest or an explicit failure reason. Preparation reads every returned
dependency; execution checks the saved dependency pins again.

A successful command atomically inserts an immutable evaluation receipt,
the evidence relation, its query projection, and the normal operation receipt.
The relation's `locator_validation` and the result's `body.locator_validation`
pin that immutable validation receipt. The result's top-level `receipt` names
the current operation receipt. Callers cannot supply computed validation links.

A failed validation is recorded in the failed command journal, including its
frozen declaration and reason. No relation, validation child receipt, or query
projection commits on that failure. Read errors during preparation may be
raised before a command is journaled; submit an executable prepared command
to receive the storage port's durable semantic outcome.

The receipt records availability at validation time. It does not promise that
bytes remain accessible. Reading existing relations, revising acceptance, or
retrying the exact saved command does not re-fetch source bytes. A new relation
ID requires its own validation. A new command carrying the same original
relation input may return `duplicate` after acceptance has changed; it returns
the current relation pin and retains the original validation receipt.

The adapter descriptor and declaration are provenance, not signatures. The
trusted host must admit declarations from its configured adapter and authorize
operations. A string that names a receipt or adapter does not authenticate its
sender or grant business authority. Stored receipt reads retain compatibility
with the adapter version that originally performed validation.

## Acceptance revisions and lookup

`revise_evidence_acceptance` takes an exact relation revision and a complete
replacement acceptance object. A non-proposed status requires an authority
reference equal to the command's authority. An optional evaluator receipt must
resolve in the same scope. The host is responsible for actual authorization.

Only acceptance changes. The scoped identity, claim, evidence, relation kind,
target, locator, quotation, applicability, original provenance and citation
receipt remain fixed. Retire a contribution by revising acceptance to
`rejected` or `superseded`; retargeting or changing the cited proposition requires
a new relation ID. This service refuses creation-time relation `supersedes`
rather than guessing an evidence replacement policy.

A changed acceptance appends the next relation and projection revisions
atomically. Identical acceptance returns `unchanged` without revision growth.
Stale acceptance edits fail with `E_REVISION_CONFLICT`; they are not refreshed
automatically. Exact command replay returns the saved result even after a later
edit has changed the current relation.

Stored acceptance and history use the bound immutable validation receipt without
requiring its historical mutable dependencies or provenance parents to remain
current. New relation creation still checks every declared dependency. A later
source-context change therefore cannot prevent the host from retiring an old
contribution.

`relations.for_claim(claim_pin, target=None, status=None)` returns full current
relations for that exact claim snapshot. The default includes proposed,
accepted, rejected and superseded contributions. `relations.history(ref)`
returns every acceptance revision. Contradictory sources and retired
contributions remain inspectable.

## Dependency notices and persistence limits

Successful runtime results contain `changes`, a list of closed records with
`cause`, `before` pins and `after` pins. New claims or evidence relations emit
`new_evidence`; explicit claim corrections emit `evidence_correction` with all
named predecessors; acceptance revisions emit `disposition_change`. Duplicate
and unchanged results contain an empty list. A `before` pin identifies an
affected dependency; it does not mean that record was deleted.

These notices are journaled model changes. A new claim or citation is not an
additional external observation or independent corroborating source. MAT-016
will own transitive assessment invalidation and queued-delivery cancellation;
MAT-007 does not execute either mechanism.

No new database migration or external client is needed. Existing transaction,
read-guard, projection-watch, receipt, restart and SQLite backup/restore APIs
preserve the new records. Payload blobs remain separately backed up under the
[observation storage contract](observations.md). A database restore alone cannot
restore missing source bytes, while its historical validation receipts remain
available.
