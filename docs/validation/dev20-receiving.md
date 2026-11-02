# Dev20 receiving acceptance: saved-objective timeline

Matter inspected StateCivics main `c99710b60617acfdd05a31b75ddcb76bdb176c71`
read-only on 2026-11-02. KS-1156 adopts MAT-091 and KS-1126 run 4 demonstrates
both reported defects repaired on the receiving host: capture after an objective
revision and repeated same-subject captures under the unchanged budget.
This accepts that bounded SDK/host repair. It does not establish production
readiness, live JEV interpretation quality or formal qualification.

## Source, package and external artifacts

- Matter release: PR #41, merge `5cbdba17af46907bc537f5d791ef0f8b1eaef22e`,
  SDK `matter-foundation==0.1.0.dev20`. Runtime commit
  `401f1a4839c3b170b3c43269d8b5de8d3afa6b73` and tested commit
  `cf5578bd551cc5fd6a2248ee8783aebfc5356058` have the same runtime/schema bytes;
  see [MAT-091](MAT-091.md).
- Receiving image: `ks-test-runner:matter-401f1a4`, image ID
  `sha256:a240d63c2b62498ca0b1f1532f664203576a4e22d1c8b19e1ad3ebd0d56f68a0`.
  Matter independently inspected it in a network-disabled, read-only container:
  runtime and distribution both dev20, provenance helper importable, all **207**
  packaged files equal Matter's verified manifest, none missing/extra/changed.
  This verifies the image SDK, not the running backend's mounted code or store.
- StateCivics reports its rebuilt wheel SHA-256 as
  `5ca1f1762fbc7db3e8a0a2224ce67c2108c44a04d2ef1423875088715bd06fe7`.
  Matter did not rebuild that wheel here; the image contents were compared
  directly. Its wheel digest differs from Matter's local build; file equality
  supplies the cross-build comparison.
- Run phase pin: `5faf0ff9c2e39fa047f30f7bd480cd4b998082fb`. Restore, setup and
  objective creation ran earlier under `289685fd7`/`9702d6032`; do not describe
  the whole procedure as executed on the final pin.
- External source records: StateCivics tickets `KS-1156` and `KS-1126` and
  `.release/ks1126-timeline/preserved-run4-20261102/`. The manifest identifies
  run 4; Matter verified every listed size and SHA-256 against those files.
  Manifest SHA-256:
  `dc1cbb50de087a4492d494d97aabb572d4cb0de56c0264e6975c460f082629ff`.
  `run.json` SHA-256:
  `7df32e5ef6672c9cd7e18a3b4397aa1b9552a418def10bd8c1ae6e6921ddb9a7`.
  `RECEIPT.md` SHA-256:
  `514e7eb821dd507885ac7f8445ae1fde6c1b40fc2ca2ab4a4bc32c0179bcb4af`.

No source text, objective bodies, assistant messages, credentials or database
copies were imported into Matter. Local verification metadata is retained in
ignored `data/validation/dev20-receiving/`.

## Receiving behavior and checks

The host now separates current rule-input roots from baseline/history roots.
The provenance helper supplies grant candidates; the host authorizes each and
uses tokens covering the full granted dependency inventory. Old context pins
remain exact history, not current rule inputs. Each outcome measures both the
host-rule and attention preparation against the original 2 MiB limit.

Matter read the receiving logs, without rerunning the receiving suite:

- `.release/ks1156-gate/matter-tests.txt`: the two MAT-091 regression files,
  **6 passed in 301.34s** in the receiving image.
- `.release/ks1156-gate/t3.txt`: dispatch, model-capture and review-adapter gate,
  **24 passed in 946.23s**, 23 warnings, gate exit 0. This is a focused gate,
  not a new full statewide-suite result.
- The ticket records two reviews with 5 and 3 findings, repaired before the run.
  Earlier failing/intermediate gates remain earlier evidence, not final passes.
  KS-1156's implementation is merged; its inspected frontmatter still says
  `in_review`. Matter did not alter the host ticket.

Recounting the preserved run JSON agrees with its summary:

- 15 steps, 2 skipped; 27 dispatches: **22 captures, 1 exact reuse, 4 refusals,
  0 quiet, 0 withheld**. Each objective has 11 new captures: 10 replay-origin
  captures and 1 live-origin capture. Reuse is counted separately from capture.
- The edit made during s07 refuses `context_changed`; redispatch under the
  approved new revision captures. Its history context is encoding 1.1. The
  receiving host's own precheck and Matter's currentness fences remain distinct.
- The other objective's fifth capture succeeds. The authored corrected
  printings are labelled rehearsal material; they are not legislative revisions.
- Host-rule prepared inputs are **80,747–99,898 bytes**; attention preparation
  **44,613–54,806 bytes**, each against **2,097,152 bytes**. Matter checked the
  bounds for all 22 new captures; no budget increase or baseline omission.
- Of 24 probes, **22 are fenced**, **2 have no held version left to probe**,
  none is unfenced. Every probe reports zero comparisons touching a held
  version. Scope is the reached readers named in the receipt; MongoDB and
  Qdrant readers are absent from this stack, so this is not a test of them.
- The four refusals are the paused objective, the in-flight edit, and two missing
  comparison packets. They are not quiet decisions. The reprint is skipped by
  detector deduplication, and the future-event notice is skipped because no
  packet exists; neither is an executed semantic-silence case.
- The closing live-origin capture completes A's wake/review; B records pressure
  only. Both capture channels are `in_app`; the review records outputs unsent.

Matter's documentation-only follow-up passed `python -m matter render --check`,
`python -m matter validate` (91 tickets, 107 requirements, 109 schemas,
3 walkthroughs), all **18 repository checks in 0.723s**, and `git diff --check`.
No runtime changed, so the 1,552-test SDK run was not repeated. Receiving test
counts above come from inspected host logs, not tests rerun by Matter here.

## Meaning and remaining boundaries

The timeline dispatch explicitly injects `RecordedExecutor` (fixed probability)
into the deterministic host-rule path, including its closing live-origin step.
It makes no JEV call. The separate host assistant-review path is wired to the
existing real assistant; the receipt shows a completed review, not a retained
network trace or a new JEV trial. Matter made no provider calls while inspecting.
The wake's opponent trigger remains objective-wide, not an event-specific model
adversity judgment. No accuracy estimate or MAT-040/042/050 qualification follows.

The API-created-objective timeline and both MAT-091 receiving regressions are
now demonstrated. This run has no quiet outcome; silence/model discrimination
remain separate checks, not evidence inferred from refusals or skipped steps.
The non-admin real-form walk remains the owner-run post-activation step recorded
in KS-1126. No new sign-in infrastructure is approved or built here.

Run 4 overwrote run 3's principal JSON/receipt files. Run 3's console and ticket
figures remain; Matter did not retrieve or verify Dropbox version history.
Run 4 has its own preserved directory and verified manifest. The overwritten
artifacts are a limitation of the earlier before/after record.

StateCivics owns its activation packet, persistent store/image wiring and joint
activation with Workbench and state intel. Cadence, KS-1152 backup choices and
production facts remain owner/host work. A store written by dev20 must not be
opened by dev19. MAT-083's intermittent SQLite issue remains separate and open.
