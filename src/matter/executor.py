"""MAT-014 concurrent bounded rule stages over explicit host preparation seams.

The executor retains uncommitted diagnostics. It grants no storage, source,
control, assessment publication, or external-delivery capability.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event, Lock
import math
import time

from ._rule_values import FrozenValue, checked, descriptor, fragment
from .canonical import canonical_bytes
from .conflicts import ConflictResolverRegistry
from .contracts import ContractError
from .evaluators.base import EvaluationInput
from .evaluators.runner import RuleEvaluator, admit_result, _now
from .planner import RulePlan, read_pointer

_FINISHED_RUN = object()


class GraphRun(FrozenValue):
    __slots__ = ()

    def __init__(self, value, *, _completion=None):
        if _completion is not _FINISHED_RUN:
            raise ContractError("E_POLICY_INVALID", "Use GraphExecutor to produce a graph-run diagnostic.")
        self._freeze(value)

    @property
    def reference(self):
        value = self.value
        return descriptor("matter", value["run_id"], "1.0", value, "matter.rule-graph-run.v1")


class GraphExecutor:
    """One cooperative bounded graph run, with deterministic stage admission.

    Host preparation runs serially after fresh prerequisite admission. Evaluator
    callbacks may run concurrently and must use safe host handles. The host's
    currentness/control callbacks must work across those threads; max_workers=1
    supports hosts with serial handles. Threads are joined; blocked arbitrary
    Python cannot be preempted or sandboxed by this in-process executor.
    """
    def __init__(self, evaluator, *, conflicts=None, clock=None, monotonic=None):
        if not isinstance(evaluator, RuleEvaluator):
            raise ContractError("E_POLICY_INVALID", "An exact rule evaluator is required.")
        if conflicts is not None and not isinstance(conflicts, ConflictResolverRegistry):
            raise ContractError("E_POLICY_INVALID")
        self.evaluator = evaluator
        self.conflicts = conflicts if conflicts is not None else ConflictResolverRegistry()
        self.clock = clock or _now
        self.monotonic = monotonic or time.monotonic

    def execute(self, plan, *, prepare, run_id, remaining_budget=None, max_workers=4,
                check_current=None, check_control=None, cancelled=None):
        if not isinstance(plan, RulePlan) or not callable(prepare):
            raise ContractError("E_POLICY_INVALID", "A compiled plan and explicit host preparer are required.")
        fragment(run_id, "identifier")
        if type(max_workers) is not int or not 1 <= max_workers <= 16:
            raise ContractError("E_POLICY_INVALID", "Worker concurrency must be between one and sixteen.")
        if cancelled is not None and not callable(cancelled):
            raise ContractError("E_POLICY_INVALID")
        declaration = plan.value
        for reference in declaration["nodes"].values():
            rule = self.evaluator.rules.resolve(reference)
            self.evaluator.bindings.resolve(rule.value["evaluator_binding"])
        for group in declaration["compositions"]:
            resolver = self.conflicts.resolve(group["resolver"]).value
            if resolver["mode"] == "precedence" and not set(group["nodes"]) <= set(resolver["precedence"]):
                raise ContractError("E_POLICY_INVALID", "The explicit resolver order does not cover every composed node.")
        ceiling = declaration["resource_limits"]
        budget = deepcopy(ceiling) if remaining_budget is None else checked(remaining_budget, required=tuple(ceiling), code="E_POLICY_INVALID")
        if any(type(value) is not int or value < 0 or value > ceiling[key] for key, value in budget.items()):
            raise ContractError("E_POLICY_INVALID", "Remaining resource limits must fit the admitted profile envelope.")
        start = self.monotonic()
        deadline = start + budget["max_elapsed_ms"] / 1000
        spent = {"reserved_attempts": 0, "reserved_input_bytes": 0, "reserved_output_bytes": 0, "actual_invocations": 0}
        receipts, prepared_inputs = {}, {}
        scope = None
        pending = list(declaration["order"])
        cancellation = Event()
        cancellation_lock = Lock()
        stop_diagnostics = []

        def stopped():
            with cancellation_lock:
                if cancellation.is_set():
                    return True
                if cancelled is None:
                    return False
                try:
                    answer = cancelled()
                except Exception:
                    stop_diagnostics.append({"stage": "cancellation_query", "reason": "callback_failed",
                        "error_code": "E_POLICY_INVALID"})
                    cancellation.set()
                    return True
                if type(answer) is not bool:
                    stop_diagnostics.append({"stage": "cancellation_query", "reason": "non_boolean_result",
                        "error_code": "E_POLICY_INVALID"})
                    cancellation.set()
                    return True
                if answer:
                    cancellation.set()
                return answer

        def admission(name, selector):
            receipt = receipts[name]
            if receipt["status"] not in {"completed", "unresolved"} or receipt["judgment"] is None:
                return {"status": "blocked", "reason": "predecessor_" + receipt["status"]}
            rule = self.evaluator.rules.resolve(declaration["nodes"][name])
            now = fragment(self.clock(), "known_time")
            # A host may install additional admission constraints even for an
            # input without a native mutable/time watch. Do not discard that
            # explicit guard when consuming a completed attempt.
            if callable(check_current):
                check_current(prepared_inputs[name], as_of=deepcopy(now))
            return admit_result(receipt["judgment"], rule,
                binding=self.evaluator.bindings.resolve(rule.value["evaluator_binding"]), schemas=self.evaluator.schemas,
                qualifications=self.evaluator.qualifications, expected_input=prepared_inputs[name],
                as_of=now, accepted_labels=selector["accepted_labels"],
                accepted_statuses=selector["accepted_statuses"], require_qualified=selector["require_qualified"],
                check_current=check_current)

        def edge_admission(edge):
            source = edge["from"]
            selector = edge
            if edge["kind"] == "conditional":
                source_rule = self.evaluator.rules.resolve(declaration["nodes"][source])
                selector = {**edge, "accepted_labels": [item["label"] for item in source_rule.value["outcomes"]],
                    "accepted_statuses": ["applicable", "not_applicable", "insufficient_evidence", "ambiguous", "conflicting"]}
            accepted = admission(source, selector)
            if accepted["status"] != "usable":
                return accepted
            body = receipts[source]["judgment"]["body"]
            if edge["kind"] == "conditional" and (body["evaluation_status"] not in edge["accepted_statuses"]
                    or body["semantic_output"]["value"]["label"] not in edge["accepted_labels"]):
                state = "skipped" if body["evaluation_status"] == "applicable" else "blocked"
                return {"status": state, "reason": "condition_not_satisfied"}
            return accepted

        def node_receipt(name, status, reason, *, error_code=None, bundle=None):
            edges = [edge for edge in declaration["edges"] if edge["to"] == name]
            return {"node": name, "rule": declaration["nodes"][name], "status": status, "reason": reason,
                "error_code": error_code, "input_digest": prepared_inputs[name].digest if name in prepared_inputs else None,
                "upstream_input_digests": {edge["from"]: receipts[edge["from"]]["input_digest"] for edge in edges},
                "judgment": bundle.judgment if bundle is not None else None,
                "attempt_receipt": bundle.receipt if bundle is not None else None}

        def fail_node(name, error, stage):
            code = error.code if isinstance(error, ContractError) else None
            status = ("cancelled" if code == "E_CANCELLED" else "budget_exhausted" if code == "E_BUDGET_EXHAUSTED" else
                      "blocked" if code in {"E_EVIDENCE_UNAVAILABLE", "E_STORAGE_UNAVAILABLE", "E_DEPENDENCY_STALE"} else "failed")
            receipts[name] = node_receipt(name, status, stage, error_code=code)

        def evaluate(name, prepared):
            if stopped():
                raise ContractError("E_CANCELLED")
            bundle = self.evaluator.evaluate(prepared, judgment_id=run_id + ":judgment:" + name,
                attempt_id=run_id + ":attempt:" + name, check_current=check_current, check_control=check_control)
            return bundle, self.monotonic(), stopped()

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="matter-rule") as pool:
            while pending:
                is_cancelled = stopped()
                if is_cancelled or self.monotonic() >= deadline:
                    state = "cancelled" if is_cancelled else "budget_exhausted"
                    for name in pending:
                        receipts[name] = node_receipt(name, state, "host_cancelled" if state == "cancelled" else "shared_elapsed_limit")
                    pending.clear()
                    break
                ready = [name for name in pending if all(other in receipts for other in declaration["dependencies"][name])]
                if not ready:
                    raise ContractError("E_POLICY_INVALID", "The compiled graph has no runnable frontier.")
                futures = {}
                for name in sorted(ready)[:max_workers]:
                    pending.remove(name)
                    try:
                        if stopped():
                            raise ContractError("E_CANCELLED")
                        edges = [edge for edge in declaration["edges"] if edge["to"] == name]
                        predecessors = {}
                        blocked = False
                        for edge in edges:
                            source = edge["from"]
                            accepted = edge_admission(edge)
                            if accepted["status"] != "usable":
                                receipts[name] = node_receipt(name, accepted["status"], accepted["reason"])
                                blocked = True
                                break
                            predecessors[source] = {"judgment": receipts[source]["judgment"], "input": prepared_inputs[source].value}
                        if blocked:
                            continue
                        if spent["reserved_attempts"] >= budget["max_calls"]:
                            receipts[name] = node_receipt(name, "budget_exhausted", "shared_call_limit")
                            continue
                        rule = self.evaluator.rules.resolve(declaration["nodes"][name])
                        prepared = prepare(name, deepcopy(predecessors))
                        if not isinstance(prepared, EvaluationInput):
                            raise ContractError("E_POLICY_INVALID", "The host must return an admitted EvaluationInput.")
                        input_scope = prepared.value["packet"]["scope_id"]
                        if scope is None:
                            scope = input_scope
                        elif scope != input_scope:
                            raise ContractError("E_SCOPE_FORBIDDEN", "A rule graph cannot combine independent host scopes.")
                        self._check_prepared(prepared, rule, name, declaration, predecessors)
                        prepared_inputs[name] = prepared
                        if stopped():
                            raise ContractError("E_CANCELLED")
                        size = len(prepared.canonical_bytes)
                        output_cap = rule.value["resource_limits"]["max_output_bytes"]
                        if (spent["reserved_input_bytes"] + size > budget["max_input_bytes"]
                                or spent["reserved_output_bytes"] + output_cap > budget["max_output_bytes"]
                                or len(prepared.value["packet"]["evidence"]) > budget["max_evidence"]):
                            receipts[name] = node_receipt(name, "budget_exhausted", "shared_byte_or_evidence_limit")
                            continue
                        if self.monotonic() >= deadline:
                            receipts[name] = node_receipt(name, "budget_exhausted", "shared_elapsed_limit")
                            continue
                        spent["reserved_attempts"] += 1
                        spent["reserved_input_bytes"] += size
                        spent["reserved_output_bytes"] += output_cap
                        futures[name] = pool.submit(evaluate, name, prepared)
                    except Exception as error:
                        fail_node(name, error, "preparation_or_admission_failed")
                # A stable frontier barrier makes budget admission independent of
                # future completion order while still evaluating independent nodes concurrently.
                for name in sorted(futures):
                    try:
                        bundle, finished, was_cancelled = futures[name].result()
                        body = bundle.judgment["body"]
                        status = body["execution_status"]
                        if status == "completed" and body["evaluation_status"] != "applicable":
                            status = "unresolved"
                        reason = "evaluated"
                        if was_cancelled:
                            status, reason = "cancelled", "host_cancelled_after_attempt"
                        elif finished > deadline:
                            status, reason = "timed_out", "shared_elapsed_limit_after_attempt"
                        receipts[name] = node_receipt(name, status, reason, bundle=bundle)
                        spent["actual_invocations"] += int(bundle.receipt["body"]["details"]["value"]["called"])
                    except Exception as error:
                        fail_node(name, error, "evaluation_failed")
        # Recheck each exact original input at consumption time. Unusable attempts
        # remain diagnostics, never fresh semantic results or implicit negatives.
        for name in declaration["order"]:
            receipt = receipts[name]
            if receipt["status"] not in {"completed", "unresolved", "skipped"}:
                continue
            edge_checks = []
            for edge in (edge for edge in declaration["edges"] if edge["to"] == name):
                try:
                    accepted = edge_admission(edge)
                except Exception as error:
                    accepted = {"status": "blocked", "reason": "edge_currentness_failed",
                        "error_code": error.code if isinstance(error, ContractError) else None}
                edge_checks.append({"from": edge["from"], "kind": edge["kind"], **accepted})
            receipt["final_edge_admissions"] = edge_checks
            cancelled_edge = next((item for item in edge_checks if item.get("error_code") == "E_CANCELLED"), None)
            blocked_edge = next((item for item in edge_checks if item["status"] == "blocked"), None)
            skipped_edge = next((item for item in edge_checks if item["status"] == "skipped"), None)
            held_edge = cancelled_edge or blocked_edge or skipped_edge
            if held_edge is not None:
                receipt["status"] = "cancelled" if cancelled_edge is not None else held_edge["status"]
                receipt["reason"] = "final_" + held_edge["reason"]
                receipt["final_admission"] = {**held_edge, "reason": receipt["reason"]}
            if held_edge is not None or receipt["status"] == "skipped":
                continue
            rule = self.evaluator.rules.resolve(declaration["nodes"][name])
            selector = {"accepted_labels": [item["label"] for item in rule.value["outcomes"]],
                        "accepted_statuses": ["applicable", "not_applicable", "insufficient_evidence", "ambiguous", "conflicting"],
                        "require_qualified": False}
            try:
                result = admission(name, selector)
            except Exception as error:
                result = {"status": "blocked", "reason": "final_currentness_failed",
                          "error_code": error.code if isinstance(error, ContractError) else None}
            receipt["final_admission"] = result
            if result["status"] != "usable":
                receipt["status"] = "cancelled" if result.get("error_code") == "E_CANCELLED" else "blocked"
                receipt["reason"] = result["reason"]
        composition_results = []
        for group in declaration["compositions"]:
            originals = [{"node": name, "judgment": receipts[name]["judgment"],
                          "input_digest": receipts[name]["input_digest"], "status": receipts[name]["status"]} for name in sorted(group["nodes"])]
            held = []
            selectors = list(group["mandatory_gates"])
            for name in group["nodes"]:
                rule = self.evaluator.rules.resolve(declaration["nodes"][name])
                selectors.append({"node": name, "accepted_labels": [item["label"] for item in rule.value["outcomes"]],
                    "accepted_statuses": ["applicable"], "require_qualified": True})
            for selector in selectors:
                try:
                    accepted = admission(selector["node"], selector)
                except Exception:
                    accepted = {"status": "blocked", "reason": "composition_currentness_failed"}
                if accepted["status"] != "usable":
                    held.append({"node": selector["node"], "reason": accepted["reason"]})
            if stopped() or self.monotonic() > deadline:
                held.append({"node": None, "reason": "shared_cancelled_or_elapsed_limit"})
            if held:
                resolution = {"status": "withheld", "treatment": "quiet", "selected_node": None,
                    "semantic_output": None, "originals": originals, "resolver": group["resolver"], "held_gates": held}
            else:
                resolution = self.conflicts.resolve(group["resolver"]).compose(originals)
                resolution["held_gates"] = []
            composition_results.append({"id": group["id"], **resolution})
        elapsed = max(0, math.ceil((self.monotonic() - start) * 1000))
        remaining = {
            "max_calls": max(0, budget["max_calls"] - spent["reserved_attempts"]),
            "max_input_bytes": max(0, budget["max_input_bytes"] - spent["reserved_input_bytes"]),
            "max_output_bytes": max(0, budget["max_output_bytes"] - spent["reserved_output_bytes"]),
            "max_evidence": budget["max_evidence"],
            "max_elapsed_ms": max(0, budget["max_elapsed_ms"] - elapsed),
        }
        stop_reason = ("cancelled" if stopped() else "elapsed_limit" if self.monotonic() > deadline else
                       "completed" if all(item["status"] == "completed" for item in receipts.values())
                       and all(item["status"] == "resolved" for item in composition_results) else "incomplete")
        status = "completed" if stop_reason == "completed" else "incomplete"
        return GraphRun({"schema_version": "1.0", "run_id": run_id, "scope_id": scope, "plan": plan.reference,
            "profile": declaration["profile"], "status": status, "stop_reason": stop_reason,
            "stop_diagnostics": stop_diagnostics,
            "nodes": {name: receipts[name] for name in sorted(receipts)},
            "inputs": {name: prepared.value for name, prepared in sorted(prepared_inputs.items())},
            "compositions": composition_results,
            "resource_reservations": {**spent, "elapsed_ms": elapsed,
                "admitted_budget": budget, "remaining_budget": remaining},
            "limitations": ["Uncommitted graph diagnostics; no action authority or current assessment.",
                            "Synchronous Python bindings and host callbacks require cooperative completion."]}, _completion=_FINISHED_RUN)

    @staticmethod
    def _check_prepared(prepared, rule, name, declaration, predecessors):
        material = prepared.value
        if material["rule_definition"] != rule.value or material["packet"]["rule"] != rule.reference:
            raise ContractError("E_EVIDENCE_INVALID", "The host preparer changed the selected rule meaning.")
        required = [edge for edge in declaration["edges"] if edge["to"] == name and edge["kind"] == "required"]
        upstream = {canonical_bytes(item["judgment"]["body"]["rule"]): item for item in material["packet"]["upstream"]}
        if set(upstream) != {canonical_bytes(declaration["nodes"][edge["from"]]) for edge in required}:
            raise ContractError("E_EVIDENCE_INVALID", "The prepared input omitted or added an exact prerequisite.")
        for edge in required:
            previous = predecessors[edge["from"]]
            selected = upstream[canonical_bytes(declaration["nodes"][edge["from"]])]
            if (selected["expected_input"] != previous["input"]
                    or any(selected["judgment"].get(key) != value for key, value in previous["judgment"].items())):
                raise ContractError("E_EVIDENCE_INVALID", "The prepared input swapped the validated predecessor/input pair.")
        for mapping in declaration["input_bindings"]:
            if mapping["to"] == name:
                original = predecessors[mapping["from"]]["judgment"]["body"]["semantic_output"]["value"]
                consumed = material["packet"]["proposition"]["value"]
                if canonical_bytes(read_pointer(original, mapping["source_pointer"])) != canonical_bytes(read_pointer(consumed, mapping["target_pointer"])):
                    raise ContractError("E_EVIDENCE_INVALID", "The dependent proposition changed its validated selected output.")
