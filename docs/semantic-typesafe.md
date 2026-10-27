# Optional TypeSafe HTTP adapter

`matter.semantic.providers.typesafe.TypeSafeHTTPExecutor` implements one original,
optional stdlib HTTP path compatible with Oil's arbitrary-question `ask` boundary.
The [recorded reuse decision](reuse/semantic-evaluation.md) compares pinned Oil and
SDK surfaces and their licenses. Matter imports neither runtime and adds no SDK
dependency. Importing the common core or this module reads no credential and
opens no connection. Only explicit construction selects the provider.

```python
from matter.semantic.providers.typesafe import TypeSafeHTTPExecutor

executor = TypeSafeHTTPExecutor(
    model="jev-1.14.0",   # explicit host selection; no discovery or default model
    timeout=30,
    max_calls=1,
    max_retries=0,
)
```

Construction reads `TYPESAFE_API_KEY` only when `api_key` is omitted. It never
loads `.env`. Missing configuration raises a fixed `TypeSafeConfigurationError`;
it cannot substitute a fixture. Credentials are private constructor state, never
result fields. Timeout must be positive, finite and at most 300 seconds. Each
instance shares its explicit local call cap across threads. Durable attempts and
budgets belong to the host, rather than this additional local cap.

## Execution and guarded egress

The exact Batch context must name `provider="typesafe"`, `transport="http"`,
`adapter_version=ADAPTER_VERSION`, the configured requested model, and
`mode="provider_shadow"`. The adapter refuses offline/replay modes. Restore
recorded evidence with `ExecutionReceiptStore.replay`, which makes no HTTP call.
Score has the vendor's native maximum of ten ordered levels. Choice criteria
become an ordered ID-to-description map; Noul criteria retain the explicit
`true` and `false` meanings. The adapter does not fetch sources or reinterpret
question specifications, renderings, identities or profile meaning.

Use actual `ExecutionReceiptStore.run` with a committed resource allocation,
original work token and an explicit guarded dispatcher. Private packet preparation,
rendering, recording and dispatch must use the installed `AccessService` and its
original access context. The dispatcher calls actual `AccessService.dispatch`
with host fresh reads for every explicit attempt. Close database read transactions
before invoking external I/O; a detached `FrozenAssessmentView` can carry the
declared captured inputs. The integrated tests exercise this path and perform a
separate SQLite write during the injected HTTP boundary. The raw adapter alone
is privileged host machinery and is not an authorization service.

The fixed endpoint is `https://api.typesafe.ai/v1/systemone`. The stdlib transport
disables redirects and ambient proxy selection, sends one POST, and bounds UTF-8
JSON request and response bytes by both adapter and Batch limits (at most 1 MiB).
The socket timeout is the lesser of configured timeout and remaining Batch
deadline. Synchronous I/O remains cooperative; no thread preemption or remote
exactly-once guarantee is claimed. There are zero automatic retries. MAT-030 owns
logical/attempt IDs, started/completed/unknown receipts and explicit retry lineage;
MAT-020 conservatively charges each claimed attempt before dispatch. A later
attempt needs its own authorized capacity even after timeout or unknown outcome.

## Native evidence and precision

Original response bytes are parsed with the existing exact numeric lexer before
any SDK-shaped typed values are inspected. An original-lexeme emitter creates
the neutral response, then the existing whole-batch validator checks distributions,
Score means, legends, IDs and shape. Canonical decimal strings and residuals
retain exact numeric meaning; wire artifacts separately retain numeric spelling.
Native quoted numbers, booleans, extra fields and substituted Score legends cannot
silently qualify as numeric answers. Noul never gains an invented confidence.
Valid heads remain diagnostic evidence when another head invalidates the batch.

`precision_profile` is an explicit trusted `PrecisionProfile`, exact by default.
Pass that same profile into the receipt request/core execution. No response can
select a tolerance, model resolver, specification, criteria or renderer. The
observed response model is recorded independently of the host's requested model
and concrete-model binding; missing model is `model_unresolved`, never a guess.
Neither a primitive-valid result nor an adapter conformance pass grants method
qualification or consequential authority. Actual MAT-031 applicability remains
an independent current certificate check.

The injected callable accepts `body`, `api_key`, `timeout`, `max_response_bytes`
keyword arguments and returns immutable `HTTPResponse(status, content)`.
For SDK-shaped conformance it can instead return an object exposing original
`raw_http_response.content` bytes and `status_code`. This is the same normalization
boundary, not a second SDK client. Typed SDK floats or integer-indexed Score maps
are never substituted for the wire. Without recoverable original bytes, execution
records `precision_unavailable` and exact numeric admission is false.

Native and neutral bytes remain separate immutable payload artifacts under
MAT-030, with their own digests and lengths. HTTP headers and arbitrary exception
text are never persisted. A response echoing the configured credential, including
JSON-escaped spelling, is withheld entirely; invalid JSON is also withheld because
its decoded strings cannot be safely inspected. Safe parseable failure bodies may
remain native diagnostics. Faults use fixed literal codes only. Timeout, rate
limit, malformed response and missing-model observations remain unqualified.

Instrumentation records observed request/response bytes, times and native integer
usage counters where available. Missing counters and IDs are null with reasons;
total tokens are not guessed from components. Cost and pricing remain unknown,
not zero. Host receipt IDs remain authoritative even when the transport exposes
no native identifiers. No credentials, headers, pricing service or SDK object is
stored.

## Verification boundary

`tests/semantic/test_typesafe_adapter.py` uses injected synthetic HTTP and SDK-wire
fixtures, a network-denying import subprocess, real SQLite attempts/budgets and
actual access/qualification ports. It makes no live provider requests. The earlier
single synthetic live diagnostic was sent through Oil, not this adapter; replaying
its retained native bytes offline checks compatibility only. Empirical provider
qualification, threshold selection and live usefulness remain MAT-039/040 work.
