# DIAT meeting-learning profile

Status: governing research and integration design. Tickets MAT-051 through MAT-065 are planned. This document does not run experiments, change DIAT resolution/enrollment behavior, process the reported corpus, or deploy into any core project.

## Mission and explicit user requirements

DIAT owns the learning and formal-meeting implementation. Matter supplies neutral evidence, occurrence, assessment, dependency, temporal and attention contracts. The local crawler owns jurisdiction-specific source definitions and authority/profile exports. Experimental output remains advisory evidence.

The user reported approximately **315 hours of diarized commission meetings with roughly 5–10 recurring people** and requested longitudinal voice/behavior patterns and jurisdiction/committee fingerprints. Those are user-reported opportunity and scale assumptions, not a verified dataset inventory. MAT-051 must measure actual bytes, audio duration, usable speech, meetings, unique participants, provenance groups, available labels and missing features before claiming coverage.

The user also required all experiments to stay **DIAT-only on copied/exported evidence**. No core integration, deployment, automatic enrollment, human confirmation or production identity assignment is authorized by this roadmap. Semantic relevance is evidence-selection information; it is never an acoustic identity probability or a component added to a weighted identity score.

Original design inputs are [matterbrainstormspec](../../matterbrainstormspec), [matterjevmesh](../../matterjevmesh), and [jevinmatter](../../jevinmatter). The final formal-meeting section of the latter proposes recognition, motions, debate and voting as soft procedural context. Its historical claim of 446 interaction events has no corpus witness in this review and is not adopted as a measured fact. Personal-context retrieval was unavailable during this build; unseen prior suggestions are not invented.

## Current repository baseline

Read-only source audit: DIAT `da33bb1171bb537954f59b234c86cfa32cb2641c`; crawler `f2fd7d39f97fb4f3510e3edef9c0c852e0b5f36f`.

| Existing component | Reusable behavior | Boundary |
| --- | --- | --- |
| [Meeting handoff](https://github.com/mfreeze77/statecivicsai-diat/blob/da33bb1171bb537954f59b234c86cfa32cb2641c/docs/meeting-handoff.md) | Stable package/recording/track/turn IDs, original recording clocks, hashes, optional words, source artifacts and separate upstream result claims | Validation is not identity verification; the package itself is not a blind benchmark |
| [Behavior module](https://github.com/mfreeze77/statecivicsai-diat/blob/da33bb1171bb537954f59b234c86cfa32cb2641c/docs/behavior.md) | Opening/closing 1–5-grams, lexical n-grams, filler counts, speech-rate/timed articulation proxy, adjacent-word pauses and phrase–pause–continuation motifs | Descriptive support only; missing timing remains missing; punctuation is not prosody |
| [Behavior profiles](https://github.com/mfreeze77/statecivicsai-diat/blob/da33bb1171bb537954f59b234c86cfa32cb2641c/src/speaker_identity/behavior/profiles.py) | Mode-separated verified reference profiles, provenance-group balancing and query-group exclusion | No behavior vote modifies the acoustic resolver |
| [Identity-context evaluation](https://github.com/mfreeze77/statecivicsai-diat/blob/da33bb1171bb537954f59b234c86cfa32cb2641c/docs/identity-context-evaluation.md) | Frozen A/B/C/D packages, fixed acoustic candidates, historical/retrospective modes, labels only at reporting, immutable runs | Model decisions are private evaluation artifacts |
| [Crawler export](https://github.com/mfreeze77/statecivics-local-crawler/blob/f2fd7d39f97fb4f3510e3edef9c0c852e0b5f36f/src/civic_crawler/diat_export.py) | Copies completed native meeting outputs into a private package without another transcription pass | Existing upstream names remain unverified machine claims; audio/pitch/behavior availability is explicit |
| [Crawler minutes profile](https://github.com/mfreeze77/statecivics-local-crawler/blob/f2fd7d39f97fb4f3510e3edef9c0c852e0b5f36f/src/civic_crawler/jurisdictions/ks/ks_county_wyandotte/minutes.json) | Jurisdiction/body-specific source parsing conventions | It supplies source context, not an acoustic or procedural ground-truth label |

No procedure state machine, grammar parser, calibrated prosody identity feature or jurisdiction fingerprint learner was established by this audit. Those are proposed research and implementation below. Existing lexical/timing functionality should be extended through its interfaces, not rebuilt.

## Neutral-core and domain boundaries

Matter records anonymous or pseudonymous subject references, typed evidence relationships, assessments, uncertainty, temporal dependencies and proposed attention. Its core must run without DIAT, acoustic libraries, a roster, parliamentary vocabulary or jurisdiction code.

DIAT owns extraction, meeting-state inference, behavioral/fingerprint feature definitions, candidate-context preparation, ablations, labels and private reports. Planned DIAT artifacts live under `src/speaker_identity/experiments/meeting_matter/` and ignored `data/meeting-matter/`; these paths do not claim an existing module.

Civic authority remains with the crawler profile and the receiving application's reviewed authority contract. A learned chair role is not proof that the person had legal authority; a recognition cue is not a vote; speaker consistency is not verified identity.

An exported experimental assessment must name its model/prompt/profile versions, source/package/recording/turn IDs, original-clock spans, eligible candidate references, effective and available-at times, evidence exclusions, uncertainty reasons, and `authority: experimental_advisory`. Its payload cannot invoke a production assignment or create an enrollment.

## Corpus intake and experimental views

Use the existing meeting-package validator before preparing evidence. Retain upstream result files and original transcripts privately for audit; create model-visible views from an explicit field allowlist. Raw transcripts can contain embedded upstream names or self-introductions even when result files are separate.

Keep at least three views:

1. **Blind consistency view:** anonymous track IDs, permitted acoustic/lexical/procedural evidence and no verified identity labels.
2. **Frozen candidate view:** the existing evaluator's fixed acoustic candidate set and allowed roster/context evidence, with no additional candidate generated by semantics.
3. **Reviewer view:** source media and independent outcome labels, accessible only at the permitted annotation/report stage.

Every item carries occurrence, evidence-availability, identity-verification, identity-link-availability and import times where known. Strict historical replay refuses unknown or future eligibility; retrospective hearing-separated evaluation is labeled accordingly. A meeting date or import time does not establish historical availability.

One file can contain multiple meetings; one speaker track can mix voices; one source may be a re-encode or clip of another. Preserve recording-group and equivalence-group relationships before filtering by person or feature. A zero-second clock reset on an audio crop is invalid.

## Procedural evidence and soft state

MAT-052 and MAT-053 define source-linked procedural observations and a deterministic tracker. The initial event vocabulary is domain data, not a fixed core enum:

| Family | Candidate observations |
| --- | --- |
| Session/body | Call to order, recess, return, adjournment, reconvening as another body, unknown boundary |
| Agenda | Item called, deferred, resumed, consent grouping, item removed from consent |
| Floor | Chair recognition, self-identification, floor release, response invitation, interruption, overlap |
| Motion | Motion introduced, second, second not required/stated, amendment, substitute, withdrawal, reconsideration |
| Discussion | Presentation, testimony, question, answer, debate, procedural clarification |
| Vote | Vote called, roll-call response, voice vote, announced tally, reported outcome |
| Exception | Unintelligible event, unsupported procedure, missing span, conflicting role/sequence |

Track hypotheses about active body, agenda item, procedural phase, pending motion/amendment structure, floor holder and role assignment. Retain multiple possible states when the evidence supports them. Do not force every utterance into a canonical Robert's Rules sequence. A jurisdiction/committee profile may modify conventions, and absence of a second may mean unknown, not failure.

Transitions retain input event IDs, source intervals, rule/profile version, alternatives, and reasons. A late correction invalidates downstream procedural assessments. The tracker should recognize a conflict between procedure and acoustics without forcing the audio to fit the expected speaker.

Recognition can improve an anonymous floor hypothesis: “the next speaker probably holds the floor.” It cannot convert “Commissioner Lee was recognized” into a verified acoustic assignment. A chair can yield, change mid-meeting, act as an ordinary participant or share a microphone; a person can be quoted by someone else. These are required negative controls.

## Fingerprints are descriptive, versioned context

The word fingerprint names an experimental, reproducible profile; it does not imply unique or biometric proof.

### Jurisdiction and committee profile

MAT-055 estimates patterns such as recognition formulas, agenda order, motion/second phrasing, voting style, typical role transitions, interruption conventions, meeting modes and source reliability. Every profile includes training cohort and time cutoff, jurisdiction/body/meeting-type IDs, reference profile/override hashes, effective period, uncertainty, supporting spans and unavailable features.

Separate learned regularities from reviewed procedural rules. Shared meeting scripts must not become person features. A new chair or rule change creates a new context regime; a county profile cannot silently spill into a city or committee.

### Longitudinal person and roster context

MAT-056 studies recurring speakers only through reference evidence whose identity verification is independently eligible. Profiles separate prepared/spontaneous/unknown mode, time regime and recording group. Roster membership, attendance, seniority, seat position and “normally chairs this meeting” remain contextual claims, not acoustic verification.

Store roster versions and role intervals, including turnover, guests, substitute chairs, newly appearing people and missing participants. Reference coverage and unknown participants must remain visible. Do not freeze the candidate universe to the user-reported 5–10 recurring people.

### Feature research

| Family | Starting point | Proposed extension or evaluation |
| --- | --- | --- |
| Prefix/suffix | Existing opening/closing n-grams | Formulaic recognition/thanks versus individual patterns; names and self-introductions handled as explicit evidence views |
| Grammar | No grammar extractor established | Bounded syntax/dependency templates, clause/repair/hedge patterns, with parser/version uncertainty |
| Prosody | Handoff exposes feature availability, not computed pitch | Voiced pitch contours, intensity/energy, duration and emphasis measures from actual audio; compare within channel/mode |
| Pauses/rhythm | Existing adjacent-word gaps and motifs | Alignment-quality-aware distributions, phrase timing, response latency and interrupted-turn timing |
| Interaction | Existing turn/source spans | Question/answer handoff, turn-taking, overlap, backchannels and chair-mediated transitions |
| Agenda/topic | Exported contextual documents | Align utterances to items and phases without using future minutes or gold identities |
| Room/microphone | Available recording/source metadata | Room/channel/mic regime and shared-mic controls; missing metadata stays unknown |

Each feature must state units, denominator, extractor version, input/source hash, original-time window, quality gate and failure reason. Pitch requires voiced audio analysis; punctuation cannot create intonation. An inter-word alignment gap is not proof of silence. A room or microphone signature cannot be rewarded as evidence of the person when it is merely correlated with a seating arrangement.

Keep raw acoustic scores, behavior comparisons, semantic relevance and procedural compatibility separate. Any experimental model that uses multiple features produces its own evaluated output; it does not relabel those inputs as independent identity probabilities.

## Conflict and identity boundary

MAT-061 composes evidence in a bounded experimental decision packet. The following must remain representable:

- Acoustic candidate absent despite a compelling semantic name cue.
- Procedure predicts the chair but the voice is inconsistent.
- A familiar opening phrase appears in several people's prepared scripts.
- The recognized person does not take the floor.
- Overlap or shared microphone makes the source interval mixed.
- An agenda association is uncertain or a later source contradicts it.
- A model/provider failed, required evidence is missing, or the profile is stale.

Allowed outputs are existing frozen candidates where the evaluation contract permits them, anonymous consistency hypotheses, `unknown`, `manual_review`, and recorded failures. An identity outside the frozen pool is an invalid decision. A matter can retain an unresolved speaker/turn question without asking Michael or enrolling a candidate.

The matter's assessment describes evidence, provenance, current uncertainty, useful next permitted check and what changed since its last assessment. It does not acquire the production resolver's authority.

## Comparable experiments and leakage controls

Preserve the existing four-arm definitions:

| Baseline | Evidence |
| --- | --- |
| A | Fixed acoustic candidates and their enrollment evidence |
| B | A plus eligible behavior |
| C | B plus unconditioned historical semantic retrieval |
| D | B plus candidate-conditioned, balanced historical semantic retrieval |

Do not silently rename an augmented condition “B” or “D.” MAT-062 adds a new versioned ablation family over exactly the same frozen queries, e.g. A+procedure, B+procedure, D+procedure, and independently switched grammar/prosody/channel/agenda factors. Preregister a bounded subset instead of running every combination by default.

All compared conditions pin query spans/text, candidate pools, roster, cutoffs, source groups, model/prompt/qualification policy and common evidence. Factor-specific evidence must be the only intended change. Report both the common evaluable cohort and each condition's missing-feature coverage; never improve results by silently dropping difficult examples.

MAT-063 preserves existing exclusions before ranking: query event, equivalent copies, entire query hearing, connected provenance group and unavailable future evidence. It adds procedure/fingerprint-specific checks: no held-out meeting in profile training; no future chair announcement or later corrected minutes in an earlier decision; no target labels in semantic history; no source-processing result masquerading as a human label; no condition-specific candidate expansion.

Strict historical inference and retrospective smoothing are separate named modes. If a method uses later turns to clarify an earlier floor transfer, its allowed lookahead must be explicit and it cannot claim streaming/as-of performance. Population separation alone does not eliminate room, agenda or repeated-script leakage; dedicated controls are required.

## Independent outcomes and usefulness

MAT-064 creates an annotation guide with independent reviewers, adjudication, uncertain/unresolvable labels, source visibility rules and measured agreement. Machine upstream identities are not gold labels. Unknown and unenrolled speakers, overlapping speech, guest participants, shared microphones, procedural exceptions and source failures belong in the held-out set.

Report different tasks separately:

- Anonymous within-meeting speaker consistency and switching errors.
- Floor/role/agenda transition quality and temporal boundary error.
- Frozen-pool identity precision/coverage, unknown handling, wrong-name rate and raw candidate recall.
- Incremental value of each evidence family and interactions.
- Stale, repeated, misleading or late attention; useful next-check contributions; missed useful interventions.
- Feature availability, calls, bytes, extraction/model time and cost.

Split and compute uncertainty by independent meeting/provenance group, not random neighboring segments. The small recurring population and reported hours do not establish broad generalization. Evaluate new meetings, changed chairs, room/mic regimes and at least a held-out institutional context before claiming transfer.

## Maintenance and revocation

MAT-065 governs profile/model/question updates, corpus additions, changed rosters, source corrections and revoked reference samples. Profiles retain their training manifests; removing a reference invalidates affected future assessments and pending hints while preserving old run receipts and their original inputs.

Detect distribution changes in feature coverage, speaking mode, chair role, room/channel and recurrence. Drift is a request for requalification, not automatic identity retraining or threshold relaxation. A failed/expired/inapplicable qualification must not become a fresh approved profile through a cache hit.

Export and replay always retain model requested/resolved versions, exact questions, extractor/calibration versions and availability clocks. Source removal/privacy handling is a domain-approved operation with explicit dependency effects; a “resolved matter” does not erase evidence retention obligations.

## Delivery order and acceptance

1. MAT-051 verifies the copied corpus and benchmark views.
2. MAT-052–054 establish anonymous procedure/floor observations and a soft tracker.
3. MAT-055–060 add independently versioned contextual and feature families.
4. MAT-061–063 compose experimental evidence and enforce comparable, leakage-controlled ablations.
5. MAT-064 provides independent labels and usefulness outcomes.
6. MAT-065 maintains only profiles whose evidence and qualification remain applicable.

Dependencies are detailed in the ticket registry; annotation and leakage design begin before experimentation, not after results. A small synthetic/private pilot is sufficient to validate mechanics. Large-corpus inference, production integration and enrollment changes remain outside this build and require separate concrete scope.

Every ticket starts `planned` with `completion.state: not_run`. Source inspection, schema tests, feature extraction, provider inference, human review, historical replay and live deployment are separate evidence stages. The first desired result is an anonymous continuing meeting concern that absorbs repeated observations, recognizes a supported change, and contributes a useful experimental hint without changing identity truth.
