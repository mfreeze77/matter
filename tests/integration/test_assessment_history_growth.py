"""MAT-091 bounded immutable history; full input stays in its original journal."""
import json
from copy import deepcopy
import unittest

from matter.assessments import PUBLICATION_EXTENSION
from matter.canonical import canonical_bytes, source_digest
from matter.storage import pin
from matter.contracts import ContractError
from integration.helpers import create_command
from integration import test_assessment_commit as fixtures
from integration.test_monitoring_handoff import MonitoringFixture


class AssessmentHistoryGrowth(unittest.TestCase):
    def test_historical_proof_cannot_extend_the_original_access_context(self):
        h = MonitoringFixture(self)
        request = h.f.request(evidence=[pin(h.claim), pin(h.occurrence)])
        request["body"].update(purpose=h.a.purpose_ref, audience=h.a.audience_ref,
            control_epoch=h.token["control_epoch"])
        prepared = h.f.service.prepare(request, token=h.token, plan=h.f.plan,
            extra_dependencies=h.references, access_context=h.access_context)
        data = prepared.value
        data["historical_records"] = [h.f.storage.get(h.contexts["purpose"])]
        self.assertEqual(h.f.service._preparation(data), data)
        foreign = h.f.storage.get(h.other_contexts["purpose"])
        attacked = deepcopy(data)
        attacked["historical_records"] = [foreign]
        attacked["records"].append(foreign)
        attacked["reads"] = sorted([*attacked["reads"], pin(foreign)], key=canonical_bytes)
        with self.assertRaises(ContractError) as denied:
            h.f.service._preparation(attacked)
        self.assertEqual(denied.exception.code, "E_AUTHORITY_REQUIRED")

    def test_legacy_inline_publication_still_commits_replays_and_reconstructs(self):
        f = fixtures.AssessmentCommitTests("runTest")
        f.setUp()
        self.addCleanup(f.doCleanups)
        prepared = f.prepare()
        command = f.command(prepared)
        command["body"]["assessment"]["extensions"] = {PUBLICATION_EXTENSION: command["extensions"][PUBLICATION_EXTENSION]}
        result = f.service.commit(command)
        self.assertEqual(result.get("outcome"), "committed", result)
        self.assertEqual(f.service.commit(command), result)
        stored = f.storage.get(result["body"]["assessment"])
        self.assertEqual(source_digest(f.service.input_artifact(command["idempotency_key"])), stored["body"]["input_artifact"]["digest"])
        self.assertEqual(f.service.current(f.subject, profile=f.profile.reference, purpose=f.purpose, audience=f.audience), stored)

    def test_historical_transaction_read_requires_current_head_fence(self):
        f = fixtures.AssessmentCommitTests("runTest")
        f.setUp()
        self.addCleanup(f.doCleanups)
        original = f.subject
        f.rename_subject()
        def read(tx):
            old = tx.get_historical(pin(original))
            self.assertEqual(old, original)
            return tx.success("created", {"matter": pin(old)})
        command = create_command("historical-proof", "unused", scope_id=f.storage.scope_id)
        refused = f.storage.execute(command, read)
        self.assertEqual(refused["error"]["code"], "E_REVISION_CONFLICT")
        command.update(command_id="historical-fenced", idempotency_key="historical-fenced",
                       expected_revisions=[pin(f.subject)])
        self.assertEqual(f.storage.execute(command, read)["status"], "success")
        command.update(command_id="historical-stale", idempotency_key="historical-stale")
        f.rename_subject("A newer head")
        self.assertEqual(f.storage.execute(command, read)["error"]["code"], "E_REVISION_CONFLICT")

    def test_ten_assessments_with_prior_records_keep_exact_inputs_within_budget(self):
        f = fixtures.AssessmentCommitTests("runTest")
        f.setUp()
        self.addCleanup(f.doCleanups)
        history, sizes = [], []
        for step in range(10):
            request = f.request()
            request["body"]["budget"]["max_bytes"] = 2 * 1024 * 1024
            prepared = f.prepare(request=request, extra=[pin(r) for r in history])
            sizes.append(len(canonical_bytes(prepared.value)))
            print(json.dumps({"step": step + 1, "prepared_bytes": sizes[-1]}), flush=True)
            self.assertLessEqual(sizes[-1], request["body"]["budget"]["max_bytes"])
            command = f.command(prepared)
            result = f.service.commit(command)
            self.assertEqual(result.get("outcome"), "committed", (step, sizes, result))
            stored = f.storage.get(result["body"]["assessment"])
            artifact = f.service.input_artifact(command["idempotency_key"])
            self.assertEqual(source_digest(artifact), stored["body"]["input_artifact"]["digest"])
            self.assertEqual(f.service.commit(command), result)
            history.append(stored)
        self.assertEqual(len(history), 10)
        self.assertTrue(all(PUBLICATION_EXTENSION not in r.get("extensions", {}) for r in history))
        self.assertLess(sizes[-1], sizes[0] + 200000)
