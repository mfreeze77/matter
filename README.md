# Matter

Matter is a shared foundation for following a continuing subject, preserving its evidence, evaluating it under explicit rules, and providing a current, useful reason for a particular audience to care.

**The matter preserves continuity. An assessment records what the evidence means under a versioned policy, purpose, audience, and time.**

## Current status

This repository contains the governing design, a dependency-linked implementation backlog, portable core record/command/result schemas, strict canonical encoding, durable SQLite storage, immutable observation intake, persistent matter identity, explicit occurrence grouping, validation tools, and three runnable synthetic lifecycle walkthroughs. MAT-002 supplies the executable structural boundary: twelve record kinds, explicit success/failure results, and portable byte/digest fixtures. MAT-003 adds transactional persistence with checked revisions, exact command retries, immutable history, atomic receipts, migrations, and verified backup/restore. MAT-004 adds source-aware observation deduplication, exact payload storage, conflict receipts, explicit corrections, and source history filtered by evidence availability. MAT-005 adds exact scoped subject keys, continuing IDs across runs, and revisioned metadata. MAT-006 separates reports, happenings, and declared provenance groups with atomic membership corrections and covered counts; its bounded grouping operation brings the command inventory to eighteen variants. Claim/evidence semantics, semantic association, assessment, provider adapters, and native integrations remain planned in the backlog.

The walkthroughs are deliberately small: their fixtures already contain host-supplied associations and classifications. They demonstrate selected continuity and delivery rules; they do not infer semantic meaning, execute an agent hook, call JEV, train a speaker model, or establish production correctness.

## Run the scaffold

Use Python 3.11 or newer from the repository checkout:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e . -c requirements-test.txt
python -m matter validate
python -m unittest discover -s tests -v
python -m matter demo all
python -m matter tickets --ready
```

On Windows, activate with `.venv\Scripts\activate` instead. An installed CLI can use `matter --root /path/to/matter validate`. The CLI reads repository assets; it is currently checkout tooling rather than a self-contained production SDK.

No API credentials or live datasets are required. `validate` checks the JSON Schemas, every ticket record, dependencies and cycles, requirement coverage, generated Markdown/index consistency, local documentation links, and the declared outcomes of each walkthrough. Tests include negative cases so invalid records and stale behavior must be rejected.

## Use the portable contracts

The `matter.contracts` and `matter.canonical` modules work from an installed package without repository assets. All three core schemas ship with the package. This example uses a synthetic fixture from the checkout:

```python
from pathlib import Path
from matter.contracts import decode_record, error_result, record_digest

record = decode_record(
    Path("tests/fixtures/contracts/records/observation.json").read_bytes()
)
print(record["id"], record_digest(record))

failure = error_result(
    "ingest_observation", "example-operation", "E_STORAGE_UNAVAILABLE",
    retriable=True,
)
assert failure["status"] == "failure"
assert "outcome" not in failure
```

Use the strict `decode_record`, `decode_command`, or `decode_result` entry point on original JSON bytes. They reject duplicate keys, floating number tokens, invalid Unicode, unsafe integers, unsupported versions, and malformed envelopes. In-memory `validate_*` functions enforce the same value and shape rules after parsing. A returned record preserves unknown-time reasons, evidence references, and namespaced extension values; validation does not establish source truth, permission, or durable state.

Canonical record and command hashes bind their contract kind and version. Original-source hashes cover exact source bytes separately. Object key order does not affect normalized hashes, while ordered arrays and Unicode normalization differences are preserved. The [canonical specification](docs/contracts/canonical.md) defines the exact framing and committed golden vectors. With Node.js installed, run the independent positive-vector verifier:

```bash
node tests/fixtures/canonical/verify.mjs
```

See the [schema inventory](docs/contracts/schema-inventory.md), [compatibility matrix and API boundary](docs/contracts/compatibility.md), and [MAT-002 validation receipt](docs/validation/MAT-002.md) for the supported shapes and executed evidence.

## Use durable storage

`matter.storage.SQLiteStore` accepts a host-authorized scope and a synchronous
command handler. Each command atomically commits its checked record/projection
writes, operation receipt, and exact result. An identical retry returns the
original result, including after process restart. A competing stale writer
receives `E_REVISION_CONFLICT`; an unavailable database produces an explicit
storage error.

The installed package includes its SQLite migrations and receipt schema. See
the [storage API and executable example](docs/storage.md) for transactions,
historical reads, projection watches, and new-file backup/restore. The
[MAT-003 validation receipt](docs/validation/MAT-003.md) records crash,
concurrency, migration, and restore evidence. The storage port does not supply
the later domain operation rules or host authentication.

## Ingest immutable observations

`matter.observations.ObservationIngestor` preserves evidence under a scoped source
namespace and event ID. Repeated deliveries return the original observation and
creation receipt. Changed content under the same source revision yields an
auditable conflict; an explicit revision or correction appends evidence without
changing old bytes or availability. Observations can remain unassociated.

Prepare each new command once to capture its dependency pins, then execute and
retry that exact prepared command. `matter.payloads.FilePayloadStore` preserves
original bytes in immutable, scope-separated blobs and reports unavailable or
withheld payloads explicitly. The [observation API](docs/observations.md) describes
command retries, source duplicates, lineage, correction history, and payload
backup boundaries. Run the complete synthetic API example with:

```bash
python examples/observation_intake.py
```

## Preserve continuing matter identity

`matter.matters.MatterService` creates questions, opportunities, and problems
under adapter-declared exact subject keys. The same scoped key resolves the
same persistent ID after a new processing run or restart. Titles, audiences,
purposes, and assessment policies do not establish identity. Conflicting keys
produce an explicit conflict; all keys for a new matter commit atomically.

`update_matter_metadata` revisions the title, description, and namespaced
extensions while preserving identity, provenance, and previous snapshots.
An unchanged replacement keeps its current revision. Competing stale edits
receive a revision conflict, and exact command retries retain their original
results. See the [matter identity API](docs/matters.md) for policy configuration,
replacement semantics, scopes, and the boundaries for future identity changes.

```bash
python examples/matter_identity.py
```

## Distinguish reports, happenings, and evidence groups

`matter.occurrences.OccurrenceService` accepts explicit observation membership
under exact adapter execution/event keys. A log and a report can describe one
execution, while identical diagnostics from a later execution remain a second
occurrence. One observation can describe several occurrences or none.

One `commit_occurrence_grouping` command can split a mistaken grouping and
correct root provenance declarations. Original reports and every occurrence
revision remain available. Summaries inherit their parents' declared groups,
and unresolved dependence remains explicit. Counts cover a specified set of
observations and report source coverage separately from provenance coverage.
These counts do not establish cause or independent corroboration.

See the [occurrence and provenance API](docs/occurrences.md) for the policy,
correction, retry, and count contracts. The installed example exercises two
reports of one execution, a split, identical diagnostics from another execution,
summary lineage, provenance corrections, and backup/restore:

```bash
python examples/occurrence_grouping.py
```

## Read the specification

| Document | Responsibility |
|---|---|
| [Architecture](docs/architecture.md) | Ownership, trust boundaries, and application integration |
| [Core contract](docs/contracts/core.md) | Identity, observations, occurrences, claims, evidence, and time |
| [Executable schemas](docs/contracts/schema-inventory.md) | Implemented record, command, and result shapes with conditional references |
| [Canonical encoding](docs/contracts/canonical.md) | Exact normalized bytes, digest framing, and portable golden vectors |
| [Compatibility](docs/contracts/compatibility.md) | Version acceptance, unknown-time handling, errors, and API boundaries |
| [Durable storage](docs/storage.md) | Transaction API, exact retries, revision history, migrations, backup, and restore |
| [Observation intake](docs/observations.md) | Source identity, immutable payloads, duplicate/conflict receipts, corrections, and knowledge-time views |
| [Matter identity](docs/matters.md) | Persistent scoped subject keys, conflicts, metadata revisions, and continuity across runs |
| [Occurrences and provenance](docs/occurrences.md) | Exact happenings, accepted memberships, correction history, dependence declarations, and covered counts |
| [Rule contract](docs/contracts/rules.md) | Meaning, outcomes, qualification, dependencies, and composition |
| [Lifecycle contract](docs/contracts/lifecycle.md) | Reassessment, resolution, reopening, attention, and delivery |
| [JEV design](docs/jev.md) | Replaceable semantic execution and question/version handling |
| [Evaluation](docs/evaluation.md) | Corpus discipline, baselines, qualification, and outcome measures |
| [Oil profile](docs/profiles/oil.md) | First integration and existing runtime reuse boundaries |
| [Civic profile](docs/profiles/civic.md) | Jurisdiction configuration, source claims, and receiver authority |
| [DIAT profile](docs/profiles/diat.md) | Isolated formal-meeting research and reusable evidence contracts |
| [Backlog](tickets/INDEX.md) | Every implementation ticket, owner, phase, status, and dependency |
| [Requirement coverage](docs/COVERAGE.md) | Traceability from the requirement inventory to tickets |
| [Scaffold validation receipt](docs/validation.md) | What was executed for MAT-001 |
| [Core contract validation receipt](docs/validation/MAT-002.md) | What was executed for MAT-002 |
| [Storage validation receipt](docs/validation/MAT-003.md) | What was executed for MAT-003 |
| [Observation validation receipt](docs/validation/MAT-004.md) | What was executed for MAT-004 |
| [Matter identity validation receipt](docs/validation/MAT-005.md) | What was executed for MAT-005 |
| [Occurrence validation receipt](docs/validation/MAT-006.md) | What was executed for MAT-006 |

## What this repo owns

Matter owns the neutral contracts and future reusable implementation. Oil is the first operational integration workload. Civic adapters preserve their own record and authority semantics. DIAT owns speaker learning, meeting fingerprints, anonymous-track experiments, and private corpus processing. JEV is one replaceable evaluator behind the common contract.

Creating a domain ticket here records planned work and its target owner; it does not modify another repository or change a deployed system. The [ownership decision](docs/decisions/0001-core-ownership.md) resolves the older notes' alternative implementation sequences.

## Work from a ticket

Canonical tickets live in `tickets/records/MAT-NNN.json`. Each declares dependencies, requirements, scope, implementation steps, acceptance criteria, evidence, tests, risks, and reuse sources. Human-readable ticket pages and the index are generated:

```bash
python -m matter render
python -m matter render --check
python -m matter validate
```

Use the [ticket guide](tickets/README.md) and [contribution guide](CONTRIBUTING.md). Readiness is derived from dependency completion. A planned ticket remains unimplemented even when it is ready to start. Completion requires recorded execution evidence.

## Original design discussions

The starter files [matterbrainstormspec](matterbrainstormspec), [matterjevmesh](matterjevmesh), and [jevinmatter](jevinmatter) are preserved as source discussions. The last is a procedural-meeting/anonymous-speaker example. The governing contracts and recorded decisions take precedence when the discussions contain shorthand or an older implementation sequence. See [sources and corrections](docs/source-map.md).

## License

The repository retains its original [Apache License 2.0](LICENSE). Referenced third-party projects retain their own licenses; references and reuse plans do not grant permission to copy their code.
