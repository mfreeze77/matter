# Matter v1 schema inventory

MAT-002 turns the common record and operation shapes into executable Draft 2020-12 contracts. These are structural contracts. A valid document does not prove that its references exist, its authority is applicable, its evidence is true, its reads are current, or its state was durably committed.

The three canonical resources are:

| Family | File | Canonical `$id` |
|---|---|---|
| Stored record | [core-record.schema.json](../../schemas/core-record.schema.json) | `https://github.com/mfreeze77/matter/schemas/core-record.schema.json` |
| Proposed command | [operation-command.schema.json](../../schemas/operation-command.schema.json) | `https://github.com/mfreeze77/matter/schemas/operation-command.schema.json` |
| Operation result | [operation-result.schema.json](../../schemas/operation-result.schema.json) | `https://github.com/mfreeze77/matter/schemas/operation-result.schema.json` |

Every family requires the exact `schema_version: "1.0"`. The URLs identify schemas; validation registers all three local resources and does not fetch those URLs. The core schema contains shared `$defs`. Commands and results reference those definitions instead of maintaining alternative copies. The supported value domain, encoding, and compatibility decisions are documented in [compatibility.md](compatibility.md).

Implementation-specific resources also ship with the package:
[storage receipt details](../../schemas/storage-receipt-details.schema.json)
and the [observation source-index value](../../schemas/observation-source-index.schema.json).
They bind receipt details and internal projection values to exact schema digests;
they do not introduce additional core record kinds or wire operations.

MAT-007 also packages the [claim lookup and correction index](../../schemas/claim-index.schema.json),
[locator-validation declaration](../../schemas/locator-validation.schema.json),
[exact text-line selector](../../schemas/text-line-selector.schema.json), and
[evidence-relation index](../../schemas/evidence-relation-index.schema.json).
These adapter and projection schemas are separate from the three portable
envelopes. Their exact descriptors bind the runtime's validation declarations
and index values; an arbitrary `domain_value` admitted by the core is not
automatically valid under one of these specialized contracts.

MAT-008 adds the [candidate-set snapshot](../../schemas/candidate-set.schema.json),
[association evaluation](../../schemas/association-evaluation.schema.json),
[association decision](../../schemas/association-decision.schema.json),
[persistent disposition](../../schemas/association-disposition.schema.json), and
[membership lookup](../../schemas/association-membership.schema.json) contracts.
These five schemas bind host-published catalogs, immutable evaluation/decision
receipt details and current association projections.

MAT-009 adds the [typed-link index](../../schemas/matter-link-index.schema.json),
[complete identity-group mirror](../../schemas/identity-group.schema.json),
[immutable identity decision](../../schemas/identity-decision.schema.json),
[protected separation history](../../schemas/identity-separation.schema.json),
[explicit separation release](../../schemas/identity-release.schema.json), and
[registered identity validity](../../schemas/identity-dependency.schema.json).
These new resources preserve original evidence and exact historical partitions;
they do not supply semantic equivalence proof or a transitive assessment engine.

MAT-010 adds the [typed observation predicate](../../schemas/observation-predicate.schema.json),
[source catalog and admission revisions](../../schemas/source-catalog.schema.json),
[frozen coverage snapshot](../../schemas/coverage-snapshot.schema.json), and
[negative-dependency registration](../../schemas/negative-dependency.schema.json).
At MAT-010 the package reached **31 JSON Schema resources**: three portable families,
twenty-five runtime-specific resources and three repository-tooling schemas.
These four resources bind exact source/query/time scopes and historical
catalog populations; structural validation alone cannot establish completeness.

MAT-012 adds [immutable rule definitions](../../schemas/rule-definition.schema.json),
[bounded evaluation input](../../schemas/rule-evaluation-input.schema.json),
[typed evaluator responses](../../schemas/rule-evaluator-response.schema.json), and
[evaluation receipt details](../../schemas/rule-evaluation-receipt.schema.json).
They reuse the existing judgment and receipt creation inputs; no core record
kind, command, or result variant is added. Domain schemas use separate exact,
self-contained resource resolution as described in the [rule API](../rules.md).
Together with MAT-011's five [control resources](#trusted-control-runtime-schemas),
the current package contains **40 JSON Schema resources**: three portable
families, thirty-four runtime-specific resources, and three repository-tooling
schemas. The portable inventory remains twelve record kinds, twenty-four
command variants, and forty-five successful operation/outcome pairs.

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
| `claim` | Immutable proposition version | Referenced or schema-bound subject, namespaced predicate, typed value and qualifiers, temporal applicability, attributed evidence dependencies, and proposition version. Optional namespaced components identify scoped parts of this exact proposition. |
| `evidence_relation` | Mutable aggregate; revision required | Pinned claim and evidence, one declared relation kind, whole-proposition or component target, exact/whole/unavailable locator, temporal applicability, and explicit acceptance state and rationale. Optional quotation preserves exact source wording; optional locator-validation receipt pins the adapter's recorded check. |
| `association_proposal` | Immutable proposal | Pinned subject and candidates, selection outcome, selected references, matching rule, evidence, evaluator receipt, schema-bound uncertainty, and qualification state. Optional candidate-set, coverage, assessment time and evaluation-receipt fields bind the MAT-008 decision. |
| `accepted_association` | Mutable aggregate; revision required | Pinned proposal, observation/occurrence/matter membership, exact relationship definition, active/revoked/superseded state, and authority receipt. Optional candidate-set, policy, decision-receipt and capability fields record MAT-008 acceptance. |
| `matter_relation` | Mutable aggregate; revision required | Two pinned matters, namespaced relationship kind, relationship schema, evidence basis, authority receipt, and active/revoked/superseded state. |
| `judgment` | Immutable execution result | Exact rule, input digest and artifact availability, evaluator, execution interval/state, raw result availability, qualification, cited evidence with locators, limitations, dependency manifest, attempt receipts, and proposed consequences. Completion and failure have disjoint conditional fields. |
| `assessment` | Immutable assessment result | Pinned matter, profile, purpose, optional relevant audience, knowledge boundary, input artifact, evidence selection/omissions/coverage, dependency manifest, judgment dependencies, assessed propositions, change causes, consequences/material changes/gaps, resource use, stop reason, completeness, proposals, and limitations. |
| `control` | Immutable accepted host effect | Kind of instruction or disposition, actor and authority, explicit target scope, control epoch, effective time and expiry/unknown reason, and schema-bound effect. |
| `receipt` | Append-only observed outcome | Explicit stage, operation identity, known recording time, namespaced outcome, evidence dependencies, and schema-bound details. |

The `control` record covers cancellation, instructions, corrections, permissions, scope/task changes, deferral, acknowledgement, rejection, preference, decisions, and protected separation. A source record mentioning one of these words remains ordinary evidence. Control records and inputs require `provenance.origin: "host"`; source and evaluator origins cannot validate as controls. The MAT-011 host control interface accepts effective controls under its explicit policy; the schema does not authenticate a serialized claim of host origin.

Assessment `evaluation_state` describes whether the recorded evaluation was complete. It is separate from the future current/superseded/invalidated projection. Changing projection validity must not mutate the immutable judgment or assessment result.

Evidence-relation kinds are `supports`, `contradicts`, `qualifies`, `reports_assertion`, `context_only`, and `unresolved`. Several records can target the same claim under different components or relationships. A schema-valid accepted relation does not establish claim truth. For accepted, rejected, or superseded relation decisions, the acceptance descriptor requires an authority receipt; authority applicability is a later check.

MAT-007 adds optional `claim.body.components`, a nonempty object whose keys use `namespaced_name` and whose values use `domain_value`. The immutable proposition declares these component names. A relation's existing `{kind: "component", component: "example:name"}` target must name a component on its exact claim at runtime; structural validation alone cannot resolve that reference. Support for one component does not imply support for another or the whole proposition. A claim without components remains valid and may receive whole-proposition relations.

Claim corrections reuse `supersedes` and append a new immutable claim. The MAT-007 handler requires distinct pinned claim predecessors with the same subject and predicate, a new ID, and a changed proposition-version label relative to every predecessor. Branches remain explicit; queries preserve branching heads rather than choose a single latest truth. The generic supersession schema stays unchanged because other record kinds have their own correction policies. Neither source wording nor earlier claim and citation records are overwritten.

Evidence relations permit optional `quotation`, using nonempty exact text, and `locator_validation`, using an immutable `receipt_dependency`. The latter is separate from the earlier selected-span locator's optional bare `validation_receipt`; it can bind an adapter check for any locator kind, including an explicit whole artifact or an unavailable citation. A receipt reference is not proof of validation or authority. The MAT-007 handler assigns the relation-level receipt, verifies its binding, and refuses caller-supplied computed pins. The generic relation input schema remains compatible with the shared record body and does not implement that runtime restriction.

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

Intervals contain `start`, `end`, and explicit boundary semantics. The structural contracts validate their shape and individual timestamps. MAT-010 supplies exact interval comparison, separate knowledge/effective selection, explicit source coverage and direct negative-watch invalidation. Domain calendars, event authority and transitive assessment invalidation remain separate work; see [time and coverage](../time-coverage.md).

MAT-010 adds optional `negative_watch.assessed_as_of` to retain a known original
knowledge boundary. The runtime requires it on registrations, while earlier
structural manifests without it remain valid. `coverage_specification` binds
a domain query, nonempty eligible source set and observed interval. The
`coverage_member_input` and `coverage_source_baseline` fragments require exact
host projection/observation pins and explicit ownership/history declarations.
New `coverage_change` and `negative_scope_arrival` causes distinguish these
local dependency notices. Committed observation results may include `changes`;
duplicate deliveries do not. Both new operations require nonempty result
`changes` and the exact published coverage or registration pin.

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

Creation operations embed typed `*_input` records. These preserve the source/proposition fields but omit the stored record's creation receipt and aggregate revision. The host/store assigns the receipt and initial revision atomically. Supplying an input does not establish that a stored record was created.

| Operation | Required request content | Permitted successful result outcomes |
|---|---|---|
| `ingest_observation` | Proposed observation input. | `committed`, `duplicate` |
| `create_matter` | Proposed matter input and identity policy. | `created`, `existing` |
| `update_matter_metadata` | Pinned matter and complete replacement of optional title, description, and namespaced extensions. | `updated`, `unchanged` |
| `commit_occurrence_grouping` | Batch occurrence creations, pinned membership replacements, explicit root provenance assignments, grouping policy, and schema-bound basis. | `committed`, `unchanged` |
| `publish_association_candidates` | Query, complete declared catalog entries, coverage, evidence, as-of time, and previous set pin or explicit null. | `published`, `unchanged` |
| `publish_coverage` | Exact source/query/interval specification, catalog and collection coverage, known cut, mode, protected derivative members, optional one-time source baselines, prior pin, adapter and policy. | `published` |
| `register_negative_watch` | Stable watch ID, exact host derivative and coverage pins, original knowledge cut, expiry or next-check, previous registration pin and policy. | `registered` |
| `propose_association` | Subject, considered candidates, matching rule, evidence and knowledge boundary; optional candidate-set pin and external evaluation declaration. | `proposal`, `no_match`, `ambiguous`, `insufficient_evidence`, `evaluation_failed` |
| `accept_association` | Pinned proposal/candidates and acceptance policy; optional candidate set, relationship and capability. | `accepted` |
| `decide_association` | Pinned pair, relationship/capability, reject/protect/release decision, previous disposition or null, reason, as-of time and policy. | `applied`, `unchanged` |
| `append_claim` | Proposed claim input. | `appended`, `duplicate` |
| `relate_evidence` | Proposed evidence-relation input; optional schema-bound frozen adapter validation declaration. | `appended`, `duplicate` |
| `revise_evidence_acceptance` | Pinned evidence relation and a complete replacement acceptance descriptor. | `updated`, `unchanged` |
| `link_matters` | Pinned matters, relationship kind/schema, and basis. | `linked` |
| `merge_matters` | Survivor, losing matter revisions, equivalence basis, and merge policy. | `committed` |
| `correct_merge` | Merge receipt, undo/split intent, explicit original identity partitions and retained children, basis and optional as-of time. | `committed` |
| `release_identity_separations` | Exact current protected separation pins, basis, explicit reason, merge policy and optional as-of time. | `released` |
| `record_control` | Proposed accepted host-effect input. | `applied`, `duplicate` |
| `commit_assessment` | Proposed assessment input and its dependency manifest. | `committed` |
| `invalidate_dependents` | Nonempty changed positive references or negative scopes and change cause. | `affected`, `no_op` |
| `request_transition` | Matter/lifecycle revision, profile edge, evidence, assessment, and effective time. | `applied`, `already_applied`, `held_for_evidence`, `held_for_conflict` |
| `prepare_delivery` | Assessment, audience/purpose, baseline, epoch, treatment, content/dependency digests, and stable delivery key. | `ready`, `withheld` |
| `dispatch` | Intent, lease token, epoch, delivery key, audience, and baseline. | `delivered`, `withheld` |
| `assess` | Matter, profile/purpose, explicit evidence selection or query, knowledge boundary, resource budget, and control epoch. | `assessed`, `incomplete` |

These are 24 command variants and 45 successful operation/outcome pairs. MAT-010 adds coverage publication and negative-watch registration; MAT-009 adds the explicit separation-release operation. MAT-005 adds the bounded `update_matter_metadata` operation, MAT-006 adds `commit_occurrence_grouping`, MAT-007 adds `revise_evidence_acceptance`, and MAT-008 adds `publish_association_candidates` and `decide_association` to the initial 16-operation inventory. MAT-008 also adds the explicit `evaluation_failed` proposal outcome. The `assess` operation comes from the rule contract in addition to the core operation table. `no_match` preserves the considered candidate set, requires an empty `selected` array, and declares adequate coverage. A nonempty considered set can yield no match when every candidate is rejected; the fixture preserves that history. `ambiguous` returns multiple candidates. Insufficient evidence remains explicit. Association subjects, candidates, selected references, and accepted membership all use the same typed observation/occurrence/matter dependency union. A claim, control, judgment, or receipt cannot become an association member. MAT-008 verifies candidate existence and currentness within the declared catalog and preserves its coverage. External discovery, actual source completeness, independent-source qualification and allowed domain transitions remain separate responsibilities.

For `ingest_observation`, both successful bodies require a pinned `observation` and permit an optional `observation_receipt`, a typed bare receipt reference to that observation's original creation receipt. The MAT-004 handler supplies both fields. The top-level `receipt` always identifies the current command's operation receipt: it matches the observation receipt for a new commit and differs for a duplicate submitted under a new command. Structural validation checks the reference type, not that either receipt exists or that their relationship is correct. Existing v1 results without the optional field remain valid; [compatibility.md](compatibility.md) describes the reader-update requirement.

`update_matter_metadata` requires exactly `body.matter` and `body.metadata`. The matter reference must carry a revision or immutable snapshot digest. The metadata object permits only optional `title`, `description`, and `extensions`, using the shared text and namespaced-extension contracts. It is a complete replacement of those three optional record fields: omission removes a field, and `{}` clears all three. It is not a partial patch. Null does not mean removal and is rejected. The operation preserves scoped identity, identity keys, domain kind, provenance, creation receipt, lifecycle, and supersession fields. The command journal records the edit actor and operation receipt; no replacement provenance is accepted.

Metadata results contain only the pinned `matter` in their body and the current command's top-level `receipt`. `updated` identifies a new matter revision; `unchanged` retains the current revision when the requested metadata already matches. A stale revision is a failure rather than a successful no-op. These cross-record and no-op behaviors belong to the MAT-005 handler; schemas validate the allowed shapes and do not execute an update.

`commit_occurrence_grouping` requires exactly `creates`, `replacements`, `provenance_assignments`, `grouping_policy`, and `basis` in its body. At least one of the first three arrays must be nonempty. Creates use `occurrence_input` with an empty `body.provenance_groups` placeholder; the handler computes stored group membership rather than admitting caller-supplied counts or computed groups. Each replacement contains only a pinned `occurrence` and its complete `observations` list. An empty membership list is valid and preserves the historical occurrence record. Other occurrence fields cannot be changed through a replacement.

The shared `$defs.occurrence_grouping_assignment` contains a pinned immutable `observation`, a `status`, and either `group` or `reason`. A `declared` status requires one adapter-owned `identity_key` group and forbids a reason; an `unknown` status requires a nonempty reason and forbids a group. These are dependence declarations, not certificates of independent corroboration. The host supplies authenticated authority and truthful source classification; the handler checks root eligibility, parent lineage, scope, and current dependencies. Structurally valid references or group labels alone establish none of those guarantees.

Grouping success bodies require `occurrences`, `previous`, and `provenance_assignments` arrays. `occurrences` names affected current occurrence snapshots; `previous` names only occurrence snapshots that were actually revised. An `unchanged` result therefore requires an empty `previous` array. Assignment results are pinned `matter:projection` references restricted to the `matter.provenance_groups` namespace, covering new, changed, or unchanged assignments involved in the operation. The top-level receipt identifies the current command. A command can change assignments without directly naming an occurrence creation or replacement; the runtime must find and revision all affected grouping projections atomically. This is a bounded grouping operation, not execution of semantic association proposals or transitive assessment invalidation.

`append_claim` retains its required claim input. `relate_evidence` retains its required relation input and permits `body.validation`, a `domain_value` containing the frozen adapter declaration prepared outside the storage transaction. These declarations are not executed by the structural validator. The runtime checks their exact evidence, artifact, locator, quotation, adapter, dependency, and result bindings before accepting a citation. A successful validation receipt and relation commit atomically. An invalid or unavailable citation remains an explicit failure; the failed command journal preserves its frozen declaration, but the failed transaction does not commit a new validation-receipt record. Whole-artifact validation never substitutes for an invalid exact passage.

Both successful `append_claim` and `relate_evidence` bodies permit `changes`. If supplied, an `appended` result requires a nonempty array and a `duplicate` result requires an empty array. Relation results additionally permit a pinned `locator_validation` receipt. The MAT-007 handlers always supply these fields. The top-level receipt still identifies the current command, while a duplicate relation preserves its original validation receipt. Duplicates are exact canonical input matches for the same scoped ID, excluding storage-assigned and computed receipt fields; matching wording under another ID is not a duplicate.

`revise_evidence_acceptance` requires exactly `relation` and `acceptance` in the body. The relation reference carries its current revision or snapshot digest; the shared acceptance object completely replaces only acceptance state, rationale, authority, and any evaluator reference. It cannot rewrite claim, evidence, relation kind, target, locator, quotation, validation receipt, applicability, original provenance, extensions, or creation receipt. `updated` requires current `relation`, `previous`, and nonempty `changes`; `unchanged` requires current `relation` and empty `changes`, with no `previous` field. Each has its own command receipt. Scope, authorization, exact receipt bindings, and current revisions remain runtime checks.

The shared `$defs.dependency_change` is a closed object containing `cause`, `before`, and `after`. Both reference arrays contain exact pinned snapshots, and at least one array must be nonempty. It reuses the existing change-cause vocabulary. MAT-007 emits `new_evidence` for a newly recorded claim or relation, `evidence_correction` for explicit claim supersession, and `disposition_change` for an acceptance revision. These are changes to typed model records; they do not assert a newly observed external event, independent corroboration, or claim truth. Previous references remain readable history. Notices do not themselves invalidate assessments, traverse dependent graphs, or cancel delivery; those effects belong to MAT-016.

## Bounded association publication and decisions

`publish_association_candidates` completely publishes the declared query's
catalog. Its query binds a source component, bare scoped subject, candidate
type, exact-key or semantic mode, matching-rule component, typed selector, and
query keys. Exact-key mode requires at least one key; semantic mode omits keys
or supplies an empty key list. Each entry contains a candidate pin, catalog keys and basis
pins. `previous` is explicit null for creation or the exact current projection
pin for replacement. The stored private snapshot also binds the current
subject, host policy and authority. Both success outcomes return `candidate_set`.

The existing proposal command retains its portable required fields and gains
optional `candidate_set` and `evaluation` fields. The MAT-008 handler requires
the candidate-set pin and verifies the full considered matching list against
it. The exact matcher uses any equal namespace/value key in the declared
catalog; it does not rewrite continuing matter identity keys. An external
semantic declaration contains producer, outcome, selected pins, uncertainty,
qualification, reason and missing-evidence descriptions. It is preserved in a
service-generated evaluation receipt, without running or qualifying a provider.
Every runtime proposal result identifies the immutable `proposal` and its
`candidate_set`, including no-match, ambiguous, insufficient and failed
outcomes. Existing result fields and outcome distinctions remain intact.

Acceptance retains required proposal, candidate list and policy fields. The
runtime additionally requires `candidate_set`, `relation`, and `capability`.
The candidate list includes all considered candidates, not just the selected
one. The handler requires a single matched selection, a current catalog and
member pins, the configured host authority, and no blocking pair disposition.
Both revision and immutable snapshot digest pins are supported for mutable
records. `attach` and `relate` preserve identity; the serialized `merge`
capability is representable but always refused by this bounded host policy.
Accepted runtime records retain their candidate-set, acceptance-policy,
authority decision and capability. Confidence and claimed qualification never
supply acceptance permission.

`decide_association` records `reject`, `protect`, or explicit `release` for a
scoped pair and capability. Stable protection keys retain the relationship's
namespace and ID across version changes; merge protection is symmetric, while
attachment and relatedness are ordered. The complete disposition and decision
receipt commit atomically with any revocation of an active association.
Release requires correction authority and the current prior disposition;
it does not itself reactivate an attachment. The result contains `disposition`,
`decision`, affected `associations`, and `changes`. The schema permits `applied`
with nonempty changes and `unchanged` with no changes. Current runtime decisions
append an explicit decision; exact command retry returns its saved result.
A later new acceptance may reactivate a released pair while retaining history.

New proposal/accepted-record fields remain optional in portable v1 schemas so
older fixtures remain structurally readable. The runtime requires and verifies
its own receipt/index bindings; structural admission alone does not make a
legacy record executable. Generic controls, control epochs, equivalence merges,
provider qualification and transitive assessment invalidation are not supplied
by this association handler. See the [association API](../associations.md).

## Identity merge, correction and release fields

`correct_merge.partitions[].identity_members` is an additive array of exact
matter dependencies; it is separate from child `members`. Runtime partitions
must cover every original identity once, preserve each child in all of its
original owners' partitions, and contain their representative. Merge/correction
accept an optional known `as_of` and emit exact `identity_views` projection pins
plus nonempty dependency `changes`. Older success fixtures without these
optional fields remain readable. The runtime always provides them.

`release_identity_separations` requires current projection dependencies in
`separations`, a nonempty `basis`, explicit `reason` and `merge_policy`; optional
`as_of` uses the same known UTC contract. Its `released` result requires exact
new separation pins, an immutable `release_receipt` and nonempty changes.
Release does not change identity groups or imply merge acceptance.

Private separation values distinguish protected/released status, name the exact
`previous` projection or initial null, and retain their immutable decision.
Re-protection after an authorized release advances that same projection again.
The identity and release proof schemas preserve full policy admission, authority,
before/after partitions or barriers, child routing and changes. Shape alone
proves neither currentness nor that the declared receipt actually committed
those snapshots; the runtime verifies those bindings. See the
[identity API](../identity-corrections.md).

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

The [fixture manifest](../../tests/fixtures/contracts/manifest.json) declares the validity of standalone record, command, result, and intentionally invalid examples. The [inventory](../../tests/fixtures/contracts/inventory.json) lists the supported kinds, operations, outcome pairs, and error codes. The current manifest contains **203 fixtures: 145 valid and 58 intentionally invalid**. All examples are synthetic. Their zero-valued digest placeholders establish shape only and are not evidence that source bytes or referenced schemas exist.

The examples cover every record kind, every command, every permitted success pair, every semantic error code, and additional unknown-time, failed/unknown/qualified judgment cases. Invalid examples include storage failure disguised as `no_match`, embedded execution failure in a semantic success, empty scope, unknown time with an invented value, failed judgment with a conclusion, absent qualification certificate, unsafe revision, missing dependency pin, malformed source digest, undeclared command fields, incompatible availability/locator declarations, ineligible association members, newline-suffixed digests or scope identifiers, missing reproducibility fields, fabricated digests for unproduced outputs, missing evidence locators, and negative resource ceilings.

Structural validation does not implement persistence, idempotent execution, reference existence or access, same-scope authorization, duplicate-event counting, source locator verification, merges, trusted control routing, dependency freshness, rule evaluation, profile compatibility, transition authority, timers, or external delivery. Those behaviors remain owned by their dependent tickets. Canonical wire validation also remains necessary before schema validation: JSON Schema alone cannot detect duplicate keys already lost by a decoder or distinguish the numeric token `1.0` from the integer `1`.

## Trusted control runtime schemas

MAT-011 reuses the existing `record_control` command/result pairs and immutable
`control` kind. It adds five packaged private schemas, without changing the
twenty-four command variants, forty-five success pairs, core wire version,
canonical encoding or SQLite migration:

- [control-effect](../../schemas/control-effect.schema.json): registered action, reason, capabilities and optional inert typed payload.
- [control-sequence](../../schemas/control-sequence.schema.json): scope and audit ordering counter.
- [control-fence](../../schemas/control-fence.schema.json): exact target, epoch and retained governing restrictions/dispositions, including overlapping original scopes.
- [control-token](../../schemas/control-token.schema.json): static policy/authority binding, actual work context, root/target pins with explicit absence, governing and active controls, and capture time.
- [control-hook](../../schemas/control-hook.schema.json): accepted control, hook/attempt identity, started/succeeded/failed state and safe exception type.

The `matter:control-token` command extension uses the exact packaged token schema
descriptor. Generic structural readers preserve it as data. The guarded runtime
requires and checks it, includes existing pins in the read set, and never treats
a supplied token as authentication. Old v1 control fixtures remain structurally
valid; their arbitrary effect descriptor does not make them executable controls.
See [trusted controls](../controls.md) for scope conjunction, explicit releases,
current-time enforcement, exact replay and the future dispatch binding seam.
