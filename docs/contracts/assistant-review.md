# Assistant review handoff 1.0 — MAT-088/089

Status: additive SDK candidate (`matter-foundation 0.1.0.dev19`), with Matter
software conformance separate from StateCivics receiving acceptance. Monitoring
1.0/1.1, `HostMonitoringState`, provider qualification and delivery wires do not
change. No numeric burst threshold or production activation is supplied here.

## Ownership and reuse

The existing host assistant performs the review. StateCivics' receiving entry is
`AssistantReviewService.review(*, user_id, intent_id, assessment_id, why, wake_key=...)` on
`f87d509c2ff2b132628f7c6e45c27f16559ad205`. Matter's differently namespaced
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
- host-selected contributions, each with evidence pointer, provenance `lineage`, stable source `material_version`
  and `material_digest`; use public `pressure_contribution(artifact, lineage=..., material_version=...)`;
- optional ledger pointer snapshot, source-availability `as_of`, explicit
  `limits.max_tool_calls`, `limits.timeout_ms`, `limits.max_reads` and
  `limits.max_bytes`, plus explicit `limits.cost_policy: host_managed`;
- one or both `trigger_routes` (`immediate`, `accumulation`) and a short
  `reason_code`. This is an internal wake-up reason, not an alert body.

The host owns decisive/cumulative trigger selection and correlated-source
lineage. Matter does not count keywords, add model probabilities, select a
threshold, or certify that host-declared lineages are independently sourced.
Source content is canonicalized before computing the contribution material
identity. Reprints retain the original material version and cannot rebuild cleared
pressure. Genuine source revisions use new material versions, including a later
reversion to earlier wording. Different versions remain pending together in one
provenance lineage: a late reprint cannot evict an unreviewed correction. Same
version with contradictory material is a source-identity conflict, including
a version already consumed by a completed review. The host uses
its existing canonical source-version identity, never a delivery wrapper ID. A later fact may change the meaning of earlier quiet context.

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
   The native `command_id` identifies one registration attempt; persist it for
   exact/uncertain retries. Changed content under a reused ID conflicts. The store retains pointer history, pending source versions grouped by lineage,
   and consumed material-version identities. Pressure is separate per native matter
   and approved lens revision; a logical objective/lens lock spans revisions and
   matters so its existing assistant session never runs overlapping reviews. No
   score/decay/retention formula is added. A pressure window holds at most 128
   pending versions and its encoded state remains within the 256 KiB wire bound;
   overflow is E_BUDGET_EXHAUSTED without changing pressure, never a silent
   drop or an accepted unreadable window. A commit-time refusal may still
   produce its immutable failure receipt. Keep the
   unaccepted contribution in the host ledger. After draining completed work,
   retry a bounded batch with a **fresh native registration command ID** if the
   earlier attempt has a recorded refusal. Exact retries of a durable refusal
   keep returning that refusal; they never rewrite history. Keep the same
   semantic request/wake identity. A fresh local ID is not permission to rerun
   an assistant or bypass unknown work; uncertain attempts retain their IDs
   until the existing receipt establishes what happened.
3. Call `claim(request, token=..., access_context=...)`. It returns
   `(acquired, attempt_record)`. **Only acquired=True permits host execution.**
   A refused local transaction remains a recorded refusal; a caller may make a
   fresh local preparation while retaining the original semantic token. This
   never repeats an assistant call. A stale competing preparation may refuse; never interpret refusal as an
   invitation to call the assistant. The existing store arbitrates real handles. One active review per lens
   serializes overlapping wakes; new contributions remain pending.
4. Outside the Matter transaction, call the existing host review method once.
   Pass the real user/intent/assessment mapping and rendered reason, with
   `wake_key=request.wake_id`. The host returns the prior review on a repeated
   key; this never authorizes a second turn or skips present read guards. The host enforces the requested time/tool ceilings. Async
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
text. An invalid result leaves the claim unresolved. A new wrapper or quota never bypasses unknown work. The SDK
`reconcile(request, witness, actor=..., authority=..., access_context=...,
command_id=...)` is an explicit correction-authorized operator control: a
verified host control projection must name the wake, attest `inflight: false`,
and record `resolution` as observed_completion, not_started, stopped or failed.
It releases the lens lock without clearing pressure, admitting a quiet proposal
or calling the assistant. The original wake stays non-dispatchable. StateCivics
owns the actual lookup/proof and operator UI; inventing a witness is forbidden.
Reconciliation uses the operator control lane, not a new assessment/work token.
Current read and correction capability, including active correction denials,
are checked over the full prepared command, including transitive source parents;
cancellation or a revised
native pin does not prevent recording recovery, and recovery never resumes work.

## Completion and pressure

The result status is `completed`, `stopped`, `failed` or `unknown`. A completed
result has a proposal (`quiet`, `digest`, `report`, `alert`), exact review/session
pointers, the actual subset of requested evidence reviewed, optional host ledger
snapshot, and host-approved rule-change pointers. The host's canonical review
projection must bind these fields and the wake ID to the actual stored review.
Its content includes `wake_id`, `status`, `proposal`, `reviewed`, `rule_changes`,
the exact `session` pointer, and `ledger_binding`. Compute the latter with
`review_ledger_digest(ledger, review_reference)`: it excludes only that review
identity from the review list to avoid a circular self-digest; every other
selected reference, lens and availability cut remains bound.
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
review; the review entry point does not itself prove replay cuts.
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

## Bounded selections and metadata reads

Each request has at most 64 contributions and binds at most 96 distinct root
host pointers, also within its declared
input artifact-read budget; the source/ledger closure is verified before host execution. Ledger
snapshots are bounded selections, not a growing dump of all lens history. Results
also have a 96-root bound. Result/witness integrity verification has a separate
fixed 256-artifact / 1 MiB aggregate ceiling, not the assistant's tool-read budget.
Individual wire/artifact values remain capped at 256 KiB. An unsupported/oversize
result refuses without clearing pressure; use a valid bounded host projection
or explicit reconciliation, never a second assistant call.

`pressure()` is present-authorized pointer metadata/history for one lens/matter,
not a fresh model packet. It permits superseded source history under current
READ rights and checks host pointer-read permission at the current host clock,
without rereading every accepted body. Historical rows retain their original
native pin selection and check its pins against the present reader's grants,
actor and authority, never the writer's grants. Metadata uses local READ
(`provider=None`), so a retired assistant provider need not retain egress
permission just for inspection. One current
request need not pretend multiple versions are one input snapshot. This keeps a
large accepted backlog and superseded contributions inspectable without treating
metadata as a source packet.
Reusing any of those pointers still requires the request cut, current-use guards
and declared packet budgets.

For operator/identity rotation, `history_context(request, actor=..., authority=...,
audience=...)` admits the exact historical native pins under present local READ.
It works under cancellation and after native revision, does not renew assessment
work and cannot be used as a provider packet. Pass the resulting access context
to `inspect`, `history` or `reconcile` (and its read token to `pressure`). Each
metadata call binds that context to the actual reader; a borrowed writer context
is refused. The host still authenticates the actual caller/audience selection
and enforces lens ownership in `require_read`.

Accumulated pressure can span earlier native selections. `pressure`, `history`
and pressure append/retry returns check all retained native selections under the
current reader, not only the newest write's pins. These metadata reads fail
closed if any retained selection is no longer readable; a new write never hides
old protected contributions. Equivalent native selections share checks only
within one consistent read snapshot, never across permission changes or calls.
This conservative history authorization does not copy artifact bodies or make
history eligible for model reuse.
