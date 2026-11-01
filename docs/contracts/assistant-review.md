# Assistant review handoff 1.0 — MAT-088/089

Status: additive SDK candidate (`matter-foundation 0.1.0.dev19`), with Matter
software conformance separate from StateCivics receiving acceptance. Monitoring
1.0/1.1, `HostMonitoringState`, provider qualification and delivery wires do not
change. No numeric burst threshold or production activation is supplied here.

## Ownership and reuse

The existing host assistant performs the review. StateCivics' receiving entry is
`AssistantReviewService.review(user_id, intent_id, assessment_id, why)` on
`b87c6027f4e85cd77d4a8d0e2d65e151caf1ac5f`. Matter's differently namespaced
`matter.assistant_review.AssistantReviewService` supplies durable wake-up claims,
completion guards, pressure bookkeeping and pointer resolution around that call.
It does not construct an assistant, MCP server, database, retriever, queue,
notification sender or price policy. Existing ControlService, AccessService and
transactional storage own native permissions, source egress and receipts.

StateCivics owns client/objective lenses, evidence, assistant sessions, findings,
full feedback, reports and their ledgers. Matter stores canonical ID/digest
references and its own review/pressure/control state. It never persists resolved
host artifact bodies, conversational replies or full findings. Existing core
records are not migrated or deleted by this boundary.

## Portable values

The packaged [schema](../../schemas/assistant-review.schema.json) defines version
`1.0` messages. `ReviewRequest` and `ReviewResult` additionally enforce relational
constraints. Unknown fields, raw replies, unsupported versions, floating JSON
numbers and out-of-bound arrays are refused. JSON decimal values use strings.

A **lens** names `host`, `user_id`, `workspace_id`, nullable `client_id`,
`intent_id`, and approved `revision_id`. IDs use strings at this SDK boundary;
the host maps them to existing typed IDs. A changed approved revision is a new
selection, not silent rebinding of old research. A **host pointer** is
`{host, kind, id, digest}`. Its kind is evidence, judgment, review, session,
finding, report, conveyed, feedback, rule or control. Identity is host-scoped.

A **request** contains:

- exact lens, native matter pin and declared native dependency pins;
- native audience and actual assistant-provider component references, checked
  against MAT-072 egress; a grant for a different provider is insufficient;
- host assessment/judgment pointer and the original `host_control` pointer;
- host-selected contributions, each with evidence pointer, provenance `lineage`
  and `material_digest`; use public `pressure_contribution(artifact, lineage=...)`;
- optional ledger pointer snapshot, source-availability `as_of`, explicit
  `limits.max_tool_calls`, `limits.timeout_ms`, `limits.max_reads` and
  `limits.max_bytes`, plus explicit `limits.cost_policy: host_managed`;
- one or both `trigger_routes` (`immediate`, `accumulation`) and a short
  `reason_code`. This is an internal wake-up reason, not an alert body.

The host owns decisive/cumulative trigger selection and correlated-source
lineage. Matter does not count keywords, add model probabilities, select a
threshold, or certify that host-declared lineages are independently sourced.
Source content is canonicalized before computing the contribution material
identity. Reprints with the same lineage/material cannot rebuild cleared
pressure; changed source material can request a fresh review even in the same
lineage. A later fact may change the meaning of earlier quiet context.

`ReviewRequest.wake_id` binds lens, native semantic inputs, assessment, selected
contributions and exact ledger references. Array order for set-like inputs,
wrapper time, reason wording, call-limit renewal and immediate versus cumulative
routing cannot produce another wake over the same basis. A second route does
not authorize a second review. Control renewal itself does not create a wake.

## Installed host port and actual controls

`ReviewHost(binding, require_current, require_read, resolve)` is constructed by
the authenticated application, never from wire fields or a model answer.

- Guards receive `(request, references, as_of)`. **Return None on success and
  raise on refusal**; booleans are not accepted as grants.
- `require_current` validates the real owner/workspace/client/objective mapping,
  approval revision, actual native matter/context/audience/provider binding,
  active account/client/intent, source/evidence currentness, access, assistant
  and tool egress, and actual configured per-review limits. It compares the
  original host-control pointer against current lifecycle history. A boolean
  active check alone misses a pause/resume during a call.
- `require_read` authorizes historical metadata under **present** rights and the
  requested availability cut. Historical access is not permission to reuse it
  for a new evaluation. The full source/parent closure remains protected.
- `resolve(lens, pointer, as_of)` returns the exact `host_artifact` projection or
  refuses; there is no search/latest-version fallback. The SDK validates its
  lens, kind, digest, availability, labels and transitive citation/derivation
  closure, with repeat access checks and bounded cycles/bytes/counts.

StateCivics can reference its append-only `watch_intent_controls` history for the
control pointer; no second intent-control database is needed. The host must
also keep original native control tokens and pins. Matter checks them inside
its write transaction. Source/data and permission checks do not become cached
just because schemas or digests were checked earlier.

Host guards/readers run outside the Matter write transaction. There is no
transaction spanning the host Postgres database and Matter SQLite. The host
must recheck actual current controls in its own transaction before linking a
result or creating any later user output. A successful local SDK finish is not
a claim of distributed serializability or production delivery permission.

## Claim, call, complete

1. Build the request from existing approved host state. Capture an original
   native `assessment` control token and MAT-072 access context covering the
   actual native matter/dependencies/audience/provider.
2. Call `record_pressure(request, token=..., access_context=..., command_id=...)`.
   IDs are stable per host command. Changed content under a reused command ID
   conflicts. The store retains pointer history, one pending slot per lineage,
   and consumed material identities. No score/decay/retention formula is added.
3. Call `claim(request, token=..., access_context=...)`. It returns
   `(acquired, attempt_record)`. **Only acquired=True permits host execution.**
   A refused local transaction remains a recorded refusal; a caller may make a
   fresh local preparation while retaining the original semantic token. This
   never repeats an assistant call. A stale competing preparation may refuse; never interpret refusal as an
   invitation to call the assistant. The existing store arbitrates real handles. One active review per lens
   serializes overlapping wakes; new contributions remain pending.
4. Outside the Matter transaction, call the existing host review method once.
   Pass the real user/intent/assessment mapping and rendered reason; bound it
   to this `wake_id`. The host enforces the requested time/tool ceilings. Async
   hosts can await the existing service between claim and complete. Synchronous
   hosts may use `execute(..., reviewer=callback)`; it cannot preempt arbitrary
   Python callbacks and is not a replacement for transport limits.
5. Persist the actual host review result and exact reviewed inputs, then call
   `complete(request, result, token=..., access_context=...)`. Completed output
   must match the persisted host artifact's wake, status, proposal, reviewed
   source pointers and actual host-approved rule-change references.

A started claim after a crash is **outcome unknown**. The assistant may have run;
there is no automatic takeover or blind resend. Unknown work keeps the lens
blocked for explicit reconciliation rather than launching another review in the
same session. `inspect(...)` exposes that
state honestly. A callback exception produces unknown without leaking exception
text. An invalid result leaves the claim unresolved. Reconciliation/retry of
unknown work requires a separate explicit host decision; quota renewal or a new
wrapper must not bypass it.

## Completion and pressure

The result status is `completed`, `stopped`, `failed` or `unknown`. A completed
result has a proposal (`quiet`, `digest`, `report`, `alert`), exact review/session
pointers, the actual subset of requested evidence reviewed, optional host ledger
snapshot, and host-approved rule-change pointers. The host's canonical review
projection must bind these fields and the wake ID to the actual stored review.
Do not hash a model-declared success and call it a host-verified result.

A non-completed result has no proposal, reviewed-set reset, ledger update,
rule-change application or review/session pointers. A host can retain its own
stopped/failed review record and later expose it through an authorized ledger;
this does not make the failed attempt quiet.

After both quiet and alert completion, the same Matter transaction clears only
covered lineage/material contributions. Concurrent new/changed evidence, other
lenses and unreviewed material remain pending. Old pointer/control histories
remain available. Native or host currentness loss prevents completion from
clearing pressure. Exact completion replay cannot clear later arrivals twice.

No reset declares a matter resolved, the user informed, evidence read or the
client's purpose changed. Rule-change pointers name actual authorized host
updates; the SDK never executes model-directed writes or modifies approved
intent, recipients, permissions or budgets on its own.

## Ledger reuse without copying memory

The snapshot has four primary lists: `judgments`, `reviews`, `conveyed`,
`feedback`; `findings` is derived context associated with reviews. All are exact
host pointers under one lens and knowledge cut. A changed, missing, unavailable,
foreign or revoked record cannot be guessed or silently rebound.

The host artifact projection contains lens, availability, classification,
original citations, derivation parents, explicit `communication_state` and
host-owned `content`. Use `host_artifact_reference(artifact)` to compute its exact
projection reference. The digest covers identity, lens and all provenance, not
just its text. No process-local cache can override current read authorization.

Classifications distinguish source quote/fact, JEV judgment, interpretation,
user feedback, communication, review, session, rule and host control. Cited
findings and judgments retain original sources; interpretations do not become
supported claims or independent corroboration. A source and five summaries
resolve once per exact pointer, with their provenance intact.

Communication state is explicit: `never_communicated`, `report_prepared`,
`capture_unknown`, `observed_capture`, `actually_conveyed`, `read`, or `acted`.
Only communication-class artifacts have a non-null value. Neither an observed
study capture nor a proposed report is silently promoted to human receipt/read.
The host must bind each state to its actual receipts; feedback never rewrites
source truth or becomes global training.

`resolve_ledger(request, token=..., access_context=...)` returns transient,
authorized projections for existing host packet construction. It sends nothing
and stores no bodies. Native rules/source packets still require their existing
MAT-028/072 provider-egress admission; do not label derived context as source
facts or count it as independent evidence. Roots outside the bound request are
refused; transitive parents are verified under the same budget and access.

## Receiving slice and limitations

StateCivics slice 2 owns the adapter around its existing async review method,
actual canonical ledger/artifact/control views, per-wake/result persistence,
exact reviewed-set provenance from real reads, and host-transaction currentness.
Its review engine alone does not yet supply every field of this SDK contract.
A source-availability cut must also reach the exact readers used inside the
review; the four-argument review entry point does not itself prove replay cuts.
Refuse a replay that cannot enforce them instead of reading future documents.

Slice 3 owns evidence cards, Report Studio and prepared report/notice mapping.
Use the county report claim-before-send ledger when authorized later; never
forward raw model replies. KS-1126 must exercise the connected run with actual
assistant/tool receipts, both flags on and all output unsent. Authored vectors,
software checks, actual interpretation and formal qualification remain distinct.

Threshold selection, findings admission/retention, visible host experience and
pilot policy remain with their recorded host/owner decisions. This SDK adds no
threshold defaults, new spend ceiling, forced notification or production flag.
The installed walkthrough-schema gap and MAT-083 concurrency investigation
remain separate from this review boundary.
