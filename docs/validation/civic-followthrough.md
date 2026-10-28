# Civic evaluation follow-through

PR #20 merged into main at `838f00bb3162fe9cf5c706b8cdfab3cefb395fd8` on
2026-10-28. The operator waived waiting for GitHub CI; the tested head and
recorded independent reviews were retained. No branches were deleted.

This pass reuses the existing environment, KS-1105/KS-841 replay, crawler ZIP
custody/extractions, MAT-072 access dispatcher and MAT-020 resource ledger.
KS-1105 is recorded done with actual PostgreSQL and browser receipts; this is
not permission to duplicate or redeploy it. The receiving run is presently
synthetic/deterministic, with live-provider and civic acceptance still separate.

Storage at start: about 59 GiB free, 50 GiB reserve, 10 GiB additional task cap,
estimated peak below 1 GiB. Tracked output is code, synthetic tests and receipts.
Real packets/review material and live responses stay under the external private
`~/.local/share/matter-validation/` root. No bulk extraction, new environment,
new stack, corpus/media duplication or cleanup is planned.

Selected work: independently fix the installed walkthrough resource lookup;
prepare a broader source-grounded review/evaluation pack from saved public
artifacts; implement the bounded MAT-022 protocol using actual host control,
budget and intake ports; add MAT-040 calibration/report mechanics without
asserting empirical qualification. Status and executed checks follow below.

## Public source review/evaluation pack

The existing KS-1105 receipt confirms completed no-login synthetic replay,
12 releases/48 audience decisions/19 captures and recorded PostgreSQL/browser
checks. This pass reads that evidence rather than recreating the stack. The
existing JEV research and KS-738 pilot motivate negative/counterevidence cases
but do not establish independently reviewed held-out alert labels. A request
for the testing team's existing pack is pending; engineering work continues.

Four public attachments were selected from the same verified latest dropoffs:
Shawnee `r2q`, SHA-256
`5936d0a01f06faf63f37736955b24ac72d0c674eb38cfeb4c27982b265f86b3b`, and
Topeka `t`, SHA-256
`10978258d5be0136c6876bb11c12d142cecfdd3a3b79f0dfa655df2a6e84a957`.
They cover the previously exposed SS4A close-out, permission to solicit annual
supplies bids, a draft zoning ordinance, and the corresponding planning
commission recommendation. Three additional original PDFs were fetched from
their public official URLs without credentials and matched custody hashes;
saved extractions were reused without OCR. The old SS4A files were referenced
by external symlinks rather than copied.

The private external root is
`/Users/mfrieson/.local/share/matter-validation/civic-review-20261028/`.
`pack.json`, `protocol.json`, per-source `provenance.json`/`plan.json`,
`review-blind.json`, `run-summary.json` and actual provider starts/results retain
the inputs, source/version hashes, pre-call protocol and score-blind questions.
No independent reviewer identity/outcome has been invented. The four documents
span three conservative episodes: the two zoning documents stay together.
Historical document dates are not substituted for actual experiment availability.
The prior captures and analyst corrections remain explicitly experimental;
no government correction or actual client delivery is fabricated.

One fixed revision-2 question form asks generic document-stage alternatives,
final-action evidence, audience contribution, novelty and correction. It removes
source-specific interpretations from the current input and audience purpose.
The existing example accepts an external bounded plan, uses separate stable
source scopes, and reuses the same MAT-072 preparation/rendering/dispatch path.
Source text is supplied once in state instead of repeated in every question.
Original diagnostic behavior remains available without a plan.

All 24 scheduled calls completed (four documents × three histories × two
contexts), using `jev-1.14.0`, zero retries, capture-only delivery. Each source
run allowed six calls, 30-second request timeout, 300-second wall limit, 64 KiB
wire bounds and USD 0.02 reservation ceiling; the pack allowed 24 calls,
1,200 seconds and USD 0.08 total ceiling. Actual native/neutral responses and
requested/resolved model identities remain external. Fresh calls, recorded
response revalidation, software conformance and qualification stay separate.

Observed findings, not accuracy estimates:

- Relevant objective scores were 0.87–0.97; school-IT objective scores were
  0.01–0.02. No school-irrelevance answer was embedded in that audience description.
- Exact-duplicate novelty was 0.02–0.04 across documents and audiences, while
  objective relevance stayed high for the relevant audience. Novelty and
  relevance were usefully separate in this revision.
- The bid document was classified as a pending proposal/authorization request,
  not an already open bid invitation or awarded purchases. Planning minutes
  were classified as a recommendation, not final city adoption.
- Final-action scores remained 0.01–0.19. This set has no independently verified
  affirmative final-adoption example, so false-negative performance is untested.
- The same draft ordinance switched from C (proposal) to E (unestablished/mixed)
  in one school-IT duplicate case; Choice confidence was low there (0.35).
  Factual-stage interpretation should not change merely because the audience
  changes. Source-only factual evaluation and audience consequence remain
  separate requirements before consequential use.
- For the zoning draft, correction scores 0.65–0.66 may overstate contradiction:
  missing final-adoption proof is not proof an adoption claim is false. In
  contrast, minutes explicitly recommending approval supported correction of
  the experimental prior claim of rejection (0.95–0.99). These need independent
  adjudication; the scores themselves cannot establish correctness.
- Irrelevant but new source information still received novelty 0.62–0.81.
  Novelty alone is therefore unsuitable as an alert policy. No calibrated
  attention/outbox decision was published from these raw judgments.

Every selected case is now exposed exploratory/tuning material. No untouched
held-out claim or passing empirical certificate follows from these calls.

The 24 calls consumed a price-basis estimate of USD 0.005888274 in input
charges, against USD 0.066060288 conservatively reserved (below the USD 0.08
pack ceiling). Actual billed cost was not observed. Reported token usage remains
in each native/neutral response; estimates are not a billing receipt.

Each result was subsequently reopened under the same host authority/access
policy, revalidated from retained raw bytes and rebound to its exact guarded
render manifest. Five frozen per-head corpora preserve the PDF/extraction
lineage, 24 trials each, and all three episodes' exposure. This was recorded
replay, not 120 additional HTTP calls. All five fits returned `insufficient`:
24 unlabeled cases each, zero eligible independent labels and no usable held-out
episode. `review-blind.json` withholds scores for reviewer handoff. Its blank
outcomes and unreviewed status remain intact. Prototype gates used only to
exercise refusal are not approved production acceptance targets.

Report SHA-256 references under the external root:

- `p0/source-grounded-v2-live/report-913355277541541.json`:
  `5ebfb978fb73ed20ddcc980bf25b3a23add2c1fb5ff9d1f947ff3e8a81736c74`
- `p1/source-grounded-v2-live/report-913370017739791.json`:
  `572c78262bb789dab6e620428aebd80cdc943be28a209cee2a8121a0cd1cfb39`
- `p2/source-grounded-v2-live/report-913384070276875.json`:
  `6164e3e15a8f5b44b5bdf1f0d3fa8f622e1a01059edaca45c82b5730be1981f0`
- `p3/source-grounded-v2-live/report-913398318019875.json`:
  `659b78110d164f824cd841ea8c4af7362fbf4c9b0d5c31ff82817a999e3b6493`

## Implementation and validation in progress

MAT-022 adds the bounded investigation protocol described in
[its API](../investigation.md). Existing control transactions, committed resource
reservations and actual payload verification are reused. Initial focused runs
found and fixed a projection-reference schema typo, duplicate target entries and
a shadowed payload local; the corrected combined run passed 26 tests in 43.635s.
That run covers 13 investigation integration tests, three work-key tests, nine
calibration tests and one installed-asset regression test.

MAT-040's fitter, held-out reports and reviewed-certificate candidate construction
are implemented as software mechanics. Synthetic pass/fail conformance is not
empirical qualification. The external source pack is deliberately unlabeled and
therefore cannot pass. Real qualification remains blocked, not done.

The separate default walkthrough resource lookup now uses the bundled schema.
Checkout regression passes alone do not close the installed-package gap. A wheel
has been built and installed into an isolated target; the full test run is in
progress from outside the checkout with that target first on the import path.
Independent two-pass subscription review is also in progress. Final outcomes,
fixes and source inventories will be appended before closeout.

## Reused crawler and receiver coverage

A fresh filename/mtime check still identifies Shawnee `r2q` and Topeka `t` as the
newest local dropoffs. Both already contain `bundle/matter_source_claims.json`
and its pinned schema. T-238's earlier missing-claims observation predates its
October 22 delivery; it is not a current absence claim. The existing claims
exporter and the KS-1105 no-login rehearsal must be reused.

The exact MAT-047 authority/applicability export and reviewed-host attestations
have not been verified from these general source-claim bundles. MAT-047 remains
crawler-owned and planned in this repository's cross-repo roadmap. T-090 remains
in progress and records source identity/lifecycle/crosswalk work and receiver
coordination; its older receiver observations are dated evidence, not a new live
failure. MAT-048 waits on MAT-047, MAT-049 waits on MAT-048, and MAT-050 additionally
needs core qualification/useful-silence and receiving evidence. No crawler or
StateCivics code, deployment or ticket was changed in this pass.

The public-source run observed 140,197 input tokens and 4,140 output tokens.
Provider total-token usage and actual billed charges were not reported. The
price-basis estimate above is computed from observed input tokens, not a bill.

## Core release evidence scope

MAT-025 reuses 40 selected existing behavioral assertions, including the new
receipt-refusal checks, rather than rerunning a new simulated-live stack. Its
frozen plan maps CORE-01–24 and AC-1–4 to exact named tests. Runtime, schemas,
assertion source, synthetic fixture inputs and actual SQLite settings are pinned
before execution. Its report explicitly leaves provider accuracy, live
usefulness, StateCivics acceptance, other backends and physical power loss unrun.
This is a separate bounded core qualification, not a substitute for MAT-040.

The first frozen 40-check core matrix passed in 415.967s. Review then identified
reporter fixture-error handling and further investigation finish-race/alternative
source paths. Corrections and their negative controls are being verified; the
first matrix is retained as a named earlier source snapshot, not silently
attributed to the eventual final source. The full installed run likewise freezes
its built runtime; any later review deltas need their own installed checks.

The initial custom installed-suite launcher was aborted after its missing
`__main__` guard caused spawned workers to import the launcher recursively. A
second early run was stopped to correct a too-strict assertion about downward
rounding of a tiny statistical bound. Neither is a passing full-run receipt.
The replacement uses standard `python -m unittest discover`, outside the checkout
with installed code first on `PYTHONPATH`, the repository only for test imports,
and `TMPDIR=/private/tmp` for this macOS host. Package walkthroughs separately ran
with isolated Python and no schema directory. No multiprocessing test failure
was hidden as a product success.

The current built wheel has 197 runtime/SQL/schema files, each byte-matched to
source (`stable-runtime-manifest.json`). Compared with the wheel used by the
ongoing full run, only `matter/investigation.py` differs and the qualification
report schema is newly packaged. The installed focused run on this current
wheel passed **43 tests in 96.338s**: 25 actual investigation cases, work-key and
asset regressions, ten calibration cases, plan-isolation and three reporter
refusal cases. Checkout investigation checks separately passed **25 tests in
77.977s**. The current wheel's three walkthroughs also ran under isolated Python
outside the checkout, with no schema directory. This directly closes the narrow
walkthrough resource-lookup failure; the wider MAT-077 ticket remains planned.

Task-local ignored artifacts occupy about 20 MiB and the external source/run
pack about 6 MiB, well within the storage cap. Archive inspection found no
credential/media/corpus paths. The value-level credential audit scanned 944
public/retained files (including decoded raw-response fields), about 8.3 MB,
with zero credential matches. No secret values were printed.
