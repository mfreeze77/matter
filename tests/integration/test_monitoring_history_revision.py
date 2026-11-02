"""MAT-091 actual native captures with an intervening approved purpose edit."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import json
import unittest

from matter.access import HostAccessPolicy, is_source_access_target, source_access_provenance
from matter.canonical import canonical_bytes, canonical_digest
from matter.contexts import ContextDefinition, _binding
from matter.contracts import ContractError
from matter.attention import RESULT_EXTENSION
from matter.queries import QueryService, _ReadView
from matter.storage import pin, entity_ref
from integration.test_monitoring_handoff import MonitoringFixture, HOST_FIELDS
from rule_helpers import component


class MonitoringHistoryRevision(unittest.TestCase):
    def refresh_access(self, h, roots):
        h.references = list({canonical_bytes(r): r for r in roots}.values())
        with h.f.storage.snapshot() as view:
            grants = source_access_provenance(view, h.references)
        h.access.policy = HostAccessPolicy(scope_id=h.f.storage.scope_id,
            audiences=[h.a.audience_ref], providers=h.access.policy.value["providers"],
            grants=[{"reference": r, "audiences": [h.a.audience_ref], "providers": [h.provider]} for r in grants])
        targets = list({canonical_bytes(entity_ref(r)): entity_ref(r) for r in grants if is_source_access_target(r)}.values())
        h.token = h.f.controls.capture(actor=h.f.actor, authority=entity_ref(h.f.authority), capability="assessment", targets=targets)
        with h.f.storage.snapshot() as view:
            h.access_context = h.access.capture(view, token=h.token, audience=h.a.audience_ref,
                provider=h.provider, references=h.references)

    def refresh_packet(self, h):
        h.packet = h.prepare_source_packet(h.access, h.access_context)
        source = h.req["evidence"]["sources"][0]
        selected = h.packet.state["evidence"][0]
        source.update(reference=pin(h.source), available_at=h.source["body"]["available_at"],
            occurred_at=h.source["body"]["occurred_at"], published_at=h.source["body"]["source_published_at"],
            artifact_sha256=h.source["body"]["content"]["digest"], selected_text_sha256=selected["text_digest"],
            locator=selected["locator"], origin=h.source["provenance"]["origin"], parents=h.source["provenance"]["parents"])
        h.req["evidence"].update(packet_digest=h.packet.digest, occurrences=[pin(h.occurrence)])
        h.state = replace(h.state, contexts=deepcopy(h.contexts), source_finding=pin(h.claim),
            projection={k: deepcopy(h.req[k]) for k in HOST_FIELDS})
        h.host = replace(h.host, access_context=h.access_context)

    def record_capture(self, h, parameters):
        admitted = h.admit()
        result = admitted.project(**parameters)
        self.assertNotEqual(result["treatment"], "quiet")
        def sink(**args):
            args["require_current"]()
            self.assertEqual(args["channels"], ["in_app"])
            return h.observe(parameters)
        return admitted.handoff(result, capture=sink)

    def test_capture_revision_then_new_same_subject_capture_preserves_history(self):
        h = MonitoringFixture(self)
        first = h.publish_attention()
        first_journal = h.f.storage.command_receipt("attention-key-" + str(h.a.sequence))
        self.assertEqual(h.admit().project(**first)["treatment"], "digest")
        material = self.record_capture(h, first)
        baseline = deepcopy(h.req["baseline"])
        h.f.now = {**h.f.now, "value": (datetime.fromisoformat(h.f.now["value"].replace("Z", "+00:00"))
            + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")}
        h.req["evidence"]["knowledge_cut"] = deepcopy(h.f.now)
        h.req["context_selection"]["effective_at"] = deepcopy(h.f.now)
        old_context = h.contexts["purpose"]
        with h.f.storage.snapshot() as view:
            definition = _binding(view, h.f.storage.scope_id, old_context)["definition"]
        definition["semantic_version"] = "2.0"
        definition["content"]["objectives"].append(component("recovery-objective"))
        revised, _, _ = h.a.contexts.publish(ContextDefinition(definition), previous=old_context)
        h.contexts["purpose"] = pin(revised)
        h.a.context_refs["purpose"] = pin(revised)
        with h.f.storage.snapshot() as view:
            binding = _binding(view, h.f.storage.scope_id, pin(revised))
        h.a.purpose_ref = h.f.purpose = binding["reference"]
        h.req["context_components"]["purpose"] = binding["reference"]
        h.req["intent"].update(revision_id="intent-a-v2", revision_number=2,
            content_hash=canonical_digest(definition["content"], "synthetic.approved-purpose.v1"))
        h.req["intent"]["purpose"] += " Also track recovery."
        h.req.update(request_id="revision-second", idempotency_key="revision-second")

        # An explicitly authored new source development, on the same subject.
        previous_claim = h.claim
        h.source, h.occurrence = h.e.event("revision-second-source", at=h.f.now, available_at=h.f.now)
        h.claim = h.e.claim("revision-second-claim", h.e.condition_a, "recovered", h.source,
                            supersedes=[pin(previous_claim)])
        h.f.source = h.source
        roots = [r for r in h.references if entity_ref(r) != entity_ref(old_context)]
        roots += [pin(revised), binding["version"], binding["control"],
                  pin(h.source), pin(h.claim), pin(h.occurrence)]
        self.refresh_access(h, roots)
        self.assertEqual(h.access_context.value["schema_version"], "1.1")
        self.assertIn(old_context, h.access_context.value["dependencies"])
        self.assertIn(pin(revised), h.access_context.value["dependencies"])
        saved_policy = h.access.policy
        class DeniedRootReadCanary:
            def __init__(self, view):
                self.view = view
            def __getattr__(self, name):
                return getattr(self.view, name)
            def get(self, ref):
                if entity_ref(ref) == entity_ref(revised):
                    raise AssertionError("An ungranted root was read before denial.")
                return self.view.get(ref)
        for forbidden in (old_context, pin(revised)):
            policy = saved_policy.value
            h.access.policy = HostAccessPolicy(scope_id=h.f.storage.scope_id,
                audiences=policy["audiences"], providers=policy["providers"],
                grants=[g for g in policy["grants"] if g["reference"] != forbidden])
            with h.f.storage.snapshot() as view, self.assertRaises(ContractError) as denied:
                guarded = DeniedRootReadCanary(view) if forbidden == pin(revised) else view
                h.access.capture(guarded, token=h.token, audience=h.a.audience_ref,
                    provider=h.provider, references=h.references)
            self.assertEqual(denied.exception.code, "E_AUTHORITY_REQUIRED")
        h.access.policy = saved_policy
        with h.f.storage.snapshot() as view, self.assertRaises(ContractError) as stale:
            h.access.capture(view, token=h.token, audience=h.a.audience_ref,
                provider=h.provider, references=[baseline["assessment_reference"], old_context])
        self.assertEqual(stale.exception.code, "E_DEPENDENCY_STALE")
        self.refresh_packet(h)
        self.assertEqual(h.admit().audience_packet().state["monitoring"]["observed_baseline"], material["material"])
        self.assertEqual(h.req["baseline"], baseline)
        with h.f.storage.snapshot() as view:
            minimal_history = h.access.capture(view, token=h.token, audience=h.a.audience_ref,
                provider=h.provider, references=[baseline["assessment_reference"]])
        self.assertEqual(minimal_history.value["schema_version"], "1.1")
        h.renew_allocation()
        execution = h.execute()
        self.assertTrue(execution["result"].primitive_valid)
        self.assertEqual(len(h.calls), 1)
        h.execute()
        self.assertEqual(len(h.calls), 1)
        second = h.publish_attention(status="supported")
        second_journal = h.f.storage.command_receipt("attention-key-" + str(h.a.sequence))
        self.assertNotEqual(h.admit().project(**second)["treatment"], "quiet")
        self.record_capture(h, second)
        self.assertEqual(h.req["baseline"]["intent_revision_id"], "intent-a-v2")
        self.assertNotEqual(h.req["baseline"]["receipt"], baseline["receipt"])

        no_future_grant_policy = h.access.policy
        with h.f.storage.snapshot() as view:
            no_future_grant_context = h.access.capture(view, token=h.token, audience=h.a.audience_ref,
                provider=h.provider, references=[baseline["assessment_reference"]])
        future_ref = {**pin(revised), "revision": revised["revision"] + 1}
        policy = no_future_grant_policy.value
        h.access.policy = HostAccessPolicy(scope_id=h.f.storage.scope_id,
            audiences=policy["audiences"], providers=policy["providers"],
            grants=[*policy["grants"], {"reference": future_ref, "audiences": [h.a.audience_ref], "providers": [h.provider]}])
        future_grant_policy = h.access.policy
        with h.f.storage.snapshot() as view:
            future_grant_context = h.access.capture(view, token=h.token, audience=h.a.audience_ref,
                provider=h.provider, references=[baseline["assessment_reference"]])
        h.access.policy = no_future_grant_policy

        # A later revision cannot rewrite either the 1.0 or 1.1 historical
        # selection, even when the latter retained an implicit head anchor.
        definition["semantic_version"] = "3.0"
        third, _, _ = h.a.contexts.publish(ContextDefinition(definition), previous=pin(revised))
        for journal, arguments in ((first_journal, first), (second_journal, second)):
            decision_ref = journal["result"]["extensions"][RESULT_EXTENSION]["value"]["decision"]
            read_token = h.f.controls.capture(actor=h.f.actor, authority=entity_ref(h.f.authority),
                capability="read", targets=arguments["read_token"]["targets"])
            historical = h.a.service.read(read_token, decision_ref, access_context=arguments["access_context"])
            self.assertEqual(pin(historical), decision_ref)
            self.assertEqual(h.a.service.evaluate(journal["command"]), journal["result"])
        with h.f.storage.snapshot() as view:
            h.access.require_history(view, minimal_history, references=[baseline["assessment_reference"]])
            query = QueryService(h.f.storage, controls=h.f.controls, access=h.access)
            reader = _ReadView(view, query, h.f.actor, entity_ref(h.f.authority), h.f.now, h.access_context)
            self.assertEqual(pin(reader.get_historical(old_context)), old_context)
            self.assertEqual(pin(reader.get_historical(pin(revised))), pin(revised))
            early = {"state": "known", "value": "2020-01-01T00:00:00Z", "precision": "second"}
            early_reader = _ReadView(view, query, h.f.actor, entity_ref(h.f.authority), early, h.access_context)
            with self.assertRaises(ContractError) as not_known:
                early_reader.get_historical(old_context)
            self.assertEqual(not_known.exception.code, "E_EVIDENCE_UNAVAILABLE")
        for policy, context in ((no_future_grant_policy, no_future_grant_context), (future_grant_policy, future_grant_context)):
            h.access.policy = policy
            with h.f.storage.snapshot() as view, self.assertRaises(ContractError) as changed:
                h.access.require_current(view, context)
            self.assertEqual(changed.exception.code, "E_DEPENDENCY_STALE")
        h.access.policy = no_future_grant_policy
        with self.assertRaises(ContractError) as changed:
            h.admit()  # The unrefreshed current context remains stale.
        self.assertEqual(changed.exception.code, "E_DEPENDENCY_STALE")

    def test_ten_successive_developments_capture_with_bounded_prepared_inputs(self):
        h = MonitoringFixture(self)
        sizes, receipts = [], []
        for step in range(10):
            if step:
                h.f.now = {**h.f.now, "value": (datetime.fromisoformat(h.f.now["value"].replace("Z", "+00:00"))
                    + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")}
                h.req["evidence"]["knowledge_cut"] = deepcopy(h.f.now)
                h.req["context_selection"]["effective_at"] = deepcopy(h.f.now)
                previous = h.claim
                h.source, h.occurrence = h.e.event("series-source-" + str(step), at=h.f.now, available_at=h.f.now)
                h.claim = h.e.claim("series-claim-" + str(step), h.e.condition_a,
                    "recovered" if step % 2 else "present", h.source, supersedes=[pin(previous)])
                h.f.source = h.source
                h.req.update(request_id="series-" + str(step), idempotency_key="series-" + str(step))
                self.refresh_access(h, [*h.references, pin(h.source), pin(h.claim), pin(h.occurrence)])
                self.refresh_packet(h)
            request = h.f.request(evidence=[pin(h.claim), pin(h.occurrence)])
            request["body"].update(purpose=h.a.purpose_ref, audience=h.a.audience_ref, control_epoch=h.token["control_epoch"])
            request["body"]["budget"].update(max_bytes=2 * 1024 * 1024, max_elapsed_ms=30000)
            # The host rule does not consume prior assessments as current
            # semantic truth. Its baseline/history context stays separate.
            current_refs = [r for r in h.references if r["record_type"] != "assessment"]
            with h.f.storage.snapshot() as view:
                current_access = h.access.capture(view, token=h.token, audience=h.a.audience_ref,
                    provider=h.provider, references=current_refs)
            prepared = h.f.service.prepare(request, token=h.token, plan=h.f.plan,
                extra_dependencies=current_refs, access_context=current_access)
            sizes.append(len(canonical_bytes(prepared.value)))
            print(json.dumps({"capture": step + 1, "prepared_bytes": sizes[-1]}), flush=True)
            command = h.f.command(prepared, interpretations=[{"node": "evidence", "claim": pin(h.claim),
                "labels": {"example:positive": "supported"},
                "evidence_standard": h.f.profile.component_references["evidence"]}])
            committed = h.f.service.commit(command)
            self.assertEqual(committed.get("outcome"), "committed", committed)
            assessment = h.f.storage.get(committed["body"]["assessment"])
            h.e.remember(assessment)
            for ref in assessment["body"]["judgments"]:
                h.e.remember(h.f.storage.get(ref))
            parameters = h.evaluate_attention(assessment)
            self.record_capture(h, parameters)
            receipts.append(h.req["baseline"]["receipt"])
        self.assertEqual(len({canonical_bytes(r) for r in receipts}), 10)
        self.assertEqual(len(sizes), 10)
        self.assertLess(max(sizes), 2 * 1024 * 1024)
