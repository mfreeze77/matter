# Time, source coverage, and negative evidence scopes

MAT-010 implements explicit temporal selection, revisioned source coverage,
protected replacement membership, and direct negative-dependency watches.
An empty query is usable as evidence of absence only within an explicitly
declared, adequately covered source/query/interval scope. A failed collection,
an incomplete history, and incremental silence remain distinct outcomes.

The complete runnable example is
[`examples/time_coverage.py`](../examples/time_coverage.py):

```bash
python examples/time_coverage.py
```

It uses synthetic evidence, local storage, an explicitly admitted host
authority, and a deterministic predicate. It does not execute a domain
calendar, evaluator, background collector, or assessment scheduler.

## Two independent temporal questions

`matter.time` keeps knowledge availability separate from the interval during
which a proposition applies. A cancellation discovered today can describe an
event effective yesterday. It can change today's understanding of yesterday,
while remaining excluded from a query asking what was known yesterday.

| Function | Meaning |
|---|---|
| `known_time_key(value)` | An exact comparison key for a validated known UTC instant |
| `compare_times(left, right)` | `-1`, `0`, `1`, or `None` when either time is unknown |
| `validate_interval(interval)` | Validate ordered known endpoints without filling unknown endpoints |
| `contains(interval, instant)` | Definite membership, definite exclusion, or `None` |
| `overlaps(left, right)` | Definite overlap, definite exclusion, or `None` |
| `knowledge_eligible(available_at, as_of)` | Inclusive availability at an explicit known knowledge cut |
| `select_knowledge(packets, as_of=...)` | Partition an explicit corpus into included, excluded, and unknown pins |
| `select_effective(packets, effective_at=..., as_of=...)` | Apply knowledge gating first, then explicit effective-time selection |

Selection consumes closed packets:

```python
packet = {
    "reference": exact_record_pin,
    "available_at": recorded_earliest_availability,
    "effective": declared_applicability_interval,
}
```

The caller supplies the appropriate applicability interval. An observation's
occurrence time does not automatically become a claim's effective time. The
helpers do not guess fields, establish source independence, select authoritative
claims, or apply supersession. Explicit distinct record versions may coexist;
the same exact pin cannot be repeated. Results preserve input order within
each partition and return detached values.

Known timestamps preserve their original UTC spelling and declared second,
millisecond, microsecond, or nanosecond precision. Comparison pads fractional
digits internally without rounding. Equal timestamps establish no order
between different events. Unknown times never receive ingestion, publication,
or wall-clock substitutes. A known end before a known start is refused.
Equal closed endpoints describe one instant; equal endpoints with an open
bound describe an empty interval. Unknown endpoints are not infinite bounds.
One known violated bound can establish exclusion even if another is unknown.

Observation intake and occurrence creation use the shared interval validator.
Claim applicability validation delegates to the same helper. Existing
`ObservationIngestor.revisions(..., as_of=...)` and `heads(..., as_of=...)`
reuse the exact comparison while retaining their source-family semantics.
Current payload readability remains separate from historical `available_at`.

## Source catalogs and the historical initialization boundary

`matter.source_catalogs` owns a revisioned projection per storage scope and
source namespace. `source_key("example:feed")` creates the explicit selector
`{"namespace": "matter.source_namespace", "value": "example:feed"}`.
Its value matches `observation.body.source_identity.namespace` exactly.
Future event IDs belong to the same source bucket; neither observation IDs
nor source revision labels define that bucket.

Every genuinely new observation committed through `ObservationIngestor`
updates its source-family index and source catalog in the same transaction.
Exact retries and duplicate deliveries do not create another catalog admission
or arrival signal. Catalogs retain every admitted immutable observation,
including explicit corrections. They do not collapse revisions into a count
or infer that a later publication is more authoritative.

Each catalog records an admission revision for each observation. Its
`catalog_population(catalog, revision)` helper can reconstruct the exact
earlier population from a current catalog using only a guarded current read.
This is necessary because a transaction cannot silently refresh a historical
proof or bypass the storage port's current-dependency checks. Coverage readers
verify their complete observation population against these admission revisions.

A newly created catalog has `baseline: null`. That state does **not** certify
that all observations stored before MAT-010 were inventoried. An authorized
coverage publication can supply a one-time baseline:

```python
source_baselines = [{
    "source": source_key("example:feed"),
    "observations": exact_preexisting_observation_pins,
    "history_complete": True,
}]
```

Initialization verifies the supplied pins, merges them with all observations
already captured in that bucket, and records the adapter, host authority,
declaration time, and initialization revision. A later baseline cannot make
an earlier catalog revision historically complete. A second initialization
is refused. Later publications normally pass `source_baselines=[]`.

The host owns the truthfulness of this inventory declaration. No global scan
discovers observations created by arbitrary custom storage handlers. Existing
databases must explicitly inventory any such legacy evidence before relying
on absence. Catalog initialization and source collection completeness are
independent requirements.

## Exact coverage publications

`CoveragePolicy` admits a scoped actor list, actual immutable host-origin
authority receipts, collection adapter descriptors, and an explicit
`allow_retirement` capability. Descriptors preserve exact versions and digests;
an observation, model confidence, or quoted instruction cannot configure
this host capability.

`CoverageService.prepare(command)` reads one snapshot and captures every
current dependency while retaining caller-supplied pins. Keep the prepared
command for exact retries. `publish(command)` executes `publish_coverage`;
`register(command)` executes `register_negative_watch`.

A publication binds all of the following:

- A typed query, eligible source selectors, and observed interval.
- The external snapshot and catalog descriptors, collection status and any
  required failure reason, and the admitted collection adapter.
- The original knowledge boundary and replacement or incremental mode.
- Exact catalog revisions, observation population, matching, excluded and
  indeterminate observation pins, and historical initialization status.
- Explicitly declared host-derived members, protected ownership, policy,
  authority, and the publication's committing operation receipt.

`coverage_ref(scope, specification)` identifies one exact source/query/interval
family. Reordering eligible sources produces the same canonical set. Changing
a predicate, source set, or interval creates a separate family. Every update
requires the previous current coverage pin. A publication with an older
knowledge boundary cannot overwrite the current snapshot. External revision
labels and equal timestamps establish no implicit ordering; a new publication
still requires its exact previous pin and host declaration.

`read_coverage(view, scope, reference)` verifies a current publication, including
its exact frozen catalog population and temporal partition. Its operation
receipt must have written that coverage revision under the declared authority
and actually read or written every selected catalog snapshot. Exact historical
catalog reconstruction also accepts equivalent digest-form read pins without
refreshing an old proof. `coverage_at`
verifies an explicitly selected historical snapshot. The storage history and
operation journal retain earlier declarations and their results.

### Collection status and absence usability

| Collection declaration | Empty-result treatment |
|---|---|
| `complete` | May produce `adequate_empty` only with complete initialized history, replacement mode, and a fully known, nonempty observed interval ending no later than the knowledge cut |
| `partial` | `unusable_coverage`; retain the collection reason |
| `failed` | `unusable_coverage`; retain the collection failure |
| `not_expected_yet` | `unusable_coverage`; preserve the declared expectation state |
| `expected_not_published` | `unusable_coverage`; preserve the declared publication gap |
| `manual_review` | `unusable_coverage`; preserve the review requirement |

Even a declared complete incremental batch cannot establish absence from its
silence. An uninitialized source history, an unknown interval endpoint, a
future interval, or an empty interval also prevents adequate absence.

Within an otherwise adequate scope, matching observations produce
`evidence_present`. Potentially relevant evidence with unknown availability,
unknown occurrence time, or missing required predicate metadata produces
`indeterminate` when no definite match exists. All three evidence partitions
remain recorded even when coverage is unusable. These labels describe the
declared evidence query; they do not establish source truth or a matter's
domain lifecycle.

### Typed predicates

`observation_predicate(clauses=...)` binds the installed
`observation-predicate` schema and canonicalizes a unique clause set. Supported
scalar clauses use `field` and `equals` for `record_namespace`,
`source_event_id`, `source_revision_id`, `origin`, or `media_type`.
Extension clauses use `field="extension"`, a namespaced `key`, an exact
component `schema`, and a whole canonical JSON `value`.

All clauses are ANDed. No clauses means all observations within the explicit
source/time scope. A missing optional field is indeterminate. A definite
mismatch can exclude a record even if another field is unknown. Extension
comparison preserves canonical JSON types, Unicode and exact values: Boolean
`true` is not integer `1`. No source payload is executed or parsed implicitly.

Occurrence-time matching uses point containment or interval overlap. Availability
gating is separate and runs first when publishing a historical query. These
predicates intentionally do not interpret business calendars, source text,
legal meaning, claim truth, or domain-specific correction rules.

## Replacement affects owned membership

The publication's `members` list registers exact **host projection** pins with
one of four ownership declarations. Internal Matter projections cannot be
registered as replaceable host derivatives. Each member's validity lives in
this exact coverage family's durable membership snapshot.

| Existing ownership | Complete authorized replacement omits it |
|---|---|
| `machine` | Set this scope's membership to `retired` |
| `operator` | Preserve the active member and its original pin |
| `reviewed` | Preserve the member and pin; flag `review_required` |
| `rejected` | Preserve the rejected tombstone |

Retirement additionally requires adequate complete replacement coverage and
no indeterminate evidence. Disabled retirement, partial or failed collection,
incremental silence, or incomplete history preserves prior member state.
Neighboring source/query/interval families remain independent.

Replacement cannot demote protected ownership to machine ownership. A rejected
member cannot be resurrected by including it again. A changed reviewed pin
requests review while retaining its original evidence; an operator-owned pin
is preserved. A retired machine member may become active again when the host
explicitly includes its current derivative in a new publication.

This service never deletes or changes the referenced host projection, an
observation, a claim, an occurrence, a matter, a user decision, or an identity
protection. The durable membership flag is the implemented retirement boundary.
It does not resolve a matter or turn an omitted claim into a false claim.

## Negative registrations and later arrivals

A registration binds a stable host watch ID, an exact assessment or host
derivative, an exact current coverage snapshot, the original knowledge cut,
and at least one expiry or next-check time. Its core negative scope includes
`assessed_as_of`, typed query, eligible sources, observed interval, catalog,
coverage status, and time conditions. An assessment must retain both the
exact coverage pin in its positive manifest and the exact negative scope.

Only `adequate_empty` coverage admits `current` use. Other registrations remain
explicitly `unusable_coverage`, `evidence_present`, or `indeterminate`.
Registration reads the latest source catalogs as well as the frozen proof:
relevant evidence arriving after coverage publication cannot slip through
before a watch is registered.

Each registration subscribes to the exact source-bucket keys. Supported
observation intake reevaluates the narrow predicate and observed interval for
every registration in that bucket. A matching or indeterminate new observation
invalidates every currently usable matching registration in the **same
transaction** as observation and catalog publication. Unrelated records leave
a narrow watch's semantic status and revision unchanged.

The original knowledge cut is not a permanent arrival filter. A later-available
observation about a past event must reconsider current use. New potentially
matching records with declared future availability also conservatively require
reconsideration; the notice does not claim they were known at an earlier cut.
The historical coverage receipt and original assessment remain unchanged.

Ingestion's successful result carries `negative_scope_arrival` changes with
exact before/after registration pins. A changed registration retains the exact
observation and its operation receipt. Readers verify that the observation
and watch change were committed together. A second delivery or exact retry
does not emit another arrival or revive an earlier registration.

Both first-arrival races are guarded. If an arrival commits after a registration
was prepared, the catalog revision or newly occupied catalog address makes the
registration stale. If the first watch is registered after ingestion was
prepared, transactional watch discovery finds an unpinned registration and
refuses that ingestion command. A new prepared command can then include it.

## Current use, expiry, and recovery

`negative_status(view, scope, registration, as_of=...)` checks an explicit
clock value without writes. It returns `current`, `expired`, `review_due`,
`invalidated`, `unusable_coverage`, `evidence_present`, `indeterminate`, or
`dependency_stale`. `require_current_negative_dependency` returns the validated
registration only when it is currently usable; otherwise it raises
`E_DEPENDENCY_STALE`.

Expiry and next-check boundaries are inclusive. Clock progression cannot
publish observations, improve incomplete collection, invent an expected
event, resolve a matter, or run a scheduler. Evidence already in the catalog
but available at a later declared time is reevaluated at the requested cut.
A current-use check cannot predate its original proof; use historical
selection for that question.

Changing the exact host derivative or publishing a new coverage revision makes
the old registration stale. An unrelated catalog admission alone does not.
Refresh requires a newly prepared, authorized registration against current
evidence and the exact prior registration pin. A watch ID cannot be reassigned
to a different derivative. Replaying an old successful publication or
registration returns its saved historical result without repeating writes.

The tests exercise competing processes and actual exits before and after SQL
commit. Observation, source indexes, catalogs, all affected watches, membership,
and operation receipts recover or roll back together. Payload blobs remain
the existing separate immutable store; preserve them alongside database backups.

## Bounds, reuse, and qualification

The supported bounds are 64 source selectors and 64 predicate clauses per
scope, 4,096 observation pins per catalog or coverage population, 4,096 derived
members per replacement family, and 4,096 watch registrations per arrival
bucket. Temporal selection accepts up to 4,096 packets. Exceeding a bound
refuses instead of silently truncating evidence or registrations.

The implementation reuses Matter's strict time schemas and canonical encoding,
immutable observation intake, scoped SQLite storage, transaction read sets,
watch indexes, operation receipts, and existing host policy pattern. No new
database, migration, network collector, or dependency was introduced.

The ticket-pinned civic
[`replace_scope` importer](https://github.com/mfreeze77/state-civics-ai/blob/a34fcec27f353187e7a23d54788b203d13ac87c1/services/local-accountability/sar_tracker/core_import/matters.py)
was inspected at its pinned revision. Its reusable distinctions are exact
replacement ownership, retained human decisions, unchanged evidence retention,
review flags, and refusal to let older content silently replace newer work.
Its callers separately guard suspicious empty derivations; the replacement
function alone does not establish completeness. MAT-010 makes completeness and
historical initialization explicit. No civic SQL or downstream runtime was
copied or modified, and no upstream test suite was run.

Qualification remains synthetic and local. Automatic catalog/watch maintenance
is guaranteed through the supported services; arbitrary trusted custom storage
handlers are responsible for their own indexing and admission. Transitive
assessment invalidation, host control epochs, scheduling, domain expectations,
source discovery, downstream adapters and native delivery remain later tickets.
The wire version, twelve core record kinds and SQLite migration remain stable;
older closed-schema readers must update for the additive commands and fields.
