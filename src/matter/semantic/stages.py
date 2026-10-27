"""MAT-029 explicit fixed-packet batches and gated semantic stages.

No source fetch, provider client, durable retry or qualification issuance is
implemented here. Hosts supply exact packet transforms and original context.
"""

from concurrent.futures import Future, TimeoutError as FutureTimeout
from copy import deepcopy
from datetime import datetime, timedelta
import math
import time

from .._rule_values import FrozenValue, bounded, checked, descriptor, fragment
from ..budgets import BudgetService
from ..canonical import canonical_bytes, canonical_digest
from ..contracts import ContractError
from ..planner import read_pointer
from ..storage import PROJECTION_TYPE, entity_ref, pin
from ..time import compare_times, known_time_key
from .contracts import Batch, BatchResult, PrecisionProfile, _number as _decimal_number, execute_batch
from .packets import PreparedPacket
from .questions import QuestionRegistry
from .rendering import RenderedQuestion


class StageError(ContractError):
    def __init__(self, reason, code="E_POLICY_INVALID"):
        self.reason = reason
        super().__init__(code, "Semantic stage: " + reason + ".")


def _fail(reason, code="E_POLICY_INVALID"):
    raise StageError(reason, code) from None


def _number(value):
    try:
        return _decimal_number(value)
    except ContractError:
        _fail("invalid_acceptance_range")


class StagePlan(FrozenValue):
    """A bounded immutable host plan, validated before any preparation/call."""
    def __init__(self, value, *, questions):
        if not isinstance(questions, QuestionRegistry):
            _fail("question_registry_required")
        data = checked(value, required=("namespace", "id", "version", "stages"))
        for field, kind in (("namespace", "namespace"), ("id", "identifier"), ("version", "text")):
            fragment(data[field], kind)
        stages, names, question_ids = bounded(data["stages"], 128), {}, set()
        if not stages:
            _fail("empty_plan")
        for raw in stages:
            stage = checked(raw, required=("id", "packet_key", "transform", "questions", "requires", "max_candidates"))
            for field in ("id", "packet_key"):
                fragment(stage[field], "identifier")
            fragment(stage["transform"], "component_ref")
            if stage["id"] in names or type(stage["max_candidates"]) is not int or not 0 <= stage["max_candidates"] <= 128:
                _fail("invalid_stage")
            if not stage["questions"]:
                _fail("empty_stage")
            for raw_question in bounded(stage["questions"], 128):
                item = checked(raw_question, required=("id", "specification", "use_if"))
                fragment(item["id"], "identifier")
                questions.resolve(item["specification"])
                if item["id"] in question_ids:
                    _fail("duplicate_question")
                question_ids.add(item["id"])
                if len(question_ids) > 128:
                    _fail("question_budget", "E_BUDGET_EXHAUSTED")
                if item["use_if"] is not None:
                    condition = checked(item["use_if"], required=("pointer", "equals"))
                    if type(condition["pointer"]) is not str or not condition["pointer"].startswith("/"):
                        _fail("invalid_fixed_condition")
            names[stage["id"]] = stage
        graph = {name: set() for name in names}
        for stage in stages:
            seen = set()
            for raw in bounded(stage["requires"], 128):
                edge = checked(raw, required=("stage", "question", "accepted", "require_qualified", "bindings"))
                if edge["stage"] not in names:
                    _fail("missing_prerequisite")
                source = names[edge["stage"]]
                candidates = [item for item in source["questions"] if item["id"] == edge["question"]]
                if not candidates:
                    _fail("missing_prerequisite_outcome")
                if source["id"] == stage["id"] or source["packet_key"] == stage["packet_key"]:
                    _fail("in_batch_sibling_dependency")
                key = (edge["stage"], edge["question"])
                if key in seen or type(edge["require_qualified"]) is not bool:
                    _fail("invalid_prerequisite")
                seen.add(key)
                spec = questions.resolve(candidates[0]["specification"]).value
                accepted = edge["accepted"]
                if spec["primitive"] == "choice":
                    checked(accepted, required=("choices",))
                    options = {item["id"] for item in spec["criteria"]}
                    if not accepted["choices"] or any(item not in options for item in bounded(accepted["choices"], 128)):
                        _fail("missing_prerequisite_outcome")
                else:
                    checked(accepted, required=("minimum", "maximum"))
                    lower, upper = _number(accepted["minimum"]), _number(accepted["maximum"])
                    ceiling = 1 if spec["primitive"] == "proposition_probability" else len(spec["criteria"]) - 1
                    if not 0 <= lower <= upper <= ceiling:
                        _fail("invalid_acceptance_range")
                for raw_binding in bounded(edge["bindings"], 32):
                    binding = checked(raw_binding, required=("answer_pointer", "packet_pointer"))
                    if any(type(value) is not str or not value.startswith("/") for value in binding.values()):
                        _fail("invalid_transform_binding")
                graph[stage["id"]].add(source["id"])
        pending, order = deepcopy(graph), []
        while pending:
            ready = sorted(name for name, parents in pending.items() if not parents)
            if not ready:
                _fail("cycle")
            order.extend(ready)
            for name in ready:
                del pending[name]
            for parents in pending.values():
                parents.difference_update(ready)
        self._freeze({**data, "order": order})

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["version"], value, "matter.semantic-stage-plan.v1")


class StageInput(FrozenValue):
    """Exact host transform output; parent trace refs never imply source authority."""
    def __init__(self, *, packet, rendered_questions, context, transform, parents=(), candidate_count=0):
        if not isinstance(packet, PreparedPacket) or not isinstance(rendered_questions, (list, tuple)):
            _fail("prepared_packet_required")
        if (not rendered_questions or len(rendered_questions) > 128 or
                any(not isinstance(item, RenderedQuestion) for item in rendered_questions)):
            _fail("rendered_questions_required")
        fragment(transform, "component_ref")
        parent_refs = [fragment(item, "component_ref") for item in bounded(list(parents), 128)]
        if type(candidate_count) is not int or not 0 <= candidate_count <= 128:
            _fail("invalid_candidate_count")
        Batch({"schema_version": "1.0", "id": "validation", "scope_id": packet.state["scope_id"],
            "run_id": "validation", "stage_id": "validation", "state": packet.state, "packet_digest": packet.digest,
            "questions": [item.question.value for item in rendered_questions], "context": context})
        self._freeze({"packet": packet.value, "rendered_questions": [item.value for item in rendered_questions],
            "context": context, "transform": transform, "parents": parent_refs, "candidate_count": candidate_count})

    @property
    def packet(self):
        return PreparedPacket(self.value["packet"], _prepared=True)

    @property
    def rendered_questions(self):
        return tuple(RenderedQuestion(item, _factory=True) for item in self.value["rendered_questions"])


class StageRun(FrozenValue):
    @property
    def reference(self):
        return descriptor("matter", self.value["run_id"], "1.0", self.value, "matter.semantic-stage-run.v1")


class StageExecutor:
    def __init__(self, *, questions, budgets, executor, clock, monotonic=time.monotonic, dispatch=None):
        if not isinstance(questions, QuestionRegistry) or not isinstance(budgets, BudgetService) or not callable(clock):
            _fail("installed_ports_required")
        self.questions, self.budgets, self.executor = questions, budgets, executor
        self.clock, self.monotonic, self.dispatch = clock, monotonic, dispatch

    def execute(self, plan, *, prepare, reservation, ceiling, run_id, qualify=None, check_current=None, cancelled=None, precision=None):
        if not isinstance(plan, StagePlan) or not callable(prepare):
            _fail("validated_plan_required")
        if ((precision is not None and not isinstance(precision, PrecisionProfile)) or
                any(callback is not None and not callable(callback) for callback in (qualify, check_current, cancelled))):
            _fail("invalid_execution_ports")
        fragment(run_id, "identifier")
        profile = precision or PrecisionProfile()
        started, tick = fragment(self.clock(), "known_time"), self.monotonic()
        with self.budgets.storage.snapshot() as view:
            allocation = self.budgets.require_committed(view, reservation, as_of=started)
            envelope = self.budgets.resource_envelope(view, reservation, ceiling=ceiling, as_of=started)
        remaining = envelope.remaining_budget
        amounts = allocation["amounts"]
        candidates_left = amounts.get("candidates", 0)
        receipts, inputs, batches, decisions = {}, {}, [], {}
        spent = {"reserved_calls": 0, "reserved_input_bytes": 0, "reserved_output_bytes": 0,
                 "reserved_candidates": 0, "known_invocations": 0, "unobserved_dispatches": 0}
        stages = {item["id"]: item for item in plan.value["stages"]}
        pending = set(stages)

        def gate():
            now = fragment(self.clock(), "known_time")
            if cancelled is not None:
                answer = cancelled()
                if type(answer) is not bool:
                    _fail("invalid_cancellation_result")
                if answer:
                    _fail("cancelled", "E_CANCELLED")
            elapsed = max(0, math.ceil((self.monotonic() - tick) * 1000))
            if elapsed >= envelope.remaining_budget["max_elapsed_ms"] or compare_times(now, started) == -1:
                _fail("elapsed_limit", "E_BUDGET_EXHAUSTED")
            with self.budgets.storage.snapshot() as view:
                self.budgets.require_committed(view, reservation, as_of=now)
            return now

        def trace(name, status, reason, **extra):
            value = {"stage": name, "status": status, "reason": reason, "parents": [], **extra}
            value["reference"] = descriptor("matter.semantic-stages", run_id + ":" + name, "1.0", value,
                                            "matter.semantic-stage-trace.v1")
            receipts[name] = value

        def input_gate(prepared):
            now = gate()
            references = prepared.packet.value["dependencies"]
            targets = []
            with self.budgets.storage.snapshot() as view:
                for ref in references:
                    if ref["scope_id"] != self.budgets.scope_id or pin(view.get(entity_ref(ref))) != ref:
                        _fail("source_changed", "E_DEPENDENCY_STALE")
                    if ref["record_type"] not in {"receipt", "control"} and not (
                            ref["record_type"] == PROJECTION_TYPE and ref["namespace"].startswith("matter.")):
                        targets.append(entity_ref(ref))
                token = allocation["token"]["value"]
                self.budgets.controls.require_current(view, token, capability="assessment", targets=targets or token["targets"], as_of=now)
                self.budgets.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])}, targets)
            if check_current is not None:
                if check_current(prepared, as_of=now) is False:
                    _fail("source_gate_refused", "E_DEPENDENCY_STALE")

        def accepted(edge, consumer, phase):
            parent = receipts[edge["stage"]]
            classification = None
            decision_at = fragment(self.clock(), "known_time")
            def outcome(answer, reason):
                decisions.setdefault(consumer, []).append({"phase": phase, "parent": parent["reference"],
                    "question": edge["question"], "qualification": classification, "as_of": decision_at,
                    "status": "usable" if reason is None else "blocked", "reason": reason})
                return answer, reason
            if parent["status"] != "completed":
                return outcome(None, "prerequisite_" + parent["status"])
            batch_result = batches[parent["batch_index"]]["result"]
            if batch_result["admission"]["primitive_status"] != "valid":
                return outcome(None, "invalid_prerequisite_batch")
            if edge["question"] in parent["ignored_questions"]:
                return outcome(None, "prerequisite_condition_false")
            input_gate(inputs[edge["stage"]])
            decision_at = gate()
            question = next(item for item in stages[edge["stage"]]["questions"] if item["id"] == edge["question"])
            if edge["require_qualified"]:
                if qualify is None:
                    classification = {"status": "unknown", "certificate": None}
                    return outcome(None, "qualification_unknown")
                classification = qualify(question=deepcopy(question), stage_input=inputs[edge["stage"]],
                    batch=deepcopy(batches[parent["batch_index"]]["batch"]), batch_result=deepcopy(batch_result), as_of=decision_at)
                classification = checked(classification, required=("status", "certificate"))
                if classification["status"] not in {"qualified", "unknown", "expired", "revoked", "mismatch"}:
                    _fail("invalid_qualification_classification")
                if classification["certificate"] is not None:
                    fragment(classification["certificate"], "component_ref")
                if classification["status"] != "qualified":
                    return outcome(None, "qualification_unusable")
                fragment(classification["certificate"], "component_ref")
            answer = next(item["answer"] for item in batch_result["diagnostics"] if item["id"] == edge["question"])
            predicate = edge["accepted"]
            if "choices" in predicate:
                okay = answer["choice"] in predicate["choices"]
            else:
                value = answer["probability"] if answer["primitive"] == "proposition_probability" else answer["score"]
                okay = _number(predicate["minimum"]) <= _number(value) <= _number(predicate["maximum"])
            return outcome(deepcopy(answer), None) if okay else outcome(None, "prerequisite_outcome_not_admitted")

        while pending:
            ready = [name for name in plan.value["order"] if name in pending and all(edge["stage"] in receipts for edge in stages[name]["requires"])]
            groups = {}
            for name in ready:
                pending.remove(name)
                stage, parents = stages[name], []
                try:
                    gate()
                    for edge in stage["requires"]:
                        answer, reason = accepted(edge, name, "prepare")
                        if reason:
                            trace(name, "blocked", reason)
                            break
                        parents.append({"stage": edge["stage"], "question": edge["question"],
                            "receipt": receipts[edge["stage"]]["reference"], "answer": answer})
                    if name in receipts:
                        continue
                    if stage["max_candidates"] > candidates_left:
                        _fail("candidate_limit", "E_BUDGET_EXHAUSTED")
                    candidates_left -= stage["max_candidates"]
                    spent["reserved_candidates"] += stage["max_candidates"]
                    prepared = prepare(deepcopy(stage), deepcopy(parents), remaining=deepcopy(remaining))
                    if isinstance(prepared, Future):
                        while True:
                            gate()
                            if prepared.cancelled():
                                _fail("host_future_cancelled", "E_CANCELLED")
                            try:
                                prepared = prepared.result(timeout=0.05)
                                break
                            except FutureTimeout:
                                continue
                    gate()
                    if not isinstance(prepared, StageInput):
                        _fail("stage_input_required")
                    value = prepared.value
                    if (value["transform"] != stage["transform"] or value["parents"] != [item["receipt"] for item in parents] or
                            value["candidate_count"] > stage["max_candidates"] or prepared.packet.state["scope_id"] != self.budgets.scope_id):
                        _fail("transform_or_parent_mismatch")
                    rendered = prepared.rendered_questions
                    if len(rendered) != len(stage["questions"]):
                        _fail("question_inventory_mismatch")
                    ignored = []
                    for declared, actual in zip(stage["questions"], rendered):
                        if actual.question.value["id"] != declared["id"] or actual.manifest["specification"] != declared["specification"]:
                            _fail("question_inventory_mismatch")
                        self.questions.resolve(declared["specification"])
                        condition = declared["use_if"]
                        if condition is not None and canonical_bytes(read_pointer(prepared.packet.state, condition["pointer"])) != canonical_bytes(condition["equals"]):
                            ignored.append(declared["id"])
                    for edge, parent in zip(stage["requires"], parents):
                        if prepared.packet.digest == inputs[edge["stage"]].packet.digest:
                            _fail("dependent_stage_requires_new_packet")
                        for binding in edge["bindings"]:
                            if read_pointer(parent["answer"], binding["answer_pointer"]) != read_pointer(prepared.packet.state, binding["packet_pointer"]):
                                _fail("transform_binding_mismatch")
                    if len(prepared.packet.state["evidence"]) > remaining["max_evidence"]:
                        _fail("per_packet_evidence_limit", "E_BUDGET_EXHAUSTED")
                    input_gate(prepared)
                    inputs[name] = prepared
                    key = canonical_digest({"packet": prepared.packet.digest, "context": value["context"]}, "matter.semantic-batch-group.v1")
                    groups.setdefault(key, []).append((name, prepared, ignored))
                except Exception as error:
                    code = error.code if isinstance(error, ContractError) else "E_POLICY_INVALID"
                    trace(name, "cancelled" if code == "E_CANCELLED" else "blocked",
                          error.reason if isinstance(error, StageError) else "stage_preparation_or_gate_failed", error_code=code,
                          parents=[item["receipt"] for item in parents])
            for group in groups.values():
                names = [item[0] for item in group]
                index = None
                try:
                    gate()
                    for name in names:
                        for edge in stages[name]["requires"]:
                            if accepted(edge, name, "dispatch")[1] is not None:
                                _fail("prerequisite_changed", "E_DEPENDENCY_STALE")
                        input_gate(inputs[name])
                    first = group[0][1]
                    context = first.value["context"]
                    elapsed_left = max(0, envelope.remaining_budget["max_elapsed_ms"] - math.ceil((self.monotonic() - tick) * 1000))
                    now = gate()
                    main, nanos = known_time_key(now)
                    deadline = datetime.fromisoformat(main + "+00:00") + timedelta(milliseconds=int(nanos) // 1000000 + elapsed_left)
                    clipped = {"state": "known", "value": deadline.isoformat(timespec="milliseconds").replace("+00:00", "Z"), "precision": "millisecond"}
                    for limit in (envelope.value["deadline"], clipped):
                        if compare_times(limit, context["deadline"]) == -1:
                            context["deadline"] = limit
                    caps = {"max_calls": 1, "max_input_bytes": context["max_request_bytes"], "max_output_bytes": context["max_response_bytes"]}
                    if any(caps[key] > remaining[key] for key in caps):
                        _fail("remaining_allocation_exhausted", "E_BUDGET_EXHAUSTED")
                    rendered = [item for _, material, _ in group for item in material.rendered_questions]
                    batch = Batch({"schema_version": "1.0", "id": run_id + ":batch:" + str(len(batches)),
                        "scope_id": self.budgets.scope_id, "run_id": run_id, "stage_id": "+".join(names),
                        "state": first.packet.state, "packet_digest": first.packet.digest,
                        "questions": [item.question.value for item in rendered], "context": context})
                    for key, amount in caps.items():
                        remaining[key] -= amount
                    spent["reserved_calls"] += 1
                    spent["reserved_input_bytes"] += caps["max_input_bytes"]
                    spent["reserved_output_bytes"] += caps["max_output_bytes"]
                    if self.dispatch is None:
                        if "access_context" in first.packet.state or context["mode"] not in {"offline_fixture", "recorded_replay"}:
                            _fail("access_dispatch_required", "E_AUTHORITY_REQUIRED")
                        spent["unobserved_dispatches"] += 1
                        result = execute_batch(self.executor, batch, clock=self.clock, precision=profile)
                    else:
                        spent["unobserved_dispatches"] += 1
                        result = self.dispatch(batch, rendered_questions=rendered, clock=self.clock, precision=profile)
                    if not isinstance(result, BatchResult) or result.value["batch_digest"] != batch.digest:
                        _fail("wrong_batch_result")
                    index = len(batches)
                    batches.append({"batch": batch.value, "result": result.value})
                    spent["unobserved_dispatches"] -= 1
                    spent["known_invocations"] += int(result.value["timing"]["called"])
                    gate()
                    for name, _, ignored in group:
                        trace(name, "completed" if result.primitive_valid else "invalid", "batch_admitted" if result.primitive_valid else "batch_invalid",
                            parents=[receipts[edge["stage"]]["reference"] for edge in stages[name]["requires"]],
                            batch_index=index, ignored_questions=ignored)
                except Exception as error:
                    code = error.code if isinstance(error, ContractError) else "E_POLICY_INVALID"
                    for name in names:
                        trace(name, "cancelled" if code == "E_CANCELLED" else "blocked",
                            error.reason if isinstance(error, StageError) else "dispatch_or_consumption_gate_failed", error_code=code,
                            batch_index=index,
                            parents=[receipts[edge["stage"]]["reference"] for edge in stages[name]["requires"]])
        # Preserve earlier raw results, but never leave a path usable after a
        # late source/qualification/control change at final consumption.
        for name in plan.value["order"]:
            if receipts[name]["status"] != "completed":
                continue
            try:
                gate()
                input_gate(inputs[name])
                if any(accepted(edge, name, "final")[1] is not None for edge in stages[name]["requires"]):
                    _fail("prerequisite_changed", "E_DEPENDENCY_STALE")
            except Exception as error:
                trace(name, "blocked", "final_admission_failed", error_code=error.code if isinstance(error, ContractError) else "E_POLICY_INVALID",
                      parents=receipts[name]["parents"], original_trace=receipts[name])
        remaining["max_elapsed_ms"] = max(0, envelope.remaining_budget["max_elapsed_ms"] - max(0, math.ceil((self.monotonic() - tick) * 1000)))
        output = StageRun()
        output._freeze({"schema_version": "1.0", "run_id": run_id, "plan": plan.reference, "reservation": reservation,
            "timing": {"started": started, "completed": fragment(self.clock(), "known_time"),
                       "elapsed_ms": max(0, math.ceil((self.monotonic() - tick) * 1000))},
            "status": "completed" if all(item["status"] == "completed" for item in receipts.values()) else "incomplete",
            "stages": receipts, "gate_decisions": decisions, "inputs": {name: material.value for name, material in inputs.items()},
            "batches": batches, "resources": {**spent,
                "actual_invocations": None if spent["unobserved_dispatches"] else spent["known_invocations"], "remaining_budget": remaining,
                "auxiliary_allocations": {key: value for key, value in amounts.items() if key in {"candidates", "retries", "cost_units"}},
                "remaining_candidates": candidates_left, "automatic_retries": 0, "cost": {"value": None, "reason": "price_basis_not_supplied"}},
            "limitations": ["Uncommitted stage traces; no qualification issuance or action authority.",
                "Host callbacks and synchronous executors require cooperative completion; no implicit retries."]})
        return output
