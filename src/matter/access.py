"""MAT-072 host-declared source eligibility and current audience/provider egress.

This is an adapter boundary over existing source pins and ControlService, not
authentication, source truth, a redactor or a Python sandbox. Raw host storage
and payload handles remain privileged and must not be exposed as user APIs.
"""

from copy import deepcopy

from ._rule_values import FrozenValue, bounded, checked, descriptor, domain, fragment
from .canonical import canonical_bytes, canonical_digest
from .contracts import ContractError
from .controls import ControlService
from .storage import PROJECTION_TYPE, StorageError, entity_ref, pin


MAX_SOURCES = 256
MAX_REFERENCE_OCCURRENCES = 65536


def _fail(reason="forbidden", code="E_AUTHORITY_REQUIRED"):
    # No source name, locator, quotation, caller value or adapter exception is
    # echoed. Even a source identity may itself be restricted information.
    raise ContractError(code, "Access boundary: " + reason + ".") from None


def _key(value):
    return canonical_bytes(value)


def is_source_access_target(ref):
    """Classify an already validated reference for source-access handling.

    False excludes receipts, controls and internal ``matter.*`` projections
    from source grants. It does not permit their disclosure. True establishes
    neither public availability nor a grant: HostAccessPolicy, READ authority,
    transitive parent access, currentness and revocation still apply.
    Accepts validated record, entity or pinned references; performs no schema
    validation, storage read, permission lookup or mutation.
    """
    return ref["record_type"] not in {"receipt", "control"} and not (
        ref["record_type"] == PROJECTION_TYPE and ref["namespace"].startswith("matter."))


# Preserve existing imports as an alias of the public classifier.
_public = is_source_access_target


def _pins(values, *, historical_metadata=False):
    result = {}
    for index, raw in enumerate(values):
        if index >= MAX_REFERENCE_OCCURRENCES:
            _fail("reference_budget", "E_BUDGET_EXHAUSTED")
        ref = fragment(raw, "pinned_ref")
        identity = _key(ref) if historical_metadata else _key(entity_ref(ref))
        if identity in result and result[identity] != ref:
            _fail("unavailable", "E_EVIDENCE_UNAVAILABLE")
        result[identity] = ref
        if len(result) > MAX_SOURCES:
            _fail("source_budget", "E_BUDGET_EXHAUSTED")
    return sorted(result.values(), key=_key)


def _context_metadata(record):
    """An exact native context pointer, not a source or arbitrary projection."""
    if record["record_type"] != PROJECTION_TYPE:
        return False
    wrapped = record["value"]
    if wrapped.get("schema", {}).get("id") != "context-current":
        return False
    return wrapped == domain("context-current", wrapped["value"]) and wrapped["value"]["scope_id"] == record["scope_id"]


def _provenance_record(view, ref, *, parent=False, historical=False):
    if parent:
        head = view.get(entity_ref(ref))
        if pin(head) != ref and _context_metadata(head):
            original = view.get_historical(ref)
            if not _context_metadata(original):
                _fail("unavailable", "E_EVIDENCE_UNAVAILABLE")
            return original, head
    record = view.get(ref if historical else entity_ref(ref))
    if pin(record) != ref:
        _fail("stale_source_context", "E_DEPENDENCY_STALE")
    return record, None


def source_access_provenance(view, roots):
    """Bounded exact grant candidates for an already host-authorized history.

    This privileged storage helper grants nothing. The host must authorize each
    returned pin before building its policy. Context provenance keeps the old
    snapshot plus today's head; other current sources never silently rebind.
    """
    found, active = {}, set()
    def visit(ref, parent=False):
        ref = fragment(ref, "pinned_ref")
        if not _public(ref):
            return
        key = _key(ref)
        if key in active:
            _fail("unavailable", "E_EVIDENCE_UNAVAILABLE")
        if key in found:
            return
        if len(found) + len(active) >= MAX_SOURCES:
            _fail("source_budget", "E_BUDGET_EXHAUSTED")
        record, head = _provenance_record(view, ref, parent=parent)
        active.add(key)
        if head is not None:
            visit(pin(head))
        for p in record.get("provenance", {}).get("parents", []):
            visit(p, True)
        active.remove(key)
        found[key] = ref
    roots = _pins(roots)
    for root in roots:
        if _public(root) and root["record_type"] == PROJECTION_TYPE:
            _provenance_record(view, root)
    for root in roots:
        visit(root)
    return sorted(found.values(), key=_key)


class HostAccessPolicy(FrozenValue):
    """An immutable authenticated-host allowlist; evidence cannot mint it.

    Each grant binds an exact source snapshot, exact audience versions and exact
    provider versions. Empty lists deny. Local reads use provider=None. Public
    provenance parents restrict derivations conjunctively; a derivation cannot
    override a parent by copying a more permissive sharing label.
    """
    __slots__ = ()

    def __init__(self, *, scope_id, audiences, providers, grants):
        scope = fragment(scope_id, "identifier")
        audience_refs = sorted([fragment(item, "component_ref") for item in bounded(audiences, 128)], key=_key)
        provider_values = []
        for raw in bounded(providers, 32):
            value = checked(raw, required=("reference", "provider", "transport"))
            fragment(value["reference"], "component_ref")
            for field in ("provider", "transport"):
                fragment(value[field], "text")
            provider_values.append(value)
        source_values = []
        known_providers = [item["reference"] for item in provider_values]
        for raw in bounded(grants, MAX_SOURCES):
            value = checked(raw, required=("reference", "audiences", "providers"))
            ref = fragment(value["reference"], "pinned_ref")
            if ref["scope_id"] != scope or not _public(ref):
                _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
            for field, known in (("audiences", audience_refs), ("providers", known_providers)):
                value[field] = sorted([fragment(item, "component_ref") for item in bounded(value[field], 128)], key=_key)
                if any(item not in known for item in value[field]) or len({_key(item) for item in value[field]}) != len(value[field]):
                    _fail("invalid_host_policy", "E_POLICY_INVALID")
            source_values.append(value)
        if (len({_key(item) for item in audience_refs}) != len(audience_refs) or
                len({_key(item["reference"]) for item in provider_values}) != len(provider_values) or
                len({_key(item["reference"]) for item in source_values}) != len(source_values)):
            _fail("invalid_host_policy", "E_POLICY_INVALID")
        self._freeze({"scope_id": scope, "audiences": audience_refs,
                      "providers": sorted(provider_values, key=_key), "grants": sorted(source_values, key=_key)})

    @property
    def reference(self):
        return descriptor("matter", "host-access-policy", "1.0", self.value, "matter.host-access-policy.v1")


class AccessContext(FrozenValue):
    """Serializable exact access identity; its existence does not grant access."""
    __slots__ = ()

    def __init__(self, value):
        data = checked(value, required=("schema_version", "scope_id", "policy", "audience", "provider", "token", "references", "dependencies"))
        if data["schema_version"] not in {"1.0", "1.1"}:
            _fail("invalid_context", "E_SCHEMA_INVALID")
        fragment(data["scope_id"], "identifier")
        fragment(data["policy"], "component_ref")
        fragment(data["audience"], "component_ref")
        if data["provider"] is not None:
            fragment(data["provider"], "component_ref")
        domain("control-token", data["token"])
        if data["references"] != _pins(data["references"]) or data["dependencies"] != _pins(
                data["dependencies"], historical_metadata=data["schema_version"] == "1.1"):
            _fail("invalid_context", "E_SCHEMA_INVALID")
        self._freeze(data)

    @property
    def reference(self):
        return descriptor("matter", "access-context", self.value["schema_version"], self.value, "matter.access-context.v1")

    @property
    def eligibility_reference(self):
        data = self.value
        return descriptor("matter", "access-eligibility", "1.0",
            {key: data[key] for key in ("policy", "audience", "provider", "dependencies")},
            "matter.access-eligibility.v1")

    @property
    def status(self):
        return "permitted" if self.value["references"] else "permitted_empty"


class AccessService:
    def __init__(self, *, policy, controls, current_read=None):
        if (not isinstance(policy, HostAccessPolicy) or not isinstance(controls, ControlService) or
                (current_read is not None and not callable(current_read))):
            _fail("invalid_host_policy", "E_POLICY_INVALID")
        if policy.value["scope_id"] != controls.scope_id:
            _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
        self.policy, self.controls, self.scope_id = policy, controls, controls.scope_id
        self.current_read = current_read

    def _closure(self, view, references, audience, provider, token, *, historical=False):
        definition = self.policy.value
        if audience not in definition["audiences"] or (provider is not None and provider not in [item["reference"] for item in definition["providers"]]):
            _fail()
        grants = {_key(item["reference"]): item for item in definition["grants"]}
        visited, active = {}, set()
        def visit(raw, parent=False):
            ref = fragment(raw, "pinned_ref")
            if ref["scope_id"] != self.scope_id:
                _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
            if not _public(ref):
                return
            key = _key(ref)
            if key in visited:
                return
            if key in active or len(visited) + len(active) >= MAX_SOURCES:
                _fail("unavailable", "E_EVIDENCE_UNAVAILABLE")
            grant = grants.get(key)
            if grant is not None and (audience not in grant["audiences"] or (provider is not None and provider not in grant["providers"])):
                _fail()
            # Verify READ before retrieving a possibly protected body.
            self.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])}, [entity_ref(ref)])
            try:
                record, head = _provenance_record(view, ref, parent=parent, historical=historical)
            except StorageError as error:
                if error.code == "E_NOT_FOUND":
                    if grant is None:
                        _fail()
                    _fail("unavailable", "E_EVIDENCE_UNAVAILABLE")
                raise
            # Host metadata projections have no source provenance. They need
            # their own exact grant and cannot implicitly inherit a source ACL.
            provenance = record.get("provenance", {})
            parents = [item for item in provenance.get("parents", []) if _public(item)]
            derived = provenance.get("origin") in {"derived", "evaluator"} or record["record_type"] in {"judgment", "assessment"}
            if grant is None and not (derived and parents):
                _fail()
            active.add(key)
            if head is not None:
                # Both exact snapshots need real present grants. The old pin
                # remains provenance, while the current head fences changes.
                visit(pin(head))
            for parent in parents:
                visit(parent, True)
            active.remove(key)
            visited[key] = ref
        if not historical:
            # Root currentness cannot depend on whether an earlier traversal
            # happened to visit this same pin as historical provenance.
            for ref in references:
                if _public(ref) and ref["record_type"] == PROJECTION_TYPE:
                    self.controls._audit(view, {"actor": token["actor"], "authority": entity_ref(token["authority"])}, [entity_ref(ref)])
                    _provenance_record(view, ref)
        for ref in references:
            visit(ref)
        return sorted(visited.values(), key=_key)

    def capture(self, view, *, token, audience, references, provider=None):
        """Use the original token; never capture or renew a ControlService token."""
        refs = _pins(references)
        try:
            domain("control-token", token)
            if token["scope_id"] != self.scope_id:
                _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
            dependencies = self._closure(view, refs, audience, provider, token)
            targets = list({_key(entity_ref(ref)): entity_ref(ref) for ref in dependencies}.values())
            self.controls.require_current(view, token, capability=token["capability"], targets=targets or token["targets"])
        except StorageError as error:
            if error.code == "E_REVISION_CONFLICT":
                _fail("stale_control_context", "E_DEPENDENCY_STALE")
            reasons = {"E_DEPENDENCY_STALE": "stale_control_context", "E_CANCELLED": "cancelled",
                       "E_BUDGET_EXHAUSTED": "budget_exhausted", "E_STORAGE_UNAVAILABLE": "unavailable"}
            if error.code in reasons:
                _fail(reasons[error.code], error.code)
            _fail("unavailable" if error.code in {"E_NOT_FOUND", "E_STORAGE_UNAVAILABLE"} else "forbidden",
                  "E_EVIDENCE_UNAVAILABLE" if error.code in {"E_NOT_FOUND", "E_STORAGE_UNAVAILABLE"} else "E_AUTHORITY_REQUIRED")
        identities = [_key(entity_ref(ref)) for ref in dependencies]
        version = "1.1" if len(set(identities)) != len(identities) else "1.0"
        return AccessContext({"schema_version": version, "scope_id": self.scope_id, "policy": self.policy.reference,
            "audience": audience, "provider": provider, "token": deepcopy(token), "references": refs, "dependencies": dependencies})

    def require_current(self, view, context, *, references=(), audience=None, provider=None, _fresh=False):
        if not isinstance(context, AccessContext):
            try:
                context = AccessContext(context)
            except (ContractError, TypeError, ValueError):
                _fail()
        data = context.value
        if (data["policy"] != self.policy.reference or data["scope_id"] != self.scope_id or
                (audience is not None and audience != data["audience"]) or
                (provider is not None and provider != data["provider"])):
            _fail()
        refs = _pins(references)
        if any(ref["scope_id"] != self.scope_id for ref in refs):
            _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
        if any(ref not in data["dependencies"] for ref in refs if _public(ref)):
            _fail()
        fresh = self.capture(view, token=data["token"], audience=data["audience"], provider=data["provider"], references=data["references"])
        if fresh.value != data:
            _fail()
        # A real current transaction is already the atomic guard. Detached
        # computation and dispatch need a fresh host read; no token is renewed.
        from .assessments import FrozenAssessmentView
        if _fresh or isinstance(view, FrozenAssessmentView):
            if self.current_read is None:
                _fail("fresh_read_required")
            with self.current_read() as live:
                current = self.capture(live, token=data["token"], audience=data["audience"],
                    provider=data["provider"], references=data["references"])
            if current.value != data:
                _fail()
        return context

    def require_history(self, view, context, *, references=()):
        """Present READ/grants on original snapshots, without renewing old work.

        History remains inspectable after benign source/control revisions. This
        never authorizes dispatch, cache reuse or current assessment admission.
        """
        try:
            admitted = context if isinstance(context, AccessContext) else AccessContext(context)
        except (ContractError, TypeError, ValueError):
            _fail()
        data = admitted.value
        if data["scope_id"] != self.scope_id:
            _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
        refs = _pins(references)
        if any(ref["scope_id"] != self.scope_id for ref in refs):
            _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
        if any(ref not in data["dependencies"] for ref in refs if _public(ref)):
            _fail()
        try:
            dependencies = self._closure(view, data["references"], data["audience"], data["provider"],
                data["token"], historical=True)
        except StorageError as error:
            if error.code in {"E_STORAGE_UNAVAILABLE", "E_DEPENDENCY_STALE", "E_BUDGET_EXHAUSTED"}:
                _fail("history_unavailable", error.code)
            if error.code == "E_NOT_FOUND":
                _fail("unavailable", "E_EVIDENCE_UNAVAILABLE")
            _fail()
        if dependencies != data["dependencies"]:
            _fail()
        return admitted

    def view(self, view, context):
        self.require_current(view, context)
        return _AccessView(self, view, context)

    def require_packet(self, view, context, state, *, _fresh=False):
        context = self.require_current(view, context, _fresh=_fresh)
        if type(state) is not dict or state.get("scope_id") != self.scope_id:
            _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
        if state.get("access_context") != context.reference:
            _fail()
        refs = []
        def scan(value):
            if type(value) is dict:
                if {"scope_id", "namespace", "record_type", "id"} <= set(value):
                    ref = entity_ref(value)
                    if ref["scope_id"] != self.scope_id:
                        _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
                    if _public(ref):
                        # Every public data reference must be exact.
                        refs.append(fragment(value, "pinned_ref"))
                        return
                for item in value.values():
                    scan(item)
            elif type(value) is list:
                for item in value:
                    scan(item)
        scan(state)
        self.require_current(view, context, references=refs, _fresh=_fresh)
        return context

    def dispatch(self, view, context, batch, executor, *, rendered_questions, clock, precision=None):
        """Current egress gate immediately before the injected executor seam.

        External I/O after this authorization point remains host-owned; this
        synchronous call cannot retract an already sent request or preempt it.
        """
        from .semantic.contracts import execute_batch
        from .semantic.rendering import RenderedQuestion
        admitted = self.require_packet(view, context, batch.value["state"], _fresh=True)
        if batch.value["scope_id"] != self.scope_id:
            _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
        if not isinstance(rendered_questions, (list, tuple)) or not 1 <= len(rendered_questions) <= 128:
            _fail()
        rendered = list(rendered_questions)
        if (any(not isinstance(item, RenderedQuestion) or item.manifest.get("access_context") != admitted.reference
                for item in rendered) or [item.question.value for item in rendered] != batch.value["questions"] or
                admitted.value["token"]["capability"] != "assessment"):
            _fail()
        provider = next((item for item in self.policy.value["providers"] if item["reference"] == admitted.value["provider"]), None)
        if provider is None or any(batch.value["context"][key] != provider[key] for key in ("provider", "transport")):
            _fail()
        result = execute_batch(executor, batch, clock=clock, precision=precision)
        self.require_packet(view, context, batch.value["state"], _fresh=True)
        return result

    def explain(self, view, context, reference):
        """Render only an actual eligible assessment, never raw attempt journals."""
        admitted = self.require_current(view, context)
        ref = fragment(reference, "assessment_dependency")
        if ref["scope_id"] != self.scope_id:
            _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
        data = admitted.value
        try:
            dependencies = self._closure(view, [ref], data["audience"], data["provider"], data["token"])
            record = view.get(ref)
            if record["body"].get("audience") != data["audience"]:
                _fail()
            for dependency in dependencies:
                if dependency not in data["dependencies"]:
                    derived = view.get(dependency)
                    if (derived["record_type"] not in {"assessment", "judgment"} and
                            derived["provenance"]["origin"] not in {"derived", "evaluator"}):
                        _fail()
        except StorageError:
            _fail()
        self.require_current(view, admitted)
        return {"status": "permitted", "assessment": pin(record), "access_context": admitted.reference,
                **{key: deepcopy(record["body"][key]) for key in ("propositions", "proposals", "causes", "limitations")}}

    @staticmethod
    def public_failure(error):
        """Fixed public coverage/error outcome with no denied audit references."""
        code = getattr(error, "code", None)
        distinct = {"E_DEPENDENCY_STALE": {"status": "stale", "reason": "context_changed"},
                    "E_CANCELLED": {"status": "cancelled", "reason": "host_cancelled"},
                    "E_BUDGET_EXHAUSTED": {"status": "budget_exhausted", "reason": "resource_limit"}}
        if code in distinct:
            return deepcopy(distinct[code])
        unavailable = code in {"E_EVIDENCE_UNAVAILABLE", "E_STORAGE_UNAVAILABLE"}
        return {"status": "unavailable" if unavailable else "forbidden",
                "reason": "source_unavailable" if unavailable else "access_forbidden"}


class _AccessView:
    def __init__(self, access, view, context):
        self.access, self._view, self.context = access, view, context

    def get(self, reference):
        if reference["scope_id"] != self.access.scope_id:
            _fail("scope_forbidden", "E_SCOPE_FORBIDDEN")
        try:
            record = self._view.get(reference)
        except StorageError as error:
            if error.code == "E_NOT_FOUND" and _public(reference):
                _fail("unavailable", "E_EVIDENCE_UNAVAILABLE")
            raise
        if _public(reference):
            self.access.require_current(self._view, self.context, references=[pin(record)])
        return deepcopy(record)

    def lookup_identity(self, reference):
        return self.get(reference)

    def receipt_for(self, reference):
        self.get(reference)
        return self._view.receipt_for(reference)
