"""Typed links keep frozen graph rules across identity partition changes."""

from copy import deepcopy
from unittest.mock import patch

from association_helpers import ACTOR, SCOPE, AssociationTestCase, envelope
from matter.canonical import source_digest
from matter.identity_groups import read_group
from matter.relations import (
    RelationPolicy, RelationRule, RelationService, collect_relations,
    validate_identity_partition,
)
from matter.storage import StorageError, entity_ref, pin, snapshot_digest
from matter_helpers import metadata_command


class MatterRelationTests(AssociationTestCase):
    def setUp(self):
        super().setUp()
        self.rule = RelationRule("example:related_to", namespace="example", id="related-to")
        self.relations = self.service_for(self.rule)

    def service_for(self, *rules, actors=None, authorities=None):
        policy = RelationPolicy(SCOPE, actors=actors or [ACTOR],
            authorities=authorities or [pin(self.authority)], rules=rules)
        return RelationService(self.storage, policy=policy)

    def command(self, identity, first, second, *, rule=None, basis=None):
        rule = rule or self.rule
        return envelope(identity, "link_matters", {
            "from_matter": pin(first), "to_matter": pin(second),
            "relation_kind": rule.definition["kind"], "relationship_schema": rule.reference,
            "basis": [pin(self.subject)] if basis is None else basis,
        }, self.authority)

    def link(self, identity, first, second, *, rule=None, service=None):
        service = service or self.relations
        prepared = service.prepare(self.command(identity, first, second, rule=rule))
        result = service.link(prepared)
        self.assertEqual(result.get("outcome"), "linked", result)
        return self.storage.get(result["body"]["relation"]), prepared, result

    def mapping(self, *pairs):
        return [{"member": entity_ref(member), "survivor": entity_ref(survivor)} for member, survivor in pairs]

    def assert_code(self, code, function, *args):
        with self.assertRaises(StorageError) as error:
            function(*args)
        self.assertEqual(error.exception.code, code)

    def test_related_chain_preserves_three_identities_and_raw_endpoints(self):
        first, second, third = [self.matter(name) for name in ("a", "b", "c")]
        left, _, _ = self.link("a-related-b", first, second)
        right, _, _ = self.link("b-related-c", second, third)
        self.assertEqual(self.relations.for_matter(first), [left])
        self.assertEqual({item["id"] for item in self.relations.for_matter(second)}, {left["id"], right["id"]})
        with self.storage.snapshot() as view:
            for matter in (first, second, third):
                group = read_group(view, SCOPE, entity_ref(matter))
                self.assertEqual(group["members"], [matter])
                self.assertEqual(group["survivor"], matter)
            collected = collect_relations(view, SCOPE, [first, second, third])
        self.assertEqual(len(collected["records"]), 2)
        self.assertEqual(len(collected["indexes"]), 2)
        self.assertEqual(left["body"]["from_matter"], pin(first))
        self.assertEqual(left["body"]["to_matter"], pin(second))

    def test_directed_cycle_is_refused_without_partial_link(self):
        rule = RelationRule("example:depends_on", namespace="example", id="dependency", acyclic=True)
        service = self.service_for(rule)
        a, b, c = [self.matter(name) for name in ("a", "b", "c")]
        self.link("a-to-b", a, b, rule=rule, service=service)
        self.link("b-to-c", b, c, rule=rule, service=service)
        before = self.record_counts()
        self.assert_code("E_RULE_CONFLICT", service.prepare, self.command("c-to-a", c, a, rule=rule))
        self.assertEqual(self.record_counts(), before)

    def test_merge_partition_cannot_collapse_forbidden_self_relationship(self):
        a, b = self.matter("a"), self.matter("b")
        self.link("link-a-b", a, b)
        with self.storage.snapshot() as view:
            self.assert_code("E_MERGE_CONFLICT", validate_identity_partition, view, SCOPE,
                             self.mapping((a, a), (b, a)))

    def test_quotient_graph_detects_cycle_even_when_raw_graph_is_acyclic(self):
        rule = RelationRule("example:depends_on", namespace="example", id="dependency", acyclic=True)
        service = self.service_for(rule)
        a, b, c = [self.matter(name) for name in ("a", "b", "c")]
        self.link("a-to-b", a, b, rule=rule, service=service)
        self.link("b-to-c", b, c, rule=rule, service=service)
        with self.storage.snapshot() as view:
            self.assert_code("E_MERGE_CONFLICT", validate_identity_partition, view, SCOPE,
                             self.mapping((a, a), (c, a)))

    def test_explicit_reflexive_related_rule_permits_projection_without_merging(self):
        rule = RelationRule("example:reflexive_related", namespace="example", id="reflexive", allow_self=True)
        a, b = self.matter("a"), self.matter("b")
        link, _, _ = self.link("reflexive-link", a, b, rule=rule, service=self.service_for(rule))
        with self.storage.snapshot() as view:
            dependencies = validate_identity_partition(view, SCOPE, self.mapping((a, a), (b, a)))
            self.assertEqual(dependencies["records"], [link])
            self.assertEqual(len(read_group(view, SCOPE, entity_ref(a))["members"]), 1)

    def test_frozen_acyclic_rule_survives_permissive_later_rule_version(self):
        strict = RelationRule("example:depends_on", namespace="example", id="dependency", acyclic=True)
        relaxed = RelationRule("example:depends_on", namespace="elsewhere", id="relaxed", version="2.0")
        a, b = self.matter("a"), self.matter("b")
        self.link("strict-a-b", a, b, rule=strict, service=self.service_for(strict))
        relaxed_service = self.service_for(relaxed)
        self.assert_code("E_RULE_CONFLICT", relaxed_service.prepare,
                         self.command("relaxed-b-a", b, a, rule=relaxed))

    def test_undirected_acyclic_rules_refuse_triangle_and_normalize_duplicate_direction(self):
        rule = RelationRule("example:tree", namespace="example", id="tree", directed=False, acyclic=True)
        service = self.service_for(rule)
        a, b, c = [self.matter(name) for name in ("a", "b", "c")]
        first, _, _ = self.link("tree-a-b", a, b, rule=rule, service=service)
        same, _, _ = self.link("tree-b-a", b, a, rule=rule, service=service)
        self.assertEqual(first, same)
        self.link("tree-b-c", b, c, rule=rule, service=service)
        self.assert_code("E_RULE_CONFLICT", service.prepare, self.command("tree-c-a", c, a, rule=rule))

    def test_rule_is_immutable_content_bound_and_does_not_accept_boolean_numbers(self):
        before = self.rule.reference
        value = self.rule.definition
        value["allow_self"] = True
        self.assertEqual(self.rule.reference, before)
        with self.assertRaises(AttributeError):
            self.rule._encoded = b"{}"
        with self.assertRaises(StorageError) as error:
            RelationRule("example:x", namespace="example", id="x", directed=1)
        self.assertEqual(error.exception.code, "E_POLICY_INVALID")
        changed = RelationRule("example:related_to", namespace="example", id="related-to", allow_self=True)
        self.assertNotEqual(changed.reference, before)

    def test_authority_actor_and_exact_rule_are_independent_admission_gates(self):
        a, b = self.matter("a"), self.matter("b")
        command = self.command("unauthorized", a, b)
        command["actor"]["id"] = "unadmitted"
        self.assert_code("E_AUTHORITY_REQUIRED", self.relations.prepare, command)
        command = self.command("undeclared-rule", a, b)
        command["body"]["relationship_schema"]["digest"] = source_digest(b"forged definition")
        self.assert_code("E_POLICY_INVALID", self.relations.prepare, command)
        operation_receipt = self.storage.get(a["creation_receipt"])
        bad_service = self.service_for(self.rule, authorities=[pin(operation_receipt)])
        command = self.command("operation-not-authority", a, b)
        command["authority"] = entity_ref(operation_receipt)
        self.assert_code("E_AUTHORITY_REQUIRED", bad_service.prepare, command)

    def test_new_graph_edge_racing_preparation_forces_explicit_revision_refusal(self):
        rule = RelationRule("example:depends_on", namespace="example", id="dependency", acyclic=True)
        service = self.service_for(rule)
        a, b, c = [self.matter(name) for name in ("a", "b", "c")]
        self.link("a-to-b", a, b, rule=rule, service=service)
        prepared = service.prepare(self.command("prepared-b-c", b, c, rule=rule))
        self.link("racing-c-a", c, a, rule=rule, service=service)
        result = service.link(prepared)
        self.assert_failure(result, "E_REVISION_CONFLICT")
        self.assertEqual(service.link(prepared), result)
        self.assertEqual(len(service.for_matter(c)), 1)

    def test_fresh_metadata_does_not_rewrite_original_link_endpoints(self):
        a, b = self.matter("a"), self.matter("b")
        original, prepared, result = self.link("first-link", a, b)
        edit = metadata_command("metadata-after-link", a, {"title": "Updated source description"})
        changed = self.matters.update_metadata(self.matters.prepare(edit))
        latest = self.storage.get(changed["body"]["matter"])
        duplicate, _, _ = self.link("new-decision-same-edge", latest, b)
        self.assertEqual(duplicate, original)
        self.assertEqual(self.relations.link(prepared), result)
        self.assertEqual(self.relations.for_matter(latest), [original])
        self.assertEqual(original["body"]["from_matter"], pin(a))

    def test_exact_digest_dependencies_are_preserved_and_guarded(self):
        a, b = self.matter("a"), self.matter("b")
        command = self.command("digest-link", a, b)
        reference = {**entity_ref(a), "digest": snapshot_digest(a)}
        command["body"]["from_matter"] = reference
        command["expected_revisions"] = [deepcopy(reference)]
        prepared = self.relations.prepare(command)
        self.assertIn(reference, prepared["expected_revisions"])
        edit = metadata_command("metadata-race", a, {"title": "Changed before link"})
        self.matters.update_metadata(self.matters.prepare(edit))
        self.assert_failure(self.relations.link(prepared), "E_REVISION_CONFLICT")

    def test_foreign_endpoint_and_wrong_kind_identity_are_refused(self):
        a, b = self.matter("a"), self.matter("b")
        foreign = self.command("foreign-link", a, b)
        foreign["body"]["to_matter"]["scope_id"] = "another:scope"
        self.assert_code("E_SCOPE_FORBIDDEN", self.relations.prepare, foreign)
        wrong = self.command("wrong-kind-link", a, b)
        wrong["body"]["to_matter"] = {**entity_ref(self.subject), "record_type": "matter", "revision": 1}
        self.assert_code("E_EVIDENCE_INVALID", self.relations.prepare, wrong)

    def test_corrupt_watch_payload_and_port_outage_do_not_become_empty_graph(self):
        a, b = self.matter("a"), self.matter("b")
        self.link("indexed-link", a, b)
        with self.storage.snapshot() as snapshot:
            class BrokenView:
                def watchers(self, key):
                    values = snapshot.watchers(key)
                    if values:
                        values[0]["value"]["value"]["rule"]["allow_self"] = True
                    return values
                def lookup_identity(self, ref):
                    return snapshot.lookup_identity(ref)
            self.assert_code("E_EVIDENCE_INVALID", collect_relations, BrokenView(), SCOPE, [a])
            class UnavailableView:
                def watchers(self, key):
                    return snapshot.watchers(key)
                def lookup_identity(self, ref):
                    raise StorageError("E_STORAGE_UNAVAILABLE", retriable=True)
            self.assert_code("E_STORAGE_UNAVAILABLE", collect_relations, UnavailableView(), SCOPE, [a])

    def test_closed_link_indexes_reject_unknown_fields_and_wrong_watch_registration(self):
        a, b = self.matter("a"), self.matter("b")
        self.link("watched-link", a, b)
        with self.storage.snapshot() as snapshot:
            for mutation in (lambda row: row["value"]["value"].update(permission="merge"),
                             lambda row: row.update(watch_keys=[]),
                             lambda row: row.update(namespace="other:index")):
                class BrokenView:
                    def watchers(self, key):
                        values = snapshot.watchers(key)
                        for value in values:
                            mutation(value)
                        return values
                    def lookup_identity(self, ref):
                        return snapshot.lookup_identity(ref)
                self.assert_code("E_EVIDENCE_INVALID", collect_relations, BrokenView(), SCOPE, [a])

    def test_graph_bounds_refuse_instead_of_truncating_relation_inventory(self):
        a, b, c = [self.matter(name) for name in ("a", "b", "c")]
        self.link("a-to-b", a, b)
        self.link("a-to-c", a, c)
        with self.storage.snapshot() as view, patch("matter.relations._LIMIT", 1):
            self.assert_code("E_BUDGET_EXHAUSTED", collect_relations, view, SCOPE, [a])
