# Durable finite temporal conditions

MAT-020 persists timer conditions and idempotent firings over the existing
Storage port. A host invokes it when work is due; no daemon, distributed
scheduler, business calendar or semantic evaluator is created.

## Declare and schedule

`TimerDefinition` is immutable and names a namespace/identity/version,
condition identity and generation, exact matter/assessment/profile/purpose/
audience, actual assessment rule versions, dependency pins, finite checkpoints,
expiry and allowed clock skew in milliseconds. Checkpoint identities are unique,
times strictly increase, and expiry follows the final checkpoint. At most 128
checkpoints, 128 rule references and 256 direct dependency pins are admitted.

Create a `Scheduler` with the actual `AttentionService`, same Storage and
ControlService, and trusted clock. A `schedule_timer` body contains action
`create`, `replace` or `cancel`, a typed `timer-definition` value and expected
prior timer pin (or explicit null for creation). `prepare_schedule(command,
token=original_work_token)` captures current reads. `execute(prepared)` commits
the timer and its original dependency/control context atomically.

Scheduling needs actual host write authority, current assessment capability
for the work, READ permission and the complete original token scope. The exact
selected current assessment must agree with the declared subject, policy and
context. Its actual graph rule versions must match the timer declaration;
naming some other installed rule does not supply a truthful temporal scope.

A replacement requires an explicit newer condition generation and different
semantic version. It does not silently renew a revoked same-generation token.
Administrative cancellation can make old work inert under current host write
authority without executing it. It never authorizes a new firing. Cancelling an
already cancelled timer returns `unchanged`.

## Discover and fire

`due()` is bounded trusted-host discovery over the existing exact-key active
cohort. Raw store and scheduler handles remain host machinery; this method is
not a source-disclosure API for an untrusted agent. At most 512 active timer
conditions are admitted, with the shared 4,096-record/8-MiB checked-read bounds.

When a condition is due, prepare an actual deterministic attention command at
the actual current clock, passing the timer's **stored original token**. Use
the exact same actor/authority, selected assessment and scoped context. Wrap
that prepared command with `domain("operation-command", prepared_attention)`
inside a `fire_timer` body together with the exact current timer pin and
`firing_key(definition, latest_due_checkpoint)`.

```python
prepared_fire = scheduler.prepare_fire(fire_command)
result = scheduler.execute(prepared_fire)
```

Preparation includes every inner attention read pin in the outer command.
The handler reruns timer source/control guards, then calls
`AttentionService.stage(tx, prepared_attention)` through the same actual write
transaction. It opens no nested transaction and makes no semantic/provider
call. Attention's current assessment, context, lifecycle, original access,
baseline and authority guards remain mandatory.

The immutable firing receipt, actual attention decision and timer cursor commit
together. An attention-stage failure rolls all of them back. The receipt records
the exact condition/generation, original token, scheduled checkpoint, actual
firing time, delay and number of coalesced checkpoints. A changed prerequisite
requires fresh explicit preparation, rather than an automatic stale retry.

## Restart, catch-up and cancellation

Restart reads durable rows through a newly opened backend; no process-local
queue is needed. Crossing several checkpoints during downtime produces one
firing for the latest currently due checkpoint and advances over the older
ones. Future checkpoints remain pending. It does not produce an obsolete warning
for every missed tick. A late firing preserves the scheduled time and records
actual delay; it never rewrites history to claim punctual execution.

Exact command retry returns the journal result. A new inspection of the same
firing key returns `already_fired` with its original receipt and decision,
without reevaluating attention. A key bound to another definition/generation
cannot stand in for the current condition.

`not_due` leaves the cursor unchanged. Expired, cancelled or invalidated
original contexts produce an explicit `inert` result rather than fabricated
evaluation. Missing attention preparation records its unavailable reason and
leaves the condition pending. Current READ denial remains a refusal. A new
equal-epoch token cannot replace the original timer context, even if it currently
has sufficient scope.

Source/access eligibility is checked by the actual attention stage. With an
installed access boundary, existing-firing inspection and exact replay also use
`AccessService.require_history` against the original stored attention context
and current source grants. Installing a boundary does not retroactively mint a
missing original context.

Backward clock movement beyond the declared skew is refused, with fractional
milliseconds treated conservatively. The actual clock still determines whether
a checkpoint is due; tolerance never fires a future checkpoint early. Current
authorization uses the shared ControlService's actual host clock. Earlier
caller hints do not backdate authority and future hints are refused. Direct
stop and READ controls are applied through ControlService immediately, including
when all ordinary resource or attention allocations are exhausted.

## Additive portable operations

The closed v1 wire adds four operations while preserving the original 24
operations, 12 core record kinds and 19 error codes:

- `schedule_timer`: `scheduled`, `cancelled`, `unchanged`.
- `fire_timer`: `fired`, `already_fired`, `not_due`, `inert`.
- `reserve_budget`: `reserved`, `budget_limited`.
- `settle_budget`: `committed`, `released`, `expired`, `unchanged`.

There are now 28 operation variants and 58 explicit success pairs. Every new
command/result body is closed and has standalone synthetic vectors. Core record
shapes and the SQLite migration remain unchanged. A reader which recognizes
only the old closed operation set must reject a new operation rather than guess
its meaning; the conformance tests exercise that failure boundary.

See [budget allocation semantics](budgets.md) and the actual
[MAT-020 validation receipt](validation/MAT-020.md). The reference checks prove
bounded deterministic timing, transactional conflict behavior and zero unchanged
semantic reruns. They do not qualify a provider, production-scale scheduler,
domain calendar, outbox, external delivery or live attention usefulness.
