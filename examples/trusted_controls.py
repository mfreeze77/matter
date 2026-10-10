"""Portable MAT-011 example: trusted controls and an actual guarded matter API.

All records are synthetic. Authentication is represented by explicit host
setup, not inferred from the text or provenance fields of an observation.
"""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from matter.authority import AuthorityPolicy
from matter.canonical import source_digest
from matter.controls import ControlService, GuardedStorage, control_effect
from matter.identity_keys import ExactIdentityPolicy
from matter.matters import MatterService
from matter.storage import SQLiteStore, StorageError, entity_ref, pin


SCOPE = "synthetic:control-example"
ACTOR = {"scope_id": SCOPE, "namespace": "example", "id": "host"}
AUTHORITY = {"scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "grant"}
PRODUCER = {"namespace": "example", "id": "control-example", "version": "1.0",
            "digest": source_digest(b"Synthetic trusted-control example v1")}
NOW = {"state": "known", "value": "2026-10-10T12:00:00Z", "precision": "second"}
IDENTITY = ExactIdentityPolicy(key_namespaces=["example:subject"])


def record(kind, identity, body):
    return {"schema_version": "1.0", "record_type": kind, "scope_id": SCOPE, "namespace": "example", "id": identity,
            "provenance": {"origin": "host", "producer": PRODUCER, "recorded_at": NOW, "parents": []}, "body": body}


def envelope(identity, operation, body):
    return {"schema_version": "1.0", "operation": operation, "command_id": identity, "idempotency_key": identity,
            "scope_id": SCOPE, "actor": ACTOR, "authority": AUTHORITY, "expected_revisions": [], "body": body}


def creation(identity):
    return envelope("create-" + identity, "create_matter", {"identity_policy": IDENTITY.reference,
        "matter": record("matter", identity, {"domain_kind": "example:subject", "title": identity,
            "identity_keys": [{"namespace": "example:subject", "value": identity}]})})


def control(identity, targets, *, action="cancel", supersedes=(), capabilities=()):
    kind = {"cancel": "cancellation", "resume": "instruction", "deny": "permission"}[action]
    value = record("control", identity, {"control_kind": kind, "actor": ACTOR, "authority": AUTHORITY,
        "scope": {"scope_id": SCOPE, "targets": [entity_ref(item) for item in targets]}, "control_epoch": 0,
        "effective_from": NOW, "effective_until": {"state": "unknown", "reason": "not_applicable",
            "detail": "Until explicit host supersession."},
        "effect": control_effect(action, "Synthetic accepted host input.", capabilities=capabilities)})
    if supersedes:
        value["supersedes"] = list(supersedes)
    return envelope(identity, "record_control", {"control": value})


def main():
    with TemporaryDirectory() as directory:
        database = Path(directory) / "matter.sqlite"
        with SQLiteStore(database, scope_id=SCOPE) as store:
            # Privileged host bootstrap, outside the observed-source path.
            def bootstrap(tx):
                tx.insert(record("receipt", "grant", {"stage": "authority", "operation_id": "create-setup",
                    "recorded_at": NOW, "outcome": "example:host_grant", "evidence": [],
                    "details": {"schema": PRODUCER, "value": "Explicit synthetic host admission."}}))
                setup = tx.insert(tx.command["body"]["matter"])
                return tx.success("created", {"matter": pin(setup)})
            assert store.execute(creation("setup"), bootstrap)["status"] == "success"
            policy = AuthorityPolicy(SCOPE, actors=[ACTOR], authorities=[pin(store.get(AUTHORITY))],
                capabilities=["read", "write", "delivery"], control_kinds=["cancellation", "instruction", "permission"])
            callbacks = []
            controls = ControlService(store, policy=policy, clock=lambda: NOW,
                                      hooks={"cancel-old-workers": lambda item: callbacks.append(item["id"])})
            ordinary = MatterService(store, identity_policy=IDENTITY)
            subjects = []
            for identity in ("A", "B"):
                result = ordinary.create(ordinary.prepare(creation(identity)))
                subjects.append(store.get(result["body"]["matter"]))
            a, b = subjects
            guarded = GuardedStorage(store, controls=controls)
            matters = MatterService(guarded, identity_policy=IDENTITY)
            def prepare_edit(identity, subject):
                prepared = matters.prepare(envelope(identity, "update_matter_metadata",
                    {"matter": pin(subject), "metadata": {"title": "Prepared work for " + subject["id"]}}))
                token = guarded.capture(prepared)  # BEFORE evaluating/computing the work.
                return guarded.prepare(prepared, token=token), token
            edit_a, token_a = prepare_edit("edit-A", a)
            edit_b, token_b = prepare_edit("edit-B", b)
            stop = controls.prepare(control("stop-A", [a]))
            stopped = controls.apply(stop)
            assert callbacks == []  # Durable stop never waits on a callback.
            assert controls.run_hooks(stopped["body"]["control"], attempt_id="initial")[0]["status"] == "succeeded"
            assert callbacks == ["stop-A"]
            assert matters.update_metadata(edit_a)["status"] == "failure"
            accepted_b = matters.update_metadata(edit_b)
            assert accepted_b["outcome"] == "updated"
            release = controls.prepare(control("resume-A", [a], action="resume", supersedes=[stopped["body"]["control"]]))
            assert controls.apply(release)["outcome"] == "applied"
            try:
                controls.check(token_a)
                raise AssertionError("Old computed work must remain stale after resume.")
            except StorageError as error:
                assert error.code == "E_DEPENDENCY_STALE"
            assert controls.apply(stop) == stopped  # Historical replay does not stop A again.
            controls.capture(actor=ACTOR, authority=AUTHORITY, capability="write", targets=[entity_ref(a)])
            denied = controls.prepare(control("deny-B-history", [b], action="deny", capabilities=["read"]))
            assert controls.apply(denied)["outcome"] == "applied"
            assert matters.update_metadata(edit_b)["error"]["code"] == "E_AUTHORITY_REQUIRED"
            assert store.command_receipt(edit_b["idempotency_key"])["result"] == accepted_b
        with SQLiteStore(database, scope_id=SCOPE) as reopened:
            restarted = ControlService(reopened, policy=policy, clock=lambda: NOW)
            assert restarted.apply(stop) == stopped
            restarted.capture(actor=ACTOR, authority=AUTHORITY, capability="write", targets=[entity_ref(a)])
        print("Trusted controls example passed: scoped stop, guarded commits, explicit release, stale-work fencing, hook receipts, replay, and restart.")


if __name__ == "__main__":
    main()
