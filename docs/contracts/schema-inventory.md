# Matter v1 schema inventory

MAT-002 turns the common record and operation shapes into executable Draft 2020-12 contracts. These are structural contracts. A valid document does not prove that its references exist, its authority is applicable, its evidence is true, its reads are current, or its state was durably committed.

The three canonical resources are:

| Family | File | Canonical `$id` |
|---|---|---|
| Stored record | [core-record.schema.json](../../schemas/core-record.schema.json) | `https://github.com/mfreeze77/matter/schemas/core-record.schema.json` |
| Proposed command | [operation-command.schema.json](../../schemas/operation-command.schema.json) | `https://github.com/mfreeze77/matter/schemas/operation-command.schema.json` |
| Operation result | [operation-result.schema.json](../../schemas/operation-result.schema.json) | `https://github.com/mfreeze77/matter/schemas/operation-result.schema.json` |

Every family requires the exact `schema_version: "1.0"`. The URLs identify schemas; validation registers all three local resources and does not fetch those URLs. The core schema contains shared `$defs`. Commands and results reference those definitions instead of maintaining alternative copies. The supported value domain, encoding, and compatibility decisions are documented in [compatibility.md](compatibility.md).

## Common record envelope

All 12 stored record kinds require `schema_version`, `record_type`, `scope_id`, `namespace`, `id`, `creation_receipt`, `provenance`, and a typed `body`. Core objects are closed to undeclared fields. Optional `extensions` and `supersedes` are explicit.

`namespace` is separate from `scope_id` and `id`. Equal IDs in different namespaces do not acquire the same identity. An ordinary reference has `scope_id`, `namespace`, `record_type`, and `id`. A pinned reference additionally requires exactly one of `revision` or `digest`; an unpinned reference or a reference containing both is invalid where a dependency is required. Immutable core record references require a digest because those records have no aggregate revision. Mutable aggregate references may pin a revision or the digest of one immutable revision snapshot. Namespaced external references permit either pin form under the external contract. A digest is 64 lowercase SHA-256 hex characters. Revisions are integers from 1 through 9,007,199,254,740,991. Counters such as a control epoch may also be zero.

Stored `record_type` values are the 12 kinds below. References also permit explicitly namespaced external record types such as `example:profile`, because a host may reference an independently owned registry. That does not register a thirteenth Matter record kind or assert that the external object exists. Rule, profile, evaluator, producer, and domain-schema definitions use the separate exact `component_ref` shape: `namespace`, `id`, `version`, and `digest`.

A creation receipt is a typed receipt reference. A receipt may refer to itself as its creation receipt, avoiding an infinitely embedded receipt chain. This permits structural bootstrapping; atomic creation and audit verification belong to MAT-003. Provenance requires an origin, an exact producer component, a known recording time, and parent dependencies. A derived origin requires at least one parent. An optional `run_id` records provenance and is not a continuing matter identity field.

| Record kind | Revision model | Required body meaning and references |
|---|---|---|
| `observation` | Immutable; no aggregate revision | Scoped source event identity, original content digest/locator/availability, occurrence time or interval, publication and availability times, known ingestion time, and exact extraction component. |
| `occurrence` | Mutable aggregate; revision required | Namespaced event kind, source-owned identity keys, observation dependencies, occurrence time or interval, and provenance groups distinct from event identity. |
| `matter` | Mutable aggregate; revision required | Namespaced domain kind and at least one scoped identity key. Title and description are optional. A lifecycle projection, if supplied, requires its profile, namespaced state, and transition receipt. |
| `claim` | Immutable proposition version | Referenced or schema-bound subject, namespaced predicate, typed value and qualifiers, temporal applicability, attributed evidence dependencies, and proposition version. |
| `evidence_relation` | Mutable aggregate; revision required | Pinned claim and evidence, one declared relation kind, whole-proposition or component target, exact/whole/unavailable locator, temporal applicability, and explicit acceptance state and rationale. |
| `association_proposal` | Immutable proposal | Pinned subject and candidates, selection outcome, selected references, matching rule, evidence, evaluator receipt, schema-bound uncertainty, and qualification state. |
| `accepted_association` | Mutable aggregate; revision required | Pinned proposal, observation/occurrence/matter membership, exact relationship definition, active/revoked/superseded state, and authority receipt. |
| `matter_relation` | Mutable aggregate; revision required | Two pinned matters, namespaced relationship kind, relationship schema, evidence basis, authority receipt, and active/revoked/superseded state. |
| `judgment` | Immutable execution result | Exact rule, input digest and artifact availability, evaluator, execution interval/state, raw result availability, qualification, cited evidence with locators, limitations, dependency manifest, attempt receipts, and proposed consequences. Completion and failure have disjoint conditional fields. |
| `assessment` | Immutable assessment result | Pinned matter, profile, purpose, optional relevant audience, knowledge boundary, input artifact, evidence selection/omissions/coverage, dependency manifest, judgment dependencies, assessed propositions, change causes, consequences/material changes/gaps, resource use, stop reason, completeness, proposals, and limitations. |
| `control` | Immutable accepted host effect | Kind of instruction or disposition, actor and authority, explicit target scope, control epoch, effective time and expiry/unknown reason, and schema-bound effect. |
| `receipt` | Append-only observed outcome | Explicit stage, operation identity, known recording time, namespaced outcome, evidence dependencies, and schema-bound details. |

The `control` record covers cancellation, instructions, corrections, permissions, scope/task changes, deferral, acknowledgement, rejection, preference, decisions, and protected separation. A source record mentioning one of these words remains ordinary evidence. Control records and inputs require `provenance.origin: "host"`; source and evaluator origins cannot validate as controls. Only the future host control interface can accept an effective control; the schema does not authenticate a serialized claim of host origin.

Assessment `evaluation_state` describes whether the recorded evaluation was complete. It is separate from the future current/superseded/invalidated projection. Changing projection validity must not mutate the immutable judgment or assessment result.

Evidence-relation kinds are `supports`, `contradicts`, `qualifies`, `reports_assertion`, `context_only`, and `unresolved`. Several records can target the same claim under different components or relationships. A schema-valid accepted relation does not establish claim truth. For accepted, rejected, or superseded relation decisions, the acceptance descriptor requires an authority receipt; authority applicability is a later check.

## Exact source bytes and normalized contract values

An observation's `content.digest` is SHA-256 of the exact original source bytes. Its content locator and availability state are separately required. An `available` content state requires a concrete whole-artifact or selected-span locator. Content currently unavailable may retain its prior concrete locator; the schema does not erase source history when access changes. Source bytes can use any source encoding, including bytes that would not be valid normalized Matter JSON. Normalized record/command digests use the versioned Matter canonical preimage described in [compatibility.md](compatibility.md). These digests have different purposes and must not be substituted for one another.

Locators explicitly distinguish a whole artifact, a selected span with a typed selector, and an unavailable source with a reason. The optional span-validation receipt preserves an adapter's claimed validation result. MAT-007 implements the actual locator-validation boundary; the core schema does not fetch a URI or confirm that a quoted passage exists.

`decimal_string` describes an exact decimal lexeme, with an optional minus sign and fractional digits, without exponent notation. Its use is declared by the containing schema. A separate `nonnegative_decimal_string` forbids a minus sign for resource cost ceilings, including a negative-zero spelling. Canonical encoding preserves the string exactly. It does not round, trim fractional zeros, or infer a probability, currency, unit, or importance score from an ordinary string.

## Explicit time values

Known time uses this shape:

```json
{
  "state": "known",
  "value": "2026-10-08T15:00:00.123Z",
  "precision": "millisecond"
}
```

The declared precision must match the exact number of fractional digits: `second` has none, `millisecond` has three, `microsecond` has six, and `nanosecond` has nine. The schema's conditional patterns enforce that correspondence. The `matter-utc-time` format validates Gregorian dates, years 0001 through 9999, uppercase `T` and `Z`, and seconds 00 through 59. This version does not admit numeric UTC offsets or leap-second timestamps. Another-language consumer must implement this custom calendar format check as well as the schema patterns.

Unknown time uses a different closed branch:

```json
{
  "state": "unknown",
  "reason": "not_reported"
}
```

Allowed reasons are `not_reported`, `not_observed`, `source_unavailable`, `conflicting_evidence`, and `not_applicable`; optional `detail` supplies context. Unknown time forbids `value` and `precision`. A timestamp must not be filled from ingestion time. A complete occurrence instant and occurrence interval are alternative fields on observations and occurrences; neither silently supplies the other.

Intervals contain `start`, `end`, and explicit boundary semantics. This ticket validates their shape and individual timestamps. Event-order interpretation, interval comparison, knowledge gating, completeness, and negative-watch invalidation are implemented by MAT-010 and later tickets.

## Domain values and optional extensions

An explicitly schema-bound domain value has two fields:

```json
{
  "schema": {
    "namespace": "example",
    "id": "claim-status",
    "version": "1.0",
    "digest": "0000000000000000000000000000000000000000000000000000000000000000"
  },
  "value": {
    "status": "unknown",
    "reason": "The required source is unavailable."
  }
}
```

The zero digest above is a synthetic illustration. A real producer supplies the exact external schema digest. The `value` is intentionally opaque to the common core and must still use the strict Matter JSON value domain. The producer's claimed schema identity does not establish domain validation or qualify its conclusion. MAT-012 and profile/adaptor implementations perform those checks before relying on a result.

A namespaced optional extension maps a key such as `example:display` to one of these domain values. Extension keys must include a namespace separator. Unknown but well-formed optional extensions are preserved on round trip. An extension cannot grant authority or introduce an implicit required semantic feature. Required extension negotiation and migrations remain MAT-074 work; the v1 envelope rejects undeclared fields such as `required_extensions`.

This typed container is the only intentionally open domain-value boundary. Core evidence, reference, authority, time, command, result, and failure objects remain closed. Provider-specific raw formats are outside these schemas.

## Judgment completion, unknown meaning, and failures

A completed judgment requires `evaluation_status` and `semantic_output`, and forbids `failure`. Applicable, not-applicable, insufficient-evidence, ambiguous, and conflicting are distinct evaluation states. An unknown proposition can be a completed evaluation with an explicit schema-bound unknown semantic result. It is not an infrastructure failure.

Failed, cancelled, timed-out, and budget-exhausted executions instead require a failure descriptor and forbid both `evaluation_status` and `semantic_output`. They cannot propose consequences or claim qualified execution. The failure reason must match the execution state. Completed independent judgments may be retained in their own records when another judgment fails.

A `qualified` result requires an exact certificate component reference. `not_required` requires a reason and excludes a certificate. The schema does not validate certificate applicability, model accuracy, rule semantics, current admission, or a provider's reported confidence. Those guarantees belong to MAT-012 and MAT-026 onward.

## Reconstructable inputs, citations, and explicit missing artifacts

Judgments require an `input_artifact`, a `raw_result`, and an `execution_interval` in addition to their normalized `input_digest`. The artifact reference identifies the exact original immutable bytes using `source_content`, including their original-byte digest, locator, media type, and current availability. That digest is distinct from the normalized-contract input digest. Evidence use records contain both a pinned `reference` and a `locator`, so a whole-artifact citation is distinguishable from a selected passage or an unavailable citation.

If an exact artifact was never recorded, never persisted, has become inaccessible, is withheld, or has expired under retention, the producer can instead declare:

```json
{
  "state": "unavailable",
  "reason": "not_persisted",
  "detail": "The original input bytes were not retained."
}
```

The allowed artifact reasons are `not_recorded`, `not_persisted`, `source_unavailable`, `withheld`, and `retention_expired`. This closed branch has no invented digest or locator. A known immutable content digest may still be retained through `source_content` when current access is unavailable. These represent different evidence states: known-byte identity with unavailable access, versus no verified artifact reference that the producer can supply.

`raw_result` additionally permits `state: "not_produced"` or `state: "not_applicable"`, each with an explicit reason. A failed attempt may have produced no provider response; a deterministic function may have no separate provider wire response. Neither state means an empty successful semantic conclusion. When a raw response exists it remains a separately referenced artifact, including when validation of that response failed. Schema admission cannot claim full historical replayability for an unavailable artifact.

Assessments require their exact `input_artifact` or unavailable reason, plus an `evidence_selection` containing `references`, `omitted`, and `coverage`. The same evidence-selection definition is used by the `assess` command. `resource_use` is an explicit schema-bound domain value. `consequences` and `evidence_gaps` are arrays of typed domain values, and `material_changes` contains objects with a declared `cause` and typed `value`. These arrays may be empty; their presence prevents the common shape from losing recorded absence, omission, or reported effects.

Every assessment supplies a `stop_reason`: `completed`, `incomplete`, `execution_failed`, `timed_out`, `evidence_satisfied`, `no_eligible_source`, `conflict_persists`, `budget_exhausted`, `cancelled`, `source_unavailable`, or `decision_required`. Limitations and evidence gaps supply the concrete unresolved context. These are reported reasons; this ticket does not run an investigator, authorize a decision request, reserve resources, or infer that sufficient evidence establishes every downstream conclusion.

## Operation commands

Every command requires `schema_version`, `operation`, `command_id`, `idempotency_key`, `scope_id`, `actor`, `authority`, `expected_revisions`, and a closed operation-specific `body`. Optional extensions follow the same explicit namespace contract. Actor references do not replace authority receipt references. Expected reads are pinned references and may include an immutable digest.

Creation operations embed typed `*_input` records. These preserve the source/proposition fields but omit the stored record's creation receipt and aggregate revision. The future host/store assigns the receipt and initial revision atomically. Supplying an input does not establish that a stored record was created.

| Operation | Required request content | Permitted successful result outcomes |
|---|---|---|
| `ingest_observation` | Proposed observation input. | `committed`, `duplicate` |
| `create_matter` | Proposed matter input and identity policy. | `created`, `existing` |
| `propose_association` | Subject, candidate set, matching rule, evidence, and knowledge boundary. | `proposal`, `no_match`, `ambiguous`, `insufficient_evidence` |
| `accept_association` | Pinned proposal/candidates and acceptance policy. | `accepted` |
| `append_claim` | Proposed claim input. | `appended`, `duplicate` |
| `relate_evidence` | Proposed evidence-relation input. | `appended`, `duplicate` |
| `link_matters` | Pinned matters, relationship kind/schema, and basis. | `linked` |
| `merge_matters` | Survivor, losing matter revisions, equivalence basis, and merge policy. | `committed` |
| `correct_merge` | Merge receipt, undo/split intent, partitions, and basis. | `committed` |
| `record_control` | Proposed accepted host-effect input. | `applied`, `duplicate` |
| `commit_assessment` | Proposed assessment input and its dependency manifest. | `committed` |
| `invalidate_dependents` | Nonempty changed positive references or negative scopes and change cause. | `affected`, `no_op` |
| `request_transition` | Matter/lifecycle revision, profile edge, evidence, assessment, and effective time. | `applied`, `already_applied`, `held_for_evidence`, `held_for_conflict` |
| `prepare_delivery` | Assessment, audience/purpose, baseline, epoch, treatment, content/dependency digests, and stable delivery key. | `ready`, `withheld` |
| `dispatch` | Intent, lease token, epoch, delivery key, audience, and baseline. | `delivered`, `withheld` |
| `assess` | Matter, profile/purpose, explicit evidence selection or query, knowledge boundary, resource budget, and control epoch. | `assessed`, `incomplete` |

These are 16 command variants and 31 successful operation/outcome pairs. The `assess` operation comes from the rule contract in addition to the core operation table. `no_match` preserves the considered candidate set, requires an empty `selected` array, and declares adequate coverage. A nonempty considered set can yield no match when every candidate is rejected; the fixture preserves that history. `ambiguous` returns multiple candidates. Insufficient evidence remains explicit. Association subjects, candidates, selected references, and accepted membership all use the same typed observation/occurrence/matter dependency union. A claim, control, judgment, or receipt cannot become an association member. Candidate existence, completeness, independence, allowed transitions, and actual query results are later runtime checks.

## Operation results and error codes

All results require `schema_version`, `operation`, `operation_id`, and `status`. The two branches are disjoint:

- A success requires its operation-specific `outcome`, a typed receipt reference, and a closed result `body`. It cannot contain an error object.
- A failure requires only a typed `error` in addition to the common fields. It cannot contain a success outcome, a result body, or a successful receipt. Its inner and outer operation IDs must agree.

A held domain transition can be a successfully evaluated request whose evidence does not permit a state change. Storage, authorization, stale dependencies, and uncertain transport are separate explicit errors. Refusal labels such as stale, forbidden, invalid evidence, and identity conflict from the governing prose are represented by the applicable semantic failure code, never converted into successful `no_match` results.

Every error requires `code`, `operation_id`, a real boolean `retriable`, caller-readable `affected_references`, and safe `detail`. A schema cannot determine whether a caller may read a reference. The host must filter references and text before constructing a public result. Transport mapping must preserve the code.

| Code | Required distinction |
|---|---|
| `E_SCHEMA_INVALID` | The value violates the declared structural/value contract. |
| `E_VERSION_UNSUPPORTED` | The declared contract version is unsupported. |
| `E_SCOPE_FORBIDDEN` | Access or operation scope is forbidden. |
| `E_NOT_FOUND` | A requested readable object was not found. |
| `E_IDEMPOTENCY_CONFLICT` | A command key was reused with different content. |
| `E_SOURCE_IDENTITY_CONFLICT` | A source identity was reused incompatibly. |
| `E_REVISION_CONFLICT` | An expected revision no longer matches. |
| `E_ASSOCIATION_CONFLICT` | Association conflicts require explicit resolution. |
| `E_MERGE_CONFLICT` | A guarded merge cannot be accepted. |
| `E_EVIDENCE_INVALID` | Declared evidence is invalid. |
| `E_EVIDENCE_UNAVAILABLE` | Required evidence is unavailable. |
| `E_DEPENDENCY_STALE` | An assessment or operation used stale dependencies. |
| `E_POLICY_INVALID` | Policy references or configuration are invalid. |
| `E_RULE_CONFLICT` | Applicable rule conclusions conflict. |
| `E_AUTHORITY_REQUIRED` | Applicable authority is missing. |
| `E_BUDGET_EXHAUSTED` | The permitted resource budget was exhausted. |
| `E_CANCELLED` | The operation was cancelled. |
| `E_STORAGE_UNAVAILABLE` | No durable storage outcome was established. |
| `E_DELIVERY_UNKNOWN` | The actual transport outcome is unknown. |

A delivered result names the observed transport milestone; it does not assert consumption, action, or usefulness. An uncertain send remains `E_DELIVERY_UNKNOWN` and cannot produce the successful `delivered` branch.

## Fixtures, verification, and remaining boundaries

The [fixture manifest](../../tests/fixtures/contracts/manifest.json) declares the validity of standalone record, command, result, and intentionally invalid examples. The [inventory](../../tests/fixtures/contracts/inventory.json) lists the supported kinds, operations, outcome pairs, and error codes. All examples are synthetic. Their zero-valued digest placeholders establish shape only and are not evidence that source bytes or referenced schemas exist.

The examples cover every record kind, every command, every permitted success pair, every semantic error code, and additional unknown-time, failed/unknown/qualified judgment cases. Invalid examples include storage failure disguised as `no_match`, embedded execution failure in a semantic success, empty scope, unknown time with an invented value, failed judgment with a conclusion, absent qualification certificate, unsafe revision, missing dependency pin, malformed source digest, undeclared command fields, incompatible availability/locator declarations, ineligible association members, newline-suffixed digests or scope identifiers, missing reproducibility fields, fabricated digests for unproduced outputs, missing evidence locators, and negative resource ceilings.

Structural validation does not implement persistence, idempotent execution, reference existence or access, same-scope authorization, duplicate-event counting, source locator verification, merges, trusted control routing, dependency freshness, rule evaluation, profile compatibility, transition authority, timers, or external delivery. Those behaviors remain owned by their dependent tickets. Canonical wire validation also remains necessary before schema validation: JSON Schema alone cannot detect duplicate keys already lost by a decoder or distinguish the numeric token `1.0` from the integer `1`.
