"""Synthetic source, proposition and citation commands for MAT-007 checks."""

from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest

from matter.citations import Utf8LineLocatorAdapter, line_selector
from matter.claims import ClaimService
from matter.evidence_relations import EvidenceRelationService
from matter.matters import MatterService
from matter.observations import ObservationIngestor
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from integration.helpers import _in_scope, domain_value, fixture, record_input
from matter_helpers import identity_key, identity_policy, matter_command
from observation_helpers import observation_command


SCOPE = "synthetic:claims"
PASSAGE = (b"Funding is expected next year, subject to approval.\n"
           b"No allocation has been approved.\n")


def as_pin(value):
    return pin(value) if "body" in value else deepcopy(value)


def claim_command(command_id, identity, subject, source, *, value="funding discussion",
                  version="1.0", supersedes=(), components=None, predicate="example:funding"):
    command = _in_scope(fixture("commands/append_claim.json"), subject["scope_id"])
    command.update(command_id=command_id, idempotency_key=f"key:{command_id}", expected_revisions=[])
    claim = record_input("claim", identity, scope_id=subject["scope_id"])
    claim["body"].update(subject=entity_ref(subject), predicate=predicate,
                         value=domain_value(value), attribution=[as_pin(source)],
                         proposition_version=version)
    claim["body"]["components"] = deepcopy(components if components is not None else {
        "example:funding": domain_value("Funding is under discussion."),
        "example:timing": domain_value("Expected next year, conditional on approval."),
    })
    if supersedes:
        claim["supersedes"] = [as_pin(item) for item in supersedes]
    command["body"] = {"claim": claim}
    command["authority"] = deepcopy(subject["creation_receipt"])
    return command


def relation_command(command_id, identity, claim, source, *, relation="supports",
                     component="example:funding", status="accepted", exact=True,
                     quotation="Funding is expected next year", lines=(1, 1)):
    command = _in_scope(fixture("commands/relate_evidence.json"), claim["scope_id"])
    command.update(command_id=command_id, idempotency_key=f"key:{command_id}", expected_revisions=[])
    proposed = record_input("evidence_relation", identity, scope_id=claim["scope_id"])
    proposed["namespace"] = "example:relations"
    body = proposed["body"]
    body.update(claim=as_pin(claim), evidence=as_pin(source), relation=relation,
                target={"kind": "whole"} if component is None else {"kind": "component", "component": component})
    locator = deepcopy(source["body"]["content"]["locator"])
    if exact:
        locator.update(kind="selected_span", selector=line_selector(*lines))
    body["locator"] = locator
    if quotation is not None:
        body["quotation"] = quotation
    command["authority"] = deepcopy(claim["creation_receipt"])
    body["acceptance"] = {"status": status, "rationale": "Synthetic host-reviewed scoped relation."}
    if status != "proposed":
        body["acceptance"]["authority"] = deepcopy(command["authority"])
    command["body"] = {"relation": proposed}
    return command


def acceptance_command(command_id, relation, status, *, rationale="Synthetic contribution withdrawn."):
    command = _in_scope(fixture("commands/revise_evidence_acceptance.json"), relation["scope_id"])
    command.update(command_id=command_id, idempotency_key=f"key:{command_id}", expected_revisions=[])
    command["authority"] = deepcopy(relation["creation_receipt"])
    acceptance = {"status": status, "rationale": rationale}
    if status != "proposed":
        acceptance["authority"] = deepcopy(command["authority"])
    command["body"] = {"relation": as_pin(relation), "acceptance": acceptance}
    return command


class ClaimTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.database = self.directory / "claims.sqlite"
        self.payload_directory = self.directory / "payloads"
        self.storage = SQLiteStore(self.database, scope_id=SCOPE)
        self.addCleanup(self.storage.close)
        self.payloads = FilePayloadStore(self.payload_directory, scope_id=SCOPE)
        self.ingestor = ObservationIngestor(self.storage, self.payloads)
        self.matters = MatterService(self.storage, identity_policy=identity_policy())
        self.claims = ClaimService(self.storage)
        self.adapter = Utf8LineLocatorAdapter(self.payloads)
        self.relations = EvidenceRelationService(self.storage, locator_adapter=self.adapter)
        self.subject = self.make_matter("subject-a")
        self.source = self.observe("source-a")

    def make_matter(self, identity):
        command = matter_command(f"create-{identity}", matter_id=identity,
                                 keys=[identity_key(identity)], scope_id=SCOPE)
        result = self.matters.create(self.matters.prepare(command))
        self.assertEqual(result["outcome"], "created")
        return self.storage.get(result["body"]["matter"])

    def observe(self, identity, payload=PASSAGE, *, availability=None):
        command = observation_command(f"observe-{identity}", identity, payload=payload,
                                      scope_id=SCOPE, event_id=identity)
        if availability is not None:
            content = command["body"]["observation"]["body"]["content"]
            content["availability"].update(status=availability, reason="Synthetic source access restriction.")
        prepared = self.ingestor.prepare(command)
        result = self.ingestor.ingest(prepared, payload=payload if availability is None else None)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(result["body"]["observation"])

    def append(self, identity="claim-a", **kwargs):
        command = claim_command(f"append-{identity}", identity, self.subject, self.source, **kwargs)
        prepared = self.claims.prepare(command)
        result = self.claims.append(prepared)
        self.assertEqual(result.get("outcome"), "appended", result)
        return self.storage.get(result["body"]["claim"]), prepared, result

    def relate(self, claim, identity="relation-a", *, source=None, **kwargs):
        command = relation_command(f"relate-{identity}", identity, claim, source or self.source, **kwargs)
        prepared = self.relations.prepare(command)
        result = self.relations.relate(prepared)
        self.assertEqual(result.get("outcome"), "appended", result)
        return self.storage.get(result["body"]["relation"]), prepared, result

    def validation(self, relation):
        receipt = self.storage.get(relation["body"]["locator_validation"])
        return receipt["body"]["details"]["value"]

    def assert_failure(self, result, code):
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], code, result)
        self.assertNotIn("outcome", result)

    def assert_missing(self, reference):
        with self.assertRaises(StorageError) as error:
            self.storage.get(reference)
        self.assertEqual(error.exception.code, "E_NOT_FOUND")

    def record_counts(self):
        with sqlite3.connect(self.database) as connection:
            return dict(connection.execute(
                "SELECT record_type,count(*) FROM heads WHERE scope_id=? GROUP BY record_type", (SCOPE,),
            ).fetchall())
