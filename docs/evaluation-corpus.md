# Frozen evaluation episode manifests

MAT-036 supplies an offline corpus contract in `matter.evaluation`. It prepares
source-linked data for later evaluation; it does not run the MAT-038 harness,
fit thresholds, issue qualifications or call a provider.

```python
from pathlib import Path
from matter.evaluation import load_jsonl

corpus = load_jsonl(Path("tests/fixtures/evaluation/episodes.jsonl").read_bytes())
print(corpus.sha256)
print(corpus.denominators()["counts"])
prefix = corpus.prefix(as_of={
    "state": "known", "value": "2026-01-01T00:00:03Z", "precision": "second",
})
inputs = prefix["included"]
```

The six explicitly synthetic episodes cover routine work, an unrecovered
failure, repeated reports of one execution, a misleading success wrapper, a
late correction, and a quiet unlabeled interval. Their nine declared reference
cases produce three primary eligible cases, one explicitly excluded case, one
unlabeled case, one teacher-only case, one derived-only case, one disputed case
and one unresolved case. These are fixture counts, not measured accuracy.

## Closed manifest and exact references

A manifest has `schema_version: "matter.episode-corpus.v1"`, `id`, `scope_id`,
an exact core `component_ref` for `extraction_profile`, and `episodes`.
`freeze_corpus(manifest)` validates and captures canonical bytes. All exposed
JSON values are detached copies; changing a caller's original dictionaries or
the source file cannot change an existing frozen corpus. An optional
`expected_sha256` refuses a changed manifest. The digest uses the existing
kind-framed Matter canonical algorithm; `source_digest(original_jsonl_bytes)`
can independently retain the original file-byte hash.

Each episode contains:

- An opaque `id`, matching `scope_id`, and explicit closed `boundary` interval.
- `sources` with exact `{id, revision, sha256}` source-byte references,
  `available_at`, and an artifact descriptor.
- `observations` with immutable IDs, an exact source reference, separate
  `available_at` and `occurred_at`, occurrence IDs, provenance groups,
  derivation kind, and explicit parent IDs.
- `occurrences` with exact bidirectional observation memberships. A copied
  report retains its original occurrence IDs and inherited provenance groups.
  Summaries and corrections also retain parent provenance; they do not become
  independent corroboration.
- `cases` enumerating association, recovery and attention reference questions,
  target observation IDs, and explicit eligible/excluded reasons. Cases exist
  independently of labels so unlabeled and quiet episodes remain counted.
- `labels` with unique ID/revision, case ID, origin, review status, outcome,
  reviewer kind/role, review time, exact observation/source evidence pins, and
  a reason. Outcomes are explicit domain-owned text, not a universal label set.

Only declared fields are accepted. Unknown IDs, altered hashes, missing
reviewer provenance, missing evidence, duplicate identities, inconsistent
occurrence membership, invalid derivation, cross-scope episodes, reversed
known chronology and evidence unavailable at review time are refused. A shared
source, observation or occurrence identity across episodes must retain its
exact content. This preserves overlap for later grouped partitioning; it does
not implement MAT-037's splits.

Known UTC availability retains nanoseconds. Unknown time reasons remain
explicit. Event time does not establish availability. Parents must precede
derived reports in the manifest, and equal-time order follows that explicit
sequence without claiming a physical order between simultaneous events.

## External artifacts and byte verification

An artifact is either `{kind: "synthetic", text: ...}` or
`{kind: "external", reference: ..., permission_reference: ...}`. The former
checks its exact UTF-8 source hash immediately. The latter contains references
only and never opens a path, performs a fetch, or embeds private content.
The host must keep real exported sessions, rosters, audio and source documents
outside this repository. The synthetic tag is a host declaration, not an
automatic privacy classifier.

`freeze_corpus(manifest, source_payloads={
(episode_id, source_id, revision): exact_bytes})` can validate bytes already
supplied by an authorized host. Unknown keys, non-byte values and mismatching
hashes are refused. These bytes are verified transiently and are not copied
into the retained manifest. `source_verification` reports `verified` or
`not_checked` separately from the manifest digest. Byte verification at capture
does not establish continuous availability, content truth or source authority.
A permission reference records the host's declaration; it does not authenticate
the host or grant access. No source text can issue a trusted control or action.

Unverified external sources cannot supply admitted prefix inputs or qualify a
primary reference case. Their metadata can still be frozen and audited without
pretending that unavailable bytes were inspected.

## Prefixes and reference denominators

`prefix(as_of=known_time)` reports `included`, `excluded` and `unknown` inputs.
Only the `included` array is an input packet. The other arrays are diagnostics
and contain identities of later or unavailable inputs, so they must not be
sent to a chronological evaluator. Inputs expose exact observation/source
references, not reference labels, case outcomes, future source revisions or
complete occurrence membership lists. Source hydration remains a host duty.
Use opaque identifiers in real manifests; a descriptive name can itself reveal
an outcome that a chronological experiment intends to withhold.

Availability gating is inclusive and applies before event time. A known input
also needs verified source bytes and admitted parents. Unknown availability is
reported as unknown, never guessed. Prefix limits explicitly state that input
gating cannot establish a model's ignorance of later facts and cannot simulate
wall-clock latency or concurrent completion.

`denominators()` counts every frozen case exactly once. Its categories are
`eligible`, `excluded`, `unlabeled`, `teacher_only`, `derived_only`, `disputed`,
`unresolved`, and `unverified`. Label counts retain independent, teacher and
derived origins separately. Only an eligible case with verified target and
independent-review evidence, an agreed accepted independent outcome, and no
disputed/unresolved independent labels enters the primary eligible set.
Disagreeing accepted independent outcomes remain disputed. Teacher/model labels
cannot promote themselves to independent human reference evidence; teacher
disagreement also cannot overwrite an independent reference outcome.

These are full frozen reference-data counts, not historical provider inputs.
No predictions or accuracy, confidence intervals, release gates or support
thresholds are computed. Host declarations of independent review are retained
for audit; this module cannot prove a reviewer's actual independence.

## Bounds and JSONL capture

The default format is one strict JSON header line followed by one strict JSON
episode per line, with a final newline and no blank rows. `load_jsonl` takes
an original bytes snapshot, not a mutable path. It rejects duplicate object
keys, floats, unsupported versions and incomplete rows through the existing
canonical decoder. Captures are bounded to 8 MiB, 256 episodes and 4096 total
declared source/observation/occurrence/case/label items. Large private datasets
need a later explicitly bounded adapter; this module does not claim year-scale
replay capacity.

The existing [evaluation contract](evaluation.md) remains governing. Source
review, synthetic contract tests, provider evaluation and live usefulness are
separate evidence. See the [MAT-036 receipt](validation/MAT-036.md).
