# Shared resource and attention allocations

MAT-020 adds separate durable allocation ledgers over the existing neutral
Storage port. A reservation holds unused capacity. Committing it charges the
full conservative allocation before work begins. Actual evaluator invocations,
provider usage and transport outcomes retain their own evidence; an allocation
is not a receipt that those events happened.

## Policies and units

The host installs immutable `BudgetDefinition` values in `BudgetService`.
Each definition names an identity/version, kind, explicit half-open fixed
window, integer limits, corresponding units and description. No source text,
model output, mutable price oracle or implicit currency conversion defines a
limit. A host can express fractional monetary quantities in a declared integer
unit such as microcredits before constructing the definition.

Resource dimensions are `calls`, `input_bytes`, `output_bytes`, `elapsed_ms`,
`candidates`, `retries` and `cost_units`. Attention dimensions are `deliveries`
and `interruption_units`. Limits and requests use portable nonnegative integers;
every limit has an explicit namespaced unit. A request supplies all dimensions
of its selected policy, and at least one requested quantity is positive.

All workers selecting the same budget identity and window share one account,
independent of rule or worker identity. Resource and attention accounts are
different. Versions cannot silently mint fresh capacity in an existing account:
an incompatible definition for the same identity/window is refused. New windows
are explicit host declarations; this module supplies no calendar or automatic
periodic reset.

## Reserve and settle

The four new operations are documented together in the [scheduler API](scheduler.md).
For a budget, construct an ordinary command envelope for `reserve_budget` with
an exact installed budget reference, unique reservation identity, integer
amounts, expiry and public work targets. Then:

```python
prepared = budgets.prepare(command, token=original_work_token)
result = budgets.execute(prepared)
```

The original token uses capability `assessment` for resource work or `delivery`
for attention allocations. Preparation retains its exact scope and the complete
discovered read set. Current controls and READ permission are checked before
budget availability; a full budget cannot hide a stop or grant a denied action.

`reserved` returns the actual reservation pin, remaining capacity and next
eligibility boundary. `budget_limited` records why shared capacity or its time
window is unavailable, the remaining quantities and the next known eligibility
boundary. Unknown next eligibility stays explicit. A hold alone authorizes no
provider invocation or external dispatch.

Use `settle_budget` with the exact current reservation pin and action `commit`
or `release`, prepared with the reservation's original token. Commit checks that
same original token and deadline, then atomically moves the whole allocation
from held to charged. Charge happens **before work**, including work whose
eventual outcome may be unknown. Do not recapture an equal-epoch token to renew
an old reservation.

An unused hold can be released or expire. Expiry returns capacity exactly once,
either through settlement or atomically when another reservation reclaims
expired unused holds. Release still requires actual host authority and READ
permission; cancelling work does not require waiting for ordinary budget
capacity. Finalized allocations return `unchanged` on another settlement.

Committed allocations are never automatically refunded, even after their work
deadline or an uncertain provider/transport outcome. Their full conservative
quota stays charged for that explicit account/window. Releasing an already
committed allocation does not manufacture unused capacity. This first primitive
does not infer actual spend or partially refund a completed attempt.

Reservations and account totals change within one checked writer transaction.
Competing connections cannot both reserve the same remaining quantity. A stale
prepared loser receives a conflict; the service does not silently refresh or
retry it. A fresh request can then observe `budget_limited`. Exact command retry
returns the durable journal result and does not renew an allocation or prove a
new invocation occurred. Reservation identities cannot be recycled for new work.
Settlement retry audits the actual original allocation snapshot's stored work
targets, including after its current projection has advanced to released or
committed. Caller cleanup hints cannot omit those READ checks. Historical
inspection does not require the old work token to become current again, but a
present target READ denial still prevents disclosure.

## Execute within one committed allocation

`require_committed(view, reservation_pin, as_of=None)` is the view-local guard
before host work and final result consumption. It checks the current exact
reservation, committed status, actual host time, policy window, original
controls and current READ permission. Expired work cannot start another call,
even though its conservative charge remains on the account. An earlier time
hint cannot backdate authority; a future hint is refused.

For the existing `GraphExecutor`:

```python
with storage.snapshot() as view:
    envelope = budgets.resource_envelope(
        view, committed_reservation, ceiling=profile.value["resource_limits"]
    )
run = executor.execute(
    plan, prepare=prepare_node, run_id=run_id,
    remaining_budget=envelope.remaining_budget,
    check_current=check_current, check_control=controls.check,
)
```

The envelope caps calls, input/output bytes and elapsed time by the committed
allocation and host profile ceiling. Elapsed time is also clipped to the
remaining reservation deadline. `max_evidence` stays the host's per-packet cap;
it is not a shared counter. The original token and deadline are retained in the
immutable detached envelope.

Each reservation belongs to **one work assignment**. Carry the graph's decreasing
`resource_reservations.remaining_budget` into subsequent batches within that
assignment. Reconstructing a full envelope for every batch would reuse already
allocated capacity. Durable attempt identity and retry-safe execution belong
to the actual executor/receipt layer; an allocation is not an exactly-once
external-call mechanism. Actual GraphRun invocation counts remain separate from
the full caps charged here.

The caller rechecks `require_committed` immediately before host preparation,
fetch or dispatch and before consuming results. An envelope is data, not a new
capability or a substitute for the normal source, control and qualification
gates.

## Bounds and validation

An account has at most 512 live unused holds through the existing exact-key
watch index. Checked operations retain at most 4,096 records and 8 MiB of unique
record data. Each unique record's bytes are counted once; duplicate reads retain
the existing exact-pin conflict checks without repeatedly serializing the whole
prior read set under the writer lock. Exceeding a bound is an explicit budget refusal. Historical rows
remain available after finalization; they leave the live cohort.

The [MAT-020 receipt](validation/MAT-020.md) records real SQLite races,
expiry/release, precharge, separate accounts, guarded envelopes and direct stop
tests. These are synthetic mechanism checks, not provider pricing, measured
live costs or verified transport delivery.
