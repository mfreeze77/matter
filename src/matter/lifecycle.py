"""MAT-017 evidence-backed domain projections over the existing storage port.

Host-installed edges interpret typed claims, never source text or confidence.
Preparation retains the original controls and exact reads; transition checks
them again in one transaction. History is independent of current validity.
"""

from copy import deepcopy
from importlib.resources import files
import json

from ._rule_values import FrozenValue, descriptor, domain, fragment
from .assessments import AssessmentService, _Tracked, _read_targets
from .canonical import canonical_bytes, canonical_digest
from .claims import ClaimService, read_claim
from .contracts import validate_command, validate_record
from .controls import ControlService, _active, _effect, command_targets
from .dependencies import (capture_dependencies, register_dependency, registration_ref,
                           recomputation_token, require_current_dependency)
from .identity_groups import read_group
from .occurrences import OccurrenceService, _read_membership
from .profiles import ProfileRegistry
from .rules import SchemaDefinition, SchemaRegistry
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times, contains, knowledge_eligible


NAMESPACE = "matter.lifecycle"
REQUEST_EXTENSION = "matter:lifecycle-request"
_ENGINE = descriptor("matter", "lifecycle", "1.0", {
    "edges": "explicit-exact", "correspondence": "typed-subject-condition",
    "effective_time": "declared-claim-start", "knowledge": "actual-commit",
    "reopening": "distinct-accepted-occurrence-or-explicit-correction",
    "authority": "original-host-control", "publication": "atomic-registered-projection",
}, "matter.lifecycle-engine.v1")


def _fail(detail="The lifecycle declaration is invalid.", code="E_POLICY_INVALID"):
    raise StorageError(code, detail)


def lifecycle_schema():
    """Self-contained domain schema to install alongside a lifecycle profile."""
    value = json.loads(files("matter._schemas").joinpath("lifecycle-profile.schema.json").read_text())
    return SchemaDefinition("matter", "lifecycle-profile", "1.0", value)


def _pointer(value, pointer):
    # RFC 6901 only; no expression evaluation or implicit property search.
    current = value
    for raw in pointer.split("/")[1:]:
        if "~" in raw.replace("~0", "").replace("~1", ""):
            _fail("A lifecycle selector is not a JSON Pointer.")
        part = raw.replace("~1", "/").replace("~0", "~")
        if type(current) is dict and part in current:
            current = current[part]
        elif type(current) is list and part.isdigit() and str(int(part)) == part and int(part) < len(current):
            current = current[int(part)]
        else:
            _fail("The typed evidence lacks a declared lifecycle field.", "E_EVIDENCE_INVALID")
    return deepcopy(current)


class LifecycleDefinition(FrozenValue):
    """Immutable explicit state/edge meanings; construction grants no authority."""
    __slots__ = ()

    def __init__(self, value, *, schemas):
        if not isinstance(schemas, SchemaRegistry):
            _fail()
        declaration = {"schema": lifecycle_schema().reference, "value": value}
        schemas.validate(declaration)
        if len(canonical_bytes(value)) > 262144:
            _fail(code="E_BUDGET_EXHAUSTED")
        states = {item["name"]: item["role"] for item in value["states"]}
        if len(states) != len(value["states"]) or value["initial_state"] not in states:
            _fail("Lifecycle states must be distinct and include the initial state.")
        if states[value["initial_state"]] != "unknown":
            _fail("An unobserved condition must start unknown.")
        identities = set()
        for edge in value["edges"]:
            identity = edge["id"]
            if identity in identities or not set(edge["from_states"]) <= set(states) or edge["to_state"] not in states:
                _fail("Lifecycle edges must be unambiguous and name declared states.")
            identities.add(identity)
            schemas.resolve(edge["claim_schema"])
            for selector in (edge["condition_pointer"], edge["signal_pointer"]):
                # Validate escape spelling without interpreting an example.
                if "~" in selector.replace("~0", "").replace("~1", ""):
                    _fail("A lifecycle selector is not a JSON Pointer.")
            trigger, target = edge["trigger"], states[edge["to_state"]]
            if trigger == "resolution" and target != "resolved":
                _fail("A resolution edge must declare a resolved state.")
            if trigger == "recurrence" and (target != "open" or any(states[x] != "resolved" for x in edge["from_states"])):
                _fail("Recurrence must explicitly reopen a resolved condition.")
            if trigger == "retraction":
                if (target not in {"unknown", "open"} or edge["assessment_statuses"] != ["unknown"] or
                        any(states[x] != "resolved" for x in edge["from_states"])):
                    _fail("Retraction removes support; it cannot assert a contrary fact.")
            elif trigger != "correction" and (edge["assessment_statuses"] != ["supported"] or edge["assessment_states"] != ["complete"]):
                _fail("Ordinary lifecycle facts require a complete supported assessment.")
        self._freeze(value)

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["semantic_version"], value, "matter.lifecycle-definition.v1")

    @property
    def extension(self):
        return {"schema": lifecycle_schema().reference, "value": self.value}

    def edge_reference(self, identity):
        candidates = [edge for edge in self.value["edges"] if edge["id"] == identity]
        if len(candidates) != 1:
            _fail("Select one exact installed lifecycle edge.")
        edge = candidates[0]
        return descriptor(self.value["namespace"], edge["id"], edge["semantic_version"],
                          {"definition": self.reference, "edge": edge}, "matter.lifecycle-edge.v1")

    def edge(self, reference):
        fragment(reference, "component_ref")
        for edge in self.value["edges"]:
            if self.edge_reference(edge["id"]) == reference:
                return edge
        _fail("The requested edge is not installed by this lifecycle profile.", "E_AUTHORITY_REQUIRED")


def lifecycle_ref(matter, *, profile, condition):
    subject, policy = fragment(entity_ref(matter), "matter_ref"), fragment(profile, "component_ref")
    if len(canonical_bytes(condition)) > 65536:
        _fail("The declared condition exceeds its bounded identity budget.", "E_BUDGET_EXHAUSTED")
    key = {"matter": subject, "profile": {key: policy[key] for key in ("namespace", "id")}, "condition": condition}
    return {"scope_id": subject["scope_id"], "namespace": NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "condition-" + canonical_digest(key, "matter.lifecycle-lane.v1")}


def _event_ref(address, occurrence):
    return {**address, "namespace": "matter.lifecycle_events",
            "id": "event-" + canonical_digest({"lane": address, "occurrence": entity_ref(occurrence)}, "matter.lifecycle-event.v1")}


def _lookup(view, ref):
    try:
        return view.get(ref)
    except StorageError as error:
        if error.code != "E_NOT_FOUND":
            raise
        return None


class _Reads(_Tracked):
    def __init__(self, view, scope):
        super().__init__(view, scope)
        self.bytes = 0

    def _remember(self, value):
        identity = tuple(value[key] for key in ("scope_id", "namespace", "id"))
        if identity not in self.records:
            self.bytes += len(canonical_bytes(value))
        result = super()._remember(value)
        if len(self.records) > 4096 or self.bytes > 8388608:
            _fail("Lifecycle preparation exceeds its bounded read budget.", "E_BUDGET_EXHAUSTED")
        return result

    def exact(self, reference):
        result = self.get(entity_ref(reference))
        if pin(result) != reference:
            _fail("A lifecycle dependency is no longer current.", "E_DEPENDENCY_STALE")
        return result


class LifecycleService:
    """Trusted host adapter; storage, clock and optional decision selector are host-owned.

    The decision validator must interpret an authenticated decision's exact
    domain payload against the supplied matter/profile/edge/condition. Returning
    true alone cannot bypass the control service, current assessment or evidence
    guards. No validator is called for ordinary automatic maintenance.
    """

    def __init__(self, storage, *, profiles, definitions, schemas, claims, occurrences,
                 assessments, controls, clock, decision_validator=None):
        if (not isinstance(profiles, ProfileRegistry) or not isinstance(schemas, SchemaRegistry) or
                not isinstance(claims, ClaimService) or not isinstance(occurrences, OccurrenceService) or
                not isinstance(assessments, AssessmentService) or not isinstance(controls, ControlService) or
                not callable(clock) or decision_validator is not None and not callable(decision_validator)):
            _fail()
        values = tuple(definitions)
        if not values or len(values) > 128 or any(not isinstance(value, LifecycleDefinition) for value in values):
            _fail()
        identities = [(value.reference["namespace"], value.reference["id"], value.reference["version"]) for value in values]
        if len(set(identities)) != len(identities):
            _fail("Lifecycle definition versions may be installed only once.")
        if any(service.scope_id != storage.scope_id for service in (claims, occurrences, assessments, controls)):
            _fail(code="E_SCOPE_FORBIDDEN")
        if assessments.controls is not controls:
            _fail("Lifecycle and assessment consumption must share the trusted control service.")
        self.storage, self.scope_id = storage, storage.scope_id
        self.profiles, self.definitions, self.schemas = profiles, values, schemas
        self.claims, self.occurrences, self.assessments = claims, occurrences, assessments
        self.controls, self.clock, self.decision_validator = controls, clock, decision_validator

    def _definition(self, reference):
        profile = self.profiles.resolve(reference)
        component = profile.value["components"].get("lifecycle", {})
        if self.scope_id not in component.get("data_scopes", []):
            _fail("The lifecycle profile does not admit this data scope.", "E_SCOPE_FORBIDDEN")
        extensions = component.get("lifecycle_extensions", [])
        matches = [value for value in self.definitions if value.extension in extensions]
        if len(matches) != 1:
            _fail("The exact profile must install one lifecycle declaration.")
        return profile, matches[0]

    def _request(self, command):
        result = validate_command(command)
        if result["operation"] != "request_transition" or result["scope_id"] != self.scope_id:
            _fail(code="E_SCOPE_FORBIDDEN")
        return result

    @staticmethod
    def _value(record):
        wrapped = record["value"]
        if wrapped != domain("lifecycle-state", wrapped["value"]):
            _fail("The lifecycle state has an unknown schema.", "E_EVIDENCE_INVALID")
        return wrapped["value"]

    def _assessment(self, view, reference, profile, now):
        return self.assessments.read_current(view, reference, profile, as_of=now)

    def _inspect(self, view, command, request, now, *, retain_previous):
        body, token = command["body"], request["token"]["value"]
        if request["token"] != domain("control-token", token):
            _fail(code="E_AUTHORITY_REQUIRED")
        if token["actor"] != command["actor"] or entity_ref(token["authority"]) != command["authority"]:
            _fail(code="E_AUTHORITY_REQUIRED")
        self.controls.require_current(view, token, capability="transition", targets=command_targets(command), as_of=now)
        profile, definition = self._definition(request["profile"])
        edge = definition.edge(body["profile_edge"])
        group = read_group(view, self.scope_id, body["matter"])
        if pin(group["survivor"]) != body["matter"]:
            _fail("A redirected subject cannot transition under its old identity.", "E_DEPENDENCY_STALE")
        address = lifecycle_ref(body["matter"], profile=profile.reference, condition=request["condition"])
        current = _lookup(view, address)
        previous = None if current is None else pin(current)
        registration = _lookup(view, registration_ref(address))
        prior_registration = None if registration is None else recomputation_token(view, pin(registration))
        if retain_previous and (request["previous"] != previous or request["previous_registration"] != prior_registration):
            _fail("The original lifecycle revision or validity generation changed.", "E_DEPENDENCY_STALE")
        prior = None if current is None else self._value(current)
        if prior is not None and (prior["matter"] != body["matter"] or prior["profile"] != profile.reference or
                                  canonical_bytes(prior["condition"]) != canonical_bytes(request["condition"])):
            _fail("The lifecycle lane holds another exact profile or subject revision.", "E_DEPENDENCY_STALE")
        revision = 1 if prior is None else prior["lifecycle_revision"]
        if body["lifecycle_revision"] != revision:
            _fail("The expected lifecycle revision changed.", "E_DEPENDENCY_STALE")
        state = definition.value["initial_state"] if prior is None else prior["state"]
        claim = read_claim(view, self.scope_id, request["claim"])
        lineage = self.claims._lineage(view, request["claim"])
        superseded = [ref for item in lineage for ref in item.get("supersedes", [])]
        if request["claim"] in superseded:
            _fail("Superseded claims cannot establish a lifecycle transition.", "E_DEPENDENCY_STALE")
        observation = view.exact(request["occurrence"])
        validate_record(observation)
        _read_membership(view, observation)
        assessment, lane = self._assessment(view, body["assessment"], profile, now)
        # Admission requires the selected current lane. The durable domain
        # result retains this exact proof; replacing a lane later is not by
        # itself a change to the facts which established the domain state.
        publication = self.assessments._current_value(lane)["publication"]
        source_pins = list(claim["body"]["attribution"])
        sources = []
        for ref in source_pins:
            source = view.exact(ref)
            sources.append(source)
            if source["record_type"] == "observation":
                if knowledge_eligible(source["body"]["available_at"], assessment["body"]["assessed_as_of"]) is not True:
                    _fail("The evidence was unavailable at the assessment knowledge boundary.", "E_EVIDENCE_UNAVAILABLE")
        seen = _lookup(view, _event_ref(address, observation))
        hold, substantive_hold = None, False
        def held(reason, conflict=False, idempotent=False):
            nonlocal hold, substantive_hold
            substantive_hold = substantive_hold or not idempotent
            if hold is None:
                hold = ("held_for_conflict" if conflict else "held_for_evidence", reason)
        if state not in edge["from_states"]:
            held("The declared edge does not leave the current state.", True, idempotent=True)
        if assessment["body"]["matter"] != body["matter"]:
            held("The assessment concerns another subject.")
        if request["claim"] not in body["evidence"] or request["occurrence"] not in body["evidence"]:
            held("The triggering claim and occurrence must both be declared evidence.")
        if (claim["body"]["subject"] != entity_ref(body["matter"]) or claim["body"]["predicate"] != edge["predicate"] or
                claim["body"]["value"]["schema"] != edge["claim_schema"]):
            held("The typed claim does not match this subject and declared edge.")
        else:
            self.schemas.validate(claim["body"]["value"])
            value = claim["body"]["value"]["value"]
            if canonical_bytes(_pointer(value, edge["condition_pointer"])) != canonical_bytes(request["condition"]):
                held("The evidence concerns another condition or circumstances.")
            if canonical_bytes(_pointer(value, edge["signal_pointer"])) not in {canonical_bytes(item) for item in edge["accepted_signals"]}:
                held("The evidence does not establish the declared trigger.")
        if claim["provenance"]["origin"] not in edge["allowed_origins"]:
            held("The claim origin is outside the declared evidence standard.")
        if any(source["provenance"]["origin"] not in edge["allowed_origins"] for source in sources):
            held("An evidence source is outside the declared origin standard.")
        if len([item for item in lineage if pin(item) not in superseded]) != 1:
            held("The evidence has unresolved correction branches.", True)
        if not source_pins or not any(ref in observation["body"]["observations"] for ref in source_pins):
            held("The claim lacks a source assigned to the accepted occurrence.")
        positives = assessment["body"]["dependency_manifest"]["positive"]
        if any(ref not in positives for ref in (request["claim"], request["occurrence"])):
            held("The assessment does not guard the complete trigger.")
        propositions = [item for item in assessment["body"]["propositions"] if item["claim"] == request["claim"]]
        if len(propositions) != 1 or propositions[0]["evidence_standard"] != profile.component_references.get("evidence"):
            held("The assessment does not establish one qualifying proposition.")
        elif propositions[0]["status"] not in edge["assessment_statuses"]:
            held("The assessed proposition does not meet this edge's evidence standard.", propositions[0]["status"] == "mixed")
        if assessment["body"]["evaluation_state"] not in edge["assessment_states"]:
            held("Incomplete evaluation cannot establish this edge.")
        effective = body["effective_at"]
        if (effective != claim["body"]["applicability"]["start"] or
                contains(claim["body"]["applicability"], effective) is not True or
                compare_times(effective, now) not in {-1, 0}):
            held("The effective time is not established by the declared claim interval.")
        if not edge["allow_past_effective"] and compare_times(effective, assessment["body"]["assessed_as_of"]) == -1:
            held("This edge does not admit effectivity before its admitted assessment knowledge boundary.")
        if knowledge_eligible(assessment["body"]["assessed_as_of"], now) is not True:
            held("The assessment knowledge cut lies in the future.")
        trigger = edge["trigger"]
        if trigger in {"establish", "resolution", "recurrence"} and seen is not None:
            held("Redelivery of an accepted occurrence cannot change lifecycle state.", idempotent=True)
        if trigger == "recurrence":
            prior_event = None if prior is None else view.get(entity_ref(prior["basis"]["occurrence"]))
            if prior_event is not None:
                _read_membership(view, prior_event)
                prior_receipt = view.get(prior["last_transition"])
                details = prior_receipt["body"]["details"]
                if details != domain("lifecycle-transition", details["value"]):
                    _fail("The prior lifecycle chronology lacks its original proof.", "E_EVIDENCE_INVALID")
                proof = details["value"]["assessment_publication"]["value"]["preparation"]
                anchors = [record for record in proof["records"] if entity_ref(record) == entity_ref(prior_event)]
                if (len(anchors) != 1 or pin(anchors[0]) != prior["basis"]["occurrence"] or
                        anchors[0]["body"]["occurred_at"] != prior_event["body"]["occurred_at"]):
                    held("The prior happening's chronology changed and requires explicit correction.", True)
            if (prior_event is None or compare_times(observation["body"]["occurred_at"], prior_event["body"]["occurred_at"]) != 1):
                held("Reopening requires a distinct later happening, not later delivery.")
            if compare_times(observation["body"]["occurred_at"], now) not in {-1, 0}:
                held("The recurrence happening is not known to precede this knowledge boundary.")
        if trigger in {"resolution", "recurrence"} and prior is not None:
            if compare_times(effective, prior["effective_at"]) not in {0, 1}:
                held("An ordinary transition cannot take effect before its corresponding condition.")
        if trigger in {"retraction", "correction"}:
            if prior is None or prior["basis"]["claim"] not in superseded:
                held("A correction must supersede the corresponding prior lifecycle basis.")
        already = False
        basis = {"claim": request["claim"], "occurrence": request["occurrence"], "assessment": body["assessment"]}
        if prior is not None and prior["state"] == edge["to_state"] and prior["basis"] == basis:
            old_receipt = view.get(prior["last_transition"])
            old_details = old_receipt["body"]["details"]
            if old_details == domain("lifecycle-transition", old_details["value"]) and old_details["value"]["edge"] == body["profile_edge"]:
                require_current_dependency(view, registration_ref(address), as_of=now, controls=self.controls)
                already = not substantive_hold
        decision = request["decision"]
        if decision is not None and not edge["requires_decision"]:
            _fail("This automatic edge does not consume a host decision.")
        if edge["requires_decision"]:
            if decision is None or self.decision_validator is None:
                _fail("This declared edge requires its applicable host decision.", "E_AUTHORITY_REQUIRED")
            control = validate_record(view.exact(decision))
            if (control["body"]["control_kind"] != "decision" or _effect(control)["action"] != "disposition" or
                    not _active(control, now) or decision not in token["active_controls"]):
                _fail("Acknowledgement or inactive control cannot authorize this decision.", "E_AUTHORITY_REQUIRED")
            try:
                valid = self.decision_validator(view, control, profile=profile.reference, edge=body["profile_edge"],
                    matter=body["matter"], condition=deepcopy(request["condition"]))
            except Exception:
                _fail("The host decision selector could not establish authority.", "E_AUTHORITY_REQUIRED")
            if valid is not True:
                _fail("The host decision does not authorize this exact transition.", "E_AUTHORITY_REQUIRED")
        positive = [body["matter"], body["assessment"], request["claim"], request["occurrence"], *source_pins]
        manifest = capture_dependencies(view, scope_id=self.scope_id, as_of=now, positive=positive,
            control_token=token, controls=self.controls)
        complete_targets = _read_targets(command, [pin(item) for item in view.records.values()])
        self.controls._audit(view, command, complete_targets)
        self.controls.require_current(view, token, capability="transition", targets=complete_targets, as_of=now)
        if self.assessments.access is not None:
            context = request.get("access_context")
            if context is None or context.get("token") != token:
                _fail("The installed access boundary requires the original transition context.", "E_AUTHORITY_REQUIRED")
            self.assessments.access.require_current(view, context, references=[pin(item) for item in view.records.values()],
                audience=assessment["body"].get("audience"))
        elif "access_context" in request:
            _fail("The original access boundary is not installed.", "E_AUTHORITY_REQUIRED")
        return {"profile": profile, "definition": definition, "edge": edge, "address": address,
            "prior": prior, "previous": previous, "previous_registration": prior_registration,
            "state": state, "revision": revision, "manifest": manifest, "hold": hold, "already": already,
            "assessment_publication": domain("assessment-publication", publication),
            "event": _event_ref(address, observation)}

    def prepare(self, command, *, profile, condition, claim, occurrence, token, decision=None, access_context=None):
        command = self._request(command)
        if REQUEST_EXTENSION in command.get("extensions", {}):
            _fail("Prepare a new request once; retry its returned command unchanged.")
        request = {"profile": fragment(profile, "component_ref"), "condition": deepcopy(condition),
            "claim": fragment(claim, "claim_dependency"), "occurrence": fragment(occurrence, "occurrence_dependency"),
            "decision": None if decision is None else fragment(decision, "control_dependency"),
            "token": domain("control-token", token), "previous": None, "previous_registration": None,
            "captured_at": fragment(self.clock(), "known_time")}
        if access_context is not None:
            request["access_context"] = deepcopy(getattr(access_context, "value", access_context))
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            result = self._inspect(view, command, request, request["captured_at"], retain_previous=False)
            request.update(previous=result["previous"], previous_registration=result["previous_registration"])
            command["expected_revisions"] = sorted([pin(item) for item in view.records.values()], key=canonical_bytes)
        command.setdefault("extensions", {})[REQUEST_EXTENSION] = domain("lifecycle-request", request)
        return validate_command(command)

    def transition(self, command):
        command = self._request(command)
        wrapped = command.get("extensions", {}).get(REQUEST_EXTENSION)
        if type(wrapped) is not dict or "value" not in wrapped or domain("lifecycle-request", wrapped["value"]) != wrapped:
            _fail("An original typed lifecycle preparation is required.")
        request = wrapped["value"]
        def handler(tx):
            now = fragment(self.clock(), "known_time")
            if compare_times(now, request["captured_at"]) == -1:
                _fail("The lifecycle knowledge clock regressed.", "E_DEPENDENCY_STALE")
            view = _Reads(tx, self.scope_id)
            result = self._inspect(view, command, request, now, retain_previous=True)
            reads = sorted([pin(item) for item in view.records.values()], key=canonical_bytes)
            if command["expected_revisions"] != reads:
                _fail("The original complete lifecycle read set changed.", "E_DEPENDENCY_STALE")
            if result["already"]:
                return tx.success("already_applied", {"matter": command["body"]["matter"],
                    "transition_receipt": result["prior"]["last_transition"], "state": result["prior"]["state"]})
            if result["hold"] is not None:
                outcome, reason = result["hold"]
                return tx.success(outcome, {"reason": reason, "evidence": command["body"]["evidence"]})
            basis = {"claim": request["claim"], "occurrence": request["occurrence"], "assessment": command["body"]["assessment"]}
            body = {"schema_version": "1.0", "matter": command["body"]["matter"], "profile": request["profile"],
                "edge": command["body"]["profile_edge"], "trigger": result["edge"]["trigger"], "condition": request["condition"],
                "from_state": result["state"], "to_state": result["edge"]["to_state"], "lifecycle_revision": result["revision"] + 1,
                "effective_at": command["body"]["effective_at"], "knowledge_at": now, "basis": basis,
                "previous_transition": None if result["prior"] is None else result["prior"]["last_transition"],
                "decision": request["decision"], "control_token": request["token"],
                "assessment_publication": result["assessment_publication"]}
            receipt = tx.insert({"schema_version": "1.0", "record_type": "receipt", "scope_id": self.scope_id,
                "namespace": NAMESPACE, "id": "transition-" + canonical_digest(command, "matter.lifecycle-command.v1"),
                "provenance": {"origin": "system", "producer": _ENGINE, "recorded_at": now,
                    "parents": [*command["body"]["evidence"], command["body"]["assessment"]]},
                "body": {"stage": "operation", "operation_id": command["command_id"], "recorded_at": now,
                    "outcome": "matter:applied", "evidence": command["body"]["evidence"], "details": domain("lifecycle-transition", body)}})
            state = {key: body[key] for key in ("schema_version", "matter", "profile", "condition", "lifecycle_revision", "effective_at", "knowledge_at", "basis")}
            state.update(state=body["to_state"], last_transition=pin(receipt))
            stored = tx.put_projection(result["address"], domain("lifecycle-state", state))
            tx.put_projection(result["event"], domain("lifecycle-event", {"transition": pin(receipt)}))
            register_dependency(tx, pin(stored), result["manifest"], as_of=now, controls=self.controls,
                previous=result["previous_registration"])
            return tx.success("applied", {"matter": command["body"]["matter"], "transition_receipt": pin(receipt), "state": state["state"]})
        def audit(view):
            self.controls._audit(view, command, command_targets(command))
            if self.assessments.access is not None:
                self.assessments.access.require_current(view, request.get("access_context", {}), references=command["expected_revisions"])
        return self.storage.execute(command, handler, replay_guard=audit, dependency_error_code="E_DEPENDENCY_STALE")

    def _audit_state(self, view, state, *, read_token=None, access_context=None):
        receipt = validate_record(view.get(state["last_transition"]))
        details = receipt["body"]["details"]
        if details != domain("lifecycle-transition", details["value"]):
            _fail(code="E_EVIDENCE_INVALID")
        token = details["value"]["control_token"]["value"]
        self.controls._view(view, actor=token["actor"], authority=entity_ref(token["authority"]),
                            capability="read", targets=token["targets"], now=fragment(self.clock(), "known_time"), audit=True)
        if read_token is not None:
            domain("control-token", read_token)
            detail = details["value"]
            proof = detail["assessment_publication"]["value"]
            targets = {canonical_bytes(ref): ref for ref in self.assessments._read_targets(proof["preparation"], proof["graph"])}
            for ref in (detail["matter"], *detail["basis"].values()):
                targets[canonical_bytes(entity_ref(ref))] = entity_ref(ref)
            targets = sorted(targets.values(), key=canonical_bytes)
            # An enclosing assessment/attention operation keeps its original
            # captured capability. Reading still needs its own actual READ
            # authorization; possession of a work token alone cannot grant it.
            self.controls.require_current(view, read_token, capability=read_token["capability"], targets=targets,
                as_of=fragment(self.clock(), "known_time"))
            self.controls._audit(view, {"actor": read_token["actor"], "authority": entity_ref(read_token["authority"])}, targets)
        if self.assessments.access is not None:
            context = deepcopy(getattr(access_context, "value", access_context))
            if read_token is None or type(context) is not dict or context.get("token") != read_token:
                _fail("The installed access boundary requires the original read context.", "E_AUTHORITY_REQUIRED")
            detail = details["value"]
            self.assessments.access.require_current(view, context, references=[detail["matter"], *detail["basis"].values()])
        return receipt

    def _basis(self, view, state, receipt, now):
        """Recheck original admitted facts without requiring the old lane.

        This proof was copied only from the actual selected current lane in
        _inspect, before the immutable transition receipt was inserted. It is
        never accepted from a request or replaced with a freshly captured token.
        """
        assessment = validate_record(view.exact(state["basis"]["assessment"]))
        wrapped = receipt["body"]["details"]["value"]["assessment_publication"]
        if wrapped != domain("assessment-publication", wrapped["value"]):
            _fail("The lifecycle basis has an unknown admission proof.", "E_EVIDENCE_INVALID")
        publication = wrapped["value"]
        preparation = self.assessments._preparation(publication["preparation"])
        request = preparation["request"]["body"]
        if (assessment["record_type"] != "assessment" or assessment["id"] != publication["assessment_id"] or
                assessment["body"]["matter"] != state["matter"] or assessment["body"]["profile"] != state["profile"] or
                request["matter"] != state["matter"] or request["profile"] != state["profile"]):
            _fail("The lifecycle basis is not the originally admitted assessment.", "E_EVIDENCE_INVALID")
        registration = _lookup(view, registration_ref(assessment))
        if registration is not None:
            require_current_dependency(view, pin(registration), as_of=now, controls=self.controls)
        admission = self.assessments._guards(view, preparation, publication["graph"], now)
        self.assessments._require_fresh_result(view, publication, assessment, now, admission)
        return assessment

    def current(self, matter, *, profile, condition, read_token=None, access_context=None):
        with self.storage.snapshot() as snapshot:
            return self.read_current(snapshot, matter, profile=profile, condition=condition,
                                     read_token=read_token, access_context=access_context)

    def read_current(self, view, matter, *, profile, condition, read_token=None, access_context=None):
        """The same guarded current read within a caller's consistent snapshot.

        All reads pass through the supplied view so a caller transaction must
        declare the complete discovered read set. This never opens a fallback
        storage snapshot or renews either authorization context.
        """
        self._definition(profile)
        view = _Reads(view, self.scope_id)
        record = _lookup(view, lifecycle_ref(matter, profile=profile, condition=condition))
        if record is None:
            return None
        state = self._value(record)
        receipt = self._audit_state(view, state, read_token=read_token, access_context=access_context)
        if (state["profile"] != profile or canonical_bytes(state["condition"]) != canonical_bytes(condition) or
                entity_ref(state["matter"]) != entity_ref(matter)):
            _fail(code="E_DEPENDENCY_STALE")
        now = fragment(self.clock(), "known_time")
        require_current_dependency(view, registration_ref(record), as_of=now, controls=self.controls)
        view.exact(state["matter"])
        self._basis(view, state, receipt, now)
        lineage = self.claims._lineage(view, state["basis"]["claim"])
        superseded = [ref for item in lineage for ref in item.get("supersedes", [])]
        if state["basis"]["claim"] in superseded or len([item for item in lineage if pin(item) not in superseded]) != 1:
            _fail("The current lifecycle basis was corrected.", "E_DEPENDENCY_STALE")
        if read_token is not None:
            source_request = receipt["body"]["details"]["value"]["assessment_publication"]["value"]["preparation"]["request"]
            targets = _read_targets(source_request, [pin(item) for item in view.records.values()])
            self.controls.require_current(view, read_token, capability=read_token["capability"], targets=targets, as_of=now)
            self.controls._audit(view, {"actor": read_token["actor"], "authority": entity_ref(read_token["authority"])}, targets)
        return record

    def state_role(self, profile, state):
        """Interpret a declared state only through its exact installed profile."""
        _, definition = self._definition(profile)
        for item in definition.value["states"]:
            if item["name"] == state:
                return item["role"]
        _fail("The state is not declared by this exact lifecycle profile.")

    def history(self, matter, *, profile, condition, knowledge_at=None, effective_at=None, read_token=None, access_context=None):
        """Immutable transition receipts, ordered by actual commitment.

        A knowledge cut excludes subsequently learned corrections. An effective
        cut filters their declared effective time; it never rewrites old receipts.
        Historical availability is not present validity or a qualified replay.
        """
        self._definition(profile)
        if knowledge_at is not None:
            fragment(knowledge_at, "known_time")
        if effective_at is not None:
            fragment(effective_at, "known_time")
        with self.storage.snapshot() as snapshot:
            view = _Reads(snapshot, self.scope_id)
            record = _lookup(view, lifecycle_ref(matter, profile=profile, condition=condition))
            if record is None:
                return []
            state = self._value(record)
            next_ref, seen, result = state["last_transition"], set(), []
            while next_ref is not None:
                key = canonical_bytes(next_ref)
                if key in seen or len(seen) >= 4096:
                    _fail("The lifecycle history is cyclic or exceeds its read budget.", "E_BUDGET_EXHAUSTED")
                seen.add(key)
                receipt = validate_record(view.get(next_ref))
                wrapped = receipt["body"]["details"]
                if wrapped != domain("lifecycle-transition", wrapped["value"]):
                    _fail(code="E_EVIDENCE_INVALID")
                detail = wrapped["value"]
                if entity_ref(detail["matter"]) != entity_ref(matter) or canonical_bytes(detail["condition"]) != canonical_bytes(condition):
                    _fail(code="E_EVIDENCE_INVALID")
                self._audit_state(view, {"last_transition": next_ref}, read_token=read_token, access_context=access_context)
                if (detail["profile"] == profile and (knowledge_at is None or compare_times(detail["knowledge_at"], knowledge_at) <= 0) and
                        (effective_at is None or compare_times(detail["effective_at"], effective_at) <= 0)):
                    result.append(receipt)
                next_ref = detail["previous_transition"]
            return list(reversed(result))
