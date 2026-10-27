"""Public context declarations must be usable as actual core references."""

from copy import deepcopy
import unittest

from matter._rule_values import domain, fragment
from matter.contexts import ContextDefinition, context_ref
from matter.contracts import ContractError
from matter.dispositions import DispositionDefinition, disposition_ref


class ContextNamespaceTests(unittest.TestCase):
    def context(self):
        return {"schema_version": "1.0", "namespace": "example:contexts", "id": "purpose",
            "semantic_version": "1.0", "kind": "purpose", "description": "Synthetic purpose.",
            "applies_to": [], "effective_from": {"state": "known", "value": "2026-10-27T00:00:00Z", "precision": "second"},
            "effective_until": {"state": "unknown", "reason": "not_applicable"},
            "content": {"objectives": [], "constraints": []}}

    def disposition(self):
        component = {"namespace": "example", "id": "context", "version": "1.0", "digest": "0" * 64}
        pointer = {"scope_id": "synthetic", "namespace": "example:contexts", "record_type": "matter:projection",
            "id": "context", "revision": 1}
        return {"schema_version": "1.0", "namespace": "example:dispositions", "kind": "acknowledgement",
            "matter": {"scope_id": "synthetic", "namespace": "example", "record_type": "matter", "id": "subject"},
            "purpose": {"reference": deepcopy(component), "context": deepcopy(pointer)},
            "audience": {"reference": deepcopy(component), "context": deepcopy(pointer)},
            "subject": {"scope_id": "synthetic", "namespace": "example", "record_type": "observation",
                "id": "source", "digest": "0" * 64},
            "effective_from": {"state": "known", "value": "2026-10-27T00:00:00Z", "precision": "second"},
            "effective_until": {"state": "unknown", "reason": "not_applicable"},
            "reason": "Synthetic receipt only.", "decision": None, "status": "active"}

    def test_invalid_namespaces_fail_at_declaration_instead_of_persistence(self):
        for schema, make, constructor in (("context-definition", self.context, ContextDefinition),
                ("disposition-definition", self.disposition, DispositionDefinition)):
            valid = constructor(make())
            fragment(valid.reference, "component_ref")
            address = context_ref("synthetic", valid) if schema == "context-definition" else disposition_ref(valid)
            fragment(address, "entity_ref")
            for namespace in ("1host", "@acme", "acme+ops"):
                with self.subTest(schema=schema, namespace=namespace):
                    value = make()
                    value["namespace"] = namespace
                    with self.assertRaises(ContractError):
                        domain(schema, value)
                    with self.assertRaises(ContractError):
                        constructor(value)

    def test_context_version_contract_matches_component_reference(self):
        value = self.context()
        value["semantic_version"] = "version with spaces"
        with self.assertRaises(ContractError):
            domain("context-definition", value)
        with self.assertRaises(ContractError):
            ContextDefinition(value)

