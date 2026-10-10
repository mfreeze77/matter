"""One bounded local attempt; no scheduler, provider client, or state mutation."""

from copy import deepcopy
from datetime import datetime, timezone
import math
import time

from ..canonical import canonical_bytes, canonical_digest
from ..contracts import ContractError, validate_record
from ..rules import RuleRegistry, SchemaRegistry
from ..storage import entity_ref
from ..time import validate_interval
from .._rule_values import checked, descriptor, domain, fragment, same
from .base import BindingRegistry, EvaluationBundle, EvaluationInput, QualificationRegistry


_ENGINE = descriptor("matter", "rule-evaluator", "1.0",
    {"semantics": "detached-single-attempt-v1", "authority": "none", "receipts": "uncommitted-inputs"},
    "matter.rule-evaluator.v1")


def _now():
    return {"state": "known", "value": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "precision": "microsecond"}


def _body(judgment):
    if "creation_receipt" in judgment:
        value = validate_record(judgment)
        if value["record_type"] != "judgment":
            raise ContractError("E_EVIDENCE_INVALID")
    else:
        value = fragment(judgment, "judgment_input")
    return value["body"]


def _label(body, rule, schemas):
    output = schemas.validate(body["semantic_output"])
    if output["schema"] != rule.value["output_schema"] or type(output["value"]) is not dict:
        raise ContractError("E_EVIDENCE_INVALID", "The semantic output does not use the exact rule schema.")
    outcome = rule.outcome(output["value"].get("label"))
    if outcome["evaluation_status"] != body["evaluation_status"]:
        raise ContractError("E_EVIDENCE_INVALID", "The label does not mean this evaluation status.")
    return outcome


def admit_result(judgment, rule, *, binding, schemas, qualifications=None, as_of,
                 accepted_labels, accepted_statuses=("applicable",), require_qualified=True):
    """Admit a prerequisite, not an action. Failure never means semantic false.

    Recheck certificate applicability at this consumption time. A stored
    qualification declaration alone cannot authenticate a certificate or
    revive an expired result. No result from this function grants authority.
    """
    body = _body(judgment)
    if not same(body["rule"], rule.reference) or not same(body["evaluator"], binding.reference):
        return {"status": "blocked", "reason": "meaning_or_binding_mismatch"}
    if body["execution_status"] != "completed":
        return {"status": "blocked", "reason": "execution_" + body["execution_status"]}
    outcome = _label(body, rule, schemas)
    for label in accepted_labels:
        rule.outcome(label)
    if body["evaluation_status"] not in accepted_statuses:
        return {"status": "blocked", "reason": "evaluation_" + body["evaluation_status"]}
    if outcome["label"] not in accepted_labels:
        return {"status": "blocked", "reason": "output_not_admitted"}
    registry = qualifications if qualifications is not None else QualificationRegistry()
    qualification = registry.classify(body["qualification"], rule=rule, binding=binding,
        context=body["dependency_manifest"]["context"], as_of=as_of)
    if require_qualified and qualification["status"] not in {"qualified", "not_required"}:
        return {"status": "blocked", "reason": "qualification_" + qualification["status"]}
    return {"status": "usable", "reason": "declared_prerequisite_satisfied"}


class RuleEvaluator:
    """Pure single-attempt executor over host-installed cooperative bindings.

    Byte/count limits are enforced before use. Elapsed time is checked after
    a synchronous callback returns; TimeoutError is typed. This is not a
    preemptive timeout or sandbox for arbitrary Python. Host supervision of
    blocked/untrusted work belongs to the later executor, not this adapter.
    """
    __slots__ = ("rules", "bindings", "schemas", "qualifications", "_clock", "_monotonic")

    def __init__(self, *, rules, bindings, schemas, qualifications=None, clock=None, monotonic=None):
        if not isinstance(rules, RuleRegistry) or not isinstance(bindings, BindingRegistry) or not isinstance(schemas, SchemaRegistry):
            raise ContractError("E_POLICY_INVALID")
        self.rules, self.bindings, self.schemas = rules, bindings, schemas
        self.qualifications = qualifications if qualifications is not None else QualificationRegistry()
        self._clock = clock or _now
        self._monotonic = monotonic or time.monotonic

    def _fallback(self, rule, label, reason):
        outcome = rule.outcome(label)
        return {"execution_status": "completed", "evaluation_status": outcome["evaluation_status"],
                "semantic_output": deepcopy(outcome["fallback_output"]),
                "qualification": {"status": "unknown"}, "used_evidence": [],
                "proposed_consequences": [], "limitations": [reason]}

    def _preconditions(self, rule, packet, started):
        definition = rule.value
        requirements = definition["evidence_requirements"]
        roles = {role for item in packet["evidence"] for role in item["roles"]}
        missing = (len(packet["evidence"]) < requirements["minimum"]
            or not set(requirements["required_roles"]) <= roles
            or any(item["mandatory"] for item in packet["omitted"])
            or (requirements["require_complete_coverage"] and packet["coverage"]["status"] != "complete"))
        if missing:
            return self._fallback(rule, requirements["incomplete_label"], "Required evidence or coverage is incomplete.")
        for condition in definition["preconditions"]:
            value = packet["proposition"]["value"]
            try:
                for part in condition["pointer"].split("/")[1:]:
                    part = part.replace("~1", "/").replace("~0", "~")
                    if isinstance(value, list):
                        if not part.isascii() or not part.isdigit() or (part != "0" and part.startswith("0")):
                            raise KeyError(part)
                        value = value[int(part)]
                    elif isinstance(value, dict):
                        value = value[part]
                    else:
                        raise KeyError(part)
                passes = same(value, condition["equals"])
            except (KeyError, IndexError, TypeError, ValueError):
                passes = False
            if not passes:
                return self._fallback(rule, condition["otherwise_label"], "A declared deterministic prerequisite was not satisfied.")
        supplied = {}
        for predecessor in packet["upstream"]:
            key = canonical_bytes(predecessor["body"]["rule"])
            if key in supplied:
                raise ContractError("E_RULE_CONFLICT", "Multiple upstream results need an explicit composition policy.")
            supplied[key] = predecessor
        expected = {canonical_bytes(item["rule"]) for item in definition["dependencies"]}
        if set(supplied) - expected:
            raise ContractError("E_EVIDENCE_INVALID", "The packet includes an undeclared upstream rule.")
        for requirement in definition["dependencies"]:
            predecessor = supplied.get(canonical_bytes(requirement["rule"]))
            if predecessor is None:
                return self._fallback(rule, requirements["incomplete_label"], "A required predecessor is missing.")
            previous_rule = self.rules.resolve(requirement["rule"])
            previous_binding = self.bindings.resolve(previous_rule.value["evaluator_binding"])
            admission = admit_result(predecessor, previous_rule, binding=previous_binding,
                schemas=self.schemas, qualifications=self.qualifications, as_of=started,
                accepted_labels=requirement["accepted_labels"], accepted_statuses=requirement["accepted_statuses"],
                require_qualified=requirement["require_qualified"])
            if admission["status"] != "usable":
                return self._fallback(rule, requirements["incomplete_label"], "Required predecessor blocked: " + admission["reason"] + ".")
        return None

    def _validate_response(self, response, rule, packet):
        value = domain("rule-evaluator-response", response)["value"]
        allowed = [{"reference": item["reference"], "locator": item["locator"]} for item in packet["evidence"]]
        seen = set()
        for use in value["used_evidence"]:
            encoded = canonical_bytes(use)
            if use not in allowed or encoded in seen:
                raise ContractError("E_EVIDENCE_INVALID", "Citations must be unique exact admitted evidence and locators.")
            seen.add(encoded)
        if value["execution_status"] != "completed":
            return value
        outcome = _label(value, rule, self.schemas)
        for proposal in value["proposed_consequences"]:
            self.schemas.validate(proposal)
            if proposal["schema"] not in outcome["implications"]:
                raise ContractError("E_AUTHORITY_REQUIRED", "The rule does not permit this typed proposal.")
        return value

    def evaluate(self, prepared, *, judgment_id, attempt_id, check_control=None):
        if not isinstance(prepared, EvaluationInput):
            raise ContractError("E_SCHEMA_INVALID", "Evaluation requires a prepared detached input.")
        request = prepared.value
        packet = request["packet"]
        rule = self.rules.resolve(packet["rule"])
        if not same(request["rule_definition"], rule.value):
            raise ContractError("E_POLICY_INVALID", "The complete executed rule definition changed.")
        binding = self.bindings.resolve(packet["binding"])
        if not same(binding.reference, rule.value["evaluator_binding"]):
            raise ContractError("E_POLICY_INVALID")
        for identity in (judgment_id, attempt_id):
            fragment(identity, "identifier")
        if judgment_id == attempt_id:
            raise ContractError("E_SCHEMA_INVALID", "Judgment and attempt identities must be distinct.")
        token = prepared.control_token
        if token is not None and not callable(check_control):
            raise ContractError("E_POLICY_INVALID", "A captured host control token requires its currentness guard.")
        # Revalidate exact packet bytes before calling any installed function.
        domain("rule-evaluation-input", packet)
        if len(prepared.canonical_bytes) > rule.value["resource_limits"]["max_input_bytes"]:
            raise ContractError("E_BUDGET_EXHAUSTED")
        started = fragment(self._clock(), "known_time")
        tick = self._monotonic()
        response, called, reason, failure_code = None, False, "completed", None
        raw = {"state": "not_produced", "reason": "No evaluator response was returned."}
        try:
            if token is not None:
                check_control(deepcopy(token))
            response = self._preconditions(rule, packet, started)
            if response is None:
                called = True
                returned = binding.evaluate({"input_digest": prepared.digest, "input": deepcopy(request)})
                returned = checked(returned, required=("response", "raw_result"))
                if len(canonical_bytes(returned)) > rule.value["resource_limits"]["max_output_bytes"]:
                    raise ContractError("E_BUDGET_EXHAUSTED")
                raw = fragment(returned["raw_result"], "raw_result_reference")
                response = self._validate_response(returned["response"], rule, packet)
            else:
                response = self._validate_response(response, rule, packet)
            if token is not None:
                check_control(deepcopy(token))
        except TimeoutError:
            reason = "timed_out"
        except ContractError as error:
            reason = "cancelled" if error.code == "E_CANCELLED" else "budget_exhausted" if error.code == "E_BUDGET_EXHAUSTED" else "failed"
            failure_code = error.code
        except Exception:
            reason = "failed"
        elapsed = max(0, int(math.ceil((self._monotonic() - tick) * 1000)))
        ended = fragment(self._clock(), "known_time")
        interval = validate_interval({"start": started, "end": ended, "bounds": "closed"})
        if reason == "completed" and elapsed > rule.value["resource_limits"]["max_elapsed_ms"]:
            reason = "timed_out"
        if reason != "completed":
            response = {"execution_status": reason, "qualification": {"status": "unknown"},
                        "used_evidence": [], "proposed_consequences": [], "limitations": ["The attempt did not establish a domain conclusion."]}
        status = response["execution_status"]
        qualification = (self.qualifications.classify(response["qualification"], rule=rule, binding=binding,
            context=packet["context"], as_of=ended) if status == "completed" else {"status": "unknown"})
        scope = packet["scope_id"]
        receipt_ref = {"scope_id": scope, "namespace": "matter.rule_attempts", "record_type": "receipt", "id": attempt_id}
        receipt_body = {"input_digest": prepared.digest, "rule": rule.reference, "binding": binding.reference,
                        "execution_status": status, "qualification": qualification, "elapsed_ms": elapsed,
                        "called": called, "reason": "The declared result was validated." if status == "completed" else "The evaluator did not complete a usable attempt.",
                        "control_token_digest": packet["control_token_digest"], "raw_result": raw}
        parents = deepcopy(packet["dependencies"]["positive"])
        receipt = {"schema_version": "1.0", **receipt_ref,
                   "provenance": {"origin": "system", "producer": deepcopy(_ENGINE), "recorded_at": ended, "parents": parents},
                   "body": {"stage": "evaluation", "operation_id": attempt_id, "recorded_at": ended,
                            "outcome": "matter:evaluation_" + status, "evidence": parents,
                            "details": domain("rule-evaluation-receipt", receipt_body)}}
        body = {"rule": rule.reference, "input_digest": prepared.digest, "evaluator": binding.reference,
                "execution_status": status, "qualification": qualification, "used_evidence": response["used_evidence"],
                "limitations": response["limitations"], "dependency_manifest": deepcopy(packet["dependencies"]),
                "attempt_receipts": [receipt_ref], "proposed_consequences": response["proposed_consequences"],
                "input_artifact": {"state": "unavailable", "reason": "not_persisted"},
                "raw_result": raw, "execution_interval": interval}
        if status == "completed":
            body.update(evaluation_status=response["evaluation_status"], semantic_output=response["semantic_output"])
        else:
            body["failure"] = {"reason": status, "detail": "The attempt produced no admissible domain conclusion.",
                               "attempt_receipt": receipt_ref}
            if failure_code:
                body["failure"]["code"] = failure_code
        judgment = {"schema_version": "1.0", "record_type": "judgment", "scope_id": scope,
                    "namespace": "matter.rule_judgments", "id": judgment_id,
                    "provenance": {"origin": "evaluator", "producer": binding.reference, "recorded_at": ended, "parents": parents},
                    "body": body}
        return EvaluationBundle(judgment, receipt)

