# Provider-neutral rules and bounded judgment attempts

MAT-012 implements immutable rule definitions, exact local schemas and bindings,
detached input preparation, one synchronous deterministic or recorded attempt,
and validation of direct prerequisites. It returns proposed judgment and
evaluation receipt inputs. It does not persist them, publish an assessment,
perform an action, invoke a provider, issue a qualification certificate, or
schedule retries. The [governing rule contract](contracts/rules.md) also describes
later policy composition, assessment, invalidation, and investigation work.

Run the installed-package arithmetic example with:

```bash
python examples/rule_evaluation.py
```

The example compares two host-supplied integers. Its explicit zero-source rule
does not establish evidence for an external claim.

## Public values and registries

`matter.rules` exports `SchemaDefinition`, `SchemaRegistry`, `RuleDefinition`, and
`RuleRegistry`. Definitions store canonical immutable bytes; `.value` and
`.reference` return detached copies. Registries resolve exact descriptors. A
missing version or changed digest fails with `E_POLICY_INVALID` rather than
selecting the newest definition. Duplicate namespace/ID/version meanings are
refused. Changing the full rule meaning changes its reference digest, including
labels, fallback outputs, evidence preparation, limits, and proposal permissions.

A domain `SchemaDefinition(namespace, id, version, schema)` requires a local
Draft 2020-12 schema with an explicit unique root `$id`. Supported references
are self-contained fragment references, including local `$defs`. External and
relative resource references, nested resource IDs, and dynamic references are
unsupported. Each value is validated with only its own schema resource in the
resolver. A local pointer into annotation data therefore cannot reach another
installed resource or a packaged core schema. Unknown references never fetch
the network. Ordinary data properties named `$ref` or `$id` remain valid.

`RuleDefinition(value, schemas=registry)` checks the exact input/output schemas,
unique labels, the required insufficient-evidence fallback, precondition
fallbacks, and permitted implication schemas. Each semantic output is an object
with a declared `label`. Its label and `evaluation_status` must agree with the
rule. Fallback output values are validated at definition construction. JSON
Pointer equality preconditions use the proposition value; a missing field
selects the declared insufficient or not-applicable fallback.

`matter.evaluators` exports the following boundary:

| API | Purpose |
|---|---|
| `DeterministicBinding(..., implementation, semantics, conformance_cases, function)` | Host-installed cooperative function with explicit implementation identity |
| `RecordedBinding(..., evaluator, semantics, recordings)` | Frozen external responses keyed by the exact complete input digest |
| `BindingRegistry(bindings)` | Exact installed bindings, with no dynamic import or source execution |
| `QualificationRegistry(certificates)` | Host allowlist of already issued, content-bound certificates |
| `prepare_input(view, rule, ..., schemas, scope_id, proposition, coverage, as_of)` | Read supplied pins in a host-authorized consistent snapshot |
| `RuleEvaluator(...).evaluate(prepared, judgment_id, attempt_id, check_control=None, check_current=None)` | One pure attempt yielding an immutable `EvaluationBundle` |
| `admit_result(judgment, rule, ..., expected_input, as_of, accepted_labels)` | Revalidate the host-selected exact prerequisite at consumption time |
| `check_input_current(view, prepared, as_of, check_control_context=None)` | Read-only currentness check in a fresh host snapshot |

Keyword arguments shown after `...` are keyword-only. Registries and callbacks
are trusted host configuration. Descriptors identify the configured code; this
package does not hash Python bytecode, authenticate an arbitrary callback, or
sandbox Python. Binding callbacks receive only detached JSON, with no supplied
storage, host control, provider, or mutable core handle.

## Preparing the exact input

Keep the supplied read view's consistent snapshot context open during
`prepare_input`. Optional inputs are `subject`, `evidence`, `omitted`, `context`,
`upstream`, `negative_dependencies`, and `control_token`.

`subject` is the current pinned matter revision when the question concerns a
matter. Every evidence declaration names an exact reference, locator, quotation
or null, roles, and a locator-validation declaration from an adapter admitted
by the rule. Preparation verifies the source snapshot and locator declaration,
reads every declared validation dependency, and preserves input order. The host
is responsible for authenticating its locator adapter; a claimed adapter digest
from untrusted input is not authenticated by schema validation.

Observation availability comes from the stored observation and cannot be
replaced. Other evidence kinds require explicit host `available_at`. Judgments
and assessments also cannot predate their intrinsic recorded/produced time.
Future, unknown, unavailable, or ineligible evidence is recorded as an omission;
it is not sent to the evaluator. Required-role omissions, insufficient evidence
count, missing prerequisites, and required incomplete coverage select the
declared insufficient-evidence outcome. Preparation does not discover or rank
sources, infer completeness, or silently truncate a corpus. The host supplies
the bounded selection and explicit omitted evidence.

The input digest binds the complete definition, exact binding, proposition,
subject, ordered evidence snapshots and locators, context, omissions, coverage,
knowledge cut, dependency manifest, direct prerequisite input material, and
captured control-token digest. Recordings do not use a fuzzy question match.
A changed order, proposition, version, context, or meaningful selected content
requires a different exact recording.

## Prerequisite mapping and the two clocks

Each `upstream` declaration requires `reference`, `expected_input` (the original
prepared `.value`), and host `available_at`. Naming a rule alone is insufficient.
The stored judgment must match the expected input digest, scope, full rule and
binding, and dependency manifest. That original material remains in the new
packet so citation and proposal validation also runs when the result is consumed.
The host or future MAT-014 composition policy owns the explicit mapping between
questions; prerequisites may intentionally answer different propositions.

The knowledge cut determines which evidence may enter the input. Actual attempt
and consumption time determine current admission, deadlines, and certificate
validity. A later-produced result cannot be backdated into an earlier input or
admission, and an attempt cannot use a future knowledge cut. Historical replay
with special production semantics needs a separate explicit policy; this
interface does not silently infer that permission.

Direct predecessor positive dependencies, negative registrations, and time
conditions are retained and rechecked. Multiple results for one required rule
are refused pending an explicit composition policy. No graph planner or general
transitive invalidation service is implemented here.

## Currentness and controls

Mutable dependencies, temporal conditions, absence registrations, and upstream
results require `check_current` before and after the attempt. The callback receives
the same immutable prepared input and an actual `as_of` time. A fresh authorized
snapshot plus `check_input_current` is the reusable storage seam. It checks exact
positive pins, real negative registrations, and inclusive due/expiry boundaries.
Conservative source-catalog dependencies may invalidate a packet after a catalog
change that proves irrelevant only under a later, more precise policy.

A captured `control_token` is held privately outside evaluator-visible JSON;
its exact digest and epoch are in the input identity. A token requires
`check_control(token)` both before and after evaluation. The host supplies its
actual control-service check. The runner never recaptures or renews a token.
Post checks still run after a callback fails or times out; the evaluation receipt
retains both stage events, while the final result has no semantic conclusion.

Original prerequisite control contexts remain host-owned. When an original
input has a token digest, `check_input_current` requires a host resolver callback:

```python
check_control_context(
    input_digest=original_digest,
    token_digest=original_token_digest,
    control_epoch=original_epoch,
    as_of=actual_admission_time,
)
```

The host retrieves and checks the original captured token for that context.
Missing context fails closed. Equal epoch integers for different target sets
cannot renew earlier work. If `check_input_current` is already inside a snapshot
on the same SQLite handle, the resolver must use that existing view:

```python
controls.require_current(
    view, original_token,
    capability=original_token["capability"],
    targets=original_token["targets"],
    as_of=actual_admission_time,
)
```

The host first verifies the retained token against the requested input/token
digest. Calling `controls.check` there would attempt a nested snapshot on that
handle and fail with `E_STORAGE_UNAVAILABLE`. The runner's separate
`check_control` callback can call `controls.check` outside the dependency snapshot.
Current clock enforcement and exact target matching still apply to both paths.
Persisting/restoring complete input artifacts and
control contexts is MAT-015 work. These read-only pre/post checks do not provide
an atomic assessment commit; a result must still pass the later in-transaction
guard before publication.

## Results, qualification, and limits

An `EvaluationBundle` exposes detached `.judgment` and `.receipt` inputs. The
judgment references the actual accompanying attempt receipt; neither claims a
creation receipt. Input artifact availability is explicitly `not_persisted`.
A recording can retain a raw artifact reference or explicit unavailability.
When an invalid or oversized response returns, the runner reports unavailable
raw content rather than claiming no response existed; a valid bounded supplied
raw reference survives local semantic validation failure or elapsed timeout.

The dimensions remain separate: execution status, evaluation status, semantic
output, and qualification. Insufficient, not applicable, ambiguous, and
conflicting outcomes can be completed executions. Failed, cancelled, timed-out,
and exhausted attempts cannot supply a domain conclusion or consequences.
Independent bundles remain inspectable when another attempt fails. No retry,
joint probability, independent-vote count, or automatic conflict resolver is
added by this interface.

Fresh and consumed results use the same strict schema, label, exact evidence-ID
and locator, and permitted proposal validation. Proposals remain inert typed
values. A qualified score cannot grant host authority or a domain transition.

The qualification registry authenticates only against its explicit host
allowlist. It rechecks exact rule, binding, schemas, evidence preparation, task
scope, threshold policy, content-bound certificate, and validity at actual
evaluation or consumption time. Unknown certificates remain unknown; a recorded
answer cannot declare qualification unnecessary. The registry does not issue
certificates or verify model accuracy, cohort quality, or threshold suitability.

Byte/count limits, one call, and zero retries are enforced locally. The elapsed
limit is checked after a synchronous callback returns; `TimeoutError` is typed.
This is cooperative execution, **not a preemptive deadline** or memory/process
sandbox. Supervising blocked or untrusted work belongs to the later executor.
No claim of live provider, policy DAG, durable replay, assessment publication,
or production attention usefulness follows from these interface tests.
