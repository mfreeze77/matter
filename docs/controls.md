# Trusted controls and scoped authority

MAT-011 implements a host-only control lane, durable scoped fences, guarded mutation and read seams, and explicit cooperative cancellation hooks. It does not authenticate a person, execute a provider, supply a scheduler, send messages, or replace the existing association and merge policies. Authentication and access to the raw storage handle remain the host's responsibility.

The control lane does not consult evaluators, recurrence, salience, resource budgets, or attention budgets. `ControlService.apply` returns after the control, projection changes, and operation receipt commit. SQLite may wait behind another short writer; this is independence from evaluation and budgets, not a preemptive or real-time latency guarantee. Provider calls, callbacks and external I/O must stay outside write transactions.

## Admission and effects

`AuthorityPolicy(scope_id, actors=..., authorities=..., capabilities=..., control_kinds=..., targets=None)` is immutable. Authorities are exact pins of stored receipts whose origin is `host` and stage is `authority`. The host constructs this policy from an already authenticated transport context. An actor field, source role label, schema-valid control, evaluator answer, or high confidence cannot construct a grant.

The static capability ceiling distinguishes `association`, `merge`, `correction`, `transition`, `read`, `delivery`, `assessment`, and `write`. Permission controls can restrict these capabilities and explicitly release a restriction within the ceiling. `targets=None` permits the whole declared storage scope; a configured target list permits only those exact entity references. No substring, semantic similarity, redirect, or inferred hierarchy expands this grant. Existing domain policies remain mandatory: general association authority does not supply `MergePolicy`.

Controls reuse the existing `record_control` command and immutable `control` record. The body actor, authority and scope must match the command. Target references use canonical ordering. The runtime interprets only the packaged `control-effect` schema produced by `control_effect(action, reason, capabilities=..., payload=...)`:

| Action | Admitted kind | Effect |
|---|---|---|
| `cancel` | `cancellation` | Blocks guarded work in the applicable scope. |
| `resume` | `instruction`, `correction`, or `decision` | Explicitly supersedes the current matching-scope cancellation. |
| `deny` | `permission` | Denies the named capabilities within the static ceiling. |
| `allow` | `permission` | Explicitly supersedes matching-scope denials; creates no new capability. |
| `invalidate` | Other declared control kinds | Advances the applicable fence and retains the host's typed correction or task change. |
| `disposition` | Other declared control kinds | Retains the scoped host disposition and advances the fence. It does not resolve a matter or interpret an arbitrary payload. |

Controls must be effective at application time. Finite restrictions use a half-open interval: active at `effective_from`, inactive at `effective_until`. For this registered effect schema, an unknown end with reason `not_applicable` explicitly means no automatic expiry until supersession. Other unknown endpoints and future controls are refused. Generic time helpers do not acquire this special interpretation.

Resume and allow are permanent supersessions and therefore require the explicit no-expiry form. Temporary permission overrides are unsupported. Their `supersedes` array must include the exact current restriction and have the same original target scope. A narrow `[A]` grant cannot release `[A,B]` or scope-wide control. Independent overlapping scopes remain conjunctive. Within one exact scope, a later stop or denial can strengthen a restriction, but a shorter end cannot weaken an earlier end or indefinite restriction. Releasing an A-only restriction therefore leaves a still-applicable A-and-B restriction intact.

An ordinary observation cannot occupy the internal `matter.controls` projection namespace or the hook namespace. SQLite also reserves these addresses across core-record creation paths. A preexisting wrong-kind occupant produces an explicit integrity/storage failure, never an invented epoch zero. Raw SQLite mutation and privileged host storage code are outside this local trust boundary.

## Prepare, apply and retry

Use `controls.prepare(command)` once. It binds the next audit epoch and all preexisting reads into the command. Persist that exact returned command, then call `controls.apply(prepared)`. The control's proposed epoch before preparation is only a placeholder; execution compares the prepared epoch with the current sequence.

Exact command replay returns the original result and never reapplies the control. New-command redelivery of the identical immutable control returns `duplicate` and retains its original epoch. Changed content under a control identity is a source-identity conflict. A stale prepared control returns a revision conflict; a new attempt requires a new command ID/key and explicit fresh preparation. There is no silent loop, overwritten journal, or automatic work-token renewal.

The global audit sequence orders accepted controls. It is not a dependency of every worker. Work depends on the scope-wide fence plus its exact target fences. A control affecting A does not advance B's fence. The scalar `control_epoch` in a work token is the maximum applicable epoch for explanation; the complete fence manifest determines currentness, including explicit absence of a target fence at capture time.

## Protect work before and after evaluation

Capture a token before expensive work:

```python
prepared = association_service.prepare(command)
token = guarded_storage.capture(prepared)
# Run bounded work outside the transaction using the frozen inputs.
fenced = guarded_storage.prepare(prepared, token=token)
result = association_service.accept(fenced)
```

The service in this example was constructed with `GuardedStorage(store, controls=controls)`. `GuardedStorage.prepare` requires the original token; it cannot capture or replace one. An applicable control-state change during evaluation makes later preparation or execution fail; an unrelated target's control leaves the token usable. A later resume does not revive an earlier token. A new evaluation attempt must capture new state.

The minimum affected set is derived from every explicit entity reference in the full prepared command body and expected read set. Internal projections and receipt bookkeeping are excluded. The token must cover that set; callers cannot provide a smaller target list. A trusted domain service must still declare every read influencing its write, as required by the storage port. Work that discovers additional targets needs a new appropriately scoped attempt rather than reusing a narrow token.

The command digest binds the entire original token through the registered `matter:control-token` extension. Existing authority, governing control and fence pins enter `expected_revisions`. The guard checks inside the same transaction as the domain write. An existing fence revision mismatch may produce `E_REVISION_CONFLICT` before the guard runs; active cancellation produces `E_CANCELLED` where the guard reads current state; changed applicable state produces `E_DEPENDENCY_STALE`. All prevent authoritative child writes. Absence at capture time is explicit, so the first later target fence also blocks old work.

`ControlService.capture(actor=..., authority=..., capability=..., targets=...)` is the detached-token API for other hosts. `check(token)` checks a consistent current snapshot without mutation. `require_current(view, token, capability=..., targets=...)` is the atomic commit seam; the host must declare the token's preexisting authority/control/fence pins in the transaction read set. MAT-012 may call `check` around a binding but cannot replace the later atomic commit gate.

The host clock determines current authority. A historical or future `as_of` cannot authorize a current read or write. If that clock moves before an already committed governing control's effective start, current authority checks fail closed rather than treating the restriction as temporarily inactive. For deterministic simulation, inject a fixed clock; an explicit `as_of` must equal that clock. Historical controls remain available through trusted audit/storage queries, separately from current authorization.

## Reads, replay and dispatch

`controls.read(token, reference)` checks a `read` token and fetches the requested entity in one consistent snapshot. The reference must be covered by the token. This is the permission-checked data-delivery seam. `GuardedStorage.snapshot/get` delegation exists for trusted domain-service preparation; those methods and the raw store must not be exposed directly to an untrusted agent as a read API.

Exact guarded-command replay returns historical results without invoking the domain handler. SQLite's optional `execute(..., replay_guard=...)` checks present read permission inside the idempotency transaction before disclosing the prior result. Cancellation alone does not erase history; a current read denial blocks disclosure of both successful and failed historical results. Refusal preserves the original journal. Old success never becomes a new dispatch or new domain effect.

`controls.authorize_dispatch(transaction, token, targets=...)` is a transaction-time seam for a host with a `delivery` token. The host derives targets from its real intent, declares those reads, and records authorization before external I/O. Receipt-only dispatch commands are not automatically routed by `GuardedStorage`, because opaque receipt IDs do not reveal the affected matter. The host must implement that binding when its outbox exists. No native transport or outbox implementation is claimed here.

Cancellation observed before authorization prevents that attempt. A later cancellation cannot retract a completed external send or change a stored delivered receipt. A send after its authorization point is an explicit host transport responsibility, including its idempotency and outcome-unknown rules. MAT-021 owns the full delivery protocol.

## Post-commit hooks

`apply` never invokes hooks. After a successful durable control, call `run_hooks(control_pin, attempt_id="...")` explicitly. The host-configured callbacks receive a detached copy of the accepted control. They may cooperatively cancel old work but cannot replace the epoch fence: a running Python callable may ignore cancellation.

Each hook attempt first commits a unique `started` receipt. Only the caller whose reservation handler ran can invoke the callback. Success or a caught exception produces a separate immutable `succeeded` or `failed` receipt; only the exception type is retained, not sensitive exception text. `hook_status` reports the durable state. Replaying an attempt ID does not rerun a started or finished callback. Explicit retry uses a new attempt ID.

Crash or unavailable storage after reservation can leave `started`, meaning outcome unknown. Do not blindly retry while claiming exactly-once callbacks. An explicit hook-call storage error remains observable to that caller and cannot alter the already returned control result. The system does not automatically restart hook work, deliver external messages, or require a user closeout ceremony.

## Run the synthetic qualification

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_control*.py' -v
PYTHONPATH=src python examples/trusted_controls.py
```

The tests use real SQLite handles, existing association acceptance, synchronized worker races, explicit source spoofing, replay, restart and fault scenarios. They qualify these shared mechanisms, not live OIL effectiveness, provider accuracy, production authentication, or native delivery guarantees.
