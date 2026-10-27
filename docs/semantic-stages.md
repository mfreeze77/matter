# Independent batches and semantic stages

MAT-029 composes the existing [typed executor](semantic-executor.md),
[question registry/renderer](semantic-questions.md),
[source packets](semantic-packets.md) and actual committed
[resource allocations](budgets.md). It adds no provider client, fetch client,
agent framework, scheduler, automatic retry or qualification issuer.

## Explicit plan

`StagePlan(value, questions=QuestionRegistry(...))` accepts immutable
`namespace`, `id`, `version` and an ordered `stages` array. Each stage declares:

- `id`, a symbolic fixed `packet_key`, and an exact host `transform` component.
- `questions`: exact registry `specification` references, unique correlation
  `id`s, and optional `use_if: {pointer, equals}` conditions on the fixed packet.
- `requires`: prior stage/question identities, typed `accepted` outcomes,
  `require_qualified`, and exact answer-to-packet `bindings`.
- `max_candidates`: the conservative candidate-fetch allocation required before
  its host preparation callback runs.

The plan permits at most 128 stages and 128 questions total. It rejects cycles,
missing stages/outcomes and dependencies on a sibling in the same fixed-packet
group before preparation or dispatch. Choice gates name explicit admitted
options; Score/proposition-probability gates name exact decimal-string minimum
and maximum values. Unknown/uncertain results outside that declared region
stop the dependent stage without a default candidate.

Question IDs only route answers. Full meaning, ordered criteria and renderer
versions remain the registry's responsibility. No text heuristic attempts to
discover a hidden dependency in a prompt; the authenticated host must declare
the real dependency graph. This implementation uses recorded stops rather than
inventing alternative branches or model-generated plans.

## Host preparation and transforms

`StageExecutor(questions=..., budgets=actual_budget_service,
executor=injected_executor, clock=..., monotonic=..., dispatch=None)` runs:

```python
run = stages.execute(
    plan, prepare=prepare_stage, reservation=exact_committed_allocation_pin,
    ceiling=profile_resource_limits, run_id="host-run",
    qualify=current_qualification_adapter,
    check_current=current_source_adapter, cancelled=host_cancelled,
)
```

The callback receives `(stage, parents, remaining=..., deadline=...)`. Only admitted parent
answers and their exact trace references are provided. It returns a
`StageInput(packet=PreparedPacket(...), rendered_questions=[...], context=...,
transform=exact_ref, parents=[...], candidate_count=...)` or a host-owned
`concurrent.futures.Future` that resolves to one. The executor waits for that
future cooperatively while checking cancellation, allocation validity and time.
It does not start a fetch itself. Remaining elapsed capacity and the absolute
deadline are refreshed before each preparation; a failed gate requests cancellation
of an unfinished future. A completed future exception is inspected once.
Compatible members are admitted separately, so one expired prerequisite does not
block unrelated members. Every attempted dispatch retains its exact request and
unique batch index, with a null result when no valid result was observed.

Parent references, exact specifications, question inventory, packet digest,
scope, declared candidate cap and transform identity must match. Each binding
contains `answer_pointer` and `packet_pointer`; their actual canonical values
must match. A dependent stage must produce a genuinely new packet. A transform
reference is an auditable host code identity, not a proof that arbitrary host
Python implements its semantics correctly.

Known candidate references must already be within the original host assignment.
Discovering a genuinely new target requires a new appropriately scoped host
assignment; the executor never captures or renews a control token. Hosts own
source fetch authorization and must not hide provider calls in preparation.

## Dispatch and admission

Ready inputs with identical frozen packet digests and compatible identical
execution contexts are combined into one `Batch`, preserving question order.
Questions whose fixed-packet `use_if` condition is false are still batched, then
their answers are marked ignored. JSON types remain distinct: false does not
equal numeric zero. An ignored answer cannot satisfy a later prerequisite.

Whole-batch primitive validity is mandatory even when one diagnostic head is
valid. A malformed sibling cannot become an admissible prerequisite through
partial-result handling. Raw failed batches and their valid diagnostic heads
remain inspectable.

Qualification is unknown by default. For a qualified prerequisite, the trusted
`qualify` adapter receives the exact declared question, `StageInput`, actual
coalesced `batch`, `batch_result` and current `as_of`. It returns strict
`{status, certificate}` data; only a current `qualified` result with an exact
certificate reference passes. Status, certificate, time and parent reference
are retained for preparation, dispatch and final-consumption gates. This adapter
classifies separately issued evidence; a model label, probability or confidence
cannot qualify itself or grant source/action authority.

Source pins, READ authority and original allocation-token scope are checked
before consuming inputs and immediately before dispatch. Host currentness and
qualification are checked again after preparation and at final consumption;
late failures retain the earlier raw attempt but block its dependent path.

Default dispatch permits only unprotected `offline_fixture` or
`recorded_replay` inputs. A protected packet, or `provider_shadow`, requires an
explicit host dispatcher. For protected data, wrap actual
[`AccessService.dispatch`](access.md), passing the exact rendered question
objects and original access context, with a detached original preparation view
and the configured fresh-read factory. The injected wrapper must perform that
real current gate; a no-op fixture is not evidence of provider authorization.
No database read transaction should span external I/O. The tests exercise the
actual AccessService wrapper and its protected-default refusal.

## One committed allocation and retained evidence

The executor reads `BudgetService.resource_envelope` once and carries a
decreasing local call/input-byte/output-byte remainder across all batches.
It rechecks `require_committed` before host preparation, dispatch and final
consumption. Candidate caps use the actual allocation's optional `candidates`
dimension; absent capacity authorizes no fetch. Declared retries and cost units
remain allocation facts. This executor performs no automatic retries and records
actual monetary cost as null with a missing-basis reason.

Each dispatch conservatively reserves the request/response byte ceilings and
one call before work. Deadlines are clipped to both the allocation deadline and
remaining elapsed allowance, conservatively floored to milliseconds. No spent
or unknown work is refunded. Actual known invocations are separate from
reservations; an opaque dispatcher failure leaves the total invocation count
unknown rather than claiming zero calls.

A reservation is one work assignment. Hosts must not invoke this uncommitted
runner repeatedly with a fresh copy of the same envelope to reset capacity.
Use MAT-030's [receipt store](semantic-receipts.md) for durable pre-I/O claiming,
attempt idempotency and exact reuse. Its `view_result` supplies the current-batch
view to this planner; a cache hit retains the original execution and adds zero
new calls. This synchronous runtime cannot preempt a Python callback that ignores
cancellation.

`StageRun.value` retains the plan/reservation identity, exact prepared inputs,
batch requests/results, parent trace IDs, ignored questions, timed gate
decisions, safe stop codes, resource reservations and actual/unknown invocation
observations. Trace references identify uncommitted evidence; they are not
stored host authority receipts. No result from this module alone authorizes an
action or establishes a domain conclusion.

The [validation receipt](validation/MAT-029.md) separates local synthetic checks
from provider accuracy, release qualification and live usefulness.
