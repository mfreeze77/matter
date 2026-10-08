"""Synthetic host authority and explicit registry commands for MAT-008 tests.

The bootstrap storage handler represents trusted host setup, not an authority
inferred from source content. Candidate registries are explicit publications,
not a claim of automatic discovery or semantic ranking.
"""

from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest

from matter.associations import AssociationPolicy, AssociationService
from matter.canonical import source_digest
from matter.matters import MatterService
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from integration.helpers import create_command, domain_value, record_input
from matter_helpers import identity_key, identity_policy, matter_command
from observation_helpers import known_time, observation_command
from occurrence_helpers import coverage


SCOPE = "synthetic:associations"
ACTOR = {"scope_id": SCOPE, "namespace": "example:host", "id": "reviewer"}
RULE = {"namespace": "example:matching", "id": "declared-exact-keys", "version": "1.0",
        "digest": source_digest(b"Synthetic declared exact key matching v1")}
RELATION = {"namespace": "example:relations", "id": "attachment", "version": "1.0",
            "digest": source_digest(b"Synthetic attachment relation v1")}
SOURCE = {"namespace": "example:catalog", "id": "host-registry", "version": "1.0",
          "digest": source_digest(b"Synthetic bounded candidate registry v1")}
PAYLOAD = b"Synthetic report concerning an unassigned continuing subject.\n"
MATCH_KEY = {"namespace": "example:catalog-key", "value": "reported-subject"}


def as_pin(value):
    return pin(value) if "body" in value or "value" in value else deepcopy(value)


def bootstrap_authority(storage):
    """Trusted generic host transaction creates its admitted authority receipt."""
    command = create_command("host-bootstrap", "host-bootstrap-record", scope_id=SCOPE)
    def handler(tx):
        authority = record_input("receipt", "host-grant", scope_id=SCOPE)
        authority["namespace"] = "example:host"
        authority["provenance"]["origin"] = "host"
        authority["body"].update(stage="authority", operation_id="host-bootstrap",
                                  outcome="example:granted", evidence=[],
                                  details=domain_value({"synthetic": "trusted host admission"}))
        tx.insert(authority)
        record = tx.insert(tx.command["body"]["matter"])
        return tx.success("created", {"matter": pin(record)})
    result = storage.execute(command, handler)
    if result["status"] != "success":
        raise AssertionError(result)
    return storage.get({"scope_id": SCOPE, "namespace": "example:host", "record_type": "receipt", "id": "host-grant"})


def policy_for(authority, *, allow_semantic=False, allow_correction=False,
               actors=None, authorities=None, relations=None):
    return AssociationPolicy(SCOPE, actors=actors if actors is not None else [ACTOR],
        authorities=authorities if authorities is not None else [pin(authority)],
        matching_rules=[RULE], relations=relations if relations is not None else [RELATION],
        allow_semantic=allow_semantic, allow_correction=allow_correction)


def envelope(command_id, operation, body, authority):
    return {"schema_version": "1.0", "operation": operation, "command_id": command_id,
            "idempotency_key": f"key:{command_id}", "scope_id": SCOPE,
            "actor": deepcopy(ACTOR), "authority": entity_ref(authority),
            "expected_revisions": [], "body": deepcopy(body)}


def query_for(subject, *, mode="exact_keys", keys=None):
    return {"source": deepcopy(SOURCE), "subject": entity_ref(subject), "candidate_type": "matter",
            "mode": mode, "matching_rule": deepcopy(RULE),
            "selector": domain_value({"catalog": "synthetic host-published candidates"}),
            "keys": deepcopy(keys if keys is not None else ([] if mode == "semantic" else [MATCH_KEY]))}


def entry(candidate, source, *, keys=None):
    return {"candidate": as_pin(candidate), "keys": deepcopy(keys if keys is not None else [MATCH_KEY]),
            "basis": [as_pin(source)]}


def publish_command(command_id, authority, query, entries, source, *, previous=None, source_coverage=None):
    return envelope(command_id, "publish_association_candidates", {
        "query": query, "entries": entries,
        "coverage": source_coverage if source_coverage is not None else coverage(),
        "evidence": [as_pin(source)], "as_of": known_time(),
        "previous": as_pin(previous) if previous is not None else None,
    }, authority)


def proposal_command(command_id, authority, candidate_set, query, entries, source, *, evaluation=None):
    candidates = [{"candidate": item["candidate"], "basis": item["basis"]} for item in entries]
    body = {"subject": as_pin(source), "candidates": candidates, "matching_rule": query["matching_rule"],
            "evidence": [as_pin(source)], "assessed_as_of": known_time(), "candidate_set": as_pin(candidate_set)}
    if evaluation is not None:
        body["evaluation"] = deepcopy(evaluation)
    return envelope(command_id, "propose_association", body, authority)


def acceptance_command(command_id, authority, proposal, candidate_set, candidates, policy,
                       *, relation=None, capability="attach"):
    return envelope(command_id, "accept_association", {
        "proposal": as_pin(proposal), "candidates": [as_pin(item) for item in candidates],
        "candidate_set": as_pin(candidate_set), "acceptance_policy": policy.reference,
        "relation": relation if relation is not None else RELATION, "capability": capability,
    }, authority)


def decision_command(command_id, authority, subject, target, policy, *, decision="reject",
                     previous=None, relation=None, capability="attach"):
    return envelope(command_id, "decide_association", {
        "subject": as_pin(subject), "target": as_pin(target),
        "relation": relation if relation is not None else RELATION, "capability": capability,
        "decision": decision, "previous": as_pin(previous) if previous is not None else None,
        "reason": "Synthetic host decision with explicit bounded authority.",
        "as_of": known_time(), "acceptance_policy": policy.reference,
    }, authority)


def semantic_evaluation(selected, *, outcome="matched", score="0.999999"):
    return {"producer": deepcopy(RULE), "outcome": outcome,
            "selected": [as_pin(item) for item in selected],
            "uncertainty": domain_value({"confidence": score}),
            "qualification": {"status": "not_required", "reason": "Synthetic host fixture, no provider qualification claim."},
            "reason": "Synthetic externally supplied proposal; confidence is not authority.",
            "missing_evidence": []}


class AssociationTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.database = self.directory / "associations.sqlite"
        self.storage = SQLiteStore(self.database, scope_id=SCOPE)
        self.addCleanup(self.storage.close)
        self.authority = bootstrap_authority(self.storage)
        self.policy = policy_for(self.authority)
        self.service = AssociationService(self.storage, policy=self.policy)
        self.matters = MatterService(self.storage, identity_policy=identity_policy())
        self.payloads = FilePayloadStore(self.directory / "payloads", scope_id=SCOPE)
        self.ingestor = ObservationIngestor(self.storage, self.payloads)
        self.subject = self.observe("subject")
        self.query = query_for(self.subject)

    def observe(self, identity, *, availability=None):
        command = observation_command(f"observe-{identity}", identity, payload=PAYLOAD,
                                      scope_id=SCOPE, event_id=identity)
        if availability is not None:
            command["body"]["observation"]["body"]["content"]["availability"].update(
                status=availability, reason="Synthetic required key evidence is inaccessible.")
        result = self.ingestor.ingest(self.ingestor.prepare(command), payload=PAYLOAD if availability is None else None)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(result["body"]["observation"])

    def matter(self, identity):
        command = matter_command(f"matter-{identity}", matter_id=identity, keys=[identity_key(identity)], scope_id=SCOPE)
        result = self.matters.create(self.matters.prepare(command))
        self.assertEqual(result.get("outcome"), "created", result)
        return self.storage.get(result["body"]["matter"])

    def publish(self, candidates, *, command_id="publish", query=None, source=None, previous=None,
                source_coverage=None, entries=None):
        source = source or self.subject
        query = query or self.query
        entries = entries if entries is not None else [entry(item, source) for item in candidates]
        command = publish_command(command_id, self.authority, query, entries, source,
                                  previous=previous, source_coverage=source_coverage)
        prepared = self.service.prepare(command)
        result = self.service.publish_candidates(prepared)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(result["body"]["candidate_set"]), entries, prepared, result

    def propose(self, candidate_set, entries, *, command_id="propose", query=None, source=None,
                evaluation=None, service=None):
        service = service or self.service
        command = proposal_command(command_id, self.authority, candidate_set, query or self.query,
                                   entries, source or self.subject, evaluation=evaluation)
        prepared = service.prepare(command)
        result = service.propose(prepared)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(result["body"]["proposal"]), prepared, result

    def accept_command(self, proposal, candidate_set, candidates, *, command_id="accept", service=None,
                       policy=None, relation=None, capability="attach"):
        service = service or self.service
        command = acceptance_command(command_id, self.authority, proposal, candidate_set, candidates,
                                     policy or self.policy, relation=relation, capability=capability)
        return service.prepare(command)

    def decide(self, target, *, command_id="decide", decision="reject", previous=None,
               relation=None, capability="attach", service=None, policy=None):
        service = service or self.service
        command = decision_command(command_id, self.authority, self.subject, target, policy or self.policy,
                                   decision=decision, previous=previous, relation=relation, capability=capability)
        prepared = service.prepare(command)
        result = service.decide(prepared)
        self.assertEqual(result["status"], "success", result)
        return prepared, result

    def assert_failure(self, result, code):
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], code, result)
        self.assertNotIn("outcome", result)

    def assert_refused(self, prepare, execute, command, code):
        """Read-only preparation may refuse; commit refusals must be typed."""
        try:
            prepared = prepare(command)
        except StorageError as error:
            self.assertEqual(error.code, code)
            return
        result = execute(prepared)
        self.assert_failure(result, code)

    def record_counts(self):
        with sqlite3.connect(self.database) as connection:
            return dict(connection.execute(
                "SELECT record_type,count(*) FROM heads WHERE scope_id=? GROUP BY record_type", (SCOPE,),
            ).fetchall())
