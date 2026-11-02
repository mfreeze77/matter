# Dev19 assistant-review receiving evidence

StateCivics' retained run 5 demonstrates the narrow MAT-088/089 receiving path:
live-origin dispatch in isolated rehearsal, Matter pressure/claim, the existing
assistant review, and guarded completion. It does not complete KS-1126's broader
acceptance criteria, qualify JEV, establish interpretation accuracy or activate
production delivery.

## Source and external receipts

- Matter SDK: `matter-foundation==0.1.0.dev19`, main merge
  `d9584ddc6ac3f1f3b1da1eef299fa81172abfe66`; runtime
  `0ce70c60f1341a0a1068c73b54af84fc928b8336`.
- StateCivics main inspected read-only:
  `f1e6cb4256486aa57ff1ec6cb5c4f7c3183653f0`. Its KS-1150 and KS-1126 logs
  distinguish assistant-review receiving from the unexecuted broader rehearsal.
- External evidence stays in StateCivics:
  `.release/ks1126-wired/run5.txt`, recorded 2026-11-02 01:29–01:33 UTC.
  SHA-256: `4ba96c443f100fa03dd39ab07b7e371b759c13c2d03d9e07e278c0fb9813b930`.
- Companion `.release/ks1126-wired/packet-size.txt` SHA-256:
  `fb2d1aeff27692e6231ed58671d7df86665286ec6f51ba47f1e24f96b2f91b65`.

No real client records, raw assistant messages, bill text, credentials or database copies
were imported into Matter. This receipt records metadata and external references.

## What Matter checked

The receiving fixes were inspected in StateCivics' existing
`services/assistant_review.py` and `services/matter_review_host.py`:

- The wake carries the whole exact packet material alongside Tracking's excerpts
  when it fits the host bound. Clipped material produces an empty `reviewed` set,
  preserving pressure. The evidence projection also bounds large material.
- One finding helper serves both ledger selection and resolution. Verbatim
  evidence quotes remain quotes; other findings are interpretations with their
  original citations. The underlying deterministic/JEV judgment retains its
  separate classification.
- The receiving code normalizes stored native JSON to plain values and covers
  retained native selections in the current policy/token. This must continue to
  respect actual present host grants; historical presence is not permission.

Matter inspected the available receiving-test image
`ks-test-runner:matter-0ce70c6`, image ID
`sha256:e7fb52d0004dd0b93ed0c6cc3599c2452470e30216d0386a0959bcf424156c36`.
An isolated, network-disabled container reported dev19 for both runtime and
distribution metadata. All **207 packaged runtime/schema files** matched the
release manifest: zero missing, changed or extra files. This verifies that image's
SDK content, not the currently running backend's mounts, flags or database state.
The latter, including migration 125, are StateCivics-reported operational facts.

## What retained run 5 shows

- First SCR 1603 development: captured/digest, a completed wake and completed
  assistant review with proposal digest, three tool invocations and four findings.
  The result names one reviewed evidence reference. Matter's subsequent pending
  list is empty.
- Exact dispatch retry: reused, with the same retained assessment; reported
  elapsed field 0.5 seconds. Direct wake repeat: `acquired=false`, completed;
  the receipt then lists one review.
- Second distinct development: a second completed wake and digest proposal; the
  retained review list then contains two completed reviews. StateCivics' log
  records the first review/session/findings in this wake's ledger. The second
  source is the previous compared bill version, not a chronological advance;
  this is not a forward-timeline novelty or correction test.
- The first and second dispatch receipts report 136.4 and 110.2 seconds. These
  are reported dispatch-duration fields, not an independently profiled breakdown
  of capture, guards and model latency.
- Nothing was sent according to the host run record. A digest proposal and an
  isolated in-app capture do not establish a delivered report or user read.

The first review's retained tool IDs are `get_objective_outcomes`,
`get_bill_details`, and `propose_review_outcome`. Run 5 does not show a
`get_bill_text` invocation; that appears in an earlier run's narrative. Record
whole-packet input and a bill-detail lookup here, not a verified full-bill fetch
or proof the assistant understood every passage. These are real assistant-turn
receipts reported by StateCivics, not a new live JEV evaluation or a model-call
count inferred from the number of tool calls. Matter made no provider calls.

## Remaining acceptance and ownership

StateCivics KS-1126 AC-1 through AC-4 remain unexecuted: two contrasting objectives
through the real UI/API, timeline replay, and quiet/duplicate/correction contrasts.
The current dispatch hook wakes only on live-origin captures; replay wakes
nothing. Its immediate opponent rule is objective-wide, not a demonstrated
event-specific adversity judgment. Do not report full StateCivics readiness.

Slice 2c remains StateCivics-owned: construct a bounded accumulated request from
actual pending material, preserve provenance/correlation and actual reviewed-set
coverage, and wire explicit operator reconciliation to the SDK with a real
no-inflight witness and present correction authority. Failed/unknown never means
quiet; reconciliation itself clears no pressure and starts no new assistant turn.
No numerical accumulation formula or burst threshold is selected by this receipt.

KS-1152's recovery/window choices, shared rehearsal image operations, deployment
and joint activation stay with StateCivics and the owner. The reported
`rehearse.sh` image-pin refusal is host operations follow-up, not a new replay
implementation for Matter. KS-1155's commit-based pacing fix and its reported
207 checks remain StateCivics evidence; Matter did not rerun its paid civic path.

The SDK [release validation](MAT-088-089.md), separate installed walkthrough-schema
gap, MAT-083 concurrency work and formal qualification retain their own scopes.

## Checks for this Matter record

Matter ran all 18 repository-integrity checks (passed), `render --check`,
`validate` and `git diff --check`. Validation remains 90 tickets, 107 requirements,
109 schemas and 3 walkthroughs. The two canonical JSON records received the
configured independent two-round key-spelling review: 2/2 files, no findings or
warnings; both round processes completed successfully. Markdown was excluded by
those rules and checked manually against the named source and receipt metadata.

No StateCivics suite or paid run was rerun. Its reported host gate counts remain
host evidence. Matter runtime, schemas, packaging and SDK version are unchanged;
this documentation closeout does not require another SDK image rebuild.
