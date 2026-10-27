# Versioned semantic questions

MAT-027 adds immutable question specifications, an exact registry, deterministic
field rendering and semantic change reports. It extends the
[typed executor](semantic-executor.md) under the governing
[semantic contract](jev.md#questions-and-rendering). It neither calls a provider
nor qualifies a question. Packet eligibility remains the host's responsibility;
MAT-028 adds source-linked preparation, and MAT-030 adds durable execution
receipts. The renderer returns canonical materialized data for a host to retain;
it does not silently write to storage.

## Specification and registry

`QuestionSpecification(value)` accepts exactly these fields:

- `schema_version: "1.0"`, `namespace`, opaque `id`, semantic `family` and
  `revision`.
- `primitive`, complete `instructions`, and static ordered `criteria` using the
  existing Choice, Score or proposition-probability shape.
- Ordered `required_fields`, each containing `name`, `path` and `description`.
  Names are lowercase identifier tokens; paths are arrays of exact dictionary
  keys and nonnegative array indices. An empty path names the complete packet.
- `renderer: {"id": "canonical-json-bindings", "version": "1.0"}`.

Instructions reference every declared binding with a literal `{{name}}` marker.
Undeclared, unused and malformed bindings fail specification validation. There
is no attribute traversal, expression evaluation, wildcard lookup, arbitrary
formatter, dynamic criterion construction or source-text template evaluation.

`QuestionRegistry([specification, ...])` retains one canonical definition per
family/revision and per namespace/ID/revision. Conflicting or duplicate entries
are refused. The registry itself is immutable. `registry.resolve(spec.reference)`
requires an exact existing component reference: namespace, ID, explicit version
and semantic digest. An unknown version/digest cannot resolve to a newer or
latest definition. Historical versions can coexist and remain resolvable.

Specifications are limited to 256 KiB, registries to 256 entries, and field
bindings to 128 entries and 32 segments per path. Values use the existing
canonical encoding. All public `.value`, `.reference` and resolved values are
detached copies; `.canonical` retains exact canonical bytes internally.

## Distinct identities

The specification's `.semantic_digest` binds family, revision, complete wording,
primitive, ordered criteria, required field names/paths/descriptions/order and
renderer ID/version. Opaque catalogue namespace/ID are excluded. Renaming an
opaque ID does not change what the evaluator is asked. The full specification
`.digest` and exact registry reference still distinguish its catalogue identity.

Changing an option description, rubric position, field path or renderer changes
the semantic digest even if the primitive's output shape remains the same.
Criteria arrays keep their presentation order through serialization and hashing.
Revision strings are part of declared semantic identity; a new revision does not
automatically inherit qualification from an older one.

## Rendering and manifests

`render_question(spec, state, correlation_id, bound_ids=(), source_manifest=None,
max_render_bytes=65536)` first freezes the canonical state and resolves every
required path. Missing bindings, incompatible containers, nulls and empty
strings/arrays/objects fail with `E_EVIDENCE_UNAVAILABLE`; required `false` and
zero values remain valid. A `QuestionError.path` such as
`("render", "required_fields", 1, "path")` identifies the declaration to inspect
without echoing private caller keys, names or source content.

The supported renderer replaces a marker with an explicit path, for example
`packet["sources"][0]["text"]`, and appends one canonical JSON list containing
the bound paths, descriptions and values. Text resembling another marker inside
a source value stays quoted data. It is not interpolated a second time. This
preserves evidence as evidence; it is not a claim that formatting alone prevents
a model from following malicious source instructions.

The returned `RenderedQuestion` exposes:

- `.question`: the exact immutable MAT-026 `Question`, including correlation ID,
  static criteria, specification semantic digest and exact packet digest.
- `.manifest`: exact specification reference, renderer, correlation ID, criteria
  digest, ordered binding paths/value digests, included/excluded source
  declarations, truncation declaration and missing-prerequisite list.
- `.semantic_digest`: the specification's meaning identity.
- `.rendered_digest`: the primitive, exact model-visible instructions and static
  ordered criteria, excluding the opaque correlation ID.
- `.input_digest`: semantic identity, full packet digest, bound subject IDs and
  rendered digest. Source/state changes alter this identity without rewriting
  the specification's meaning.

The packet digest is exactly
`canonical_digest(state, "matter.semantic.packet.v1")`, so the resulting Question
can be inserted into a MAT-026 Batch carrying that same frozen state. Source
availability, access, admissibility, candidate coverage and independence are
not inferred from this digest or renderer.

`source_manifest`, when supplied, contains `included` and `excluded` descriptor
arrays plus an explicit nonempty `truncation` object. Every excluded descriptor
requires a reason. This is a host declaration for audit, not verified source
authority. Selection audit data is kept in the manifest and is never appended
to model-visible instructions. Hosts must also keep excluded content out of the
selected `state` they send to an executor. Without a source manifest, truncation
has an explicit `not_supplied` status rather than claiming complete coverage.

The renderer does not truncate. Exceeding the output budget fails explicitly.
Only installed renderer ID/version pairs can render; an unknown renderer cannot
fall back to a familiar version. Both question and manifest are retained in the
result's canonical bytes. Durable persistence is the consuming host's operation.

## Initial definitions and lint

`association_specification()` creates an original unqualified initial definition
with exactly `same_matter`, `related`, `different`, and `insufficient` outcomes
in that order. Candidate IDs stay in bound data, not dynamic alternatives. The
reserved `association` family refuses changed cardinality, names or order. A
dynamic candidate family requires a separately specified and evaluated extension.

`comparison_specification("topic" | "matter" | "occurrence")` creates separate
original propositions for topic overlap, one continuing subject and one actual
happening. Each has its own family and versioned reference. These small
conformance definitions establish no empirical identity accuracy or automatic
association permission.

Criteria are static. Registry lint rejects template markers, explicit
`[[level:...]]`/`[[level....]]` references and a narrow set of obvious reference-only
level descriptions such as `Same as previous level.`. This is conservative
syntax lint, not natural-language proof that arbitrary wording is self-contained.
The host still reviews descriptive criteria and qualifies actual procedures.

## Semantic change reports

`semantic_diff(before, after, certificates=())` lists concrete changed field
paths, distinguishes semantic change from opaque identity change, and reports
exact certificate references requiring applicability review. Certificate inputs
are declaration pairs `{reference, specification}` using component references.
Only declarations bound to the exact old specification are flagged, with
duplicates removed. The function does not claim those certificates exist or
are trusted, issue a replacement certificate, or transfer qualification. Even
an opaque identity rename can require reference applicability review while
leaving model-visible meaning unchanged.

For an offline example:

```python
from matter.semantic.questions import QuestionRegistry, association_specification
from matter.semantic.rendering import render_question

spec = association_specification()
registry = QuestionRegistry([spec])
state = {
    "observation": {"text": "Synthetic report of a recurring issue."},
    "candidate": {"id": "synthetic-subject", "text": "The continuing issue."},
}
rendered = render_question(registry.resolve(spec.reference), state, "route-1",
                           bound_ids=["synthetic-subject"])
assert rendered.question.value["specification_digest"] == spec.semantic_digest
```

Run `python -m unittest discover -s tests/semantic -p test_rendering.py -v` for the
synthetic [acceptance cases](validation/MAT-027.md).
