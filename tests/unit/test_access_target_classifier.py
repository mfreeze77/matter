"""Public classification preserves source-grant boundaries, not permissions."""
from copy import deepcopy
import unittest

from matter.access import HostAccessPolicy, _public, is_source_access_target
from matter.contracts import ContractError


def reference(kind="observation", namespace="synthetic.host"):
    return {"scope_id": "synthetic:access", "namespace": namespace,
            "record_type": kind, "id": "target", "digest": "a" * 64}


class AccessTargetClassifierTests(unittest.TestCase):
    def test_one_callable_preserves_old_import_without_mutating_input(self):
        self.assertIs(is_source_access_target, _public)
        ref = reference(); original = deepcopy(ref)
        self.assertTrue(is_source_access_target(ref))
        self.assertEqual(ref, original)

    def test_bookkeeping_and_exact_internal_projection_prefix(self):
        cases = [
            ("receipt", "synthetic.host", False), ("control", "synthetic.host", False),
            ("receipt", "matter.internal", False), ("control", "matter.internal", False),
            ("matter:projection", "matter.internal", False),
            ("matter:projection", "matter.", False),
            ("matter:projection", "synthetic.host", True),
            ("matter:projection", "matter", True),
            ("matter:projection", "matterish.internal", True),
            ("observation", "matter.internal", True),
            ("claim", "synthetic.host", True), ("judgment", "synthetic.host", True),
            ("assessment", "synthetic.host", True), ("matter", "synthetic.host", True),
        ]
        for kind, namespace, expected in cases:
            with self.subTest(kind=kind, namespace=namespace):
                self.assertIs(is_source_access_target(reference(kind, namespace)), expected)

    def test_true_candidate_does_not_authorize_a_foreign_scope(self):
        ref = reference()
        self.assertTrue(is_source_access_target(ref))
        with self.assertRaises(ContractError) as denied:
            HostAccessPolicy(scope_id="synthetic:other", audiences=[], providers=[],
                grants=[{"reference": ref, "audiences": [], "providers": []}])
        self.assertEqual(denied.exception.code, "E_SCOPE_FORBIDDEN")

    def test_excluded_bookkeeping_is_not_a_source_grant(self):
        ref = reference("receipt")
        self.assertFalse(is_source_access_target(ref))
        with self.assertRaises(ContractError) as denied:
            HostAccessPolicy(scope_id=ref["scope_id"], audiences=[], providers=[],
                grants=[{"reference": ref, "audiences": [], "providers": []}])
        self.assertEqual(denied.exception.code, "E_SCOPE_FORBIDDEN")
