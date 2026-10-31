# Unqualified monitoring capture: MAT-084 proposal

Status: **implementation candidate, not frozen**. Owner/KS-1124 approved
implementation of PR #31 at `ffdb9a4` on 2026-10-31. The current candidate targets
`matter-foundation==0.1.0.dev16` and opt-in `monitoring-handoff/1.1.0`, beside
unchanged frozen 1.0. Final API and validation evidence are maintained in the
[implementation handoff](../adapters/statecivics-capture.md) and
[validation receipt](../validation/MAT-084.md). The consumer must run the
recorded vectors in its SDK image before freeze. The proposal below records
intent; the implementation handoff describes actual candidate behavior.

## Confirmed gap and existing fallback

The merged `AdmittedMonitoring.execute()` already guards provider execution
through actual access, budgets and durable receipts. `project()` separately
requires a current native AttentionService decision and its actual assessment.
A probability or detached BatchResult cannot supply that assessment.
`SemanticQualificationService` can persist an explicitly unqualified admission;
without an applicable certificate it does not assign a qualified decision.
Those boundaries are intentional and remain intact.

StateCivics reports that KS-1124's first slice uses a genuinely deterministic
host rule over approved intent fields, with qualification `not_required`.
Model answers are unqualified notes beside it. This is a temporary host
assessment basis, not a claim that JEV drives the existing attention decision.
Do not substitute model-derived labels into that deterministic rule and retain
`not_required` as a shortcut. The new study path must say what it actually uses.

The bounded runtime extension is being verified; final consumer conformance and
contract freeze remain pending.

## Planned shared boundary

Version 1.0 stays byte-frozen, including its compatibility lock. It continues to
accept the existing native assessment/attention path. Version 1.1 is an explicit
opt-in with a new schema/vector inventory, never a decoder fallback. Wire
request data alone grants no study authority.

Proposed version 1.1 input difference: a `proposal_basis` discriminant selects
`native_attention` or `unqualified_model_capture`. The model branch pins an
immutable `capture_policy` approved/configured by the trusted host. That policy
binds exact monitoring objective/novelty question identities, precision and
separate positive/negative/abstention regions. No default threshold is approved
here; policy thresholds are study selection rules, not qualified accuracy claims.
Existing model, packet, purpose/audience/intent, control, cost and call/time/byte
bindings remain required.

Proposed result difference: `decision_basis` records the actual basis:

- `native_attention` retains a real `assessment_reference` and attention record.
- `unqualified_model_capture` has `assessment_reference: null` and exact
  `capture_admission_reference`, original/reuse execution references, question
  references, model binding and capture-policy pin. It is not a native
  AttentionService decision or a supported source assessment.

Both remain `qualification: unqualified`, `permitted_use: capture_only` and
explicitly `consequential_use: false`. Reasons, uncertainty, source citations,
coverage and consumed dependencies remain bounded and inspectable. No model
text becomes a new source citation or authorizes a destination.

The input baseline needs corresponding explicit provenance. A prior native
capture may retain its real assessment; a prior model study capture must resolve
its actual capture receipt, conveyed material and capture admission without
inventing an assessment or delivered milestone. Preserve user/workspace/client/
intent/subject/purpose applicability. Unknown capture stays unknown. The exact
1.1 baseline schema and mixed native/study compatibility vectors must be reviewed
before freeze; legacy 1.0 consumers are not silently upgraded.
StateCivics may retain its own study `IntentAssessment` row, but that host row
does not become a native Matter assessment reference. Its storage/decoder mapping
must preserve the new basis and nullable native reference explicitly.

## Planned SDK/host changes

Keep `HostMonitoringState.source_finding` and existing native context/candidate,
ownership/lifecycle/mute and pricing fields unchanged. Proposed addition:
`capture_policy: pinned_ref | None = None`, matched against trusted current host
state. A missing policy retains the old path and refuses the model-capture path.

The trusted `MonitoringHost` must also receive an explicitly installed capture
admission service/configuration over the same actual access, controls, receipts
and storage. It cannot be built from request JSON. Proposed additive methods on
the existing adapter are `admit_capture(...)` (actual receipt-backed admission)
and `project_capture(...)` (current unqualified study proposal). Names and exact
signatures remain draft until implementation review. Existing `project()` keeps
requiring an actual admitted native AttentionService decision.

`handoff()` must revalidate the selected branch and actual admission at capture,
preserving its current guard-in-sink contract, duplicate key and unknown-outcome
behavior. It must not reproject model proposals through the native `project()`
or manufacture a host assessment to satisfy that method.

## Composition and safeguards

Consume the actual MAT-030 receipt chain and registered unqualified semantic
admission. Validate the whole batch, exact numbers, question semantic identities,
resolved/requested model, packet/context, original command and original token.
Raw probabilities, detached or altered results, invalid sibling heads, failures
and unresolved outcomes cannot enter this path. Reuse refers to the original
physical execution and adds no trial or call.
The inspected native receipt cache supports explicitly unqualified reuse when
no qualified classifier is supplied. The study path
must not return `qualified` merely to gain a cache hit. Reuse needs an explicitly
typed capture-only eligibility decision under current access, or it must be
withheld; exact-command durable recovery remains separate. Preserve the existing
cache/receipt owners rather than adding a second cache.

Keep objective contribution and novelty separate. Study policy may select an
unqualified positive/negative or abstain; it cannot establish source truth,
neutral client position, recovery, permission or need for a human decision.
Incomplete evidence and unknown/failed judgments do not become confident
irrelevance or a generic question for the user.

Compose existing neutral mechanical constraints for source availability, current
purpose/audience, ownership, dispositions, actual baseline and linked correction.
Do not add a parallel attention engine or feed a synthetic supported assessment
to core decision helpers. Any shared neutral refactoring must preserve old
behavior and keep civic/JEV meaning in the optional adapter. The exact reuse
seam is an implementation-review item; current core behavior is not relaxed by
this proposal.

Use existing dependency registration/invalidation for source, context, policy,
disposition, execution/admission and actual capture history. Relevant edits or
revocation withhold stale output; preference-only changes refresh output guards
without rewriting shared facts or unnecessarily rerunning authorized semantics.
Keep current real permission/budget clocks separate from replay availability and
the reconstructed approved-intent clock.

Capture identity must derive from the versioned conveyed-material contract and
applicable subject/audience/objective/baseline, not execution IDs or probability
jitter. Exact repeats and reprints stay quiet. Actual linked corrections and
materially new deadlines can survive old handled feedback; model assertions alone
cannot establish a source-correction link. Preserve actual captures even after
later context edits, and never pretend they were delivery, reading or action.

The study admission/proposal must be rejected by normal consequential
assessment/publication/DeliveryService ports. Prove that through negative tests;
wire labels alone are not an enforcement boundary. The existing isolated sink
is the only allowed output, with real owned watchlist/item/activity associations
and an atomic currentness check. No production sender, new queue or new sink.

## Verification and StateCivics handoff

Reuse the existing synthetic two-audience scenario, real native controls/budgets/
receipts and no-login rehearsal/capture support. Change only the admitted model
answers to demonstrate positive, quiet and unknown behavior. Include sibling
failure, forged/cross-context receipts, duplicates/jitter, mixed actual baselines,
correction/deadline controls, partial coverage, edits/revocation and future-source
canaries. Verify legacy 1.0 unchanged and production ports refusing study objects.
Recorded conformance, fresh provider interpretation, receiving acceptance and
formal MAT-040 qualification remain separate receipts.

Only after implementation/freeze/review and installed-wheel checks should KS-1124
switch from its deterministic host rule. Matter supplies actual release/API/schema
and HostMonitoringState differences plus source/wheel hashes; StateCivics owns
its SDK image, dispatcher/capture mapping and KS-1126 receiving run. No new model
release is required merely to continue the current fallback. Workbench/state-intel
activation, dashboard interactions and the pilot's place/workspace/objectives
remain host/owner choices.

StateCivics reports KS-1121 merged at `86bbcc22a`, 220 SDK-backed replay passes,
clean skips without the optional SDK and 13,233 statewide passes with the same
failures as its baseline. Those are reported StateCivics receipts, not independent
Matter reruns or saved-objective model admission. The reported county-place 404
fix was reverted; the current study uses statewide Kansas. County runtime support
is outside this Matter ticket.

SQLite contention is already tracked as [MAT-083](../../tickets/MAT-083.md) in
PR #30, not a new blocker invented for this feature. StateCivics also reports the
race on pre-stack main; the exact baseline SHA/run was not supplied in this
handoff, so that observation is attributed rather than claimed as a new Matter
reproduction. MAT-084 does not depend on repairing MAT-083, grant production
readiness, or authorize a SQLite fix.

## Draft verification

Canonical render/check and validation pass with 84 tickets, 104 requirements,
107 existing schemas and three walkthroughs. Diff whitespace checks pass.
The two-pass ticket/index JSON review covered both selected files in 62.1s
with zero findings or warnings. Raw receipts are in gitignored
`data/validation/MAT-084-plan/`. No executable schema, SDK version, runtime,
provider call or StateCivics implementation was changed or behaviorally tested
by this planning change.
