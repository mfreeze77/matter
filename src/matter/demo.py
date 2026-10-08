"""Small, synthetic lifecycle walkthrough; not the production Matter engine.

Fixtures supply trusted host classifications and associations. This module does
not infer meaning, call a model, resolve identities, or contact an application.
Its purpose is to make a few required continuity and delivery behaviors runnable.
"""

from dataclasses import dataclass, field
from datetime import datetime
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .jsonio import canonical, read


def _schema(value: dict[str, Any] | None = None) -> dict[str, Any]:
    """Use checkout contracts; the CLI passes its selected checkout explicitly."""
    schema = value if value is not None else read(
        Path(__file__).resolve().parents[2] / "schemas/walkthrough.schema.json"
    )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"invalid walkthrough schema: {exc.message}") from exc
    return schema


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    try:
        canonical(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: not finite JSON data") from exc
    problem = next(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), None)
    if problem is not None:
        raise ValueError(f"invalid {label} {list(problem.absolute_path)}: {problem.message}")


def validate_fixture(fixture: dict[str, Any], *, schema: dict[str, Any] | None = None) -> None:
    """Validate the entire fixture before executing its first event."""
    contract = _schema(schema)
    _validate(fixture, contract, "walkthrough")
    previous = None
    seen = {}
    for event in fixture["events"]:
        at = instant(event["at"])
        if previous is not None and at < previous:
            raise ValueError("input availability order moved backwards")
        if event["scope_id"] != fixture["scope_id"]:
            raise ValueError("cross-scope event rejected")
        if event["kind"] == "observation" and instant(event["effective_at"]) > at:
            raise ValueError("walkthrough observations cannot report future occurrences")
        identity = (event["source"], event["id"])
        content = canonical({k: v for k, v in event.items() if k != "at"})
        if identity in seen and seen[identity] != content:
            raise ValueError("source event identity reused with different content")
        seen[identity] = content
        previous = at


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamps must include an offset")
    return result


@dataclass
class MatterState:
    identity: str
    context: str
    condition: str
    latest_effective: datetime
    status: str = "open"
    observations: int = 0
    occurrences: set[str] = field(default_factory=set)
    episode: int = 1
    change: int = 0
    resolved_at: datetime | None = None
    pending: dict[str, tuple[int, int, str, str]] = field(default_factory=dict)
    delivered: dict[str, set[tuple[int, int, str, str]]] = field(default_factory=dict)

    def token(self) -> tuple[int, int, str, str]:
        return self.episode, self.change, self.context, self.condition


class Walkthrough:
    def __init__(self, scope: str, audience: str, *, schema: dict[str, Any] | None = None):
        if not isinstance(scope, str) or not scope or not isinstance(audience, str) or not audience:
            raise ValueError("scope and audience must be nonempty strings")
        contract = _schema(schema)
        self._event_schema = {"$schema": contract["$schema"], "$defs": contract["$defs"],
                              "$ref": "#/$defs/event"}
        self.scope = scope
        self.audience = audience
        self.matters: dict[str, MatterState] = {}
        self.seen: dict[tuple[str, str], str] = {}
        self.clock: datetime | None = None
        self.outcomes: list[str] = []
        self.delivered_updates = 0
        self.controls: list[str] = []
        self.paused = False

    def apply(self, event: dict[str, Any]) -> str:
        _validate(event, self._event_schema, "walkthrough event")
        staged = deepcopy(self)
        outcome = staged._apply(event)
        self.__dict__.update(staged.__dict__)
        return outcome

    def _apply(self, event: dict[str, Any]) -> str:
        at = instant(event["at"])
        if self.clock is not None and at < self.clock:
            raise ValueError("input availability order moved backwards")
        if event["scope_id"] != self.scope:
            raise ValueError("cross-scope event rejected")
        if event["kind"] not in {"observation", "context_change", "delivery_boundary", "control"}:
            raise ValueError("unknown event kind")
        effective = instant(event["effective_at"]) if event["kind"] == "observation" else None
        if effective is not None and effective > at:
            raise ValueError("walkthrough observations cannot report future occurrences")
        identity = (event["source"], event["id"])
        content = canonical({k: v for k, v in event.items() if k != "at"})
        if identity in self.seen:
            if self.seen[identity] != content:
                raise ValueError("source event identity reused with different content")
            self.clock = at
            self.outcomes.append("duplicate")
            return "duplicate"
        self.clock = at
        self.seen[identity] = content
        if event["kind"] == "control":
            self.controls.append(event["id"])
            if event["instruction"] == "stop":
                self.paused = True
                for state in self.matters.values():
                    state.pending.clear()
            outcome = "forwarded_control"
        else:
            key = event["matter_key"]
            audience = event.get("audience", self.audience)
            state = self.matters.get(key)
            if event["kind"] == "delivery_boundary":
                outcome = self._deliver(state, audience)
            elif event["kind"] == "context_change":
                if state is None:
                    raise ValueError("context change requires an existing matter")
                if state.context == event["context_revision"]:
                    outcome = "unchanged_context"
                else:
                    state.context = event["context_revision"]
                    state.pending.clear()
                    outcome = "invalidated"
            else:
                assert effective is not None
                if state is None:
                    if event["classification"] == "resolution":
                        outcome = "resolution_unmatched"
                    elif event["classification"] == "material" and not event["host_qualified"]:
                        # Retain the source receipt, but do not invent an accepted
                        # lifecycle/occurrence from unqualified material evidence.
                        outcome = "material_unqualified"
                    else:
                        matter_id = hashlib.sha256(canonical([self.scope, key]).encode()).hexdigest()[:24]
                        state = MatterState(matter_id, event["context_revision"], event["condition_id"], effective)
                        self.matters[key] = state
                        outcome = self._observe(state, event, effective, audience)
                else:
                    outcome = self._observe(state, event, effective, audience)
        self.outcomes.append(outcome)
        return outcome

    def _observe(self, state: MatterState, event: dict[str, Any], effective: datetime, audience: str) -> str:
        state.observations += 1
        classification = event["classification"]
        if event["context_revision"] != state.context or event["condition_id"] != state.condition:
            return "resolution_unmatched" if classification == "resolution" else "outside_current_condition"
        if classification == "resolution":
            if not event["host_qualified"]:
                return "resolution_unqualified"
            if effective < state.latest_effective:
                return "resolution_unmatched"
            if state.status == "resolved":
                return "already_resolved"
            state.status = "resolved"
            state.resolved_at = effective
            state.pending.clear()
            return "resolved"
        if classification not in {"routine", "material"}:
            raise ValueError("unknown observation classification")
        if classification == "material" and not event["host_qualified"]:
            # Observation receipt/count is distinct from an accepted recurrence.
            # In particular, this cannot advance the clock used to match recovery.
            return "material_unqualified"
        if state.resolved_at is not None and effective <= state.resolved_at:
            return "historical_observation"
        occurrence = event["occurrence_id"]
        correlated = occurrence in state.occurrences
        state.occurrences.add(occurrence)
        if state.status == "resolved":
            state.status = "open"
            state.episode += 1
        state.latest_effective = max(state.latest_effective, effective)
        if classification == "material":
            state.change += 1
            if not self.paused:
                state.pending[audience] = state.token()
                return "eligible"
            return "recorded_while_paused"
        return "correlated_report" if correlated else "recorded"

    def _deliver(self, state: MatterState | None, audience: str) -> str:
        if state is None or self.paused:
            return "quiet"
        token = state.pending.pop(audience, None)
        if token is None:
            return "quiet"
        if state.status != "open" or token != state.token():
            return "withheld_stale"
        delivered = state.delivered.setdefault(audience, set())
        if token in delivered:
            return "quiet"
        delivered.add(token)
        self.delivered_updates += 1
        return "delivered"

    def result(self) -> dict[str, Any]:
        return {
            "outcomes": list(self.outcomes),
            "delivered_updates": self.delivered_updates,
            "forwarded_controls": list(self.controls),
            "matters": {key: {"status": state.status, "observations": state.observations,
                              "distinct_occurrences": len(state.occurrences), "episodes": state.episode,
                              "queued_updates": len(state.pending)} for key, state in sorted(self.matters.items())},
        }


def run_fixture(fixture: dict[str, Any], *, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = _schema(schema)
    validate_fixture(fixture, schema=contract)
    runner = Walkthrough(fixture["scope_id"], fixture["audience"], schema=contract)
    for event in fixture["events"]:
        runner.apply(event)
    return runner.result()
