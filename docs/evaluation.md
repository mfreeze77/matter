# Evaluation and release evidence

Status: planned evaluation contract, covering MAT-036 through MAT-045. Examples and synthetic fixtures demonstrate contracts; they do not establish provider accuracy, live usefulness, or production readiness. Results must identify which mode actually ran and which gates remain unrun.

## Questions the evaluation must answer

The relevant outcome is whether a continuing matter preserves useful evidence and contributes at the right time with less unnecessary interruption. Classifier accuracy alone cannot establish that. The evaluation compares complete episodes while also locating failures in association, evidence interpretation, recovery, attention, and delivery.

An episode is a bounded task, incident, or hearing history with all related observations. It includes ordinary work and recovery, not only failures that already generated an alert. Independent reviewers label the outcomes that the experiment claims to measure, with source references, disagreement, and unresolved labels retained. Teacher-model labels are identified as such and cannot silently become human ground truth.

## Corpus and availability

Every corpus manifest declares its scope, source snapshots/hashes, extraction profile, observation IDs, occurrence groups, matter labels, and label provenance. Record event time separately from first availability to the evaluating system. Later corrections and documents may update current interpretation without appearing in an earlier replay prefix.

Use synthetic or appropriately cleared fixtures in the repository. Private exported sessions, rosters, MP3s, and live evaluation responses remain outside version control. The run records their manifest references and permissions; no production integration is required to evaluate the contract.

A provider may already know later facts through pretraining or previous exposure. Chronological input gating tests what the application supplied, not what the model has never seen. A stepwise replay also does not reproduce wall-clock latency or concurrent completion order. Both limits must be printed with any chronological results, following the explicit distinction in [OIL chronological replay](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/cognition_replay.py).

## Comparable arms and splits

The principal comparison uses two arms on the same frozen event stream:

| Arm | Allowed contribution |
|---|---|
| A: deterministic baseline | Existing deterministic identity, evidence, recovery, and attention policies |
| B: semantic candidate | The same policies and evidence, plus the declared semantic judgment families and their qualification gates |

Optional ablations can add one family at a time. Their manifest must name the difference. Separate retrieval experiments must not attribute better answers to the evaluator when one arm received more evidence. Either freeze equal packets or report an explicitly different retrieval arm with its cost and coverage.

Partition train/tuning, qualification, and final evaluation by episode and source lineage before fitting or selecting questions. The same occurrence, paraphrase, derived summary, copied log, or model-generated restatement must not cross those boundaries. Keep the final evaluation partition untouched by question rewrites and threshold searches. Repeatedly optimizing against a held-out set makes it tuning data; refresh the final test accordingly.

## Modes and what each proves

| Mode | Provides evidence for | Cannot establish |
|---|---|---|
| Offline fixture | Contract validation, deterministic transitions, faults, budget accounting, replay ordering | Semantic correctness of a live model |
| Recorded response replay | Admission/invalidation behavior on a fixed provider-output snapshot | Current provider availability, latency, nondeterminism, or current accuracy |
| Provider shadow | Observed model behavior on the declared corpus and exact inputs | Real-world delivery usefulness unless delivery is separately observed |
| Controlled contribution trial | Timing, consumption, response, and outcomes under a specified host integration | Broad transfer to other hosts or domains |

Default tests use no credentials or network. Provider mode must be explicitly selected with a supported adapter, data scope, model, call/cost limits, and output destination. Missing credentials produce an unrun-provider result. Never fall back to synthetic answers and label that run live.

## Primitive and question conformance

The contract suite covers all three primitives, unknown/missing/extra IDs, malformed JSON, duplicate keys, nonfinite values, booleans, wrong options, incorrect legends, truncated responses, and inconsistent Score distributions under the trusted precision profile. Include the same Score mean with different distributions so reducing an answer to one number cannot hide disagreement.

Question sensitivity probes must separate invariance from changed meaning:

- Repeat identical calls to estimate ordinary variation.
- Reorder options and map outcomes back to the original semantic labels.
- Substitute neutral option names while retaining definitions; separately swap names across fixed definitions.
- Change the question from topic overlap to same matter or same occurrence on cases where the answer must change.
- Ask logically linked complements and equivalent forms, including batched and separate requests.
- Change packet preparation, distractors, omissions, negation, dates, and required state paths deliberately.

Agreement between versions is not correctness. The probes supplement independently labeled outcomes and produce an incompatibility report when qualification must be redone. The relevant primary research is indexed in [semantic-evaluation.md](reuse/semantic-evaluation.md); those papers motivate tests and do not supply Matter's acceptance numbers.

## Thresholds and qualification

Predeclare decision-family targets, eligible source/domain scope, minimum independent episode support, tolerated errors, confidence-interval method, and abstention policy. Store the actual support behind every result. Thresholds fitted to Choice confidence, top probability, Score distributions, or Noul probabilities are different procedures and require separate evidence.

Tune only on the tuning split. Evaluate selected thresholds on the qualification split and report accepted accuracy, coverage, class-conditional mistakes, disagreement, and failed support requirements. For correlated observations, resample at the episode/provenance cluster level; do not manufacture a narrow interval by treating duplicated messages as independent trials. An observed zero error count on a small sample is not proof of zero error.

Jevcal provides useful fit/report/check patterns. Its inspected runtime gate accepts based on a stored threshold and observed confidence, without examining stored held-out status at that decision point. Matter therefore requires its own certificate admission boundary; a printed report marked failed must never be usable merely because a threshold was emitted. See the pinned source review in [semantic-evaluation.md](reuse/semantic-evaluation.md).

## End-to-end measures

Report counts, denominators, paired differences, and uncertainty at the episode level. Retain the bad examples that explain each result.

| Dimension | Required measures |
|---|---|
| Continuity | Correct associations, false merges, false splits, ambiguous cases, duplicate versus new-occurrence confusion |
| Evidence | Supported/unsupported conclusions, omitted counterevidence, unresolved prerequisites, coverage failures |
| Recovery | Matching recoveries, false closures, reopened matters, stale advice after recovery or source correction |
| Attention | Useful interventions, unnecessary interventions, repeats, important developments missed or delivered late |
| Delivery | Eligible, enqueued, delivered, consumed, acted on, verified outcome; each has its own denominator |
| Investigation | Useful evidence gained, repeated reads, stopped gaps, cost per resolved gap, evidence missed by search |
| Overhead | Calls, attempts, question/packet bytes, tokens, cost basis, CPU, wall time, queue delay, blocking time, p50/p95 latency |
| User effort | Required questions, unnecessary questions, manual bookkeeping, ordinary closeout actions |

Never optimize interruption count alone. A system that stays silent on every episode must fail when important cases were missed. Audit a declared sample of quiet outcomes, all severe labeled misses, and deferrals caused by failed observation or missing coverage. Label why the system was quiet and whether that disposition was justified at that time.

## Timing, concurrency, and overhead

Add a separate interleaving suite with controlled clocks and delayed provider responses. It must include a source edit during evaluation, recovery before a queued hint, a task switch, user cancellation, an old model result after a new assessment, conflicting simultaneous updates, retries, observer disconnection, and delayed data publication.

Measure queue time, provider duration, cancellation delay, final freshness checks, and actual delivery separately. A late completion can be retained for diagnosis while remaining ineligible to affect current state. Zero newly observed failures during a disconnected interval is a coverage condition, not a healthy interval.

Budgets are profile data with declared enforcement points. Report observed costs and unknown measurements; unknown is not free. Compare overhead with the same baseline workload. For percentage overhead, publish the denominator and do not divide by a zero baseline. This scaffold does not invent a numeric interpretation of the earlier low-overhead goal: the contribution trial must declare the actual target before measuring success.

## Release packet

MAT-045 collects the run manifest, source and question digests, model resolution, split definition, labels, executed commands, raw-response references, metrics, failures, qualification records, and gate decisions. Include a matrix with `passed`, `failed`, or `not_run` for each required gate. A documentation check or tiny deterministic walkthrough cannot mark MAT-038's full evaluator or a provider/attention qualification complete.

A release candidate can enable only the rule families that passed their applicable gates. Unqualified families remain shadow-only; live permission and application integration remain owned by the host. Replacing a model, renderer, criteria order, or evidence preparation requires the appropriate requalification. A delivery preference change may require only audience-policy evaluation when the raw judgment remains applicable.

Sources: [matterbrainstormspec](../matterbrainstormspec), [matterjevmesh](../matterjevmesh), [OIL validation](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/decisions/validate.py), [Jevcal runtime](https://github.com/abhixhek/jevcal/blob/ae8f3144d69c9cb0e5e0a2c17f70b9d14714cb9f/src/jevcal/runtime.py).
