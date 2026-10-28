# Bounded source-linked semantic packets

MAT-028 implements deterministic preparation for a single claim or candidate
relation in `matter.semantic.packets`. It consumes explicitly supplied pins
through one host-authorized storage snapshot and the existing payload store.
It performs no candidate discovery, adaptive retrieval, provider call, source
mutation or action dispatch. The [JEV contract](jev.md) governs its meaning.

```python
from matter.semantic.packets import PacketProfile, prepare_packet
from matter.semantic.rendering import render_question

profile = PacketProfile({
    "namespace": "example", "id": "claim-packet", "version": "1.0",
    "required_roles": ["example:basis", "example:counterexample"],
    "allowed_origins": ["source", "derived", "evaluator"],
    "locator_adapters": [locator_adapter.reference],
    "max_sources": 16, "max_source_bytes": 65536, "max_packet_bytes": 262144,
})
with store.snapshot() as view:
    packet = prepare_packet(
        view, profile, payloads=payload_store, scope_id=store.scope_id,
        binding={"kind": "candidate_relation", "left": left_pin,
                 "right": right_pin, "relation": "example:same_matter"},
        as_of=knowledge_cut, evidence=explicit_sources,
        occurrences=exact_occurrence_pins, coverage=host_coverage,
    )
rendered = render_question(specification, packet.state, "comparison-1",
                           source_manifest=packet.source_manifest)
assert rendered.question.value["packet_digest"] == packet.digest
```

The host supplies the storage/payload handles, authenticated access, installed
locator adapter, admitted declarations, source roles and source-selection
coverage. A packet profile or quoted source cannot grant these permissions.

## Source and subject bindings

A binding is either `{kind: "claim", claim: exact_claim_pin}` or
`{kind: "candidate_relation", left: exact_pin, right: exact_pin, relation:
namespaced_relation}`. Candidate endpoints may be observations, occurrences or
matters. Every endpoint is read and matched against its exact same-scope pin;
foreign scopes are refused before source rendering. Claim packets retain the
proposition values rather than inventing one from a topic label. Preparation
revision 1.1 freezes references inside that selected body to exact, same-scope
snapshots available at the packet cut, and includes their read dependencies.
The immutable original body remains available through the claim pin. This is a
packet view; it does not revise the claim or turn its assertions into evidence.
Unavailable referenced records refuse preparation. The revision changes the
preparation fingerprint so prior packet/cache identities cannot silently mix.

Each evidence declaration has exactly `reference`, `roles`, `locator`,
`quotation` and `validation`. The reference pins an existing observation.
`validation` is the existing immutable locator-adapter declaration. Preparation
checks its source, content, locator, exact quotation, admitted adapter and read
dependencies with `verify_locator_validation`. Late or unknown locator-read
dependencies are omitted with an explicit knowledge-cut reason. It then reads and verifies
original bytes using the existing `PayloadStore`. Whole-artifact text uses
strict UTF-8 without normalization. For a selected span, the model text is the
exact validated quotation; it does not silently become another line range or
summary. Source and text hashes remain separate.

Availability always comes from the stored observation. An old event timestamp
cannot make a later cancellation visible before its publication/availability
cut. Unknown availability remains unknown. Non-observation bindings and
occurrence-group snapshots require their own recorded and committing-receipt
times to be available at the cut. Such receipts are checked facts, not an
inference from a revision number or event time.

## Deterministic bounded selection

The profile binds its namespace, identity, version, required roles, allowed
origins, admitted locator adapters and resource limits into a component
reference. The preparation algorithm has its own exact version/digest.
Changing either changes packet identity and later qualification applicability.

Candidate references are unique. Role lists have set semantics. Selection
orders every source bearing a required role first, then orders exact reference
bytes canonically. No semantic ranking or arrival/completion order is used.
Foreign scope is an error; missing source snapshots, unavailable or denied
payloads, unusable locators, ineligible origins, unknown/late availability and
source/count/packet limits produce explicit omission records.

Oversized sources are omitted whole. No partial text is silently relabeled
complete. The total bound covers the final canonical state, including coverage,
binding, provenance and mechanical calculation metadata. If those final fields
overflow, preparation removes the last selected source deterministically and
recomputes the state until it fits. A budget too small for even the empty
packet metadata fails explicitly with `E_BUDGET_EXHAUSTED`.

Limits are at most 128 candidate sources, 128 explicit occurrence pins and
1 MiB of model-visible canonical state. Audit material is bounded separately
to 4 MiB. Original payload I/O remains subject to the host's existing payload
store and authorized source-size limits; this module is not a streaming media
reader or a general large-artifact ingestion service.

## Coverage, occurrence and provenance

`packet.state["coverage"]` reports `complete` or `incomplete`, missing required
roles, mandatory omission count, source coverage and separate occurrence and
provenance status. Any unavailable/oversized required source keeps coverage
incomplete even when another source supplies the same role. Optional source
omissions remain visible in the audit while the profile may still have all its
declared requirements met. A complete packet does not establish source truth,
complete retrieval, authority, permission or the truth of an absence claim.

Occurrence pins are an explicit supplied set. Preparation validates actual
stored membership against the candidate observations, counts only occurrences
with selected members, and preserves unavailable-at-cut groupings as audit
omissions. It does not discover every occurrence through an unbounded query or
claim that an empty supplied set proves no event occurred.

Provenance uses the existing `resolve_groups` algorithm and exact observation
parents/root assignments. Original, copied and repeatedly summarized reports
retain the union of declared root groups; they do not mint extra corroboration.
Distinct groups are declared dependence groups, not empirically qualified
independent sources. Unknown/missing ancestry remains explicit.

The resolver normally reads current root assignments. Preparation checks every
resolved ancestor's observation availability and every assignment snapshot's
committing receipt against the historical cut. A newer assignment is never
backdated: its groups are withheld from model state, provenance coverage becomes
incomplete, and the audit records `provenance_not_available_at_cut`. This
bounded adapter does not reconstruct an earlier historical grouping or
substitute an older declaration implicitly.

## Mechanical facts and receipts

`state.mechanical` contains selected observation, occurrence and provenance
group counts together with their exact input references. It also contains
pairwise exact source-event and source-revision matches, availability ordering
and event-time ordering. The existing nanosecond-aware `matter.time`
comparisons calculate dates in code. Unknown event instants remain unknown;
original occurrence intervals are retained separately and never reduced to a
guessed instant. None of these mechanical results is delegated to a model.

`packet.state`, `.canonical` and `.digest` describe exactly the model-visible
packet. The digest uses `matter.semantic.packet.v1`, matching MAT-027 rendering.
The separately detached `.source_manifest` has `included`, `excluded` and
`truncation`; it is passed to the renderer's audit interface. Omissions may
contain future or unavailable IDs, so the full `.value`, `.source_manifest`
and diagnostic arrays must not be used as provider state. The renderer does
not append these audit fields to instructions. `.audit_digest` binds the full
manifest, read dependencies, omission reasons and limits for later execution
receipts. Model-visible state still contains the coverage summary needed to
preserve uncertainty, without future source IDs or text.

All exposed JSON is detached. Caller mutation cannot change the frozen packet
or profile. Preparation performs no durable assessment commit, transitive
invalidation, certificate issuance or provider admission. The
[receipt store](semantic-receipts.md) and [admission service](semantic-qualification.md)
retain exact packet/profile/preparation/audit identities and perform their own
currentness and authority checks.

See the [MAT-028 receipt](validation/MAT-028.md) for executed synthetic evidence.
