# Registered dependencies and atomic invalidation

MAT-016 adds scoped dependency registrations, transitive invalidation and
freshness tokens. It uses existing SQLite projections, exact-key watches,
typed source predicates, coverage/negative watches, candidate catalogs and
host controls. It introduces no database, event broker, background scheduler,
provider client or external delivery implementation.

## Install the trusted transaction observer

```python
from matter.invalidation import InvalidationHook
from matter.storage import SQLiteStore
from matter.controls import ControlService

hook = InvalidationHook(clock=host_clock)
store = SQLiteStore(database_path, scope_id=scope_id, transaction_hook=hook)
controls = ControlService(store, policy=host_authority_policy, clock=host_clock)
hook.controls = controls  # trusted host setup, before accepting work
```

Every participating write handle must install the hook. Existing core services
then use that handle normally. The observer runs after a successful trusted
handler and before the operation receipt and commit, inside the same
`BEGIN IMMEDIATE` transaction. It receives actual before/after write pins and
the handler's typed change notices. Observation `supersedes` pins also emit a
correction notice; ordinary summary parents do not become corrections. No
application must remember to notify invalidation after a write.

The storage observer is a privileged host seam. Its current-only scoped reads,
reverse-watch queries and projection writes are recorded in the same operation
receipt. Caller `expected_revisions`, command bytes and command digest remain
unchanged; normal handler read checks remain strict. Failed transactions roll
back source and derivative writes together. Exact command replay returns the
original result without rerunning the observer.

## Capture a semantic dependency manifest

```python
from matter.dependencies import capture_dependencies, register_dependency

with store.snapshot() as view:
    manifest = capture_dependencies(
        view, scope_id=scope_id, as_of=host_clock(),
        positive=exact_source_pins,
        contexts=exact_context_projection_pins,
        candidate_sets=exact_candidate_catalog_pins,
        negative_registrations=exact_negative_watch_pins,
        queries=typed_query_specifications,
        time_conditions=declared_time_conditions,
        control_token=original_host_token, controls=controls,
    )
# The host includes manifest.read_pins in its real command's checked read set.
# Inside that command's trusted handler, after creating the actual derivative:
registration = register_dependency(
    transaction, derivative_pin, manifest,
    as_of=host_clock(), controls=controls,
)
```

The target is an exact stored judgment, assessment or host projection. Ordinary
source observations and unrelated internal projections cannot be registered as
derived work. Registrations neither alter the target's payload nor establish
the correctness of its conclusion. Raw storage handlers and registration are
not exposed as source/evaluator capabilities.

Manifest contents have separate meanings:

- `positive` records exact semantic object reads. `contexts` records only the
  exact mutable contexts this result consumes. An audience change reaches
  audience-dependent attention without reaching an independent evidence result.
- `candidate_sets` binds published candidate catalogs. Their subject, considered
  members, basis and evidence pins are also indexed as semantic dependencies,
  so a member correction invalidates uniqueness before catalog republication.
- `negative_registrations` binds the existing coverage-backed absence watches.
  New matching or indeterminate evidence can revise those watches even when
  its observation ID did not exist at assessment time. Broad catalog/coverage
  proof reads are not substituted for these narrow semantic edges.
- `queries` uses the existing typed observation predicate, eligible source set
  and event interval. Capture freezes the current explicit catalog population;
  a matching or indeterminate new observation invalidates the query-dependent
  result. Nonmatching arrivals leave it current. Query watches detect change;
  they do not establish completeness or prove absence. Coverage-backed absence
  still requires the dedicated negative-watch contract.
- `time_conditions` retain independent `next_check_at` and known/unknown
  `expires_at` values. Either reached deadline makes current use stale; an
  unknown expiry is not invented. Time-only freshness is checked at actual use.
- `control_token` remains the exact original host context. It is checked with
  the actual `ControlService`, never renewed or expanded by an evaluator.
  `read_access` separately captures required source READ fences under that
  original actor/authority. A freshness registration is not assessment admission:
  the actual assessment token must cover its semantic inputs independently.
  Registered derivatives retain source READ guards transitively; their generated
  judgment/assessment identities do not require new static source grants.
  Receipt/control bookkeeping likewise does not become a source READ target.
- `scope_fence` retains an exact generation or its explicit absence. It protects
  against a bounded observer fallback on the immediate host control path.

`manifest.read_pins` includes transaction proof reads needed to capture those
declarations safely. It is broader than the semantic watch edges. For example,
checking an empty-scope proof reads a source catalog without making every
unrelated arrival invalidate the assessment. Captured/public values are detached
immutable canonical snapshots; source text never executes a query language.

## Transitive changes and history

`InvalidationHook` uses scoped reverse watches and an in-memory breadth-first
frontier. A changed source reaches registered judgments/assessments and then
their registered host descendants. Logical invalidation follows the target
identity even when an immutable judgment or claim's old bytes remain readable.
Immutable claim correction notices therefore invalidate old-claim consumers
without rewriting the old claim.

Equivalent actual-write and typed notices are deduplicated, preferring the typed
cause. Each registration is written once per source transaction with
`status: "invalidated"`, an incremented change epoch, retained cause/receipt
references and `recompute_pending: true`. This flag represents one pending
recomputation; the engine does not enqueue a new job for every repeated notice.
A distinct later matching change still advances the epoch while already
invalidated, fencing an in-flight recomputation. Current reason storage retains
a bounded 128-entry tail; older reasons remain in immutable projection history.

The narrow MAT-015 adapter recognizes the exact `matter.assessments`
`assessment-current` schema. It registers actual stored graph judgments,
assessments and the current lane in the publication transaction, matching
children by identity rather than list position. Original node control contexts
are retained. Later invalidation updates the current lane's status and cause,
preserving every assessment, judgment, prior lane and operation receipt.
Republication uses a new actual assessment and replaces its stable lane's
registration once; it does not invalidate its own fresh after-image.

Other host projections retain their own payloads. Their separate validity
registration becomes invalidated; this ticket does not claim that a queue was
physically canceled, a message was recalled or an external action was undone.

## Freshness and recomputation fences

`registration_ref(target)` addresses the current validity registration.
`require_current_dependency(view, registration, as_of=..., controls=...)` checks
the target, exact current dependencies, transitive registered predecessors,
query arrivals, negative/candidate guards, deadlines and original control/READ
context. It returns no action authority.

`capture_freshness(...)` emits a schema-bound token containing the exact target,
registration revision, epoch and manifest digest. `require_freshness(...)`
refuses historical tokens at commit/dispatch time. The host must still perform
its current control/permission gate and record an authorization boundary before
external I/O. These checks do not implement a delivery outbox or exactly-once
transport.

To recompute, capture `recomputation_token(view, registration)` before expensive
work, capture new semantic inputs, and include the original registration pin
and input proof pins in the final command. `register_dependency(...,
previous=original_token)` accepts only that exact prior registration while
checking new current inputs. A second correction or scoped fallback revisions
the guard and refuses stale publication. Recovery requires a new authorized
control context where appropriate; no old token silently becomes fresh.

## Bounded immediate-control fallback

Graph work is bounded: 4096 registrations/references per cohort, 32 typed
queries, 128 time conditions, 128 retained reasons, a 2 MiB captured manifest,
and bounded freshness-read attempts. The storage system port checks a reverse
bucket's SQL identity-row limit **before** materializing its records.
Ordinary source mutations may refuse explicitly when graph capacity is exceeded.

Temporal watches contain only current registrations and index the earliest
known next-check/expiry deadline. The exact UTC ordering preserves nanoseconds
and supported four-digit years without floating-point timestamp conversion.
Each timed registration uses 77 deadline-prefix keys plus one capacity key;
each hook boundary queries a disjoint prefix cover through the current instant,
loading due registrations without loading unrelated future payloads. Invalidation
removes temporal membership while retaining object/query/control watches for
further recomputation fences. Historical judgments therefore do not accumulate
in a global time scan. No background scheduler is introduced.

A scope generation admits at most 512 live timed registrations. Admission is
checked atomically; exceeding this cap refuses only the new registration, and
ordinary intake can continue. Cohort proof rows enter the checked read set, not
semantic dependency edges. Temporal keys also bind the captured scope fence,
so registrations from a prior fallback generation do not consume renewed
capacity. This explicit capacity and 78 watch keys per timed registration are
the tradeoff for bounded operation using the existing exact-key storage port.

An already-admitted `record_control` cannot be rolled back merely because a
model/derivative graph is too large or its metadata is invalid. On a semantic
observer failure, the hook advances a small scoped generation fence in the
same transaction as the host control. All earlier registered freshness guards
then refuse until recomputed against that generation. This conservative
fallback may invalidate unrelated work in that scope; it does not fabricate
individual queued cancellations or traverse an unbounded graph. Storage outages
remain explicit durability failures.

Fallback generation is derived from the old fence's verified storage revision,
not its obsolete domain payload. A structurally valid projection with an unknown
or malformed fence declaration can therefore be replaced by a valid fence
without blocking the admitted control. Its old revision remains historical.
Freshness compares exact fence pins/absence, so it cannot accept an older guard
merely because malformed epoch data was discarded. Raw database integrity
failures remain storage errors; this is not a corruption bypass.

After the host explicitly restores required permissions, a recomputation can
capture a new original token, the current scope fence and exact old registration
epoch. A later fallback still fences that work. `AssessmentService.current()`
consults existing general registrations so the fallback is honored even if a
lane could not be individually marked during the bounded traversal.

## Limits and deployment responsibility

Raw unconfigured storage remains a privileged host interface. Read-time gates
can detect changed pins, matching query arrivals, negative watches, deadlines
and control denial even when a handle omitted the observer. They do not replay
unobserved typed semantic notices from arbitrary privileged writes. Installing
the observer on every participating handle is required for atomic transitive
validity updates. This is a host integration responsibility, not a new provider
permission or a distributed invalidation guarantee.

Semantic caches retain MAT-015's declared projection and original qualification
guards; this adapter does not overinvalidate them from unrelated wrapper fields
or turn cached raw responses into fresh provider evidence. General DAG validity
does not replace semantic admission, source truth, qualification, lifecycle
policy or source access. No live provider or production usefulness was tested.
See the [MAT-016 receipt](validation/MAT-016.md).
