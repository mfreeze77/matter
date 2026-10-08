"""Identity and idempotency properties of validated contract digest helpers."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from matter.contracts import ContractError, command_digest, record_digest


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def fixture(relative):
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


class ContractDigestTests(unittest.TestCase):
    def test_record_hash_preserves_order_independence_and_scoped_identity(self):
        record = fixture("records/matter.json")
        before = deepcopy(record)
        original = record_digest(record)
        reordered = dict(reversed(list(record.items())))
        self.assertEqual(record_digest(reordered), original)
        for field, other in (("scope_id", "synthetic:other"), ("namespace", "other")):
            with self.subTest(field=field):
                changed = deepcopy(record)
                changed[field] = other
                self.assertNotEqual(record_digest(changed), original)
        self.assertEqual(record, before)

    def test_same_idempotency_key_does_not_hide_changed_command_content(self):
        command = fixture("commands/create_matter.json")
        original = command_digest(command)
        changed = deepcopy(command)
        changed["body"]["matter"]["body"]["title"] = "A changed proposed subject"
        self.assertEqual(changed["idempotency_key"], command["idempotency_key"])
        self.assertNotEqual(command_digest(changed), original)
        self.assertEqual(command_digest(dict(reversed(list(command.items())))), original)

    def test_invalid_contracts_do_not_receive_validated_record_or_command_hashes(self):
        for digest, relative in (
            (record_digest, "records/matter.json"),
            (command_digest, "commands/create_matter.json"),
        ):
            with self.subTest(relative=relative):
                invalid = fixture(relative)
                invalid["schema_version"] = "2.0"
                with self.assertRaises(ContractError) as error:
                    digest(invalid)
                self.assertEqual(error.exception.code, "E_VERSION_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
