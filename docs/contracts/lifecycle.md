# Matter lifecycle, attention, and delivery contract

Status: normative target specification. Bounded portions are implemented by MAT-009 [identity correction](../identity-corrections.md), MAT-010 [time and coverage](../time-coverage.md), and MAT-011 [trusted controls](../controls.md). Domain lifecycle, audience attention, scheduling and full delivery remain to be implemented and qualified through MAT-017 through MAT-025. The existing components do not establish those later runtime guarantees.

Sources: [matterbrainstormspec](../../matterbrainstormspec), sections 2–5 and 8–9, and [matterjevmesh](../../matterjevmesh), sections 3–7, 9, and 10. Companion contracts: [core](core.md) and [rules](rules.md).

## 1. Independent state dimensions

A matter is a durable identity. Its domain state, the validity of assessments, the user's dispositions, and attention delivery are separate dimensions.

| Dimension | Examples | Governing authority |
|---|---|---|
| Identity | active identity, redirected, protected separation | Accepted identity decisions |
| Domain lifecycle | proposed, active, resolved, withdrawn, or profile-defined states | Profile transitions and qualifying evidence |
| Assessment validity | current, superseded, invalidated, incomplete | Declared dependencies and versions |
| Disposition | acknowledged, deferred, rejected proposal, accepted decision | Host-authenticated decision and scope |
| Attention | quiet, eligible, queued, withheld, delivered, delivery_unknown | Audience policy, budgets, freshness, transport evidence |

There is no mandatory collecting-to-important-to-resolved sequence. Important is a contextual assessment, not an identity state. A resolved matter can remain relevant to research or receive a correction. A matter being quiet does not mean resolved, and an acknowledged warning does not mean its condition was repaired.

Domain lifecycle extensions MUST be versioned and describe permitted transitions, required evidence, applicable actor authority, effective time, and reopening rules. The core rejects transitions not declared by the active profile.

## 2. Domain transitions and ordinary maintenance

A transition request contains matter and lifecycle revisions, profile/edge version, triggering evidence and assessment, actor/authority reference, expected effective time, and idempotency key.

The operation validates the edge, scope, dependencies, applicable authority, and temporal correspondence. It atomically appends the transition receipt, updates the domain-state projection, and invalidates incompatible pending attention. Results are applied, already_applied, held_for_evidence, held_for_conflict, stale, or forbidden.

Resolution MUST be grounded in the profile's qualifying correspondence. The evidence must concern the relevant subject, condition, and circumstances. An unrelated successful action cannot resolve a failed required operation; a later discussion cannot establish an authoritative disposition. The core does not hard-code those domain examples.

Newly available evidence can establish a resolution effective in the past. The receipt records the past effective date and today's knowledge boundary. New evidence need not describe a later event to be relevant; later publication alone is not proof of supersession.

Ordinary resolution, expiry, source correction, and reopening SHOULD follow the evidence stream and declared policy without a user closeout ceremony. A human confirmation is required only when the host or domain policy assigns that particular decision to a human. A general desire for auditability is not a reason to request acknowledgement after every update.

## 3. Correction, retraction, and reopening

A correction adds a new source or decision record with a supersession relation. Prior records and assessments remain historically available. The current projection excludes superseded or invalidated evidence according to the rule profile.

Reopening requires one of the declared triggers: a new occurrence of a continuing condition, invalidated resolution evidence, an authorized corrected disposition, or a domain-defined recurrence rule. It must identify what changed since the last valid resolution. Repeated delivery of the original event does not reopen a matter.

Retraction of a source removes that source's current evidential contribution; it does not prove the opposite claim. If the remaining evidence no longer meets the standard, the current result becomes unknown or conflicted as appropriate. That transition may warrant a correction to a prior audience even if it introduces no new positive fact.

A complete source snapshot can retire its own machine-derived assertions only within a declared complete replacement scope. Failed collection, partial coverage, and incremental silence cannot close a matter. User decisions, rejected proposals, and protected identity separations survive replay until explicitly superseded.

## 4. Purpose and audience context

An audience context names an audience ID, responsibility/capability scope, active purposes, preferences, relevant dispositions, delivery channels, and interruption budget. A purpose has its own identity and revision, objectives and constraints, and applicable time.

Evidence interpretation can be shared across audiences when their evidence rules match. Consequence and attention decisions bind the purpose and audience revisions that actually affect them. No preference can change what a source stated.

Human and working-agent audiences are separate destinations. A matter that needs a routine next step may justify a host-agent hint while the human remains uninvolved. A decision request must name the decision, the person or role who can make it, the available options and evidence, and why ordinary authorized work cannot settle it.

Unknown semantic confidence alone is insufficient to request a human decision. Permitted responses include retaining an unresolved assessment, awaiting a scheduled source, conducting a bounded read, or using another qualified evaluator. The host's existing permissions continue to govern actual actions.

## 5. Attention decision

Attention is evaluated for one matter assessment, purpose, audience, and time. The required inputs are the current applicable assessment, previous delivered baseline for that audience/purpose, current dispositions, pending delivery state, and the relevant budgets and control epoch.

A decision MUST record:

- Whether a concrete objective, responsibility, opportunity, or decision is affected.
- What changed relative to the last delivered assessment, not merely the last internal computation.
- New evidence and its qualification, plus uncertainty and counterevidence.
- Whether the next step is already owned or underway.
- Proposed treatment and urgency with policy reasons.
- The known latest point before delay changes options, if any.
- Why a question or update would improve a decision.
- Freshness dependencies, cancellation epoch, and next reconsideration.

Allowed neutral treatments are quiet, host_hint, digest, update, correction, and decision_request. Profiles map them to their application channels. Eligibility is not authorization to send an external message. Channel adapters must enforce the host's actual delivery permission.

Required quiet/withheld reason codes include no_material_change, already_delivered, recovery_established, handled_by_owner, disposition_applies, deferred_until_checkpoint, budget_limited, insufficient_evidence, incomplete_coverage, stale_assessment, cancelled, and no_active_purpose. Several reasons may coexist. Insufficient evidence must not be reported as no important matter.

## 6. Recurrence and attention thresholds

Recurrence uses distinct accepted occurrence identities and declared provenance groups. Repeated observations of one occurrence can improve coverage or clarify a claim but do not automatically increase independent corroboration.

A profile may treat sustained duration or repeated genuine failures as greater consequence, while the proposed cause remains uncertain. It may also surface one decisive event immediately. Therefore the engine cannot require a universal count or a universal minimum confidence before every attention path.

Thresholds have declared units, windows, severity dimensions, and boundary semantics. Entry and exit thresholds or cooldown rules must be explicit where used. Hysteresis can prevent oscillation around a noisy threshold, but must not hide an authoritative correction, cancellation, or a newly critical deadline.

Deterministic obligations and direct control input bypass ordinary aggregation. Importance ranking cannot override a denied capability, accepted scope constraint, or cancellation.

## 7. Time-driven reevaluation and budgets

Relevant timer conditions are durable records keyed by rule/matter/purpose/audience scope and version. Each has next_check_at, expiry, dependency revisions, cancellation epoch, and an idempotent firing key.

Clock progression may make an existing fact important without a new observation. The scheduler reevaluates only affected temporal, consequence, or attention nodes. It must not call a semantic evaluator merely because a timer ticked when its semantic inputs are unchanged.

The scheduler handles process restart, delayed execution, clock skew within declared tolerance, cancelled jobs, and multiple workers. A late timer records scheduled and actual firing times. Catch-up deduplicates already applied conditions; it must not emit one obsolete warning for every missed interval.

Resource budgets and attention budgets are separate:

- Resource budgets cap evaluation, reads, candidate expansion, retries, bytes, elapsed time, and spend.
- Attention budgets cap deliverable rate or interruption cost per declared audience/purpose scope.

Reservations must be atomic so concurrent workers cannot overspend the same remaining budget. Unused reservations are released or expire under explicit rules. A budget-limited decision records its reason and next eligibility. No budget can defer a direct stop instruction or authorize a denied action.

Adaptive investigation remains optional. Basic persistence and deterministic attention must work without a model or investigator.

## 8. Delivery preparation, freshness, and concurrency

Delivery uses a durable outbox intent distinct from actual transport outcome. Preparing an intent binds the assessment revision, dependency manifest digest, audience/purpose versions, prior-delivered baseline, control epoch, treatment, content digest, authority receipt, and stable delivery key.

Before dispatch the worker MUST:

1. Claim the intent with a lease or equivalent fencing token.
2. Revalidate current assessment dependencies, resolution, dispositions, audience, baseline, and control epoch.
3. Recompute or withhold a stale proposal; never send known stale content.
4. Reserve attention budget and verify the host permits this destination.
5. Dispatch using the stable delivery key where transport supports idempotency.
6. Record the observed transport outcome without inventing consumption or action.

The eligibility check and dispatch authorization need a documented linearization point. Cancellation or recovery observed before that point prevents dispatch. An event arriving after an irreversible external send cannot be retroactively prevented; record the actual outcome and consider an authorized correction. A local transaction cannot promise exactly-once external delivery from a transport that supplies neither idempotency nor queryable receipts.

If the transport outcome is unknown after a timeout or crash, retain delivery_unknown. Retry may occur only according to transport capabilities and policy. Never mark unknown as delivered, and never blindly resend while claiming duplicate-free delivery.

A new delivered baseline is committed only with evidence of the declared successful delivery milestone. Concurrent intents compare that baseline to avoid repeating the same material delta. Cancelled or withheld intents do not advance the baseline. The receipt records invalidation that occurred during or after transport.

## 9. Outcome receipts and explainability

Outcome stages are independent:

| Stage | Evidence required |
|---|---|
| eligible | Attention rule result and valid inputs |
| offered / queued | Host presentation or outbox acceptance receipt |
| delivered | Transport's declared success milestone |
| consumed | Observable read/receipt event or explicit acknowledgement, if available |
| acted_on | A corresponding action linked to the contribution |
| outcome_verified | Evidence that the relevant objective or condition changed |
| useful | A declared evaluation or feedback criterion, not assumed from delivery |

Absence of a consumption receipt means unknown, not ignored. Acknowledgement is not proof of factual agreement, action, resolution, or usefulness. A later success is not automatically caused by the advice; attribution is recorded at its supported strength.

Required explainability queries are why_open, why_resolved, why_reopened, what_changed, why_this_audience, why_delivered, why_quiet, and what_evidence_is_missing. They return the applicable rule versions, evidence references, unresolved reasons, time/context, and operation receipts. Explanations are built from actual decisions; they must not invent a rationale after the fact.

Large receipt content can be stored once and referenced by immutable digest. Deletion or retention policies must preserve explicit unavailable reasons when exact reconstruction is no longer possible. A missing historical payload must not be represented as a fully replayable decision.

## 10. Replay and qualification episodes

Two separate historical queries are required: what the system knew as of time T, and what current evidence says was effective at time T. Replay binds a corpus manifest, availability cut, profiles, deterministic evaluator bindings or recorded judgments, and clock schedule.

Deterministic replay should reproduce allowed operations, assessments, reasons, and deliveries from recorded inputs. Provider re-execution is a separate experiment that may yield different answers. Sequential replay does not establish concurrency or real transport timing behavior; those need dedicated fault/race scenarios.

Core qualification includes complete episodes: duplicate evidence, a new occurrence, an unresolved gap, a changed association, qualified recovery, queued-advice invalidation, a real recurrence, an audience change, a deadline crossing, a cancelled run, and an uncertain delivery. It must also sample quiet decisions to detect missed developments.

Runtime acceptance requires durable restart, atomic conflict behavior, absence-watch invalidation, direct-control responsiveness, bounded costs, per-audience deduplication, and no mandatory ordinary closeout. Tests using synthetic domain profiles validate the shared mechanisms only. They do not claim measured Jev accuracy, validated civic authority rules, successful DIAT identity evaluation, or improved live OIL behavior.
