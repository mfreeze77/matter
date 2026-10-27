# Semantic evaluation: reuse decisions and source evidence

Reviewed 2026-10-08. This is an implementation planning record, not a claim that upstream code was incorporated or its tests were rerun. Only the listed files and source pages were inspected. No third-party code has been copied for this record.

## October 16 follow-up

The [JEV research update](../research/jev-watch-2026-10-16.md) adds VideoJev,
Sayora's candidate-selection experiment, Liquid d1-ultra, and OpenRouter's Jev
transport. It maps the findings to the existing semantic and evaluation tickets
and records proposed EXAIS/CSCAi relationships alongside the OIL, civic, and DIAT
profiles. The October 8 review below remains unchanged historical evidence.
See also the [new evaluation cases](../evaluation.md#october-16-research-derived-cases).

## Existing OIL seams

All OIL links below are pinned to `3d7c629fd45067de405c1bbae0a2aa0e4036399a`.

| Inspected source | Verified behavior | Matter application and limit |
|---|---|---|
| [decisions/system_one_http.py](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/decisions/system_one_http.py) | `SystemOneHTTPBackend.ask(state, questions)` accepts caller-supplied typed sets and records response/model/latency/usage; `evaluate` uses a fixed OIL set. | Prefer the arbitrary-question seam for an adapter comparison. An `ask` response still needs Matter's primitive validation and qualification before admission. |
| [decisions/jev.py](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/decisions/jev.py) | `JevDecisionBackend` lazily creates an async SDK client and evaluates the fixed catalogue with tracing and model-resolution metadata. | Reuse the separation of adapter and core, and SDK test injection. Do not import the fixed memory/review policy as Matter's semantic contract. |
| [decisions/validate.py](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/decisions/validate.py) | Strict key/type/range validation; dynamic specs; resolved-model handling; trusted precision profiles and quantization-aware Score checks; diagnostic heads separated from whole-set admission. | Adapt the validated-answer boundary and its failure fixtures after a dependency/API review. Keep diagnostic partial results from becoming qualified evidence. |
| [decisions/schemas.py](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/decisions/schemas.py) | Projects one question catalogue into provider-neutral data or SDK primitives, with lazy SDK imports. | Use one canonical Matter registry with projections. OIL's fixed outcome mapping and default coercions are not the reusable part. |

The choice between a shared package, a small protocol adapter, and an independently implemented compatible boundary is an implementation decision. Record the exact source, license, dependencies, API stability, and verification if code is later imported. A conceptual reference does not establish production compatibility.

## Jevcal

Reviewed [repository README](https://github.com/abhixhek/jevcal), [runtime.py](https://github.com/abhixhek/jevcal/blob/ae8f3144d69c9cb0e5e0a2c17f70b9d14714cb9f/src/jevcal/runtime.py), and [check.py](https://github.com/abhixhek/jevcal/blob/ae8f3144d69c9cb0e5e0a2c17f70b9d14714cb9f/src/jevcal/check.py). The exact code snapshot is `ae8f3144d69c9cb0e5e0a2c17f70b9d14714cb9f`.

Useful patterns are selecting a threshold on one split, reporting accepted accuracy and coverage on another, retaining confidence/wrong-answer examples, and checking drift. The README labels its sample output as simulated and acknowledges that teacher labels are not ground truth. Its license is described as MIT; a future code import still needs the actual license file and attribution retained.

At the inspected commit, `Cascade.decide` accepts when a stored threshold exists and the measured confidence meets it. It does not consult a stored held-out status there. The called `questions_from_lock` reconstructs specifications; the separate `check` workflow measures drift. Matter must place its own applicability and validity gate in front of consequential use, including for a high-confidence answer from a failed or mismatched qualification record.

Decision: reuse the measurement workflow as a reference; evaluate any library dependency separately. Do not treat this runtime as a complete qualification service or reuse its simulated percentages as Jev measurements.

## Jev-Mem

Reviewed [memory/jev_questions.py](https://github.com/libingzheren/Jev-Mem/blob/7ab0c73c6d8f4f611ad252c1e6ba8083f8df0e44/memory/jev_questions.py) at `7ab0c73c6d8f4f611ad252c1e6ba8083f8df0e44`. Relevant functions include `admission_questions`, `consolidation_questions`, `traversal_questions`, and `stopping_questions`.

The templates distinguish novel details from topic overlap, explicit updates from recency, incompatible claims from explained temporal changes, and a needed fact from a merely related passage. They also separately ask about missing evidence, remaining conflict, sufficiency, and the usefulness of another retrieval round. The source notes that question IDs are not model input.

Decision: adapt these distinctions into original Matter question definitions with declared outcomes and test examples. Do not copy templates without reviewing the applicable license. The repository's use of a corroboration question cannot establish independence of sources; Matter occurrence and provenance records must do that. No template performance or full Jev-Mem system validation is claimed here.

## Official provider contract

Use [TypeSafe primitives](https://docs.typesafe.ai/primitives), [Choice](https://docs.typesafe.ai/primitives/choice), [Score](https://docs.typesafe.ai/primitives/score), [Noul](https://docs.typesafe.ai/primitives/noul), [confidence](https://docs.typesafe.ai/confidence), and the [Python SDK reference](https://docs.typesafe.ai/sdk/python/api) when implementing MAT-032. `TypeSafeClient.system_one` and `AsyncTypeSafeClient` are documented SDK surfaces; a wrapper must declare which transport/version it uses. The HTTP request/response contract is separate from SDK object representation.

Matter's supported primitive set is deliberately explicit. An unknown server-side type is unsupported until its semantics, validation, and qualification are implemented; it cannot silently inherit another type's rules. Pin the selected SDK at implementation and exercise its object responses against the same conformance suite as HTTP-shaped responses.

## Research translated into tests

These are verified primary preprints and author-reported findings. They were read, not reproduced. They do not measure Matter's outcomes.

| Primary source | Relevant finding | Planned test |
|---|---|---|
| [Beyond Calibration: Do a Typed-Decision Model's Probabilities Obey the Probability Axioms?](https://arxiv.org/html/2609.33209v1) | Jev's linked-question answers were not perfectly coherent on the tested 160-item, fixed-snapshot study; batching did not remove the discrepancy. | Complement/equivalent-form checks, repeat baseline, joint-probability misuse prevention, separate composition tests. |
| [Type-Safe Decision Frameworks for Agentic 5G Control](https://arxiv.org/abs/2609.33689) | The dramatic changed-question failure belonged to the fine-tuned Laya encoder; hosted Jev and AnyJev behaved differently. | Paired examples where changing topic/matter/occurrence meaning must change the answer. Do not transfer Laya's rate to Jev. |
| [Type-Safe Is Not Error-Free](https://arxiv.org/abs/2609.26758v2) | Reassigning meaningful option names across fixed definitions affected hosted Jev as well as studied open models. | Label-definition swaps, neutral-label controls, semantic remapping, ordinary repeat variation. No claim about hosted internals. |
| [Evaluating and Benchmarking the System One Model Jev](https://arxiv.org/abs/2609.37647) | A 37-dataset evaluation reported encouraging classification behavior while binary thresholds needed task-specific care. | Family-specific thresholds and separate affirmative/negative error accounting on Matter episodes. No borrowed accuracy claim. |

## What is not imported

This plan does not add a graph database, message broker, acoustic model, or separate retrieval platform. It also does not import OIL's fixed policy catalogue, Jev-Mem's memory authority, Jevcal's runtime trust decision, or benchmark scores as Matter qualification. The intended deliverable is a small neutral execution and evaluation boundary over the existing Matter contracts, with optional provider transport and explicit receipts.

Roadmap: MAT-026–035 implement semantic contracts; MAT-036–045 supply the evaluation, comparison, and release evidence. Every ticket starts planned with no execution evidence.


## MAT-032 transport decision for the current roadmap

Inspected on 2026-10-27: Oil's arbitrary `ask(state, questions)` and SDK adapter
at `14772cd10b4fc3d3b54768a131de3acb45b5fde4`, under its Apache-2.0 license;
and the official Python SDK **0.7.5**, tag/commit
[`f36e68549ceca3191e5791e5f99ea1baa1a258b5`](https://github.com/typesafe-ai/typesafe-sdk-python/tree/f36e68549ceca3191e5791e5f99ea1baa1a258b5).
The SDK's [package declaration](https://github.com/typesafe-ai/typesafe-sdk-python/blob/f36e68549ceca3191e5791e5f99ea1baa1a258b5/pyproject.toml)
uses MIT and adds HTTP, Pydantic, retry and other runtime dependencies.
Its [response boundary](https://github.com/typesafe-ai/typesafe-sdk-python/blob/f36e68549ceca3191e5791e5f99ea1baa1a258b5/src/typesafe_sdk/_core/response_types.py)
exposes typed answers, including integer Score map keys, while
[raw HTTP metadata](https://github.com/typesafe-ai/typesafe-sdk-python/blob/f36e68549ceca3191e5791e5f99ea1baa1a258b5/src/typesafe_sdk/_core/schemas/base.py)
retains original bytes. Thus the SDK can support lossless validation through
its raw path; reconstructing decimals from its typed floats cannot.

Decision: implement one optional Matter adapter compatible with Oil's arbitrary
question HTTP boundary, using Python's standard library and Matter's existing
strict decimal validator. The existing Oil implementation returns a parsed
payload and belongs to a separate runtime; importing it would couple Matter to
that runtime and would still require an original-byte capture seam. The Matter
adapter will preserve the native wire artifact before normalization and reuse
one conformance boundary for HTTP and raw-byte-bearing SDK-shaped fixtures.
It will not construct a second SDK client or depend on Oil. This is an original
compatible implementation based on inspected API behavior, not copied upstream
code or a claim that upstream tests ran here.

The adapter will require explicit selection/model, bounded timeout/calls/retries,
redacted faults, exact requested/resolved models and honest usage/byte evidence.
Core imports and default tests remain offline. MAT-030 receipts and MAT-031
admission are prerequisites to implementation closeout; this decision alone does
not complete MAT-032. The earlier single synthetic live call used Oil's existing
transport and remains connectivity evidence only. No new live call is authorized
merely by this decision or assumed necessary to resume the roadmap.
