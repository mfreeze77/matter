# Dashboard objectives → Matter monitoring handoff

Planning baseline: 2026-10-28; host code rechecked 2026-10-29 at `e349713e6`. Owner asked for tickets and a coordinated plan,
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
- StateCivics at `e349713e6`: `WorkspaceClient`, `WatchIntent`, immutable
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
- KS-1118 is on StateCivics main. KS-1121 public-source rehearsal code is on
  the backed-up planning branch, not main; `e2dcb04cc` corrected its main ticket
  status to blocked. Matter PR #26 is open. These are tested foundations, not a
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
A broad objective is not itself a civic matter. D1 must specify how its versioned
context template binds to an actual authorized candidate subject at dispatch,
without manufacturing a civic identity. New records/subjects that did not exist
when the objective was activated must remain discoverable through existing event
and candidate-scope watches; an exact-follow-only implementation is insufficient.

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

### Candidate envelope and validation boundary

MAT-081 now has a [candidate specification](../contracts/monitoring-handoff.md),
portable schema and synthetic compatibility examples, tagged
`monitoring-handoff/1.0.0-candidate.1`. It remains unfrozen; this is not a
shipped runtime API. That specification supersedes the earlier draft field names.
The request projects approved intent, authenticated host-binding identifiers,
context components, evidence, baseline, capture binding, evaluation and budgets.
The actual trusted host controls and MAT-028 PreparedPacket are injected alongside
it; JSON `access_context` is forbidden and cannot grant authority.

Pinned StateCivics main has real ownership checks and create/revise/retire, but
no production MAT-072 host-control adapter, draft/pause/revoke lifecycle, broad
record-free create scope or live assessment provider (the seam returns 503).
Current capture requires a real watchlist/item and ActivityEvent association.
Owned broad-objective capture provisioning is an explicit unresolved host choice,
not existing functionality. See the specification's host-build list and D1-D7
freeze gate before dependent implementation.

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
   KS-1122 may contribute design review before its implementation dependencies
   clear; MAT-081 does not wait for KS-1122 implementation to complete.
   KS-1122 records the host scope/default/permission mapping against it and closes
   the relevant KS-701 acceptance. A proposed boundary is not an implemented API.
2. After contract agreement, MAT-082 implements the bounded Matter adapter while
   StateCivics KS-1123 adds the minimal saved-objective/review/activation controls.
   This describes dependency readiness, not authorization for parallel execution.
   MAT-082 completes on bounded synthetic adapter conformance; KS-1126 later owns
   the actual saved-objective receiving proof and is not its completion gate.
3. KS-1124 connects approved intent/evidence to that adapter and the existing
   capture sink, with current authorization, exact retry and stale-result guards.
4. KS-1125 connects reasons/feedback and scoped edit/disposition effects.
5. KS-1126 exercises two real saved objective records for contrasting fictional
   client contexts through the existing no-login fast-forward rehearsal, including
   edits, duplicates, corrections, silence and evidence/time/permission negatives.
6. KS-1127 connects subsequent incoming-live events to the same serializer and
   dispatcher in bounded capture-only shadow mode. Compare replay/live with fixed
   recorded judgments; fresh-provider variability is separately reported.

Dependency clarification, 2026-10-29: MAT-082 follows MAT-081 freeze and
uses PR #26 civic_exports/civic_attention after merge or by stacking. Only
KS-1124/1126 directly require the KS-1121 study code, after #26 and a rebuilt SDK
image. KS-1122 does not wait for that code. StateCivics `e2dcb04cc`, verified
on main through `8955f16d8`, corrected KS-1121's status and dependencies and
restored `docs/plans/dashboard-matter-integration.md`. KS-701 remains in_review
and gates KS-1122 acceptance, not this contract design. Those record corrections
do not supply the missing host runtime capabilities. Matter has not edited that
checkout in this slice.

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
rehearsal), KS-1127 (incoming-live capture). MAT-081 is now in progress as a candidate specification; MAT-082 and the new
host capabilities remain planned. None is implemented or qualified by this document. StateCivics' local plan carries its exact paths and
local dependency edges; this is the proposed shared boundary's single owner.


## Planning verification (not runtime acceptance)

Canonical ticket generation/check and repository validation passed with 82
tickets, 104 requirements, 106 existing runtime schemas and three walkthroughs.
At that planning receipt MAT-081/082 were planned/not_run; current MAT-081
candidate progress is recorded in [the contract receipt](../validation/dashboard-matter-handoff.md). Cross-side planning checks found an
acyclic new-ticket graph, existing source/local-doc paths, unique index rows and
named external MAT-081/082 dependencies for each StateCivics consumer.
StateCivics' existing Docker ticket metadata/contiguity check passed once at
`2069223eb`; this is metadata evidence, not execution of the new acceptance cases.
The two-pass JSON ticket review found an adapter-versus-host completion-gate
ambiguity; corrected MAT-082 to synthetic component conformance, with actual
saved-objective acceptance remaining KS-1126-owned. Markdown was inspected as
planning content; it is excluded by the default code-review rules. No runtime
source file, provider call, production dataset or deployment was changed.

Final review delta: the corrected MAT-082 canonical record received two passes,
zero findings and zero coverage warnings. The initial four-JSON-record review
also had no coverage warnings. Markdown planning content was manually checked
against the paired StateCivics tickets and current code; it was not represented
as code-review coverage. StateCivics tickets are committed locally on
`plan/dashboard-matter-handoff` (`7c61e7b89` at the planning closeout), based on the
existing KS-1121 work/current main. Matter's plan is stacked on the existing
`feat/civic-source-adapter` branch so the new plan does not silently merge that
implementation or alter main. Ticket IDs KS-1122–1127 and MAT-081/082 are reserved
by these committed records; inspect branches as well as main before allocating
further IDs.

## Version 1 contract freeze

The owner approved an owned watchlist/item capture target and refusal until it
exists and is authorized. [Decision 0002](../decisions/0002-monitoring-handoff.md)
records bounded D1–D7 dispositions for `monitoring-handoff/1.0.0`; the shared
specification and compatibility examples are frozen for MAT-082 component work.
Host lifecycle/access/scope/provider implementation and KS-701 closeout remain
host work. No production delivery or provider qualification follows from freeze.
The [broader workflow catalog](../research/civic-monitoring-use-cases.md) informs
future examples without expanding the first two-objective runtime slice.
