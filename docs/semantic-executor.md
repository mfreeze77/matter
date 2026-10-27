# Typed semantic executor

MAT-026 supplies detached provider-neutral interface values and an injected
offline executor. It does not construct a vendor client, obtain credentials,
issue qualification, publish assessments, or call a host action. The governing
[semantic contract](jev.md) and [rule contract](contracts/rules.md) still apply.
MAT-027 owns the later specification registry and renderer; MAT-030 owns durable
execution receipts and reuse; MAT-031 owns semantic qualification admission.

## Questions and batches

`matter.semantic.Question` accepts a JSON object with `id`, `family`, `revision`,
`primitive`, `instructions`, `criteria`, `specification_digest`,
`rendering_revision`, `packet_digest`, and `bound_ids`. It represents a fully
rendered instance, not a registry. The host supplies the specification digest;
this interface binds the exact provided question bytes but does not verify that
the digest belongs to an installed specification version.

Supported primitives have separate criteria and response requirements:

- `choice`: an ordered list of objects with `id` and `description`; at least two
  distinct IDs. The answer retains the selected option, complete distribution,
  and separate confidence. The selected option must have maximal transmitted
  probability; ties are permitted.
- `score`: an ordered list of descriptive levels. The answer retains the
  fractional position, exact legend, complete indexed distribution, separate
  confidence, and the observed difference from its probability-weighted mean.
- `proposition_probability`: an object with explicit `true` and `false`
  descriptions. The answer retains the probability of the proposition named in
  the instructions. The TypeSafe Noul primitive projects to this meaning in a
  future adapter. There is no confidence or severity field for this primitive.

`Batch` accepts `schema_version: "1.0"`, `id`, `scope_id`, `run_id`, `stage_id`,
`state`, `packet_digest`, ordered `questions`, and `context`. `state` is frozen
JSON-native data. Its digest must equal
`canonical_digest(state, "matter.semantic.packet.v1")`; every question must bind
that exact packet digest. IDs are unique within a batch. The host remains
responsible for evidence eligibility, source access, and independence of the
questions. A batch cannot consume a sibling answer as an implicit prerequisite.

Context fields are `provider`, `transport`, `requested_model`, `adapter_version`,
`mode`, `deadline`, `max_request_bytes`, and `max_response_bytes`. The deadline
uses the existing explicit `known_time` dictionary. Supported mode names are
`offline_fixture`, `recorded_replay`, and `provider_shadow`; no mode grants
qualification. Limits are at most 128 questions and 1 MiB of request/response
bytes, and hosts can select smaller limits. The request budget includes the
complete canonical Batch, including its context.

Question, batch, capability, precision and result values retain canonical bytes
internally. `.value` returns a detached JSON object, `.canonical` returns bytes,
and `.digest` uses the existing framed canonical algorithm. Array order and all
question/context/state changes contribute to batch identity. Mutating a returned
dictionary cannot change the original value.

## Neutral response and exact numbers

`normalize_response(batch, original_bytes, precision=...)` accepts strict UTF-8
JSON with exactly `answers` and `resolved_model`. `answers` is an array, so even
duplicate answer IDs remain available for diagnosis. Each answer names its `id`
and `primitive` plus these fields:

- Choice: `choice`, `probabilities` keyed by every option ID, and `confidence`.
- Score: `score`, `legend` keyed by every stringified zero-based level index,
  `probabilities` with those exact keys, and `confidence`.
- Proposition probability: `probability` alone.

For example, the bytes below are a response to one rendered probability question
whose correlation ID is `q0`:

```json
{"answers":[{"id":"q0","primitive":"proposition_probability","probability":0.1234567890123456789}],"resolved_model":"synthetic-model-v1"}
```

Numeric JSON tokens are parsed directly into lossless decimal lexemes. Decimal
strings are also accepted for explicitly normalized adapter representations.
Normalized answer numbers and residuals are canonical decimal strings. Numeric
range, distribution sum, Score mean and tolerance checks use decimal arithmetic
with a fixed sufficient context, before normalized receipt hashing. No path
converts through binary float. Booleans, nonfinite values, invalid legends,
missing probabilities, altered key sets and impossible numeric values fail.
Decimal coefficients are limited to 128 digits and exponents to magnitude 128;
oversized values fail before fixed-point expansion.

The result retains exact received bytes as Base64, source SHA-256, byte length,
and each original JSON number's path and lexeme. Its canonical digest covers
those bytes and the normalized diagnostics. These retained bytes are the exact
neutral response supplied to this interface. A native transport adapter must
also preserve its original provider artifact when projection changes the wire
shape; this implementation does not claim to reconstruct native wire evidence.

Passing an SDK mapping instead of original bytes returns `original_wire_required`
with `exact_numeric: false` and an unavailable raw artifact. Formatting an SDK
float back into text does not recover precision, and a host must not claim it
was the original response. There is no native SDK projection in this milestone.

`PrecisionProfile()` defaults to exact sums and means. An explicitly trusted
profile can select versioned probability and Score quantums. Nonzero quantums
declare independent nearest rounding: transmitted values must lie on that grid,
and the clipped probability intervals must contain a distribution summing to
one. A Score must be compatible with the minimum/maximum mean attainable by
that distribution and its own rounding interval. Observed distribution and
Score residuals remain recorded. The response cannot select or widen its
profile, and the implementation supplies no provider-specific tolerance.

## Whole-batch validation and execution

The result's `.primitive_valid` reports structural and exact numeric validity of
the entire batch. Missing, duplicate, unexpected or wrong-type IDs make it false.
Valid independent answer diagnostics are retained; they cannot silently become
partially admitted results. `admission.qualification_status` remains `unknown`,
`certificate` is null, and `consequential_use` is always false. A successful
transport or high confidence cannot change those fields.

An `Executor` exposes immutable `Capabilities` and
`execute(batch: Batch) -> RawExecution`. Capabilities identify provider,
transport, adapter version, supported primitives/modes, and question/request/
response limits. `execute_batch(executor, batch, clock=..., precision=...)`
checks identity, mode, primitive support and budgets before dispatch. Unknown
primitive names can be represented in Question so negotiation can refuse them;
they never pass answer validation. The clock is an injected host function
returning a `known_time` dictionary. A call at or after the deadline is refused.
Late completions and reversed clocks invalidate admission while preserving
available diagnostics. The synchronous deadline is cooperative, not preemptive.

`FixtureExecutor(capabilities, {batch.digest: raw_bytes})` supplies exact offline
recordings. A recording miss is an execution failure; it does not fall back to
another packet/model or invent a negative answer. Fixtures accept only offline
or replay modes. Adapter exceptions yield a fixed fault without exposing their
message. An injected adapter is trusted host code; this is not a process sandbox
for untrusted Python. No host action or delivery callback is part of the API.
Usage and cost remain null with explicit reasons because this interface does
not measure them. Full durable execution receipts remain MAT-030.

Run the synthetic conformance suite with:

```bash
python -m unittest discover -s tests/semantic -v
```

The [combined example](../examples/ready_foundations.py) also exercises this
interface. See the [validation receipt](validation/MAT-026.md) for executed scope.
