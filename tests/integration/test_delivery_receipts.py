"""Actual journal proof, rather than caller-shaped delivery assertions (MAT-021)."""
from copy import deepcopy

from integration.delivery_helpers import DeliveryFixture
from matter.outbox import REQUEST_EXTENSION, RESULT_EXTENSION, TransportResult


class DeliveryReceiptProofs(DeliveryFixture):
    def test_tampered_journal_proof_cannot_advance_baseline_or_commit_observation(self):
        intent, _, _ = self.enqueue()
        claim = self.service.prepare_claim(
            intent, token=self.token, worker="receipt-worker", lease_ms=10000,
            command_id="receipt-claim", idempotency_key="receipt-claim")
        leased = self.service.execute(claim)
        self.assertEqual(leased.get("outcome"), "leased", leased)
        lease = leased["extensions"][RESULT_EXTENSION]["value"]["lease"]
        prepared = self.service.prepare_authorize(
            intent, token=self.token, lease=lease, attempt_id="receipt-attempt",
            command_id="receipt-authorize", idempotency_key="receipt-authorize")
        authorized = self.service.execute(prepared)
        self.assertEqual(authorized.get("outcome"), "authorized", authorized)
        authorization = authorized["body"]["authorization"]
        observed = TransportResult({
            "status": "delivered", "receipt_id": "synthetic-receipt",
            "at": deepcopy(self.f.now), "milestone": "example:delivered",
            "reason": "transport:accepted"})
        completion = self.service.prepare_observation(
            authorization, observed, command_id="receipt-observation",
            idempotency_key="receipt-observation")
        baseline = self.a.baseline()
        # Both mutations retain valid command/result envelopes and all apparent
        # authorization pins. Only binding to the real immutable journal rejects
        # them. Each refusal must roll back its staged observation and baseline.
        for kind in ("command", "result"):
            with self.subTest(kind=kind):
                changed = deepcopy(completion)
                changed["command_id"] = changed["idempotency_key"] = "forged-" + kind
                proof = changed["extensions"][REQUEST_EXTENSION]["value"]["authorization_proof"]
                # Use a schema-valid extension value from the actual request.
                proof[kind].setdefault("extensions", {})["synthetic:tamper"] = deepcopy(
                    completion["extensions"][REQUEST_EXTENSION])
                result = self.service.execute(changed)
                self.assertEqual(result["status"], "failure", result)
                self.assertEqual(result["error"]["code"], "E_EVIDENCE_INVALID", result)
                self.assertEqual(self.a.baseline(), baseline)
        recorded = self.service.execute(completion)
        self.assertEqual(recorded.get("outcome"), "delivered", recorded)
        self.assertIsNotNone(self.a.baseline()["value"]["value"]["delivered"])
        self.assertEqual(self.transport.calls, [])
