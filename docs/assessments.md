# Revision-bound assessments and semantic caches

MAT-015 adds neutral assessment publication over existing SQLite transactions,
[versioned profiles](profiles.md), [rule graphs](composition.md),
[bounded rule evaluation](rules.md), and [trusted controls](controls.md).
Evaluation happens outside the writer transaction. A failed/stale publication
does not become current and retains its original attempt in the command
journal. Transport, learned calibration and global transitive invalidation are
separate milestones.

## Assessment lifecycle

`AssessmentService(storage, profiles=..., rules=..., bindings=..., schemas=...,
controls=..., clock=..., qualifications=None, cache=None, conflicts=None)` uses
host-installed exact registries and a trusted actual clock. The injected
`ControlService` must cover the same scope. Source access, locator adapters,
domain interpretations and bindings remain host-owned declarations; a model
judgment grants none of these capabilities.

1. Capture an original assessment token with the host control service before
   doing work. The service accepts an existing token; it does not recapture or
   renew one after evaluation. Its target set must cover every public entity
   referenced by the assessment command and declared semantic reads, including
   selected sources, extra claim dependencies and candidate sets. Internal
   projections and receipt bookkeeping use the existing control exclusions.
   Read access alone cannot replace assessment authority over a source target.
2. Call `prepare(assess_command, token=..., plan=RulePlan, ...)`. The existing
   `assess` command names the exact matter/profile/purpose/audience, explicit
   selected evidence, knowledge cut, resource budget and control epoch.
   Unmaterialized retrieval queries are refused. Optional `extra_dependencies`,
   `candidate_sets`, `negative_dependencies` and original `control_contexts`
   declare additional reads. Call/byte limits are checked before evaluation.
3. Preparation takes one short, tracked, authorized snapshot. Candidate
   universes, negative-scope proof reads, control fences and existing lane state
   are captured together. `PreparedAssessment.view` returns detached records
   from that snapshot. It has no live fallback: only explicitly captured
   absences return `E_NOT_FOUND`; uncaptured reads return
   `E_EVIDENCE_UNAVAILABLE`. No SQLite read transaction stays open while a
   callback runs.
4. Use that frozen view with the existing `prepare_input` and `GraphExecutor`.
   A fresh gate can call `service.check_current(prepared, material, as_of=...)`.
   Evaluation retains its original exact input and actual attempt receipts.
   Rule inputs must bind the assessment's exact scope, matter and knowledge cut.
5. Call `prepare_commit(prepared, graph_run, command_id=..., idempotency_key=...,
   assessment_id=..., interpretations=(), cache_entries=())`. It returns an
   ordinary serializable `commit_assessment` command. No write occurs yet.
6. Call `commit(command)`. The writer atomically checks exact original reads,
   currently applicable controls, candidate scopes, negative registrations,
   time conditions, result schemas, locator declarations, qualification and
   every graph prerequisite/composition gate. An outdated result returns a
   durable `E_DEPENDENCY_STALE` and changes no assessment/current pointer.

Required/conditional graph path verdicts are preserved. A completed raw child
cannot bypass a blocked or expired predecessor. An unresolved explicit
composition leaves its component claims unknown, preserves disagreeing raw
results and emits no selected consequence. Installed conflict resolvers are
required to reconstruct resolved compositions; execution order/confidence is
not a fallback.

`interpretations` are explicit host mappings with `node`, a captured exact
`claim` pin, `labels` mapping declared rule labels to core proposition statuses,
and this profile's exact evidence component as `evidence_standard`. A supported
or refuted status requires an admissible qualified/deterministic node and its
graph path. Otherwise the proposition remains `unknown`. This mapping does not
establish source truth or authorize the proposals that the rule may return.

## Proposed and materialized fields

The typed `matter:assessment_publication` command extension binds the original
preparation, graph inputs/results, host interpretation mappings, staged cache
entries, requested assessment ID and construction timestamp. Its exact packaged
schema is `assessment-publication.schema.json`.

The proposed `command.body.assessment.body.judgments` is empty. It cannot contain
predicted child hashes. The handler validates each raw `EvaluationBundle`,
inserts its real evaluation receipt/judgment, then materializes only their
**actual** judgment pins into the stored assessment. Those pins are also added
to stored provenance parents. Other proposed assessment fields must match their
retained input reconstruction. Receipt input digests, rule/binding/schema,
qualification, origin, time, evidence and raw-result declarations are checked.

The operation receipt is supplied by the real transaction. Since the command
binds raw creation inputs rather than the eventual receipt-dependent child
digests, there is no circular receipt hash, synthetic authority receipt or dummy
production staging operation. Existing explicitly staged immutable children can
be reused only when their original bytes exactly match; their creation receipts
remain original. New children, assessment, cache stages and current projection
commit together or are rolled back together.

`extend_staged(prepared, references=[...])` supports the graph's explicit
host-owned prerequisite staging seam. It reads actual stored immutable judgment
or receipt pins after freshly checking the original semantic dependencies,
negative watches and controls, returning a new frozen preparation. It preserves
the original cut, capture time and tokens and records the additional snapshot.
The original token must already cover any public prerequisite judgment target;
discovering an additional target requires a new appropriately scoped attempt,
not an expanded or renewed token inside this lifecycle.
It grants no write authority, accepts no mutable record, and cannot backdate a
new judgment into an earlier evidence cut. The host must have persisted the
prerequisite through a genuine authorized operation before supplying its pin.

## Current lanes, causes and history

`assessment_current_ref(scope, matter, profile=..., purpose=..., audience=None)`
addresses a stable scoped lane. The key includes the continuing matter and the
stable namespace/ID of the profile, purpose and optional audience. Exact versions
remain in the lane value. Different profiles coexist for one subject/audience;
a new version can supersede only its own lane.

`current(matter, profile=exact_ref, purpose=exact_ref, audience=exact_ref)` requires
explicit exact selectors. It does not choose a latest historical profile or
another policy's last writer. It checks current read permission and all original
semantic/control/negative/time/qualification guards again before returning the
immutable stored assessment. Old records remain readable through privileged
historical storage even when their lane is no longer usable.

Policy/profile changes produce `policy_change`; changed selected evidence
produces `new_evidence`; exact purpose/audience changes have their own labels.
These are declared input-change classifications, not newly observed external
events. An unchanged assessment context with no changed evidence, policy,
subject or temporal cut is refused rather than fabricated as a new event.

`attempt(idempotency_key)` returns the durable original command, typed result and
actual operation receipt under current read authority. Failed commands retain
raw staged attempts in their original command extension, not as current records.
Exact retry returns the original result, including a durable stale refusal.
Reusing an ID/key with different canonical content remains an idempotency
conflict. Cancellation does not erase history; a current read denial can block
disclosure of history and exact replay.

`input_artifact(key)` reconstructs exact canonical bytes containing the original
preparation and every original graph input. Its source SHA-256 matches the
assessment's available embedded JSON artifact. This availability claim concerns
those embedded normalized bytes, not availability of a provider response or
original external payload. Missing provider usage/cost is not reported as zero;
resource evidence here records actual binding invocation/reservation diagnostics
and explicitly staged cache hits.

## Semantic cache contract

`SemanticComputationDefinition(value, rules=..., bindings=...)` declares exact
rule, binding and preparation references, ordered record field projections,
ordered context projections and increasing temporal boundaries. Record fields
contain `name`, a declared record role and exact JSON Pointer; context fields
contain `name` and pointer. Empty temporal boundaries explicitly declare clock
independence. There is no heuristic removal of titles, audience data or clocks.

`SemanticCache(definitions=..., rules=..., bindings=..., schemas=...,
controls=..., qualifications=None)` captures these declared inputs from a read
view. The computation callback receives only selected field values, stable
record identities, exact definition/qualification context, citations and temporal
class. It receives no full records, unselected audience settings or delivery
wrappers. Installed callbacks are trusted code, not sandboxed Python.

For one consistent assessment snapshot, `prepare(..., cache_queries=[...])`
accepts declaration objects containing `definition`, `records` (role to exact
pin), `context`, `qualification_context`, `citations` and
`negative_dependencies`. It exposes resulting `prepared.cache_inputs`. The
corresponding cache key's actual absence/pin and original cached control context
are captured too. `cache_references` can also nominate exact cache projection
addresses for inspection. Unknown lookups cannot masquerade as cache misses.

`get_or_compute(view, cache_input, compute=..., attempt_id=..., as_of=...)`
returns a `CacheResult`. On a hit it preserves the original source attempt/raw
result and rechecks actual field equivalence, negative dependencies and the
**original** cached control token. A fresh token for another target with the
same epoch cannot renew stale upstream work. A stale cache is an explicit
refusal, not an automatic provider fallback.

Qualification is freshly classified at consumption time using the exact rule,
binding, task and admitted certificate registry. `.response` exposes that current
classification; `.entry` separately retains the original reported response and
its origin. Unknown conclusions stay unknown. Expired qualification stays
expired. Neither structural validity nor a cache hit grants action authority.

Pass cache results to `prepare_commit(..., cache_entries=[...])` to stage them
with the assessment. An entry is keyed by the exact declared semantic
projection. A title-only matter revision can reuse a computation that never
received the title, while a title-reading computation gets a different key.
Audience-independent support can be shared across audiences; an audience-reading
judgment cannot. Moving through one temporal equivalence class preserves the
key, while crossing a declared boundary changes it. Whole assessments always
bind the fresh matter/context revisions even when a semantic computation is
reused.

## Proof and qualification limits

`preparation.reads` includes transaction proof reads. The semantic graph uses
`current_dependencies.positive`, explicit candidate pins and registered negative
watch pins. `proof_reads` records rows read only to validate absence; these are
not broad semantic invalidation edges unless independently declared. An unrelated
arrival can leave a narrow absence assessment usable. A race after final write
read-set preparation can conservatively refuse the attempt; it never publishes
an unchecked result.

If a host actually consumes catalog/control proof contents in a proposition,
rendered question or computation, it must also declare those references as
explicit `extra_dependencies`. They then receive ordinary semantic currentness
and invalidation guards. A frozen Python view is a data boundary, not a sandbox:
trusted callback code can still consult undeclared closure/global data, which
the storage port cannot discover or authorize automatically.

This implementation performs no retrieval, provider call, model training,
native integration, audience transport or global transitive propagation. It
qualifies synthetic local behavior, not provider accuracy or live usefulness.
See the [validation receipt](validation/MAT-015.md) for executed evidence.
