# Saved-objective monitoring adapter (MAT-082)

The optional `matter.statecivics_monitoring` module composes existing MAT-072
access, MAT-028 packets, MAT-030 execution receipts and MAT-019 current attention.
The neutral core and provider transport are unchanged. It implements the frozen
`monitoring-handoff/1.0.0` boundary; it does not supply the missing StateCivics
ORM/API mapping, host control service or production provider configuration.

## Host setup and flow

1. The authenticated host constructs `MonitoringHost` with its fixed user /
   workspace / optional client / place binding, actual AccessService/AccessContext,
   current read factory, current-state resolver, host clock and AttentionService.
   JSON and model output cannot construct this trusted host configuration.
   For preference-only semantic reuse the host can supply a narrower semantic
   AccessService/AccessContext and a separate `output_access` /
   `output_access_context` containing the preference. Both use the same controls
   and storage scope. Output guards still cover the current preference; the
   semantic boundary cannot gain grants by changing delivery preferences.
2. The resolver returns `HostMonitoringState`: approved current projection,
   actual candidate, exact native context pointers, lifecycle/mute/ownership
   results, verified budget/price reservation and source finding. The projection
   names the original command's selected context clock; it is not rewritten to
   a new `now()` at every guard. Its source manifest, permissions and actual
   capture associations must come from real host controls/records. Price values
   must come from current host pricing/reservation, not caller guesses. Those
   are StateCivics work, not fake production defaults supplied by this module.
3. Prepare a real MAT-028 source packet with that access context and call
   `AdmittedMonitoring(request, host=host, packet=packet)`. Draft/paused/revoked,
   missing/foreign/muted capture, mismatched current versions, unavailable source,
   wrong candidate and unresolved prior outcome refuse before provider I/O.
   Declared correction references must be actual ancestors along persisted
   `supersedes` edges from the bound claim, source finding or selected sources;
   readable unrelated records and self-links do not establish correction.
   Traversal is bounded at 128 ancestors, checks current access and subject/type
   compatibility, and excludes observations unavailable at the source cutoff.
   Catch boundary errors with `monitoring_refusal(error, request_id=validated_id)`;
   it produces the frozen bounded refusal, maps missing/unavailable native reads,
   preserves cancellation/budget/currentness distinctions, and never copies raw
   exception details or denied references. Invalid correlation stays null with a
   structural refusal. Do not expose raw privileged storage exceptions over HTTP.
4. `audience_packet()` preserves the source selection and cutoff and attaches an
   allowlisted approved intent plus verified prior conveyed material. It uses an
   explicit separate context clock, permitting a reconstructed current objective
   against older source evidence without forging historical preference or adding
   later source bytes. Source-only work continues to use the unmodified source
   packet and existing civic source families. Contacts, unrelated client notes,
   identity/control tokens, capture IDs and expected labels are not selected into
   the audience context. Context grants still protect the entire prepared state.
   Delivery preferences are output inputs, excluded from semantic state; the
   exact semantic components and current egress grant remain part of reuse.
5. `monitoring_questions()` reuses MAT-034 objective/novelty instructions and
   criteria, under distinct civic question identities and an explicitly different
   current-intent input binding. This transfers no provider qualification.
   Render through existing `render_question`; build an explicit-model Batch.
6. `execute()` routes through the supplied actual ExecutionReceiptStore and its
   committed BudgetService allocation, then actual AccessService.dispatch before
   and after I/O. It checks model/question/adapter bindings and call/time/byte/
   host-price ceilings. Exact attempts retain MAT-030's durable claims/results;
   an unresolved attempt is never automatically resent. A changed body under the
   same logical key is a conflict. No read transaction spans transport I/O.
   The native attempt pointer distinguishes exact recovery from new work. A
   deadline that has elapsed, an expired dispatch allocation or an unavailable
   executor cannot turn an already-started attempt into a fresh zero-send
   refusal. Native exact-context/digest checks still decide recovery; a different
   body cannot borrow that branch. Recorded cancellation requires a new command
   identity after resume. New work needs its own applicable committed allocation
   with the identical original control token; no token is renewed here.
   The existing stage parent-trace field binds the full command to the durable
   request; the native semantic cache deliberately excludes that trace. This
   permits a new output command to reuse identical authorized semantics without
   creating a parallel cache or weakening exact-command conflict detection.
   A host-only edit after a received response withholds the old output after the
   durable attempt is recorded; it does not erase an observed response. A known
   host cancellation before transport records cancellation, while a failed
   completion write after transport remains unknown. Egress revocation retains
   the existing access service's post-I/O gate.
7. The host's existing registered profile/rules/family admission and assessment
   pipeline persists the source finding and private audience assessment. This
   module does not turn a valid probability into a supported source claim or
   qualified judgment. Use the actual admitted native AttentionService decision.
   `project()` requires its current assessment, applicable source references,
   exact purpose/audience, consumed context/disposition dependencies and current
   access. It returns only an unqualified,
   capture-only proposal with actual references and bounded reasons/citations.
   The actual assessment's selected sources must match this packet, and its
   observation dependencies must be available by this source cutoff. A current
   assessment cannot smuggle later evidence into an earlier replay prefix.
8. `handoff()` accepts only that unchanged real projection after fresh core/host
   guards, and passes the existing sink explicit in-app channels and a material /
   audience / objective assessment key. A quiet result never calls the sink. The
   sink must recheck the supplied guard within its own authorized write boundary
   and enforce the key using existing capture deduplication. It must be an
   isolated capture implementation, not production notification delivery.
   A propagated guard refusal before any guard has passed remains its original
   refusal. Once a guard has passed, a later failure can follow a partial write
   and remains unknown. An opaque
   write exception, skipped guard or swallowed guard refusal remains unknown;
   none is reported as a verified capture. The callback still owns atomicity:
   this Python boundary cannot prevent a faulty privileged sink from writing.
   The adapter never fabricates a receipt or advances observed history from a
   proposed/queued/failed output.

There is no new client store, retriever, discovery daemon, permission engine,
queue or delivery implementation. The host dispatches candidate changes from its
existing event/candidate/absence watches, including newly eligible real records;
the adapter consumes explicitly authorized candidates without requiring an exact
follow or a fake bill identity. Native context templates may have empty
`applies_to` only when the host enforces the approved one-place/project scope;
that declaration does not grant access to arbitrary records.

## Baselines, edits and capture outcomes

Host history supplies the exact applicable output receipt and material digest,
not an assessment that was never captured. Native MAT-019 producer/milestone /
audience/purpose checks and present source-history access protect model-facing
material. An unknown outcome is not empty history. The wire keeps observed
capture and observed delivery distinct; the host must preserve the actual
channel/producer outcome when adapting an actual capture row to its admitted
native output-milestone record. A native milestone category alone does not
establish that a user received, read or acted on an alert. StateCivics capture-row
conversion and receiving proof remain KS-1124/1126 work.

Scoped dispositions use existing definitions/control pointers, not an intent-wide
handled flag. A new linked correction or deadline must not inherit an old blanket
handled result. Relevant context/source/permission changes cause refusal rather
than silently renewing original work. Preference-only edits refresh output guards;
shared source bytes/findings remain unchanged. A current historical explanation
is not authority to dispatch a new result.

## Evidence and limits

The tests use real SQLite intake, contexts, claims, access controls, budget
reservations, durable execution attempts and native attention decisions. Host
ownership/lifecycle projections and provider probabilities are authored synthetic
fixtures. Their declared synthetic clock is separate from the wall-stamped legacy
fixture creation receipts. They are software conformance, not actual JEV source
interpretation or accuracy measurements. Capture callback checks are not the
StateCivics AlertPlanner receiving run. Exact executed checks and unresolved AC
coverage are in `docs/validation/dashboard-matter-handoff.md`.

The source-only civic profiles, TypeSafe/JEV transport, existing no-login
rehearsal and capture sink remain the reuse targets. KS-1122 owns the saved host
scope mapping (and KS-701 acceptance); KS-1124 owns actual dispatch/receipt mapping;
KS-1126 owns the two actual saved-objective receiving run; KS-1127 owns incoming
live shadow use. PR #26 / SDK rebuild / KS-1121 gates still apply on that side.
MAT-040 qualification, production alert rollout and the custom writer are separate.

The [pinned SDK handoff](statecivics-sdk-handoff.md) distinguishes the #26-only
KS-1121 package from the #29 saved-objective package, records exact source/wheel
hashes, and lists host configuration and installed-check evidence. Neither
candidate is a merged or deployed release without the separate owner/host steps.
