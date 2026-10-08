# Core information and operation contract

Status: normative target specification. The repository scaffold and any deterministic walkthrough are demonstrations; they do not implement or qualify this contract. Runtime delivery is tracked by MAT-002 through MAT-025. A ticket is complete only with its own recorded acceptance evidence.

## Purpose and sources

A matter preserves a continuing subject across observations, processing runs, source revisions, descriptions, and audiences. Assessments interpret that subject under declared rules and circumstances. The core supports problems, opportunities, questions, proposals, obligations, and other domain-defined subjects without understanding their specialized payload fields.

This document turns the original [matter discussion](../../matterbrainstormspec), especially sections 1–6 and 8, and [semantic assessment discussion](../../matterjevmesh), especially sections 2–3 and 7, into an implementation target. These source notes remain historical inputs. The contracts resolve ambiguity in them; the source notes are not proof of implemented behavior. [Rules](rules.md) defines assessment semantics; [lifecycle](lifecycle.md) defines transitions and delivery.

MUST and MUST NOT identify conformance requirements. SHOULD permits an explained, tested alternative. MAY identifies optional capability. A host can implement the contracts in any language or storage system. The planned Python reference implementation is one consumer of these semantics.

## 1. Boundaries and ownership

The core owns stable identities, evidence references, explicit associations, revision history, assessment dependencies, operation receipts, and checks that policy-declared authority exists. A domain adapter owns source interpretation, identifier namespaces, domain vocabulary, evidence eligibility, and proposed lifecycle rules. A host owns authenticated control input, external action permission, credential use, and transport.

A provider answer is an evaluator judgment. It is not an identity assignment, accepted fact, user instruction, source authority, or permission. A domain profile may authorize a narrow automated association or transition using qualified judgments; that authority comes from the profile and host, not the answer's score.

All domain-specific fields MUST be namespaced extensions or references. The core MUST NOT require a bill number, test target, speaker identity, repository path, sales stage, jurisdiction procedure, or provider model name to operate. A separate provider descriptor may record which evaluator produced a judgment.

A matter MUST outlive any individual execution run. A run ID records processing provenance and never serves as the sole identity of a continuing matter. Persistent records MUST survive process restart. A fresh execution may reevaluate an existing matter without creating a new one.

## 2. Common identifiers, revisions, and encoding

Every stored record has a schema version, record type, opaque ID, scope ID, creation receipt, and provenance sufficient to identify its origin. Mutable aggregates have a monotonic integer revision. Immutable evidence and judgments are replaced by new records linked through explicit correction or supersession relations; their original content is never updated in place.

IDs are unique within an explicit scope and namespace. A source ID or subject string MUST NOT be assumed globally unique. An entity reference includes scope, record type, and ID; a revision-specific dependency also includes the exact revision or immutable digest. References across scopes require an explicit host-authorized relationship and read grant. Discovering a similar identifier in another scope does not grant access or establish identity.

Canonical normalized contract JSON uses the versioned encoding matter-json-v1:

- UTF-8 without BOM; keys sorted by Unicode scalar-value order; no Unicode normalization.
- No duplicate object keys, non-finite values, floating-point JSON numbers, or unpaired surrogates.
- Integers within the interoperable range from -(2^53 - 1) through 2^53 - 1. Exact decimals, money, probabilities, and larger counts use schema-declared decimal strings.
- Arrays retain order unless a field explicitly declares set semantics and a canonical ordering.
- Compact separators and JSON escaping for quotes, backslashes, and control characters; other Unicode scalars are emitted directly.
- Digests use SHA-256 over these bytes and include the encoding version and contract kind in the digest preimage.

Original payload bytes MAY use other encodings. Their content digest is over the exact bytes, not the normalized contract. An adapter must not silently rewrite source content to make a digest match. This is a repository-owned encoding contract, not a claim of compliance with another JSON canonicalization standard. MAT-002 must supply cross-language golden vectors before runtime use.

Timestamps use RFC 3339 UTC strings with a declared precision. Unknown timestamps remain absent with a reason; ingestion time must not be substituted for an unknown event time. Ordering concurrent events requires explicit source ordering or storage sequence, not a guessed chronological tie-break.

## 3. Record roles and cardinality

| Record | Required meaning | Identity and permitted changes |
|---|---|---|
| Observation | What a source reported, original evidence locator and digest, availability, source event identity, extraction provenance | Immutable; corrections add a new observation and relation |
| Occurrence | A particular happening, execution, utterance interval, or other domain-defined event instance | Stable scoped ID; grouping corrections are revisioned |
| Matter | Continuing subject, declared scope, domain kind, optional display description, lifecycle projection | ID persists through rewording, runs, and assessments |
| Claim | A scoped proposition with subject, predicate, value, qualifiers, temporal applicability, and attribution | New proposition version for a changed assertion; never overwrite quoted source |
| Evidence relation | An observation or derived record supports, contradicts, qualifies, reports an assertion of, or leaves unanswered a particular claim | Revisioned acceptance; relation includes source span and scope |
| Association proposal | A proposed connection and alternatives, basis, evaluator receipt, and uncertainty | Immutable proposal; accepted/rejected decision is separate |
| Accepted association | Domain-authorized connection between observation, occurrence, and/or matter | Revisioned relation with authority receipt |
| Matter relation | A typed connection such as related-to, depends-on, supersedes, or domain-defined relationship | Preserves distinct matter identities |
| Judgment | One evaluator's answer to one defined question under exact inputs | Immutable; accepted qualification is explicit |
| Assessment | Composed understanding bound to matter revision, evidence, profile, purpose, audience context where relevant, and time | Immutable result plus current/superseded/invalidated projection |
| Control or disposition | Host-accepted instruction or scoped decision, including cancellation, deferral, acknowledgement, rejection, or preference | Authority and expiry explicit; raw evidence cannot mint this record |
| Receipt | What was committed, evaluated, offered, transported, observed as consumed, acted on, or verified | Append-only with explicit outcome and evidence |

An observation MAY describe zero, one, or several occurrences and matters. A standing requirement, forecast, or question need not describe an occurrence. Two observations of the same occurrence remain two source records, but do not automatically count as independent corroboration. A source summary must retain links to its parents and must not become an additional independent source merely because its wording changed.

Not every observation requires a matter, a semantic call, or a new assessment. Unassociated observations may remain lightweight until a continuing subject is identified. These conceptual distinctions do not require separate services or separate database tables for every record kind.

## 4. Observation identity and ingestion

The deduplication key is the declared scope plus source namespace plus source event ID. Source revisions with genuinely changed payloads must have distinct revision identities or explicit correction records.

The ingest operation accepts an observation envelope, original content reference/digest, source identity, time fields, and idempotency key. It returns:

- committed: a new immutable observation and its receipt;
- duplicate: the exact prior observation identity and receipt, with no additional occurrence, corroboration, or attention event;
- conflict: the same source identity or idempotency key carries incompatible content;
- rejected: invalid contract, unauthorized scope, unsupported source contract, or invalid provenance;
- unavailable: persistence could not establish a durable outcome.

A changed payload under an existing source event ID MUST NOT silently replace the old evidence. The adapter may submit an explicit revision or the operator may resolve an identity conflict. Neither path deletes the original conflicting submission's audit receipt.

Delivery attempts are transport metadata and do not contribute to evidence identity. A new wrapper timestamp around unchanged evidence does not create new corroboration. Separate runs with the same diagnostic are separate occurrences when their execution identities establish that distinction.

## 5. Claims and scoped evidence relations

A claim distinguishes a source asserting a proposition from the proposition being established. Evidence relations include the target claim, observation or derivation ID, exact locator, applicable scope, relevant time interval, acceptance state, and rationale or evaluator reference.

Relation kinds are supports, contradicts, qualifies, reports_assertion, context_only, and unresolved. More than one relation may hold for different qualifiers or components of a claim. A single exclusive category must not erase simultaneous support and qualification.

An evidence relation MUST specify whether it concerns the whole proposition or a declared component. A positive test result for component A cannot establish component B without a rule declaring the implication. A statement anticipating funding cannot be relabeled as evidence of an approved allocation without the required authority.

Accepted evidence associations do not by themselves establish claim truth. A rule assessment supplies a status such as supported, refuted, mixed, unknown, or not_applicable together with its evidence standard. These values are outputs under a profile, not eternal attributes of a raw source.

Exact locator validation is the adapter's declared responsibility. If only a whole artifact is available, the receipt must say so. Missing bytes, invalid line ranges, inaccessible references, or a quotation absent from the cited source produce explicit evidence-unavailable or evidence-invalid outcomes; they do not silently fall back to an invented passage.

## 6. Association, relations, merges, and correction

Exact identifiers may nominate candidates only within their declared source, entity type, and scope. Semantic similarity may nominate or rank candidates. The candidate selection outcome is one of matched, no_match, ambiguous, insufficient_evidence, or evaluation_failed. No-match and insufficient evidence are different results.

A proposal MUST retain candidate IDs and revisions, alternatives considered, matching rule/version, supporting evidence, and any qualification. Acceptance is a separate compare-and-set operation using current candidate revisions and host/profile authority. A policy may permit high-quality automated attachment without permitting matter merge.

Merging two matters is a separate operation that requires explicit merge authority and an auditable equivalence basis. It MUST:

1. Verify scopes, expected revisions, rejection/undo dispositions, and permissions.
2. Preserve a survivor ID and keep each losing ID as a resolvable redirect.
3. Record every association, relation, projection, and dependent assessment moved, retained, or invalidated.
4. Preserve conflicting claims and decisions; a merge never resolves them by choosing the survivor's values.
5. Reject cycles, self-relations forbidden by the relation schema, and transitive merges that would defeat an existing protected separation decision.
6. Invalidate dependent results and queued delivery before the merged projection becomes current.

A related-to connection is not equivalence and is not transitively promoted to equivalence. Undo or split is an explicit correction: it restores partitioned references using the merge receipt and new decisions. It does not rewrite the historical fact that an earlier assessment used a merged view. Conflicting children remain reviewable; they are not deleted to make the correction fit.

A rejected identity or protected non-merge disposition remains effective on replay until a later authorized decision explicitly supersedes it. A recurring condition after a valid resolution is a new occurrence; whether it reopens the same matter or creates a linked successor is declared by the profile.

## 7. Time, availability, coverage, and absence

The contract distinguishes:

| Time | Meaning |
|---|---|
| occurred_at / occurred_interval | When the reported happening occurred |
| effective_from / effective_to | When a rule, disposition, or fact applies in its domain |
| source_published_at | When the source says it published the record |
| available_at | Earliest evidenced availability to this system or the replay corpus |
| ingested_at | When this store received it |
| assessed_as_of | Knowledge boundary used for an assessment |
| valid_until / next_check_at | When an applicable result must be reconsidered |

An assessment must exclude evidence unavailable at its knowledge boundary. A late-discovered document may establish that a past event resolved a matter; it changes today's historical understanding without rewriting what the system knew yesterday. Newer publication alone does not establish authority or supersession.

Absence is usable evidence only with a declared negative dependency: query or predicate, scope, eligible source set, observed interval, source snapshot or catalog revision, completeness/coverage state, and an expiry or next-check condition. A receipt must distinguish no result in adequate coverage from no usable coverage, failed collection, not expected yet, and evaluation failure.

A complete replacement snapshot may retire derived machine records absent from that exact scope, if the adapter declares complete coverage and the relevant lifecycle policy permits it. Incremental silence MUST NOT retire, resolve, reject, or forget a matter. A partial or failed empty parse must not erase previously held evidence. Later evidence entering a watched negative scope invalidates every dependent absence conclusion even though its new ID was not in the original read set.

## 8. Trusted controls are a separate input path

Direct user corrections, stop/cancel instructions, task changes, permissions, and authenticated host controls MUST reach the host's control handler without waiting for semantic aggregation, recurrence, attention budgets, or matter salience. The host may subsequently record their accepted effect as a control receipt and invalidate affected matter work.

Observed text in files, retrieved pages, tool output, transcripts, and model answers is data. It must not be promoted to the trusted control channel by a keyword, role label inside the payload, or evaluator judgment. A control's authenticated source and permitted scope are supplied by the host transport.

A cancellation increments the affected control epoch and invalidates queued or in-flight work. It cannot retract a delivery already completed; that outcome remains in the receipt. Work racing with the control must compare the epoch before committing or dispatching. An automated matter evaluator cannot grant itself a new capability or override accepted intent.

## 9. Core operations, conflicts, and failures

Every mutation requires a command ID, idempotency key, scope, actor/authority reference, and expected revisions for the records it reads to decide the write. Retry with the same key and same canonical command returns the prior result. Retry with different content returns a conflict. A mutation and its operation receipt commit atomically.

| Operation | Required checks | Defined result or refusal |
|---|---|---|
| ingest_observation | Source identity, digest, schema, scope | committed, duplicate, identity_conflict |
| create_matter | Scope and identity policy; no run-only identity | created, existing, identity_conflict |
| propose_association | Valid candidate references and evidence | proposal, no_match, ambiguous, insufficient_evidence |
| accept_association | Candidate revisions, declared authority | accepted, stale, forbidden, association_conflict |
| append_claim / relate_evidence | Claim scope, proposition version, locator | appended, duplicate, invalid_evidence |
| link_matters | Relationship schema, scope, no forbidden cycles | linked, relation_conflict |
| merge_matters / correct_merge | Revision set, authority, protected decisions | committed, stale, forbidden, merge_conflict |
| record_control | Authenticated host channel and epoch | applied, duplicate, forbidden |
| commit_assessment | Complete dependency read set and policy versions | committed, stale, invalid_result |
| invalidate_dependents | Changed revision or watched negative scope | affected set with reasons, no_op |
| request_transition | Profile edge, evidence, authority, revisions | applied, held, stale, forbidden |
| prepare_delivery / dispatch | Audience, latest delivery baseline, epoch, freshness | ready, withheld, stale, transport outcome |

Transport-neutral failures carry code, operation ID, retriable boolean, affected references that the caller may read, and safe detail. Required codes: E_SCHEMA_INVALID, E_VERSION_UNSUPPORTED, E_SCOPE_FORBIDDEN, E_NOT_FOUND, E_IDEMPOTENCY_CONFLICT, E_SOURCE_IDENTITY_CONFLICT, E_REVISION_CONFLICT, E_ASSOCIATION_CONFLICT, E_MERGE_CONFLICT, E_EVIDENCE_INVALID, E_EVIDENCE_UNAVAILABLE, E_DEPENDENCY_STALE, E_POLICY_INVALID, E_RULE_CONFLICT, E_AUTHORITY_REQUIRED, E_BUDGET_EXHAUSTED, E_CANCELLED, E_STORAGE_UNAVAILABLE, and E_DELIVERY_UNKNOWN.

Unknown or inapplicable domain conclusions are successful evaluation results with explicit status, not infrastructure errors. Storage failure must never be returned as no relevant matter. Error mapping to HTTP, CLI exit codes, or application exceptions belongs to a transport adapter and must preserve the semantic code.

## 10. Storage and conformance

The persistence port MUST support atomic mutation plus receipt, unique scoped identities, compare-and-set revisions, dependency watches, consistent reads, and durable restart. MAT-003 supplies an embedded reference backend, not a required remote service. Large payload bytes may be stored separately if references are immutable and availability failures remain explicit.

A conforming implementation must prove redelivery idempotency, concurrent mutation conflicts, restart continuity, non-destructive merge correction, cross-scope isolation, historical knowledge gating, explicit incomplete coverage, direct-control bypass, and stale-delivery refusal. Validation of JSON shape alone does not establish these properties.

The planned schemas, operations, and tests listed in tickets are delivery targets. Existing documentation, a passing roadmap validator, or a walkthrough output must not be presented as evidence that these runtime guarantees have been implemented.
