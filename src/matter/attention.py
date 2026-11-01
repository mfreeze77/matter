"""MAT-019 bounded attention eligibility and actual delivered baselines.

Only admitted assessment propositions enter material comparison. Decisions are
not dispatch authority. No transport, outbox, semantic call or global score is
implemented here; delivery history advances only from admitted host receipts.
"""

from copy import deepcopy

from ._rule_values import FrozenValue, descriptor, domain, fragment
from .assessments import AssessmentService, _Tracked
from .canonical import canonical_bytes, canonical_digest
from .claims import read_claim
from .contexts import _active, _binding, _condition, _context_targets, _refs
from .contracts import command_digest, validate_command, validate_record, validate_result
from .controls import command_targets
from .dependencies import capture_dependencies, recomputation_token, register_dependency, registration_ref, require_current_dependency
from .dispositions import DispositionDefinition, disposition_scope_ref
from .identity_dependencies import _lookup, _value
from .lifecycle import _pointer
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times


NAMESPACE = "matter.attention"
REQUEST_EXTENSION = "matter:attention-request"
RESULT_EXTENSION = "matter:attention-result"
_ENGINE = descriptor("matter", "attention", "1.0", {"comparison": "declared-admitted-propositions",
    "baseline": "host-delivered-milestone", "action_authority": "none"}, "matter.attention-engine.v1")
_CORRECTIONS = {"evidence_correction", "association_correction"}


def _fail(code="E_POLICY_INVALID"):
    raise StorageError(code, "The attention inputs do not satisfy their declared current scope.")


def _stable(reference):
    return {key: reference[key] for key in ("namespace", "id")}


def _same(left, right):
    return canonical_bytes(left) == canonical_bytes(right)


def _address(matter, policy, purpose, audience, *, baseline=False):
    key = {"matter": entity_ref(matter), "purpose": _stable(purpose), "audience": _stable(audience)}
    if not baseline:
        key["policy"] = _stable(policy)
    return {"scope_id": matter["scope_id"], "namespace": NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": ("baseline-" if baseline else "decision-") + canonical_digest(key, "matter.attention-lane.v1")}


def attention_ref(matter, *, policy, purpose, audience):
    return _address(matter, policy, purpose, audience)


def delivered_baseline_ref(matter, *, purpose, audience):
    return _address(matter, {}, purpose, audience, baseline=True)


class AttentionPolicy(FrozenValue):
    """Installed exact meanings over subject-scoped typed claim selectors."""

    def __init__(self, value):
        body = domain("attention-policy", value)["value"]
        names = [item["name"] for item in body["fields"]]
        if not names or len(set(names)) != len(names) or not any("material" in item["roles"] for item in body["fields"]):
            _fail()
        if body["disposition_namespace"].startswith("matter.") or body["disposition_namespace"] == "matter":
            _fail("E_SCOPE_FORBIDDEN")
        for field in body["fields"]:
            for name in ("condition_pointer", "value_pointer"):
                pointer = field[name]
                if not pointer.startswith("/") or "~" in pointer.replace("~0", "").replace("~1", ""):
                    _fail()
            if not field["accepted_statuses"] or not field["accepted_values"]:
                _fail()
        decision = body["decision"]
        if decision is not None and (decision["field"] not in names or len(decision["options"]) < 2):
            _fail()
        self._freeze(body)

    @property
    def reference(self):
        body = self.value
        return descriptor(body["namespace"], body["id"], body["semantic_version"], body, "matter.attention-policy.v1")

    @property
    def material_contract(self):
        # Gate/treatment changes alone do not fabricate a new external fact.
        fields = [{key: value for key, value in item.items() if key in {
                    "name", "claim_schema", "predicate", "condition_pointer", "condition", "value_pointer"}}
                  for item in self.value["fields"] if "material" in item["roles"]]
        fields.sort(key=lambda item: item["name"])
        return descriptor("matter", "attention-material", "1.0", fields, "matter.attention-material-contract.v1")


def project_material(policy, assessment, claims):
    """Bounded code projection; callers must first validate source admission."""
    body = assessment["body"]
    statuses = {canonical_bytes(item["claim"]): item["status"] for item in body["propositions"]}
    material, selections, values = {}, {}, {}
    for field in policy.value["fields"]:
        matches = []
        for claim in claims:
            data = claim["body"]
            if (data["subject"] != entity_ref(body["matter"]) or data["predicate"] != field["predicate"]
                    or data["value"]["schema"] != field["claim_schema"]):
                continue
            if _same(_pointer(data["value"]["value"], field["condition_pointer"]), field["condition"]):
                matches.append(claim)
        superseded = {canonical_bytes(ref) for claim in matches for ref in claim.get("supersedes", [])}
        matches = [claim for claim in matches if canonical_bytes(pin(claim)) not in superseded]
        selections[field["name"]] = sorted([pin(claim) for claim in matches], key=canonical_bytes)
        distinct = {canonical_bytes({"status": statuses[canonical_bytes(pin(claim))],
                    "value": _pointer(claim["body"]["value"]["value"], field["value_pointer"])}):
                    {"status": statuses[canonical_bytes(pin(claim))],
                     "value": _pointer(claim["body"]["value"]["value"], field["value_pointer"])} for claim in matches}
        values[field["name"]] = next(iter(distinct.values())) if len(distinct) == 1 else {"status": "unknown", "value": None}
        if "material" in field["roles"]:
            material[field["name"]] = values[field["name"]]
    return material, selections, values


def select_attention_treatment(*, hard_quiet, correction, ordinary_quiet, decision_ready,
                               handled_by_owner, audience_kind, owned_by_audience,
                               preference, routine_treatment):
    """Neutral routing precedence; inputs carry no evidence/action authority."""
    if hard_quiet:
        return "quiet", None
    if correction:
        return "correction", "correction_delta"
    if ordinary_quiet:
        return "quiet", None
    if decision_ready:
        return "decision_request", "reserved_decision_required"
    if handled_by_owner:
        return "quiet", None
    return ("host_hint" if audience_kind == "host_agent" and owned_by_audience else
            (preference or routine_treatment)), "material_change"


def decide_attention(policy, assessment, values, material, baseline, *, purpose_active, audience_active,
                     audience_reference, audience_kind, owned, lifecycle_role, dispositions, preference=None,
                     linked_fields=(), owned_by_audience=False, selections=None):
    """Deterministic neutral treatments; no confidence-to-human escalation."""
    body = assessment["body"]
    previous = None if baseline is None else baseline["material"]
    changed = sorted(material) if previous is None else sorted(name for name in set(material) | set(previous)
        if name not in material or name not in previous or not _same(material[name], previous[name]))
    changed_values = set(changed)
    if baseline is not None and baseline["material_contract"] != policy.material_contract:
        changed = sorted(material)
    def admitted(field):
        value = values[field["name"]]
        return value["status"] in field["accepted_statuses"] and any(_same(value["value"], allowed) for allowed in field["accepted_values"])
    active = {role: any(role in field["roles"] and admitted(field) for field in policy.value["fields"])
              for role in ("relevance", "critical", "owned_next_step")}
    reasons = []
    if baseline is not None and baseline["material_contract"] != policy.material_contract:
        reasons.append("material_contract_change")
    if not purpose_active:
        reasons.append("no_active_purpose")
    if not audience_active:
        reasons.append("inactive_audience")
    if not changed:
        reasons.extend(["no_material_change", "already_delivered"])
    if not active["relevance"]:
        reasons.append("no_relevance")
    uncertain = any(values[field["name"]]["status"] in {"unknown", "mixed"} and (
        bool({"material", "relevance"} & set(field["roles"])) or selections is None or bool(selections.get(field["name"])))
        for field in policy.value["fields"])
    if body["evaluation_state"] != "complete" or body["evidence_gaps"] or uncertain:
        reasons.append("insufficient_evidence")
    if body["evidence_selection"]["coverage"]["status"] != "complete":
        reasons.append("incomplete_coverage")
    if owned and active["owned_next_step"] and not owned_by_audience:
        reasons.append("handled_by_owner")
    if lifecycle_role == "resolved":
        reasons.append("recovery_established")
    if dispositions:
        reasons.append("disposition_applies")
        if "deferral" in dispositions:
            reasons.append("deferred_until_checkpoint")
    if preference is not None:
        reasons.append("preference_applies")
    correction = baseline is not None and bool(changed_values & set(linked_fields))
    decision = policy.value["decision"]
    decision_ready = (decision is not None and decision["audience"] == audience_reference and audience_kind in {"human", "role"}
        and any(field["name"] == decision["field"] and admitted(field) for field in policy.value["fields"]))
    hard_quiet = not purpose_active or not audience_active or not changed or bool(dispositions)
    treatment, reason = select_attention_treatment(hard_quiet=hard_quiet, correction=correction,
        ordinary_quiet=not active["relevance"] or any(reason in reasons for reason in
            ("insufficient_evidence", "incomplete_coverage", "recovery_established")),
        decision_ready=decision_ready, handled_by_owner="handled_by_owner" in reasons,
        audience_kind=audience_kind, owned_by_audience=owned_by_audience,
        preference=preference, routine_treatment=policy.value["routine_treatment"])
    if reason is not None:
        reasons.append("critical_fact" if reason == "material_change" and active["critical"] else reason)
    if treatment == "quiet" and not reasons:
        reasons.append("no_material_change")
    return {"treatment": treatment, "reasons": list(dict.fromkeys(reasons)), "changed_fields": changed,
            "decision_request": decision if treatment == "decision_request" else None}


class _Reads(_Tracked):
    def __init__(self, view, scope):
        super().__init__(view, scope)
        self.bytes = 0

    def _remember(self, value):
        identity = tuple(value[key] for key in ("scope_id", "namespace", "id"))
        if identity not in self.records:
            self.bytes += len(canonical_bytes(value))
        if len(self.records) >= 4096 or self.bytes > 8388608:
            _fail("E_BUDGET_EXHAUSTED")
        return super()._remember(value)


class AttentionService:
    """Trusted deterministic evaluation and separately verified delivery facts."""

    def __init__(self, storage, *, assessments, policies, controls, clock, lifecycle=None, access=None):
        if not isinstance(assessments, AssessmentService) or assessments.controls is not controls or storage is not assessments.storage:
            _fail()
        if access is None:
            access = assessments.access
        elif access is not assessments.access:
            _fail()
        self.storage, self.scope_id, self.assessments, self.controls = storage, storage.scope_id, assessments, controls
        self.policies, self.clock, self.lifecycle, self.access = tuple(policies), clock, lifecycle, access
        if not callable(clock) or not self.policies or len(self.policies) > 128 or any(not isinstance(p, AttentionPolicy) for p in self.policies):
            _fail()
        if len({tuple(p.reference[key] for key in ("namespace", "id", "version")) for p in self.policies}) != len(self.policies):
            _fail()
        for policy in self.policies:
            assessments.profiles.resolve(policy.value["profile"])
            for field in policy.value["fields"]:
                assessments.schemas.resolve(field["claim_schema"])

    def _policy(self, reference):
        matches = [p for p in self.policies if p.reference == reference]
        if len(matches) != 1:
            _fail()
        return matches[0]

    def _access_boundary(self):
        if self.access is not self.assessments.access:
            _fail()

    def _command(self, command):
        value = validate_command(command)
        if value["operation"] != "assess" or value["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        return value

    def _request(self, command):
        wrapped = command.get("extensions", {}).get(REQUEST_EXTENSION)
        return _value("attention-request", wrapped)

    def _inspect(self, view, command, request, now, *, original):
        self._access_boundary()
        policy = self._policy(request["policy"])
        token = _value("control-token", request["token"])
        if self.access is None and request["access_context"] is not None:
            _fail("E_AUTHORITY_REQUIRED")
        if token["actor"] != command["actor"] or entity_ref(token["authority"]) != command["authority"]:
            _fail("E_AUTHORITY_REQUIRED")
        if compare_times(now, request["captured_at"]) < 0:
            _fail("E_DEPENDENCY_STALE")
        profile = self.assessments.profiles.resolve(policy.value["profile"])
        assessment, lane = self.assessments.read_current(view, request["assessment"], profile, as_of=now)
        view.get(request["subject"])
        if (assessment["body"]["matter"] != command["body"]["matter"] or command["body"]["profile"] != profile.reference):
            _fail("E_SCOPE_FORBIDDEN")
        bindings, conditions, contexts = {}, [], []
        for kind, references in request["contexts"].items():
            references = references if type(references) is list else [references]
            bindings[kind] = []
            for ref in references:
                binding = _binding(view, self.scope_id, ref)
                if pin(view.get(entity_ref(ref))) != ref or binding["definition"]["kind"] != {"responsibilities": "responsibility", "preferences": "preference"}.get(kind, kind):
                    _fail("E_DEPENDENCY_STALE")
                scopes = binding["definition"]["applies_to"]
                if scopes and entity_ref(command["body"]["matter"]) not in scopes:
                    _fail("E_SCOPE_FORBIDDEN")
                bindings[kind].append(binding)
                conditions.extend(_condition(binding["reference"], binding["definition"], now))
                contexts.extend([binding["context"], binding["version"]])
        purpose, audience = bindings["purpose"][0], bindings["audience"][0]
        if (purpose["reference"] != command["body"]["purpose"] or audience["reference"] != command["body"].get("audience")
                or assessment["body"]["purpose"] != purpose["reference"]
                or assessment["body"].get("audience", audience["reference"]) != audience["reference"]):
            _fail("E_SCOPE_FORBIDDEN")
        active_dispositions, selected_dispositions, candidate_slots = [], [], []
        for kind in ("acknowledgement", "deferral", "rejection", "decision"):
            slot = disposition_scope_ref(namespace=policy.value["disposition_namespace"], kind=kind,
                matter=entity_ref(command["body"]["matter"]), purpose={"reference": purpose["reference"], "context": purpose["context"]},
                audience={"reference": audience["reference"], "context": audience["context"]}, subject=request["subject"])
            candidate_slots.append(slot)
            stored = _lookup(view, slot)
            if stored is not None:
                body = _value("disposition-current", stored["value"])
                definition = DispositionDefinition(body["definition"])
                if disposition_scope_ref(**{name: definition.value[name] for name in ("namespace", "kind", "matter", "purpose", "audience", "subject")}) != slot:
                    _fail("E_EVIDENCE_INVALID")
                control = validate_record(view.get(body["control"]))
                if _value("disposition-mutation", control["body"]["effect"]["value"]["payload"])["definition"] != definition.value:
                    _fail("E_EVIDENCE_INVALID")
                selected_dispositions.append(pin(stored))
                conditions.extend(_condition(definition.reference, definition.value, now))
                if definition.value["status"] == "active" and _active(definition.value, now):
                    active_dispositions.append(kind)
        claims = [read_claim(view, self.scope_id, item["claim"]) for item in assessment["body"]["propositions"]]
        for claim in claims:
            if any(field["claim_schema"] == claim["body"]["value"]["schema"] for field in policy.value["fields"]):
                self.assessments.schemas.validate(claim["body"]["value"])
        material, selections, values = project_material(policy, assessment, claims)
        address = _address(command["body"]["matter"], policy.reference, purpose["reference"], audience["reference"])
        baseline_address = _address(command["body"]["matter"], policy.reference, purpose["reference"], audience["reference"], baseline=True)
        previous = _lookup(view, address)
        previous_registration = None if previous is None else _lookup(view, registration_ref(address))
        baseline_record = _lookup(view, baseline_address)
        baseline = None if baseline_record is None else _value("attention-baseline", baseline_record["value"])["delivered"]
        linked_fields = set()
        if baseline is not None:
            if (baseline["material_digest"] != canonical_digest(baseline["material"], "matter.attention-material.v1")
                    or entity_ref(baseline["matter"]) != entity_ref(command["body"]["matter"])
                    or _stable(baseline["purpose"]) != _stable(purpose["reference"]) or _stable(baseline["audience"]) != _stable(audience["reference"])):
                _fail("E_EVIDENCE_INVALID")
            view.get(baseline["assessment"])
            delivered = validate_record(view.get(baseline["decision"]))
            if delivered["provenance"]["producer"] != _ENGINE:
                _fail("E_EVIDENCE_INVALID")
            prior_decision = _value("attention-decision", delivered["body"]["details"])
            if (prior_decision["assessment"] != baseline["assessment"] or not _same(prior_decision["material"], baseline["material"])
                    or prior_decision["material_digest"] != baseline["material_digest"]):
                _fail("E_EVIDENCE_INVALID")
            for field in policy.value["fields"]:
                if "material" not in field["roles"]:
                    continue
                old_selected = {canonical_bytes(ref) for ref in prior_decision["selections"].get(field["name"], [])}
                selected = {canonical_bytes(ref) for ref in selections[field["name"]]}
                if selected & old_selected and set(assessment["body"]["causes"]) & _CORRECTIONS:
                    linked_fields.add(field["name"])
                pending = [ref for claim in claims if canonical_bytes(pin(claim)) in selected for ref in claim.get("supersedes", [])]
                seen = set()
                while pending:
                    ref = pending.pop()
                    key = canonical_bytes(ref)
                    if key in seen:
                        continue
                    seen.add(key)
                    if len(seen) > 128:
                        _fail("E_BUDGET_EXHAUSTED")
                    prior_claim = read_claim(view, self.scope_id, ref)
                    data = prior_claim["body"]
                    if (data["subject"] != entity_ref(command["body"]["matter"]) or data["predicate"] != field["predicate"]
                            or data["value"]["schema"] != field["claim_schema"]):
                        continue
                    self.assessments.schemas.validate(data["value"])
                    if not _same(_pointer(data["value"]["value"], field["condition_pointer"]), field["condition"]):
                        continue
                    if key in old_selected:
                        linked_fields.add(field["name"])
                    pending.extend(prior_claim.get("supersedes", []))
        if original and ((None if previous is None else pin(previous)) != request["previous"]
                         or (None if baseline_record is None else pin(baseline_record)) != request["baseline"]):
            _fail("E_DEPENDENCY_STALE")
        role, lifecycle_pin = None, None
        if request["lifecycle"] is not None:
            if self.lifecycle is None:
                _fail()
            state = self.lifecycle.read_current(view, command["body"]["matter"], **request["lifecycle"],
                read_token=token, access_context=request["access_context"])
            if state is not None:
                role = self.lifecycle.state_role(request["lifecycle"]["profile"], state["value"]["value"]["state"])
                lifecycle_pin = pin(state)
        owned = any(_active(b["definition"], now) and "write" in b["definition"]["content"]["capabilities"] for b in bindings["responsibilities"])
        owned_by_audience = any(_active(b["definition"], now) and "write" in b["definition"]["content"]["capabilities"]
            and b["reference"] in audience["definition"]["content"]["responsibilities"] for b in bindings["responsibilities"])
        preferences = [b["definition"]["content"]["preferred_treatment"] for b in bindings["preferences"] if _active(b["definition"], now)]
        if len(set(preferences)) > 1:
            _fail("E_RULE_CONFLICT")
        preferred = preferences[0] if preferences else None
        if preferred in {"correction", "decision_request"}:
            _fail()  # A delivery preference cannot mint these semantic gates.
        decision = decide_attention(policy, assessment, values, material, baseline, purpose_active=_active(purpose["definition"], now),
            audience_active=_active(audience["definition"], now), audience_reference=audience["reference"],
            audience_kind=audience["definition"]["content"]["audience_kind"], owned=owned,
            lifecycle_role=role, dispositions=active_dispositions, preference=preferred, linked_fields=linked_fields,
            owned_by_audience=owned_by_audience, selections=selections)
        all_public = [*command_targets({**command, "expected_revisions": [pin(item) for item in view.records.values()]}),
                      *candidate_slots, *[target for group in bindings.values() for b in group for target in _context_targets(b)]]
        capability = "delivery" if request["action"] == "record_delivered" else "assessment"
        self.controls.require_current(view, token, capability=capability, targets=_refs(all_public), as_of=now)
        self.controls._audit(view, command, _refs(all_public))
        if self.access is not None:
            sources = [pin(item) for item in view.records.values() if item["record_type"] in {"assessment", "claim"}]
            sources.extend(contexts + selected_dispositions)
            self.access.require_current(view, request["access_context"], references=sources,
                                        audience=audience["reference"])
        return {"command": command, "policy": policy, "assessment": assessment, "lane": lane, "bindings": bindings,
            "conditions": conditions, "contexts": contexts + selected_dispositions, "selections": selections,
            "material": material, "decision": decision, "address": address, "baseline_address": baseline_address,
            "baseline_record": baseline_record, "baseline": baseline, "previous": previous,
            "previous_registration": previous_registration, "lifecycle": lifecycle_pin}

    def prepare(self, command, *, policy, assessment, contexts, token, subject=None, lifecycle=None,
                access_context=None, delivery_receipt=None):
        command = self._command(command)
        if REQUEST_EXTENSION in command.get("extensions", {}):
            _fail()
        request = {"schema_version": "1.0", "action": "evaluate" if delivery_receipt is None else "record_delivered",
            "policy": getattr(policy, "reference", policy), "assessment": fragment(assessment, "assessment_dependency"),
            "contexts": deepcopy(contexts), "subject": fragment(subject or assessment, "pinned_ref"), "lifecycle": deepcopy(lifecycle),
            "token": domain("control-token", token), "access_context": deepcopy(getattr(access_context, "value", access_context)),
            "captured_at": fragment(self.clock(), "known_time"), "previous": None, "previous_registration": None,
            "baseline": None, "delivery_receipt": delivery_receipt}
        domain("attention-request", request)
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            state = self._inspect(view, command, request, request["captured_at"], original=False)
            request.update(previous=None if state["previous"] is None else pin(state["previous"]),
                previous_registration=None if state["previous_registration"] is None else recomputation_token(view, pin(state["previous_registration"])),
                baseline=None if state["baseline_record"] is None else pin(state["baseline_record"]))
            if delivery_receipt is not None:
                self._delivery(view, request, state, request["captured_at"])
            command["expected_revisions"] = sorted([pin(item) for item in view.records.values()], key=canonical_bytes)
        command.setdefault("extensions", {})[REQUEST_EXTENSION] = domain("attention-request", request)
        return validate_command(command)

    def stage(self, tx, prepared):
        """Atomically stage deterministic reevaluation inside a trusted host tx."""
        command = self._command(prepared)
        request = self._request(command)
        if tx.command["actor"] != command["actor"] or tx.command["authority"] != command["authority"]:
            _fail("E_AUTHORITY_REQUIRED")
        view = _Reads(tx, self.scope_id)
        now = fragment(self.clock(), "known_time")
        state = self._inspect(view, command, request, now, original=True)
        if request["action"] == "record_delivered":
            baseline = self._delivery(view, request, state, now)
            stored = tx.put_projection(state["baseline_address"], domain("attention-baseline", {"delivered": baseline}))
            return {"assessment": pin(state["assessment"]), "baseline": pin(stored), "decision": None,
                    "dependencies": [pin(stored)], "value": None}
        baseline = state["baseline_record"]
        if baseline is None:
            baseline = tx.put_projection(state["baseline_address"], domain("attention-baseline", {"delivered": None}))
        actual_request = {**request, "baseline": pin(baseline)}
        purpose = state["bindings"]["purpose"][0]["reference"]
        audience = state["bindings"]["audience"][0]["reference"]
        payload = {"schema_version": "1.0", "scope_id": self.scope_id, "policy": state["policy"].reference,
            "matter": command["body"]["matter"], "purpose": purpose, "audience": audience, "assessment": pin(state["assessment"]),
            "material_contract": state["policy"].material_contract, "material": state["material"],
            "material_digest": canonical_digest(state["material"], "matter.attention-material.v1"),
            "selections": state["selections"], "baseline": pin(baseline), **state["decision"], "at": now, "request": actual_request}
        positive = [pin(state["assessment"]), pin(state["lane"]), pin(baseline)]
        if state["lifecycle"] is not None:
            positive.append(state["lifecycle"])
        manifest = capture_dependencies(tx, scope_id=self.scope_id, as_of=now, positive=positive,
            contexts=state["contexts"], time_conditions=state["conditions"], control_token=request["token"]["value"], controls=self.controls)
        receipt = tx.insert({"schema_version": "1.0", "record_type": "receipt", "scope_id": self.scope_id,
            "namespace": NAMESPACE, "id": "attention-" + canonical_digest(command, "matter.attention-command.v1"),
            "provenance": {"origin": "system", "producer": _ENGINE, "recorded_at": now, "parents": [pin(state["assessment"])]},
            "body": {"stage": "operation", "operation_id": tx.command["command_id"], "recorded_at": now,
                "outcome": "matter:attention_" + payload["treatment"], "evidence": positive,
                "details": domain("attention-decision", payload)}})
        current = tx.put_projection(state["address"], domain("attention-current", {"decision": pin(receipt)}))
        register_dependency(tx, pin(current), manifest, as_of=now, controls=self.controls, previous=request["previous_registration"])
        return {"assessment": pin(state["assessment"]), "baseline": None, "decision": pin(receipt), "value": payload,
                "current": pin(current), "dependencies": [*manifest.value["positive"], *manifest.value["contexts"]]}

    def evaluate(self, command):
        command = self._command(command)
        request = self._request(command)
        def handler(tx):
            staged = self.stage(tx, command)
            result = tx.success("assessed", {"assessment": staged["assessment"]})
            result["extensions"] = {RESULT_EXTENSION: domain("attention-result", {
                "action": request["action"], "decision": staged["decision"], "baseline": staged["baseline"],
                "treatment": None if staged["value"] is None else staged["value"]["treatment"],
                "reasons": ["delivery_milestone_recorded"] if staged["value"] is None else staged["value"]["reasons"],
                "dependencies": staged["dependencies"]})}
            return validate_result(result)
        def audit(view):
            self._access_boundary()
            self.controls._audit(view, command, _refs([*command_targets(command), *request["token"]["value"]["targets"]]))
            if self.access is not None:
                self.access.require_history(view, request["access_context"], references=[request["assessment"]])
            elif request["access_context"] is not None:
                _fail("E_AUTHORITY_REQUIRED")
        return self.storage.execute(command, handler, replay_guard=audit, dependency_error_code="E_DEPENDENCY_STALE")

    def read(self, token, reference, *, access_context=None):
        """Permission-checked historical decision; not a new current verdict."""
        self._access_boundary()
        with self.storage.snapshot() as view:
            record = validate_record(view.get(reference))
            payload = _value("attention-decision", record["body"]["details"])
            if self.access is None and payload["request"]["access_context"] is not None:
                _fail("E_AUTHORITY_REQUIRED")
            if (record["scope_id"] != self.scope_id or record["record_type"] != "receipt"
                    or record["provenance"]["producer"] != _ENGINE or payload["scope_id"] != self.scope_id):
                _fail("E_EVIDENCE_INVALID")
            self.controls.require_current(view, token, capability="read", targets=payload["request"]["token"]["value"]["targets"])
            if self.access is not None:
                selected = getattr(access_context, "value", access_context) or payload["request"]["access_context"]
                if selected is None or selected["audience"] != payload["audience"]:
                    _fail("E_AUTHORITY_REQUIRED")
                self.access.require_history(view, selected, references=[payload["assessment"]])
            return record

    def current(self, matter, *, policy, purpose, audience, read_token, access_context=None):
        """Current deterministic decision, with actual assessment/lifecycle gates."""
        self._access_boundary()
        selected = self._policy(getattr(policy, "reference", policy))
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            current = _lookup(view, _address(matter, selected.reference, purpose, audience))
            if current is None:
                return None
            now = fragment(self.clock(), "known_time")
            require_current_dependency(view, registration_ref(current), as_of=now, controls=self.controls)
            record = validate_record(view.get(_value("attention-current", current["value"])["decision"]))
            payload = _value("attention-decision", record["body"]["details"])
            if self.access is None and payload["request"]["access_context"] is not None:
                _fail("E_AUTHORITY_REQUIRED")
            if (record["provenance"]["producer"] != _ENGINE or payload["policy"] != selected.reference
                    or payload["purpose"] != purpose or payload["audience"] != audience):
                _fail("E_EVIDENCE_INVALID")
            self.assessments.read_current(view, payload["assessment"], selected.value["profile"], as_of=now)
            if payload["request"]["lifecycle"] is not None:
                if self.lifecycle is None:
                    _fail()
                self.lifecycle.read_current(view, matter, **payload["request"]["lifecycle"],
                    read_token=payload["request"]["token"]["value"], access_context=payload["request"]["access_context"])
            self.controls.require_current(view, read_token, capability="read", targets=payload["request"]["token"]["value"]["targets"])
            if self.access is not None:
                self.access.require_current(view, payload["request"]["access_context"], audience=audience)
                self.access.require_current(view, access_context, references=[payload["assessment"]], audience=audience)
            return record

    def stage_observed_delivery(self, tx, decision, delivery_receipt, *, authorization, authorization_proof):
        """Record a fact from an already authorized MAT-021 send in a host tx.

        This does not authorize new work or renew its original token. A late
        cancellation must not erase an actual transport observation. The
        immutable reserved storage receipt binds the supplied journal proof;
        public history/read APIs retain their present permission checks.
        """
        from .outbox import (authorization_value, OBSERVATION_EXTENSION,
                             REQUEST_EXTENSION as DELIVERY_REQUEST)
        self._access_boundary()
        if tx.command["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        authorization = fragment(authorization, "receipt_dependency")
        auth_record = validate_record(tx.get(authorization))
        auth = authorization_value(auth_record)
        token = _value("control-token", auth["control_token"])
        if (token["scope_id"] != self.scope_id or token["capability"] != "delivery" or
                tx.command["actor"] != token["actor"] or
                tx.command["authority"] != entity_ref(token["authority"])):
            _fail("E_AUTHORITY_REQUIRED")
        if type(authorization_proof) is not dict or set(authorization_proof) != {"command", "result"}:
            _fail("E_EVIDENCE_INVALID")
        command = validate_command(authorization_proof["command"])
        result = validate_result(authorization_proof["result"])
        operation_receipt = validate_record(tx.get(auth_record["creation_receipt"]))
        details = _value("storage-receipt-details", operation_receipt["body"]["details"])
        dispatch_request = _value("delivery-request", command.get("extensions", {}).get(DELIVERY_REQUEST))
        if (command["operation"] != "dispatch" or command["scope_id"] != self.scope_id or
                command["idempotency_key"] != auth["authorization_key"] or
                command["command_id"] != auth_record["body"]["operation_id"] or
                command["actor"] != token["actor"] or command["authority"] != entity_ref(token["authority"]) or
                dispatch_request["action"] != "authorize" or dispatch_request["intent"] != auth["intent"] or
                command["body"]["intent"] != auth["intent"] or
                result["operation"] != "dispatch" or result["operation_id"] != command["command_id"] or
                result["status"] != "success" or result["outcome"] != "authorized" or
                result["body"]["authorization"] != authorization or
                result["body"]["attention_budget"] != auth["attention_budget"] or
                entity_ref(operation_receipt) != result["receipt"] or
                operation_receipt["namespace"] != "matter.storage" or
                operation_receipt["body"]["operation_id"] != command["command_id"] or
                details["command_digest"] != command_digest(command) or
                details["result_digest"] != canonical_digest(result, "result.dispatch.v1") or
                authorization not in details["writes"] or auth["attention_budget"] not in details["writes"] or
                auth["baseline"] not in details["read_set"]):
            _fail("E_EVIDENCE_INVALID")
        allocation = tx.get(auth["attention_budget"])
        held = _value("budget-reservation", allocation["value"])
        if held["status"] != "committed" or held["token"] != auth["control_token"]:
            _fail("E_EVIDENCE_INVALID")
        decision = fragment(decision, "receipt_dependency")
        record = validate_record(tx.get(decision))
        value = _value("attention-decision", record["body"]["details"])
        if (decision != auth["decision"] or record["provenance"]["producer"] != _ENGINE or
                value["scope_id"] != self.scope_id or value["treatment"] == "quiet" or
                any(not _same(value[key], auth[key]) for key in
                    ("assessment", "purpose", "audience", "material_contract", "material_digest")) or
                entity_ref(value["matter"]) != auth["matter"] or
                canonical_digest(value["material"], "matter.attention-material.v1") != auth["material_digest"]):
            _fail("E_EVIDENCE_INVALID")
        receipt = validate_record(tx.get(fragment(delivery_receipt, "receipt_dependency")))
        milestone = _value("attention-delivery-milestone", receipt["body"]["details"])
        observation = _value("delivery-observation", receipt.get("extensions", {}).get(OBSERVATION_EXTENSION))
        if (receipt["scope_id"] != self.scope_id or receipt["provenance"]["origin"] != "host" or
                receipt["provenance"]["producer"] != auth["producer"] or receipt["body"]["stage"] != "delivered" or
                receipt["body"]["outcome"] != auth["milestone"] or
                observation["authorization"] != authorization or observation["status"] != "delivered" or
                any(not _same(observation[key], auth[key]) for key in ("intent", "destination", "transport", "delivery_key")) or
                milestone["decision"] != decision or milestone["milestone"] != "delivered" or
                any(not _same(milestone[key], auth[key]) for key in ("assessment", "matter", "purpose", "audience", "material_digest")) or
                receipt["provenance"]["recorded_at"] != observation["observed_at"] or
                receipt["body"]["recorded_at"] != observation["observed_at"]):
            _fail("E_EVIDENCE_INVALID")
        now = fragment(self.clock(), "known_time")
        at = milestone["delivered_at"]
        if (compare_times(observation["observed_at"], now) > 0 or
                compare_times(observation["observed_at"], auth["authorized_at"]) < 0 or
                compare_times(at, observation["observed_at"]) > 0 or compare_times(at, value["at"]) < 0):
            _fail("E_EVIDENCE_INVALID")
        ordered = observation["ordering"] == "transport_time"
        if (ordered and (observation["reported_at"]["state"] != "known" or
                         not _same(at, observation["reported_at"]))) or (not ordered and not _same(at, observation["observed_at"])):
            _fail("E_EVIDENCE_INVALID")
        address = delivered_baseline_ref(auth["matter"], purpose=auth["purpose"], audience=auth["audience"])
        current = _lookup(tx, address)
        if current is None or entity_ref(auth["baseline"]) != address:
            _fail("E_EVIDENCE_INVALID")
        prior = _value("attention-baseline", current["value"])["delivered"]
        if prior is not None and (not ordered or compare_times(at, prior["delivered_at"]) <= 0):
            if ordered or pin(current) != auth["baseline"]:
                return {"baseline": pin(current), "advanced": False, "reason": "older_or_unordered_milestone"}
        if not ordered and pin(current) != auth["baseline"]:
            return {"baseline": pin(current), "advanced": False, "reason": "baseline_changed_without_transport_order"}
        baseline = {"schema_version": "1.0", "scope_id": self.scope_id, "policy": value["policy"],
            "matter": auth["matter"], "purpose": auth["purpose"], "audience": auth["audience"],
            "assessment": auth["assessment"], "material_contract": value["material_contract"],
            "material": value["material"], "material_digest": value["material_digest"], "decision": decision,
            "delivery_receipt": pin(receipt), "delivered_at": at}
        stored = tx.put_projection(address, domain("attention-baseline", {"delivered": baseline}))
        return {"baseline": pin(stored), "advanced": True, "reason": "authorized_observed_milestone"}

    def _delivery(self, view, request, state, now):
        receipt = validate_record(view.get(request["delivery_receipt"]))
        if (receipt["record_type"] != "receipt" or receipt["provenance"]["origin"] != "host" or receipt["body"]["stage"] != "delivered"
                or not any(item["producer"] == receipt["provenance"]["producer"] and item["outcome"] == receipt["body"]["outcome"]
                    for item in state["policy"].value["delivery_producers"])):
            _fail("E_AUTHORITY_REQUIRED")
        milestone = _value("attention-delivery-milestone", receipt["body"]["details"])
        decision_record = validate_record(view.get(milestone["decision"]))
        if decision_record["provenance"]["producer"] != _ENGINE:
            _fail("E_EVIDENCE_INVALID")
        decision = _value("attention-decision", decision_record["body"]["details"])
        if (decision["treatment"] == "quiet" or decision["assessment"] != milestone["assessment"]
                or entity_ref(decision["matter"]) != milestone["matter"] or decision["purpose"] != milestone["purpose"]
                or decision["audience"] != milestone["audience"] or decision["material_digest"] != milestone["material_digest"]
                or _address(decision["matter"], decision["policy"], decision["purpose"], decision["audience"], baseline=True) != state["baseline_address"]
                or compare_times(milestone["delivered_at"], now) > 0
                or compare_times(milestone["delivered_at"], decision["at"]) < 0
                or receipt["body"]["recorded_at"] != receipt["provenance"]["recorded_at"]):
            _fail("E_EVIDENCE_INVALID")
        if state["baseline"] is not None and compare_times(milestone["delivered_at"], state["baseline"]["delivered_at"]) <= 0:
            _fail("E_DEPENDENCY_STALE")
        targets = command_targets({**state["command"], "expected_revisions": [pin(item) for item in view.records.values()]})
        self.controls.require_current(view, request["token"]["value"], capability="delivery", targets=targets, as_of=now)
        self.controls._audit(view, state["command"], targets)
        if self.access is not None:
            self.access.require_current(view, request["access_context"], references=[decision["assessment"]], audience=milestone["audience"])
        return {"schema_version": "1.0", "scope_id": self.scope_id, "policy": decision["policy"], "matter": milestone["matter"],
            "purpose": milestone["purpose"], "audience": milestone["audience"], "assessment": milestone["assessment"],
            "material_contract": decision["material_contract"], "material": decision["material"], "material_digest": decision["material_digest"],
            "decision": milestone["decision"], "delivery_receipt": pin(receipt), "delivered_at": milestone["delivered_at"]}
