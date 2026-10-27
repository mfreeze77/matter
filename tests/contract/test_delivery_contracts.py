"""MAT-021 portable stage distinctions, independently of transport execution."""

from copy import deepcopy
import unittest

from matter.contracts import ContractError, error_result, validate_result
from contract.test_operation_contracts import fixture


class DeliveryContractTests(unittest.TestCase):
    def invalid(self, value):
        with self.assertRaises(ContractError):
            validate_result(value)

    def test_authorization_is_distinct_from_observed_delivery(self):
        value = fixture("results/dispatch__authorized.json")
        self.assertEqual(validate_result(value), value)
        wrong = deepcopy(value)
        wrong["outcome"] = "delivered"
        self.invalid(wrong)
        for name in ("authorization", "attention_budget"):
            wrong = deepcopy(value)
            wrong["body"].pop(name)
            self.invalid(wrong)

    def test_lease_fence_is_a_nonnegative_portable_integer(self):
        value = fixture("results/dispatch__leased.json")
        self.assertEqual(validate_result(value), value)
        for counter in (-1, True, 1.0):
            wrong = deepcopy(value)
            wrong["body"]["fence"] = counter
            self.invalid(wrong)

    def test_recording_an_unknown_is_not_transport_success(self):
        value = fixture("results/dispatch__recorded.json")
        self.assertEqual(validate_result(value), value)
        for status in ("failed", "delivery_unknown", "consumed", "acted_on", "outcome_verified", "useful"):
            current = deepcopy(value)
            current["body"]["status"] = status
            self.assertEqual(validate_result(current), current)
        for status in ("delivered", "authorized", "ready", "success"):
            current = deepcopy(value)
            current["body"]["status"] = status
            self.invalid(current)
        unknown = error_result("dispatch", "synthetic-unknown", "E_DELIVERY_UNKNOWN")
        self.assertEqual(validate_result(unknown), unknown)
        unknown["body"] = value["body"]
        self.invalid(unknown)

    def test_dispatch_stage_bodies_are_closed(self):
        for stage in ("leased", "authorized", "recorded"):
            value = fixture("results/dispatch__" + stage + ".json")
            value["body"]["assume_consumed"] = True
            self.invalid(value)
