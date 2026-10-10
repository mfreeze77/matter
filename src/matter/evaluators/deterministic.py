"""A trusted installed function over a detached request, not a Python sandbox."""
from copy import deepcopy

from ..canonical import canonical_bytes, canonical_digest
from ..contracts import ContractError
from .._rule_values import FrozenValue, bounded, checked, descriptor, fragment


class DeterministicBinding(FrozenValue):
    __slots__ = ("_function",)

    def __init__(self, namespace, identity, version, *, implementation, semantics, conformance_cases, function):
        fragment(implementation, "component_ref")
        fragment(semantics, "text")
        cases = bounded(conformance_cases, 64)
        if not cases or not callable(function):
            raise ContractError("E_POLICY_INVALID", "An installed function requires explicit conformance cases.")
        for case in cases:
            checked(case, required=("name", "invariant"))
            fragment(case["name"], "text")
            fragment(case["invariant"], "text")
        self._freeze({"namespace": namespace, "id": identity, "version": version,
                      "mode": "deterministic", "implementation": implementation,
                      "semantics": semantics, "conformance_cases": cases})
        self.reference
        object.__setattr__(self, "_function", function)

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["version"], value,
                          "matter.evaluator-binding.v1")

    @property
    def mode(self):
        return "deterministic"

    def evaluate(self, request):
        value = checked(request, required=("input_digest", "input"))
        if value["input_digest"] != canonical_digest(value["input"], "matter.evaluation-input.v1"):
            raise ContractError("E_EVIDENCE_INVALID", "The request bytes do not match their digest.")
        # The callback receives only a detached JSON copy. Installed code is
        # trusted and cooperative; this is not process isolation or preemption.
        result = self._function(deepcopy(value))
        return {"response": deepcopy(result), "raw_result": {"state": "not_applicable",
                "reason": "An installed deterministic function has no provider wire response."}}

