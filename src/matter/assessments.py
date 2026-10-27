"""MAT-015 atomic revision-bound assessment publication.

Preparation captures a short consistent read snapshot. Evaluation stays outside
the write transaction. Publication retains raw attempts on refusal through the
existing command journal; successful publication materializes real child pins
and a guarded current pointer atomically. No delivery or transitive engine.
"""

from copy import deepcopy

from ._rule_values import FrozenValue, checked, descriptor, domain, fragment
from .canonical import canonical_bytes, canonical_digest, source_digest
from .candidate_sets import matches, require_current_candidates
from .citations import verify_locator_validation
from .contracts import ContractError, validate_command, validate_record
from .controls import ControlService, command_targets
from .conflicts import ConflictResolverRegistry
from .evaluators import EvaluationBundle, QualificationRegistry
from .evaluators.runner import _admit_result, _expected_input
from .executor import GraphRun
from .negative_dependencies import require_current_negative_dependency
from .planner import RulePlan
from .profiles import ProfileRegistry
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .storage.base import _validate_projection
from .time import compare_times
from .time import knowledge_eligible


ASSESSMENT_NAMESPACE = "matter.assessments"
PUBLICATION_EXTENSION = "matter:assessment_publication"
_PREPARED = object()
_ENGINE = descriptor("matter", "assessment-publication", "1.0", {
    "operation": "commit_assessment", "read_guards": "exact-original", "publication": "atomic-materialized-children",
    "authority": "explicit-host-controls"}, "matter.assessment-engine.v1")


def _fail(detail="The assessment publication declaration is invalid.", code="E_POLICY_INVALID"):
    raise StorageError(code, detail)


def _identity(reference):
    return tuple(reference[key] for key in ("scope_id", "namespace", "id"))


def _sorted(values):
    return sorted(deepcopy(list(values)), key=canonical_bytes)


def _unique_refs(values):
    result = {}
    for value in values:
        ref = fragment(value, "pinned_ref")
        key = _identity(ref)
        if key in result and result[key] != ref:
            _fail("One snapshot cannot contain conflicting revisions.", "E_DEPENDENCY_STALE")
        result[key] = ref
    return _sorted(result.values())


def _read_targets(request, references):
    # Reuse the established host-control target contract: implementation
    # projections and receipt/control bookkeeping cannot become user targets.
    command = deepcopy(request)
    command["expected_revisions"] = _unique_refs(references)
    return command_targets(command)


def _require_covered(token, targets):
    """Check the original scope even during immutable proposal reconstruction."""
    domain("control-token", token)
    captured = {canonical_bytes(target) for target in token["targets"]}
    if any(canonical_bytes(target) not in captured for target in targets):
        _fail("The original control context does not cover every semantic input target.", "E_AUTHORITY_REQUIRED")


def _stable(reference):
    ref = fragment(reference, "component_ref")
    return {key: ref[key] for key in ("namespace", "id")}


def assessment_current_ref(scope_id, matter, *, profile, purpose, audience=None):
    """One stable lane per subject and policy/purpose/audience identity.

    Versions are bound in the current value, so a new version can supersede its
    own lane while distinct profiles coexist. Reading still requires exact
    profile/purpose/audience version selectors; there is no latest lookup.
    """
    scope = fragment(scope_id, "identifier")
    subject = fragment(entity_ref(matter), "matter_ref")
    if subject["scope_id"] != scope:
        _fail(code="E_SCOPE_FORBIDDEN")
    key = {"matter": subject, "profile": _stable(profile), "purpose": _stable(purpose),
           "audience": None if audience is None else _stable(audience)}
    return {"scope_id": scope, "namespace": ASSESSMENT_NAMESPACE, "record_type": PROJECTION_TYPE,
            "id": "current-" + canonical_digest(key, "matter.assessment-lane.v1")}


class _Tracked:
    def __init__(self, view, scope):
        self.view, self.scope, self.records, self.absent, self.queries = view, scope, {}, {}, {}

    def _remember(self, value):
        if value["scope_id"] != self.scope:
            _fail(code="E_SCOPE_FORBIDDEN")
        key = _identity(value)
        if key in self.records and pin(value) != pin(self.records[key]):
            _fail(code="E_DEPENDENCY_STALE")
        self.records[key] = deepcopy(value)
        return deepcopy(value)

    def get(self, reference):
        if reference["scope_id"] != self.scope:
            _fail(code="E_SCOPE_FORBIDDEN")
        try:
            return self._remember(self.view.get(reference))
        except StorageError as error:
            if error.code == "E_NOT_FOUND":
                self.absent[_identity(reference)] = entity_ref(reference)
            raise

    def lookup_identity(self, reference):
        try:
            return self._remember(self.view.lookup_identity(reference))
        except StorageError as error:
            if error.code == "E_NOT_FOUND":
                self.absent[_identity(reference)] = entity_ref(reference)
            raise

    def watchers(self, key):
        rows = [self._remember(value) for value in self.view.watchers(key)]
        self.queries[key] = [entity_ref(value) for value in rows]
        return rows


class FrozenAssessmentView:
    """Only records captured by a short original snapshot; never a live fallback."""
    def __init__(self, preparation):
        self._data = deepcopy(preparation)

    def get(self, reference):
        for record in self._data["records"]:
            if entity_ref(record) == entity_ref(reference):
                if not matches(record, reference):
                    raise StorageError("E_DEPENDENCY_STALE")
                return deepcopy(record)
        if entity_ref(reference) in self._data["absent"]:
            raise StorageError("E_NOT_FOUND")
        _fail("This dependency was not captured by the original snapshot.", "E_EVIDENCE_UNAVAILABLE")

    def lookup_identity(self, reference):
        return self.get(entity_ref(reference))

    def watchers(self, key):
        if key not in self._data["watch_queries"]:
            _fail("The frozen assessment did not capture this watch query.", "E_EVIDENCE_UNAVAILABLE")
        return [self.get(ref) for ref in self._data["watch_queries"][key]]


class PreparedAssessment(FrozenValue):
    __slots__ = ()

    def __init__(self, value, *, _admission=None):
        if _admission is not _PREPARED:
            _fail("Use AssessmentService.prepare with a consistent authorized snapshot.")
        self._freeze(value)

    @property
    def view(self):
        return FrozenAssessmentView(self.value)

    @property
    def token(self):
        return self.value["token"]

    @property
    def digest(self):
        return canonical_digest(self.value, "matter.assessment-input.v1")

    @property
    def cache_inputs(self):
        from .cache import CacheInput
        return tuple(CacheInput(value, _prepared=True) for value in self.value["cache_inputs"])


class AssessmentService:
    def __init__(self, storage, *, profiles, rules, bindings, schemas, controls, clock,
                 qualifications=None, cache=None, conflicts=None, access=None):
        if not isinstance(profiles, ProfileRegistry) or not isinstance(controls, ControlService) or not callable(clock):
            _fail()
        if storage.scope_id != controls.scope_id:
            _fail(code="E_SCOPE_FORBIDDEN")
        self.storage, self.scope_id = storage, storage.scope_id
        self.profiles, self.rules, self.bindings, self.schemas = profiles, rules, bindings, schemas
        self.controls, self.clock, self.cache = controls, clock, cache
        self.access = access
        self.qualifications = qualifications or QualificationRegistry()
        self.conflicts = conflicts or ConflictResolverRegistry()

    def _now(self):
        return fragment(self.clock(), "known_time")

    def _read(self, view, reference):
        ref = fragment(reference, "pinned_ref")
        if ref["scope_id"] != self.scope_id:
            _fail(code="E_SCOPE_FORBIDDEN")
        record = view.get(entity_ref(ref))
        if not matches(record, ref):
            _fail("An assessment input revision is no longer current.", "E_DEPENDENCY_STALE")
        return record

    @staticmethod
    def _read_targets(preparation, graph=None):
        refs = list(preparation["current_dependencies"]["positive"])
        if graph is not None:
            proof = {_identity(ref) for ref in preparation["proof_reads"]}
            declared = {_identity(ref) for ref in refs}
            for material in graph["inputs"].values():
                refs.extend(ref for ref in material["packet"]["dependencies"]["positive"]
                            if _identity(ref) not in proof or _identity(ref) in declared)
        return _read_targets(preparation["request"], refs)

    @staticmethod
    def _basis(preparation):
        """Flat semantic comparison material, never recursive prior history."""
        body = preparation["request"]["body"]
        dependencies = preparation["current_dependencies"]
        selected = {_identity(ref) for ref in [body["matter"], *body["evidence"]["references"], *dependencies["candidate_sets"]]}
        return {"plan": canonical_digest(preparation["plan"], "matter.assessment-plan-basis.v1"),
            "extra_dependencies": _unique_refs(ref for ref in dependencies["positive"] if _identity(ref) not in selected),
            "candidate_sets": _unique_refs(dependencies["candidate_sets"]),
            "negative_registrations": _unique_refs(dependencies["negative_registrations"]),
            "staged": _unique_refs(ref for snapshot in preparation["staged_snapshots"] for ref in snapshot["references"]
                                   if ref["record_type"] == "judgment"),
            "cache_projections": _sorted({"definition": item["definition"],
                "projected": {key: value for key, value in item["projected"].items() if key != "temporal_class"}}
                                          for item in preparation["cache_inputs"]),
            "cache_temporal_classes": _sorted({"projection": canonical_digest({"definition": item["definition"],
                "projected": {key: value for key, value in item["projected"].items() if key != "temporal_class"}},
                "matter.assessment-cache-projection-basis.v1"),
                "temporal_class": item["projected"]["temporal_class"]} for item in preparation["cache_inputs"]),
            # Merely selecting a new target with no control history is an
            # input change, not a new host disposition. Nonempty generations,
            # exact grants/policies and applicable controls remain explicit.
            "control_context": {**{key: value for key, value in preparation["token"].items()
                                    if key not in {"captured_at", "targets", "fences"}},
                                "fences": [item for item in preparation["token"]["fences"] if item["pin"] is not None]}}

    def _plan(self, raw, profile):
        conditions = [{key: edge[key] for key in ("from", "to", "accepted_labels", "accepted_statuses", "require_qualified")}
                      for edge in raw["edges"] if edge["kind"] == "conditional"]
        plan = RulePlan(profile, rules=self.rules, schemas=self.schemas, nodes=raw["nodes"],
            input_bindings=raw["input_bindings"], conditions=conditions, compositions=raw["compositions"])
        if plan.value != raw:
            _fail("The persisted graph differs from its installed profile compilation.")
        return plan

    def _preparation(self, value):
        data = checked(value, required=("schema_version", "request", "plan", "token", "control_contexts", "captured_at",
            "records", "reads", "absent", "watch_queries", "current_dependencies", "lane", "previous", "prior_assessment", "prior_request", "prior_basis",
            "cache_inputs", "staged_snapshots", "proof_reads"), optional=("access_context",),
            code="E_EVIDENCE_INVALID")
        if data["schema_version"] != "1.0" or len(canonical_bytes(data)) > 8388608:
            _fail("The retained assessment preparation exceeds its supported contract.", "E_EVIDENCE_INVALID")
        request = validate_command(data["request"])
        token = data["token"]
        if (request["operation"] != "assess" or request["scope_id"] != self.scope_id or
                request["actor"] != token.get("actor") or request["authority"] != entity_ref(token.get("authority", {})) or
                request["body"]["control_epoch"] != token.get("control_epoch")):
            _fail("The retained preparation changed its original host authority context.", "E_AUTHORITY_REQUIRED")
        if type(data["records"]) is not list or len(data["records"]) > 4096:
            _fail(code="E_EVIDENCE_INVALID")
        records = []
        for raw in data["records"]:
            record = _validate_projection(raw) if raw.get("record_type") == PROJECTION_TYPE else validate_record(raw)
            if record["scope_id"] != self.scope_id:
                _fail(code="E_SCOPE_FORBIDDEN")
            records.append(record)
        if len({_identity(record) for record in records}) != len(records):
            _fail("Duplicate retained record identities are ambiguous.", "E_EVIDENCE_INVALID")
        reads = _unique_refs([*[pin(record) for record in records], *([data["previous"]] if data["previous"] is not None else [])])
        if reads != data["reads"]:
            _fail("Retained snapshots do not bind the complete original read set.", "E_EVIDENCE_INVALID")
        body = request["body"]
        expected_lane = assessment_current_ref(self.scope_id, body["matter"], profile=body["profile"], purpose=body["purpose"], audience=body.get("audience"))
        if data["lane"] != expected_lane or any(ref["scope_id"] != self.scope_id for ref in reads):
            _fail(code="E_SCOPE_FORBIDDEN")
        if data["prior_assessment"] is None:
            if data["prior_request"] is not None or data["prior_basis"] is not None or data["previous"] is not None:
                _fail("A new lane cannot invent a prior semantic basis.", "E_EVIDENCE_INVALID")
        else:
            checked(data["prior_basis"], required=("plan", "extra_dependencies", "candidate_sets", "negative_registrations",
                "staged", "cache_projections", "cache_temporal_classes", "control_context"), code="E_EVIDENCE_INVALID")
            if type(data["prior_request"]) is not dict or data["previous"] is None:
                _fail("A continuing lane must retain its actual prior semantic basis.", "E_EVIDENCE_INVALID")
        dependencies = checked(data["current_dependencies"], required=("positive", "candidate_sets", "negative_registrations"), code="E_EVIDENCE_INVALID")
        nominated = [body["matter"], *body["evidence"]["references"], *dependencies["candidate_sets"]]
        if any(ref not in dependencies["positive"] for ref in nominated) or any(ref not in reads for ref in dependencies["positive"]):
            _fail("A selected semantic dependency is missing from publication guards.", "E_EVIDENCE_INVALID")
        return data

    def prepare(self, command, *, token, plan, extra_dependencies=(), candidate_sets=(), negative_dependencies=(),
                control_contexts=(), cache_references=(), cache_queries=(), access_context=None):
        request = validate_command(command)
        if request["operation"] != "assess" or request["scope_id"] != self.scope_id or not isinstance(plan, RulePlan):
            _fail()
        body = request["body"]
        if "evidence" not in body or "query" in body:
            _fail("Assessment requires an explicitly selected evidence packet; retrieval is host-owned.", "E_EVIDENCE_UNAVAILABLE")
        profile = self.profiles.resolve(body["profile"])
        if plan.value["profile"] != profile.reference:
            _fail("The graph must bind the exact requested profile.")
        if plan.value["resource_limits"]["max_calls"] > body["budget"]["max_calls"]:
            _fail("The declared graph exceeds the assessment call budget.", "E_BUDGET_EXHAUSTED")
        profile.assessment_binding(body["matter"], purpose=body["purpose"], audience=body.get("audience"))
        token = deepcopy(token)
        if request["actor"] != token.get("actor") or request["authority"] != entity_ref(token.get("authority", {})):
            _fail(code="E_AUTHORITY_REQUIRED")
        if body["control_epoch"] != token.get("control_epoch"):
            _fail(code="E_DEPENDENCY_STALE")
        now = self._now()
        if compare_times(body["assessed_as_of"], now) == 1:
            _fail("The assessment knowledge boundary cannot follow actual preparation time.", "E_EVIDENCE_INVALID")
        nominated = _unique_refs([body["matter"], *body["evidence"]["references"], *extra_dependencies,
                                  *candidate_sets, *request["expected_revisions"]])
        address = assessment_current_ref(self.scope_id, body["matter"], profile=body["profile"],
                                         purpose=body["purpose"], audience=body.get("audience"))
        with self.storage.snapshot() as snapshot:
            view = _Tracked(snapshot, self.scope_id)
            admitted_access = None
            if self.access is not None:
                if access_context is None or body.get("audience") is None:
                    _fail("The installed access boundary requires an exact audience context.", "E_AUTHORITY_REQUIRED")
                admitted_access = self.access.require_current(view, access_context, references=nominated, audience=body["audience"])
                if admitted_access.value["token"] != token:
                    _fail("The original access and assessment control contexts differ.", "E_AUTHORITY_REQUIRED")
            elif access_context is not None:
                _fail("An access context requires its installed host boundary.", "E_AUTHORITY_REQUIRED")
            self.controls.require_current(view, token, capability="assessment", targets=[entity_ref(body["matter"])], as_of=now)
            for reference in nominated:
                self._read(view, reference)
            for reference in candidate_sets:
                require_current_candidates(view, self.scope_id, reference)
            # Separate semantic dependencies from proof reads: a narrow absence
            # watch is not semantically dependent on every broad catalog row.
            positive = _unique_refs([pin(record) for record in view.records.values()
                if record["record_type"] not in {"receipt", "control"} and record["namespace"] != "matter.controls"])
            self.controls._audit(view, request, _read_targets(request, positive))
            registrations = []
            before_proof = set(view.records)
            for reference in negative_dependencies:
                registrations.append(pin(require_current_negative_dependency(view, self.scope_id, reference, as_of=now)))
            proof_reads = _unique_refs([pin(record) for identity, record in view.records.items() if identity not in before_proof])
            cache_inputs, lookup_refs = [], list(cache_references)
            if cache_queries and self.cache is None:
                _fail("Declared cache inputs require an installed semantic cache.")
            from .cache import cache_ref
            for raw_query in cache_queries:
                query = checked(raw_query, required=("definition", "records", "context", "qualification_context", "citations", "negative_dependencies"))
                cached_input = self.cache.capture(view, self.cache._definition(query["definition"]),
                    records=query["records"], context=query["context"], token=token, as_of=now,
                    qualification_context=query["qualification_context"], citations=query["citations"],
                    negative_dependencies=query["negative_dependencies"], access_context=admitted_access)
                cache_inputs.append(cached_input.value)
                lookup_refs.append(cache_ref(self.scope_id, cached_input.key))
                positive = _unique_refs([*positive, *query["records"].values()])
            for reference in lookup_refs:
                try:
                    cached = view.get(reference)
                except StorageError as error:
                    if error.code != "E_NOT_FOUND":
                        raise
                    continue
                entry = cached["value"]["value"]
                if cached["value"] != domain("cache-entry", entry):
                    _fail("A cached computation has an unknown schema binding.", "E_EVIDENCE_INVALID")
                original = entry["request"]
                self.controls.require_current(view, original["token"], capability="assessment",
                    targets=original["token"]["targets"], as_of=now)
                for registration in original["negative_dependencies"]:
                    require_current_negative_dependency(view, self.scope_id, registration, as_of=now)
            try:
                previous = view.get(address)
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
                previous = None
            prior = None if previous is None else previous["value"]["value"]
            if prior is not None:
                self._current_value(previous)
            # Keep only the prior lane's exact request, not its recursively
            # embedded preparation/history, in the next immutable input.
            prior_request = None if prior is None else deepcopy(prior["preparation"]["request"]["body"])
            data = {"schema_version": "1.0", "request": request, "plan": plan.value, "token": token,
                "control_contexts": deepcopy(list(control_contexts)), "captured_at": now,
                "records": _sorted(record for record in view.records.values() if entity_ref(record) != address),
                "reads": _unique_refs([pin(record) for record in view.records.values()]),
                "absent": _sorted(view.absent.values()), "watch_queries": deepcopy(view.queries),
                "current_dependencies": {"positive": positive, "candidate_sets": list(candidate_sets),
                    "negative_registrations": _unique_refs(registrations)},
                "lane": address, "previous": None if previous is None else pin(previous),
                "prior_assessment": None if prior is None else prior["assessment"], "prior_request": prior_request,
                "prior_basis": None if prior is None else self._basis(prior["preparation"]),
                "cache_inputs": cache_inputs, "staged_snapshots": [], "proof_reads": proof_reads}
            if admitted_access is not None:
                data["access_context"] = admitted_access.value
            self.controls.require_current(view, token, capability="assessment", targets=self._read_targets(data), as_of=now)
        if len(canonical_bytes(data)) > body["budget"]["max_bytes"]:
            _fail("The captured assessment input exceeds its byte budget.", "E_BUDGET_EXHAUSTED")
        return PreparedAssessment(data, _admission=_PREPARED)

    def extend_staged(self, prepared, *, references):
        """Add actual host-stored immutable prerequisites after checking originals.

        The original knowledge cut, capture time and control tokens stay fixed.
        This seam grants no staging write authority and cannot backdate a new
        judgment into an earlier evidence cut. A host must store it through a
        real authorized operation before supplying its exact pin here.
        """
        if not isinstance(prepared, PreparedAssessment):
            _fail()
        data, now = prepared.value, self._now()
        with self.storage.snapshot() as snapshot:
            view = _Tracked(snapshot, self.scope_id)
            if self.access is not None:
                self.access.require_current(view, data.get("access_context", {}), references=references)
            targets = _read_targets(data["request"], [*data["current_dependencies"]["positive"], *references])
            self.controls.require_current(view, data["token"], capability="assessment", targets=targets, as_of=now)
            for ref in data["current_dependencies"]["positive"]:
                self._read(view, ref)
            for ref in data["current_dependencies"]["negative_registrations"]:
                require_current_negative_dependency(view, self.scope_id, ref, as_of=now)
            for rule_ref in data["plan"]["nodes"].values():
                for condition in self.rules.resolve(rule_ref).value["temporal_dependencies"]:
                    if any(compare_times(now, condition[key]) in {0, 1} for key in ("next_check_at", "expires_at")):
                        _fail("An original temporal condition requires reconsideration before staging.", "E_DEPENDENCY_STALE")
            for ref in references:
                fragment(ref, "pinned_ref")
                if ref["record_type"] not in {"judgment", "receipt"}:
                    _fail("Only actual immutable prerequisite judgments or receipts may be staged.")
                record = self._read(view, ref)
                data["records"] = [item for item in data["records"] if _identity(item) != _identity(record)] + [record]
            self.controls._audit(view, data["request"], _read_targets(data["request"], references))
            data["records"] = _sorted(data["records"])
            data["reads"] = _unique_refs([*data["reads"], *[pin(item) for item in view.records.values()]])
            # Record proof rows needed by transaction-time control checks too.
            known = {_identity(item) for item in data["records"]}
            data["records"].extend(item for item in view.records.values() if _identity(item) not in known)
            data["records"] = _sorted(data["records"])
            data["absent"] = _sorted({canonical_bytes(ref): ref for ref in [*data["absent"], *view.absent.values()]}.values())
            data["staged_snapshots"].append({"captured_at": now, "references": _unique_refs(references)})
        return PreparedAssessment(data, _admission=_PREPARED)

    def _token_resolver(self, view, preparation, packet, now):
        digest = packet["control_token_digest"]
        if digest is None:
            return
        for token in [preparation["token"], *preparation["control_contexts"]]:
            if canonical_digest(token, "matter.evaluation-control.v1") == digest:
                proof = {_identity(ref) for ref in preparation["proof_reads"]}
                declared = {_identity(ref) for ref in preparation["current_dependencies"]["positive"]}
                targets = _read_targets(preparation["request"], [ref for ref in packet["dependencies"]["positive"]
                    if _identity(ref) not in proof or _identity(ref) in declared])
                _require_covered(token, targets)
                if isinstance(view, FrozenAssessmentView):
                    # Reconstructing an immutable proposal at its original
                    # timestamp is not current work authorization. The writer
                    # gate below separately checks this exact token at NOW.
                    domain("control-token", token)
                    if token["control_epoch"] != packet["dependencies"]["control_epoch"]:
                        _fail("The retained control token does not match its input epoch.")
                else:
                    self.controls.require_current(view, token, capability=token["capability"], targets=targets, as_of=now)
                return
        _fail("The exact original control context was not retained.")

    def _input_current(self, view, material, preparation, now):
        packet = material["packet"]
        proof_ids = {_identity(ref) for ref in preparation["proof_reads"]}
        semantic_ids = {_identity(ref) for ref in preparation["current_dependencies"]["positive"]}
        for reference in packet["dependencies"]["positive"]:
            if _identity(reference) not in proof_ids or _identity(reference) in semantic_ids:
                self._read(view, reference)
        for reference in packet["negative_registrations"]:
            require_current_negative_dependency(view, self.scope_id, reference, as_of=now)
        for condition in packet["dependencies"]["time_conditions"]:
            if any(compare_times(now, condition[key]) in {0, 1} for key in ("next_check_at", "expires_at")):
                _fail("A temporal dependency requires reconsideration.", "E_DEPENDENCY_STALE")
        self._token_resolver(view, preparation, packet, now)
        for predecessor in packet["upstream"]:
            self._input_current(view, predecessor["expected_input"], preparation, now)

    def _graph(self, view, preparation, graph, now):
        graph = checked(graph, required=("schema_version", "run_id", "scope_id", "plan", "profile", "status", "stop_reason",
            "nodes", "inputs", "compositions", "resource_reservations", "limitations"), optional=("stop_diagnostics",),
            code="E_EVIDENCE_INVALID")
        if (graph["schema_version"] != "1.0" or type(graph["nodes"]) is not dict or len(graph["nodes"]) > 128 or
                type(graph["inputs"]) is not dict or type(graph["compositions"]) is not list or len(canonical_bytes(graph)) > 8388608):
            _fail("The retained graph exceeds its supported wire contract.", "E_EVIDENCE_INVALID")
        _require_covered(preparation["token"], self._read_targets(preparation, graph))
        request = preparation["request"]["body"]
        profile = self.profiles.resolve(request["profile"])
        plan = self._plan(preparation["plan"], profile)
        if graph["plan"] != plan.reference or graph["profile"] != profile.reference or graph["scope_id"] != self.scope_id:
            _fail("The graph result does not bind the exact prepared profile, plan and scope.")
        if set(graph["nodes"]) != set(plan.value["nodes"]) or set(graph["inputs"]) - set(graph["nodes"]):
            _fail("Graph node and input inventories do not match the compiled plan.")
        captured = {_identity(ref): ref for ref in preparation["reads"]}
        bundles, usable = [], {}
        frozen_view = FrozenAssessmentView(preparation)
        for name in plan.value["order"]:
            node = checked(graph["nodes"][name], required=("node", "rule", "status", "reason", "error_code", "input_digest",
                "upstream_input_digests", "judgment", "attempt_receipt"), optional=("final_admission", "final_edge_admissions"),
                code="E_EVIDENCE_INVALID")
            if node["node"] != name or node["rule"] != plan.value["nodes"][name]:
                _fail("A retained graph node changed its declared identity or rule.", "E_EVIDENCE_INVALID")
            raw = node["judgment"]
            if raw is None:
                usable[name] = False
                continue
            material = graph["inputs"].get(name)
            if material is None or node["rule"] != plan.value["nodes"][name]:
                _fail("An attempted node has no exact prepared input.")
            rule = self.rules.resolve(node["rule"])
            binding = self.bindings.resolve(rule.value["evaluator_binding"])
            _expected_input(material, rule, binding)
            packet = material["packet"]
            if packet["scope_id"] != self.scope_id or packet["as_of"] != request["assessed_as_of"]:
                _fail("Rule inputs must use the assessment scope and knowledge boundary.")
            if packet["subject"] != request["matter"]:
                _fail("Every rule input must bind the assessment's exact continuing subject.", "E_EVIDENCE_INVALID")
            for ref in packet["dependencies"]["positive"]:
                if captured.get(_identity(ref)) != ref:
                    _fail("The graph read a record outside the captured assessment snapshot.", "E_EVIDENCE_INVALID")
            for evidence in packet["evidence"]:
                if evidence["record"] != frozen_view.get(evidence["reference"]):
                    _fail("A rule input altered the captured source snapshot.", "E_EVIDENCE_INVALID")
                source = evidence["record"]
                requirements = rule.value["evidence_requirements"]
                if (source["record_type"] not in requirements["allowed_kinds"] or
                        source["provenance"]["origin"] not in requirements["allowed_origins"] or
                        knowledge_eligible(evidence["available_at"], packet["as_of"]) is not True or
                        (source["record_type"] == "observation" and evidence["available_at"] != source["body"]["available_at"])):
                    _fail("An included source violates its declared eligibility or availability boundary.", "E_EVIDENCE_INVALID")
                adapter = evidence["validation"]["value"].get("adapter")
                if adapter not in requirements["locator_adapters"]:
                    _fail("The source locator adapter is not admitted by the exact rule.", "E_EVIDENCE_INVALID")
                declaration = verify_locator_validation(evidence["validation"], evidence=source, locator=evidence["locator"],
                    quotation=evidence["quotation"], adapter=adapter)
                if declaration["result"]["status"] != "valid":
                    _fail("Included citations require their exact valid locator declaration.", "E_EVIDENCE_INVALID")
                for dependency in declaration["dependencies"]:
                    if captured.get(_identity(dependency)) != dependency:
                        _fail("A locator dependency was not captured by this assessment.", "E_EVIDENCE_INVALID")
            from types import SimpleNamespace
            from .executor import GraphExecutor
            predecessors = {edge["from"]: {"judgment": graph["nodes"][edge["from"]]["judgment"],
                "input": graph["inputs"][edge["from"]]} for edge in plan.value["edges"] if edge["to"] == name}
            GraphExecutor._check_prepared(SimpleNamespace(value=material), rule, name, plan.value, predecessors)
            self._input_current(view, material, preparation, now)
            bundle = EvaluationBundle(raw, node["attempt_receipt"])
            receipt = bundle.receipt
            details = receipt["body"]["details"]
            if details != domain("rule-evaluation-receipt", details["value"]):
                _fail("An attempt receipt changed its exact schema declaration.", "E_EVIDENCE_INVALID")
            expected_details = {"input_digest": raw["body"]["input_digest"], "rule": rule.reference,
                "binding": binding.reference, "execution_status": raw["body"]["execution_status"],
                "qualification": raw["body"]["qualification"], "control_token_digest": packet["control_token_digest"],
                "raw_result": raw["body"]["raw_result"]}
            if (any(details["value"][key] != value for key, value in expected_details.items()) or
                    raw["provenance"]["producer"] != binding.reference or raw["provenance"]["origin"] != "evaluator" or
                    receipt["body"]["operation_id"] != receipt["id"] or
                    receipt["body"]["outcome"] != "matter:evaluation_" + raw["body"]["execution_status"] or
                    receipt["body"]["recorded_at"] != raw["body"]["execution_interval"]["end"] or
                    receipt["provenance"]["parents"] != packet["dependencies"]["positive"] or
                    raw["provenance"]["parents"] != packet["dependencies"]["positive"]):
                _fail("The attempt receipt does not describe its exact retained judgment/input pair.", "E_EVIDENCE_INVALID")
            if raw["body"]["input_digest"] != canonical_digest(material, "matter.evaluation-input.v1") or node["input_digest"] != raw["body"]["input_digest"]:
                _fail("The raw attempt and original input identity differ.", "E_EVIDENCE_INVALID")
            selector = {"accepted_labels": [outcome["label"] for outcome in rule.value["outcomes"]],
                        "accepted_statuses": ["applicable", "not_applicable", "insufficient_evidence", "ambiguous", "conflicting"]}
            _admit_result(raw, rule, binding=binding, schemas=self.schemas, qualifications=self.qualifications,
                as_of=now, expected_input=material, require_qualified=False, **selector)
            admission = _admit_result(raw, rule, binding=binding, schemas=self.schemas, qualifications=self.qualifications,
                as_of=now, expected_input=material, require_qualified=True,
                accepted_labels=selector["accepted_labels"], accepted_statuses=["applicable"])
            allowed = admission["status"] == "usable" and node["status"] == "completed"
            if node.get("final_admission", {}).get("status") == "blocked":
                allowed = False
            if any(item["status"] != "usable" for item in node.get("final_edge_admissions", [])):
                allowed = False
            for edge in plan.value["edges"]:
                if edge["to"] != name:
                    continue
                source = graph["nodes"][edge["from"]]
                source_raw = source["judgment"]
                if source_raw is None or not usable.get(edge["from"], False):
                    allowed = False
                    continue
                source_rule = self.rules.resolve(source["rule"])
                gate = _admit_result(source_raw, source_rule, binding=self.bindings.resolve(source_rule.value["evaluator_binding"]),
                    schemas=self.schemas, qualifications=self.qualifications, as_of=now,
                    expected_input=graph["inputs"][edge["from"]], accepted_labels=edge["accepted_labels"],
                    accepted_statuses=edge["accepted_statuses"], require_qualified=edge["require_qualified"])
                if gate["status"] != "usable":
                    allowed = False
            usable[name] = allowed
            bundles.append((name, bundle))
        compositions = {item["id"]: item for item in graph["compositions"]}
        if set(compositions) != {item["id"] for item in plan.value["compositions"]}:
            _fail("The graph changed its explicit composition inventory.", "E_EVIDENCE_INVALID")
        for group in plan.value["compositions"]:
            original = compositions[group["id"]]
            held = any(not usable.get(name, False) for name in group["nodes"])
            for selector in group["mandatory_gates"]:
                name = selector["node"]
                if not usable.get(name, False):
                    held = True
                    continue
                source_rule = self.rules.resolve(plan.value["nodes"][name])
                decision = _admit_result(graph["nodes"][name]["judgment"], source_rule,
                    binding=self.bindings.resolve(source_rule.value["evaluator_binding"]), schemas=self.schemas,
                    qualifications=self.qualifications, as_of=now, expected_input=graph["inputs"][name],
                    accepted_labels=selector["accepted_labels"], accepted_statuses=selector["accepted_statuses"],
                    require_qualified=selector["require_qualified"])
                held = held or decision["status"] != "usable"
            if held or original["status"] != "resolved":
                for name in group["nodes"]:
                    usable[name] = False
                continue
            values = [{"node": name, "judgment": graph["nodes"][name]["judgment"],
                       "input_digest": graph["nodes"][name]["input_digest"], "status": graph["nodes"][name]["status"]}
                      for name in sorted(group["nodes"])]
            actual = self.conflicts.resolve(group["resolver"]).compose(values)
            if original != {"id": group["id"], **actual, "held_gates": []}:
                _fail("The retained composition differs from its exact admitted resolver.", "E_EVIDENCE_INVALID")
        return profile, bundles, usable

    @staticmethod
    def _composition_permits(name, preparation, graph):
        results = {item["id"]: item for item in graph["compositions"]}
        output = graph["nodes"][name]["judgment"]["body"].get("semantic_output") if graph["nodes"][name]["judgment"] else None
        for group in preparation["plan"]["compositions"]:
            if name in group["nodes"]:
                result = results[group["id"]]
                if result["status"] != "resolved" or result["semantic_output"] != output:
                    return False
        return True

    def _causes(self, preparation):
        if preparation["prior_assessment"] is None:
            return ["new_evidence"]
        before = preparation["prior_request"]
        after = preparation["request"]["body"]
        causes = []
        for field, cause in (("profile", "policy_change"), ("purpose", "purpose_change"), ("audience", "audience_change")):
            if before.get(field) != after.get(field):
                causes.append(cause)
        if before["evidence"] != after["evidence"]:
            causes.append("new_evidence")
        if before["matter"] != after["matter"] and not causes:
            causes.append("evidence_correction")
        prior, current = preparation["prior_basis"], self._basis(preparation)
        for field, cause in (("plan", "policy_change"), ("control_context", "disposition_change"),
            ("negative_registrations", "coverage_change"), ("candidate_sets", "association_correction"),
            ("extra_dependencies", "evidence_correction"), ("staged", "evidence_correction"),
            ("cache_projections", "evidence_correction")):
            if prior[field] != current[field] and cause not in causes:
                causes.append(cause)
        before_classes = {item["projection"]: item["temporal_class"] for item in prior["cache_temporal_classes"]}
        after_classes = {item["projection"]: item["temporal_class"] for item in current["cache_temporal_classes"]}
        if any(before_classes[key] != after_classes[key] for key in before_classes.keys() & after_classes.keys()):
            causes.append("temporal_transition")
        if not causes:
            if before["assessed_as_of"] != after["assessed_as_of"]:
                causes.append("temporal_transition")
            else:
                _fail("Unchanged assessment inputs require an explicit changed policy, evidence, context or temporal boundary.")
        return causes

    def _proposal(self, preparation, graph, interpretations, assessment_id, built_at, cache_entries, *, view, admission=None):
        profile, bundles, usable = self._graph(view, preparation, graph, built_at) if admission is None else admission
        body = preparation["request"]["body"]
        reservations = graph["resource_reservations"]
        if (reservations["reserved_attempts"] > body["budget"]["max_calls"] or
                reservations["elapsed_ms"] > body["budget"]["max_elapsed_ms"]):
            _fail("The graph attempt exceeded the assessment resource budget.", "E_BUDGET_EXHAUSTED")
        propositions = []
        if type(interpretations) is not list or len(interpretations) > 128:
            _fail()
        captured = {canonical_bytes(ref) for ref in preparation["reads"]}
        semantic = {canonical_bytes(ref) for ref in preparation["current_dependencies"]["positive"]}
        for mapping in interpretations:
            mapping = checked(mapping, required=("node", "claim", "labels", "evidence_standard"), code="E_POLICY_INVALID")
            if (mapping["node"] not in graph["nodes"] or canonical_bytes(mapping["claim"]) not in captured or
                    canonical_bytes(mapping["claim"]) not in semantic):
                _fail("A conclusion must name an explicitly guarded semantic claim and selected graph node.")
            fragment(mapping["claim"], "claim_dependency")
            if mapping["evidence_standard"] != profile.component_references.get("evidence"):
                _fail("The conclusion must bind this profile's exact evidence component.")
            rule = self.rules.resolve(graph["nodes"][mapping["node"]]["rule"])
            labels = mapping["labels"]
            if type(labels) is not dict:
                _fail()
            for label, status in labels.items():
                rule.outcome(label)
                fragment({"claim": mapping["claim"], "status": status, "evidence_standard": mapping["evidence_standard"]}, "assessed_proposition")
            node = graph["nodes"][mapping["node"]]
            raw = node["judgment"]
            label = raw["body"].get("semantic_output", {}).get("value", {}).get("label") if raw else None
            status = labels.get(label, "unknown") if (usable.get(mapping["node"], False) and
                self._composition_permits(mapping["node"], preparation, graph)) else "unknown"
            propositions.append({"claim": mapping["claim"], "status": status, "evidence_standard": mapping["evidence_standard"]})
        manifest = {"positive": preparation["current_dependencies"]["positive"],
            "negative": [], "time_conditions": [], "context": [profile.reference, body["purpose"], *([body["audience"]] if "audience" in body else [])],
            "control_epoch": preparation["token"]["control_epoch"]}
        for material in graph["inputs"].values():
            dependencies = material["packet"]["dependencies"]
            proof_ids = {_identity(ref) for ref in preparation["proof_reads"]}
            semantic_ids = {_identity(ref) for ref in preparation["current_dependencies"]["positive"]}
            actual_dependencies = [ref for ref in dependencies["positive"]
                                   if _identity(ref) not in proof_ids or _identity(ref) in semantic_ids]
            manifest["positive"] = _unique_refs([*manifest["positive"], *actual_dependencies])
            for field in ("negative", "time_conditions"):
                for value in dependencies[field]:
                    if value not in manifest[field]:
                        manifest[field].append(deepcopy(value))
        for ref in preparation["current_dependencies"]["negative_registrations"]:
            watch = view.get(ref)["value"]["value"]["watch"]
            if watch not in manifest["negative"]:
                manifest["negative"].append(deepcopy(watch))
        proposals = []
        for name, bundle in bundles:
            if usable.get(name, False) and self._composition_permits(name, preparation, graph):
                for proposed in bundle.judgment["body"]["proposed_consequences"]:
                    if proposed not in proposals:
                        proposals.append(deepcopy(proposed))
        causes = self._causes(preparation)
        complete = graph["status"] == "completed" and all(usable.get(name, False) for name in graph["nodes"])
        payload = {"schema_version": "1.0", "preparation": preparation, "graph": graph,
                   "interpretations": interpretations, "cache_entries": cache_entries,
                   "assessment_id": assessment_id, "built_at": built_at}
        publication = domain("assessment-publication", payload)
        input_material = {"preparation": preparation, "inputs": graph["inputs"]}
        input_bytes = canonical_bytes(input_material)
        assessment_body = {"matter": body["matter"], "profile": body["profile"], "purpose": body["purpose"],
            "assessed_as_of": body["assessed_as_of"], "dependency_manifest": manifest, "judgments": [],
            "propositions": propositions, "causes": causes, "evaluation_state": "complete" if complete else "incomplete",
            "proposals": proposals, "limitations": deepcopy(graph["limitations"]),
            "input_artifact": {"digest": source_digest(input_bytes),
                "locator": {"kind": "whole_artifact", "uri": "urn:matter:assessment-input:" + canonical_digest(input_material, "matter.assessment-input.v1")},
                "media_type": "application/json", "availability": {"status": "available", "checked_at": built_at}},
            "evidence_selection": body["evidence"],
            "resource_use": domain("assessment-resources", {"binding_invocations": graph["resource_reservations"]["actual_invocations"],
                "elapsed_ms": graph["resource_reservations"]["elapsed_ms"], "cache_hits": sum(bool(item["cache_hit"]) for item in cache_entries)}),
            "stop_reason": "completed" if complete else "incomplete", "consequences": [],
            "material_changes": [{"cause": cause, "value": domain("assessment-change", {"cause": cause,
                "prior": preparation["prior_assessment"], "profile": profile.reference})} for cause in causes],
            "evidence_gaps": [domain("assessment-gap", {"node": name,
                "reason": graph["nodes"][name]["reason"], "error_code": graph["nodes"][name]["error_code"]})
                for name in graph["nodes"] if not usable.get(name, False)]}
        if "audience" in body:
            assessment_body["audience"] = body["audience"]
        if preparation["prior_assessment"] is not None:
            assessment_body["prior_assessment"] = preparation["prior_assessment"]
        record = {"schema_version": "1.0", "record_type": "assessment", "scope_id": self.scope_id,
            "namespace": ASSESSMENT_NAMESPACE, "id": assessment_id,
            "provenance": {"origin": "system", "producer": _ENGINE, "recorded_at": built_at,
                           "parents": manifest["positive"]}, "extensions": {PUBLICATION_EXTENSION: publication},
            "body": assessment_body}
        fragment(record, "assessment_input")
        return record, publication

    def prepare_commit(self, prepared, run, *, command_id, idempotency_key, assessment_id, interpretations=(), cache_entries=()):
        if not isinstance(prepared, PreparedAssessment) or not isinstance(run, GraphRun):
            _fail()
        fragment(assessment_id, "identifier")
        preparation, graph = prepared.value, run.value
        entries = [entry.value if hasattr(entry, "value") else deepcopy(entry) for entry in cache_entries]
        record, publication = self._proposal(preparation, graph, list(interpretations), assessment_id, self._now(), entries, view=prepared.view)
        reads = list(preparation["reads"])
        # Existing cache values are immutable by key, but the storage port still
        # requires their exact projection pins for a checked transaction read.
        for entry in entries:
            if entry["stored"] is not None:
                reads.append(entry["stored"])
        request = preparation["request"]
        return validate_command({"schema_version": "1.0", "operation": "commit_assessment", "command_id": command_id,
            "idempotency_key": idempotency_key, "scope_id": self.scope_id, "actor": request["actor"], "authority": request["authority"],
            "expected_revisions": _unique_refs(reads), "body": {"assessment": record},
            "extensions": {PUBLICATION_EXTENSION: publication}})

    def _publication(self, command):
        wrapped = command.get("extensions", {}).get(PUBLICATION_EXTENSION)
        if wrapped is None or type(wrapped) is not dict or "value" not in wrapped:
            _fail("The typed assessment publication extension is required.")
        value = domain("assessment-publication", wrapped["value"])
        if value != wrapped:
            _fail("The publication uses an unknown schema binding.")
        return value["value"]

    def _guards(self, view, preparation, graph, now):
        body = preparation["request"]["body"]
        if self.access is not None:
            if "access_context" not in preparation:
                _fail("The installed access boundary requires its original context.", "E_AUTHORITY_REQUIRED")
            access_reads = [*preparation["current_dependencies"]["positive"],
                *(reference for material in graph["inputs"].values() for reference in material["packet"]["dependencies"]["positive"])]
            self.access.require_current(view, preparation["access_context"], audience=body.get("audience"), references=access_reads)
        elif "access_context" in preparation:
            _fail("The original access boundary is not installed.", "E_AUTHORITY_REQUIRED")
        self.controls._audit(view, preparation["request"], self._read_targets(preparation, graph))
        self.controls.require_current(view, preparation["token"], capability="assessment", targets=self._read_targets(preparation, graph), as_of=now)
        for ref in preparation["current_dependencies"]["positive"]:
            self._read(view, ref)
        for ref in preparation["current_dependencies"]["candidate_sets"]:
            require_current_candidates(view, self.scope_id, ref)
        for ref in preparation["current_dependencies"]["negative_registrations"]:
            require_current_negative_dependency(view, self.scope_id, ref, as_of=now)
        return self._graph(view, preparation, graph, now)

    def check_current(self, prepared, material, *, as_of):
        """Fresh read gate for GraphExecutor, independent of the frozen preparer."""
        if not isinstance(prepared, PreparedAssessment):
            _fail()
        value = material.value if hasattr(material, "value") else material
        with self.storage.snapshot() as view:
            if self.access is not None:
                self.access.require_current(view, prepared.value.get("access_context", {}))
            self._input_current(view, value, prepared.value, fragment(as_of, "known_time"))

    def _require_fresh_result(self, view, publication, assessment, now, admission):
        fresh, _ = self._proposal(publication["preparation"], publication["graph"],
            publication["interpretations"], publication["assessment_id"], now, publication["cache_entries"], view=view, admission=admission)
        fields = ("evaluation_state", "stop_reason", "propositions", "proposals", "evidence_gaps")
        if any(fresh["body"][field] != assessment["body"][field] for field in fields):
            _fail("A published result no longer has its original admissible graph state.", "E_DEPENDENCY_STALE")

    def commit(self, command):
        command = validate_command(command)
        if command["operation"] != "commit_assessment" or command["scope_id"] != self.scope_id:
            _fail()
        publication = self._publication(command)
        preparation, graph = self._preparation(publication["preparation"]), publication["graph"]
        request = validate_command(preparation["request"])
        if command["actor"] != request["actor"] or command["authority"] != request["authority"]:
            _fail(code="E_AUTHORITY_REQUIRED")
        # Rebuild from retained exact bytes; callers cannot prefill arbitrary
        # generated child pins, edited conclusions, causes or qualification.
        expected, wrapped = self._proposal(preparation, graph, publication["interpretations"], publication["assessment_id"],
            publication["built_at"], publication["cache_entries"], view=FrozenAssessmentView(preparation))
        if command["body"]["assessment"] != expected or command["extensions"][PUBLICATION_EXTENSION] != wrapped:
            _fail("The proposed assessment differs from its declared staged inputs.", "E_EVIDENCE_INVALID")
        expected_reads = _unique_refs([*preparation["reads"], *[entry["stored"] for entry in publication["cache_entries"] if entry["stored"] is not None]])
        if command["expected_revisions"] != expected_reads:
            _fail("Publication must retain its complete original checked read set.", "E_EVIDENCE_INVALID")
        def materialize(tx):
            now = self._now()
            for record in preparation["records"]:
                if tx.get(pin(record)) != record:
                    _fail("A retained snapshot differs from its actual stored revision.", "E_EVIDENCE_INVALID")
            admission = self._guards(tx, preparation, graph, now)
            profile, bundles, usable = admission
            self._require_fresh_result(tx, publication, expected, now, admission)
            try:
                current = tx.get(preparation["lane"])
            except StorageError as error:
                if error.code != "E_NOT_FOUND":
                    raise
                current = None
            if (None if current is None else pin(current)) != preparation["previous"]:
                _fail("Another assessment published to this lane.", "E_DEPENDENCY_STALE")
            if current is not None:
                prior = self._current_value(current)
                if (prior["assessment"] != preparation["prior_assessment"] or
                        prior["preparation"]["request"]["body"] != preparation["prior_request"] or
                        self._basis(prior["preparation"]) != preparation["prior_basis"]):
                    _fail("The prior assessment basis changed inside the retained input.", "E_EVIDENCE_INVALID")
            children, ids = [], set()
            for name, bundle in bundles:
                for raw in (bundle.receipt, bundle.judgment):
                    if _identity(raw) in ids:
                        _fail("Staged child identities must be distinct.", "E_EVIDENCE_INVALID")
                    ids.add(_identity(raw))
                def child(raw):
                    try:
                        existing = tx.get(entity_ref(raw))
                    except StorageError as error:
                        if error.code != "E_NOT_FOUND":
                            raise
                        return tx.insert(raw)
                    retained = deepcopy(existing)
                    retained.pop("creation_receipt")
                    if retained != raw:
                        _fail("A staged child identity already contains different original bytes.", "E_EVIDENCE_INVALID")
                    return existing
                receipt = child(bundle.receipt)
                judgment = child(bundle.judgment)
                children.append(pin(judgment))
            actual = deepcopy(expected)
            actual["body"]["judgments"] = children
            actual["provenance"]["parents"] = _unique_refs([*actual["provenance"]["parents"], *children])
            stored = tx.insert(actual)
            if publication["cache_entries"] and self.cache is None:
                _fail("A cache stage requires the exact installed semantic cache.")
            for entry in publication["cache_entries"]:
                self.cache.stage(tx, entry, as_of=now)
            tx.put_projection(preparation["lane"], domain("assessment-current", {"schema_version": "1.0", "status": "current",
                "assessment": pin(stored), "preparation": preparation, "publication": publication, "invalidation": None}))
            return tx.success("committed", {"assessment": pin(stored)})
        def handler(tx):
            try:
                return materialize(tx)
            except StorageError as error:
                if error.code == "E_REVISION_CONFLICT":
                    _fail("An assessment dependency or previously absent current state changed.", "E_DEPENDENCY_STALE")
                raise
        def audit(view):
            self.controls._audit(view, command, self._read_targets(preparation, graph))
        return self.storage.execute(command, handler, replay_guard=audit, dependency_error_code="E_DEPENDENCY_STALE")

    def _current_value(self, record):
        raw = record["value"]
        if raw != domain("assessment-current", raw["value"]):
            _fail("Current assessment projection has an unknown schema.", "E_EVIDENCE_INVALID")
        return raw["value"]

    def read_current(self, view, reference, profile, *, as_of=None):
        """Validate one exact assessment using the caller's consistent view.

        Lifecycle, attention and scheduling share the publication guards instead
        of opening nested snapshots or treating an immutable old result as current.
        The original publication's authority and access context remain mandatory.
        """
        selected = getattr(profile, "reference", profile)
        self.profiles.resolve(selected)
        reference = fragment(reference, "pinned_ref")
        if reference["scope_id"] != self.scope_id:
            _fail(code="E_SCOPE_FORBIDDEN")
        stored = validate_record(view.get(entity_ref(reference)))
        if not matches(stored, reference):
            _fail("The selected assessment revision is no longer current.", "E_DEPENDENCY_STALE")
        if stored["record_type"] != "assessment":
            _fail("The selected record is not an assessment.", "E_EVIDENCE_INVALID")
        body = stored["body"]
        if body["profile"] != selected:
            _fail("The assessment uses another exact policy.", "E_DEPENDENCY_STALE")
        lane = view.get(assessment_current_ref(self.scope_id, body["matter"],
            profile=selected, purpose=body["purpose"], audience=body.get("audience")))
        value = self._current_value(lane)
        if value["status"] != "current" or value["assessment"] != reference:
            _fail("The selected assessment is not current.", "E_DEPENDENCY_STALE")
        preparation, publication = value["preparation"], value["publication"]
        self.controls._audit(view, preparation["request"], self._read_targets(preparation, publication["graph"]))
        now = self._now() if as_of is None else fragment(as_of, "known_time")
        from .dependencies import registration_ref, require_current_dependency
        try:
            registration = view.get(registration_ref(lane))
        except StorageError as error:
            if error.code != "E_NOT_FOUND":
                raise
            registration = None
        if registration is not None:
            require_current_dependency(view, pin(registration), as_of=now, controls=self.controls)
        admission = self._guards(view, preparation, publication["graph"], now)
        self._require_fresh_result(view, publication, stored, now, admission)
        return stored, lane

    def current(self, matter, *, profile, purpose, audience=None):
        self.profiles.resolve(profile)
        reference = assessment_current_ref(self.scope_id, matter, profile=profile, purpose=purpose, audience=audience)
        with self.storage.snapshot() as view:
            try:
                record = view.get(reference)
            except StorageError as error:
                if error.code == "E_NOT_FOUND":
                    return None
                raise
            value = self._current_value(record)
            stored, _ = self.read_current(view, value["assessment"], profile)
            body = stored["body"]
            if body["purpose"] != purpose or body.get("audience") != audience:
                _fail("The lane holds a different exact contextual revision.", "E_DEPENDENCY_STALE")
            return stored

    def attempt(self, idempotency_key):
        """Durable original command/result/receipt, including refused raw attempts."""
        with self.storage.snapshot() as view:
            journal = view.command_receipt(idempotency_key)
            publication = self._publication(journal["command"])
            if self.access is not None:
                self.access.require_current(view, publication["preparation"].get("access_context", {}))
            elif "access_context" in publication["preparation"]:
                _fail("The original access boundary is not installed.", "E_AUTHORITY_REQUIRED")
            self.controls._audit(view, journal["command"], self._read_targets(publication["preparation"], publication["graph"]))
            return journal

    def input_artifact(self, idempotency_key):
        journal = self.attempt(idempotency_key)
        publication = self._publication(journal["command"])
        return canonical_bytes({"preparation": publication["preparation"], "inputs": publication["graph"]["inputs"]})
