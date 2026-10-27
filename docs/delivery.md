# Freshness-checked delivery

MAT-021 adds a neutral durable outbox over the existing SQLite storage, controls,
assessment/attention freshness and budget services. The transport is an injected
host port. No broker, worker daemon, external client, notification adapter or
retry scheduler is included. All repository examples and tests use synthetic
content and local injected transports.

`DeliveryService` composes the existing `AttentionService`, `BudgetService`,
`ControlService` and scoped payload store. The host installs immutable
`DestinationDefinition` and `TransportCapabilities` values from `matter.outbox`.
A destination binds an exact audience and transport and an independently
permissioned public entity. Receipt, control and internal bookkeeping targets
cannot stand in for that destination grant. Registering a destination does not
grant an actor permission to send to it.

The transport declares its producer, successful milestone, optional stable-key
idempotency scope/retention and optional reliable terminal receipt-lookup scope.
These declarations are host assertions about the actual transport contract.
They are not inferred from a model, a local lease or a successful HTTP request.
The engine checks that the producer/milestone is allowed by the selected
attention policy. A `TransportResult` distinguishes `delivered`, definite
`failed`, `delivery_unknown` and lookup `not_found`, preserving known or unknown
transport time. Status/reason pairs are strict: accepted means delivered,
rejected means definite failure, timeout/unavailable/unknown mean unknown, and
not-found remains a lookup result. Delivered requires a receipt identity and the
declared milestone.

## Preparation, lease and authorization

The executable fixture is [delivery_helpers.py](../tests/integration/delivery_helpers.py).
The public sequence is:

1. Prepare an ordinary `prepare_delivery` command with `service.prepare(...)`.
   Supply the actual attention decision and its original evaluation command,
   original delivery control token, destination, exact rendered bytes, attention
   budget/amounts, expiry and original access context when access policy is installed.
2. Execute that prepared command. A successful `ready` result returns an immutable
   intent. Queue publication and an actual held attention reservation are atomic.
3. Call `prepare_claim(...)` and execute it to receive a worker token, increasing
   fence and finite lease. A lease itself authorizes no I/O.
4. Call `prepare_authorize(...)` with that exact lease and original token. Pass the
   prepared command to `send(...)`, or execute it explicitly when the host owns
   the subsequent trusted transport/factual-recording boundary.

Preparation captures exact assessment, decision, audience/purpose contexts,
material contract/digest, prior delivered baseline, dependency manifest, original
control/access context, expiry, destination authority and content digest. The
rendered bytes live in the existing content-addressed payload store. Model
judgments and copied text do not become action authority.

The equivalence key uses the matter, stable purpose/audience identities and the
before/after material contract and digest. Arbitrary intent IDs, wording and
attention-policy versions do not make the same semantic delta new. Exact context
versions and policies still govern eligibility. A per-delta slot prevents two
SQLite handles from authorizing competing equivalent intents. Actual new material,
including a new deadline or a corrected fact, remains an attention-policy decision;
this module adds no civic or legal meaning.

The **authorization transaction commit is the declared linearization point**.
Inside that transaction the service rechecks original authority, current source,
assessment/recovery, attention decision, contexts, baseline, destination permission,
control epoch, access restrictions and lease. It commits the actual held attention
allocation and inserts an immutable authorization, attempt state and fenced slot
atomically. Host time is sampled again after budget staging; crossing the intent
or lease deadline rolls back both authorization and charge.

`prepare_withhold(intent, token=original_token, reason=..., ...)` supplies bounded
withdrawal for queued or leased work that has never been authorized. Execution
checks present READ/static authority, releases only its actual unused allocation,
appends a withheld fact and clears the lease with a higher fence atomically.
Withdrawal does not renew the old token. A later current same-material attempt
can then reserve capacity normally. Old workers cannot authorize through the
changed slot; authorized or unknown attempts cannot withdraw or refund. Exact
withdrawal replay returns its original result without reentering the ledger.

No read transaction survives transport I/O. `send` checks eligibility again after
commit, then calls the injected `transport.send(destination=..., delivery_key=...,
content=..., authorization=...)` once. The final local check and external action
cannot be one atomic transaction. Cancellation observed before authorization
prevents the send; cancellation or recovery after irreversible sending cannot
retract it. The original token is retained, never renewed by recapture.

## Unknown outcomes and recovery

An authorization is durable before I/O. If the fresh owning process observes a
known local guard, lease or content failure before calling the transport, it
records a **system-origin definite no-send** fact and raises the local error. A
serialized generic observation cannot claim this private local proof. The
committed allocation remains charged; later eligible work can proceed as a new
intent. This is distinct from a process disappearing without an observation.

Process loss before send, acceptance
followed by process loss, timeout, malformed adapter output or an exception cannot
fabricate a delivered receipt. The stored attempt phase remains `authorized`
until an observation exists;
`history` maps that unresolved outcome to `delivery_unknown`, and a `send`
replay raises `E_DELIVERY_UNKNOWN`. A failed or ambiguous attempt retains its
conservatively
committed attention charge; allocation is not evidence that delivery happened.

There is **no resend/retry API or automatic retry loop**. Authorized or unknown
attempts block equivalent redispatch even after lease expiry and even if a
transport advertises idempotency. Idempotency expiry never silently grants a new
key. A resumed old worker cannot authorize under an obsolete fence; if an old
worker had already crossed authorization outside this process, a later missing
receipt cannot prove that it will never reach I/O.

`reconcile(authorization, command_id=..., idempotency_key=...)` is lookup-only.
It requires present READ/source access and the exact configured transport's
explicit lookup capability. A reliable positive lookup records the actual
milestone without sending. `not_found`, lookup unavailability or an ambiguous
answer records or retains unknown and raises `E_DELIVERY_UNKNOWN`; it does not
permit a resend. A transport with no lookup capability leaves the attempt unknown
for host investigation. Repeated unknown observations are coalesced into the
retained unknown receipt;
each outer report remains in the command journal. Unknown polling therefore
cannot fill the 128-entry history and prevent a later positive receipt. The
remaining observation bound refuses additional work rather than dropping facts.

The host may retry a prepared **storage command** exactly after a local storage
failure; that is not permission to repeat external I/O. `execute` uses the existing
command journal. A replay of `send` inspects the durable attempt instead of calling
the transport; its resolved replay value is the actual journaled typed completion
result.
Immediate replay is equal to the original result. Already delivered or definitely
failed reconciliation returns that completion without querying the transport.
Present READ/access denial blocks disclosure
on both paths. Missing transport configuration refuses new work before a durable
claim; authorized history remains inspectable after configuration removal.

## Facts, baselines and independent outcomes

`prepare_observation(...)` is a trusted factual adapter boundary. It records what
an already authorized transport observed; it grants no fresh dispatch authority.
It binds the actual immutable authorization and its authorizing command/result
proof to the reserved storage operation receipt. A caller-shaped producer string
or forged proof cannot substitute for that journal provenance.

Factual completion retains the original actor/authority and can record a real send
after cancellation, source correction or READ revocation. Public result/history
access still checks present READ and original source/audience/provider eligibility.
The receipt records the eligibility observation time and safe invalidation error
when the original work became stale. That diagnostic does not reinstate authority.
A concurrent storage conflict can refuse factual publication; the failed command
remains journaled and the host must prepare a fresh factual observation, without
resending. The `before_io`/`after_io` injection hooks exist for deterministic host
fault tests; process loss leaves the durable pre-I/O authorization intact.

Only the declared observed success milestone can advance the MAT-019 delivered
baseline. Transport time orders baseline updates only when it falls within the
original
authorization/host-observation interval. Skewed reported timestamps are preserved
exactly with unavailable ordering; they do not discard a real success or order a
baseline by a remote future time. Valid positive transport time orders updates;
an older reconciliation
cannot overwrite newer delivered knowledge. With unavailable transport time,
advancement requires the baseline to remain exactly the one captured at
authorization. Late success remains in history even when it cannot advance the
baseline. Unknown, failure and withholding never advance it.

Delivery alone creates no consumption, action, repair or usefulness claim.
`prepare_outcome(authorization, evidence, ...)` appends an independently stored
host receipt whose stage is `consumed`, `acted_on`, `outcome_verified` or `useful`.
The receipt must come from the original configured transport producer and explicitly
cite the authorization. Such outcomes require a delivered attempt, retain their
own evidence and do not change transport status or the delivered baseline.
`history(authorization)` checks current disclosure rights before returning immutable
observations. Trusted raw database handles remain privileged; this API is not a
sandbox for arbitrary host storage access.

The [validation receipt](validation/MAT-021.md) separates synthetic behavior from
independent source review, installed-package checks and real transport usefulness.
