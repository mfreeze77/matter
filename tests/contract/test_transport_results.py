"""Declared terminal and ambiguous transport meanings must agree (MAT-021)."""
from itertools import product
import unittest

from matter._rule_values import domain
from matter.contracts import ContractError
from matter.outbox import TransportResult


class TransportResultContracts(unittest.TestCase):
    PAIRS = {
        ("delivered", "transport:accepted"),
        ("failed", "transport:rejected"),
        ("delivery_unknown", "transport:timeout"),
        ("delivery_unknown", "transport:unknown"),
        ("delivery_unknown", "transport:unavailable"),
        ("not_found", "transport:not_found"),
    }

    def value(self, status, reason):
        return {
            "status": status, "reason": reason,
            "receipt_id": "synthetic-acceptance" if status == "delivered" else None,
            "milestone": "synthetic:delivered" if status == "delivered" else None,
            "at": {"state": "unknown", "reason": "not_reported"},
        }

    def test_declared_success_definite_failure_and_uncertainty_pairs(self):
        for status, reason in sorted(self.PAIRS):
            with self.subTest(status=status, reason=reason):
                value = self.value(status, reason)
                self.assertEqual(domain("delivery-transport-result", value)["value"], value)
                self.assertEqual(TransportResult(value).value, value)

    def test_contradictory_pairs_cannot_reopen_an_unknown_delta_as_failed(self):
        statuses = {status for status, _ in self.PAIRS}
        reasons = {reason for _, reason in self.PAIRS}
        for status, reason in sorted(set(product(statuses, reasons)) - self.PAIRS):
            with self.subTest(status=status, reason=reason):
                value = self.value(status, reason)
                for check in (lambda: domain("delivery-transport-result", value),
                              lambda: TransportResult(value)):
                    with self.assertRaises(ContractError) as refused:
                        check()
                    self.assertEqual(refused.exception.code, "E_SCHEMA_INVALID")
