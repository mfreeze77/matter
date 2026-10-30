# MAT-081: saved monitoring intent handoff

Status: **frozen for component implementation**, 2026-10-30 UTC. Version:
`monitoring-handoff/1.0.0`. This specifies an optional civic adapter,
not a new neutral-core type, API endpoint, permission engine or shipped callable.
MAT-082 implements this version. Neither this document nor its examples
authorize production alerts or establish provider qualification.

The wire definition is [monitoring-handoff.schema.json](monitoring-handoff.schema.json).
The [synthetic compatibility vectors](../../tests/fixtures/civic/handoff/manifest.json)
and their [frozen byte inventory](../../tests/fixtures/civic/handoff/contract-lock.json)
are pinned compatibility inputs. Their references, hashes and expected decisions are invented;
they create no host records, PreparedPacket, grants, assessments or captures.
They are not an evaluation corpus or a runtime validation receipt.

## Pinned host baseline and work still to build

StateCivics main baseline: `e349713e62e35d65cbfb8585a76361f0230cf2b0`.
Paths below are relative to that repository. Later ticket-only corrections do
not change this code baseline. Reuse these existing owners:

- `models/monitoring_intelligence.py`: WatchIntent, immutable
  WatchIntentRevision, EvidencePacket and IntentAssessment already exist.
  Reuse approved revision provenance and private assessment ownership. Preserve
  existing revision hashes; do not recompute them over this projected DTO.
- `services/watch_intents.py`, `schemas/tracking.py`, `api/routers/tracking.py`:
  owner/workspace/client/place checks and create, revise, list, get and retire
  exist. Client is optional. Create requires an entity type/ID and exactly one
  jurisdiction. KS-701's remaining acceptance is not a second-store project.
- `models/watchlists.py`, `services/alert_planner.py`: reuse actual ActivityEvent,
  UserActivityEvent, WatchlistItem and in-app capture. EvidencePacket requires
  an activity event; UserActivityEvent requires a watchlist. AlertPlanner takes
  a WatchlistItem. Existing factual exact-follow activity remains intact even
  when optional Matter attention is quiet or unavailable.

Projection mapping for host implementation review:

- WatchIntent user/workspace/client/jurisdiction → `host_binding`; intent/revision
  IDs, revision number, content hash and approved-by/at → `intent` identity and
  approval. Existing purpose, concepts, interests, exclusions and requested events
  map directly, within their existing limits. Numeric host keys become strings.
- Existing entity type/ID → record scope. The existing API entity-type grammar
  and 300-character entity-ID limit are retained. Broad objective scope is new.
- Existing nullable active-from/until need a documented effective-interval
  projection: absent active-from uses the stored approved-at, explicit start
  is preserved, and absent end means no scheduled end. Evidence/model text
  cannot choose activation time.
- Approved positions, selected defaults, responsibility, lifecycle state and
  component pins require an explicit typed host projection/version mapping.
  Do not reinterpret arbitrary `assumptions` JSON as approved structured fields.
  Existing watchlist channels/cadence are not automatically approved intent values.
- Existing EvidencePacket/IntentAssessment and factual/audience event links
  supply host identities; Matter prepared packets, exact source manifest and
  shared/private assessment references supply verified evaluation identity.
  A StateCivics packet hash and MAT-028 packet digest are different namespaces:
  verify each in its own system instead of substituting one for the other.
- Existing AlertDelivery/capture records supply actual outcome history. Use
  their real conveyed payload for baseline material; an intended delivery or an
  IntentAssessment row cannot establish that history by itself.

The following are **StateCivics work still to build**, not main capabilities:

1. KS-1122/1124: bind real MAT-072 AccessContext/current host controls to the
   authenticated host scope and source grants. Existing ORM ownership checks
   are useful, but do not supply this adapter. KS-1121's unmerged study guard
   is study-only and cannot stand in for production authorization.
2. KS-1122/1123: saved-objective draft, explicit activation, pause and revoke
   behavior. Main has create/revise/retire only. Generic UI workflow drafts
   are not an implemented monitoring lifecycle.
3. KS-1122: discriminated broad objective scope without a fake civic record;
   retain one place per objective for this slice. New authorized
   candidate records may appear after activation. Exact-follow-only dispatch
   would miss that requirement.
4. KS-1122/1124: provision or select an owned watchlist/item capture binding
   for broad objectives and associate the real candidate ActivityEvent. The
   frozen contract requires these references. The owner approved requiring a
   real owned watchlist/item, refusing evaluation until it exists and is
   authorized. Provision/select it in the host; do not create a second sink. Do not invent
   a bill, source event or null foreign key. A record-free preview without this
   binding would need a separately agreed contract mode; it is not this slice.
5. KS-1124: configure the production assessment seam. At this baseline,
   `get_assessment_decision_adapter` deliberately returns 503. Having DTOs
   and the study hook does not mean live dashboard assessment exists.

Matter PR #26 supplies `civic_exports`/`civic_attention`; merge it first or stack
MAT-082 on it. MAT-081 can be specified now. Only KS-1124 and KS-1126 directly
need KS-1121's rehearsal code, after #26 and the rebuilt Matter SDK image.
KS-1122 design/scope work does not wait for that study code. StateCivics commit
`e2dcb04cc` is now on main: KS-1121 is marked blocked,
KS-1122 no longer waits on it, KS-1124/1126 do, and the cited plan is restored.
These are record corrections, not a merge of KS-1121 runtime code. KS-701 remains
`in_review` and must close before KS-1122 acceptance; it does not block MAT-081
contract design. The relevant host code is unchanged from `e349713e6` through
inspected main `8955f16d8`.

## Boundary and encoding

Conceptual call, **not implemented**:
`evaluate_monitoring(request, *, host_context, prepared_packet, executor)`.
Use existing packet factories, source-first civic profiles and attention ports.
No replacement client, queue, context store, retrieval stack or delivery sink.

The JSON request is data. `host_context` is an injected trusted host facility:
authenticated ownership, actual MAT-072 controls/access, current revision/read
factories, source grants and capture-binding verification. It cannot be created
from browser JSON. `prepared_packet` is the existing factory-produced MAT-028
packet and must match the manifest, selected bytes, scope and packet digest.
Do not construct a packet from a claimed digest. No serialized `access_context`
or `authorized: true` can grant authority. Model output cannot activate intent,
change source authority, renew access or choose a delivery destination.

Use strict Matter canonical JSON encoding and existing UTC-time, pinned-reference,
component-reference, locator and SHA-256 formats. The schema copies those core
fragments exactly; tests detect drift. No binary floating point for monetary or
semantic values. Provider scores retain their existing exact numeric encoding.
Host integer primary keys project to canonical decimal strings without leading
zeros; other opaque IDs must match the schema. Do not parse string IDs into
authority. `null` means absent only where explicitly admitted. Empty client IDs,
unknown fields, unsupported tags and coerced types are rejected, not defaulted.

All messages require the exact contract version. A changed required field,
enum meaning, hashing rule or semantic guard requires a new tag and a new fixture
inventory; consumers explicitly admit a version. No silent fallback or ignoring
unknown fields. There is no stable 1.0 compatibility promise before use.

## Request projection

All top-level fields are required. The schema is authoritative for wire types,
limits and nullability; the guards below are additional semantic obligations.

- `request_id` correlates a logical evaluation. `idempotency_key` identifies the
  same command, not a provider attempt. Opaque identifiers are 1–128 characters.
  Host binding contains user, workspace, optional client and one jurisdiction.
  The jurisdiction is an exact registered host key, 5–120 characters, with no
  ASCII whitespace or control characters.
  Revalidate every relationship server-side, including personal/client ownership.
- `intent` pins ID, immutable revision ID/number, **host** content hash, approved
  actor/time, purpose (1–2,000 characters), scope, interests, exclusions and
  requested events (each at most 50 entries of 1–500 characters). Scope is
  `record` with entity type/ID or `objective` with objective ID.
  Intent `concepts` admits 0–50 entries for record scope and requires 1–50 for
  objective scope; record IDs retain the host limit of 300 characters.
  The latter is a proposed host extension, not an existing create API field.
- Provision positions are at most 32 approved entries: proponent, opponent,
  neutral or unknown. Omitted position stays unknown; legacy `monitor` is a
  monitoring preference, never neutral stance. No model-inferred client position
  becomes approved. Responsibility names an optional owner;
  active interval is explicit. `active_until: null` means no scheduled end,
  not irrevocable access. Reject end at/before start and inactive intent.
- `defaults` is a snapshot with optional selected client-profile pin. Do not
  copy contacts, free-form client notes or an entire ORM object. Store effective
  approved values and their provenance; later defaults edits do not silently
  rewrite the revision. Preference is `in_app` only, immediate or digest.
  Digest is evaluated at an explicit host capture checkpoint; no scheduler is
  created by this spec and no real delivery is implied.
- `context_components` independently pins purpose, scope, audience,
  responsibility and preference. Approved positions/exclusions participate in
  the appropriate consumed context digest. Host revision hash and component
  digests have different ownership and are not interchangeable. A cadence edit
  refreshes output guards without rewriting shared source facts.
- `context_selection` names `retrospective_selected` for rehearsal and `current`
  for incoming live. A selected rehearsal revision is reconstructed study
  context, not proof it was the user's actual historical preference.
- `evidence` pins host packet ID, existing prepared-packet digest, knowledge cut,
  coverage/reason, up to 16 selected source entries, correction lineage and
  occurrence references. Each source has an exact pinned reference, artifact
  and selected-text digests, locator, origin and parent references, plus separate
  available/occurred/published/effective times. Unknown times retain reasons.
  A derived source needs verified derivation parents; source origin is not model
  authority. Validate correction/occurrence scope and lineage against real records.
  Partial/unavailable coverage needs a reason; complete means complete only for
  the stated selected source scope. It cannot imply jurisdiction-wide coverage,
  final legal effect or absence of later action. Empty sources cannot justify
  a positive semantic claim; unavailable coverage withholds ordinary attention.
  These three wire labels summarize existing core coverage: complete → complete,
  partial/manual_review → partial, failed/not_expected_yet/expected_not_published
  → unavailable. Preserve the exact core status, snapshot and reason in the
  verified pinned packet/assessment; begin the public coverage reason with that
  status when summarizing a non-complete value. The summary never replaces those
  records or turns expected-but-unpublished evidence into proof of absence.
- `baseline` is no observed output, an observed capture/delivery receipt with
  audience/intent owner and exact conveyed-material digest, or outcome unknown
  with attempt ID. Resolve actual receipt/content; an assessment is not proof
  it was captured or delivered. Historical imported delivery baselines require
  actual evidence and do not enable delivery in this mode. Different clients,
  subjects or purposes do not share communicated history by default.
- `dispositions` pins up to 32 existing scoped host disposition/current records.
  Resolve them under current access and check exact purpose/audience/subject and
  contribution. Feedback is not an intent-wide boolean or an immutable-revision
  edit; changed disposition pointers invalidate their consumers independently.
  A handled old contribution does not suppress a new deadline or linked
  correction. Model text cannot create or broaden a disposition.
- `capture_binding` pins real watchlist, item, factual activity and user-activity
  association. Verify all belong to the current authorized audience/candidate.
  Broad objective identity remains distinct from candidate civic identity.
- `evaluation` pins policy, 1–16 questions, provider, explicit model and adapter.
  This version is always `unqualified`. `budgets` caps calls (1–64), per-call
  timeout (1–120 seconds), wall time (1–3,600 seconds), request/response bytes
  (1–65,536) and decimal USD cost, with an exact price-reservation basis pin.
  Reject zero cost, unavailable pricing/reservation or timeout above wall limit.
  These are envelope maxima, not permission to spend them: actual host budgets
  and provider/egress rules may be lower. No secrets belong in this request.

## Validation, execution and capture sequence

1. Strictly validate shape/version and byte limits. Resolve authenticated host
   binding, current intent approval and component pins. Refuse missing controls,
   retired/paused/revoked/draft state, foreign scope, stale hash or invalid capture
   binding **before** provider I/O. Refusal must not reveal foreign IDs/rationale.
2. Resolve actual prepared packet and current source grants. Check source origin,
   derivation, selected bytes and availability at the evidence cut. Do not send
   expected labels, fixture outcomes, contacts, unrelated notes, capability
   tokens or other-client rationale to a model. Source-only questions receive no
   private audience context; audience questions receive only approved projection.
3. Verify actual baseline and budget reservation. An unresolved prior outcome
   remains unknown; reconcile it through existing receipt machinery rather than
   treating it as absent and blindly resending. Acquire fresh currentness/access
   guards using the host's real clock. No database snapshot spans provider I/O.
4. Use existing executor/receipt/admission ports with explicit model and limits.
   Retain native and normalized responses according to existing privacy rules.
   Provider failure, exhaustion and semantic uncertainty remain distinguishable.
   Model advice never grants eligibility or removes uncertainty from source facts.
5. Re-read guards after provider I/O and before exposing/persisting an audience
   result. An edit, source replacement, revoked permission or cancelled control
   invalidates affected output. Never renew old tokens with submitted old JSON.
6. Before capture the host revalidates current result, scope, mute/retirement,
   capture association and destination. Call AlertPlanner with **explicit
   `channels=["in_app"]`**, never inherited external channels. Explicit channels
   can bypass its normal mute-channel selection, so check mute separately.
   Keep external delivery disabled. Advance a capture baseline only on an actual
   successful capture receipt; delivery/consumption/action are separate outcomes.

Attention is proposed through existing MAT-019 behavior, not hardcoded from the
examples. Quiet is inspectable on demand, not an alert for each keyword. Preserve
useful positives and justified correction, not only all-quiet safety cases.
Use existing dependency capture, targeted invalidation and source/semantic cache
keys. Reuse a finding only when its exact consumed inputs and **current** access
permit it; equal source hashes do not authorize cross-account cache disclosure.

## Result, refusal and retry semantics

`monitoring_result` is an unqualified, capture-only **proposal**, never a send
receipt. It names request/result IDs, exact intent revision, packet digest,
component pins, source-finding and assessment references, typed treatment,
bounded reason codes, cited source/locator/text digest, coverage, uncertainty,
dependency references and optional actual baseline receipt. The host must resolve
persisted records and guards: a reference/digest alone is not a capability or
proof an assessment exists. Citation bytes and dependencies must belong to the
authorized packet; do not silently cite future/foreign sources. No generic
next-step suggestion becomes permission to act. `decision_request` requires a
real user decision, not merely low confidence. Partial coverage normally withholds
ordinary output; any allowed correction must follow existing explicit policy.

`reasons` preserves the core `quiet_reason` codes and the existing MAT-019
positive/audience/preference codes, without renaming them. In particular,
duplicate material uses `no_material_change` (and actual conveyed history may add
`already_delivered`), not a new duplicate-specific attention code. An already
handled disposition retains `disposition_applies`, and uncertainty retains
`insufficient_evidence`. Only `provider_unavailable` and `semantic_unknown` are
explicit adapter diagnostic additions; budget withholding uses `budget_limited`.
The copied core quiet-reason definition participates in the fragment drift check.

`monitoring_refusal` returns only version, request correlation, typed core error
code and bounded public reason. A malformed/unparseable request with no valid
correlation uses `request_id: null`, admitted only for schema/version refusal;
never echo a malformed ID or invent a correlation. Required pairings include:

- malformed request/version → E_SCHEMA_INVALID/invalid_request or
  E_VERSION_UNSUPPORTED/unsupported_version;
- foreign scope → E_SCOPE_FORBIDDEN/access_forbidden;
- unavailable host controls → E_AUTHORITY_REQUIRED/host_controls_unavailable;
- changed context/source dependency → E_DEPENDENCY_STALE/context_changed;
- unavailable/future evidence → E_EVIDENCE_UNAVAILABLE/source_unavailable;
- absent/invalid capture target → E_POLICY_INVALID/capture_binding_missing or
  capture_binding_invalid;
- provider not configured → E_POLICY_INVALID/provider_not_configured;
- exhausted budget → E_BUDGET_EXHAUSTED/resource_limit;
- control cancellation → E_CANCELLED/host_cancelled;
- unresolved prior outcome → E_DELIVERY_UNKNOWN/outcome_unknown;
- same idempotency key with a different body →
  E_IDEMPOTENCY_CONFLICT/idempotency_conflict.

The schema permits the code/reason enums; MAT-082 must enforce these semantic
pairings. Provider runtime failures use the existing receipt machinery and an
honest `provider_unavailable`/semantic-unknown attention outcome when authorized,
not a fabricated positive or an unsupported permission denial.

The host binds a logical idempotency key to canonical request digest and current
scope. Same key/different body is a conflict/refusal, not an overwrite. Exact
retry under still-valid guards reuses the logical result/receipt without a new
provider call or capture. Attempts retain separate identities. A stale retry
requires an explicitly refreshed command/revision and new identity. Capture
deduplication must distinguish applicable intent, audience, subject, revision
and material contribution so two objectives sharing a watchlist item cannot
collapse. Retain prior capture history after intent edits; preserve correction
obligations. Provider completion alone never advances conveyed history.

## Time and lifecycle cases

Evidence availability is the replay boundary, not publication or event date.
For each prefix, available_at must be known and at/before knowledge_cut. A notice
available November 1 about a November 12 hearing may matter on November 1.
A source published October 31 but first available November 2 cannot be read in
a November 1 release. Unknown availability is withheld until resolved. Candidate
selection and packet preparation must enforce this, not just the final output.
Late source release refreshes the relevant prefix; do not rewrite earlier results.
Authorization, credential, expiry, cost and cancellation checks always use the
actual current host clock, even for historical evidence.

Contract lifecycle sequences, **host work not shipped on the pinned main**:

- Autosave draft → no approved request/provider evaluation/capture. Explicit
  user review/submission → immutable approved revision, effective snapshot and
  capture-target verification. Existing create/revise can supply provenance;
  draft/activation UX and gating still need implementation.
- Purpose/position/scope edit while queued → cancel/refresh only affected
  evaluations with new component pins. During I/O → withhold stale result and
  evaluate a fresh command if authorized. Old capture history stays factual.
- Cadence-only edit → refresh destination/pending capture guard without changing
  source-only finding. Don't reannounce all history as novel.
- Pause/retire/revoke → immediate host-control path, not evidence awaiting a
  model score. Block pending capture and recheck in-flight results. Retire exists;
  pause/revoke mapping and reactivation semantics remain StateCivics work.
- Already-handled feedback → scoped disposition, not source rewrite/global
  negative label. A new material deadline or correction may still matter.
  Undo uses an explicit host disposition revision/removal. No hidden expiry
  timer is introduced; purpose-incompatible ordinary baselines are withheld for
  reconciliation while actual older conveyed history remains available for a
  linked correction under current access.

## Frozen decisions and ownership

[Decision 0002](../decisions/0002-monitoring-handoff.md) records D1–D7.
The owner explicitly approved the owned capture target and directed progress;
the remaining protocol dispositions are bounded engineering choices, not claims
of owner approval of UI labels or implemented host controls. Snapshot defaults,
approved provision-specific stance, explicit submission, reconstructed selected
rehearsal context, preserved conveyed baselines/scoped feedback and in-app-only
capture define this version. Host UI wording and provisioning mechanics remain
host-owned without changing those invariants.

The [contract lock](../../tests/fixtures/civic/handoff/contract-lock.json) pins
this specification, decision record, portable/installed schema and synthetic
compatibility vectors. MAT-081 freezes the boundary; MAT-082 and KS-1122 may now
implement against it. Actual host lifecycle/access/record-free capture/live seam
are still missing work, not prerequisites that must be secretly implemented to
specify them. Research-driven examples in the separate use-case catalog are not
normative wire changes, provider labels or new MAT-082 completion requirements.

## Verification handoff

Current wire examples cover contrasting clients with a shared source finding,
personal/no-client and two objectives for one client, record/broad scope,
incoming-live shape, duplicate, explicit analyst-error correction, unknown prior
outcome, future-available source, foreign client, stale revision and missing host
controls. Invalid-shape vectors cover version, notes/contact-field leakage,
forged access JSON, absent capture, production mode, draft, external channel,
empty broad selector and replay/live-policy mismatch. Positive examples have
narrow complete synthetic-notice coverage with unknown legal effect; they do
not assert legal completeness or real JEV accuracy.

Schema tests check encoding and these structural distinctions. Semantic refusal
examples intentionally pass shape validation: their expected refusal is a
**proposed MAT-082 check**, not recorded authorization/time enforcement. Runtime
still needs current ownership/packet/capture verification, same-number foreign
jurisdictions, permission/edit during I/O, late release, unknown times, canary
packet exclusion, partial-coverage withholding, outcome reconciliation and retry
failure-path checks. No provider, capture or production assessment was executed
by this contract work.

Next: MAT-082 synthetic component conformance and KS-1122 host scope
mapping → KS-1123 minimal saved-objective UI → KS-1124 dispatcher → KS-1125
reasons/feedback → KS-1126 two actual saved objectives through existing no-login
rehearsal → KS-1127 incoming-live capture using the same boundary. Respect actual
ticket dependencies; this order creates no permission for parallel execution.
KS-1126 owns the receiving/runtime receipt, not MAT-082's component closeout.
Reuse the existing rehearsal stack; don't build another simulator or alert feed.

Formal provider qualification, human-reviewed held-out labels, broader civic
acceptance and installed walkthrough-schema packaging remain separate gaps.
Passing these contract tests does not resolve any of them.
