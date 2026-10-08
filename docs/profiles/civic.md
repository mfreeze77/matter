# Civic profile and crawler boundary

Status: governing design and planned work. This file defines the civic profile for Matter; it does not implement a crawler change, receiving migration, legal determination, or deployment. Tickets MAT-046 through MAT-050 carry the work.

## Purpose and ownership

Matter follows continuing subjects, links observed evidence to claims, records assessments under a versioned purpose, and decides whether an audience has a meaningful update. The civic profile supplies civic identifiers, source stages, body relationships, authority references, and lifecycle predicates. The neutral core does not know Kansas law, parliamentary rules, procurement stages, or which board can approve a particular act.

The local crawler owns jurisdiction-specific definitions, extraction conventions, body aliases, source acquisition and proposed authority tiers/overrides. A receiving application's reviewed authority record remains the authority for consequential state. A crawler parser's label such as `action: final` is evidence about how a source was parsed; it is not proof of a body's legal power. Matter preserves both the raw label and its interpretation status.

This follows the user clarification of 2026-10-08: build the general substrate while keeping jurisdiction knowledge in the local crawler and meeting-learning experiments in DIAT. It also preserves the existing crawler's explicit receiver/operator boundary in [T-087](https://github.com/mfreeze77/statecivics-local-crawler/blob/f2fd7d39f97fb4f3510e3edef9c0c852e0b5f36f/tickets/T-087-source-backed-motion-intent-and-vote-mechanics.md).

| Owner | Owns | Supplies or consumes |
| --- | --- | --- |
| `mfreeze77/matter` | Neutral profile contracts, evidence/claim/assessment mechanics, replay and attention rules | Validates a pinned civic profile and exported evidence; offers advisory assessments |
| `mfreeze77/statecivics-local-crawler` | Jurisdiction definitions, source parsing, body/source-stage conventions, profile evidence and exports | Produces immutable, source-linked profile and observation packages |
| Receiving civic application/operator | Reviewed body capacities, identity resolutions, accepted legal state and operational actions | Provides an explicit authority attestation; evaluates any consequential proposal |
| `mfreeze77/statecivicsai-diat` | Private meeting procedure, speaker and behavioral research | May export experimental procedural claims with no legal or identity authority |

A shared schema does not authorize writes between these repositories. Every downstream ticket here is planned work requiring its own repository implementation and review. This change creates specifications and backlog in Matter only.

## Source audit and knowledge boundary

Read-only audit pins:

- Crawler: `f2fd7d39f97fb4f3510e3edef9c0c852e0b5f36f`.
- DIAT: `da33bb1171bb537954f59b234c86cfa32cb2641c`.
- Original design inputs: [matterbrainstormspec](../../matterbrainstormspec), [matterjevmesh](../../matterjevmesh), and [jevinmatter](../../jevinmatter).

Existing source patterns worth reusing:

1. The crawler's [Wyandotte definition](https://github.com/mfreeze77/statecivics-local-crawler/blob/f2fd7d39f97fb4f3510e3edef9c0c852e0b5f36f/src/civic_crawler/jurisdictions/ks/ks_county_wyandotte/definition.json) retains body names, aliases, parent relationships, type basis and source information. A parent relationship is not automatically legal authority.
2. Its [minutes profile](https://github.com/mfreeze77/statecivics-local-crawler/blob/f2fd7d39f97fb4f3510e3edef9c0c852e0b5f36f/src/civic_crawler/jurisdictions/ks/ks_county_wyandotte/minutes.json) contains body-specific parsing patterns and recommendation/final action tags. They are local parsing conventions, not a universal procedural constitution.
3. [T-090](https://github.com/mfreeze77/statecivics-local-crawler/blob/f2fd7d39f97fb4f3510e3edef9c0c852e0b5f36f/tickets/T-090-matter-identity-case-parties-and-lifecycle-exports.md) distinguishes continuing cases/instruments, agenda appearances, source claims and unresolved identity/lifecycle relationships. Its implementation notes do not establish complete receiver acceptance.
4. [T-104](https://github.com/mfreeze77/statecivics-local-crawler/blob/f2fd7d39f97fb4f3510e3edef9c0c852e0b5f36f/tickets/T-104-related-jurisdiction-and-authority-relationships.md) remains open for verified related-government/authority relationship exports. Related-entity leads are not verified relationship coverage.
5. The current [matter source-claims schema](https://github.com/mfreeze77/statecivics-local-crawler/blob/f2fd7d39f97fb4f3510e3edef9c0c852e0b5f36f/schemas/matter_source_claims.json.schema.json) is a loose, sample-derived producer schema. Passing it does not certify semantic completeness or a new Matter contract.

This specification is an additive contract proposal. It does not label all of those existing tickets complete or reinterpret retained source claims as accepted facts.

## Profile manifest contract

MAT-046 defines a portable JSON manifest. Its exact schema is future work under the neutral profile contract, with these required meanings:

| Field group | Required meaning |
| --- | --- |
| Identity | Profile ID/version/digest, producer repository/revision, schema version and intended domain |
| Scope | Jurisdiction ID, body ID, meeting types, matter/instrument categories and explicit source namespaces |
| Validity | Effective-from/to and evidence-available-at clocks; unknown bounds stay explicit |
| Parents and overrides | Exact parent profile digest, scoped overrides, conflict precedence, source basis and reviewer identity where reviewed authority is claimed |
| Authority capability | Named act, body, target category, jurisdiction and temporal scope; state of the authority assertion; supporting source and optional receiving attestation |
| Procedure | Allowed event vocabulary, recognition/second/vote/threshold conventions, deviations and applicability; observations cannot invent missing rules |
| Sources | Eligible source kinds, required evidence, locator requirements, source stage, coverage limits, known exclusions and precedence by claim family |
| Rule bindings | Rule IDs/versions, dependencies and parameters; separate factual-stage, authority, resolution and attention rules |
| Qualification | Fixture/corpus hashes, independent review state, supported/unsupported cases and version compatibility |
| Change history | Supersedes/withdraws links and reason; no in-place rewriting of a prior manifest |

An authority capability is not an integer rank. A body may recommend in one category, decide another, act as a differently constituted board during a separate sitting, and have unknown capacity for a third category. The proposed assertion states are `unreviewed`, `supported_source_claim`, `reviewed_host_attestation`, `disputed`, `withdrawn`, and `unknown`; these are profile-domain values pending the common schema, not new core authority states.

Override order is explicit and testable: a referenced base profile supplies defaults; a narrower jurisdiction/body/category/effective-period override may replace only listed fields. Conflicting equally applicable reviewed sources remain disputed. Missing parents, unknown signatures or contradictory validity periods cannot silently fall back to a more permissive tier. A new profile version can change an assessment without changing the underlying occurrence.

## Observations, occurrences and source-claim links

Each export retains the original producer event ID, source namespace, revision/hash, original raw identifier and locator. A meeting occurrence has its own identity even when it concerns the same continuing case. One recording can contain several body sittings; joint meetings and reconvened boards must retain interval-specific acting bodies.

Use typed relationships instead of title-only matching:

- Continuing matter to agenda appearance.
- Case to proposed/adopted instrument.
- Instrument to amendments, repeal, renewal and replacement.
- Motion occurrence to target matter/instrument and source vote report.
- Source claim to the specific proposition it supports, contradicts, qualifies, or reports.
- Body/role/authority assertion to its supporting source and effective period.

A case number must retain issuer, jurisdiction, type and year scope. A publisher tracking number is not interchangeable with an ordinance number. Similar titles, the same address or a repeated person name generate candidates for review, not automatic merges. Applicant, agent, staff presenter, public speaker and voting member remain separately sourced roles.

The minimum claim record includes exact subject/predicate/object or bounded source text, the claim family, evidence references, source stage, event and availability clocks, observation/occurrence IDs, derivation lineage, confidence meaning, completeness and unresolved reasons. A summary cites its underlying evidence and does not increase independent corroboration.

## Civic stages are supported claims, not a universal progress bar

Profiles may represent discussion, recommendation, authorization, funding, procurement, award, publication, effective date, cancellation, expiration or renewal. These dimensions can branch, coexist or reverse. A funding discussion is not an appropriation; an appropriation is not a solicitation; a failed approval motion is not adoption; a recommendation is not an exercise of final authority.

For a proposed action assessment, evaluate separately:

1. What was moved, including the target and any amendment.
2. What outcome the source reports.
3. What vote method, denominator and threshold are actually stated or reviewed.
4. Whether the acting body had reviewed authority for this act, category and time.
5. Whether additional conditions, publication or effective-date requirements remain unmet or unknown.

Compute vote arithmetic in code only when required operands and applicable rules are known. Preserve `not_computable` when seats, threshold, abstentions, membership changes or rule applicability are unknown. Spoken unanimity is not a machine-readable roster tally unless the source supports it.

The result can be a supported source claim, an unresolved condition, a disagreement between sources, or an action proposal for the receiving application. A semantic evaluator can identify the proposition; it cannot confer legal authority.

## Time, coverage and correction

Keep occurrence time, source publication time, capture time, evidence availability, authority-review availability and assessment time distinct. Late minutes may change today's understanding of an earlier meeting without pretending the earlier system had those minutes.

Coverage states must distinguish `expected_not_published`, `capture_failed`, `available_partial`, `available_complete_for_declared_scope`, `manual_review`, `not_applicable`, and unknown states where applicable. These are profile descriptions; a retrieval timeout cannot establish absence. A negative claim requires a named expected source set and a coverage witness.

Corrections, withdrawn documents, reclassified bodies, edited minutes and revoked authority attestations append new evidence/profile versions. They invalidate dependent assessments and queued updates; delivered claims may warrant a correction to the same audience. A user's dismissal changes attention disposition, not source truth.

## Purpose-specific attention

MAT-049 consumes the same evidence for different declared purposes: public research, monitored civic action, procurement planning or service-fit opportunity monitoring. Territory, service match, deadlines, responsible owner and already-delivered assessment are explicit audience inputs. No jurisdiction fact changes because a salesperson's preferences change.

Quietness reasons distinguish unchanged assessment, already-delivered change, irrelevant current purpose, audience disposition, expected future publication, incomplete evidence and unavailable evaluation. Only a named decision that requires the audience's authority should become a decision request. Ordinary missing information first becomes bounded evidence work or a recorded unresolved question.

DIAT procedure output is only an experimental source claim. It may identify a plausible motion or floor transfer; it does not close a civic matter or establish the official vote.

## Delivery and receiver qualification

The first adapter operates on copied/exported packages and synthetic fixtures. It pins producer and consumer schema versions, hashes every source artifact, rejects unknown consequential fields, and emits proposed assessments to a reviewable local artifact. No new crawler run, public notification, receiving import, enrollment or deployment is part of this roadmap-delivery action.

Qualification must include:

- Recommendation then final decision by different bodies.
- Failed approval, no second, unanimous consent, unknown threshold and absent denominator.
- Joint sitting/reconvening with the same people under different body identities.
- Case-number collision across jurisdictions and years; multiple instruments on one case.
- Two reports of one meeting versus a new hearing of the same case.
- Late minutes, future authority review, withdrawal and correction before queued delivery.
- An authoritative positive retained alongside missing/ambiguous sources.
- Stable IDs and identical replay for an unchanged package.
- The same evidence assessed differently for two audiences with no factual divergence.

Native receiving integration remains separately qualified against the receiving application's pinned contract. Existing crawler schema acceptance is insufficient.

## Planned deliverables

| Ticket | Deliverable |
| --- | --- |
| MAT-046 | Neutral civic profile/authority manifest contract and synthetic examples |
| MAT-047 | Crawler-owned jurisdiction overrides and source-backed authority export |
| MAT-048 | Export adapter for source claims, occurrences, stages and relationships |
| MAT-049 | Purpose/audience assessment and meaningful-change delivery profile |
| MAT-050 | Temporal, authority and producer/receiver conformance qualification |

All five remain planned. Implemented code, synthetic conformance, historical replay, provider semantics, receiving acceptance and live usefulness must be reported as distinct evidence.
