"""Synthetic, explicitly host-admitted controls and deterministic clock."""

from copy import deepcopy

from matter.authority import AuthorityPolicy, CAPABILITIES, CONTROL_KINDS
from matter.canonical import canonical_bytes
from matter.controls import ControlService, GuardedStorage, control_effect
from matter.storage import entity_ref, pin

from association_helpers import ACTOR, SCOPE, AssociationTestCase, envelope
from integration.helpers import record_input


def instant(value="2026-10-10T12:00:00Z"):
    return {"state": "known", "value": value, "precision": "second"}


class Clock:
    def __init__(self):
        self.value = instant()

    def __call__(self):
        return deepcopy(self.value)


def authority_policy(authority, *, capabilities=CAPABILITIES, kinds=CONTROL_KINDS, targets=None):
    return AuthorityPolicy(SCOPE, actors=[ACTOR], authorities=[pin(authority)],
                           capabilities=capabilities, control_kinds=kinds, targets=targets)


def control_command(identity, authority, *, targets=(), action="cancel", kind=None,
                    capabilities=(), supersedes=(), until=None, now=None):
    kind = kind or {"cancel": "cancellation", "resume": "instruction", "deny": "permission",
                    "allow": "permission", "invalidate": "correction", "disposition": "decision"}[action]
    control = record_input("control", identity, scope_id=SCOPE)
    control["namespace"] = "example:controls"
    control["body"] = {"control_kind": kind, "actor": ACTOR, "authority": entity_ref(authority),
        "scope": {"scope_id": SCOPE, "targets": sorted([entity_ref(target) for target in targets], key=canonical_bytes)},
        "control_epoch": 0, "effective_from": now or instant(),
        "effective_until": until or {"state": "unknown", "reason": "not_applicable", "detail": "Until explicit host supersession."},
        "effect": control_effect(action, "Synthetic host decision.", capabilities=capabilities)}
    control["provenance"]["parents"] = [pin(authority)]
    control["provenance"]["recorded_at"] = now or instant()
    if supersedes:
        control["supersedes"] = list(supersedes)
    return envelope(identity, "record_control", {"control": control}, authority)


class ControlTestCase(AssociationTestCase):
    def setUp(self):
        super().setUp()
        self.clock = Clock()
        self.host_policy = authority_policy(self.authority)
        self.controls = ControlService(self.storage, policy=self.host_policy, clock=self.clock)
        self.guarded = GuardedStorage(self.storage, controls=self.controls)

    def apply_control(self, identity, **options):
        command = control_command(identity, self.authority, **options)
        prepared = self.controls.prepare(command)
        result = self.controls.apply(prepared)
        self.assertEqual(result["status"], "success", result)
        return prepared, result

    def token(self, targets, *, capability="read", controls=None):
        return (controls or self.controls).capture(actor=ACTOR, authority=entity_ref(self.authority),
                                                   capability=capability, targets=[entity_ref(t) for t in targets])
