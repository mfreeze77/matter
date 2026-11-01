# StateCivics KS-1125: explanations and scoped feedback

Status: **historical SDK seam handoff**. StateCivics KS-1125 has since merged;
it records host feedback rather than committing native dispositions. The
[current review/ledger handoff](statecivics-assistant-review.md) carries that
feedback by reference. Earlier commands below describe the native SDK option,
not what KS-1125 implemented.
This handoff does not implement StateCivics, run its UI, change a frozen wire
contract, or complete KS-1125/KS-1150.

## Pinned basis

- Matter planning base: `6e13925eddf0e0fced76d29a91ed65b7dbce5e53`.
- Existing SDK: `0.1.0.dev18`, runtime commit
  `79e5e04bdd7bb18e14dae40750e6f4658401d22c`; identities and installed checks
  are in [MAT-087's receipt](../validation/MAT-087.md).
- Host source snapshot inspected read-only: StateCivics main
  `e8c2ce70ee548af475e1354416b6fbd3b9e7eb58`, KS-1125 and KS-1150.
  `services/matter_monitoring_pipeline.py` still builds `"dispositions": []`.
  Earlier KS-1125 text describing an unmerged Matter stack is historical, not
  a current prerequisite. No StateCivics files were changed here.
- Governing semantics: [monitoring decision 0002](../decisions/0002-monitoring-handoff.md),
  [contexts and dispositions](../contexts.md), and the frozen
  [monitoring adapter](statecivics-monitoring.md). Native 1.0 and opt-in unqualified
  capture-only 1.1 remain available with their existing meanings.

## Existing public control path

`matter.dispositions` exports `DispositionDefinition`, `DispositionService`,
`disposition_ref` and `disposition_scope_ref`. Use the service over the same
native store and control owner that back the admitted monitoring bridge:

1. Build a valid definition bound to the exact matter, purpose and audience
   versions/context pins, exact subject pin, effective interval and status.
2. Call `DispositionService.prepare(definition, command_id=..., idempotency_key=...,
   actor=..., authority=..., previous=...)` with real host control authority.
3. Call **`commit(prepared_command)`**; it rechecks control/read dependencies and
   preserves exact retry semantics. Do not invent an `apply()` API or treat a
   browser/model JSON declaration as a committed disposition.
4. Read through `read(read_token, reference, at=...)` under current authority.
   Supply the actual committed current projection pin in trusted host state and
   the next monitoring request's `dispositions` list. An ID without its current
   digest/control/context linkage is insufficient.

Kinds are **acknowledgement, deferral, rejection, decision**. A deferral requires
an explicit known end time. Only `decision` carries a non-null decision value.
`rejection` can name an association proposal or projection; it cannot be used
as an arbitrary rejection of a source claim. See
[`DispositionDefinition` and `DispositionService`](../../src/matter/dispositions.py).

Undo is a new authorized control transition for the same exact slot, retaining
the prior pin and marking the definition withdrawn; it is not deletion of the
old event. Normal context changes still require the approved host control path.

## Feedback meaning and subject selection

- **Already handled:** acknowledge the exact contribution/material and context,
  not the entire bill, every later source version, another client, or all future
  alerts. Acknowledgement is not agreement, repair, factual correction, a new
  send receipt or lifecycle resolution.
- **Defer:** use only an explicitly chosen time/checkpoint. Do not add a hidden
  expiry to other feedback or silently convert quiet into deferral.
- **Irrelevant / wrong scope / wrong position:** choose a valid scoped
  disposition or an explicit approved intent edit. Do not overwrite source
  truth, infer neutral from unknown, or force every UI label into `rejection`.
- **Suspected source error:** preserve original evidence and initiate the host
  review/correction path. A user's suspicion is not a verified source correction.
- **Undo:** preserve feedback history and apply the new current control state;
  subsequent evaluation must use the new pins and withhold obsolete pending work.

The host must choose real existing subject records appropriate to each result.
A native 1.0 assessment/contribution and a 1.1 study source-finding/capture
projection are different artifacts. Do not manufacture a native assessment for
1.1, whose `assessment_reference` remains null. The exact UI-label/subject matrix
and host persistence/identity mapping need receiving tests; this document does
not claim that a universal mapping has been implemented.

The adapter checks current pins, actual `disposition-current` records and their
control lineage, matching matter/purpose/audience, and access to the subject
([admission guards](../../src/matter/statecivics_monitoring.py)). The 1.1 capture
path applies an active disposition to the exact source-finding, or to unchanged
material; changed unrelated material is not globally muted
([capture routing](../../src/matter/statecivics_capture.py)). Corrections and new
deadlines require explicit receiving coverage as described below.

## Explain the actual outcome

Use `matter.queries.QueryService.project(...)` for its supported native view and
explanation history with actual actor/authority and current access context.
It preserves source/citation and context dependencies, availability, uncertainty,
attention and delivery provenance. See [query implementation](../../src/matter/queries.py)
and [query checks](../../tests/integration/test_explanation_queries.py).

For 1.1, explain the guarded study result and actual capture-admission/host
assessment provenance. Keep the unqualified label, original citations, reason
codes, actual context versions and capture status. `QueryService` is not a
promise of a native semantic assessment for a study proposal. If host integration
finds a missing read surface, retain a concrete failing case for Matter instead
of filling it with fabricated assessment or delivery state.

Distinguish shown/captured, quiet, corrected, stale/withheld, unavailable,
failed, and unknown. No capture is not automatically irrelevance. Unknown
provider or capture/delivery outcome is not a completed quiet decision and must
not trigger a blind retry or a fabricated success. Actually conveyed material,
prepared reports, internal assistant review, read and handled remain separate.

## KS-1150 ledger ownership

KS-1125 supplies scoped user feedback, the fourth ledger input alongside JEV
judgments, assistant reviews and actually conveyed output. StateCivics owns the
assistant, client lens, evidence, session history, findings, reports and full
user notes. Matter keeps exact host pointers and its own disposition, pressure,
baseline and receipt state. Later reads require current scope/access; pointers
are not grants. New assistant memory bodies should not be copied into Matter.

KS-1150 output uses the county report's `alert_deliveries` claim-before-send
pattern and stored-report notice, not the hearing broadcast log or raw model
reply. One logical review session per lens needs rollover/limits below the
configured 300-message / 3,000,000-token caps. These host tasks are still planned;
no live output is enabled here. The five owner decisions remain open in the
[bubble review plan](../plans/assistant-bubble-review.md#five-owner-decisions-remain-open).

## Verification actually run

On the Matter planning base, with the existing local SDK and synthetic fixtures:

```bash
PYTHONPATH=tests .venv/bin/python -m unittest \
  unit.test_context_scopes \
  integration.test_explanation_queries \
  unit.test_monitoring_capture_policy.CaptureMaterialRoutingTests \
  integration.test_monitoring_handoff.MonitoringHandoffTests.test_scoped_old_acknowledgement_does_not_silence_a_new_typed_deadline \
  -v
```

**26 tests passed in 47.015s.** Log retained locally at
`data/validation/ks1150-alignment/ks1125-sdk-checks.log`. This includes scoped
context/control feedback checks, native query explanations, an old-handled/new
deadline or linked-correction routing check, and native old-ack/new-deadline
integration. It is existing SDK evidence, not a StateCivics receiving run,
assistant/MCP execution, live JEV interpretation, performance benchmark or
MAT-040 qualification. No full suite was run for this documentation-only change.

## Receiving completion still needed

StateCivics owns the UI/control and database wiring, actual dispositions in
trusted host state, explanations on both native/study paths, and its acceptance:

- Two client/objective contexts over a source; feedback cannot leak across them.
- Already-handled then exact duplicate stays quiet; a genuine linked correction
  and new deadline are not swallowed by old feedback.
- Undo, explicit deferral expiry, objective edit/pause/revoke and access loss
  refresh or withhold pending/in-flight work under current pins.
- Quiet, unknown, failed and corrected explanations retain real reasons,
  citations and provenance without declaring unqualified output official.
- Exact feedback retry writes no duplicate transition; an unknown outcome follows
  actual reconciliation, not automatic redispatch.

KS-1126's connected rehearsal follows this explanation/feedback wiring. Existing
no-login isolated rehearsal and capture sinks should be reused. Pilot identity,
thresholds, visibility, prepared-without-notifying behavior, retention and budget
are not selected by these checks. No crawler delivery or broad-source capability
is established by this handoff.
