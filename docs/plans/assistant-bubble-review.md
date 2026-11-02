# Client research, Matter triggers and personal-assistant review

Status: **Matter-side implementation authorized, 2026-11-01**. MAT-088/089 now
provide the additive review SDK candidate; see the [current contract](../contracts/assistant-review.md)
and [receiving handoff](../adapters/statecivics-assistant-review.md). StateCivics
receiving acceptance remains separate. Earlier planning receipts below are
historical; this document does not approve a threshold or production activation.

The owner's 2026-11-02 [permanent-storage decision](../decisions/0003-permanent-host-storage.md)
requires PostgreSQL ledger storage and host-backed payload persistence before
StateCivics production activation. [MAT-092](../../tickets/MAT-092.md) scopes
the Matter work. No interim production mount or temporary deployment/file-backup
plumbing will be built; retain the existing SQLite rehearsal for comparison and
verification. StateCivics owns storage integration and associated receiving/
recovery acceptance under KS-1158. Encryption remains KS-637/KS-1152 work;
the production dispatcher and activation remain separate StateCivics/owner work.

## What the owner clarified

The bubble is the trigger that wakes the user's specific assistant. Matter/JEV
can identify a meaningful development; that does not automatically interrupt the
human. The assistant can investigate using the existing MCP tools/wizard and
judge whether the user's approved purpose/current work warrants a report,
digest, alert or silence. Quiet can still produce useful cited research.
Findings tagged for the user, client and angle can inform later JEV decisions.

Client creation can begin with existing organization/representation records and
a search of authorized historical documents, mentions and testimony. Present a
cited briefing and suggested interests for the user to keep, edit, add or reject.
Only explicit reviewed activation establishes monitoring intent. Existing lobbyist
records offer realistic sample organizations; representation is a dated source
fact, not proof of a current stance, a StateCivics customer, or user authorization.

## Tickets and ownership

- [MAT-088](../../tickets/MAT-088.md), **Matter**: specify the small versioned
  internal assistant-review request/result boundary, with current authority,
  citations, budgets, outcomes and honest communication-baseline semantics.
- [MAT-089](../../tickets/MAT-089.md), **Matter**: reference host-owned findings
  and quiet/revisit history through scoped IDs/digests, with permission/version
  checks, source attribution, invalidation and prevention of self-corroboration.
  StateCivics keeps the findings, evidence, sessions, reports and memory bodies.
- [MAT-090](../../tickets/MAT-090.md), **StateCivics-owned roadmap entry**:
  reuse onboarding, the user's assistant and MCP/wizard, persistence and existing
  no-login replay/capture stack for the connected receiving demonstration.
  StateCivics **KS-1150** is now its host implementation ticket; this Matter
  roadmap entry must not become a duplicate implementation or authorize host
  changes by itself.

MAT-088's contract is ready to design against the existing foundations; MAT-089
follows it. MAT-090 requires those actual interfaces before connected acceptance.
Client-profile research can progress independently through KS-1135; existing
approved objectives can exercise review without waiting for that enhancement.
No numeric trigger threshold, new assistant service or production policy is
approved by writing these tickets.

## Reuse checked before planning

Matter at `ba4165a`:

- [MAT-022](../../tickets/MAT-022.md), `InvestigationService`: bounded named-gap
  host reads, budgets, stopping and unchanged-gap suppression; no retriever or
  model is installed by that port.
- MAT-015/016/018/023/028/030/072: existing assessments, dependencies,
  versioned context/dispositions, queries, packets, receipts and access/egress.
- [MAT-082](../../tickets/MAT-082.md), [MAT-084](../../tickets/MAT-084.md):
  real source/context guards, source-only study reuse and isolated capture.
  Frozen 1.0/1.1 capture semantics stay unchanged; an internal wake-up must not
  silently be substituted for their existing observed-capture/delivery meaning.
- [MAT-049](../../tickets/MAT-049.md) previously mentioned host-owned LLM
  investigation/custom wording. This clarification adds a personal decision
  stage, rather than merely rendering an already-approved alert.
- [MAT-035](../../tickets/MAT-035.md) remains planned and MAT-040-dependent for
  qualified adaptive semantic investigation. It is not an artificial gate on
  an authorized capture-only personal-assistant experiment. These tickets do not
  complete or weaken its qualification requirements.

StateCivics sources inspected read-only (HEAD observed as `6309d5a4268ac9204e4575be0e1bc7e4e7c9948d`; work may advance in its own session):

- **KS-1135**, proposed: relation-profile research from public records and the
  workspace, including represented organizations, testimony and tracked issues.
  Reuse its `etl/workspace/auto_match_engine.py` and
  `api/routers/lobbyist_workspace.py` ownership; do not create another profile DB.
  The cited draft-briefing/keep-edit-reject acceptance should be reconciled there
  by the StateCivics owner, not silently implemented from this roadmap.
- **KS-1123**, done: existing saved-objective forms, review, draft recovery and
  explicit activation. Reuse rather than design a separate onboarding app.
- **KS-705**, proposed: existing-assistant access to assessment and exact evidence.
  Existing general tool inspection is not proof that this read boundary is built.
- `services/chat_service/wizard_dispatch.py` (`WizardDispatchMixin`),
  `services/wizard_engine.py` (`ToolExposure`, session functions), and the
  existing workflow registry are candidate host integration surfaces. Their
  actual permitted read and background-review contracts must be pinned before
  implementation; this plan invents no endpoint or assistant runtime.
- **KS-1124/1146/1148** provide the received Matter bridge/SDK foundations.
  **KS-1125** owns explanations/feedback, **KS-1126** receiving rehearsal, and
  **KS-1145** topic/keyword/place evidence packets. Current supported bill-version
  evidence can supply a first slice without waiting for all broad source types.

No StateCivics, crawler, Oil or DIAT files are modified here. The KS references
are coordination targets; their owner must reconcile local tickets/dependencies.

## Smallest proposed end-to-end slice

1. Select two real represented organizations from existing permitted records;
   confirm identity/aliases and representation dates. Label sample interests as
   illustrative until approved. Pilot place/workspace/objectives remain unchosen.
2. Reuse historical research to prepare a cited draft client briefing. Distinguish
   the client's own statements, third-party descriptions and assistant inferences.
   Surface active issues/deadlines. The user keeps/edits/adds/rejects and activates
   the reviewed objective using the existing forms.
3. Feed an availability-ordered source development through the existing
   JEV/Matter monitoring path. A candidate burst creates internal review work,
   not a human delivery milestone. Exact transport/field names await MAT-088.
4. Wake the user-specific assistant for **one bounded read-only pass** through
   eligible existing tools. Supply approved context, why flagged, actual source
   citations, uncertainty and what was actually communicated before. Initial tool
   use has explicit call/time/byte/cost bounds and no writes/messages/deployment.
5. Capture a proposed quiet/digest/report/alert result in isolated sinks. Save useful
   findings even for quiet; failed/unavailable/unknown review is not irrelevance.
6. Release a later material development. The next JEV stage sees the new source
   plus authorized, explicitly derived prior findings and their original citations.
   Recheck purpose/angle versions, access and availability before reuse/capture.

Prefer generous plausible-candidate selection over an all-keywords requirement.
Include relevant material without literal terms and irrelevant keyword matches.
Reuse one eligible source-only reading where access permits; client-specific
context and assistant findings remain separate for each audience.

## Information that must remain distinct

Source fact/quotation; source's asserted position; assistant inference; suggested
client interest; user-approved objective/position; internal wake-up; reviewed
finding; prepared report; isolated capture; actual user communication; read;
acted/handled; and unknown outcome are different concepts.

A historical scan or quiet review does not mean the user received every document.
Only actual conveyed material advances the applicable communication baseline.
A model-derived note carries its method, source citations, scope, uncertainty and
context versions; it is not an independent corroborating source, an accepted
claim, a qualification certificate or a permission grant. Current policy/source
changes can invalidate its use. Original documents stay separately addressable.

Scope findings by user/workspace/client-or-personal/approved-objective, subject
and evidence versions. KS-1150 selects the existing client-or-personal and
objective identities for the lens; no competing Matter angle store is needed.
Do not create a globally shared client dossier or share private review rationale
through a source-reading cache.

## Verification to implement later

- Same source and contrasting objectives: appropriate differences in silence or
  report proposals, unchanged factual interpretation and current permissions.
- Quiet early mention retained with citations; later budget/decision/deadline
  warrants fresh review. Historical evidence is not marked delivered wholesale.
- Duplicate material causes no repeated tool loop; a real linked correction/new
  deadline survives old quiet or handled feedback.
- Foreign client/angle, unavailable source, contradictory evidence, provider/tool
  failure, budget exhaustion, in-flight edit/pause/revoke and unknown outcomes.
- Replay follows actual evidence availability, with no future-document/correction
  leakage and no claim that today's approved preferences were historical intent.
- Actual personal-assistant/MCP execution receipts are required for connected
  acceptance. Authored vectors and injected scores demonstrate software behavior,
  not actual JEV interpretation or usefulness. Formal MAT-040/042/050 and
  production delivery remain separate; labels do not block exploratory captures.

## Confirmed dual trigger paths

The owner confirmed **both**, 2026-10-31:

- **Pin-prick path:** a single highly relevant development directly against the
  client's approved interests can immediately burst the bubble, even with no
  prior accumulated pressure. This is an example of a decisive development,
  not a restriction that only adverse events can ever be important.
- **Accumulation path:** smaller distinct developments build context/pressure;
  a later event can tip the combination into review-worthy significance. JEV
  should consider the combined meaning, including a new fact that changes how
  earlier quiet evidence is understood.

Both wake the personal assistant for investigation/judgment. Neither directly
means the user receives an alert. A dual-route match requests one review.
Pressure remains scoped to the approved user/client/objective/angle; repeated
copies and model summaries do not create additional independent evidence.

The owner's “24 percent” accumulated plus “75 percent” new-action example is a
near-boundary illustration. Read literally as addition it totals 99 percent;
no exact threshold, rounding rule or additive formula was chosen. The new event
could also qualify through the immediate path. These percentages are not
calibrated JEV confidence probabilities and do not change the existing 1.1
capture-policy regions. Record source facts, relevance/consequence and
uncertainty separately rather than installing a universal importance score.

## Confirmed completed-review lifecycle

The owner decided, 2026-10-31: after the assistant completes its review it
**clears the pressure, updates ongoing monitoring, and chooses alert or no alert**.
In either outcome, **all evidence stays attached to that user/client/evidence
context**, together with the approved objective/angle and its provenance.

Resetting pressure does not erase evidence, quiet findings, counterevidence or
previous research. It also does not by itself mean the matter is resolved,
handled, communicated or read. Only actual delivered/captured-for-user material
and its observed outcome advance the applicable communication baseline.

Retain the review decision and reasons, citations, original and newly gathered
evidence, actual reviewed source/context versions, and old/new authorized
monitoring-rule versions and rationale. Later JEV stages can use that history
under current permissions without counting prior interpretations as new facts.

The assistant can adjust monitoring within approved intent and actual delegated
host/tool authority. Changes to purpose, client/scope, positions, recipients,
permissions or budget ceilings retain the existing host approval/versioning
boundary. No new authority is implied by a model instruction. Exact writable
rule fields and application/reconciliation semantics are still design work.
The investigation pass remains read-only; any monitoring change is applied
through the separate authorized host control path, not generic MCP write access.

Clearing is scoped to evidence actually covered by a completed, current review.
New or unreviewed material arriving during investigation and another client/angle
must not be wiped out with that reset. A failed, unavailable, unknown or stale
review is not a completed no-alert decision. Recovery must preserve those facts
and avoid duplicate updates, repeated unchanged tool loops or blind retries.

## KS-1150 host boundary and next handoff

Read-only source snapshot: StateCivics main
`e8c2ce70ee548af475e1354416b6fbd3b9e7eb58`, including
`tickets/KS-1150-wake-the-users-own-assistant-for-a-bounded-review-when-matter-flags-a-development.md`.
This supersedes the earlier runtime/lens alternatives in this plan:

- **Host ownership:** StateCivics owns the existing assistant, client lens,
  sessions, memory, source evidence, findings and reports. Matter retains exact
  host IDs/digests and decision-state pointers, plus its own pressure,
  dispositions, baselines and receipts. The future pointer boundary does not
  migrate or delete existing core records or alter frozen monitoring 1.0/1.1.
- **Inbound routing:** wake-ups use the existing host message router as another
  inbound channel, with the objective's actual user identity and a bounded
  read-only tool exposure. They do not create another assistant runtime. Exact
  wire fields, permitted readers and per-review limits still need MAT-088 and
  KS-705; choosing the existing router is not evidence those pieces exist.
- **Sessions:** one logical review session per client lens, with rollover or
  explicit limits before exhausting configured chat capacity (currently 300
  messages or 3,000,000 tokens). Host history retains continuity; Matter stores
  session/review references, not chat turns. Per-review call/time/byte/cost limits
  and applicable account/monthly limits must also be enforced. No pilot budget
  or session-visibility policy has been chosen.
- **Output:** the user's output is a stored report with its alert/notice, never
  a forwarded conversational model reply. Reuse the **county meeting report**
  `alert_deliveries` claim-and-commit-before-send pattern and report notice
  rendering. The state hearing broadcast's separate log is not the record model
  to copy. Preserve honest failed/unknown delivery and reconciliation; an
  internal wake-up or prepared report is not human communication. Initial
  rehearsal notices remain isolated/unsent until joint activation; the general
  report-without-notifying option remains open.
- **Four-input ledger:** JEV judgments, assistant reviews, actually conveyed
  output, and scoped user feedback. These inputs remain distinguishable; a
  conversational assertion is not a source fact or an observed delivery.

**KS-1125 is the next host piece**: explain shown, quiet and corrected outcomes,
then commit reversible scoped feedback through existing Matter dispositions and
pass its real current pins on subsequent evaluation. The present host request
has an empty `dispositions` list; the SDK already supplies the guarded control
and explanation primitives. See the [verified SDK handoff](../adapters/statecivics-feedback-handoff.md)
for exact APIs, restrictions, checks and remaining host acceptance. It is not a
claim that KS-1125's UI/persistence wiring has been implemented here.

Crawler ZIP delivery remains pending per the host handoff; this pass neither
receives a ZIP nor establishes broader source coverage. Existing replay,
assistant, memory and report infrastructure should be extended only where these
specific contracts are missing.

## Five owner decisions remain open

1. **Burst thresholds:** immediate and accumulated paths are agreed; pressure
   meaning, boundaries and correlation policy remain to specify. The numeric
   example is not a calibrated probability formula.
2. **Session visibility:** whether the per-lens review session is visible from
   its start.
3. **Prepared report without notification:** whether a completed report can be
   kept without sending a notice, and how that option appears to the user.
4. **Findings retention:** what is retained and for how long. Clearing pressure
   does not silently erase findings, and this plan does not choose indefinite
   retention.
5. **Pilot and budget:** actual client, place/workspace, two approved objectives,
   model and bounded tool/model budget. Example organizations are not approval.

Technical contract work still includes exact reference/result fields, rollover
behavior, tool limits and reviewed-set reset/reconciliation semantics. Those
are implementation design tasks under the selected ownership, not additional
owner choices silently settled by this document.

## Planning receipt

This commit records intent and acceptance targets only. New tickets stay
`planned` with `completion: not_run`; existing MAT-035/MAT-049 statuses and formal
prerequisites are unchanged. Run receipts for render, validation and review are
recorded at planning closeout. No runtime or provider/tool experiment ran.

Planning closeout checks: `python -m matter render --check` and `python -m matter validate` pass (90 tickets, 107 requirements, 108 schemas and three walkthroughs); `git diff --check` passes. Independent two-round review covered all seven supported JSON files in 77.6s, with zero findings/warnings. Runtime source, package version and schemas are unchanged; no software/runtime tests or provider/tool experiment were claimed for this documentation-only work.

Dual-trigger clarification closeout: the updated canonical records render and validate (90 tickets, 107 requirements). Final whole-branch two-round review covered four supported JSON files in 56.2s, with zero findings/warnings. Tickets remain planned/not_run; no runtime, schema, threshold configuration or provider execution changed.

Completed-review clarification closeout: records render and validate (90 tickets, 107 requirements); the two-round review of four JSON files completed in 59.5s with no findings/warnings. All three tickets remain planned/not_run; no runtime, package, schema, live model/tool call or deployment changed.

KS-1150 alignment: the canonical roadmap now names host-owned assistant/lens
artifacts, pointer-only Matter reuse, county report delivery records and bounded
session continuity. KS-1125's SDK handoff records 26 existing synthetic checks
passed in 47.015s; it does not establish host implementation or receiving
acceptance. The five owner decisions remain open. Runtime, package and schemas
are unchanged.

Alignment closeout: render/check, validation and diff whitespace checks pass.
The two-round bridge review covered five JSON files in 70.2s with zero findings
or warnings under its configured JSON rules; those rules are limited to key
spelling, not semantic verification. Markdown is excluded from that tool and was
checked directly against the pinned host source and Matter SDK. The receiving
host tests and actual assistant runtime remain unrun by this change.

## Implementation transition, 2026-11-01

PR #37 merged as `6aeb0f0`; it was planning/SDK handoff documentation only.
The owner subsequently authorized MAT-088/089 implementation and Matter PR
closeout. StateCivics `b87c6027f` now supplies the existing review engine; KS-705
and KS-1125 source code are present. Earlier unresolved-runtime and proposed-reader
statements above describe their older inspected snapshots, not current blockers.

The current contract labels tool/time/read/byte limits and host-managed cost
policy. StateCivics' recorded owner decisions now place review sessions under
objectives, outside personal chat charge, and select host-managed study costs;
this SDK neither overrides them nor silently selects unset thresholds, findings
retention/admission or pilot policy. The host's actual session/recovery/report
implementation and receiving acceptance remain its responsibility.
