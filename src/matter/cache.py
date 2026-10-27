"""MAT-015 declared semantic projections and qualification-aware cache reuse.

Only projected values reach a computation callback. Cached results preserve
their original attempt and control context; a cache hit is never a new provider
trial, a new source, a qualification grant, or an action capability.
"""

from copy import deepcopy

from ._rule_values import FrozenValue, checked, descriptor, domain, fragment
from .canonical import canonical_bytes, canonical_digest
from .contracts import ContractError
from .evaluators import QualificationRegistry
from .negative_dependencies import require_current_negative_dependency
from .planner import read_pointer
from .rules import RuleRegistry, SchemaRegistry
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin
from .time import compare_times


CACHE_NAMESPACE = "matter.semantic_cache"


def _fail(message="The semantic cache declaration is invalid."):
    raise ContractError("E_POLICY_INVALID", message)


def _identity(reference):
    return tuple(reference[key] for key in ("scope_id", "namespace", "id"))


def _refs(values):
    return sorted(deepcopy(list(values)), key=canonical_bytes)


def _read_targets(references):
    # Same filtering as controls.command_targets: internal implementation state
    # is guarded by its owning service, never converted into a user target.
    values = {_identity(ref): entity_ref(ref) for ref in references
        if ref["record_type"] not in {"receipt", "control"} and not
        (ref["record_type"] == PROJECTION_TYPE and ref["namespace"].startswith("matter."))}
    return _refs(values.values())


def cache_ref(scope_id, key):
    return {"scope_id": fragment(scope_id, "identifier"), "namespace": CACHE_NAMESPACE,
            "record_type": PROJECTION_TYPE, "id": "cache-" + fragment(key, "sha256")}


class SemanticComputationDefinition(FrozenValue):
    """Exact rule/binding/preparation plus the only fields a callback can read."""
    __slots__ = ()

    def __init__(self, value, *, rules, bindings):
        if not isinstance(rules, RuleRegistry):
            _fail()
        data = checked(value, required=("namespace", "id", "version", "rule", "binding", "preparation",
                                        "fields", "context_fields", "time_boundaries"), code="E_POLICY_INVALID")
        rule = rules.resolve(data["rule"])
        binding = bindings.resolve(data["binding"])
        if rule.value["evaluator_binding"] != binding.reference or data["preparation"] != rule.value["evidence_preparation"]:
            _fail("The cache must bind the exact rule, evaluator and evidence preparation.")
        for fields, required in ((data["fields"], ("name", "record", "pointer")),
                                 (data["context_fields"], ("name", "pointer"))):
            if type(fields) is not list or len(fields) > 128:
                _fail()
            names = set()
            for raw in fields:
                entry = checked(raw, required=required, code="E_POLICY_INVALID")
                fragment(entry["name"], "identifier")
                if entry["name"] in names:
                    _fail("Projected field names must be unique.")
                names.add(entry["name"])
                if "record" in entry:
                    fragment(entry["record"], "identifier")
                pointer = entry["pointer"]
                if type(pointer) is not str or len(pointer) > 1024 or (pointer and not pointer.startswith("/")):
                    _fail("A projected read requires an exact JSON Pointer.")
                import re
                if re.search(r"~(?![01])", pointer):
                    _fail("A projected read uses invalid JSON Pointer escaping.")
        boundaries = data["time_boundaries"]
        if type(boundaries) is not list or len(boundaries) > 128:
            _fail()
        for index, boundary in enumerate(boundaries):
            fragment(boundary, "known_time")
            if index and compare_times(boundaries[index - 1], boundary) != -1:
                _fail("Temporal equivalence boundaries must be strictly increasing.")
        self._freeze(data)
        self.reference

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["version"], value,
                          "matter.semantic-computation.v1")


class CacheInput(FrozenValue):
    __slots__ = ()

    def __init__(self, value, *, _prepared=False):
        if not _prepared:
            _fail("Use SemanticCache.capture to declare a cache computation.")
        self._freeze(value)

    @property
    def key(self):
        return canonical_digest(self.value["projected"], "matter.semantic-cache-key.v1")

    @property
    def projected(self):
        return self.value["projected"]


class CacheResult(FrozenValue):
    __slots__ = ()

    def __init__(self, value):
        self._freeze(value)

    @property
    def response(self):
        value = self.value
        response = value["entry"]["returned"]["response"]
        # The source claim remains untouched in `entry`. Consumers receive its
        # freshly classified admission state, so expiry cannot look qualified.
        response["qualification"] = value["qualification"]
        return response

    @property
    def cache_hit(self):
        return self.value["cache_hit"]

    @property
    def entry(self):
        return self.value["entry"]


class SemanticCache:
    """Read/compute outside writes; stage entries with the assessment transaction."""

    def __init__(self, *, definitions, rules, bindings, schemas, controls, qualifications=None):
        if not isinstance(schemas, SchemaRegistry) or not isinstance(rules, RuleRegistry):
            _fail()
        self.rules, self.bindings, self.schemas, self.controls = rules, bindings, schemas, controls
        self.qualifications = qualifications or QualificationRegistry()
        values = tuple(definitions)
        if len(values) > 128 or any(not isinstance(item, SemanticComputationDefinition) for item in values):
            _fail()
        if len({canonical_bytes(item.reference) for item in values}) != len(values):
            _fail()
        self.definitions = values

    def _definition(self, reference):
        for definition in self.definitions:
            if definition.reference == reference:
                return definition
        _fail("The exact semantic computation definition is not installed.")

    def capture(self, view, definition, *, records, context, token, as_of, negative_dependencies=(),
                qualification_context=(), citations=()):
        """Capture only declared fields; absent fields fail rather than default.

        `records` maps declaration roles to exact current pins. Full records and
        unused context wrappers are never passed to the computation callback.
        An empty temporal-boundary list explicitly declares clock independence.
        """
        if not isinstance(definition, SemanticComputationDefinition):
            _fail()
        self._definition(definition.reference)
        if type(records) is not dict or type(context) is not dict:
            _fail()
        canonical_bytes(context)
        now = fragment(as_of, "known_time")
        expected_roles = {item["record"] for item in definition.value["fields"]}
        if set(records) != expected_roles:
            _fail("Record roles must exactly match the declared projection.")
        snapshots, pins = {}, {}
        for role, reference in records.items():
            ref = fragment(reference, "pinned_ref")
            current = view.get(entity_ref(ref))
            if pin(current) != ref:
                raise StorageError("E_DEPENDENCY_STALE")
            snapshots[role], pins[role] = current, ref
        targets = _read_targets(pins.values())
        self.controls.require_current(view, token, capability="assessment", targets=targets or token["targets"], as_of=now)
        if targets:
            self.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])}, targets)
        negative = []
        for reference in negative_dependencies:
            registration = require_current_negative_dependency(view, self.controls.scope_id, reference, as_of=now)
            negative.append(pin(registration))
        projected_fields = []
        for item in definition.value["fields"]:
            projected_fields.append({"name": item["name"], "record": entity_ref(pins[item["record"]]),
                "value": read_pointer(snapshots[item["record"]], item["pointer"])})
        projected_context = [{"name": item["name"], "value": read_pointer(context, item["pointer"])}
                             for item in definition.value["context_fields"]]
        qcontext = [fragment(item, "component_ref") for item in qualification_context]
        exact_citations = deepcopy(list(citations))
        for item in exact_citations:
            checked(item, required=("reference", "locator"))
            fragment(item["reference"], "pinned_ref")
            fragment(item["locator"], "locator")
        interval = sum(compare_times(now, boundary) in {0, 1} for boundary in definition.value["time_boundaries"])
        projected = {"definition": definition.reference, "fields": projected_fields, "context": projected_context,
                     "temporal_class": interval, "negative_registrations": _refs(negative),
                     "qualification_context": qcontext, "citations": exact_citations}
        return CacheInput({"schema_version": "1.0", "scope_id": self.controls.scope_id, "definition": definition.reference,
            "projected": projected, "records": pins, "context": context, "token": deepcopy(token),
            "as_of": now, "negative_dependencies": negative, "qualification_context": qcontext, "citations": exact_citations}, _prepared=True)

    def _current(self, view, original, current, now):
        # The fresh caller input cannot replace the original cached token. Check
        # it separately even if a new token happens to have the same epoch.
        definition = self._definition(original["definition"])
        targets = _read_targets(original["records"].values())
        self.controls.require_current(view, original["token"], capability="assessment", targets=targets or original["token"]["targets"], as_of=now)
        if targets:
            self.controls._audit(view, {"actor": original["token"]["actor"],
                "authority": entity_ref(original["token"]["authority"])}, targets)
        refreshed_refs = {role: pin(view.get(entity_ref(ref))) for role, ref in original["records"].items()}
        refreshed = self.capture(view, definition, records=refreshed_refs, context=current["context"],
            token=original["token"], as_of=now, negative_dependencies=original["negative_dependencies"],
            qualification_context=current["qualification_context"], citations=current["citations"])
        if refreshed.projected != current["projected"]:
            raise StorageError("E_DEPENDENCY_STALE", "The original cache computation is no longer semantically equivalent.")

    def _validate_returned(self, returned, request):
        returned = checked(returned, required=("response", "raw_result"))
        response = domain("rule-evaluator-response", returned["response"])["value"]
        fragment(returned["raw_result"], "raw_result_reference")
        rule = self.rules.resolve(self._definition(request["definition"]).value["rule"])
        if response["execution_status"] != "completed":
            _fail("Only completed semantic computations can populate the cache.")
        output = self.schemas.validate(response["semantic_output"])
        if output["schema"] != rule.value["output_schema"]:
            _fail("Cached output must use the exact rule schema.")
        outcome = rule.outcome(output["value"].get("label"))
        if outcome["evaluation_status"] != response["evaluation_status"]:
            _fail("Cached semantic labels must retain their declared outcome status.")
        if any(use not in request["citations"] for use in response["used_evidence"]):
            raise StorageError("E_EVIDENCE_INVALID", "Cached citations must come from the declared exact input.")
        for proposal in response["proposed_consequences"]:
            self.schemas.validate(proposal)
            if proposal["schema"] not in outcome["implications"]:
                raise StorageError("E_AUTHORITY_REQUIRED")
        return returned

    def _classification(self, entry, now):
        definition = self._definition(entry["request"]["definition"])
        rule = self.rules.resolve(definition.value["rule"])
        return self.qualifications.classify(entry["returned"]["response"]["qualification"], rule=rule,
            binding=self.bindings.resolve(definition.value["binding"]),
            context=entry["request"]["qualification_context"], as_of=now)

    def get_or_compute(self, view, request, *, compute, attempt_id, as_of):
        if not isinstance(request, CacheInput) or not callable(compute):
            _fail()
        fragment(attempt_id, "identifier")
        now = fragment(as_of, "known_time")
        data = request.value
        self._current(view, data, data, now)
        reference = cache_ref(data["scope_id"], request.key)
        try:
            stored = view.get(reference)
        except StorageError as error:
            if error.code != "E_NOT_FOUND":
                raise
            stored = None
        if stored is None:
            # This is the complete callback input. No unselected record, exact
            # wrapper revision, audience preference or delivery packet leaks in.
            returned = self._validate_returned(compute(deepcopy(data["projected"])), data)
            entry = {"schema_version": "1.0", "scope_id": data["scope_id"], "key": request.key,
                     "request": data, "returned": returned, "source_attempt_id": attempt_id, "created_at": now}
            domain("cache-entry", entry)
        else:
            entry = checked(stored["value"]["value"], required=("schema_version", "scope_id", "key", "request",
                "returned", "source_attempt_id", "created_at"))
            if (stored["value"] != domain("cache-entry", entry) or entry["key"] != request.key or
                    canonical_digest(entry["request"]["projected"], "matter.semantic-cache-key.v1") != entry["key"] or
                    entity_ref(stored) != reference):
                raise StorageError("E_EVIDENCE_INVALID")
            self._current(view, entry["request"], data, now)
            self._validate_returned(entry["returned"], data)
        return CacheResult({"cache_hit": stored is not None, "entry": entry,
                            "qualification": self._classification(entry, now),
                            "source_attempt_id": entry["source_attempt_id"],
                            "current_input": data, "stored": pin(stored) if stored is not None else None})

    def stage(self, tx, result, *, as_of):
        data = result.value if isinstance(result, CacheResult) else checked(result,
            required=("cache_hit", "entry", "qualification", "source_attempt_id", "current_input", "stored"))
        entry = data["entry"]
        request = data["current_input"]
        self._current(tx, entry["request"], request, as_of)
        self._validate_returned(entry["returned"], request)
        if canonical_digest(request["projected"], "matter.semantic-cache-key.v1") != entry["key"]:
            raise StorageError("E_EVIDENCE_INVALID")
        if canonical_digest(entry["request"]["projected"], "matter.semantic-cache-key.v1") != entry["key"]:
            raise StorageError("E_EVIDENCE_INVALID")
        reference = cache_ref(entry["scope_id"], entry["key"])
        try:
            previous = tx.get(reference)
        except StorageError as error:
            if error.code != "E_NOT_FOUND":
                raise
            previous = None
        if previous is None:
            return tx.put_projection(reference, domain("cache-entry", entry))
        if previous["value"] != domain("cache-entry", entry):
            raise StorageError("E_REVISION_CONFLICT", "An exact cache key already retains another original attempt.")
        return previous
