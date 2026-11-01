"""Native milestone formatting remains separate from admission authority."""
from copy import deepcopy
import unittest

from matter.attention import build_delivery_milestone_details
from matter._rule_values import domain
from matter.contracts import ContractError


def arguments():
    ref = {"scope_id": "synthetic:builder", "namespace": "example", "id": "decision",
           "record_type": "receipt", "digest": "a" * 64}
    component = {"namespace": "example", "id": "purpose", "version": "1.0", "digest": "b" * 64}
    return {"decision": ref, "assessment": {**ref, "record_type": "assessment", "id": "assessment"},
            "matter": {k: v for k, v in {**ref, "record_type": "matter", "id": "subject"}.items() if k != "digest"},
            "purpose": component, "audience": {**component, "id": "audience"}, "material_digest": "c" * 64,
            "delivered_at": {"state": "known", "value": "2026-10-31T12:00:00Z", "precision": "second"}}


class DeliveryMilestoneBuilderTests(unittest.TestCase):
    def test_public_builder_matches_existing_native_wire(self):
        args = arguments()
        expected = domain("attention-delivery-milestone", {
            "schema_version": "1.0", **args, "milestone": "delivered"})
        self.assertEqual(build_delivery_milestone_details(**args), expected)

    def test_null_or_study_assessment_invalid_material_and_time_refuse(self):
        for key, value in (("assessment", None), ("assessment", arguments()["decision"]),
                           ("material_digest", "not-a-digest"),
                           ("delivered_at", {"state": "unknown", "reason": "not_reported"})):
            with self.subTest(field=key, value=value):
                args = arguments(); args[key] = value
                with self.assertRaises(ContractError):
                    build_delivery_milestone_details(**args)

    def test_values_are_detached_and_no_storage_or_transport_is_required(self):
        args = arguments(); original = deepcopy(args)
        result = build_delivery_milestone_details(**args)
        result["value"]["decision"]["id"] = "changed"
        self.assertEqual(args, original)
        self.assertNotEqual(build_delivery_milestone_details(**args), result)
