# Dashboard objectives → Matter monitoring handoff

Planning baseline: 2026-10-28. Owner asked for tickets and a coordinated plan,
not implementation, migrations, deployment or provider execution. Proposed names
and wire fields below are design inputs; MAT-081 freezes the contract before
implementation. DIAT, replacement infrastructure, PostgreSQL backend changes,
broad dashboard redesign and the later custom alert writer are outside this plan.

## Current evidence and reuse

- Matter: MAT-018 contexts/dispositions; MAT-015/016 assessment dependency capture
  and invalidation; MAT-019 attention; MAT-021 outbox/outcome receipts; MAT-023
  explanations; MAT-024 chronological replay; MAT-028 packets; MAT-031 admission;
  MAT-032 optional TypeSafe transport; MAT-072 access/egress are implemented.
- MAT-048/049 remain in progress. Their bounded crawler import and source-first
  experiment do not complete the broader civic contract. MAT-040 is blocked;
  MAT-042/050 remain later outcome/receiving qualification. None blocks bounded,
  authorized capture-only diagnostics solely for lack of held-out human labels.
- StateCivics at `98928295d`: `WorkspaceClient`, `WatchIntent`, immutable
  `WatchIntentRevision`, shared `EvidencePacket`, private `IntentAssessment`,
  `/tracking/intents` and `WatchIntentService` already exist. KS-701 is still
  `in_review`; its applicable acceptance needs closeout, not another intent store.
- The create schema currently requires `entity_type` and `entity_id` and one
  jurisdiction. Broad client/project/topic objectives need an explicit scope
  extension. Never manufacture a bill or overload a suggestion as intent history.
- Existing client forms, workflow drafts, watchlists, Tracking, ActivityEvent /
  UserActivityEvent, AlertPlanner and the in-app sink remain the owners. KS-997
  owns broader JEV/local suggestions and place choice; KS-1071 owns client-board
  local-record usability. This work does not redo or close those whole tickets.
- KS-1118 is on StateCivics main. KS-1121 public-source rehearsal is committed on
  its local branch; Matter PR #26 is open. These are tested foundations, not a
  connection to real saved dashboard configuration or production alert readiness.
  The five-call public study found underconfident stance/positive relevance;
  retained limitations remain in `docs/validation/civic-source-integration.md`.

## Single proposed boundary (MAT-081 owns its versioned specification)

StateCivics remains the authority for account/client ownership, subscriptions,
approved intent, source grants and host control. Matter accepts bounded explicit
inputs and returns inspectable assessments/attention proposals. JEV supplies
versioned judgments behind the existing executor; its output cannot grant access,
change source authority, activate an objective or authorize delivery.

The contract should be callable within the existing host; no new service, queue,
client directory, source ledger or dashboard-specific common-core vocabulary.
Cross-service Workbench data stays behind its existing authorized API boundary.

### Input groups to specify

1. Contract/schema version, request/idempotency identity, host policy version,
   scope/principal/workspace binding, run identity and mode. The authenticated
   host verifies ownership; submitted IDs are never proof of permission.
2. An exact approved intent ID/revision/hash plus effective interval and approval
   provenance; optional client or personal-work identity; independently versioned
   purpose, scope, audience, responsibility, position/exclusion and preference
   components. Say which selected client-default values were used and their
   versions. One client's several objectives stay separate.
3. Purpose text; scoped subjects/places; changes of interest; issue/provision
   positions and exclusions; assigned responsibility/already-handled status;
   active dates; audience and delivery preferences. Missing stance is unknown,
   not neutral. Legacy `monitor` is a watching preference, not a source position.
4. A separate authorized evidence manifest: exact source/version hashes and
   citation spans, observation/occurrence/instrument identities, origin/derivation,
   coverage and omissions, withdrawal/correction lineage. Keep occurrence,
   publication, effective time and actual availability distinct, with explicit
   unknowns. Selected source-only interpretation receives no private client goals.
5. Actual prior communicated/captured baseline and outcome receipt, scoped to the
   applicable audience/purpose/subject; the exact content communicated, not a
   guess that the entire source was conveyed. No baseline and outcome-unknown
   remain explicit. Undelivered assessments do not advance that baseline.
6. Selected question/profile/model/adapter versions, qualification state,
   current access/egress token/grants, and explicit call/time/byte/cost budgets.
   Pass only approved monitoring fields; contact details and general client notes
   are excluded by default. Never serialize an entire client ORM record.
7. Replay/live origin, evidence cutoff and explicit context-selection policy.
   Domain/replay time never substitutes for the actual authority/provider clock.
   Direct pause/retire/revoke/edit commands use the host control path immediately.

### Draft envelope and validation boundary

Proposed request name `MonitoringAssessmentRequest`, contract tag
`monitoring-handoff/draft-1` (not accepted by any runtime yet):

- Required: `contract_version`, `request_id`, `idempotency_key`, `mode`,
  `host_scope_binding`, `intent_version`, `context_components`, `evidence`,
  `baseline`, `evaluation_config`, `access_context` and `budgets`.
- `mode` first admits only `rehearsal_capture` or `live_shadow_capture`.
  `intent_version` carries host intent/revision/hash/approval/effective-time pins;
  `context_components` carries the exact independent purpose, scope, audience,
  responsibility and preference versions, with approved positions/exclusions.
  `client_id` is optional within the authenticated host binding.
- `evidence` carries the authorized packet/source manifest, exact spans/hashes,
  coverage/lineage and `knowledge_cut`; `context_selection` explicitly names the
  agreed historical/retrospective mode and selected revisions. Existing Matter
  reference/time/packet types should supply exact encodings where compatible.
- `baseline.status` distinguishes observed capture/delivery, absent history and
  outcome unknown; an observed baseline carries its receipt and exact conveyed
  material. A caller may not substitute an undelivered assessment.
- `evaluation_config` pins question/profile/policy/model/adapter and qualification;
  `access_context` is backed by actual current host controls, not asserted JSON.
  Input shape/version/hash/scope/cut/budget failures refuse before provider I/O.
- Repeated logical requests reuse permitted results/receipts only while their
  dependency and current-access guards still hold; an invalidated retry is stale,
  not a silently fresh replacement under the old key.

Proposed result name `MonitoringAssessmentResult`: `request_id`, contract and
logical result identity, exact assessment/source-finding/context references,
`treatment`, `reasons`, `citations`, `coverage`, `uncertainty`, `qualification`,
`currentness`, `dependency_guards`, `baseline_reference`, `permitted_use` and
`proposed_next_steps`. These proposals carry no delivery outcome; the host adds
actual capture/delivery receipts afterward. The first modes permit capture only.
Denied responses expose a bounded public error/correlation, never forbidden
source/client IDs, citations, rationale or raw attempt journals. MAT-081 must
freeze exact types, required/optional/null meanings and errors before code.

### Output groups to specify

- Correlated intent/evidence/context/policy/question/assessment references and
  exact versions, evaluation cutoff, currentness, coverage and qualification.
- Shared source findings and cited reported positions, separate from private
  audience consequence and the client's approved positions. Unknown legal effect
  stays unknown. Reuse source interpretation only where authorization permits.
- Existing typed attention treatment (`quiet`, `host_hint`, `digest`, `update`,
  `correction`, `decision_request`) and structured reasons: irrelevant,
  unchanged/duplicate, already handled, insufficient evidence, stale context,
  access refused, provider unavailable or budget exhausted remain distinct.
  A decision request requires an actual user decision, not generic uncertainty.
- Source/version/span citations; uncertainty/withholding explanation; supported
  proposed next steps; dependency/freshness guards; prior-baseline reference;
  allowed use (capture-only, qualified/consequential if separately admitted).
- Stable logical result/receipt identity so retrying a command adds no capture or
  provider call. Attempt IDs and incomplete outcomes remain separately counted.
  Capture, real delivery, consumption and action are independently evidenced.
- Minimal authorized read projections for why-shown/why-quiet/why-corrected.
  Denied results never reveal another account/client's rationale or raw journals.

This is a field-group proposal, not a newly implemented runtime schema or an
approval of final option wording. Exact wire shapes, limits and compatibility
rules are acceptance work in MAT-081 with StateCivics KS-1122.

## Dashboard proposal (StateCivics owns the product choices)

Add a small monitoring-objective form to existing client and personal workflows:
purpose, scope, changes that matter, positions/exclusions, responsibility/timing
and delivery preferences. Reuse existing draft recovery and jurisdiction rules.
Render a plain-language review summary of effective defaults/overrides, missing
information, recipient/cadence and capture-only status. Normal explicit submission
activates an approved immutable revision; autosaved drafts do not. No additional
approval ceremony is implied. StateCivics records who activated which version.

Keep keyword matches as authorized discovery candidates. Matter attention cannot
remove an exact-follow factual event, copied read state or existing saved work.
Show decision reasons in the existing tools, including an on-demand quiet audit;
do not create a second alert feed or notify users for each quiet keyword match.

Feedback is scoped to its user/client/objective/result. Already handled, irrelevant,
wrong scope, wrong position and suspected source error have distinct effects.
Feedback proposes context edits or records dispositions; it does not rewrite a
shared source claim, label every client, train a global model or grant authority.
Pause/retire/revoke commands take effect promptly through host controls.

## Decisions to resolve before the affected implementation

- D1, MAT-081 + KS-1122: broad scope discriminator and mapping to existing records.
  Proposal: one place per objective in the first slice; choose explicitly between
  later multi-place objectives and UI grouping of existing single-place intents.
- D2, KS-1122/1123: snapshot client defaults at activation versus a live linked
  default with dependency-driven revisions. Proposal: explicit snapshot first;
  no silent inheritance of future edits or general client notes.
- D3, MAT-081 + KS-1123: supported position granularity and names. Preserve
  provision-specific support/oppose/neutral/unknown; decide how legacy record-level
  positions apply without pretending they describe every provision.
- D4, KS-1123: Save versus Save-and-activate wording, retirement/reactivation and
  responsibility fields. Reuse existing explicit submission and draft controls.
- D5, MAT-081 + KS-1126: replay historical-context-as-of versus retrospective use
  of a selected current intent. Proposal for the first study: explicitly frozen
  approved revisions plus scheduled edits, labeled reconstructed. Never describe
  present client settings as their actual historical preferences.
- D6, MAT-081/082 + KS-1125: baseline compatibility when purpose materially changes,
  feedback expiry/undo and how an already-handled disposition interacts with a
  new correction/deadline. Preserve actual communicated history; never suppress
  correcting an unsupported prior contribution solely for low current relevance.
- D7, KS-1123/1127: later delivery/cadence defaults and live source/privacy envelope.
  First slice is existing in-app capture only. A future model price, threshold,
  question wording, production destination or custom writer is not approved here.

Each owning ticket records the chosen option, rationale and contract version
before code relying on it begins; unresolved choices do not become silent defaults.

## Ownership and implementation order

1. MAT-081 specifies the boundary and frozen compatibility/negative examples.
   KS-1122 records the host scope/default/permission mapping against it and closes
   the relevant KS-701 acceptance. A proposed boundary is not an implemented API.
2. After contract agreement, MAT-082 implements the bounded Matter adapter while
   StateCivics KS-1123 adds the minimal saved-objective/review/activation controls.
   This describes dependency readiness, not authorization for parallel execution.
3. KS-1124 connects approved intent/evidence to that adapter and the existing
   capture sink, with current authorization, exact retry and stale-result guards.
4. KS-1125 connects reasons/feedback and scoped edit/disposition effects.
5. KS-1126 exercises two real saved objective records for contrasting fictional
   client contexts through the existing no-login fast-forward rehearsal, including
   edits, duplicates, corrections, silence and evidence/time/permission negatives.
6. KS-1127 connects subsequent incoming-live events to the same serializer and
   dispatcher in bounded capture-only shadow mode. Compare replay/live with fixed
   recorded judgments; fresh-provider variability is separately reported.

Both sides keep their own store/schema/authorization owners. Cross-repo gates
are named explicitly in tickets; they are not encoded as pretend local ticket IDs
or counted as completed because one repository's graph says ready. MAT-049 remains
in progress for full civic behavior, with MAT-048's wider authority/source scope
still open. KS-997/1071 retain broader suggestion/board work. Production delivery
requires separately approved receiving acceptance, actual qualification where
required (MAT-040/042/050), supported current source/profile authority and rollout
controls. No production activation is part of these six StateCivics tickets.

## Evidence required for the first slice and the later live follow-up

Start with exactly two saved objectives submitted through existing dashboard/API
flows in the isolated rehearsal, for contrasting fictional clients under a test
workspace. Verify personal/no-client mapping in focused cases without expanding
that first end-to-end scenario. Current client notes/contact canaries and foreign
workspace/client IDs must not enter model requests or unauthorized readbacks.

Use a frozen source sequence with authored expectations outside model packets:
relevant change, expected silence, duplicate/reprint, a genuinely linked correction,
intent edit while queued/in flight, pause/revocation, a newly available late source
and a known future deadline already published. Future-event dates can be meaningful
now; future-*available* evidence is forbidden before its release. Corrections of
sandbox analyst errors and actual source revisions must be identified separately.

For each checkpoint retain saved revision/hash, exact released prefix, source-only
and audience packet hashes, native/normalized responses if actually called,
assessment/treatment/reasons/citations, actual capture/outcome receipts, baseline
and retry/freshness/refusal checks. One event can yield two private assessments
without duplicating the factual event. The two audiences must share source findings
but have independently justified treatments. Check controls that retain useful
positives, not only all-quiet negatives.

Replaying the same released inputs, intent versions and recorded judgments must
reproduce the deterministic attention/capture trace. Actual fresh JEV scores may
vary; report that separately and never claim frozen replay proves accuracy.
Live runs require explicit provider/model/call/time/cost limits and current
MAT-072 egress, but held-out labels do not block an authorized exploratory run.
Provider qualification and real receiving usefulness remain separate evidence.

## Ticket inventory

Matter canonical records: MAT-081 (shared contract), MAT-082 (bounded context /
assessment adapter). StateCivics: KS-1122 (scope/backend), KS-1123 (minimal UI),
KS-1124 (dispatcher), KS-1125 (explanations/feedback), KS-1126 (two-objective
rehearsal), KS-1127 (incoming-live capture). All newly planned; none implemented
or qualified by this document. StateCivics' local plan carries its exact paths and
local dependency edges; this is the proposed shared boundary's single owner.
