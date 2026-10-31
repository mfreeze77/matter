# MAT-084: optional unqualified monitoring capture

Status: implementation candidate, **not frozen or receiving-accepted**. SDK
candidate `matter-foundation==0.1.0.dev16`; explicit wire
`monitoring-handoff/1.1.0`. KS-1124 must run the supplied recorded vectors in
its SDK image before the new contract is frozen. Keep the frozen 1.0 adapter
available per objective. No production delivery or provider qualification is
introduced. The consumer's deterministic 1.0 fallback uses approved objective
fields and the event only, never model-derived labels.

## Host installation and migration

Import the opt-in API from `matter.statecivics_capture`:
`MonitoringCapturePolicy`, `CaptureAdmissionService`, `AdmittedCaptureMonitoring`,
`admit_monitoring`, `CaptureAdmission`, `CaptureReuseEligibility`,
`capture_source_reading_eligibility`, `ObservedMonitoringCapture`,
`validate_capture_handoff`, `capture_refusal`, and `VERSION`.
`conveyed_capture_identity` is also exported there and in
`matter.statecivics_monitoring`. Call this shared function for the capture key;
do not copy its implementation. It is an identity, never permission to write.

Reuse the real host access/control/storage/receipt owners. Construct
`CaptureAdmissionService(storage, receipts=..., controls=..., clock=...,
capture_history=...)` with the same store and controls as the execution service.
No new database, sender or transport is installed. `install_policy(policy,
actor=..., authority=..., command_id=..., idempotency_key=...)` records an
immutable policy through the existing host control transaction and returns a
pinned reference. An authorized host must explicitly install it and grant its
output read access; browser JSON cannot do that.

Add `MonitoringHost.capture_service` (default `None`) and
`HostMonitoringState.capture_policy` (default `None`). The current host projection
includes the 1.1 `proposal_basis`. All existing ownership, owned watchlist **and
item**, real activity associations, lifecycle, pricing, evidence and context
checks remain mandatory. `source_finding` retains its original meaning.
The current policy pin must match the request. Missing configuration refuses
model capture; it does not silently fall back to a host rule.

Choose explicitly for each objective:

- 1.0: use the existing `AdmittedMonitoring` and frozen schema unchanged.
- 1.1 native: `proposal_basis = {"kind": "native_attention"}`. `project(...)`
  still requires a real native assessment and AttentionService decision.
- 1.1 study: `proposal_basis = {"kind": "unqualified_model_capture",
  "capture_policy": policy_pin, "source_reading": source_execution_or_null}`.
  Use `admit_monitoring(request, host=host, packet=prepared_packet)`, the existing
  guarded `execute(...)`, then `admit_capture(execution=outcome["execution"])`
  and `project_capture(admission=...)`. `handoff(result, capture=existing_sink)`
  keeps the existing atomic guard and unknown-outcome contract. The sink calls
  `require_current()` inside its write transaction and uses `assessment_key`
  (equal to `capture_key`) for idempotency. It must not send notifications.

Wire JSON is validated against the installed, self-contained
[1.1 candidate schema](../contracts/monitoring-handoff-v1.1.schema.json).
Do not decode 1.1 with a 1.0 decoder or coerce a null assessment into a native
reference. `admit_monitoring` selects the explicitly declared version; unknown
versions refuse.

## Explicit policy, no threshold defaults

A policy contains `schema_version: "1.1"`, `namespace`, `id`, `semantic_version`,
`precision` (the exact native `PrecisionProfile.value`, including rounding and
probability/score quantums), `questions` (the exact `monitoring_questions()` objective and novelty references),
`regions` for each question, `material_paths`, and `native_baseline` (null or an
explicit projection mapping). Each region requires decimal strings
`negative_maximum < positive_minimum`. Positive is at or above the upper bound;
negative is at or below the lower; the gap is **unknown**. Both current and original reused executions must match the declared precision
exactly. There are no SDK threshold defaults. Synthetic test values 0.8/0.2 are illustrations, not approved
study settings, calibrated accuracy or production thresholds.

`material_paths` are explicit JSON pointers into the authorized source finding's
`/body/`. Choose stable conveyed source facts, including any applicable deadline;
exclude execution IDs, probabilities, generated prose and timestamps that do not
represent new material. Missing selected material abstains. Material selection
is a host/profile decision, not inferred by the model. Objective and novelty
judgments remain separate; no multiplied importance score exists.

Monitoring admission additionally checks the exact logical command/initial
attempt, full stage binding, adapter/mode, actual committed allocation and original
dispatch byte/call/time envelope. It does not extend an expired provider
reservation or require a new model call just to inspect already recorded work.
A study result records `decision_basis.kind: "unqualified_model_capture"`, real
capture-admission, current/original execution and policy pins, and separate
positive/negative/unknown judgments. `assessment_reference` is null,
`qualification` is `unqualified`, `permitted_use` is `capture_only`, and
`consequential_use` is false. Ordinary positives can propose a digest; quiet
never calls the sink. A verified changed linked correction can propose a
correction even when ordinary relevance is unknown, following the core routing
precedence. No model answer becomes a supported source claim, qualified method,
human decision request, assessment or delivery milestone.

## One source reading, independent audience checks

The source-reading receipt must be an actual durably completed or reused/current whole-batch
execution of the existing four `civic_attention.source_questions()`, over the
same source packet (apart from its access snapshot). It cannot contain monitoring
or comparison context. Give this reader only common source material; an
execution whose protected read closure includes client-private context is not a
shareable source read. Post-hoc `record_stage_batch` observations do not prove
durable authorization before I/O and cannot enter this path. Cached aliases
retain the original execution and original token checks.

`capture_source_reading_eligibility(admitted, receipts=..., execution=...)`
returns a typed **unqualified, capture-only** eligibility after the recipient's
fresh access check. Each audience runs its own objective/novelty questions under
its own original token, intent and budget. The shared reading is included as
explicit unqualified diagnostics and a real execution parent. It is checked at
execution, admission, projection and capture; it is never reclassified as
qualified to obtain reuse. Native durable exact-command recovery and semantic
cache reuse remain distinct from another empirical trial.

## Actual captured baselines and consumer duties

Observed native baselines add `decision_basis: "native_attention"` and retain
their actual native assessment and host milestone. To compare native conveyed
material with study material, configure `native_baseline.material_contract` to
match that actual decision and `native_baseline.paths` to map each study material
path to its corresponding native material JSON pointer. No mapping is guessed.

Observed study baselines use `status: "observed_capture"`,
`decision_basis: "unqualified_model_capture"`, `assessment_reference: null`, and
a real `capture_admission_reference`. The trusted `capture_history` resolver
receives the baseline receipt, host binding and output access context. It must
read the **actual successful isolated capture row**, enforce current read and
ownership, and return `ObservedMonitoringCapture(receipt, admission_reference,
owner, candidate, material, material_contract, captured_at)`. Owner includes
user/workspace/client/intent. A wire DTO or model is not this authority. Return
nothing/raise when history is absent or unknown; never invent a native delivered
milestone. The SDK checks the real original admission/execution, source history,
material digest, subject/owner and capture time. The host also supplies
`baseline_compatible=False` when an edited purpose invalidates prior history.

Study history cannot be downgraded into 1.0's native-assessment baseline. Keep
such an objective on 1.1, or explicitly reconcile actual native history; do not
fabricate an assessment. New material or a linked correction survives feedback
on an older subject. Preference-only changes refresh output authorization and
can reuse still-current semantic work when the host separates semantic/output
contexts as in the existing adapter.

The host owns durable atomic duplicate suppression, capture receipts and unknown
outcomes across process restarts. An uncertain sink result must be reconciled
through that history before a new command; it is not absent history or permission
to resend. Exact admission retries recover the original record without calling
the provider. Current pause/revoke, source/context/policy edits and withdrawn
access withhold old output. Replay keeps evidence availability separate from the
current approved objective clock.

## Receiving gate and evidence

The pinned candidate package and receiving instructions are in the
[SDK handoff](statecivics-capture-sdk-handoff.md).
The recorded vectors and relevant checks are described in
[MAT-084 validation](../validation/MAT-084.md). They are synthetic component
conformance, not fresh JEV interpretation, a StateCivics receiving run, formal
MAT-040 qualification or production authorization. KS-1124 owns host mapping and
its image run; KS-1125 owns explanations/feedback; KS-1126 owns the two-objective
receiving rehearsal. Existing KS-1121 public-source work needs #26, while this
saved-objective path additionally needs #29 and the reviewed MAT-084 candidate.
The separate MAT-083 SQLite race and broader packaging backlog remain separate.
