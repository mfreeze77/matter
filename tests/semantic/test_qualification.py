"""MAT-031 synthetic reviewed-method gates over real SQLite executions."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from matter._rule_values import domain
from matter.controls import ControlService
from matter.dependencies import registration_ref
from matter.invalidation import InvalidationHook
from matter.semantic.contracts import RawExecution
from matter.semantic.qualification import (SemanticCertificate, SemanticQualificationService,
    qualification_identity, certificate_ref)
from matter.storage import SQLiteStore, StorageError, entity_ref, pin
from semantic import test_receipts as receipt_fixture
from integration.helpers import create_command, record_input, domain_value, _in_scope
from rule_helpers import component, EARLY, LATE

CASES = json.loads((Path(__file__).parents[1] / "fixtures/semantic/certificates.json").read_text())

MEASURE = {"name": "probability", "unit": "probability"}
DOMAIN = component("eligible-synthetic-domain")


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = receipt_fixture.DurableExecutionTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f, self.stage, self.receipts = self.fixture.f, self.fixture.stage, self.fixture.service
        self.request = self.fixture.request
        self.sequence = 0
        self.reviewer = component("review-authority")
        self.service = SemanticQualificationService(self.f.storage, controls=self.f.controls, receipts=self.receipts,
            reviewers=[self.reviewer], clock=lambda: self.f.now)

    def next(self):
        self.sequence += 1
        return str(self.sequence)

    def record(self, identity, details, *, producer=None, origin="host"):
        command = create_command("qualification-bootstrap-" + identity, "qualification-subject-" + identity,
                                 scope_id=self.f.storage.scope_id)
        record = record_input("receipt", identity, scope_id=self.f.storage.scope_id)
        record["provenance"].update(origin=origin, producer=producer or self.reviewer, recorded_at=self.f.now, parents=[])
        record["body"].update(stage="evaluation", operation_id=command["command_id"], outcome="synthetic:reviewed",
            recorded_at=self.f.now, evidence=[], details=details)
        def bootstrap(tx):
            tx.insert(record)
            matter = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(matter)})
        result = self.f.storage.execute(command, bootstrap)
        self.assertEqual(result["status"], "success", result)
        return self.f.storage.get(entity_ref(record))

    def certificate(self, *, status="passed", identity=None, changes=None, report_changes=None):
        key = self.next()
        identity = deepcopy(identity or qualification_identity(self.request, "support", domain_scope=DOMAIN, measure=MEASURE))
        if changes:
            identity.update(changes)
        artifact = self.record("artifact-" + key, domain_value({"synthetic": True, "external_manifest": "urn:synthetic:heldout:" + key}))
        counts = deepcopy(CASES["support"])
        regions = deepcopy(CASES["regions"])
        report = {"schema_version": "1.0", "identity": identity, "regions": regions, "status": status,
            "labels": "independent", "support": {"positive": deepcopy(counts), "negative": deepcopy(counts)},
            "interval_method": component("synthetic-review-interval"), "artifacts": [pin(artifact)],
            "reason": CASES["review_reason"]}
        if report_changes:
            report.update(report_changes)
        evaluation = self.record("review-" + key, domain("semantic-qualification-evaluation", report))
        cert = SemanticCertificate({"schema_version": "1.0", "namespace": "synthetic_qualification", "id": "certificate-" + key,
            "semantic_version": "1.0", "description": "Synthetic reviewed method.", "identity": identity, "regions": regions,
            "evaluation": pin(evaluation), "valid_from": EARLY, "valid_until": LATE})
        command = self.service.prepare_install(cert, command_id="install-" + key, idempotency_key="install-" + key,
            actor=self.f.actor, authority=entity_ref(self.f.authority))
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        return cert

    def token(self, cert=None, *, capability="assessment"):
        targets = list(self.stage.targets)
        if cert is not None:
            targets.append(certificate_ref(self.f.storage.scope_id, cert))
        return self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
                                      capability=capability, targets=targets)

    def run_execution(self, *, probability=None, model="synthetic-fixed", invalid=False, identity=None):
        if probability is None:
            self.stage.invalid = invalid
            return self.fixture.run_attempt(identity or "trial-" + self.next())
        outer = self.stage
        class Adapter:
            capabilities = outer.spy.capabilities
            def execute(inner, batch):
                outer.calls.append(batch.value)
                answers = [{"id": item["id"], "primitive": "proposition_probability", "probability": probability}
                           for item in batch.value["questions"]]
                return RawExecution(json.dumps({"answers": answers, "resolved_model": model}).encode())
        return self.receipts.run(self.request, executor=Adapter(), token=self.stage.token,
            logical_request_id="logical", attempt_id=identity or "trial-" + self.next(), allocation=self.stage.reservation)

    def inspect(self, execution, cert=None, *, domain_scope=DOMAIN, measure=MEASURE, token=None):
        token = token or self.token(cert)
        with self.f.storage.snapshot() as view:
            return self.service.inspect(view, execution, question_id="support", certificate=None if cert is None else cert.reference,
                domain_scope=domain_scope, measure=measure, token=token)

    def admit(self, execution, cert):
        key = self.next()
        command = {"schema_version": "1.0", "operation": "admit_semantic_result", "command_id": "admit-" + key,
            "idempotency_key": "admit-" + key, "scope_id": self.f.storage.scope_id, "actor": self.f.actor,
            "authority": entity_ref(self.f.authority), "expected_revisions": [], "body": {"execution": execution,
                "question_id": "support", "certificate": cert.reference, "domain": DOMAIN}}
        prepared = self.service.prepare_admission(command, token=self.token(cert), measure=MEASURE)
        result = self.service.admit(prepared)
        self.assertEqual(result["status"], "success", result)
        return prepared, result

    def test_failed_heldout_threshold_never_qualifies_confident_actual_receipt(self):
        cert = self.certificate(status="failed")
        result = self.run_execution(probability="0.999999999999999999")
        self.assertEqual(result["status"], "completed", result)
        admission = self.inspect(result["execution"], cert)
        self.assertEqual((admission.value["status"], admission.value["reason"]), ("unqualified", "held_out_failed"))
        self.assertFalse(admission.eligible)
        self.assertFalse(self.receipts.replay(result["execution"]).value["admission"]["consequential_use"])
        _, recorded = self.admit(result["execution"], cert)
        self.assertEqual(recorded["body"]["qualification"], "unqualified")

    def test_exact_identity_matrix_and_expiry_have_specific_reasons(self):
        execution = self.run_execution()["execution"]
        actual = qualification_identity(self.request, "support", domain_scope=DOMAIN, measure=MEASURE)
        alternatives = {"resolved_model": "different-model", "requested_model": "different-request", "model_resolution": component("different-resolution"),
            "provider": "different-provider", "transport": "different-transport", "adapter_version": "2.0", "mode": "recorded_replay",
            "question": component("different-wording-or-options"), "criteria_digest": "f" * 64,
            "renderer": {"id": "different-renderer", "version": "2.0"}, "packet_profile": component("different-profile"),
            "preparation": component("different-preparation"), "domain": component("different-domain"),
            "measure": {"name": "confidence", "unit": "confidence"},
            "precision": {**actual["precision"], "probability_quantum": "0.01"}}
        for field, value in alternatives.items():
            with self.subTest(field=field):
                cert = self.certificate(changes={field: value})
                admission = self.inspect(execution, cert)
                self.assertEqual(admission.value["reason"], field + "_mismatch")
                self.assertFalse(admission.eligible)
        cert = self.certificate()
        self.f.now = deepcopy(LATE)
        self.assertEqual(self.inspect(execution, cert).value["reason"], "certificate_expired")
        self.assertIsNone(self.receipts.lookup(self.request, token=self.stage.token,
            qualify=self.service.classifier(question_id="support", certificate=cert.reference, domain_scope=DOMAIN,
                measure=MEASURE, token=self.token(cert))))
        self.assertEqual(len(self.stage.calls), 1)

    def test_missing_model_and_certificate_remain_shadow_and_half_abstains(self):
        execution = self.run_execution(probability="0.5")["execution"]
        cert = self.certificate()
        decision = self.inspect(execution, cert)
        self.assertEqual((decision.value["status"], decision.value["method_qualification"], decision.value["measure_value"]),
                         ("abstained", "qualified", "0.5"))
        self.assertFalse(decision.eligible)
        self.assertEqual(self.inspect(execution).value["reason"], "certificate_missing")
        self.assertFalse(self.receipts.replay(execution).value["admission"]["consequential_use"])

    def test_negative_and_positive_regions_use_exact_separate_values(self):
        cert = self.certificate()
        execution = self.run_execution()["execution"]
        decision = self.inspect(execution, cert)
        self.assertEqual((decision.value["status"], decision.value["decision"], decision.value["measure_value"]),
                         ("qualified", "negative", "0.1234567890123456789"))
        token = self.token(cert)
        with self.f.storage.snapshot() as view:
            preflight = self.service.preflight(view, self.request, question_id="support", certificate=cert.reference,
                domain_scope=DOMAIN, measure=MEASURE, token=token)
        self.assertEqual(preflight["status"], "applicable_pending_execution")
        self.assertFalse(preflight["host_authority_granted"])
        callback = self.service.stage_classifier(certificates={"support": cert.reference}, domain_scope=DOMAIN,
            measure=MEASURE, token=token)
        view_result = self.receipts.view_result({"status": "completed", "execution": execution}, self.fixture.batch)
        self.assertEqual(callback(question={"id": "support", "specification": self.stage.specs["support"].reference},
            stage_input=self.fixture.material, batch=self.fixture.batch.value, batch_result=view_result.value,
            as_of=self.f.now)["status"], "qualified")

    def test_revocation_invalidates_actual_registered_assessment_and_keeps_history(self):
        # Install the real generic hook, preserving ordinary current host policy.
        old = self.f.storage
        old.close()
        hook = InvalidationHook(clock=lambda: self.f.now)
        self.f.storage = SQLiteStore(self.f.database, scope_id=old.scope_id, transaction_hook=hook)
        self.addCleanup(self.f.storage.close)
        self.f.controls = ControlService(self.f.storage, policy=self.f.controls.policy, clock=lambda: self.f.now)
        hook.controls = self.f.controls
        self.f.service = self.f.make_service()
        # Rebind actual030/020 services to the same new trusted store.
        self.stage.f = self.f
        self.stage.reserve(calls=4)
        from matter.semantic.receipts import ExecutionReceiptStore
        self.receipts = ExecutionReceiptStore(self.f.storage, payloads=self.f.payloads, controls=self.f.controls,
            questions=self.stage.questions, clock=lambda: self.f.now, budgets=self.stage.budgets)
        self.fixture.service = self.receipts
        self.service = SemanticQualificationService(self.f.storage, controls=self.f.controls, receipts=self.receipts,
            reviewers=[self.reviewer], clock=lambda: self.f.now)
        cert = self.certificate()
        execution = self.run_execution()["execution"]
        original = self.receipts.read(execution)
        command, admitted = self.admit(execution, cert)
        admission_pin = admitted["body"]["admission"]
        recorded = self.f.storage.get(admission_pin)
        self.assertEqual(recorded["value"]["value"]["decision"], "negative")
        prepared, published_command, assessment = self.f.publish(extra=[admission_pin])
        self.assertEqual(self.f.service.current(pin(self.f.subject), profile=self.f.profile.reference,
            purpose=self.f.purpose, audience=self.f.audience)["id"], assessment["id"])
        evaluation_before = self.f.storage.get(cert.value["evaluation"])
        self.assertIsNotNone(self.receipts.lookup(self.request, token=self.stage.token, qualify=self.service.classifier(
            question_id="support", certificate=cert.reference, domain_scope=DOMAIN, measure=MEASURE, token=self.token(cert))))
        key = self.next()
        revoke = self.service.prepare_revoke(cert, command_id="revoke-" + key, idempotency_key="revoke-" + key,
            actor=self.f.actor, authority=entity_ref(self.f.authority), reason="Synthetic host revocation.")
        result = self.service.commit(revoke)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self.f.storage.get(registration_ref(admission_pin))["value"]["value"]["status"], "invalidated")
        self.assertEqual(self.f.storage.get(registration_ref(pin(assessment)))["value"]["value"]["status"], "invalidated")
        with self.assertRaises(StorageError):
            self.f.service.current(pin(self.f.subject), profile=self.f.profile.reference, purpose=self.f.purpose, audience=self.f.audience)
        self.assertEqual(self.inspect(execution, cert).value["reason"], "certificate_revoked")
        self.assertEqual(self.f.storage.get(admission_pin), recorded)
        self.assertEqual(self.receipts.read(execution), original)
        self.assertEqual(self.f.storage.get(cert.value["evaluation"]), evaluation_before)
        self.assertEqual(self.service.history(admission_pin, read_token=self.token(cert, capability="read")), recorded)
        self.assertIsNone(self.receipts.lookup(self.request, token=self.stage.token, qualify=self.service.classifier(
            question_id="support", certificate=cert.reference, domain_scope=DOMAIN, measure=MEASURE, token=self.token(cert))))
        self.assertEqual(len(self.stage.calls), 1)

    def test_unresolved_observed_model_remains_shadow(self):
        cert = self.certificate()
        unresolved = self.run_execution(probability="0.99", model=None)
        self.assertEqual(unresolved["status"], "completed", unresolved)
        self.assertEqual(self.inspect(unresolved["execution"], cert).value["reason"], "model_unresolved")

    def test_failed_whole_batch_cannot_admit_valid_partial_head(self):
        cert = self.certificate()
        invalid = self.run_execution(invalid=True)
        self.assertEqual(invalid["status"], "completed", invalid)
        self.assertEqual(self.inspect(invalid["execution"], cert).value["reason"], "whole_answer_set_invalid")

    def test_teacher_labels_and_insufficient_support_never_admit(self):
        good = self.run_execution()["execution"]
        teacher = self.certificate(report_changes={"labels": "teacher_only"})
        self.assertEqual(self.inspect(good, teacher).value["reason"], "independent_labels_required")
        low = deepcopy(CASES["support"])
        low.update(episodes=2, accepted=2, minimum_episodes=10)
        sparse = self.certificate(report_changes={"support": {"positive": low, "negative": deepcopy(CASES["support"])}})
        self.assertEqual(self.inspect(good, sparse).value["reason"], "positive_support_insufficient")

    def test_reused_receipt_is_bound_to_original_trial_and_stage_gate_rejects_undecided(self):
        cert = self.certificate()
        original = self.run_execution(probability="0.5")
        reused = self.fixture.run_attempt("reuse-observation")
        self.assertEqual(reused["status"], "reused")
        self.assertEqual(self.inspect(reused["execution"], cert).value["execution"], original["execution"])
        stage_view = self.receipts.view_result(reused, self.fixture.batch).value
        callback = self.service.stage_classifier(certificates={"support": cert.reference}, domain_scope=DOMAIN,
            measure=MEASURE, token=self.token(cert))
        question = {"id": "support", "specification": self.stage.specs["support"].reference}
        self.assertEqual(callback(question=question, stage_input=self.fixture.material, batch=self.fixture.batch.value,
            batch_result=stage_view, as_of=self.f.now)["status"], "unknown")
        forged = deepcopy(stage_view)
        forged["diagnostics"][0]["answer"]["probability"] = "0.99"
        with self.assertRaises(StorageError):
            callback(question=question, stage_input=self.fixture.material, batch=self.fixture.batch.value,
                batch_result=forged, as_of=self.f.now)
        self.assertEqual(len(self.stage.calls), 1)

    def test_prepared_admission_refuses_revocation_race_and_original_token_shrink(self):
        cert = self.certificate()
        execution = self.run_execution()["execution"]
        prepared, result = self.admit(execution, cert)
        self.assertEqual(result["body"]["qualification"], "qualified")
        # Original actor and complete public target coverage are not replaceable
        # by a narrower fresh token or a caller-authored qualified status.
        bad = deepcopy(prepared)
        bad.update(command_id="fresh-bad", idempotency_key="fresh-bad")
        extension = bad["extensions"]["matter:semantic-qualification-request"]["value"]
        extension["token"] = domain("control-token", self.stage.token)
        refused = self.service.admit(bad)
        self.assertEqual(refused["status"], "failure")
        self.assertEqual(refused["error"]["code"], "E_AUTHORITY_REQUIRED")
        # A separately prepared recomputation is fenced when actual revocation
        # commits first, with its then-qualified history still readable.
        fresh = deepcopy(prepared)
        fresh.update(command_id="race-admission", idempotency_key="race-admission", expected_revisions=[])
        fresh.pop("extensions")
        pending = self.service.prepare_admission(fresh, token=self.token(cert), measure=MEASURE)
        revoke = self.service.prepare_revoke(cert, command_id="race-revoke", idempotency_key="race-revoke",
            actor=self.f.actor, authority=entity_ref(self.f.authority), reason="Synthetic race.")
        self.assertEqual(self.service.commit(revoke)["status"], "success")
        refused = self.service.admit(pending)
        self.assertEqual(refused["status"], "failure")
        self.assertEqual(refused["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.f.storage.get(result["body"]["admission"])["value"]["value"]["status"], "qualified")

    def test_actual_read_denial_blocks_current_history_and_replay(self):
        from control_helpers import control_command
        cert = self.certificate()
        execution = self.run_execution()["execution"]
        prepared, result = self.admit(execution, cert)
        read_token = self.token(cert, capability="read")
        self.assertEqual(self.service.current(result["body"]["admission"], read_token=read_token)["value"]["value"]["status"], "qualified")
        deny = _in_scope(control_command("deny-qualification-read", self.f.authority, targets=[self.f.source],
            action="deny", capabilities=["read"], now=self.f.now), self.f.storage.scope_id)
        deny["actor"] = self.f.actor
        deny["body"]["control"]["body"]["actor"] = self.f.actor
        self.assertEqual(self.f.controls.apply(self.f.controls.prepare(deny))["status"], "success")
        for read in (lambda: self.service.current(result["body"]["admission"], read_token=read_token),
                     lambda: self.service.history(result["body"]["admission"], read_token=read_token),
                     lambda: self.service.admit(prepared)):
            try:
                value = read()
            except Exception as error:
                self.assertEqual(error.code, "E_AUTHORITY_REQUIRED")
            else:
                self.assertEqual(value["status"], "failure", value)
                self.assertEqual(value["error"]["code"], "E_AUTHORITY_REQUIRED")
        self.assertEqual(len(self.stage.calls), 1)

    def test_conflicting_qualified_heads_remain_separate_and_raw_evidence_unchanged(self):
        support = self.certificate()
        opposing_identity = qualification_identity(self.request, "contradiction", domain_scope=DOMAIN, measure=MEASURE)
        contradiction = self.certificate(identity=opposing_identity)
        execution = self.run_execution(probability="0.99")["execution"]
        original = self.receipts.read(execution)
        left = self.inspect(execution, support)
        token = self.token(contradiction)
        with self.f.storage.snapshot() as view:
            right = self.service.inspect(view, execution, question_id="contradiction", certificate=contradiction.reference,
                domain_scope=DOMAIN, measure=MEASURE, token=token)
        self.assertTrue(left.eligible)
        self.assertTrue(right.eligible)
        self.assertEqual((left.value["decision"], right.value["decision"]), ("positive", "positive"))
        self.assertNotEqual(left.value["question_id"], right.value["question_id"])
        self.assertEqual(self.receipts.read(execution), original)
        self.assertFalse(original["body"]["details"]["value"]["result"]["admission"]["consequential_use"])


if __name__ == "__main__":
    unittest.main()
