# Typed rule stages and deterministic composition

MAT-014 adds `matter.planner.RulePlan`, `matter.executor.GraphExecutor`, and
exact `matter.conflicts.ConflictResolver` declarations. It extends the existing
[rule interface](rules.md) and [immutable profiles](profiles.md) under the
[governing rule contract](contracts/rules.md). The executor produces immutable
uncommitted diagnostics, not a current assessment or permission to act.

## Compile the exact graph

A `RulePlan` accepts an admitted `ProfileDefinition`, exact `RuleRegistry` and
`SchemaRegistry`, and a mapping from explicit node names to every selected
profile rule. Each rule is selected exactly once. Immutable rule prerequisites
supply required edges; profile component dependencies supply stage barriers.
The planner validates the union of those edges and all additional conditional
edges before dispatching anything. A conditional cycle is invalid even if a
particular input might make one edge inactive.

```python
from matter.planner import RulePlan

plan = RulePlan(profile, rules=rules, schemas=schemas,
    nodes={"selection": selection_rule.reference, "recovery": recovery_rule.reference},
    input_bindings=[{
        "from": "selection", "to": "recovery",
        "source_pointer": "/candidate_revision", "target_pointer": "/candidate_revision",
    }])
```

The selected producer's exact output schema supplies each edge's type. Accepted
labels, statuses, and qualification requirements come from the dependent rule's
immutable prerequisite declaration. Every required edge needs an explicit JSON
Pointer mapping from its semantic output value into the dependent proposition
value. Empty pointers select a whole JSON value. Arrays use exact nonnegative
JSON indices. The executor compares the actual selected and consumed values;
a dependent callback cannot substitute another candidate revision or ignore the
declared consumed field while retaining a plausible same-rule result.

Optional `conditions` use closed objects with `from`, `to`, `accepted_labels`,
`accepted_statuses`, and `require_qualified`. These are admission selectors,
not executable expressions. A usable applicable outcome that does not match the
condition produces a skipped path. Missing, unqualified, ambiguous or otherwise
unusable prerequisite work produces a blocked path rather than a false semantic
answer. Conditional edges do not add undeclared upstream judgments to the rule's
packet; only its immutable required edges may supply consumed data.

The full compiled declaration has a content-bound `plan.reference`; additional
conditions/mappings/composition rules cannot silently inherit the old plan ID.
Compilation checks output labels/statuses, exact profile membership, typed
composition groups, required consumption mappings and explicitly admitted
resolver references. It never constructs a provider client or evaluates source
text.

## Prepare after admission, through the host

`GraphExecutor` reuses the actual MAT-012 `RuleEvaluator`. It calls the explicit
host callback `prepare(node_name, admitted_predecessors)` only after every
required predecessor has passed fresh exact-input/result, qualification,
currentness, and control-context admission. Each predecessor entry contains:

```python
{"judgment": exact_uncommitted_judgment_input,
 "input": {"rule_definition": exact_rule_meaning, "packet": original_packet}}
```

The host returns a public `EvaluationInput` from `prepare_input` using a fresh
authorized read view. Public prerequisite preparation requires actual stored
judgment records, so the host must stage the exact prerequisite and retain its
original input/control context before it builds a dependent packet. This API
supplies no automatic storage handler. A host can explicitly persist immutable
diagnostic attempts without publishing a current assessment; publication still
belongs to MAT-015. Unavailable staging yields a typed blocked path.

The executor checks that the returned packet contains precisely the selected
original prerequisite bodies, identities and input material, as well as the
explicitly mapped output values. Another result for the same rule cannot replace
that selected pair. Host staging must not reinterpret a creation receipt as
source truth or action authority. Tests use a clearly synthetic stored-shape
read view; they do not establish a durable staging implementation.

```python
from matter.executor import GraphExecutor

run = GraphExecutor(rule_evaluator, conflicts=resolver_registry).execute(
    plan, prepare=host_prepare, run_id="assessment-attempt-1",
    max_workers=2, check_current=host_check_original_input,
    check_control=host_check_captured_control, cancelled=host_stop_requested,
)
```

`check_current` must recheck original source/dependency pins, clocks and captured
control contexts. A fresh token with an equal epoch does not replace the
original context. The executor honors an explicitly installed host currentness
guard even when a packet has no native mutable watch. Admission is rechecked
before dependent preparation and at final consumption. Final failure of a
required or conditional predecessor also blocks its already-executed descendants;
their original attempts remain diagnostic evidence. No result is repaired by
inventing a new input or recapturing authority.

Final consumption rechecks each edge's original label/status/qualification
selector, not just the predecessor's execution status. A certificate that expires
after the child ran therefore blocks its descendant even though both raw attempts
completed. Every incoming edge check is retained in `final_edge_admissions`;
cancellation and blocked gates take precedence over conditional skips. Previously
skipped conditional paths are also rechecked without fabricating a new input.

## Concurrency and shared remaining budgets

`max_workers` is between one and sixteen. Independent nodes in a ready frontier
run in a bounded thread pool; explicit dependencies run in later stages. A
stable sorted frontier barrier makes call/byte admission independent of worker
completion order. Unrelated successful results survive another node's failure.

`remaining_budget` can narrow, never enlarge, the profile's exact resource
limits. Before dispatch, the executor conservatively reserves one attempt, the
actual canonical input bytes, and the rule's declared output-byte cap. Evidence
limits are per packet. Calls/bytes are shared across the run, so concurrent nodes
cannot each claim the same remaining allowance. `actual_invocations` comes from
the existing attempt receipt's `called` flag: evidence/precondition fallbacks
are not mislabeled evaluator calls. Output reservations are declared upper
bounds, not measurements of actual provider usage or returned bytes.

The resource receipt distinguishes `admitted_budget` (the input ceiling) from
`remaining_budget` (the conservative allowance for a later run). Remaining calls
subtract reserved attempts, input/output bytes subtract their reservations, and
elapsed time subtracts the rounded-up observed run duration, all clamped at zero.
Failed or fallback attempts keep their reservations even when they invoked no
evaluator. The per-packet evidence cap remains unchanged. Passing that true
remainder into another run cannot reuse an already reserved call allowance.

A shared elapsed deadline stops later dispatch and composition. A result that
returns after it is retained as a timed-out diagnostic, even if its individual
rule completed. Cancellation is latched: a subsequent false poll cannot reopen
the run. Successful early results keep their actual attempt records.

A host stop-query exception or non-boolean response also latches cancellation.
The run retains a fixed safe entry in `stop_diagnostics`, never exception text
or the invalid response. A failed poll after a binding returns cannot discard
its raw judgment, attempt receipt or actual invocation count; an initially
failed poll prevents preparation and dispatch.

Host preparation runs serially; evaluator/currentness/control callbacks can run
concurrently and need thread-safe, fresh host handles. `max_workers=1` supports
serial handles. The thread pool joins its workers. Synchronous Python callbacks
must cooperate: this mechanism cannot kill a blocked function, enforce a memory
sandbox, preempt host reads, or prevent a callback from exceeding a resource cap
before it returns. Hosts must supervise untrusted or blocking work externally.
No external provider transport is introduced here.

## Explicit conflicts and mandatory gates

`ConflictResolver(namespace, id, version, mode="retain_conflict")` defines a
content-addressed deterministic policy. `mode="precedence"` additionally
requires a complete explicit node-name order. Install the exact resolver in
`ConflictResolverRegistry` and admit its reference in the profile/rule conflict
policies. There is no implicit resolver, confidence ranking, last-writer choice,
majority vote or probability arithmetic.

Executor preflight checks that a precedence order covers every node in each
composition before any host preparation or evaluator dispatch. An incomplete
order fails independently of whether an eventual result would be withheld.

Each optional plan composition declares `id`, exact `resolver`, distinct `nodes`
with one exact output schema, and explicit `mandatory_gates`. Gates contain
`node`, `accepted_labels`, `accepted_statuses`, and `require_qualified`. They
are checked before any resolver can choose a result. Group results must be
applicable and qualified or deterministic. High impact cannot offset incomplete
source coverage, a failed authority gate, cancellation or stale dependencies.

Retain-conflict mode preserves incompatible original results with `status:
conflicting`, `treatment: quiet`, and no selected semantic conclusion. Declared
precedence can select a result while retaining every disagreeing original.
Withheld gates produce `status: withheld` with explicit reasons and originals.
Even resolved composition is only a proposal; no host mutation or delivery
callback is available to the resolver.

## Run diagnostics and later publication

`GraphRun` is created through the executor and stores canonical immutable bytes;
public values are detached. Its `reference` binds the entire diagnostic. Fields
include the single host scope, exact plan/profile pins, stable node receipts, original prepared inputs,
composition results, resource reservations, overall status and stop reason.

Node receipts distinguish completed, unresolved, blocked, skipped, failed,
cancelled, timed-out and budget-exhausted paths. They retain rule references,
actual input digests, selected upstream input digests, original judgments and
attempt receipts when produced, error codes, reasons and final admission checks.
A path never prepared has a null input digest and no fabricated judgment. A
completed raw attempt can coexist with a blocked or timed-out graph-path receipt;
the difference explains why its semantic result cannot be consumed.

The `inputs` mapping preserves every original `rule_definition`/`packet` pair.
Downstream assessment publication must retain all relevant conditional/control
and selected-input dependencies from the run and perform its own atomic guards;
a historical graph diagnostic does not become a current assessment merely by
being serialized. MAT-015 owns publication and semantic cache admission;
MAT-016 owns general transitive invalidation. No provider accuracy, production
latency, or live usefulness is qualified by these offline stages.

See [MAT-014 focused evidence](validation/MAT-014.md).
