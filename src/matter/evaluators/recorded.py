"""Frozen exact-input external answers; no provider invocation or fuzzy lookup."""
from copy import deepcopy

from ..canonical import canonical_bytes, canonical_digest, loads
from ..contracts import ContractError
from .._rule_values import FrozenValue, bounded, checked, descriptor, domain, fragment


class RecordedBinding(FrozenValue):
    __slots__ = ("_recordings",)

    def __init__(self, namespace, identity, version, *, evaluator, semantics, recordings=()):
        fragment(evaluator, "component_ref")
        fragment(semantics, "text")
        self._freeze({"namespace": namespace, "id": identity, "version": version,
                      "mode": "recorded", "evaluator": evaluator, "semantics": semantics,
                      "lookup": "exact-ordered-evaluation-input-digest-v1"})
        self.reference
        values, seen = [], set()
        for raw in bounded(list(recordings), 256):
            item = checked(raw, required=("input_digest", "response"), optional=("raw_result",))
            fragment(item["input_digest"], "sha256")
            if item["input_digest"] in seen:
                raise ContractError("E_POLICY_INVALID", "A recorded input must have one explicit result.")
            seen.add(item["input_digest"])
            # Shape is validated again by the executor; rule meaning and
            # qualification cannot be decided while recordings are installed.
            domain("rule-evaluator-response", item["response"])
            item.setdefault("raw_result", {"state": "unavailable", "reason": "not_recorded"})
            fragment(item["raw_result"], "raw_result_reference")
            values.append((item["input_digest"], canonical_bytes(item)))
        object.__setattr__(self, "_recordings", tuple(values))

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["version"], value,
                          "matter.evaluator-binding.v1")

    @property
    def mode(self):
        return "recorded"

    def evaluate(self, request):
        value = checked(request, required=("input_digest", "input"))
        if value["input_digest"] != canonical_digest(value["input"], "matter.evaluation-input.v1"):
            raise ContractError("E_EVIDENCE_INVALID", "The request bytes do not match their digest.")
        item = next((loads(record) for digest, record in self._recordings
                     if digest == value["input_digest"]), None)
        if item is None:
            raise ContractError("E_EVIDENCE_UNAVAILABLE", "No result was recorded for this exact input.")
        return {"response": deepcopy(item["response"]), "raw_result": deepcopy(item["raw_result"])}

