"""MAT-021 current-state dispatch authorization and independent transport facts.

All irreversible I/O is injected and occurs after the durable authorization
transaction. A local fence cannot retract I/O already past that point.
"""
from copy import deepcopy
from datetime import datetime, timedelta

from ._rule_values import domain, fragment
from .attention import AttentionService, _ENGINE as ATTENTION_ENGINE
from .budgets import BudgetService, REQUEST_EXTENSION as BUDGET_REQUEST, _Reads, _lookup, _value as budget_value
from .canonical import canonical_bytes, canonical_digest, source_digest
from .contracts import ContractError, validate_command, validate_record, validate_result
from .dependencies import capture_dependencies, _manifest_current, registration_ref, require_current_dependency
from .identity_dependencies import _value
from .outbox import (DestinationDefinition, TransportCapabilities, TransportResult, ENGINE, NAMESPACE,
    REQUEST_EXTENSION, RESULT_EXTENSION, OBSERVATION_EXTENSION, authorization_value, equivalent_key, slot_ref, stable, fail)
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times, known_time_key

_UNKNOWN = {"state": "unknown", "reason": "not_applicable"}


def _same(a, b): return canonical_bytes(a) == canonical_bytes(b)


def _pins(values):
    found = {}
    for ref in values:
        fragment(ref, "pinned_ref")
        key = canonical_bytes(entity_ref(ref))
        if key in found and not _same(found[key], ref): fail("E_DEPENDENCY_STALE")
        found[key] = ref
    if len(found) > 4096: fail("E_BUDGET_EXHAUSTED")
    return sorted(found.values(), key=canonical_bytes)


def _public(ref):
    return ref["record_type"] not in {"receipt", "control"} and not (
        ref["record_type"] == PROJECTION_TYPE and ref["namespace"].startswith("matter."))


def _targets(refs):
    return sorted({canonical_bytes(entity_ref(ref)): entity_ref(ref) for ref in refs if _public(ref)}.values(), key=canonical_bytes)


def add_milliseconds(now, amount):
    if type(amount) is not int or not 1 <= amount <= 31536000000: fail("E_POLICY_INVALID")
    main, fraction = known_time_key(now)
    seconds, nanos = divmod(int(fraction) + amount * 1000000, 1000000000)
    try: at = datetime.fromisoformat(main) + timedelta(seconds=seconds)
    except (ValueError, OverflowError): fail("E_POLICY_INVALID")
    return {"state": "known", "value": at.isoformat(timespec="seconds") + ("." + str(nanos).zfill(9) if nanos else "") + "Z",
        "precision": "nanosecond" if nanos else "second"}


class DeliveryService:
    def __init__(self, storage, *, payloads, attention, budgets, controls, destinations, transports, clock):
        if (not isinstance(attention, AttentionService) or not isinstance(budgets, BudgetService) or
                attention.storage is not storage or budgets.storage is not storage or attention.controls is not controls or
                budgets.controls is not controls or payloads.scope_id != storage.scope_id or not callable(clock)):
            fail("E_POLICY_INVALID")
        self.storage, self.scope_id, self.payloads = storage, storage.scope_id, payloads
        self.attention, self.budgets, self.controls, self.clock = attention, budgets, controls, clock
        self.destinations, self.transports = tuple(destinations), tuple(transports)
        self._refusal_key = object()
        if (not self.destinations or len(self.destinations) > 128 or len(self.transports) > 128 or
                any(not isinstance(item, DestinationDefinition) for item in self.destinations) or
                len({canonical_bytes(item.reference) for item in self.destinations}) != len(self.destinations)):
            fail("E_POLICY_INVALID")
        for transport in self.transports:
            if (not isinstance(transport.capabilities, TransportCapabilities) or not callable(transport.send) or
                    (transport.capabilities.value["receipt_lookup"] is not None and not callable(getattr(transport, "lookup", None)))):
                fail("E_POLICY_INVALID")

    def _destination(self, ref):
        matches = [item for item in self.destinations if item.reference == ref]
        if len(matches) != 1: fail("E_AUTHORITY_REQUIRED")
        item = matches[0]
        if item.value["permission_target"]["scope_id"] != self.scope_id: fail("E_SCOPE_FORBIDDEN")
        return item

    def _transport(self, destination):
        matches = [item for item in self.transports if item.capabilities.reference == destination.value["transport"]]
        if len(matches) != 1: fail("E_POLICY_INVALID")
        return matches[0]

    def _intent(self, record):
        record = validate_record(record)
        if (record["namespace"] != NAMESPACE or record["provenance"]["producer"] != ENGINE or
                record["provenance"]["origin"] != "system" or record["body"]["stage"] != "queued"):
            fail()
        value = _value("delivery-intent", record["body"]["details"])
        if record["scope_id"] != self.scope_id or value["scope_id"] != self.scope_id or record["id"] != value["id"]: fail("E_SCOPE_FORBIDDEN")
        return value

    def _decision(self, view, reference):
        record = validate_record(view.get(reference))
        if record["provenance"]["producer"] != ATTENTION_ENGINE or record["scope_id"] != self.scope_id: fail()
        return record, _value("attention-decision", record["body"]["details"])

    def _audit(self, view, value):
        token = _value("control-token", value["token"])
        declared_destination = DestinationDefinition(_value("delivery-destination", value["destination_definition"]))
        if declared_destination.reference != value["destination"]: fail()
        targets = _targets([*value["dependencies"], declared_destination.value["permission_target"], *token["targets"]])
        self.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])}, targets)
        access = self.attention.access
        if access is not None:
            access.require_history(view, value["access_context"], references=[ref for ref in value["dependencies"] if _public(ref)])
        elif value["access_context"] is not None: fail("E_AUTHORITY_REQUIRED")

    def _guards(self, view, value, *, original=True):
        now = fragment(self.clock(), "known_time")
        token = _value("control-token", value["token"])
        record, decision = self._decision(view, value["decision"])
        destination = self._destination(value["destination"])
        self._transport(destination)
        if destination.value["audience"] != decision["audience"]: fail("E_SCOPE_FORBIDDEN")
        view.get(destination.value["permission_target"])
        command = _value("operation-command", value["attention_command"])
        request = self.attention._request(command)
        normalized = {**request, "baseline": decision["request"]["baseline"]}
        if not _same(normalized, decision["request"]): fail()
        if (command["body"]["matter"] != decision["matter"] or command["body"]["purpose"] != decision["purpose"] or
                command["body"].get("audience") != decision["audience"] or request["action"] != "evaluate"):
            fail()
        state = self.attention._inspect(_Reads(view, self.scope_id), command, decision["request"], now, original=False)
        transport = self._transport(destination)
        if not any(item["producer"] == transport.capabilities.value["producer"] and item["outcome"] == transport.capabilities.value["success_milestone"]
                for item in state["policy"].value["delivery_producers"]): fail("E_AUTHORITY_REQUIRED")
        if state["previous"] is None or _value("attention-current", state["previous"]["value"])["decision"] != pin(record): fail("E_DEPENDENCY_STALE")
        require_current_dependency(view, registration_ref(state["previous"]), as_of=now, controls=self.controls)
        if state["decision"]["treatment"] != "quiet" and (
                state["decision"]["treatment"] != decision["treatment"] or not _same(state["material"], decision["material"])):
            fail("E_DEPENDENCY_STALE")
        if original:
            if pin(state["baseline_record"]) != value["baseline"] or equivalent_key(decision, state["baseline"]) != value["equivalence_key"]:
                fail("E_DEPENDENCY_STALE")
            _manifest_current(view, value["manifest"], now, self.controls)
            if compare_times(now, value["expires_at"]) >= 0: fail("E_BUDGET_EXHAUSTED")
        targets = _targets([*[pin(item) for item in view.records.values()], *token["targets"], destination.value["permission_target"]])
        self.controls.require_current(view, token, capability="delivery", targets=targets, as_of=now)
        self.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])}, targets)
        if self.attention.access is not None:
            context = self.attention.access.require_current(view, value["access_context"],
                references=[pin(item) for item in view.records.values() if _public(item)], audience=decision["audience"])
            if context.value["token"] != token: fail("E_AUTHORITY_REQUIRED")
        elif value["access_context"] is not None: fail("E_AUTHORITY_REQUIRED")
        return state, token, destination

    def _header(self, operation, command_id, key, token, body):
        return {"schema_version": "1.0", "operation": operation, "command_id": command_id, "idempotency_key": key,
            "scope_id": self.scope_id, "actor": token["actor"], "authority": entity_ref(token["authority"]), "expected_revisions": [], "body": body}

    def _request(self, action, **fields):
        value = {"schema_version": "1.0", "action": action, "intent": None, "intent_payload": None, "expected_slot": None,
            "lease": None, "attempt_id": None, "authorization": None, "observation": None, "budget_command": None,
            "authorization_proof": None, "observation_kind": None, "withheld_reason": None, "evidence": [], "outcome_producer": None, "captured_at": fragment(self.clock(), "known_time"), **fields}
        return domain("delivery-request", value)

    def _result(self, result, status, *, intent=None, slot=None, lease=None, authorization=None, observation=None, reason="delivery:recorded"):
        result.setdefault("extensions", {})[RESULT_EXTENSION] = domain("delivery-result", {"schema_version": "1.0", "status": status,
            "intent": intent, "slot": slot, "lease": lease, "authorization": authorization, "observation": observation, "reason": reason})
        return validate_result(result)

    def _withheld(self, tx, reason, at=None, **fields):
        return self._result(tx.success("withheld", {"reasons": [reason], "reconsider_at": at or _UNKNOWN}), "withheld", reason="delivery:" + reason, **fields)

    def _checked(self, command):
        command = validate_command(command)
        if command["scope_id"] != self.scope_id or command["operation"] not in {"prepare_delivery", "dispatch"}: fail("E_SCOPE_FORBIDDEN")
        request = _value("delivery-request", command.get("extensions", {}).get(REQUEST_EXTENSION))
        return command, request

    def _collect(self, command, inspect):
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            inspect(view)
            command["expected_revisions"] = sorted([pin(item) for item in view.records.values()], key=canonical_bytes)
        return validate_command(command)

    def prepare(self, command, *, decision, attention_command, token, destination, content, budget, amounts, expires_at, access_context=None):
        command = validate_command(command)
        if command["operation"] != "prepare_delivery" or command["scope_id"] != self.scope_id or REQUEST_EXTENSION in command.get("extensions", {}): fail()
        domain("control-token", token)
        if command["actor"] != token["actor"] or command["authority"] != entity_ref(token["authority"]): fail("E_AUTHORITY_REQUIRED")
        if type(content) is not bytes or not 1 <= len(content) <= 65536: fail("E_BUDGET_EXHAUSTED")
        now = fragment(self.clock(), "known_time")
        if compare_times(fragment(expires_at, "known_time"), now) <= 0: fail("E_BUDGET_EXHAUSTED")
        destination = self._destination(getattr(destination, "reference", destination))
        transport = self._transport(destination)
        selected_budget = self.budgets._definition(getattr(budget, "reference", budget))
        if selected_budget.value["kind"] != "attention" or amounts.get("deliveries") != 1: fail("E_POLICY_INVALID")
        value = {"schema_version": "1.0", "scope_id": self.scope_id, "id": command["command_id"], "decision": fragment(decision, "receipt_dependency"),
            "attention_command": domain("operation-command", validate_command(attention_command)), "destination": destination.reference,
            "destination_definition": domain("delivery-destination", destination.value),
            "token": domain("control-token", token), "access_context": deepcopy(getattr(access_context, "value", access_context)),
            "created_at": now, "expires_at": expires_at, "budget": selected_budget.reference, "amounts": amounts}
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            state, _, _ = self._guards(view, value, original=False)
            _, declared = self._decision(view, decision)
            baseline = state["baseline"]
            key = equivalent_key(declared, baseline)
            delivery_key = "delivery-" + canonical_digest({"delta": key, "destination": stable(destination.reference),
                "transport": transport.capabilities.reference}, "matter.delivery-key.v1")
            manifest = capture_dependencies(view, scope_id=self.scope_id, as_of=now,
                positive=_pins([pin(state["assessment"]), pin(state["lane"]), pin(state["previous"]), pin(state["baseline_record"]),
                    pin(view.get(destination.value["permission_target"]))]), contexts=state["contexts"],
                time_conditions=[*state["conditions"], {"condition": ENGINE, "next_check_at": expires_at, "expires_at": expires_at}],
                control_token=token, controls=self.controls)
            value.update(baseline=pin(state["baseline_record"]), baseline_receipt=None if baseline is None else baseline["delivery_receipt"],
                equivalence_key=key, delivery_key=delivery_key, manifest=manifest.value, dependency_manifest_digest=manifest.digest,
                dependencies=_pins([*manifest.value["positive"], *manifest.value["contexts"], *manifest.value["negative_registrations"], *manifest.value["candidate_sets"]]))
        digest = self.payloads.put(content)
        value.update(content_digest=digest, content={"digest": digest, "byte_length": len(content), "media_type": "text/plain",
            "locator": {"kind": "whole_artifact", "uri": "urn:matter:delivery-content:" + digest},
            "availability": {"status": "available", "checked_at": now}})
        domain("delivery-intent", value)
        reservation_id = "delivery-" + canonical_digest({"intent": value["id"], "delta": key}, "matter.delivery-reservation.v1")
        inner = self._header("reserve_budget", "hold-" + reservation_id, "hold-" + reservation_id, token,
            {"budget": selected_budget.reference, "reservation_id": reservation_id, "amounts": amounts,
                "expires_at": expires_at, "targets": token["targets"]})
        inner = self.budgets.prepare(inner, token=token)
        body = {"assessment": declared["assessment"], "audience": declared["audience"], "purpose": declared["purpose"],
            "baseline": value["baseline_receipt"], "control_epoch": token["control_epoch"], "treatment": declared["treatment"],
            "content_digest": digest, "dependency_manifest_digest": manifest.digest, "delivery_key": delivery_key}
        prepared = {**command, "body": body, "extensions": {**command.get("extensions", {}), REQUEST_EXTENSION: self._request("queue",
            intent_payload=domain("delivery-intent", value), budget_command=domain("operation-command", inner))}}
        def inspect(view):
            self._guards(view, value)
            old = _lookup(view, slot_ref(self.scope_id, key))
            prepared["extensions"][REQUEST_EXTENSION]["value"]["expected_slot"] = None if old is None else pin(old)
            for ref in inner["expected_revisions"]:
                if pin(view.get(entity_ref(ref))) != ref: fail("E_DEPENDENCY_STALE")
        return self._collect(prepared, inspect)

    def _intent_input(self, value, operation_id):
        return {"schema_version": "1.0", "record_type": "receipt", "scope_id": self.scope_id, "namespace": NAMESPACE, "id": value["id"],
            "provenance": {"origin": "system", "producer": ENGINE, "recorded_at": value["created_at"], "parents": value["dependencies"]},
            "body": {"stage": "queued", "operation_id": operation_id, "recorded_at": value["created_at"], "outcome": "matter:delivery_queued",
                "evidence": value["dependencies"], "details": domain("delivery-intent", value)}}

    def _slot(self, view, value):
        row = _lookup(view, slot_ref(self.scope_id, value["equivalence_key"]))
        return row, None if row is None else _value("delivery-slot", row["value"])

    def _queue(self, tx, command, request):
        value = _value("delivery-intent", request["intent_payload"])
        token = _value("control-token", value["token"])
        # These checks precede quiet/duplicate early returns as well as writes.
        if command["actor"] != token["actor"] or command["authority"] != entity_ref(token["authority"]): fail("E_AUTHORITY_REQUIRED")
        definition = self.budgets._definition(value["budget"])
        if (definition.value["kind"] != "attention" or value["amounts"].get("deliveries") != 1 or
                set(value["amounts"]) != set(definition.value["limits"])): fail("E_POLICY_INVALID")
        inner = _value("operation-command", request["budget_command"])
        inner_request = _value("budget-request", inner.get("extensions", {}).get(BUDGET_REQUEST))
        reservation_id = "delivery-" + canonical_digest({"intent": value["id"], "delta": value["equivalence_key"]}, "matter.delivery-reservation.v1")
        expected_reserve = {"budget": value["budget"], "reservation_id": reservation_id, "amounts": value["amounts"],
            "expires_at": value["expires_at"], "targets": token["targets"]}
        if (inner["operation"] != "reserve_budget" or not _same(inner["body"], expected_reserve) or
                not _same(inner_request["token"], value["token"])): fail("E_EVIDENCE_INVALID")
        view = _Reads(tx, self.scope_id)
        state, token, _ = self._guards(view, value)
        _, decision = self._decision(view, value["decision"])
        expected_body = {"assessment": decision["assessment"], "audience": decision["audience"], "purpose": decision["purpose"],
            "baseline": value["baseline_receipt"], "control_epoch": token["control_epoch"], "treatment": decision["treatment"],
            "content_digest": value["content_digest"], "dependency_manifest_digest": value["dependency_manifest_digest"], "delivery_key": value["delivery_key"]}
        if not _same(command["body"], expected_body): fail()
        row, slot = self._slot(view, value)
        if (None if row is None else pin(row)) != request["expected_slot"]: fail("E_DEPENDENCY_STALE")
        if state["decision"]["treatment"] == "quiet":
            reasons = [r for r in state["decision"]["reasons"] if r in {"no_material_change", "already_delivered", "recovery_established", "handled_by_owner", "disposition_applies", "deferred_until_checkpoint", "insufficient_evidence", "incomplete_coverage", "no_active_purpose"}]
            return self._withheld(tx, (reasons or ["stale_assessment"])[0])
        if slot is not None and slot["state"] not in {"failed", "withheld"}:
            return self._withheld(tx, "already_delivered" if slot["state"] == "delivered" else "deferred_until_checkpoint", intent=slot["intent"], slot=pin(row))
        staged = self.budgets.stage(tx, inner)
        if staged["outcome"] != "reserved": return self._withheld(tx, "budget_limited", staged["body"]["next_eligible_at"])
        stored = tx.insert(self._intent_input(value, command["command_id"]))
        slot = {"schema_version": "1.0", "intent": pin(stored), "equivalence_key": value["equivalence_key"], "delivery_key": value["delivery_key"],
            "state": "queued", "lease": None, "reservation": staged["body"]["reservation"], "authorization": None,
            "last_observation": None, "fence": 0 if slot is None else slot["fence"] + 1}
        current = tx.put_projection(slot_ref(self.scope_id, value["equivalence_key"]), domain("delivery-slot", slot))
        return self._result(tx.success("ready", {"intent": pin(stored), "delivery_key": value["delivery_key"]}), "queued", intent=pin(stored), slot=pin(current))

    def execute(self, command, *, _claimed=None, _local_refusal=None):
        command, request = self._checked(command)
        def handler(tx):
            try:
                if request["action"] == "queue": return self._queue(tx, command, request)
                return self._stage(tx, command, request, claimed=_claimed, local_refusal=_local_refusal is self._refusal_key)
            except StorageError as error:
                if error.code == "E_REVISION_CONFLICT": fail("E_DEPENDENCY_STALE")
                raise
        def audit(view):
            value = _value("delivery-intent", request["intent_payload"]) if request["action"] == "queue" else self._intent(view.get(request["intent"]))
            self._audit(view, value)
        return self.storage.execute(command, handler, replay_guard=audit, dependency_error_code="E_DEPENDENCY_STALE")

    def _attempt_ref(self, authorization):
        return {"scope_id": self.scope_id, "namespace": NAMESPACE + ".attempts", "record_type": PROJECTION_TYPE, "id": authorization["id"]}

    def _maintenance(self, action, intent, token, *, command_id, idempotency_key, lease=None, attempt_id=None, budget_command=None):
        domain("control-token", token)
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            record = view.get(intent); value = self._intent(record)
            if not _same(_value("control-token", value["token"]), token): fail("E_AUTHORITY_REQUIRED")
            self._audit(view, value)
            _, slot = self._slot(view, value)
            if slot is None or slot["intent"] != pin(record): fail("E_DEPENDENCY_STALE")
            _, decision = self._decision(view, value["decision"])
        identity = command_id
        body = {"intent": intent, "lease_token": "unclaimed" if lease is None else lease["token"], "control_epoch": token["control_epoch"],
            "delivery_key": value["delivery_key"], "audience": decision["audience"], "baseline": value["baseline_receipt"]}
        command = self._header("dispatch", identity, idempotency_key, token, body)
        command["extensions"] = {REQUEST_EXTENSION: self._request(action, intent=intent, lease=lease, attempt_id=attempt_id,
            budget_command=None if budget_command is None else domain("operation-command", budget_command))}
        return command, value

    def prepare_claim(self, intent, *, token, worker, lease_ms, command_id, idempotency_key):
        fragment(worker, "identifier")
        if type(lease_ms) is not int or not 1 <= lease_ms <= 300000: fail("E_POLICY_INVALID")
        command, value = self._maintenance("claim", intent, token, command_id=command_id, idempotency_key=idempotency_key)
        request = command["extensions"][REQUEST_EXTENSION]["value"]
        def inspect(view):
            view.get(intent)
            self._guards(view, value)
            row, slot = self._slot(view, value)
            if slot is None or slot["intent"] != intent: fail("E_DEPENDENCY_STALE")
            if slot["state"] in {"queued", "leased"}:
                hold = budget_value(view.get(slot["reservation"]), "budget-reservation")
                if hold["status"] != "held" or hold["token"] != value["token"]: fail("E_DEPENDENCY_STALE")
            fence = slot["fence"] + 1
            now = fragment(self.clock(), "known_time")
            until = add_milliseconds(now, lease_ms)
            if compare_times(until, value["expires_at"]) > 0: until = value["expires_at"]
            request.update(expected_slot=pin(row), lease={"worker": worker, "token": "lease-" + canonical_digest(
                {"slot": entity_ref(row), "fence": fence, "worker": worker, "command": command_id}, "matter.delivery-lease.v1"),
                "fence": fence, "expires_at": until})
            command["body"]["lease_token"] = request["lease"]["token"]
        return self._collect(command, inspect)

    def prepare_authorize(self, intent, *, token, lease, attempt_id, command_id, idempotency_key):
        fragment(attempt_id, "identifier")
        command, value = self._maintenance("authorize", intent, token, command_id=command_id, idempotency_key=idempotency_key,
            lease=lease, attempt_id=attempt_id)
        with self.storage.snapshot() as view:
            row, slot = self._slot(view, value)
            if slot is None or slot["reservation"] is None: fail("E_DEPENDENCY_STALE")
            reservation = slot["reservation"]
        budget = self._header("settle_budget", "commit-" + command_id, "commit-" + idempotency_key, token,
            {"reservation": reservation, "action": "commit"})
        budget = self.budgets.prepare(budget, token=token)
        request = command["extensions"][REQUEST_EXTENSION]["value"]
        request["budget_command"] = domain("operation-command", budget)
        def inspect(view):
            view.get(intent)
            self._guards(view, value)
            row, slot = self._slot(view, value)
            self._lease(slot, lease)
            request["expected_slot"] = pin(row)
            for ref in budget["expected_revisions"]:
                if pin(view.get(entity_ref(ref))) != ref: fail("E_DEPENDENCY_STALE")
        return self._collect(command, inspect)

    def prepare_withhold(self, intent, *, token, reason, command_id, idempotency_key):
        """Withdraw unused work under its original identity, without renewal."""
        fragment(reason, "quiet_reason")
        command, value = self._maintenance("withhold", intent, token, command_id=command_id, idempotency_key=idempotency_key)
        with self.storage.snapshot() as view:
            _, slot = self._slot(view, value)
            if slot["authorization"] is not None or slot["state"] not in {"queued", "leased"}: fail("E_DELIVERY_UNKNOWN")
            reservation = pin(view.get(entity_ref(slot["reservation"])))
        budget = self._header("settle_budget", "release-" + command_id, "release-" + idempotency_key, token,
            {"reservation": reservation, "action": "release"})
        budget = self.budgets.prepare(budget, token=token)
        request = command["extensions"][REQUEST_EXTENSION]["value"]
        request.update(withheld_reason=reason, budget_command=domain("operation-command", budget))
        def inspect(view):
            view.get(intent); view.get(value["decision"]); self._audit(view, value)
            row, slot = self._slot(view, value)
            if slot["authorization"] is not None or slot["state"] not in {"queued", "leased"}: fail("E_DELIVERY_UNKNOWN")
            request["expected_slot"] = pin(row)
            for ref in budget["expected_revisions"]:
                if pin(view.get(entity_ref(ref))) != ref: fail("E_DEPENDENCY_STALE")
        return self._collect(command, inspect)

    def _lease(self, slot, lease):
        if (slot is None or slot["lease"] is None or not _same(slot["lease"], lease) or slot["fence"] != lease["fence"] or
                compare_times(self.clock(), lease["expires_at"]) >= 0): fail("E_DEPENDENCY_STALE")

    def _binding(self, view, command, request):
        record = view.get(request["intent"]); value = self._intent(record)
        token = _value("control-token", value["token"])
        _, decision = self._decision(view, value["decision"])
        if command["actor"] != token["actor"] or command["authority"] != entity_ref(token["authority"]): fail("E_AUTHORITY_REQUIRED")
        body = {"intent": pin(record), "lease_token": "unclaimed" if request["lease"] is None else request["lease"]["token"],
            "control_epoch": token["control_epoch"], "delivery_key": value["delivery_key"], "audience": decision["audience"], "baseline": value["baseline_receipt"]}
        if not _same(command["body"], body): fail()
        return record, value, token

    def _stage(self, tx, command, request, *, claimed=None, local_refusal=False):
        view = _Reads(tx, self.scope_id)
        record, value, token = self._binding(view, command, request)
        if request["action"] == "observe": return self._observe(tx, command, request, value, local_refusal=local_refusal)
        row, slot = self._slot(view, value)
        if slot is None or slot["intent"] != pin(record): fail("E_DEPENDENCY_STALE")
        if request["expected_slot"] != pin(row): fail("E_DEPENDENCY_STALE")
        if request["action"] == "withhold":
            self._audit(view, value)
            if slot["authorization"] is not None or slot["state"] not in {"queued", "leased"}: fail("E_DELIVERY_UNKNOWN")
            fragment(request["withheld_reason"], "quiet_reason")
            inner = _value("operation-command", request["budget_command"])
            inner_request = _value("budget-request", inner.get("extensions", {}).get(BUDGET_REQUEST))
            allocation_record = view.get(entity_ref(slot["reservation"]))
            allocation = budget_value(allocation_record, "budget-reservation")
            expected = {"budget": value["budget"], "amounts": value["amounts"], "targets": token["targets"],
                "expires_at": value["expires_at"], "token": value["token"]}
            if (allocation["status"] not in {"held", "released", "expired"} or
                    any(not _same(allocation[key], item) for key, item in expected.items()) or
                    inner["operation"] != "settle_budget" or
                    not _same(inner["body"], {"reservation": pin(allocation_record), "action": "release"}) or
                    not _same(inner_request["token"], value["token"])): fail("E_EVIDENCE_INVALID")
            staged = self.budgets.stage(tx, inner)
            if staged["outcome"] not in {"released", "expired", "unchanged"}: fail("E_EVIDENCE_INVALID")
            now = fragment(self.clock(), "known_time")
            reason = "delivery:" + request["withheld_reason"]
            observation = tx.insert({"schema_version": "1.0", "record_type": "receipt", "scope_id": self.scope_id,
                "namespace": NAMESPACE, "id": "withdraw-" + canonical_digest({"intent": pin(record), "slot": pin(row),
                    "key": command["idempotency_key"]}, "matter.delivery-withdrawal.v1"),
                "provenance": {"origin": "system", "producer": ENGINE, "recorded_at": now, "parents": [pin(record)]},
                "body": {"stage": "withheld", "operation_id": command["command_id"], "recorded_at": now,
                    "outcome": "matter:delivery_withheld", "evidence": [pin(record)],
                    "details": domain("delivery-result", {"schema_version": "1.0", "status": "withheld", "intent": pin(record),
                        "slot": pin(row), "lease": None, "authorization": None, "observation": None, "reason": reason})}})
            slot.update(state="withheld", lease=None, fence=slot["fence"] + 1,
                reservation=staged["body"]["reservation"], last_observation=pin(observation))
            current = tx.put_projection(entity_ref(row), domain("delivery-slot", slot))
            return self._withheld(tx, request["withheld_reason"], intent=pin(record), slot=pin(current), observation=pin(observation))
        state, _, destination = self._guards(view, value)
        if state["decision"]["treatment"] == "quiet": return self._withheld(tx, "stale_assessment", intent=pin(record), slot=pin(row))
        now = fragment(self.clock(), "known_time")
        if request["action"] == "claim":
            if slot["state"] == "delivered": return self._withheld(tx, "already_delivered", intent=pin(record), slot=pin(row))
            if slot["state"] in {"authorized", "delivery_unknown"}:
                return self._withheld(tx, "deferred_until_checkpoint", intent=pin(record), slot=pin(row), authorization=slot["authorization"])
            if slot["state"] not in {"queued", "leased"}: fail("E_DEPENDENCY_STALE")
            if slot["state"] == "leased" and compare_times(now, slot["lease"]["expires_at"]) < 0:
                return self._withheld(tx, "deferred_until_checkpoint", slot["lease"]["expires_at"], intent=pin(record), slot=pin(row))
            lease = request["lease"]
            if lease["fence"] != slot["fence"] + 1 or compare_times(now, lease["expires_at"]) >= 0: fail("E_DEPENDENCY_STALE")
            hold = budget_value(view.get(slot["reservation"]), "budget-reservation")
            if hold["status"] != "held" or hold["token"] != value["token"]: fail("E_DEPENDENCY_STALE")
            slot.update(state="leased", lease=lease, fence=lease["fence"])
            current = tx.put_projection(entity_ref(row), domain("delivery-slot", slot))
            return self._result(tx.success("leased", {"intent": pin(record), "lease_token": lease["token"], "fence": lease["fence"],
                "expires_at": lease["expires_at"]}), "leased", intent=pin(record), slot=pin(current), lease=lease)
        if request["action"] != "authorize": fail("E_SCHEMA_INVALID")
        self._lease(slot, request["lease"])
        if slot["state"] != "leased": fail("E_DEPENDENCY_STALE")
        inner = _value("operation-command", request["budget_command"])
        inner_request = _value("budget-request", inner.get("extensions", {}).get(BUDGET_REQUEST))
        if (inner["operation"] != "settle_budget" or
                not _same(inner["body"], {"reservation": slot["reservation"], "action": "commit"}) or
                not _same(inner_request["token"], value["token"])): fail("E_EVIDENCE_INVALID")
        allocation = budget_value(view.get(slot["reservation"]), "budget-reservation")
        expected_allocation = {"budget": value["budget"], "amounts": value["amounts"], "targets": token["targets"],
            "expires_at": value["expires_at"], "token": value["token"]}
        if allocation["status"] != "held" or any(not _same(allocation[key], item) for key, item in expected_allocation.items()): fail("E_EVIDENCE_INVALID")
        staged = self.budgets.stage(tx, inner)
        if staged["outcome"] != "committed": fail("E_BUDGET_EXHAUSTED")
        transport = self._transport(destination)
        if not _same(staged["body"]["reservation"], pin(tx.get(staged["body"]["reservation"]))): fail()
        # Sample at the final authorization point, after all staged work. The
        # entire transaction rolls back if the host deadline crossed meanwhile.
        now = fragment(self.clock(), "known_time")
        self._lease(slot, request["lease"])
        if compare_times(now, value["expires_at"]) >= 0: fail("E_BUDGET_EXHAUSTED")
        self._guards(view, value)
        self.controls.authorize_dispatch(view, token, targets=_targets([*[pin(item) for item in view.records.values()], *token["targets"]]))
        _, decision = self._decision(view, value["decision"])
        authorization = {"schema_version": "1.0", "scope_id": self.scope_id, "intent": pin(record), "decision": value["decision"],
            "assessment": decision["assessment"], "matter": entity_ref(decision["matter"]), "purpose": decision["purpose"], "audience": decision["audience"],
            "material_contract": decision["material_contract"], "material_digest": decision["material_digest"], "baseline": value["baseline"],
            "destination": value["destination"], "permission_target": destination.value["permission_target"], "transport": transport.capabilities.reference,
            "producer": transport.capabilities.value["producer"], "milestone": transport.capabilities.value["success_milestone"],
            "delivery_key": value["delivery_key"], "content_digest": value["content_digest"], "control_token": value["token"],
            "access_context": value["access_context"], "lease": request["lease"], "attention_budget": staged["body"]["reservation"],
            "authorized_at": now, "dependencies": value["dependencies"], "dependency_manifest_digest": value["dependency_manifest_digest"],
            "equivalence_key": value["equivalence_key"], "authorization_key": command["idempotency_key"]}
        identity = "authorize-" + canonical_digest({"intent": pin(record), "lease": request["lease"], "attempt": request["attempt_id"]}, "matter.delivery-attempt.v1")
        auth = tx.insert({"schema_version": "1.0", "record_type": "receipt", "scope_id": self.scope_id, "namespace": NAMESPACE, "id": identity,
            "provenance": {"origin": "system", "producer": ENGINE, "recorded_at": now,
                "parents": _pins([pin(record), value["decision"], decision["assessment"], staged["body"]["reservation"]])},
            "body": {"stage": "operation", "operation_id": command["command_id"], "recorded_at": now, "outcome": "matter:delivery_authorized",
                "evidence": value["dependencies"], "details": domain("delivery-authorization", authorization)}})
        tx.put_projection(self._attempt_ref(auth), domain("delivery-attempt", {"authorization": pin(auth), "status": "authorized", "current": None, "completion_key": None, "observations": []}))
        slot.update(state="authorized", reservation=staged["body"]["reservation"], authorization=pin(auth))
        current = tx.put_projection(entity_ref(row), domain("delivery-slot", slot))
        if claimed is not None: claimed.append(pin(auth))
        return self._result(tx.success("authorized", {"authorization": pin(auth), "attention_budget": staged["body"]["reservation"]}), "authorized",
            intent=pin(record), slot=pin(current), lease=request["lease"], authorization=pin(auth))

    def _observation_input(self, authorization, auth, observation, evidence, *, operation_id, producer):
        now = observation["observed_at"]
        status = observation["status"]
        if status == "delivered":
            at = observation["reported_at"] if observation["ordering"] == "transport_time" else now
            details = domain("attention-delivery-milestone", {"schema_version": "1.0", "decision": auth["decision"],
                "assessment": auth["assessment"], "matter": auth["matter"], "purpose": auth["purpose"], "audience": auth["audience"],
                "material_digest": auth["material_digest"], "milestone": "delivered", "delivered_at": at})
        else:
            details = domain("delivery-observation", observation)
        identity = "observation-" + canonical_digest({"authorization": authorization, "value": observation, "evidence": evidence}, "matter.delivery-observation.v1")
        stage = status if status in {"delivered", "delivery_unknown", "consumed", "acted_on", "outcome_verified", "useful"} else "operation"
        return {"schema_version": "1.0", "scope_id": self.scope_id, "namespace": NAMESPACE, "record_type": "receipt", "id": identity,
            "provenance": {"origin": "host" if producer != ENGINE else "system", "producer": producer, "recorded_at": now,
                "parents": _pins([authorization, auth["intent"], *evidence])},
            "body": {"stage": stage, "operation_id": operation_id, "recorded_at": now,
                "outcome": auth["milestone"] if status == "delivered" else "matter:delivery_" + status,
                "evidence": _pins([authorization, *evidence]), "details": details},
            "extensions": {OBSERVATION_EXTENSION: domain("delivery-observation", observation)}}

    def _eligibility_observation(self, value):
        checked_at = fragment(self.clock(), "known_time")
        try:
            with self.storage.snapshot() as snapshot:
                self._guards(_Reads(snapshot, self.scope_id), value)
            return {"status": "current", "error_code": None, "checked_at": checked_at}
        except ContractError as error:
            return {"status": "invalidated", "error_code": error.code, "checked_at": checked_at}

    def prepare_observation(self, authorization, result, *, command_id, idempotency_key, kind="transport", evidence=(), producer=None):
        # Trusted adapter/factual-write boundary. No current work token is
        # recaptured or required to report what an authorized transport did.
        if not isinstance(result, TransportResult): fail("E_SCHEMA_INVALID")
        if kind != "transport": fail("E_AUTHORITY_REQUIRED")
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            auth_record = view.get(authorization); auth = authorization_value(auth_record)
            value = self._intent(view.get(auth["intent"]))
            token = _value("control-token", value["token"])
            journal = snapshot.command_receipt(auth["authorization_key"])
            proof = {"command": journal["command"], "result": journal["result"]}
        now = fragment(self.clock(), "known_time")
        data = result.value
        status = data["status"]
        if status == "not_found": status = "delivery_unknown"
        if status == "delivered" and data["milestone"] != auth["milestone"]: fail()
        observation = {"schema_version": "1.0", "authorization": authorization, "intent": auth["intent"],
            "destination": auth["destination"], "transport": auth["transport"], "delivery_key": auth["delivery_key"], "status": status,
            "receipt_id": data["receipt_id"], "reported_at": data["at"], "observed_at": now,
            "ordering": "transport_time" if data["at"]["state"] == "known" and
                compare_times(auth["authorized_at"], data["at"]) <= 0 and compare_times(data["at"], now) <= 0 else "unavailable", "reason": data["reason"],
            "eligibility_at_observation": self._eligibility_observation(value)}
        command, _ = self._maintenance_for_fact(auth, value, token, command_id, idempotency_key)
        request = command["extensions"][REQUEST_EXTENSION]["value"]
        request.update(authorization=authorization, authorization_proof=proof, observation=domain("delivery-observation", observation),
            observation_kind=kind, evidence=_pins(evidence), outcome_producer=producer)
        def inspect(view):
            self._fact_reads(view, authorization, auth, value, evidence)
            row, _ = self._slot(view, value)
            request["expected_slot"] = None if row is None else pin(row)
        return self._collect(command, inspect)

    def _maintenance_for_fact(self, auth, value, token, command_id, key):
        body = {"intent": auth["intent"], "lease_token": auth["lease"]["token"], "control_epoch": token["control_epoch"],
            "delivery_key": auth["delivery_key"], "audience": auth["audience"], "baseline": value["baseline_receipt"]}
        command = self._header("dispatch", command_id, key, token, body)
        command["extensions"] = {REQUEST_EXTENSION: self._request("observe", intent=auth["intent"], lease=auth["lease"])}
        return command, value

    def _fact_reads(self, view, authorization, auth, value, evidence):
        view.get(authorization)
        view.get(auth["intent"])
        view.get(auth["decision"])
        view.get(auth["assessment"])
        view.get(auth["attention_budget"])
        auth_record = view.get(authorization)
        view.get(auth_record["creation_receipt"])
        _lookup(view, self._attempt_ref(authorization))
        self._slot(view, value)
        _lookup(view, entity_ref(auth["baseline"]))
        for ref in evidence: view.get(ref)

    def _observe(self, tx, command, request, value, *, local_refusal=False):
        auth_record = tx.get(request["authorization"]); auth = authorization_value(auth_record)
        if auth["intent"] != request["intent"] or not _same(auth["lease"], request["lease"]): fail()
        observation = _value("delivery-observation", request["observation"])
        if (observation["authorization"] != pin(auth_record) or observation["intent"] != auth["intent"] or
                any(observation[key] != auth[key] for key in ("destination", "transport", "delivery_key")) or
                compare_times(observation["observed_at"], self.clock()) > 0 or compare_times(observation["observed_at"], auth["authorized_at"]) < 0): fail()
        if observation["ordering"] == "transport_time" and (observation["reported_at"]["state"] != "known" or
                compare_times(observation["reported_at"], observation["observed_at"]) > 0 or
                compare_times(observation["reported_at"], auth["authorized_at"]) < 0): fail()
        attempt_record = tx.get(self._attempt_ref(auth_record)); attempt = _value("delivery-attempt", attempt_record["value"])
        if attempt["authorization"] != pin(auth_record): fail()
        status = observation["status"]
        producer = auth["producer"] if request["outcome_producer"] is None else request["outcome_producer"]
        if request["observation_kind"] == "refusal":
            if (not local_refusal or producer != ENGINE or status != "failed" or
                    observation["reason"] != "delivery:refused_before_io"): fail("E_AUTHORITY_REQUIRED")
        elif producer != auth["producer"]: fail("E_AUTHORITY_REQUIRED")
        if request["observation_kind"] == "outcome":
            if status not in {"consumed", "acted_on", "outcome_verified", "useful"}: fail()
            if attempt["status"] != "delivered" or not request["evidence"]: fail()
            for reference in request["evidence"]:
                source = validate_record(tx.get(reference))
                if (source["record_type"] != "receipt" or source["provenance"]["origin"] != "host" or
                        source["provenance"]["producer"] != producer or source["body"]["stage"] != status or
                        pin(auth_record) not in source["body"]["evidence"]): fail("E_AUTHORITY_REQUIRED")
        elif request["observation_kind"] not in {"transport", "refusal"} or status not in {"delivered", "failed", "delivery_unknown"}: fail()
        if request["observation_kind"] == "transport":
            TransportResult({"status": "not_found" if status == "delivery_unknown" and observation["reason"] == "transport:not_found" else status,
                "receipt_id": observation["receipt_id"], "at": observation["reported_at"],
                "milestone": auth["milestone"] if status == "delivered" else None, "reason": observation["reason"]})
        if request["observation_kind"] == "transport" and status == "delivery_unknown" and attempt["status"] == "delivery_unknown":
            # The new poll remains in the command journal. Repeated uncertainty
            # is not new corroboration and cannot consume terminal headroom.
            row = tx.get(slot_ref(self.scope_id, value["equivalence_key"]))
            return self._result(tx.success("recorded", {"delivery_receipt": attempt["current"], "status": status}), status,
                intent=auth["intent"], slot=pin(row), authorization=pin(auth_record), observation=attempt["current"])
        if len(attempt["observations"]) >= 128: fail("E_BUDGET_EXHAUSTED")
        stored = tx.insert(self._observation_input(pin(auth_record), auth, observation, request["evidence"], operation_id=command["command_id"], producer=producer))
        if status == "delivered":
            self.attention.stage_observed_delivery(tx, auth["decision"], pin(stored), authorization=pin(auth_record), authorization_proof=request["authorization_proof"])
        attempt["observations"].append(pin(stored))
        if request["observation_kind"] in {"transport", "refusal"}:
            if attempt["status"] == "delivered" and status != "delivered": fail("E_EVIDENCE_INVALID")
            attempt.update(status=status, current=pin(stored), completion_key=command["idempotency_key"])
        tx.put_projection(entity_ref(attempt_record), domain("delivery-attempt", attempt))
        row = tx.get(slot_ref(self.scope_id, value["equivalence_key"])); slot = _value("delivery-slot", row["value"])
        if request["observation_kind"] in {"transport", "refusal"} and (slot["authorization"] == pin(auth_record) or status == "delivered"):
            if slot["state"] != "delivered" or status == "delivered":
                slot.update(state=status, last_observation=pin(stored))
                current = tx.put_projection(entity_ref(row), domain("delivery-slot", slot))
            else: current = row
        else: current = row
        if status == "delivered":
            return self._result(tx.success("delivered", {"delivery_receipt": pin(stored), "milestone": auth["milestone"]}), status,
                intent=auth["intent"], slot=pin(current), authorization=pin(auth_record), observation=pin(stored))
        return self._result(tx.success("recorded", {"delivery_receipt": pin(stored), "status": status}), status,
            intent=auth["intent"], slot=pin(current), authorization=pin(auth_record), observation=pin(stored))

    def _prepare_refusal(self, authorization, code):
        with self.storage.snapshot() as view:
            auth = authorization_value(view.get(authorization))
            value = self._intent(view.get(auth["intent"]))
            token = _value("control-token", value["token"])
            journal = view.command_receipt(auth["authorization_key"])
        now = fragment(self.clock(), "known_time")
        identity = "refused-" + authorization["id"]
        observation = {"schema_version": "1.0", "authorization": authorization, "intent": auth["intent"],
            "destination": auth["destination"], "transport": auth["transport"], "delivery_key": auth["delivery_key"],
            "status": "failed", "receipt_id": None, "reported_at": now, "observed_at": now,
            "ordering": "unavailable", "reason": "delivery:refused_before_io",
            "eligibility_at_observation": {"status": "invalidated", "error_code": code, "checked_at": now}}
        command, _ = self._maintenance_for_fact(auth, value, token, identity, identity)
        request = command["extensions"][REQUEST_EXTENSION]["value"]
        request.update(authorization=authorization, authorization_proof={"command": journal["command"], "result": journal["result"]},
            observation=domain("delivery-observation", observation), observation_kind="refusal", outcome_producer=ENGINE)
        def inspect(view):
            self._fact_reads(view, authorization, auth, value, [])
            row, _ = self._slot(view, value)
            request["expected_slot"] = pin(row)
        return self._collect(command, inspect)

    def _content(self, value):
        payload = self.payloads.read(value["content"])
        if payload.status != "available" or source_digest(payload.data) != value["content_digest"]: fail("E_EVIDENCE_UNAVAILABLE")
        return payload.data

    def _completion(self, view, attempt):
        if attempt["status"] in {"authorized", "delivery_unknown"}: fail("E_DELIVERY_UNKNOWN")
        if attempt["completion_key"] is None: fail()
        journal = view.command_receipt(attempt["completion_key"])
        result = validate_result(journal["result"])
        if result["status"] != "success" or result.get("body", {}).get("delivery_receipt") != attempt["current"]: fail()
        return result

    def _reported(self, authorization):
        with self.storage.snapshot() as view:
            auth = authorization_value(view.get(authorization))
            value = self._intent(view.get(auth["intent"])); self._audit(view, value)
            record = view.get(self._attempt_ref(authorization)); status = _value("delivery-attempt", record["value"])
            return self._completion(view, status)

    def send(self, prepared_authorization, *, before_io=None, after_io=None):
        command, request = self._checked(prepared_authorization)
        if request["action"] != "authorize": fail("E_SCHEMA_INVALID")
        with self.storage.snapshot() as view:
            value = self._intent(view.get(request["intent"]))
            try: historical = view.command_receipt(command["idempotency_key"])
            except StorageError as error:
                if error.code != "E_NOT_FOUND": raise
                historical = None
            if historical is None:
                transport = self._transport(self._destination(value["destination"]))
                self._content(value)
        claimed = []
        result = self.execute(command, _claimed=claimed)
        if result["status"] != "success" or result["outcome"] != "authorized": return result
        authorization = result["body"]["authorization"]
        if not claimed:
            return self._reported(authorization)
        try:
            if before_io is not None: before_io(authorization)
            with self.storage.snapshot() as snapshot:
                view = _Reads(snapshot, self.scope_id)
                auth_record = view.get(authorization); auth = authorization_value(auth_record)
                row, slot = self._slot(view, value)
                self._lease(slot, auth["lease"])
                if slot["authorization"] != authorization or slot["state"] != "authorized": fail("E_DEPENDENCY_STALE")
                self._guards(view, value)
                self.budgets.require_committed(view, auth["attention_budget"])
            destination = self._destination(value["destination"])
            content = self._content(value)
        except ContractError as error:
            # Only this fresh local claim can establish that I/O never began.
            refusal = self._prepare_refusal(authorization, error.code)
            recorded = self.execute(refusal, _local_refusal=self._refusal_key)
            if recorded["status"] != "success": return recorded
            raise
        try:
            observed = transport.send(destination=destination, delivery_key=value["delivery_key"],
                content=content, authorization=auth_record)
            if not isinstance(observed, TransportResult): raise TypeError("untyped transport result")
        except Exception:
            observed = TransportResult({"status": "delivery_unknown", "receipt_id": None, "at": {"state": "unknown", "reason": "not_reported"},
                "milestone": None, "reason": "transport:unknown"})
        if after_io is not None: after_io(authorization, observed)
        identity = "complete-" + authorization["id"]
        completion = self.prepare_observation(authorization, observed, command_id=identity, idempotency_key=identity)
        result = self.execute(completion)
        with self.storage.snapshot() as view: self._audit(view, value)
        if result["status"] != "success": return result
        if observed.value["status"] in {"delivery_unknown", "not_found"}: fail("E_DELIVERY_UNKNOWN")
        return result

    def history(self, authorization):
        """Present-READ-authorized immutable facts, independent of work expiry."""
        with self.storage.snapshot() as view:
            auth = authorization_value(view.get(authorization))
            value = self._intent(view.get(auth["intent"])); self._audit(view, value)
            attempt = _value("delivery-attempt", view.get(self._attempt_ref(authorization))["value"])
            return {"authorization": view.get(authorization), "status": "delivery_unknown" if attempt["status"] == "authorized" else attempt["status"],
                "observations": [view.get(reference) for reference in attempt["observations"]]}

    def reconcile(self, authorization, *, command_id, idempotency_key):
        """Query only: even terminal NOT_FOUND never authorizes another send."""
        with self.storage.snapshot() as view:
            auth = authorization_value(view.get(authorization))
            value = self._intent(view.get(auth["intent"])); self._audit(view, value)
            attempt = _value("delivery-attempt", view.get(self._attempt_ref(authorization))["value"])
            if attempt["status"] in {"delivered", "failed"}: return self._completion(view, attempt)
            if len(attempt["observations"]) >= 128: fail("E_BUDGET_EXHAUSTED")
            transport = self._transport(self._destination(auth["destination"]))
            if transport.capabilities.value["receipt_lookup"] is None: fail("E_DELIVERY_UNKNOWN")
        # No storage snapshot/read transaction survives transport I/O.
        try:
            observed = transport.lookup(destination=self._destination(auth["destination"]), delivery_key=auth["delivery_key"])
            if not isinstance(observed, TransportResult): raise TypeError("untyped transport result")
        except Exception:
            observed = TransportResult({"status": "delivery_unknown", "receipt_id": None,
                "at": {"state": "unknown", "reason": "not_reported"}, "milestone": None, "reason": "transport:unknown"})
        prepared = self.prepare_observation(authorization, observed, command_id=command_id, idempotency_key=idempotency_key)
        result = self.execute(prepared)
        with self.storage.snapshot() as view: self._audit(view, value)
        if result["status"] == "success" and observed.value["status"] in {"delivery_unknown", "not_found"}: fail("E_DELIVERY_UNKNOWN")
        return result

    def prepare_outcome(self, authorization, evidence, *, command_id, idempotency_key):
        """Append an actual independent host receipt; never infer it from send."""
        with self.storage.snapshot() as view:
            auth = authorization_value(view.get(authorization))
            value = self._intent(view.get(auth["intent"])); self._audit(view, value)
            record = validate_record(view.get(evidence))
            status = record["body"]["stage"]
            if (status not in {"consumed", "acted_on", "outcome_verified", "useful"} or
                    record["provenance"]["origin"] != "host" or record["provenance"]["producer"] != auth["producer"] or
                    authorization not in record["body"]["evidence"]): fail("E_AUTHORITY_REQUIRED")
            token = _value("control-token", value["token"])
            proof = view.command_receipt(auth["authorization_key"])
            observed_at = fragment(self.clock(), "known_time")
            if compare_times(record["body"]["recorded_at"], observed_at) > 0: fail()
        observation = {"schema_version": "1.0", "authorization": authorization, "intent": auth["intent"],
            "destination": auth["destination"], "transport": auth["transport"], "delivery_key": auth["delivery_key"], "status": status,
            "receipt_id": record["id"], "reported_at": record["body"]["recorded_at"], "observed_at": observed_at,
            "ordering": "transport_time", "reason": "delivery:independent_outcome",
            "eligibility_at_observation": self._eligibility_observation(value)}
        command, _ = self._maintenance_for_fact(auth, value, token, command_id, idempotency_key)
        request = command["extensions"][REQUEST_EXTENSION]["value"]
        request.update(authorization=authorization, observation=domain("delivery-observation", observation),
            authorization_proof={"command": proof["command"], "result": proof["result"]}, observation_kind="outcome",
            evidence=[evidence], outcome_producer=auth["producer"])
        def inspect(view):
            self._fact_reads(view, authorization, auth, value, [evidence])
            row, _ = self._slot(view, value)
            request["expected_slot"] = None if row is None else pin(row)
        return self._collect(command, inspect)
