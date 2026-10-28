# MAT-040 label review and proposed qualification targets

Preparation is complete; empirical qualification is not. The work reuses the
existing public-source pack, score-blind worksheet, retained exploratory JEV
responses, corpus/split contracts and calibration implementation. No new client,
rehearsal infrastructure, provider call, production alert or certificate was
created in that preparation pass. The operator has since approved the exact
pilot targets and assigned the agent as testing team; see the
[approval record](MAT-040-target-approval.json) and
[executed study receipt](../validation/MAT-040-approved-study.md).
MAT-040 remains blocked on human reference provenance, sufficient independent
support and supporting held-out results. Team nomination and target approval
are no longer pending inputs. Artifact descriptions below retain the original
preparation checkpoint.

## Prepared artifacts

The external handoff is
`/Users/mfrieson/.local/share/matter-validation/mat040-label-targets-20261028/README.md`.
It gives the existing testing team a concrete first-pass procedure and points
to source material by exact path/hash. Real documents, review data and corpus
manifests remain outside Git. Original inputs were byte-checked and unchanged.

- `blind-review/worksheet.json`: 120 blank label slots across 24 source/history/
  audience cases, with unique IDs and original wording/criteria. No model
  outcomes, draft labels or scores are included. Reviewers must disclose prior
  exposure; score-free files cannot prove an unexposed reviewer.
- `blind-review/sources.json`: the four existing source text/PDF references and
  hashes. Review the exact supplied text for semantic labels; PDF/extraction QC
  is separate. Unavailable image facts cannot silently become model inputs.
- `author-only/draft-labels.json`: 120 source-cited model-origin drafts, all
  unresolved and explicitly non-independent. There are 113 proposed outcomes
  and seven deliberately ambiguous outcomes. All 120 still need independent
  review; seven is not the count of unreviewed labels.
- `author-only/corpora/` and `assessment.json`: actual eligibility/fit checks via
  the existing runtime. Each of five families has 24 teacher-only cases, zero
  independent eligible cases, an insufficient fit and no usable held-out group.
  Exposure history remains intact. No new trials were supplied to fitting.
- `after-first-pass/exploratory-disagreements.json`: eleven review leads comparing
  draft proposals with retained exploratory interpretations. These are not
  established model errors or accuracy measurements. Eight concern novelty
  without an established school-IT contribution, two unsupported correction of
  an adoption claim, and one draft-stage interpretation. The 0.5 display rule
  is not a qualified threshold. Keep this file away from the first blind pass.
- `blind-review/candidate-pool-metadata.json`: 24 recruitment candidates from the
  two previously verified crawler ZIPs, with saved-text member paths and custody
  metadata. Only metadata was read; source content was not opened or copied.
  Different source hashes do not establish different occurrences or non-exposure.
  This is not a held-out corpus, an availability attestation or an egress grant.

The old review pack is four documents in only **three conservative lineages**;
its 24 calls and 120 question observations do not create 120 independent episodes.
Every selected old case is exposed development material. Human adjudication can
improve its tuning labels but cannot make it an untouched qualification set.
The existing rehearsal/simulated-live team should supply or attest a fresh cohort;
there is no reason to build another stack or reviewer service.

## Labeling decisions needing review

The seven undefined outcomes are six versions of one close-out/request
classification ambiguity, plus one draft-versus-prior-adoption novelty case
without a matching history time boundary. The current stage alternatives mix
kind of action with procedural status: an amendment awaiting signature can be
both a close-out and a pending request. Preserve that ambiguity rather than
force an oracle or rewrite historical labels to match JEV. A question change
requires a new semantic identity and fresh evaluation.

Other draft flags ask reviewers to confirm case/event/time alignment for
corrections and the meaning of purpose-conditioned novelty. An absent final
adoption proof does not establish that adoption never happened. A new source
fact can be irrelevant to the named audience; the current novelty wording asks
about a supported contribution, which needs an explicit, reviewed interpretation.
The source set has no established affirmative final-adoption example, so it
cannot support both polarities of final-action qualification.

Independent human returns must include actual reviewer identity/role, review
time, source/observation hashes, evidence locators, scope/time interpretation,
status and disagreements. Do not relabel the author's drafts as independent.
A qualified second adjudicator is needed when a real disagreement remains;
no fictitious consensus or reviewer identity is recorded by this preparation.

## Approved first qualification study

The machine-readable [pilot target proposal](MAT-040-pilot-targets.proposed.json)
is the immutable original proposal. The operator explicitly approved its exact
pilot settings in the subsequent [approval record](MAT-040-target-approval.json).
The original file remains unchanged; approval was not inferred from a merge.
Its exact byte SHA-256 is
`e8b2ae1ad3d11fc33571f24b587802e4a5da16f49f1556d648462ad61e2b9adf`;
the external proposal copy is identical. The separate stricter future-use
proposal remains outside this pilot approval.

Start with the exact revision-2 audience-objective question on the declared
public county/city text and finance, land-use and school-IT experimental purposes.
This is a capture-only/manual-review pilot. It does not authorize production
alerts, qualify other question families, transfer to arbitrary clients or stance
classification, or include the later custom alert-writing step.

Approved pilot study settings:

- At least 95% lower correctness bound for each accepted decision polarity at
  95% family-wise confidence across two polarities. Use the existing one-sided
  grouped Clopper-Pearson procedure with Bonferroni adjustment.
- At least 100 accepted independent lineage groups per polarity. A group is
  correct only when every accepted case for that polarity is correct. This is
  accepted-group correctness, not per-message accuracy, recall or all-stream
  usefulness. Repeated histories/audiences do not create independent groups.
- At least 50% independent eligible-group coverage; at most 2% eligible groups
  containing failed/missing/mismatched/unavailable provider observations.
  Unsupported automation should abstain for manual review. Quiet misses still
  need the separate MAT-042 outcome assessment.
- A fixed nine-candidate grid: positive probability minimum 0.8/0.9/0.95 crossed
  with negative maximum 0.2/0.1/0.05. Those proposals are development-informed,
  not selected thresholds. Fit only on tuning; inspect qualification once;
  preserve final material separately. Freeze before scoring the fresh cohort.

Approval covers these risk/scope settings. A runnable calibration plan still
needs the actual fresh corpus/split digests, complete exact method identity,
source permissions and valid model resolution. The old exploratory domain
fingerprint explicitly pins the four old source texts; it cannot be reused as
approval of a new cohort. No current exploratory certificate can transfer.

The custodian must keep qualification/final labels out of question design and
threshold selection. Give fitting only the existing tuning partition; never put
review labels into provider state. Release locked qualification labels only for
the predeclared held-out evaluation after tuning selection. “Fresh” concerns
exposure in this study; it cannot prove the hosted model never encountered a
public document during pretraining.

## Support and capacity assessment

Actual calculations with `lower_accuracy`, using alpha 0.025 per polarity,
show that zero errors need at least 72 accepted independent groups for a 0.95
target (lower bound 0.950055916294), or 368 for a 0.99 target (0.990025945173).
At 256 groups, even a perfect observed sample has lower bound 0.985693637270.
These are planning bounds under the implemented independence assumptions,
not new measured provider accuracy. Errors, abstention and weak class coverage
increase the required material. The proposed 100-group floor is not a promise
that any 100 cases will pass.

The current `FrozenCorpus` cap is 256 episodes for the entire corpus, including
all splits. Thus a 99% two-polarity target at this confidence is currently
impossible in one corpus. The separate stricter proposal for authority/correction
needs an approved study and a reviewed capacity change; no limit was raised or
qualification gate weakened here.

A 100-tuning/100-qualification group design can fit with final material only if
real contrasting cases within a lineage supply both polarities and the episode
layout also fits the cap. Disjoint class pools, multiple episodes per group or
abstention may exceed it. Do not fabricate pairing or silently combine unrelated
reports to get support. The data custodian must verify the real layout first.

## Verification and remaining handoff

Task receipts live under ignored
`data/validation/qualification-handoff-20261028/`. The preparation used existing
source bytes and metadata; original pack/worksheet/frozen files are hash-unchanged.
The blind-sheet audit checked all 120 outcome/reviewer/evidence slots are blank
and uniquely mapped to drafts. Every draft evidence excerpt round-trips to its
exact source character range/hash. Corpus/split/calibration checks keep all
teacher drafts ineligible, preserve prior exposures, and refuse fitting.
Target-bound calculations and metadata exclusion/uniqueness checks passed.

The existing calibration/corpus/split regression suite passed **46 tests in
10.909s**. No runtime code changed and no new full discovery, installed wheel run
or live provider test is claimed. Repository projection/validation and independent
change-review receipts are recorded in the validation closeout. Initial space
was about 58 GiB free; expected new artifacts below 20 MiB, with the existing
50 GiB reserve and 10 GiB task cap. No new environment, worktree or corpus/media
copy was created.

The operator resolved the two requested assignment/approval inputs. The agent
then screened fresh candidate lineages, completed 84 score-blind model judgments
on 42 new documents, verified all original PDFs and ran the eligibility gates.
Those results and the specific remaining requirements are in the executed study
receipt. Model assignment is not human reference provenance; the gate is kept
intact. No external reviewer nomination is being requested again, no approval
was fabricated and no qualification was issued.

Final repository checks passed: generated projections, validation (80 tickets,
104 requirements, 106 schemas, three walkthroughs) and whitespace/diff checks.
The two-pass subscription change review selected both changed JSON files,
reviewed both, and reported zero findings and zero warnings. Its project rule
covers key spelling; the reviewer also traced the numeric/region constraints.
This is a metadata/code-contract review, not independent human label review or
approval of the targets. Markdown and the external review data were outside its
selected scope; the checks above cover their stated invariants.

The target-proposal SHA was separately computed and matched between tracked and
external copies. Initial storage-receipt serialization rejected a floating-point
free-space value; recording it as a decimal string corrected that receipt, with
no source or label change. The final external handoff uses 563,201 logical bytes
(589,824 allocated at measurement), with about 59 GiB free. Later small closeout
text and metadata-review logs add bounded growth. Existing worktree archives
were untouched; no additional worktree was created.
