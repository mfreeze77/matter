"""MAT-031 reviewed semantic-method applicability, decisions and revocation.

This does not issue evaluation evidence, modify original execution receipts or
grant action authority. Existing rule QualificationRegistry semantics remain
separate. Hosts admit reviewed certificates and their exact evaluation records.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from .._rule_values import FrozenValue, descriptor, domain, fragment
from ..canonical import canonical_bytes, canonical_digest
from ..contexts import _MutationService, _control_command, _namespace
from ..contracts import validate_command, validate_record
from ..controls import command_targets
from ..budgets import _Reads
from ..dependencies import (capture_dependencies, recomputation_token, register_dependency,
                            registration_ref, require_current_dependency)
from ..identity_dependencies import _lookup, _value
from ..storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from ..time import compare_times
from .cache import execution_key
from .contracts import Batch
from .receipts import ExecutionReceiptStore, _precision, _targets as _source_targets


NAMESPACE = "matter.semantic_qualification"
REQUEST_EXTENSION = "matter:semantic-qualification-request"


def _fail(code="E_EVIDENCE_INVALID"):
    raise StorageError(code, "The semantic qualification declaration or original context is invalid.")


def _targets(references):
    return sorted({canonical_bytes(ref): ref for ref in _source_targets(references)}.values(), key=canonical_bytes)


def _same(left, right):
    return canonical_bytes(left) == canonical_bytes(right)


def _decimal(value):
    fragment(value, "decimal_string")
    if len(value) > 1024:
        _fail("E_BUDGET_EXHAUSTED")
    try:
        number = Decimal(value)
    except InvalidOperation:
        _fail("E_POLICY_INVALID")
    if not number.is_finite():
        _fail("E_POLICY_INVALID")
    return number


def _inside(value, region):
    return (region["minimum"] is None or value >= _decimal(region["minimum"])) and (
        region["maximum"] is None or value <= _decimal(region["maximum"]))


class SemanticCertificate(FrozenValue):
    """Exact host-admitted method identity; construction is not issuance."""

    def __init__(self, value):
        body = domain("semantic-certificate", value)["value"]
        _namespace(body["namespace"])
        if compare_times(body["valid_from"], body["valid_until"]) >= 0:
            _fail("E_POLICY_INVALID")
        _precision(body["identity"]["precision"])
        regions = [region for region in body["regions"].values() if region is not None]
        if not regions:
            _fail("E_POLICY_INVALID")
        for region in regions:
            if region["minimum"] is not None and region["maximum"] is not None and _decimal(region["minimum"]) > _decimal(region["maximum"]):
                _fail("E_POLICY_INVALID")
            for value in (region["minimum"], region["maximum"]):
                if value is not None and body["identity"]["measure"]["name"] != "score" and not 0 <= _decimal(value) <= 1:
                    _fail("E_POLICY_INVALID")
        if len(regions) == 2:
            left, right = regions
            choice_overlap = not left["choices"] or not right["choices"] or bool(set(left["choices"]) & set(right["choices"]))
            low = max([_decimal(r["minimum"]) for r in regions if r["minimum"] is not None], default=Decimal("-Infinity"))
            high = min([_decimal(r["maximum"]) for r in regions if r["maximum"] is not None], default=Decimal("Infinity"))
            if choice_overlap and low <= high:
                _fail("E_POLICY_INVALID")
        self._freeze(body)

    @property
    def reference(self):
        body = self.value
        return descriptor(body["namespace"], body["id"], body["semantic_version"], body,
                          "matter.semantic-qualification-certificate.v1")


def certificate_ref(scope_id, reference):
    selected = getattr(reference, "reference", reference)
    fragment(selected, "component_ref")
    return {"scope_id": fragment(scope_id, "identifier"), "namespace": _namespace(selected["namespace"]),
            "record_type": PROJECTION_TYPE, "id": "certificate-" + canonical_digest(
                {key: selected[key] for key in ("namespace", "id", "version")}, "matter.semantic-certificate-slot.v1")}


def admission_ref(scope_id, *, execution, question_id, certificate, domain_scope, measure):
    return {"scope_id": scope_id, "namespace": NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": canonical_digest({"execution": execution, "question_id": question_id, "certificate": certificate,
                "domain": domain_scope, "measure": measure}, "matter.semantic-admission-slot.v1")}


def qualification_identity(request, question_id, *, domain_scope, measure, resolved_model=None):
    """Extract declared execution assumptions; packet contents are not a cohort."""
    rendered = next((item for item in request["rendered"] if item["question"]["id"] == question_id), None)
    if rendered is None:
        _fail("E_POLICY_INVALID")
    manifest = rendered["manifest"]
    context, state, binding = request["batch"]["context"], request["packet"]["state"], request["model_binding"]
    return {"resolved_model": resolved_model if resolved_model is not None else (None if binding is None else binding["model"]),
        "requested_model": context["requested_model"], "model_resolution": None if binding is None else binding["resolution"],
        **{key: context[key] for key in ("provider", "transport", "adapter_version", "mode")},
        "question": manifest["specification"], "criteria_digest": manifest["criteria_digest"], "renderer": manifest["renderer"],
        "packet_profile": state["profile"], "preparation": state["preparation"], "domain": fragment(domain_scope, "component_ref"),
        "measure": deepcopy(measure), "precision": deepcopy(request["precision"])}


class SemanticAdmission(FrozenValue):
    """Actual then-applicable method/decision status, never host authority."""

    def __init__(self, value):
        self._freeze(domain("semantic-qualification-admission", value)["value"])

    @property
    def dependencies(self):
        return self.value["dependencies"]

    @property
    def eligible(self):
        return self.value["status"] == "qualified" and self.value["decision"] in {"positive", "negative"}


class SemanticQualificationService(_MutationService):
    mutation_schema = "semantic-certificate-mutation"

    def __init__(self, storage, *, controls, receipts, reviewers, clock):
        super().__init__(storage, controls=controls)
        if not isinstance(receipts, ExecutionReceiptStore) or receipts.storage is not storage or receipts.controls is not controls or not callable(clock):
            _fail("E_POLICY_INVALID")
        self.receipts, self.clock = receipts, clock
        self.reviewers = tuple(fragment(item, "component_ref") for item in reviewers)
        if not self.reviewers or len(self.reviewers) > 128:
            _fail("E_POLICY_INVALID")

    def _now(self, as_of=None):
        # A caller's earlier sample cannot backdate present applicability. Hosts
        # inject clocks for simulation, as in ControlService._time.
        now = fragment(self.clock(), "known_time")
        if as_of is not None and compare_times(fragment(as_of, "known_time"), now) > 0:
            _fail("E_POLICY_INVALID")
        return now

    def prepare_install(self, certificate, *, command_id, idempotency_key, actor, authority):
        if not isinstance(certificate, SemanticCertificate):
            _fail("E_POLICY_INVALID")
        return self._prepare(_control_command(self.controls,
            payload={"definition": certificate.value, "previous": None, "revoked": False, "reason": "Host admitted an already reviewed certificate."},
            schema=self.mutation_schema, target=certificate_ref(self.scope_id, certificate), command_id=command_id,
            idempotency_key=idempotency_key, actor=actor, authority=authority, kind="decision"))

    def prepare_revoke(self, certificate, *, command_id, idempotency_key, actor, authority, reason):
        with self.storage.snapshot() as view:
            current, definition = self._certificate(view, getattr(certificate, "reference", certificate))
        return self._prepare(_control_command(self.controls,
            payload={"definition": definition.value, "previous": pin(current), "revoked": True, "reason": fragment(reason, "text")},
            schema=self.mutation_schema, target=entity_ref(current), command_id=command_id,
            idempotency_key=idempotency_key, actor=actor, authority=authority, kind="correction"))

    def _certificate(self, view, reference):
        record = view.get(certificate_ref(self.scope_id, reference))
        value = _value("semantic-certificate-state", record["value"])
        definition = SemanticCertificate(value["certificate"])
        if value["scope_id"] != self.scope_id or definition.reference != reference:
            _fail("E_EVIDENCE_INVALID")
        return record, definition

    def _evaluation(self, view, definition):
        record = validate_record(view.get(definition.value["evaluation"]))
        if record["record_type"] != "receipt" or record["provenance"]["origin"] != "host" or record["provenance"]["producer"] not in self.reviewers:
            _fail("E_AUTHORITY_REQUIRED")
        report = _value("semantic-qualification-evaluation", record["body"]["details"])
        artifacts = [view.get(ref) for ref in report["artifacts"]]
        if any(item["scope_id"] != self.scope_id for item in artifacts):
            _fail("E_SCOPE_FORBIDDEN")
        return record, report, artifacts

    def _read_targets(self, view, payload):
        definition = SemanticCertificate(payload["definition"])
        targets = [certificate_ref(self.scope_id, definition)]
        if not payload["revoked"]:
            report, _, artifacts = self._evaluation(view, definition)
            targets.extend(_targets([pin(report), *[pin(item) for item in artifacts]]))
        return targets

    def _state(self, view, command, payload, *, preparing):
        definition = SemanticCertificate(payload["definition"])
        address = certificate_ref(self.scope_id, definition)
        control = command["body"]["control"]["body"]
        if control["scope"]["targets"] != [address] or control["control_kind"] != ("correction" if payload["revoked"] else "decision"):
            _fail("E_SCOPE_FORBIDDEN")
        old, old_control = self._prior(view, command, payload, address, "semantic-certificate-state", preparing=preparing)
        if payload["revoked"]:
            if old is None or _value("semantic-certificate-state", old["value"])["certificate"] != definition.value:
                _fail("E_DEPENDENCY_STALE")
        elif old is not None:
            _fail("E_SOURCE_IDENTITY_CONFLICT")
        return {"old": old, "old_control": old_control, "targets": self._read_targets(view, payload)}

    def _authorize(self, view, command, targets):
        _, payload = self._payload(command)
        self.controls.policy.authorize(view, actor=command["actor"], authority=command["authority"],
            targets=targets, capability="correction" if payload["revoked"] else "assessment")
        return super()._authorize(view, command, targets)

    def _write(self, tx, payload, state, control):
        definition = SemanticCertificate(payload["definition"])
        tx.put_projection(certificate_ref(self.scope_id, definition), domain("semantic-certificate-state",
            {"scope_id": self.scope_id, "certificate": definition.value, "revoked": payload["revoked"], "control": control}))

    def _applicability(self, view, certificate, actual, now):
        dependencies = []
        if certificate is None:
            return "unknown", "certificate_missing", None, None, dependencies
        try:
            stored, definition = self._certificate(view, certificate)
        except StorageError as error:
            if error.code == "E_NOT_FOUND":
                return "unknown", "certificate_not_admitted", None, None, dependencies
            raise
        dependencies.append(pin(stored))
        if stored["value"]["value"]["revoked"]:
            return "revoked", "certificate_revoked", stored, definition, dependencies
        if compare_times(now, definition.value["valid_from"]) < 0:
            return "mismatched", "certificate_not_yet_valid", stored, definition, dependencies
        if compare_times(now, definition.value["valid_until"]) >= 0:
            return "expired", "certificate_expired", stored, definition, dependencies
        if actual["resolved_model"] is None:
            return "unqualified", "model_unresolved", stored, definition, dependencies
        if actual["model_resolution"] is None:
            return "unqualified", "model_resolution_unavailable", stored, definition, dependencies
        for field in ("resolved_model", "requested_model", "model_resolution", "provider", "transport", "adapter_version", "mode",
                      "question", "criteria_digest", "renderer", "packet_profile", "preparation", "domain", "measure", "precision"):
            if not _same(actual[field], definition.value["identity"][field]):
                return "mismatched", field + "_mismatch", stored, definition, dependencies
        report_record, report, artifacts = self._evaluation(view, definition)
        dependencies.extend([pin(report_record), *[pin(item) for item in artifacts]])
        if not _same(report["identity"], definition.value["identity"]):
            return "unqualified", "evaluation_identity_mismatch", stored, definition, dependencies
        if not _same(report["regions"], definition.value["regions"]):
            return "unqualified", "evaluation_regions_mismatch", stored, definition, dependencies
        if report["status"] != "passed":
            return "unqualified", "held_out_" + report["status"], stored, definition, dependencies
        if report["labels"] != "independent":
            return "unqualified", "independent_labels_required", stored, definition, dependencies
        for polarity, region in definition.value["regions"].items():
            if region is None:
                continue
            support = report["support"][polarity]
            if support is None or not support["passed"]:
                return "unqualified", polarity + "_support_failed", stored, definition, dependencies
            if not (1 <= support["minimum_episodes"] <= support["accepted"] <= support["episodes"]
                    and support["errors"] <= support["accepted"]):
                return "unqualified", polarity + "_support_insufficient", stored, definition, dependencies
            target, lower = _decimal(support["target_accuracy"]), _decimal(support["lower_accuracy_bound"])
            observed = Fraction(support["accepted"] - support["errors"], support["accepted"])
            if not 0 <= target <= lower <= 1 or Fraction(str(lower)) > observed:
                return "unqualified", polarity + "_accuracy_failed", stored, definition, dependencies
        return "qualified", "applicable_reviewed_method", stored, definition, dependencies

    @staticmethod
    def _decision(answer, definition):
        name = definition.value["identity"]["measure"]["name"]
        primitive = answer["primitive"]
        if (name == "probability" and primitive != "proposition_probability" or name == "score" and primitive != "score"
                or name in {"confidence", "choice_probability"} and primitive != "choice"):
            return None, "abstained", "measure_primitive_mismatch"
        value = answer.get({"probability": "probability", "score": "score", "confidence": "confidence"}.get(name)) if name != "choice_probability" else answer["probabilities"].get(answer["choice"])
        if value is None:
            return None, "abstained", "measure_unavailable"
        number = _decimal(value)
        for polarity, region in definition.value["regions"].items():
            if region is None:
                continue
            if primitive != "choice" and region["choices"]:
                return value, "abstained", "region_primitive_mismatch"
            if region["choices"] and answer["choice"] not in region["choices"]:
                continue
            if _inside(number, region):
                return value, polarity, "declared_" + polarity + "_region"
        return value, "abstained", "undecided_region"

    def inspect(self, view, execution, *, question_id, certificate, domain_scope, measure, token, as_of=None, request=None):
        now = self._now(as_of)
        record = view.get(pin(execution) if type(execution) is dict and "body" in execution else execution)
        if type(execution) is dict and "body" in execution and not _same(record, execution):
            _fail()
        value = self.receipts._details(record)
        observations = [pin(record)]
        self.receipts._validate_result(value)
        self.receipts._current(view, value)
        # A reuse observation is audit evidence, not a new provider trial.
        # Bind admission to the actual original execution and preserve the
        # intervening observation pins only as dependencies.
        while value["phase"] == "reused":
            if len(observations) >= 128 or value["source_execution"] in observations:
                _fail("E_BUDGET_EXHAUSTED")
            original = view.get(value["source_execution"])
            prior = self.receipts._details(original)
            if any(not _same(value[field], prior[field]) for field in ("result", "normalized_digest", "execution_key")):
                _fail()
            self.receipts._validate_result(prior)
            self.receipts._current(view, prior)
            record, value = original, prior
            observations.append(pin(record))
        chosen = request or value["request"]
        self.receipts._request(view, chosen, value["control_token"], value["access_context"])
        if request is not None and execution_key(Batch(chosen["batch"]), rendered=chosen["rendered"], precision=_precision(chosen["precision"]),
                model_binding=chosen["model_binding"], parents=value["parents"], token=value["control_token"],
                dependencies=chosen["packet"]["dependencies"], stage=chosen["stage"]) != value["execution_key"]:
            _fail("E_DEPENDENCY_STALE")
        result = value["result"]
        actual = qualification_identity(chosen, question_id, domain_scope=domain_scope, measure=measure,
            resolved_model=None if result is None else result["resolved_model"])
        if result is not None and result["resolved_model"] is None:
            actual["resolved_model"] = None
        sources = self.receipts._audit(view, value)
        targets = _targets([*sources, *([] if certificate is None else [certificate_ref(self.scope_id, certificate)])])
        self.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])}, targets)
        status, reason, stored, definition, deps = self._applicability(view, certificate, actual, now)
        method, decision, measured = status, None, None
        if result is None or result["admission"]["primitive_status"] != "valid" or not result["admission"]["exact_numeric"]:
            if status == "qualified":
                status, method, reason = "unqualified", "unqualified", "whole_answer_set_invalid"
        elif status == "qualified":
            diagnostic = next((item for item in result["diagnostics"] if item["id"] == question_id), None)
            if diagnostic is None or diagnostic["answer"] is None:
                status, method, reason = "unqualified", "unqualified", "answer_unavailable"
            else:
                measured, decision, reason = self._decision(diagnostic["answer"], definition)
                if decision == "abstained":
                    status = "abstained"
                else:
                    self.controls.require_current(view, token, capability="assessment", targets=targets, as_of=now)
        dependencies = {canonical_bytes(ref): ref for ref in [*observations, *sources, *value["parents"], *deps]}
        context = {"schema_version": "1.0", "token": domain("control-token", token), "measure": measure,
            "previous": None, "previous_registration": None, "access_context": value["access_context"], "captured_at": now}
        return SemanticAdmission({"schema_version": "1.0", "scope_id": self.scope_id, "execution": pin(record),
            "question_id": question_id, "certificate": certificate, "certificate_state": None if stored is None else pin(stored),
            "domain": domain_scope, "measure": measure, "status": status, "method_qualification": method,
            "reason": reason, "decision": decision, "measure_value": measured, "at": now,
            "dependencies": list(dependencies.values()), "host_authority_granted": False, "raw_result_modified": False, "request": context})

    def classifier(self, *, question_id, certificate, domain_scope, measure, token):
        """Exact MAT-030 reuse classifier; no caller-supplied qualified flag."""
        def classify(*, view, execution, request, as_of):
            decision = self.inspect(view, execution, question_id=question_id, certificate=certificate,
                domain_scope=domain_scope, measure=measure, token=token, as_of=as_of, request=request)
            return {"status": "qualified" if decision.eligible else decision.value["status"], "certificate": certificate}
        return classify

    def stage_classifier(self, *, certificates, domain_scope, measure, token):
        """MAT-029 callback; only actual persisted MAT-030 views can qualify.

        A detached raw batch or an undecided region remains unknown. This
        callback is classification, never certificate issuance or action power.
        """
        selected = {fragment(key, "identifier"): fragment(value, "component_ref") for key, value in certificates.items()}
        if len(selected) > 128:
            _fail("E_BUDGET_EXHAUSTED")
        def classify(*, question, stage_input, batch, batch_result, as_of):
            certificate = selected.get(question["id"])
            observation = batch_result.get("execution_observation")
            if observation is None or certificate is None:
                return {"status": "unknown", "certificate": certificate}
            actual_batch = Batch(batch)
            restored = self.receipts.view_result({"status": "reused" if observation["reused"] else "completed",
                "execution": observation["execution"]}, actual_batch).value
            for field in ("batch_digest", "diagnostics", "precision_profile", "resolved_model", "admission", "execution_observation", "faults", "execution_status"):
                if not _same(restored[field], batch_result[field]):
                    _fail("E_EVIDENCE_INVALID")
            with self.storage.snapshot() as view:
                record = view.get(observation["execution"])
                metadata = self.receipts._details(record)
                rendered = next((item for item in metadata["request"]["rendered"] if item["question"]["id"] == question["id"]), None)
                selected_renderings = stage_input.value["rendered_questions"]
                if (not _same(metadata["request"]["packet"], stage_input.packet.value) or rendered is None
                        or not _same(question["specification"], rendered["manifest"]["specification"])
                        or not any(_same(rendered, item) for item in selected_renderings)
                        or any(not any(_same(item, actual) for actual in metadata["request"]["rendered"]) for item in selected_renderings)):
                    _fail("E_EVIDENCE_INVALID")
                decision = self.inspect(view, record, question_id=question["id"], certificate=certificate,
                    domain_scope=domain_scope, measure=measure, token=token, as_of=as_of)
            status = "qualified" if decision.eligible else {"mismatched": "mismatch", "expired": "expired", "revoked": "revoked"}.get(decision.value["status"], "unknown")
            return {"status": status, "certificate": certificate}
        return classify

    def preflight(self, view, request, *, question_id, certificate, domain_scope, measure, token, access_context=None, as_of=None):
        self.receipts._request(view, request, token, access_context)
        now = self._now(as_of)
        actual = qualification_identity(request, question_id, domain_scope=domain_scope, measure=measure)
        sources = request["packet"]["dependencies"]
        for reference in sources:
            if pin(view.get(entity_ref(reference))) != reference:
                _fail("E_DEPENDENCY_STALE")
        targets = _targets([*sources, *([] if certificate is None else [certificate_ref(self.scope_id, certificate)])])
        self.controls.require_current(view, token, capability="assessment", targets=targets, as_of=now)
        self.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])}, targets)
        status, reason, _, _, deps = self._applicability(view, certificate, actual, now)
        return {"status": "applicable_pending_execution" if status == "qualified" else status,
            "reason": "actual_resolved_execution_required" if status == "qualified" else reason,
            "certificate": certificate, "dependencies": deps, "host_authority_granted": False}


    def _admission_command(self, command):
        command = validate_command(command)
        if command["operation"] != "admit_semantic_result" or command["scope_id"] != self.scope_id:
            _fail("E_SCOPE_FORBIDDEN")
        return command

    def _admission_state(self, view, command, request, now, *, original):
        body = command["body"]
        token = _value("control-token", request["token"])
        if command["actor"] != token["actor"] or command["authority"] != entity_ref(token["authority"]):
            _fail("E_AUTHORITY_REQUIRED")
        admission = self.inspect(view, body["execution"], question_id=body["question_id"],
            certificate=body["certificate"], domain_scope=body["domain"], measure=request["measure"], token=token, as_of=now)
        metadata = self.receipts._details(view.get(body["execution"]))
        if not _same(request["access_context"], metadata["access_context"]):
            _fail("E_AUTHORITY_REQUIRED")
        address = admission_ref(self.scope_id, execution=admission.value["execution"], question_id=body["question_id"],
            certificate=body["certificate"], domain_scope=body["domain"], measure=request["measure"])
        previous = _lookup(view, address)
        registered = _lookup(view, registration_ref(address))
        if original and (request["previous"] != (None if previous is None else pin(previous)) or
                request["previous_registration"] != (None if registered is None else recomputation_token(view, pin(registered)))):
            _fail("E_DEPENDENCY_STALE")
        # An unqualified observation is still a host operation, never permission
        # to bypass the original token merely because it will not admit a head.
        targets = _targets([*admission.dependencies, *command_targets(command)])
        self.controls.require_current(view, token, capability="assessment", targets=targets, as_of=now)
        self.controls._audit(view, command, targets)
        conditions = []
        if admission.value["certificate_state"] is not None:
            _, definition = self._certificate(view, body["certificate"])
            future = [point for point in (definition.value["valid_from"], definition.value["valid_until"])
                      if compare_times(point, now) > 0]
            if future:
                from ..time import known_time_key
                conditions = [{"condition": definition.reference, "next_check_at": min(future, key=known_time_key),
                    "expires_at": {"state": "unknown", "reason": "not_applicable"}}]
        manifest = capture_dependencies(view, scope_id=self.scope_id, as_of=now, positive=admission.dependencies,
            time_conditions=conditions, control_token=token, controls=self.controls)
        return admission, address, previous, registered, manifest

    def prepare_admission(self, command, *, token, measure, access_context=None):
        command = self._admission_command(command)
        if REQUEST_EXTENSION in command.get("extensions", {}):
            _fail("E_SCHEMA_INVALID")
        now = fragment(self.clock(), "known_time")
        # The actual original execution determines its access context. An
        # explicit context must agree; no capture or renewal occurs here.
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            metadata = self.receipts._details(view.get(command["body"]["execution"]))
            selected_access = metadata["access_context"] if access_context is None else getattr(access_context, "value", access_context)
            request = {"schema_version": "1.0", "token": domain("control-token", token), "measure": deepcopy(measure),
                "previous": None, "previous_registration": None, "access_context": selected_access, "captured_at": now}
            domain("semantic-qualification-request", request)
            _, _, previous, registered, _ = self._admission_state(view, command, request, now, original=False)
            request.update(previous=None if previous is None else pin(previous),
                previous_registration=None if registered is None else recomputation_token(view, pin(registered)))
            command["expected_revisions"] = sorted([pin(item) for item in view.records.values()], key=canonical_bytes)
        command.setdefault("extensions", {})[REQUEST_EXTENSION] = domain("semantic-qualification-request", request)
        return validate_command(command)

    def admit(self, command):
        command = self._admission_command(command)
        request = _value("semantic-qualification-request", command.get("extensions", {}).get(REQUEST_EXTENSION))
        def handler(tx):
            now = fragment(self.clock(), "known_time")
            admission, address, _, _, manifest = self._admission_state(tx, command, request, now, original=True)
            value = admission.value
            value["request"] = request
            stored = tx.put_projection(address, domain("semantic-qualification-admission", value))
            register_dependency(tx, pin(stored), manifest, as_of=now, controls=self.controls, previous=request["previous_registration"])
            return tx.success("recorded", {"execution": value["execution"], "admission": pin(stored),
                "qualification": value["status"]})
        def audit(view):
            metadata = self.receipts._details(view.get(command["body"]["execution"]))
            self.receipts._audit(view, metadata)
            self.controls._audit(view, command, _targets([*request["token"]["value"]["targets"], *command_targets(command)]))
        return self.storage.execute(command, handler, replay_guard=audit, dependency_error_code="E_DEPENDENCY_STALE")

    def current(self, reference, *, read_token):
        with self.storage.snapshot() as view:
            stored = view.get(reference)
            value = _value("semantic-qualification-admission", stored["value"])
            if stored["namespace"] != NAMESPACE or value["scope_id"] != self.scope_id:
                _fail("E_SCOPE_FORBIDDEN")
            self.controls.require_current(view, read_token, capability="read", targets=value["request"]["token"]["value"]["targets"])
            require_current_dependency(view, registration_ref(stored), as_of=self.clock(), controls=self.controls)
            metadata = self.receipts._details(view.get(value["execution"]))
            self.receipts._current(view, metadata)
            return stored

    def history(self, reference, *, read_token):
        """Read a recorded then-applicable decision with current READ authority."""
        with self.storage.snapshot() as view:
            stored = view.get(reference)
            value = _value("semantic-qualification-admission", stored["value"])
            if stored["namespace"] != NAMESPACE or value["scope_id"] != self.scope_id:
                _fail("E_SCOPE_FORBIDDEN")
            self.controls.require_current(view, read_token, capability="read", targets=value["request"]["token"]["value"]["targets"])
            self.receipts._audit(view, self.receipts._details(view.get(value["execution"])))
            return stored
