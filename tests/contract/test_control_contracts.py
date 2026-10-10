"""Portable control schemas and the distinction between shape and authority."""

from copy import deepcopy
from importlib.resources import files
import json
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from matter.citations import _contract
from matter.contracts import _FORMAT_CHECKER, schema_for, validate_command
from matter.controls import _checked, control_effect
from matter.storage import StorageError


class ControlContractTests(unittest.TestCase):
    def test_all_control_resources_are_packaged_and_closed(self):
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        for name in ("control-effect", "control-sequence", "control-fence", "control-token", "control-hook"):
            body = json.loads(files("matter._schemas").joinpath(name + ".schema.json").read_text())
            Draft202012Validator.check_schema(body)
            validator = Draft202012Validator(body, registry=registry, format_checker=_FORMAT_CHECKER)
            self.assertFalse(validator.is_valid({"invented": "does not acquire meaning"}))
            self.assertFalse(body["additionalProperties"])
            self.assertEqual(_contract(name)[0]["version"], "1.0")

    def test_effect_rejects_untyped_capabilities_and_false_counter(self):
        effect = control_effect("deny", "Synthetic restriction.", capabilities=["read"])
        self.assertEqual(_checked("control-effect", effect["value"]), effect["value"])
        for mutation in ({"capabilities": ["superuser"]}, {"capabilities": ["read", "read"]}, {"authority": "invented"}):
            value = {**effect["value"], **mutation}
            with self.assertRaises(StorageError):
                _checked("control-effect", value)
        for epoch in (False, 1.0, float("inf")):
            with self.assertRaises(StorageError) as caught:
                _checked("control-sequence", {"scope_id": "synthetic:shape", "epoch": epoch})
            self.assertEqual(caught.exception.code, "E_SCHEMA_INVALID")

    def test_legacy_control_command_remains_structurally_readable(self):
        from pathlib import Path
        fixture = Path(__file__).resolve().parents[1] / "fixtures/contracts/commands/record_control.json"
        legacy = json.loads(fixture.read_text())
        self.assertEqual(validate_command(legacy), legacy)
        # Structural admission preserves its descriptor; it does not replace
        # an old arbitrary effect schema with the new executable schema.
        self.assertNotEqual(legacy["body"]["control"]["body"]["effect"]["schema"], _contract("control-effect")[0])
