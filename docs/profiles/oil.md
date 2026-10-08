# Oil integration profile

Status: **proposed downstream integration, not implemented by this scaffold**. MAT-066 through MAT-071 govern the work in `mfreeze77/oil`. Matter owns neutral contracts and logic; Oil owns its runtime adapter, operational records, host behavior, and downstream qualification. This document does not authorize deployment, host enrollment, provider runs, or changes to Oil.

The source baseline is Oil commit [3d7c629fd45067de405c1bbae0a2aa0e4036399a](https://github.com/mfreeze77/oil/tree/3d7c629fd45067de405c1bbae0a2aa0e4036399a). Current code and the October 7 milestone were inspected. Repository test reports are source evidence; those Oil tests and live owner sessions were not executed for this scaffold.

## 1. Purpose and boundary

The user's problem is the cost of repeated, low-value input during active agent work. This profile accumulates observations into durable matters, preserves uncertainties and recovery, and asks whether a material development warrants a useful host hint or human decision. It must measure retained catches and missed developments alongside fewer interruptions.

The initial pilot is recurring operational failure and its recovery. It exercises identity, genuine occurrence counting, contextual relevance, bounded evidence, invalidation, and delivery without requiring a redesign of every Oil check. The rest of Oil continues to enforce accepted constraints and serve applicable standing context.

The following invariants are mandatory:

- The intent ledger remains authority. A recurring observation, model claim, matter priority, or attention decision cannot accept intent or supersede an accepted rule.
- Explicit user controls, permission boundaries, cancellation, and deterministic obligations bypass ordinary aggregation. They must not wait until a matter becomes important.
- Agent hints and human decision requests are distinct audiences. Routine authorized repair belongs to the working agent; uncertainty alone does not require a human question.
- Quiet, acknowledged, delivered, compacted, stale, and recovered remain distinct facts. No ordinary session requires an Oil closeout ritual.
- Models and optional investigation remain detached and bounded. Basic capture, recurrence, recovery, and deterministic attention work when providers are absent.

These requirements extend the [core](../contracts/core.md), [rules](../contracts/rules.md), and [lifecycle](../contracts/lifecycle.md) contracts. Oil's existing [resolver](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/kernel/resolver.py) already excludes model inference and review findings from superseding accepted intent.

## 2. What exists, and what still needs integration

| Inspected mechanism | Existing behavior | Matter integration work |
|---|---|---|
| Watcher observation and check lanes | Commit/edit/failure observations, detached checks, streamed findings, returned findings, and deferred work | Capture the complete episode, including successful operations, explicit no-finding outcomes, source changes, task changes, and control events |
| Generic repeated failure | Same normalized command and audience within a recent window can produce another finding after delivery | Qualify occurrence and task/workdir correspondence, retain recurrence state, and reconcile recovery |
| IO2-143 locality | Diagnostic-only locality hints have occurrence-based expiry, source freshness checks, and matching known-success receipts | Reuse these safeguards and add generic lifecycle correspondence; do not replace a working recovery path |
| Cognition store | Run-local version checks, dependency registration, atomic commits, and transitive invalidation | Give operational matters stable ownership and explicitly import/reconcile dependencies across immutable cognition runs |
| IO2-142 evidence preparation | Claim-specific code/docs/skills/tests/config domains and bounded final evidence payloads | Adapt existing admitted evidence and evaluator clients into Matter questions and dependency manifests |
| Mailbox and host hooks | Decisive-only inferred delivery, bounded output, leases, output-flush confirmation, task/context guards | Prepare attention from valid matter state and revalidate at the host's dispatch boundary |
| Replay | Pinned chronological inputs, availability gates, bounded structural replay | Add matter outcomes, quiet-decision sampling, concurrency faults, and comparative live qualification |

Sources: [watcher model](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/watcher/model.py), [checks](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/watcher/checks.py), [IO2-142](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/tickets/IO2-142-claim-specific-evidence-domains.md), and [IO2-143](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/tickets/IO2-143-failure-locality-lifecycle.md).

The [October 7 milestone](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/docs/feedback/2026-10-04/MILESTONE_2026-10-07.md) reports implementation of current-task context, contextual caps, delivery memory, semantic hotspot deduplication, bookkeeping/actionability guards, and matching locality recovery. Its latest close-of-day section reports merged changes and updated registration. It still leaves actual owner-session consumption, parts of live workload acceptance, and provider replay open. The Matter experiment must compare against this corrected baseline. Older incidents establish test scenarios; they do not establish that current code still exhibits every earlier annoyance.

## 3. Complete event capture: MAT-066

A findings-only adapter is insufficient. [`worker._post`](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/watcher/worker.py#L92-L100) returns immediately when there are no findings. [`observe_tool`](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/watcher/hook.py#L534-L595) records known success before deciding whether to queue a commit/edit/failure observation. Success is therefore not generally another queued watcher observation.

The adapter must normalize these inputs:

| Input | Required meaning |
|---|---|
| Native observation | Original occurrence/invocation identity, event and observation times, repository, audience, task, source versions, and omissions |
| Check completion | Check/version, completed or unavailable coverage, admitted evidence, findings, and explicit outcome semantics |
| Streamed or deferred finding | Stable origin identity and phase; duplicates across result lanes do not become new occurrences |
| Trusted success receipt | Exact known status source, operation correspondence, workdir, task, audience, and success time |
| Source or task change | Version/context change that may invalidate an assessment; not automatic factual recovery |
| Host control/lifecycle input | Authenticated control or task/session boundary, with explicit scope and epoch |

An empty result is useful evidence only when its producer declares a completed, relevant check and the profile defines its meaning. Missing output, failed checks, partial coverage, search no-match, and silence must not resolve a matter. The current bounded success-receipt directory requires a durable ingest cursor or equivalent atomic handoff so pruning cannot erase an unconsumed recovery. Replay and restart must reconcile duplicates without inventing success.

Preserve parent-session audience routing and child task identity. Existing edit coalescing uses audience plus task; the adapter must not merge another task merely because a command or path matches.

## 4. One operational owner and stable identity: MAT-067

**Proposed ownership decision:** Oil owns the canonical operational matter namespace through an Oil adapter in its existing watcher SQLite storage. Matter supplies the neutral storage port, reducer, and contracts. The existing mailbox remains delivery transport, and the intent ledger remains authority. No second competing matter store, background daemon, or independent delivery queue is introduced.

This is a design to implement and qualify. Current `chain.sqlite3` is opened by CognitionStore with its own application/schema checks. Adding a matter namespace requires a reviewed Oil-owned schema/version migration, compatibility policy, transaction boundary, recovery path, and retention rules. It is not permission to append unmanaged tables or bypass the existing opener.

[`chain_check._ensure_run`](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/watcher/chain_check.py#L566-L601) keys live cognition runs by core fingerprint, session audience, code tree, and lane suffix. The immutable RunManifest and its core checks must remain intact. A long-lived cognition run is not the operational matter.

Stable matter identity is scoped to repository/owner and accepted subject correspondence. It is independent of a code-tree revision or one session run. Audience, task, source revision, occurrence, assessment, and disposition remain explicit relationships. Cross-session continuity requires accepted correspondence and access scope; it must not silently carry one session's private task into another.

[`RunStore.commit`](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/cognition_store.py#L275-L350) validates read versions and transitively invalidates registered dependencies within its run. That primitive is reusable, but existing triggered advice [commits with an empty dependency list](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/cognition_engine.py#L1456-L1459). Its snapshot design does not establish source-dependent live invalidation.

The adapter must record immutable cognition-run assessment references and materialize their relevant source/read dependencies in the operational namespace. A source or purpose change must invalidate dependent assessment and pending attention there, including results imported from an earlier run. Atomicity and idempotency tests must cover the handoff. Run-local invalidation and cross-run continuity are separate acceptance cases.

## 5. Bounded claims and assessments: MAT-068

Reuse Oil's IO2-142 claim-specific preparation, `NarrowState`/`JudgmentEvidenceSource`, `cognition_context`, repository profiles, named ticket paths, and existing evaluator clients. Do not add a new evidence graph or let Matter independently retrieve an unbounded repository.

An assessment request identifies one proposition or explicit comparison, applicable rule and audience, admitted evidence IDs and byte spans, content/source versions, availability cut, coverage/omissions, and allowed provider-sharing scope. Results bind that exact packet and evaluator/model versions. A semantic result cannot silently expand citations, reinterpret unavailable evidence as absent evidence, or turn context into accepted authority.

Materially unchanged semantic packets reuse a valid recorded result only while the shared cache and qualification contract still holds. A timer or routine session restart does not itself require another model call when relevant semantic inputs and evaluator bindings remain unchanged. Repeating an identical rendering may reuse the result; a changed renderer, ordered question, or resulting packet must pass the shared compatibility checks and may require re-evaluation or requalification. Dependency changes cause targeted re-evaluation; they do not clear all history. Rejected, unavailable, contradictory, or incomplete results remain inspectable without becoming new interruptions.

Optional bounded investigation may use existing coordinator/session seams under the neutral investigation contract. It must declare scope, budget, stopping conditions, and why the result could affect a decision. It cannot be required for persistence, deterministic recovery, or basic attention.

## 6. Recurrence, recovery, and attention: MAT-069

[`RepeatedFailureCheck`](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/watcher/checks.py#L225-L259) currently groups by command and audience; its generic path does not inspect task/workdir correspondence or known-success receipts. A later count can produce a new finding after an earlier one was delivered. This is a source-supported pilot opportunity, not a measured claim that all present interruptions arise there.

The profile must distinguish these developments:

- A duplicate representation of one invocation improves provenance; it does not increment occurrence count.
- A genuine repeat of a scoped failing operation can strengthen evidence of persistence without establishing its cause.
- A known successful corresponding operation after the failure can resolve the relevant operational condition.
- A source edit invalidates stale diagnostic advice but does not prove the failing operation now succeeds.
- Recovery followed by a genuinely new failure can reopen the matter with a new episode and explicit changed evidence.
- A different task, workdir, tool, or command does not recover another operation without a qualified correspondence rule.

Retain the existing IO2-143 diagnostic exclusions, occurrence-based TTL, source-hash checks, and matching success guards. A generic reducer must not make locality hints less safe. Expired recovery evidence or incomplete capture yields unknown correspondence; it does not silently reset recurrence.

Attention compares the current valid assessment to the last delivered baseline for the relevant audience and purpose. It considers material consequence, whether the next step is already owned, time sensitivity, explicit dispositions, and cost of interruption. Recurrence thresholds, windows, hysteresis, and exception paths are versioned profile settings, calibrated under MAT-071. No universal count threshold suppresses a decisive immediate issue.

## 7. Native host delivery: MAT-070

Use Oil's existing host adapters, durable worker scheduling, and mailbox reserve/confirm flow. Preserve decisive-only inferred delivery, current-context guards, and the configured output cap. At the inspected baseline the watcher defaults to at most three items and 1,800 characters per hook boundary; other retrieval and cognition budgets are separate ([configuration](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/config.py)).

A prepared hint binds matter/assessment revisions, evidence manifest, audience/purpose, previous delivered baseline, control epoch, and stable delivery key. Immediately before the declared host dispatch cutoff, revalidate these dependencies, recovery, dispositions, and host authorization. A control or recovery observed before the cutoff prevents dispatch. An event observed after irreversible output is recorded as a race outcome, with any warranted correction governed by host policy.

The [mailbox](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/watcher/mailbox.py) and [hook delivery](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/watcher/hook.py#L609-L657) confirm local emitted output, not consumption. Preserve offered, emitted/delivered, delivery_unknown, consumed, acted_on, and outcome_verified as separate receipt stages. Crash windows need an explicit bounded retry/unknown policy; no claim of exactly-once delivery or known reading is permitted without transport evidence.

[`hooks.claude`](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/hooks/claude.py) routes subagent observations to the parent audience while retaining task identity. Session start/compaction resets delivery memory in [retrieval](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/ledger/retrieval.py#L874-L913). Matter must preserve those boundaries: reintroducing applicable context must not reopen resolved conditions or erase accepted dispositions. Parent/child and human/agent audiences are not interchangeable.

No new mandatory approval, acknowledgement, closeout, or synchronous model gate belongs in normal work. Existing precommit advisory holds remain bounded and fail open under their current host contract.

## 8. Qualification and rollout gates: MAT-071

The comparison freezes the current Oil baseline and candidate bytes, profiles, corpus manifests, evaluator settings, and budgets. Historical incident reconstructions, installed adapter witnesses, deterministic replay, provider re-execution, and live owner sessions are distinct evidence classes.

Oil's [replay controller](https://github.com/mfreeze77/oil/blob/3d7c629fd45067de405c1bbae0a2aa0e4036399a/src/intent_oil/cognition_replay.py) gates inputs by availability and pins corpus digests. Its structural replay does not establish real concurrent timing or a model's ignorance of future facts. Retain those limitations in every report.

Qualification must report:

| Dimension | Required evidence |
|---|---|
| Retained value | Important catches retained, missed/delayed developments, recovery handling, and sampled quiet decisions judged against held-out outcomes |
| Noise | Duplicate and non-actionable hints, interruption episodes, character volume, and repeat delivery after acknowledgement/compaction |
| Timing | Event-to-ready and event-to-emission distributions, observed dispatch races, time-sensitive misses, and provider-independent control latency |
| Resources | Hook/worker latency, provider calls/bytes/spend, queue growth, storage growth, and cold/warm/restart behavior |
| Host outcomes | Transport milestone, consumption if observed, action correspondence, and usefulness assessed separately |
| Product invariant | Zero required ordinary closeout actions and preserved accepted-rule/control behavior |

Use preregistered threshold arms on the same frozen cohorts, with blind human outcomes held out from tuning. Preserve representative hard catches, conflict/unknown cases, cross-task collisions, no-output success, changed-source invalidation, and genuine recurrence after recovery. Concurrent, crash, and compaction faults require dedicated native-host scenarios beyond chronological replay.

A favorable noise result cannot pass a release gate by hiding important misses, increasing unbounded inference, or assuming every emitted item was consumed. Live evaluation and activation remain downstream work with explicit owners and evidence. The scaffold records the plan; it does not claim reduced annoyance, successful deployment, or completed Oil acceptance.
