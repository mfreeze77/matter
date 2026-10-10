"""Storage-port boundaries supporting MAT-011 without weakening prior history."""

from copy import deepcopy
import unittest

from matter.controls import _fence
from matter.storage import StorageError, entity_ref, pin

from association_helpers import SCOPE
from control_helpers import ControlTestCase
from integration.helpers import create_command, record_input


class ControlStorageTests(ControlTestCase):
    def test_control_namespace_reservation_covers_all_user_record_kinds(self):
        for kind in ("observation", "matter", "occurrence", "claim", "evidence_relation"):
            for namespace in ("matter.controls", "matter.controls.hooks"):
                identity = kind + namespace.replace(".", "-")
                command = create_command(identity, identity + "-setup", scope_id=SCOPE)
                proposed = record_input(kind, identity, scope_id=SCOPE)
                proposed["namespace"] = namespace
                def handler(tx):
                    tx.insert(proposed)
                    saved = tx.insert(tx.command["body"]["matter"])
                    return tx.success("created", {"matter": pin(saved)})
                self.assert_failure(self.storage.execute(command, handler), "E_SCOPE_FORBIDDEN")
        self.assertIsNone(self.controls.current())

    def test_wrong_kind_fence_occupant_fails_closed_instead_of_epoch_zero(self):
        observation = deepcopy(self.subject)
        class ExistingLegacyOccupant:
            def lookup_identity(self, reference):
                value = deepcopy(observation)
                value.update(namespace=reference["namespace"], id=reference["id"])
                return value
            def get(self, reference):
                raise AssertionError("A typed missing lookup would hide the occupied address.")
        with self.assertRaises(StorageError) as caught:
            _fence(ExistingLegacyOccupant(), SCOPE, None)
        self.assertEqual(caught.exception.code, "E_STORAGE_UNAVAILABLE")

    def test_replay_guard_must_synchronously_authorize_and_does_not_rewrite_journal(self):
        command = create_command("replay-port", "replay-port-matter", scope_id=SCOPE)
        def handler(tx):
            saved = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(saved)})
        original = self.storage.execute(command, handler)
        async def asynchronous(view):
            raise AssertionError("An async guard cannot authorize synchronously.")
        for guard in (lambda view: False, asynchronous):
            self.assert_failure(self.storage.execute(command, handler, replay_guard=guard), "E_POLICY_INVALID")
            self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], original)
        self.assertEqual(self.storage.execute(command, handler, replay_guard=lambda view: None), original)

    def test_hook_storage_error_is_separate_from_already_returned_control(self):
        command, success = self.apply_control("already-committed")
        self.controls._hooks = {"unused": lambda control: None}
        original_status = self.controls.hook_status
        def unavailable(*args, **kwargs):
            raise StorageError("E_STORAGE_UNAVAILABLE")
        self.controls.hook_status = unavailable
        try:
            with self.assertRaises(StorageError):
                self.controls.run_hooks(success["body"]["control"], attempt_id="explicit")
        finally:
            self.controls.hook_status = original_status
        self.assertEqual(self.controls.apply(command), success)


if __name__ == "__main__":
    unittest.main()
