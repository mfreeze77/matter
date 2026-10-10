"""Detached evaluator protocols and qualification admission.

A certificate registry is an explicit host allowlist of already issued,
content-bound declarations. It validates applicability; it neither issues a
certificate nor establishes model accuracy or permission to act.
"""

from copy import deepcopy
from typing import Protocol

from ..canonical import canonical_bytes, canonical_digest, loads
from ..contracts import ContractError, validate_record
from ..rules import RuleDefinition
from ..storage import pin
from ..time import compare_times, validate_interval
from .._rule_values import FrozenValue, bounded, checked, domain, fragment, same, unique


_PREPARED_INPUT = object()


class Evaluator(Protocol):
    @property
    def reference(self) -> dict: ...
    @property
    def mode(self) -> str: ...
    def evaluate(self, request: dict) -> dict: ...


class EvaluationInput(FrozenValue):
    """An ordered, bounded packet prepared from the host's read-only view."""
    __slots__ = ("_control",)

    def __init__(self, rule, packet, *, control_token=None, _admission=None):
        if _admission is not _PREPARED_INPUT:
            raise ContractError("E_POLICY_INVALID", "Use prepare_input with an authorized read view.")
        if not isinstance(rule, RuleDefinition):
            raise ContractError("E_POLICY_INVALID")
        body = domain("rule-evaluation-input", packet)["value"]
        if not same(body["rule"], rule.reference) or not same(body["binding"], rule.value["evaluator_binding"]):
            raise ContractError("E_POLICY_INVALID", "The packet does not bind the exact rule and evaluator.")
        token = None
        if control_token is not None:
            canonical_bytes(control_token)
            if (type(control_token) is not dict or control_token.get("scope_id") != body["scope_id"]
                    or type(control_token.get("control_epoch")) is not int
                    or control_token["control_epoch"] != body["dependencies"]["control_epoch"]):
                raise ContractError("E_POLICY_INVALID", "The host control token does not match the packet.")
            token = deepcopy(control_token)
        expected = None if token is None else canonical_digest(token, "matter.evaluation-control.v1")
        if body["control_token_digest"] != expected:
            raise ContractError("E_POLICY_INVALID", "The exact host control token must be bound.")
        if token is None and body["dependencies"]["control_epoch"] != 0:
            raise ContractError("E_POLICY_INVALID", "A nonzero control epoch requires its host token.")
        self._freeze({"rule_definition": rule.value, "packet": body})
        if len(self._encoded) > rule.value["resource_limits"]["max_input_bytes"]:
            raise ContractError("E_BUDGET_EXHAUSTED")
        object.__setattr__(self, "_control", canonical_bytes(token))

    @property
    def digest(self):
        return canonical_digest(self.value, "matter.evaluation-input.v1")

    @property
    def control_token(self):
        return loads(self._control)

    @property
    def canonical_bytes(self):
        return bytes(self._encoded)


class BindingRegistry:
    """Host-installed functions only. No import strings, eval, or source execution."""
    __slots__ = ("_bindings",)

    def __init__(self, bindings=()):
        values = tuple(bindings)
        if len(values) > 128:
            raise ContractError("E_BUDGET_EXHAUSTED")
        identities = set()
        for binding in values:
            ref = fragment(binding.reference, "component_ref")
            identity = (ref["namespace"], ref["id"], ref["version"])
            if identity in identities or binding.mode not in {"deterministic", "recorded"} or not callable(binding.evaluate):
                raise ContractError("E_POLICY_INVALID", "Invalid or duplicate installed evaluator binding.")
            identities.add(identity)
        object.__setattr__(self, "_bindings", tuple((canonical_bytes(item.reference), item) for item in values))

    def __setattr__(self, name, value):
        raise AttributeError("BindingRegistry is immutable.")

    def resolve(self, reference):
        key = canonical_bytes(fragment(reference, "component_ref"))
        for ref, binding in self._bindings:
            if key == ref:
                # A mutable third-party descriptor must not silently replace its identity.
                if canonical_bytes(binding.reference) != ref:
                    raise ContractError("E_POLICY_INVALID", "An installed binding changed its descriptor.")
                return binding
        raise ContractError("E_POLICY_INVALID", "The exact evaluator binding is not installed.")


class QualificationRegistry:
    __slots__ = ("_certificates",)

    def __init__(self, certificates=()):
        admitted = []
        identities = set()
        for raw in bounded(list(certificates), 128):
            certificate = checked(raw, required=("reference", "rule", "binding", "input_schema", "output_schema", "preparation",
                "task_scope", "threshold_policy", "valid_from", "valid_until", "evaluation_evidence"))
            for field in ("reference", "rule", "binding", "input_schema", "output_schema", "preparation", "task_scope", "threshold_policy"):
                fragment(certificate[field], "component_ref")
            fragment(certificate["valid_from"], "known_time")
            fragment(certificate["valid_until"], "known_time")
            if compare_times(certificate["valid_from"], certificate["valid_until"]) != -1:
                raise ContractError("E_POLICY_INVALID", "Certificate validity must be a nonempty known interval.")
            evidence = bounded(certificate["evaluation_evidence"], 128)
            if not evidence:
                raise ContractError("E_POLICY_INVALID", "An admitted certificate requires evaluation evidence.")
            for item in evidence:
                fragment(item, "pinned_ref")
            content = {key: value for key, value in certificate.items() if key != "reference"}
            if certificate["reference"]["digest"] != canonical_digest(content, "matter.qualification-certificate.v1"):
                raise ContractError("E_POLICY_INVALID", "Certificate content does not match its admitted digest.")
            key = canonical_bytes(certificate["reference"])
            if key in identities:
                raise ContractError("E_POLICY_INVALID", "A certificate may be admitted only once.")
            identities.add(key)
            admitted.append((key, canonical_bytes(certificate)))
        object.__setattr__(self, "_certificates", tuple(admitted))

    def __setattr__(self, name, value):
        raise AttributeError("QualificationRegistry is immutable.")

    def classify(self, reported, *, rule, binding, context, as_of):
        claim = fragment(reported, "qualification")
        definition = rule.value
        requirement = definition["qualification_requirement"]
        if binding.mode == "deterministic" and requirement["kind"] == "deterministic":
            return {"status": "not_required", "reason": requirement["reason"]}
        if claim["status"] == "not_required":
            return {"status": "unqualified", "reason": "A recorded semantic result cannot waive qualification."}
        reference = claim.get("certificate")
        if reference is None:
            return {"status": "unqualified" if claim["status"] == "unqualified" else "unknown",
                    "reason": "No applicable admitted certificate was supplied."}
        certificate = next((loads(value) for key, value in self._certificates
                            if key == canonical_bytes(reference)), None)
        if certificate is None:
            return {"status": "unknown", "reason": "The host has not admitted this exact certificate."}
        expected = {"rule": rule.reference, "binding": binding.reference,
                    "input_schema": definition["input_schema"], "output_schema": definition["output_schema"],
                    "preparation": definition["evidence_preparation"],
                    "task_scope": requirement.get("task_scope"), "threshold_policy": requirement.get("threshold_policy")}
        if any(certificate[key] != value for key, value in expected.items()) or certificate["task_scope"] not in context:
            return {"status": "mismatched", "certificate": deepcopy(reference),
                    "reason": "The certificate does not cover this exact meaning, binding, preparation or task."}
        boundary = fragment(as_of, "known_time")
        if compare_times(boundary, certificate["valid_from"]) == -1:
            return {"status": "mismatched", "certificate": deepcopy(reference), "reason": "The certificate is not yet valid."}
        if compare_times(boundary, certificate["valid_until"]) != -1:
            return {"status": "expired", "certificate": deepcopy(reference), "reason": "Certificate validity has expired."}
        if claim["status"] != "qualified":
            return {"status": "unqualified", "certificate": deepcopy(reference),
                    "reason": "The recorded result did not declare qualified execution."}
        return {"status": "qualified", "certificate": deepcopy(reference)}


class EvaluationBundle(FrozenValue):
    """Uncommitted creation inputs, never a current assessment or authority."""
    __slots__ = ()

    def __init__(self, judgment, receipt):
        fragment(judgment, "judgment_input")
        fragment(receipt, "receipt_input")
        if receipt["body"]["stage"] != "evaluation":
            raise ContractError("E_EVIDENCE_INVALID")
        receipt_ref = {key: receipt[key] for key in ("scope_id", "namespace", "record_type", "id")}
        if judgment["body"]["attempt_receipts"] != [receipt_ref]:
            raise ContractError("E_EVIDENCE_INVALID", "The judgment must bind its actual returned attempt receipt.")
        if "failure" in judgment["body"] and judgment["body"]["failure"]["attempt_receipt"] != receipt_ref:
            raise ContractError("E_EVIDENCE_INVALID")
        self._freeze({"judgment": judgment, "receipt": receipt})

    @property
    def judgment(self):
        return self.value["judgment"]

    @property
    def receipt(self):
        return self.value["receipt"]

