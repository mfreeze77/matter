"""Claim-relative evidence behavior; synthetic declarations do not establish truth."""

from copy import deepcopy

from matter.canonical import source_digest
from matter.storage import entity_ref, pin

from claim_helpers import (ClaimTestCase, PASSAGE, acceptance_command, claim_command,
                           relation_command)
from integration.helpers import domain_value


class ClaimRelationTests(ClaimTestCase):
    def test_one_passage_supports_and_qualifies_distinct_declared_components(self):
        claim, _, _ = self.append()
        support, _, _ = self.relate(claim, "support")
        qualification, _, _ = self.relate(
            claim, "qualification", relation="qualifies", component="example:timing",
            quotation="subject to approval",
        )
        relations = self.relations.for_claim(pin(claim))
        self.assertEqual({row["id"] for row in relations}, {"support", "qualification"})
        self.assertEqual(self.relations.for_claim(
            pin(claim), target={"kind": "component", "component": "example:funding"}), [support])
        self.assertEqual(self.relations.for_claim(
            pin(claim), target={"kind": "component", "component": "example:timing"}), [qualification])
        self.assertEqual(support["body"]["evidence"], qualification["body"]["evidence"])
        self.assertEqual(self.validation(support)["result"], {
            "status": "valid", "kind": "exact_passage",
            "selection_digest": source_digest(PASSAGE.splitlines(keepends=True)[0]),
        })
        self.assertEqual(self.storage.get(pin(claim)), claim)

    def test_support_for_a_does_not_establish_b_or_an_assessment(self):
        discussion, _, _ = self.append("discussion")
        approval, _, _ = self.append("approval", value="approved allocation")
        self.relate(discussion)
        self.assertEqual(self.relations.for_claim(pin(approval)), [])
        self.assertEqual(self.storage.get(pin(approval))["body"]["value"]["value"], "approved allocation")
        self.assertNotIn("assessment", self.record_counts())
        self.assertEqual(self.storage.get(entity_ref(self.subject)), self.subject)

    def test_all_six_relation_kinds_remain_separate_records(self):
        claim, _, _ = self.append()
        labels = {"supports", "contradicts", "qualifies", "reports_assertion", "context_only", "unresolved"}
        for label in sorted(labels):
            self.relate(claim, label, relation=label, component=None)
        self.assertEqual({row["body"]["relation"] for row in self.relations.for_claim(pin(claim))}, labels)
        self.assertEqual(len(self.claims.for_subject(entity_ref(self.subject))), 1)

    def test_component_must_belong_to_exact_claim_version(self):
        old, _, _ = self.append("old", components={"example:old": domain_value("old component")})
        revised, _, _ = self.append("revised", version="2.0", supersedes=[old],
                                     components={"example:new": domain_value("new component")})
        command = relation_command("wrong-component", "wrong-component", revised, self.source,
                                   component="example:new")
        prepared = self.relations.prepare(command)
        prepared["body"]["relation"]["body"]["target"]["component"] = "example:old"
        result = self.relations.relate(prepared)
        self.assert_failure(result, "E_EVIDENCE_INVALID")
        self.assertEqual(self.relations.for_claim(pin(revised)), [])
        self.relate(old, "old-still-readable", component="example:old")

    def test_temporal_scope_qualifiers_and_attribution_are_preserved(self):
        command = claim_command("scoped", "scoped", self.subject, self.source)
        body = command["body"]["claim"]["body"]
        body["qualifiers"] = [domain_value({"condition": "subject to authorization", "amount": 100})]
        body["applicability"] = {
            "start": {"state": "known", "value": "2027-01-01T00:00:00Z", "precision": "second"},
            "end": {"state": "known", "value": "2028-01-01T00:00:00Z", "precision": "second"},
            "bounds": "closed_open",
        }
        result = self.claims.append(self.claims.prepare(command))
        stored = self.storage.get(result["body"]["claim"])
        self.assertEqual(stored["body"], body)
        relation_command_value = relation_command("scoped-support", "scoped-support", stored, self.source)
        relation_command_value["body"]["relation"]["body"]["applicability"] = deepcopy(body["applicability"])
        relation_result = self.relations.relate(self.relations.prepare(relation_command_value))
        relation = self.storage.get(relation_result["body"]["relation"])
        self.assertEqual(relation["body"]["applicability"], body["applicability"])

    def test_whole_artifact_is_declared_and_never_marked_exact_passage(self):
        claim, _, _ = self.append()
        relation, _, _ = self.relate(claim, exact=False, quotation=None)
        declaration = self.validation(relation)
        self.assertEqual(declaration["locator"]["kind"], "whole_artifact")
        self.assertIsNone(declaration["quotation"])
        self.assertEqual(declaration["result"], {
            "status": "valid", "kind": "whole_artifact", "selection_digest": source_digest(PASSAGE),
        })

    def test_quote_elsewhere_and_reversed_lines_fail_without_relation_children(self):
        claim, _, _ = self.append()
        for identity, lines, quotation in (
            ("elsewhere", (2, 2), "Funding is expected next year"),
            ("reversed", (2, 1), "Funding"),
            ("out-of-range", (1, 3), "Funding"),
            ("absent", (1, 1), "Funding has been approved"),
        ):
            with self.subTest(identity=identity):
                command = relation_command(identity, identity, claim, self.source,
                                           lines=lines, quotation=quotation)
                prepared = self.relations.prepare(command)
                result = self.relations.relate(prepared)
                self.assert_failure(result, "E_EVIDENCE_INVALID")
                self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], result)
                self.assertEqual(self.relations.for_claim(pin(claim)), [])
        self.assertNotIn("evidence_relation", self.record_counts())

    def test_unavailable_and_withheld_sources_have_distinct_honest_failure(self):
        claim, _, _ = self.append()
        for availability in ("unavailable", "withheld"):
            with self.subTest(availability=availability):
                source = self.observe(availability, availability=availability)
                command = relation_command(availability, availability, claim, source)
                prepared = self.relations.prepare(command)
                self.assertEqual(prepared["body"]["validation"]["value"]["result"]["status"], "unavailable")
                result = self.relations.relate(prepared)
                self.assert_failure(result, "E_EVIDENCE_UNAVAILABLE")
                self.assertEqual(self.storage.get(pin(source)), source)
        self.assertEqual(self.relations.for_claim(pin(claim)), [])

    def test_all_acceptance_statuses_still_require_valid_citation(self):
        claim, _, _ = self.append()
        for status in ("proposed", "accepted", "rejected", "superseded"):
            with self.subTest(status=status):
                command = relation_command(status, status, claim, self.source, status=status,
                                           quotation="This is not in the original source.")
                result = self.relations.relate(self.relations.prepare(command))
                self.assert_failure(result, "E_EVIDENCE_INVALID")
        self.assertEqual(self.relations.for_claim(pin(claim)), [])

    def test_acceptance_authority_cannot_be_borrowed_from_source_assertion(self):
        claim, _, _ = self.append()
        command = relation_command("wrong-authority", "wrong-authority", claim, self.source)
        prepared = self.relations.prepare(command)
        prepared["body"]["relation"]["body"]["acceptance"]["authority"] = self.source["creation_receipt"]
        result = self.relations.relate(prepared)
        self.assert_failure(result, "E_POLICY_INVALID")
        self.assertEqual(self.relations.for_claim(pin(claim)), [])

    def test_retraction_does_not_synthesize_opposite_claim(self):
        claim, _, _ = self.append()
        relation, _, _ = self.relate(claim)
        before = self.record_counts()
        command = acceptance_command("withdraw", relation, "rejected")
        result = self.relations.revise_acceptance(self.relations.prepare(command))
        self.assertEqual(result["outcome"], "updated")
        revised = self.storage.get(result["body"]["relation"])
        self.assertEqual(revised["body"]["relation"], "supports")
        self.assertEqual(revised["body"]["acceptance"]["status"], "rejected")
        self.assertEqual(self.relations.for_claim(pin(claim), status="accepted"), [])
        self.assertEqual(self.relations.for_claim(pin(claim), status="rejected"), [revised])
        self.assertEqual(self.claims.for_subject(entity_ref(self.subject)), [claim])
        self.assertEqual(self.record_counts()["claim"], before["claim"])
        self.assertNotIn("assessment", self.record_counts())
        self.assertEqual(self.storage.get(entity_ref(self.subject)), self.subject)
