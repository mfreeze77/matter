# StateCivics monitoring and contextual alerts

Owner direction, October 27, 2026: Matter is the monitoring and alert membrane
for StateCivics. Candidate developments are assessed against the user's current
work and each client's context. A keyword hit is a candidate, not an automatic
intelligent alert. StateCivics interfaces can evolve to support the integration.
Its existing civic matter records and pages remain a separate implementation;
their shared name does not select the integration surface.

Current bounded checkpoint: a StateCivics feature branch has executed the
synthetic structured-input scenario through the existing replay and Matter
attention primitive, with observed in-app captures. See the
[runtime receipt and remaining limits](../validation/statecivics-monitoring-replay.md).
This exercises the monitoring membrane; civic source adaptation, learned
judgments and receiving deployment retain their separate tickets.

## Synthetic first scenarios

The [scenario pack](../../examples/civic/purpose-comparison/monitoring-scenarios.json)
defines three invented clients and four work contexts:

- A Google-like cloud company watching interoperability policy and procurement.
- A student-privacy special-interest coalition supporting consent and opposing
  mandatory biometrics, with provision-specific positions.
- A school district's IT procurement team.
- The same district's finance team, including a changed work assignment.

Twelve release checkpoints cover routine mentions, a draft, a hearing deadline,
a repeated notice, recommendation versus adoption, procurement, corrections,
context changes, a late correction, jurisdiction collisions, unavailable evidence
and cancellation. Each checkpoint names the expected treatment for every context.
Client positions are invented host-approved inputs. A source actor's reported
position remains separately cited; unknown is not neutral, and neither position
is a permanent label for an entire organization.

This is an illustrative planning fixture, not a runtime schema, a ready-to-load
KS-698 manifest, recorded model output or a qualification corpus. Its labels are
agent-authored expectations. The separate
[runtime-inputs file](../../examples/civic/purpose-comparison/runtime-inputs.json)
contains structured inputs without those expectations. Keep the expected section outside evaluator-visible
inputs. Delivery checkpoints describe observations the eventual test must make,
not receipts by themselves. The newer runtime checkpoint above records what
actually executed; its authored structured facts do not establish semantic extraction quality.

## Reuse the existing replay

Owner correction, October 27: this integration must run in the existing local
rehearsal **without a login**. KS-841's rehearsal already runs without sign-in
and excludes copied accounts/sessions. The older KS-698 native-admin console
requirements below describe the inspected implementation, not a requirement to
add authentication to rehearsal. Reuse its replay/runtime mechanisms through
rehearsal access; retain synthetic run isolation, cutoff fences and capture-only
delivery. Acceptance must exercise the scenario controls without credentials or
a login redirect. That browser check has not run yet.

Read-only inspection of StateCivics at `d28663cc0` found (the inspected replay
runtime, manifest, router, config and console files are unchanged from
`1f7011fd8`):

- KS-698's console is `/dashboard/admin/replay`. Play paces the same single-step
  operations used by Next; Pause stops scheduling and waits for the current step.
- `src/kansas_accountability/api/routers/historical_replay.py` exposes
  `/admin/replay` beneath the configured API prefix (`/api/v1` by default), and
  currently selects only `hb2560` and `hearing829` scenario directories.
- `core/config.py` defines `historical_replay_enabled` (default false),
  `historical_replay_instance_file` and `historical_replay_scenario_root`.
  The root must be an explicit absolute path. The older admin route additionally
  requires native-admin authority and its dedicated instance identity; setting a
  flag alone does not make that route usable in the no-login rehearsal.
- Catalog/runtime responses explicitly report `model_mode: unavailable`.
  The initial retained scenarios prove the factual detection path. They do not
  supply the new Matter assessment integration or these local-record scenarios.

Read-only Docker inventory found the existing `ks-rehearsal` services running,
with `ks-rehearsal-edge-1` publishing `127.0.0.1:8080`. A five-second GET of
`http://127.0.0.1:8080/dashboard/admin/replay` timed out. A presence check for
only the three replay configuration variables in the backend process returned
none; this does not rule out other configuration sources or prove instance
readiness. No environment file or credential was read, and no service or
configuration was changed. The candidate local route is identified; the installed
scenario root and usable instance remain unverified. Use the existing rehearsal
launcher and KS-698 owners to resolve them. Do not build a second timeline,
database, queue, source reader or notification system.

The first bridge should feed cutoff-visible releases and versioned host context
through Matter, then retain decisions and delivery receipts in the existing
inspectable sink. Start with a supported bill/hearing family; extend local
packages through their existing owners as the civic adapter becomes available.
Preserve distinct policy/procurement identities. Quieting an optional intelligent
interruption must not delete factual events, an explicit follow or review state.

## Later custom alert writer

The owner intends a short LLM call after JEV has reviewed and flagged relevant
details. Reuse StateCivics' existing enrichment and synthesis ownership, including
KS-704/705/706, rather than adding prose generation to Matter's neutral core.

The intended flow is source development, bounded JEV judgments, admitted
assessment and audience attention, optional deeper reading and custom wording,
then fresh authorized delivery. Unqualified JEV judgments remain shadow evidence;
a valid response or confidence value alone cannot admit an alert. Shared facts
and client consequences remain separate throughout.

Give the writer exact supported facts, source references, relevant qualifications,
current work/client context, the meaningful change and permitted next steps.
An optional deeper investigation uses the existing authorized read tools under
MAT-022 and, later, MAT-035's canonical prerequisites. Record new source evidence
and reassess it before using it to support an alert. The LLM cannot promote an
uncertain claim to fact or alter an admitted deadline, urgency or destination.

Retain writer input/output identity and citations. Recheck source, context,
assessment and permission freshness after asynchronous work and before delivery.
A failed writer leaves an explicit enrichment failure; supported factual delivery
continues under host policy. No empty or partial prose counts as a delivered
custom alert. LLM output remains proposed until the host's delivery gates admit it.

## Ticket coverage and completion boundary

[MAT-049](../../tickets/MAT-049.md) owns purpose/audience comparison and meaningful
change. This pack prepares its cases; MAT-049 remains planned and waits on
[MAT-048](../../tickets/MAT-048.md). Civic integration still follows
[MAT-046](../../tickets/MAT-046.md), crawler-owned [MAT-047](../../tickets/MAT-047.md),
then MAT-048. MAT-022, MAT-023 through MAT-025, and MAT-033 retain their distinct
investigation, projection, replay, qualification and shadow-family scopes.

KS-698 owns the existing replay mechanics; StateCivics owns its runtime admission,
context binding, synthesis and receiving acceptance. Existing KS-704 enrichment
and KS-1071 Matter mapping are reuse/planning anchors, not proof that this bridge
or the custom-alert writer is installed. No StateCivics or crawler edits are part
of this scenario preparation.

The separate installed walkthrough-schema lookup failure remains a validation
gap recorded in [live-roadmap](../validation/live-roadmap.md). Neither this pack,
checkout validation nor replay plans resolve installed-package behavior.

Completion of this preparation means a parseable scenario with coherent source,
context and expectation references, current ticket links and a reviewed handoff.
The newer receipt records the bounded structured-input runtime replay. Actual
JEV calls, writer calls, provider qualification, receiving-system acceptance and
external alert delivery remain **not run in this slice**.
Executed authoring checks and review limits are recorded in the
[preparation receipt](../validation/statecivics-monitoring-scenarios.md).
