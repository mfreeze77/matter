# Semantic evaluation and JEV

Status: implementation contract. MAT-026 through MAT-035 are planned work; this document does not claim that a provider adapter, a qualified model, or a live attention policy has shipped. The source notes are [matterbrainstormspec](../matterbrainstormspec) and [matterjevmesh](../matterjevmesh). [jevinmatter](../jevinmatter) is a procedural-diarization example, not the general executor contract.

## Ownership

Matter owns stable subjects, observations, occurrence lineage, claims, immutable assessments, and the reasons an audience receives an update. A semantic evaluator supplies a narrowly defined judgment about a bounded input. It cannot create authority, silently merge subjects, confirm a person, enroll a speaker, resolve a matter, or deliver a message by returning a large number.

Current user instructions, corrections, and stop signals remain on the host application's control path. They do not wait for accumulation or a semantic threshold. A provider failure leaves an evaluation unresolved; it does not change accepted intent or manufacture a successful recovery.

The first semantic pilot uses agent validation episodes and fixed evidence packets. Civic and DIAT examples explain possible consumers. They do not authorize modifying those products or importing their experimental data into this repository.

## Provider-neutral executor

The planned interface accepts a batch of question instances plus an execution context and returns a batch execution record. Its inputs are ordinary serializable data; importing the core must not import a vendor SDK or read a credential. An adapter maps the neutral contract to a specific provider and transport.

| Boundary | Required contents |
|---|---|
| Question specification | Semantic family, revision, primitive, complete instructions, ordered criteria, required input fields, rendering revision |
| Question instance | Specification digest, local correlation ID, rendered question, bound candidate/claim IDs, exact packet digest |
| Execution context | Provider/transport, requested model, run/stage IDs, scope, deadline, byte/call limits, execution mode |
| Batch result | Original response reference, normalized typed answers, exact response key diagnosis, provider model, timing, usage, and faults |
| Admission result | Qualified or unqualified status, certificate reference, policy revision, and explicit reasons |

Transport success, primitive validity, qualification, and permission to act are four different checks. A result may pass one and fail the next. The first implementation uses whole-batch admission: malformed, missing, duplicated, or unexpected answer IDs make that batch ineligible for consequential use. Diagnostic records still retain individually valid answers. Later partial admission requires an explicit dependency-aware contract and its own qualification; it must not happen through an error handler.

## Preserve primitive meaning

TypeSafe's documented response shapes are the adapter reference. The neutral representation retains the original value and distribution instead of coercing every answer into a generic importance score.

| TypeSafe primitive | Meaning and response | Matter interpretation |
|---|---|---|
| Choice | One declared alternative; `choice`, `probabilities`, `confidence` | Preserve exact option identity and its full distribution. Use complete, defined outcomes. |
| Score | Position on ordered descriptive levels; `score`, `legend`, `probabilities`, `confidence` | Preserve the fractional value and rubric. For levels indexed 0 through n−1, the score is the probability-weighted level position. It is not a probability of correctness. |
| Noul | Probability that a specified proposition is true; `noul` in [0,1] | Preserve the direction of the proposition. There is no separate vendor confidence field. An intermediate value is not medium severity. |

References: [Choice](https://docs.typesafe.ai/primitives/choice), [Score](https://docs.typesafe.ai/primitives/score), [Noul](https://docs.typesafe.ai/primitives/noul), [confidence](https://docs.typesafe.ai/confidence).

### Numeric representation across the provider boundary

Raw provider-response artifacts preserve their original bytes and numeric lexemes. Normalized probability, Score, confidence, and rounding-residual fields use the schema-declared decimal strings required by the [core encoding contract](contracts/core.md). Parse numeric lexemes losslessly and perform range, distribution, rubric, and trusted-tolerance validation using exact decimal arithmetic before computing the normalized receipt or its digest. Converting through binary floating point and then formatting a string does not satisfy this requirement.

The trusted precision profile describes permitted wire rounding; it does not authorize rewriting the original response or silently changing normalized values. If an SDK exposes only rounded binary-float values and the adapter cannot recover the original representation, record that precision limitation explicitly and leave exact-numeric admission unqualified. Do not label reconstructed values as original wire evidence.

Conformance includes a raw value such as `0.1234567890123456789`: the raw artifact retains its bytes, the normalized field retains the exact decimal string, and normalization/re-encoding preserves the declared digest. Score distributions, confidence, and calculated residuals receive the same treatment. Transport wire formatting and the canonical normalized representation are separate identities.

Validation rejects booleans masquerading as numbers, nonfinite values, missing probabilities, unknown options, altered legends, and values outside the declared range. It never clamps or substitutes zero. Wire rounding must use a versioned precision profile owned by the trusted adapter, with the observed residual retained. A response cannot loosen its own tolerance. The existing [OIL validator](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/decisions/validate.py) is a concrete reuse candidate for this behavior; its OIL-specific outcome mapping is not part of Matter.

A semantic relevance result is not an identity probability. Repeated model summaries are derived evidence, not independent corroboration. Score combinations may implement a documented local ranking policy, but neither a product nor an average of judgments establishes the probability of a compound factual claim.

## Questions and rendering

The registry stores one canonical specification per family/revision. Instructions must name the actual state fields and include the question's complete meaning. Correlation IDs route responses; they do not supply model-visible instructions. Choice option names and descriptions both matter; Score levels must make sense independently. [TypeSafe primitives](https://docs.typesafe.ai/primitives) documents these distinctions.

Record a digest of the specification, renderer, ordered criteria, and fully rendered request. Preserve option order in hashing; sorting a map must not erase a meaningful presentation change. Rendering produces a manifest of included sources, excluded sources with reasons, missing prerequisites, and any truncation. Extraction of dates, arithmetic, exact identifiers, deduplication, availability checks, and deterministic scope constraints belongs in ordinary code.

For the initial association pilot, keep the outcome set fixed (`same_matter`, `related`, `different`, `insufficient`) and put bounded candidate facts in the state. Do not silently change the number or meaning of choices under a certificate fitted to another set. A future parameterized candidate-option family needs declared cardinality/mapping limits and evaluation covering them.

## Independent batching and genuine dependencies

Batch questions when they can be rendered from the same frozen packet. A conditional question can still be batched if its condition is completely described in that packet; application code may ignore an irrelevant answer. A second stage is necessary when the preceding validated result determines a new fetch, a new packet, or the next question's alternatives. No question may implicitly consume a sibling answer from the same request. [TypeSafe's dependency guidance](https://docs.typesafe.ai/primitives) is the provider reference.

The stage planner validates a directed acyclic graph before dispatch. Each edge names the required prior result and acceptance condition. An invalid or unqualified prerequisite produces a recorded stop or permitted alternate path, not a fabricated default. Stage receipts retain parent result IDs and packet revisions. Stale completions can remain historical observations while being barred from current admission.

## Execution and receipts

The first modes are `offline_fixture`, `recorded_replay`, and `provider_shadow`. A future `qualified_contribution` mode requires the release gates in [evaluation.md](evaluation.md). A missing selected adapter must fail explicitly; it cannot silently substitute a different model. The default automated checks make no network calls.

Every execution receipt binds:

- Matter and assessment revisions, scoped claim/candidate IDs, occurrence lineage, and evidence availability cutoff.
- Included source revisions/locators/hashes, omissions, coverage, packet profile, and exact packet digest.
- Question specification, rendered instructions, ordered criteria, renderer, request digest, and stage parents.
- Requested model, response-resolved model, provider/transport/SDK version, trusted precision profile, and raw-response artifact reference.
- Attempt identity, dispatch/completion times, timeout/cancellation outcome, bytes when observable, usage, and cost basis when available.
- Primitive validation, qualification certificate, policy revision, admission reasons, and later invalidation.

Unknown bytes, missing usage, and an unavailable price basis are null plus a reason, not zero cost. Secrets are excluded from receipts. A retry is another execution attempt tied to the same logical request; it is not independent source evidence.

Exact reuse requires the same semantic input and execution assumptions, including model resolution, packet, ordered questions, rendering, and precision profile. Policy-only re-evaluation may reuse a valid raw judgment while producing a new admission decision. Revoked qualification or changed evidence invalidates current eligibility even if the cached response is unchanged. A cache hit is recorded separately and never counted as a fresh provider trial.

## Qualification and uncertainty

A certificate identifies the exact model, semantic specification, option/rubric definitions, renderer, packet-preparation profile, source/domain scope, calibration measure, thresholds, evaluation corpus/split, support counts, validity period, and measured error/coverage. The rendered instance and its actual packet remain in the execution receipt. Qualification attaches to a tested procedure and domain; it is not a certificate for arbitrary new meanings with the same JSON type.

Check certificate applicability before dispatch where possible and again before admission. A failed, missing, expired, revoked, or mismatched certificate leaves a well-formed result unqualified. Floating model aliases without a sufficiently precise resolved version may run in shadow, but cannot inherit qualification from a guessed snapshot. Thresholds for positive and negative Noul decisions can differ; an undecided region is explicit.

Disagreement, insufficient evidence, irreconcilable conflict, invalid response, and provider unavailability have different reason codes. A stronger model can be a separately measured fallback, not ground truth. None of these statuses automatically generates a question for the user. The host chooses a permitted investigation, deferral, or concrete decision request.

## Bounded investigations

An evidence request names a claim, a missing prerequisite or conflict, permitted sources, and a stopping rule. Model ranking is advisory within that host-supplied candidate set. The host enforces read permissions, maximum rounds, attempts, time, bytes, and recurring-request suppression.

| Stop condition | Recorded result |
|---|---|
| Required evidence supplied | Reassess against the full policy; sufficiency alone is not an action grant |
| No eligible source or missing coverage | Preserve the named gap |
| Conflicting evidence remains | Preserve both claims and the conflict |
| Budget/deadline reached | Incomplete investigation |
| Stale matter or changed purpose | Cancel current eligibility and retain history |
| Authorized decision needed | Prepare the decision and its evidence for the host's control path |

No stop caused by cost, error, or missing access becomes an assertion that the matter is resolved. Fixed packets precede adaptive retrieval in the roadmap.

## Delivery boundary

Semantic evaluation proposes facts about relevance and change. The domain profile decides whether those facts establish a valid assessment. The audience policy decides whether an update is useful. The host checks accepted intent, ownership, stale inputs, and prior delivery immediately before delivery. Delivery, consumption, action, and verified outcome remain separate observations.

Implementation sequence: MAT-026–032 establish interfaces, rendering, packets, stages, receipts, qualification, and optional transport; MAT-033–034 add shadow question families; MAT-035 adds bounded investigation. Their acceptance evidence is defined in the ticket register and [evaluation.md](evaluation.md).
