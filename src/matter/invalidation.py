"""MAT-016 atomic, bounded transitive invalidation through storage hooks.

The constructor-installed host hook receives actual transactional writes and
typed core notices. It never executes source text, dispatches an action, or
updates state after the source transaction has committed.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone

from ._rule_values import domain, fragment
from .canonical import canonical_bytes, canonical_digest
from .contracts import ContractError, validate_record
from .coverage import match_observation
from .dependencies import (
    MAX_DEPENDENCIES, MAX_REASONS, MAX_LIVE_TEMPORAL, _current, _fail, _identity, _lookup, _scoped, _scope_fence,
    capture_dependencies, object_watch, query_watch, read_registration, recomputation_token,
    register_dependency, registration_ref, scope_fence_ref, due_time_watch_keys, watch_keys,
)
from .identity_dependencies import _value
from .source_catalogs import source_key
from .storage import PROJECTION_TYPE, entity_ref, pin
from .time import compare_times


def _now():
    return {"state": "known", "value": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"), "precision": "microsecond"}


def _changes(scope, changes, receipt):
    """Deduplicate equivalent actual-write/typed notices; prefer typed causes."""
    found = {}
    if type(changes) is not list or len(changes) > MAX_DEPENDENCIES:
        _fail(code="E_BUDGET_EXHAUSTED")
    for raw in changes:
        if type(raw) is not dict or set(raw) != {"cause", "before", "after"}:
            _fail(code="E_SCHEMA_INVALID")
        fragment(raw["cause"], "text")
        before = sorted([_scoped(scope, ref) for ref in raw["before"]], key=canonical_bytes)
        after = sorted([_scoped(scope, ref) for ref in raw["after"]], key=canonical_bytes)
        if before == after:
            continue
        meaning = {"before": before, "after": after}
        identity = canonical_digest(meaning, "matter.dependency-change.v1")
        if identity not in found or found[identity]["cause"] == "write":
            found[identity] = {"id": identity, "cause": raw["cause"], "receipt": receipt, **meaning}
    return [found[key] for key in sorted(found)]


def _affected(body, reference, reason, *, logical=False):
    target = body["target"]
    candidates = [target, *[ref for name in ("positive", "contexts", "candidate_sets", "negative_registrations") for ref in body["manifest"][name]]]
    for dependency in candidates:
        if _identity(dependency) == _identity(reference):
            if logical or dependency not in reason["after"]:
                return True
    token = body["manifest"]["control_token"]
    if token is not None:
        for fence in token["fences"]:
            if _identity(fence["reference"]) == _identity(reference) and (logical or fence["pin"] not in reason["after"]):
                return True
    for access in body["manifest"]["read_access"]:
        for fence in access["fences"]:
            if _identity(fence["reference"]) == _identity(reference) and (logical or fence["pin"] not in reason["after"]):
                return True
    return False


class _RegistrationView:
    """Allow bounded due-plus-future capacity rows before the hook flushes."""

    def __init__(self, transaction):
        self.transaction = transaction

    def __getattr__(self, name):
        return getattr(self.transaction, name)

    def watchers(self, key):
        if key.startswith("dependency-time-"):
            return self.transaction.watchers(key, limit=2 * MAX_LIVE_TEMPORAL)
        return self.transaction.watchers(key)


class InvalidationHook:
    """Install on every participating SQLiteStore handle for atomic updates.

    ``controls`` is the actual host service for original token admission, not a
    serialized claim of authority. Raw unconfigured storage remains privileged;
    freshness checks still reread dependencies and refuse stale use.
    """

    def __init__(self, *, clock=None, controls=None):
        if clock is not None and not callable(clock):
            _fail(code="E_POLICY_INVALID")
        self.clock, self.controls = clock or _now, controls

    def _capture(self, tx, target, *, positive=(), contexts=(), candidate_sets=(), negative=(), conditions=(), token=None):
        tx = _RegistrationView(tx)
        now = fragment(self.clock(), "known_time")
        manifest = capture_dependencies(tx, scope_id=tx.command["scope_id"], as_of=now, positive=positive,
            contexts=contexts, candidate_sets=candidate_sets, negative_registrations=negative,
            time_conditions=conditions, control_token=token, controls=self.controls)
        old = _lookup(tx, registration_ref(target))
        if old is not None:
            old_body = read_registration(tx, pin(old))["value"]["value"]
            if old_body["status"] == "current" and old_body["target"] == target and old_body["manifest"] == manifest.value:
                return old
        previous = None if old is None else recomputation_token(tx, pin(old))
        return register_dependency(tx, target, manifest, as_of=now, controls=self.controls, previous=previous)

    def _register_assessment(self, tx, lane):
        """Narrow adapter for actual MAT-015 publication, never arbitrary data."""
        value = _value("assessment-current", lane["value"])
        if value["status"] != "current":
            return set()
        scope = tx.command["scope_id"]
        assessment = validate_record(_current(tx, scope, value["assessment"]))
        preparation = value["preparation"]
        dependencies = preparation["current_dependencies"]
        if preparation["lane"] != entity_ref(lane) or assessment["record_type"] != "assessment":
            _fail()
        proof_only = {_identity(ref) for ref in preparation["proof_reads"] if ref not in dependencies["positive"]}
        created = set()
        # Node inputs and stored child pins are matched by identity, never order.
        raw_nodes = value["publication"]["graph"]["nodes"]
        by_id = {_identity(node["judgment"]): name for name, node in raw_nodes.items() if node.get("judgment") is not None}
        for reference in assessment["body"]["judgments"]:
            judgment = validate_record(_current(tx, scope, reference))
            name = by_id.get(_identity(judgment))
            if name is None:
                _fail("A published judgment has no retained graph input.")
            packet = value["publication"]["graph"]["inputs"][name]["packet"]
            original_token = None
            if packet["control_token_digest"] is not None:
                original_token = next((token for token in [preparation["token"], *preparation["control_contexts"]]
                    if canonical_digest(token, "matter.evaluation-control.v1") == packet["control_token_digest"]), None)
                if original_token is None:
                    _fail("A published judgment lost its original control context.", "E_POLICY_INVALID")
            manifest = judgment["body"]["dependency_manifest"]
            positive = [ref for ref in manifest["positive"] if _identity(ref) not in proof_only]
            record = self._capture(tx, reference, positive=positive, negative=packet["negative_registrations"],
                                   conditions=manifest["time_conditions"], token=original_token)
            created.add(_identity(record))
        semantic = [*dependencies["positive"], *assessment["body"]["judgments"]]
        record = self._capture(tx, pin(assessment), positive=semantic, candidate_sets=dependencies["candidate_sets"],
                               negative=dependencies["negative_registrations"],
                               conditions=assessment["body"]["dependency_manifest"]["time_conditions"], token=preparation["token"])
        created.add(_identity(record))
        record = self._capture(tx, pin(lane), positive=[pin(assessment)], token=preparation["token"])
        created.add(_identity(record))
        return created

    def __call__(self, tx, changes):
        try:
            if tx.command["operation"] == "record_control":
                # Explicit control-time repair of damaged derivative metadata;
                # ordinary intake needs only the verified fence envelope/pin.
                _scope_fence(tx, tx.command["scope_id"])
            return self._apply(tx, changes)
        except ContractError as error:
            if tx.command["operation"] != "record_control" or error.code == "E_STORAGE_UNAVAILABLE":
                raise
            # The host's already-admitted control must not wait behind graph
            # capacity or damaged derivative metadata. This bounded scoped fence
            # invalidates freshness even when full traversal was not possible.
            address = scope_fence_ref(tx.command["scope_id"])
            old = _lookup(tx, address)
            # The storage envelope/revision is already verified. The obsolete
            # domain payload may itself be damaged derivative metadata; parsing
            # it here would repeat the failure that the control fallback must
            # bypass. Freshness binds the exact projection pin, not this value.
            prior = 0 if old is None else old["revision"]
            tx.put_projection(address, domain("dependency-scope-fence", {"scope_id": tx.command["scope_id"],
                "epoch": prior + 1, "reason": "control_graph_fallback", "receipt": tx.receipt_ref}))

    def _apply(self, tx, changes):
        scope, now = tx.command["scope_id"], fragment(self.clock(), "known_time")
        changes = deepcopy(changes)
        observed = set()
        for change in list(changes):
            for reference in change["after"]:
                if reference["record_type"] == "observation" and canonical_bytes(reference) not in observed:
                    observed.add(canonical_bytes(reference))
                    observation = validate_record(_current(tx, scope, reference))
                    if observation.get("supersedes"):
                        changes.append({"cause": "evidence_correction", "before": observation["supersedes"], "after": [reference]})
        notices = _changes(scope, changes, tx.receipt_ref)
        new_registrations = set()
        for notice in notices:
            for reference in notice["after"]:
                if reference["namespace"] == "matter.assessments" and reference["record_type"] == PROJECTION_TYPE:
                    lane = _current(tx, scope, reference)
                    if lane["value"]["value"].get("status") == "current":
                        new_registrations.update(self._register_assessment(tx, lane))
        staged, queue, visited = {}, deque(), set()

        def record(reference):
            identity = _identity(reference)
            if identity not in staged:
                if len(staged) >= MAX_DEPENDENCIES:
                    _fail(code="E_BUDGET_EXHAUSTED")
                current = read_registration(tx, reference)
                staged[identity] = {"record": current, "body": deepcopy(current["value"]["value"]), "changed": False}
            return staged[identity]

        def mark(reference, reason):
            entry = record(reference)
            body = entry["body"]
            if any(item["id"] == reason["id"] for item in body["reasons"]):
                return
            if _identity(entry["record"]) in new_registrations:
                # A freshly recomputed result already binds after-images. If
                # its inputs actually remain stale, registration refused it.
                return
            if len(body["reasons"]) >= MAX_REASONS:
                # Older reasons remain in immutable projection history. Keep a
                # bounded current tail without preventing future host controls.
                body["reasons"].pop(0)
            body["status"], body["recompute_pending"] = "invalidated", True
            body["epoch"] += 1
            body["reasons"].append(deepcopy(reason))
            entry["changed"] = True
            queue.append((body["target"], reason, True))

        for notice in notices:
            for reference in [*notice["before"], *notice["after"]]:
                queue.append((reference, notice, False))
            for reference in notice["after"]:
                if reference["record_type"] != "observation":
                    continue
                observation = validate_record(_current(tx, scope, reference))
                source = source_key(observation["body"]["source_identity"]["namespace"])
                for registration in tx.watchers(query_watch(scope, source), limit=MAX_DEPENDENCIES):
                    current = read_registration(tx, pin(registration))
                    for query in current["value"]["value"]["manifest"]["queries"]:
                        if pin(observation) not in query["seen"] and match_observation(observation, query["specification"]) is not False:
                            mark(pin(current), notice)
        current_fence = _lookup(tx, scope_fence_ref(scope))
        fence_pin = None if current_fence is None else pin(current_fence)
        for key in due_time_watch_keys(scope, now, fence_pin):
            for registration in tx.watchers(key, limit=MAX_DEPENDENCIES):
                body = read_registration(tx, pin(registration))["value"]["value"]
                due = [condition for condition in body["manifest"]["time_conditions"] if compare_times(now, condition["next_check_at"]) >= 0 or (condition["expires_at"]["state"] == "known" and compare_times(now, condition["expires_at"]) >= 0)]
                if due:
                    identity = canonical_digest({"target": body["target"], "conditions": due}, "matter.dependency-due.v1")
                    mark(pin(registration), {"id": identity, "cause": "temporal_transition", "receipt": tx.receipt_ref, "before": [], "after": []})
        while queue:
            reference, reason, logical = queue.popleft()
            visit = (_identity(reference), reason["id"], logical)
            if visit in visited:
                continue
            visited.add(visit)
            if len(visited) > MAX_DEPENDENCIES * 4:
                _fail(code="E_BUDGET_EXHAUSTED")
            for registration in tx.watchers(object_watch(reference), limit=MAX_DEPENDENCIES):
                entry = record(pin(registration))
                if _affected(entry["body"], reference, reason, logical=logical):
                    mark(pin(registration), reason)
        for identity in sorted(staged):
            entry = staged[identity]
            if not entry["changed"]:
                continue
            body, original = entry["body"], entry["record"]
            tx.put_projection(entity_ref(original), domain("dependency-registration", body),
                              watch_keys=watch_keys(body["manifest"], body["target"], body["status"]))
            target = body["target"]
            if target["record_type"] == PROJECTION_TYPE and target["namespace"] == "matter.assessments":
                lane = tx.get(entity_ref(target))
                value = _value("assessment-current", lane["value"])
                if value["status"] == "current" and matches_target(lane, target):
                    value.update(status="invalidated", invalidation={"cause": "dependency_change", "receipt": tx.receipt_ref,
                                 "reasons": [item["id"] for item in body["reasons"]]})
                    tx.put_projection(entity_ref(lane), domain("assessment-current", value), watch_keys=lane["watch_keys"])


def matches_target(record, reference):
    return pin(record) == reference
