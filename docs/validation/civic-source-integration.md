# Bounded public-source civic monitoring — 2026-10-28

This is an executed capture-only integration slice of MAT-048/MAT-049. Neither
full ticket is complete. No DIAT work, new crawler processing, receiver import,
production alert, custom alert writer or qualification was performed.

## Source and handoff

Read-only crawler checkpoint: `c357ad1`, with unrelated uncommitted work preserved.
Existing owner tickets are T-087/T-090 and T-104; a MAT-046-compatible pinned,
host-reviewed authority/profile export was not established. MAT-047 remains
unfulfilled. This does not prevent a bounded diagnostic that retains authority
as unresolved. It does prevent claiming the complete civic integration contract.

Reuse latest inspected retained dropoffs: Shawnee `20261022-r2q`, Topeka
`20261022-t`, Wyandotte `20261015-a`. No replacement collection infrastructure.
The selected Shawnee ZIP SHA-256 is
`5936d0a01f06faf63f37736955b24ac72d0c674eb38cfeb4c27982b265f86b3b`;
producer revision `e4eeb0e22f32bd743bd59bfd6ddfc342c2174180`. The external
packet also retains the manifest's exporter worktree inventory.

Selection: resolution R2026005, related case CU25/05, publisher file 8751,
CivicClerk event 1283. Issuer/year are explicitly host-scoped; related identifiers
remain proposals rather than an automatic alias. Source URL:
https://shawneecoks.api.civicclerk.com/v1/Meetings/GetAttachmentFile(fileId=8751).
The package's original-PDF SHA is
`ac93c882d48a16dd569dd43ed8dcb6f3f5634a9a7844a7d0bcb503df93331945`;
this run did **not** re-fetch or verify PDF bytes. It verified the retained exact
text SHA `58a57df3aadf127470df0cc56e2ca88eb21bad5258304c9b36a874f642a4d6de`.
The saved extraction is partial (8/23 pages have text). It is not complete minutes
or proof of final action. First actual adapter preparation availability was
`2026-10-28T22:22:13.376789Z`; reconstructed replay pacing is explicitly distinct
from government publication or historical ingestion time.

Preparation accepted three native source assertions with zero citation refusals.
Original exported text and a separately hashed PDF-page-marker-free LF citation
view are retained through ObservationIngestor; MatterService, OccurrenceService
and ClaimService retain the scoped subject, publisher appearance and assertions.
No source assertion is accepted legal state. See `docs/civic-import-map.md`.

## Executed connected run

StateCivics source: `bf92f745232bfb2e1b0b2168e03e695c85802433`, branch
`feat/civic-real-packet-monitoring`, KS-1119. Matter adapter/source questions at
`eae62d6`, installed wheel SHA
`724cdc92f2020dcc0c885dee23a3f66db8d93d898b73f2bd38a2015868b75e5e`.
The existing test image was reused with only that wheel replaced:
`ks-test-runner:civic-724cdc9` (image list digest
`sha256:c70d5c824d67b1ba6f78bf02a0baf699646e770a755cabe1896bb380f875c284`).

External inputs:
`~/.local/share/matter-validation/civic-source-integration-20261028/packet-v1/`.
Runtime evidence:
`~/ks-rehearsal/matter-live-20261028T223354Z-5150/responses/run/`.
Run ID `68798f79-aded-4008-b5e2-820bd4efbd25`. Source/marker were read-only
mounts; output is private external storage. Credential arrived only on stdin.
The ordinary no-login rehearsal admission and existing PostgreSQL run schemas,
Matter attention primitive, AlertPlanner and isolated in-app sink were reused.
HTTP host routing used in-process ASGI, not a TCP/browser walk.

Actual controls: explicit `jev-1.14.0`; five-call cap, no retries, 20-second
request deadline, 300-second interpreter wall bound, 65,536-byte request/response
bounds. Existing MAT-072 AccessService captured exact source/audience/provider
and authority dependencies, prepared/rendered the packet under access, and
rechecked current permission immediately before and after provider dispatch.
The original rehearsal authority is also checked around the interpreter.
The frozen price basis is $0.042/million input tokens, zero output-token charge;
launcher cap $0.10, worst reserved input at 5 × 65,536 tokens $0.01376256.
Observed 67,636 input tokens imply $0.002840712 at that basis; billing was not
observed. Elapsed interpreter time 48.721 seconds. All five actual responses
completed with exact numeric/native response retention.

Four reconstructed checkpoints, two invented work contexts:

1. Public recommendation/source read. One source-only four-head call, then two
   audience objective/novelty calls. Both decisions quiet; no initial capture.
2. Exact duplicate. Both quiet, no provider calls.
3. Explicit **synthetic prior analyst-error control** saying final approval.
   Two deliberately erroneous sandbox captures, no provider calls. This is not
   a fabricated government publication, actual JEV output or real-client alert.
4. Corrective read of the same public text against those actual sandbox captures.
   Source projection reused; two fresh audience calls; two correction captures.
   This tests correction of our own interpretation, not a revised government file.

Result: 5 actual live calls, 8 decisions, 4 captures (2 control updates + 2
corrections), 4 quiet, zero production/external alerts. Four command retries
returned identical snapshots with no additional calls. Future s04 evidence was
404 before release and 200 afterward. Exact shared factual projection digest
across both audiences:
`b261aaa97e0c1b3ca966ab01dc317ea33c1b10d9f9b2a7ca3ca472ea00159fcb`.

## Interpretation quality and limits

Retained `01-shadow.json`: pending Board action 0.98; evidence that final Board
adoption occurred 0.01; evidence materially limits that adoption claim 0.99.
These agree with the supplied prior recommendation/future Board action and do
not upgrade an agenda/proposed resolution to final adoption. Legal status and
reviewed authority remain unknown throughout.

The stance head selected proponent at only 0.59 (confidence 0.45; unknown 0.41).
The illustrative 0.8 projection threshold therefore retained **unknown**, not
neutral. The text expressly reports a Planning Commission approval recommendation,
so this is a weak/underconfident result relative to the authored expectation,
not demonstrated provision-specific stance reliability.

Initial land-use objective 0.40 and novelty 0.31 were unresolved at the diagnostic
thresholds; school IT objective 0.02 and novelty 0.16 supported silence. No useful
positive land-use alert was demonstrated. Partial extraction independently causes
ordinary attention withholding. Stored first-land-use quiet reason is
`semantic_unknown`, not a claimed passing positive-relevance case.

Corrective-read objective/novelty: land-use 0.40/0.22, school IT 0.03/0.18.
The model did not reliably recognize correction novelty. **Host correction policy**
preserved a linked material correction of its actual unsupported prior capture,
including for the otherwise irrelevant audience. Those two captures demonstrate
the correction safeguard, not provider correction-family qualification.

This is one reused public source with two invented purposes and a synthetic
negative control. There are no independent accuracy denominators, held-out human
labels or legal-effect/production-readiness claims. MAT-040 remains unqualified;
its human-reviewed-label and independent-support requirements are unchanged.

## Verification and remaining work

- `python -m unittest discover -s tests/integration -p test_civic_exports.py -v`:
  10 passed at final adapter code, including restart/replay, two reports of one occurrence, separate later
  appearances, jurisdiction collisions, malformed rows and changed derivations.
- `python -m unittest discover -s tests/semantic -p test_civic_attention.py -v`:
  4 passed; source/audience separation, unknown versus neutral, no legal authority.
- StateCivics `run_gate.sh statewide --archive` at `bf92f7452`, four focused
  replay/civic/live-hook/API modules: 42 passed, zero skips, injected HTTP only.
  Earlier failing setup/bounds attempts are retained and superseded, not counted
  as passing checks. Source reading was expanded to an explicit supported 64 KiB
  bound; invalid/unexecuted source results now refuse instead of becoming output.
- Separate exact PostgreSQL regression controller attempted at the same commit,
  refused before tests: Docker `all predefined address pools have been fully
  subnetted`. Its owned cleanup completed. No other network was deleted. The live
  run did exercise actual PostgreSQL through the existing rehearsal network;
  that does not replace the blocked complete regression selection.
- Full `unittest discover -s tests -v` was attempted at the earlier `eae62d6`
  snapshot, then deliberately interrupted after 435 completed checks with no
  recorded failures. It has **no full-suite verdict**. The final adapter delta
  passed all 10 focused checks, and all four source-question checks passed.
- Two-pass Matter reviews: initial adapter review, expanded eight-file review,
  five-file checkpoint delta and final two-file refusal delta. Confirmed findings
  fixed; final delta has zero findings, zero warnings. Receipts under ignored
  `data/validation/civic-source-integration-20261028/`.
- State review covered 11 original files, seven guard-delta files and three final
  files, two rounds each, zero coverage warnings. All confirmed functional
  findings fixed. Two final low comments concern future constant synchronization
  and adding a civic preflight unit assertion; current model/timeout match the
  interpreter, and the actual civic zero-call preflight verified packet custody.
  They are not reported as a clean zero-finding State review.
- Final State archive check at `720637332`: 43 passed, exit 0, with closeout SDK
  wheel `5ffc85bc3982197553ca6f114e281e87ae3908b824412173e652e6fa0c177230`.
  Default image without SDK: 10 passed/3 expected skips. One intermediate
  43-passing run returned gate exit 78 after HEAD moved during verification;
  the stable archive rerun supersedes it. The generic gate message claimed an
  env refusal, but tests had executed; no entrypoint guard was bypassed.
- Post-review real-source import/replay (`import-final/receipt.json`) verified
  one subject, three claims, one occurrence, eight retained native identity
  proposals and a source-linked durable checkpoint; zero provider calls.
  Final fully-refused/empty-package handling is covered by the focused checks.
- Later launcher preflight at `~/ks-rehearsal/matter-live-20261028T224653Z-9680/`
  made zero calls, copied/hashed the exact external input and mounted the copy
  read-only. Existing run-budget query returned 1/32; preflight consumed no slot.
  The original live packet was retrospectively copied only after matching its
  recorded preflight digest; this is not described as a pre-run custody copy.
- Retained audit: five valid native responses/exact numeric values; source-only
  request contains no audience comparison; one shared factual projection;
  retries/cutoff checks passed; 41 bounded files scanned, no credential echoes.
  `summary.json` SHA `ebf835f127110e86e717517e061a64fd75582d79c0e08653c457e1d0f1c9e061`;
  `source-projection.json` SHA `6ed21aafe4ed6b79512efe323a8c823cbb3dcaa365a648b28a6cd9c25e334538`.

Full MAT-048 still needs the MAT-047 reviewed profile/authority handoff, wider
stage/vote/authority cases, and source correction/withdrawal propagation with
historical/current/fresh-delivery evidence. Full MAT-049 still needs those
prerequisites plus its wider purpose/territory/deadline and stale-correction
acceptance. A supplied recommendation alone must not be turned into final state.
The next quality investigation is the weak stance/positive land-use interpretation
and bounded evidence sufficiency; do not tune this exploratory case and call it
held-out success. DIAT is not required for this work.

Original installed walkthrough-schema failure was fixed earlier in PR #21;
MAT-077's broader distribution work remains separate. No infrastructure,
PostgreSQL backend, DIAT or alert-writing expansion was introduced. Storage was
56 GiB free before image reuse, 53 GiB at closeout; reserve 50 GiB/task cap 10 GiB.
The live artifact root is about 11 MiB. Both repositories have one worktree.

### Concurrent ticket allocation discovered at closeout

Read-only closeout found StateCivics branch `ks1119-ks1120` with an unrelated
KS-1119 ticket (commit `52b5920cd`). Our civic ticket is
`tickets/KS-1119-civic-public-source-monitoring.md` on
`feat/civic-real-packet-monitoring`. Both branches and their unique work are
preserved; no transcript/DIAT code was changed. StateCivics' stable-ID rule means
allocation must be reconciled before integration. Owner input requested for moving
our newly introduced, unmerged civic ticket to KS-1121; no renumbering performed
without that input. This is a branch-integration blocker, not a live-test failure.
