"""MAT-082 synthetic component conformance over actual core/receipt services.

The host ORM projection and provider answers are authored fixtures. These tests
are not the StateCivics two-saved-objective receiving run or JEV qualification.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from matter.access import AccessService, HostAccessPolicy, _public
from matter.attention import AttentionService, AttentionPolicy
from matter.canonical import canonical_bytes, canonical_digest
from matter.contexts import ContextDefinition, _binding
from matter.contracts import ContractError
from matter.semantic import Batch, Capabilities, RawExecution
from matter.semantic.packets import PacketProfile, prepare_packet
from matter.semantic.questions import QuestionRegistry
from matter.semantic.receipts import ExecutionReceiptStore
from matter.semantic.rendering import render_question
from matter.statecivics_monitoring import (AdmittedMonitoring, HostMonitoringState,
    MonitoringHost, monitoring_questions, monitoring_refusal, validate_handoff)
from matter.storage import StorageError, entity_ref, pin
from matter.rules import RuleRegistry
from matter.time import compare_times

from integration import test_audience_attention as attention_fixtures
from semantic import test_stages as stage_fixtures
from rule_helpers import component


ROOT = Path(__file__).resolve().parents[2]
HOST_FIELDS = ("mode", "context_selection", "host_binding", "intent", "context_components", "evidence", "baseline",
               "dispositions", "capture_binding", "evaluation")


class MonitoringFixture:
    def __init__(self, test):
        self.a = attention_fixtures.AudienceAttentionTests("runTest")
        self.a.setUp()
        test.addCleanup(self.a.doCleanups)
        self.f, self.e = self.a.f, self.a.episode
        # A declared synthetic clock after the legacy fixture's wall-stamped
        # creation receipts, never a claim about real historical availability.
        self.f.now = {"state": "known", "value": "2050-01-01T00:00:00Z", "precision": "second"}
        self.f.rule_instance = self.f.rule(self.f.binding_instance,
            change=lambda value: value["resource_limits"].update(max_elapsed_ms=30000))
        self.f.rules = RuleRegistry([self.f.rule_instance])
        self.e.install_profile(self.e.definition)
        policy = self.a.policy.value
        policy["profile"] = self.f.profile.reference
        self.a.policy = AttentionPolicy(policy)
        h = self.a.contexts
        self.contexts = {}
        for kind in ("scope", "responsibility", "preference"):
            native_kind = "objective" if kind == "scope" else kind
            definition = h.definition(native_kind, "monitoring-" + kind,
                content=({"preferred_treatment": "digest", "channels": ["statecivics:in_app"],
                    "interruption_budget": {"schema": self.a.policy.reference, "value": {"limit": 0}}}
                    if kind == "preference" else None))
            record, _, _ = h.publish(definition)
            self.contexts[kind] = pin(record)
            self.e.remember(record)
        self.contexts.update(purpose=pin(self.a.purpose), audience=pin(self.a.audience))
        self.a.context_refs["responsibilities"] = [self.contexts["responsibility"]]
        self.a.context_refs["preferences"] = [self.contexts["preference"]]
        self.other_contexts = {kind: self.contexts[kind] for kind in ("responsibility", "preference")}
        for kind in ("scope", "purpose", "audience"):
            native = "objective" if kind == "scope" else kind
            content = {"statement": "Find open school technology procurements.", "constraints": []} if kind == "scope" else None
            record, _, _ = h.publish(h.definition(native, "procurement-" + kind, content=content))
            self.other_contexts[kind] = pin(record)
            self.e.remember(record)
        # Reuse actual intake, grouping and source claims; no pre-access assessment.
        self.source, self.occurrence = self.e.event("shared-monitoring-source", at=self.f.now, available_at=self.f.now)
        future_end = {"state": "known", "value": "2051-01-01T00:00:00Z", "precision": "second"}
        from integration import test_lifecycle_episodes as lifecycle_fixtures
        with patch.object(lifecycle_fixtures, "FUTURE", future_end):
            self.claim = self.e.claim("shared-monitoring-finding", self.e.condition_a, "present", self.source, effective=self.f.now)
        self.shared = [pin(r) for r in (self.f.subject, self.f.source, self.claim, self.source, self.occurrence)]
        # The graph must consume the selected source, not its unrelated bootstrap source.
        self.f.source = self.source
        with self.f.storage.snapshot() as view:
            def dependencies(contexts):
                result = []
                for ref in contexts.values():
                    binding = _binding(view, self.f.storage.scope_id, ref)
                    result += [binding["context"], binding["version"], pin(view.get(binding["control"]))]
                return result
            ctx_dependencies = dependencies(self.contexts)
            other_dependencies = dependencies(self.other_contexts)
            self.other_audience = _binding(view, self.f.storage.scope_id, self.other_contexts["audience"])["reference"]
        self.references = self.shared + ctx_dependencies
        self.provider = component("monitoring-fixture-provider")
        grants = {}
        for refs, audience in ((self.references, self.a.audience_ref), (self.shared + other_dependencies, self.other_audience)):
            for ref in refs:
                if _public(ref):
                    item = grants.setdefault(canonical_bytes(ref), {"reference": ref, "audiences": [], "providers": [self.provider]})
                    if audience not in item["audiences"]:
                        item["audiences"].append(audience)
        self.access = AccessService(policy=HostAccessPolicy(scope_id=self.f.storage.scope_id,
            audiences=[self.a.audience_ref, self.other_audience], providers=[{"reference": self.provider, "provider": "synthetic", "transport": "fixture"}],
            grants=list(grants.values())), controls=self.f.controls, current_read=self.f.storage.snapshot)
        targets = list({canonical_bytes(entity_ref(r)): entity_ref(r) for r in self.references if _public(r)}.values())
        self.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
            capability="assessment", targets=targets)
        with self.f.storage.snapshot() as view:
            self.access_context = self.access.capture(view, token=self.token, audience=self.a.audience_ref,
                provider=self.provider, references=self.references)
            locator = self.source["body"]["content"]["locator"]
            profile = PacketProfile({"namespace": "synthetic", "id": "monitoring-source", "version": "1.0",
                "required_roles": [], "allowed_origins": ["source", "derived"], "locator_adapters": [self.f.adapter.reference],
                "max_sources": 16, "max_source_bytes": 65536, "max_packet_bytes": 65536})
            self.packet = prepare_packet(view, profile, payloads=self.f.payloads, scope_id=self.f.storage.scope_id,
                binding={"kind": "claim", "claim": pin(self.claim)}, as_of=self.f.now,
                evidence=[{"reference": pin(self.source), "roles": [], "locator": locator, "quotation": None,
                    "validation": self.f.adapter.validate(self.source, locator, checked_at=self.f.now)}],
                occurrences=[pin(self.occurrence)], coverage={"status": "complete", "snapshot": component("explicit-cohort")},
                access=self.access, access_context=self.access_context)
        self.specs = monitoring_questions()
        self.questions = QuestionRegistry(self.specs)
        self.calls, self.probability, self.on_execute = [], "0.99", None
        outer = self
        class RecordedProvider:
            capabilities = Capabilities({"provider": "synthetic", "transport": "fixture", "adapter_version": "1.0",
                "primitives": ["proposition_probability"], "modes": ["offline_fixture"], "max_questions": 16,
                "max_request_bytes": 65536, "max_response_bytes": 65536})
            def execute(self, batch):
                outer.calls.append(batch.value)
                if outer.on_execute is not None:
                    outer.on_execute()
                return RawExecution(canonical_bytes({"answers": [{"id": q["id"], "primitive": q["primitive"],
                    "probability": outer.probability} for q in batch.value["questions"]], "resolved_model": "synthetic-fixed"}))
        self.executor = RecordedProvider()
        self.stage = stage_fixtures.StageTests("runTest")
        self.stage.f, self.stage.sequence, self.stage.targets = self.f, 900, targets
        self.stage.token, self.stage.questions, self.stage.spy = self.token, self.questions, self.executor
        early = {"state": "known", "value": "2049-01-01T00:00:00Z", "precision": "second"}
        late = {"state": "known", "value": "2051-01-01T00:00:00Z", "precision": "second"}
        with patch.object(stage_fixtures, "EARLY", early), patch.object(stage_fixtures, "LATE", late):
            self.stage.reserve(calls=4, expires=late)
        self.receipts = ExecutionReceiptStore(self.f.storage, payloads=self.f.payloads, controls=self.f.controls,
            clock=lambda: deepcopy(self.f.now), questions=self.questions, access=self.access, budgets=self.stage.budgets)
        self.req = json.loads((ROOT / "tests/fixtures/civic/handoff/client-a-request.json").read_text())
        self.req["evaluation"].update(policy=self.a.policy.reference, provider=self.provider, model="synthetic-fixed",
            adapter=component("fixture-adapter"), questions=[s.reference for s in self.specs])
        self.req["intent"]["approval"]["approved_at"] = deepcopy(self.f.now)
        self.req["intent"]["active_from"] = deepcopy(self.f.now)
        self.req["context_selection"]["effective_at"] = deepcopy(self.f.now)
        self.req["context_components"] = {}
        with self.f.storage.snapshot() as view:
            for kind, ref in self.contexts.items():
                self.req["context_components"][kind] = _binding(view, self.f.storage.scope_id, ref)["reference"]
        selected = self.packet.state["evidence"][0]
        source = self.req["evidence"]["sources"][0]
        source.update(reference=pin(self.source), available_at=self.source["body"]["available_at"],
            occurred_at=self.source["body"]["occurred_at"], published_at=self.source["body"]["source_published_at"],
            artifact_sha256=self.source["body"]["content"]["digest"], selected_text_sha256=selected["text_digest"],
            locator=selected["locator"], origin=self.source["provenance"]["origin"], parents=self.source["provenance"]["parents"])
        self.req["evidence"].update(packet_digest=self.packet.digest, knowledge_cut=deepcopy(self.f.now),
            occurrences=[pin(self.occurrence)], coverage="complete" if self.packet.state["coverage"]["status"] == "complete" else "partial")
        self.req["budgets"].update(max_calls=4, timeout_seconds=20, wall_seconds=300)
        self.state = HostMonitoringState(projection={k: deepcopy(self.req[k]) for k in HOST_FIELDS},
            candidate=pin(self.f.subject), contexts=deepcopy(self.contexts), status="active", capture_exists=True,
            capture_authorized=True, capture_muted=False, budget_ceiling=deepcopy(self.req["budgets"]),
            reserved_cost_usd="0", source_finding=pin(self.claim))
        self.f.service.access = self.access
        self.a.service = AttentionService(self.f.storage, assessments=self.f.service, policies=[self.a.policy],
            controls=self.f.controls, clock=lambda: deepcopy(self.f.now), lifecycle=self.e.lifecycle, access=self.access)
        self.host = MonitoringHost(binding=deepcopy(self.req["host_binding"]), access=self.access,
            access_context=self.access_context, current_state=lambda identity: self.states.get(identity), clock=lambda: deepcopy(self.f.now), attention=self.a.service)

    @property
    def state(self):
        return self.states[self.active_intent]

    @state.setter
    def state(self, value):
        if not hasattr(self, "states"):
            self.states, self.active_intent = {}, "intent-a"
        self.states[self.active_intent] = value

    def activate_other(self):
        self.active_intent = "intent-b"
        self.contexts = self.other_contexts
        self.a.purpose = self.f.storage.get(self.contexts["purpose"])
        self.a.audience = self.f.storage.get(self.contexts["audience"])
        self.a.audience_ref = self.other_audience
        with self.f.storage.snapshot() as view:
            self.a.purpose_ref = _binding(view, self.f.storage.scope_id, self.contexts["purpose"])["reference"]
            refs = list(self.shared)
            for ref in self.contexts.values():
                bound = _binding(view, self.f.storage.scope_id, ref)
                refs += [bound["context"], bound["version"], pin(view.get(bound["control"]))]
        self.references = refs
        self.a.context_refs = {"purpose": self.contexts["purpose"], "audience": self.contexts["audience"],
            "responsibilities": [self.contexts["responsibility"]], "preferences": [self.contexts["preference"]]}
        targets = list({canonical_bytes(entity_ref(r)): entity_ref(r) for r in refs if _public(r)}.values())
        self.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="assessment", targets=targets)
        with self.f.storage.snapshot() as view:
            self.access_context = self.access.capture(view, token=self.token, audience=self.other_audience, provider=self.provider, references=refs)
        # Re-prepare through the actual factory with the other authorized audience.
        with self.f.storage.snapshot() as view:
            profile = PacketProfile({"namespace": "synthetic", "id": "monitoring-source", "version": "1.0",
                "required_roles": [], "allowed_origins": ["source", "derived"], "locator_adapters": [self.f.adapter.reference],
                "max_sources": 16, "max_source_bytes": 65536, "max_packet_bytes": 65536})
            selected = self.packet.state["evidence"][0]
            self.packet = prepare_packet(view, profile, payloads=self.f.payloads, scope_id=self.f.storage.scope_id,
                binding={"kind": "claim", "claim": pin(self.claim)}, as_of=self.req["evidence"]["knowledge_cut"],
                evidence=[{"reference": pin(self.source), "roles": [], "locator": selected["locator"], "quotation": None,
                    "validation": selected["validation"]}], occurrences=[pin(self.occurrence)],
                coverage={"status": "complete", "snapshot": component("explicit-cohort")}, access=self.access, access_context=self.access_context)
        self.req = deepcopy(self.req)
        self.req.update(request_id="request-procurement-b", idempotency_key="procurement-command-b")
        self.req["host_binding"]["client_id"] = "302"
        self.req["intent"].update(id="intent-b", revision_id="intent-b-v1", content_hash=canonical_digest({"objective": "procurement"}, "synthetic.intent.v1"),
            purpose="Find open school technology procurements to bid on.", concepts=["open procurement"])
        self.req["intent"]["scope"]["objective_id"] = "intent-b"
        self.req["capture_binding"].update(watchlist_id="402", watchlist_item_id="412", user_activity_event_id="512")
        self.req["evidence"]["packet_digest"] = self.packet.digest
        with self.f.storage.snapshot() as view:
            self.req["context_components"] = {kind: _binding(view, self.f.storage.scope_id, ref)["reference"] for kind, ref in self.contexts.items()}
        self.state = HostMonitoringState(projection={k: deepcopy(self.req[k]) for k in HOST_FIELDS}, candidate=pin(self.f.subject),
            contexts=deepcopy(self.contexts), status="active", capture_exists=True, capture_authorized=True, capture_muted=False,
            budget_ceiling=deepcopy(self.req["budgets"]), reserved_cost_usd="0", source_finding=pin(self.claim))
        self.host = replace(self.host, binding=deepcopy(self.req["host_binding"]), access_context=self.access_context)

    def prepare_source_packet(self, access, context, *, coverage=None, additional_evidence=()):
        with self.f.storage.snapshot() as view:
            profile = PacketProfile({"namespace": "synthetic", "id": "monitoring-source", "version": "1.0",
                "required_roles": [], "allowed_origins": ["source", "derived"], "locator_adapters": [self.f.adapter.reference],
                "max_sources": 16, "max_source_bytes": 65536, "max_packet_bytes": 65536})
            locator = self.source["body"]["content"]["locator"]
            return prepare_packet(view, profile, payloads=self.f.payloads, scope_id=self.f.storage.scope_id,
                binding={"kind": "claim", "claim": pin(self.claim)}, as_of=self.req["evidence"]["knowledge_cut"],
                evidence=[{"reference": pin(self.source), "roles": [], "locator": locator, "quotation": None,
                    "validation": self.f.adapter.validate(self.source, locator, checked_at=self.f.now)}, *additional_evidence],
                occurrences=[pin(self.occurrence)], coverage=coverage or {"status": "complete", "snapshot": component("explicit-cohort")},
                access=access, access_context=context)

    def split_semantic_scope(self):
        output, output_context = self.access, self.access_context
        with self.f.storage.snapshot() as view:
            pref = _binding(view, self.f.storage.scope_id, self.contexts["preference"])
            excluded = [pref["context"], pref["version"], pin(view.get(pref["control"]))]
        semantic_refs = [r for r in self.references if r not in excluded]
        policy = output.policy.value
        self.access = AccessService(policy=HostAccessPolicy(scope_id=output.scope_id, audiences=policy["audiences"],
            providers=policy["providers"], grants=[g for g in policy["grants"] if g["reference"] not in excluded]),
            controls=self.f.controls, current_read=self.f.storage.snapshot)
        targets = list({canonical_bytes(entity_ref(r)): entity_ref(r) for r in semantic_refs if _public(r)}.values())
        self.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="assessment", targets=targets)
        with self.f.storage.snapshot() as view:
            self.access_context = self.access.capture(view, token=self.token, audience=self.a.audience_ref,
                provider=self.provider, references=semantic_refs)
        self.packet = self.prepare_source_packet(self.access, self.access_context)
        self.req["evidence"]["packet_digest"] = self.packet.digest
        self.state = replace(self.state, projection={k: deepcopy(self.req[k]) for k in HOST_FIELDS})
        self.host = replace(self.host, access=self.access, access_context=self.access_context,
            output_access=output, output_access_context=output_context)
        self.stage.token, self.stage.targets = self.token, targets
        early = {"state": "known", "value": "2049-01-01T00:00:00Z", "precision": "second"}
        late = {"state": "known", "value": "2051-01-01T00:00:00Z", "precision": "second"}
        with patch.object(stage_fixtures, "EARLY", early), patch.object(stage_fixtures, "LATE", late):
            self.stage.reserve(calls=4, expires=late)
        self.receipts = ExecutionReceiptStore(self.f.storage, payloads=self.f.payloads, controls=self.f.controls,
            clock=lambda: deepcopy(self.f.now), questions=self.questions, access=self.access, budgets=self.stage.budgets)

    def edit_preference(self):
        output = self.host.output_access
        previous = self.f.storage.get(self.contexts["preference"])
        with self.f.storage.snapshot() as view:
            value = _binding(view, self.f.storage.scope_id, self.contexts["preference"])["definition"]
        value["semantic_version"] = "2.0"
        value["content"]["preferred_treatment"] = "update"
        updated, _, _ = self.a.contexts.publish(ContextDefinition(value), previous=pin(previous))
        self.contexts["preference"] = pin(updated)
        policy = output.policy.value
        grants = list(policy["grants"])
        old_grant = next(g for g in grants if g["reference"] == pin(previous))
        grants.append({**old_grant, "reference": pin(updated)})
        output.policy = HostAccessPolicy(scope_id=output.scope_id, audiences=policy["audiences"], providers=policy["providers"], grants=grants)
        refs = [r for r in self.references if r != pin(previous)] + [pin(updated)]
        token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="assessment",
            targets=list({canonical_bytes(entity_ref(r)): entity_ref(r) for r in refs if _public(r)}.values()))
        with self.f.storage.snapshot() as view:
            output_context = output.capture(view, token=token, audience=self.a.audience_ref, provider=self.provider, references=refs)
            self.req["context_components"]["preference"] = _binding(view, self.f.storage.scope_id, pin(updated))["reference"]
        self.req.update(request_id="preference-edit", idempotency_key="preference-edit")
        self.req["intent"]["revision_id"] = "intent-a-v2"
        self.req["intent"]["revision_number"] = 2
        self.req["intent"]["preference"]["cadence"] = "immediate"
        self.req["intent"]["content_hash"] = canonical_digest(self.req["intent"]["preference"], "synthetic.intent-edit.v1")
        self.state = replace(self.state, contexts=deepcopy(self.contexts), projection={k: deepcopy(self.req[k]) for k in HOST_FIELDS})
        self.host = replace(self.host, output_access_context=output_context)

    def admit(self, request=None):
        return AdmittedMonitoring(request or self.req, host=self.host, packet=self.packet)

    def renew_allocation(self):
        # Each independent command gets a real committed reservation. The
        # inherited fixture intentionally reserves only ten seconds per one.
        early = {"state": "known", "value": "2049-01-01T00:00:00Z", "precision": "second"}
        late = {"state": "known", "value": "2051-01-01T00:00:00Z", "precision": "second"}
        self.stage.token = self.token
        self.stage.targets = self.token["targets"]
        with patch.object(stage_fixtures, "EARLY", early), patch.object(stage_fixtures, "LATE", late):
            self.stage.reserve(calls=4, expires=late)
        self.receipts.budgets = self.stage.budgets

    def refresh(self, *, extra=()):
        """Real host projection refresh after adding authorized native inputs."""
        self.references = list({canonical_bytes(r): r for r in [*self.references, *extra]}.values())
        policy = self.access.policy.value
        grants = list(policy["grants"])
        for ref in extra:
            if _public(ref) and not any(g["reference"] == ref for g in grants):
                grants.append({"reference": ref, "audiences": [self.a.audience_ref], "providers": [self.provider]})
        self.access.policy = HostAccessPolicy(scope_id=self.access.scope_id, audiences=policy["audiences"],
            providers=policy["providers"], grants=grants)
        targets = list({canonical_bytes(entity_ref(r)): entity_ref(r) for r in [*self.references, *self.e.public.values()] if _public(r)}.values())
        self.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="assessment", targets=targets)
        with self.f.storage.snapshot() as view:
            self.access_context = self.access.capture(view, token=self.token, audience=self.a.audience_ref,
                provider=self.provider, references=self.references)
        self.packet = self.prepare_source_packet(self.access, self.access_context)
        self.req["evidence"]["packet_digest"] = self.packet.digest
        self.state = replace(self.state, source_finding=pin(self.claim),
            projection={k: deepcopy(self.req[k]) for k in HOST_FIELDS})
        self.host = replace(self.host, access_context=self.access_context)

    def observe(self, parameters):
        decision = parameters["attention"].current(pin(self.f.subject), policy=self.a.policy,
            purpose=self.a.purpose_ref, audience=self.a.audience_ref,
            read_token=parameters["read_token"], access_context=parameters["access_context"])
        receipt = self.a.milestone(decision)
        assessment = self.f.storage.get(decision["body"]["details"]["value"]["assessment"])
        token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
            capability="delivery", targets=self.a.targets(assessment))
        with self.f.storage.snapshot() as view:
            context = self.access.capture(view, token=token, audience=self.a.audience_ref, provider=self.provider,
                references=[*self.references, pin(assessment)])
        command = self.a.prepare(assessment, delivery_receipt=pin(receipt), token=token, access_context=context)
        result = self.a.service.evaluate(command)
        if result["status"] != "success":
            raise AssertionError(result)
        value = decision["body"]["details"]["value"]
        self.req["baseline"] = {"status": "observed_capture", "receipt": pin(receipt),
            "owner": {**{k: self.req["host_binding"][k] for k in ("user_id", "workspace_id", "client_id")}, "intent_id": self.req["intent"]["id"]},
            "intent_revision_id": self.req["intent"]["revision_id"], "assessment_reference": pin(assessment),
            "conveyed_material_digest": value["material_digest"]}
        self.refresh(extra=[pin(assessment)])
        return value

    def batch(self, admitted):
        packet = admitted.audience_packet()
        rendered = tuple(render_question(s, packet.state, s.value["id"], source_manifest=packet.source_manifest,
            access=self.access, access_context=self.access_context, access_view=self.f.storage) for s in self.specs)
        deadline = (datetime.strptime(self.f.now["value"], "%Y-%m-%dT%H:%M:%SZ") + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return Batch({"schema_version": "1.0", "id": "monitoring-batch", "scope_id": self.f.storage.scope_id,
            "run_id": "monitoring-run", "stage_id": "audience", "state": packet.state, "packet_digest": packet.digest,
            "questions": [q.question.value for q in rendered], "context": {"provider": "synthetic", "transport": "fixture",
                "requested_model": "synthetic-fixed", "adapter_version": "1.0", "mode": "offline_fixture", "deadline": {
                    "state": "known", "value": deadline, "precision": "second"}, "max_request_bytes": 65536, "max_response_bytes": 65536}}), rendered

    def execute(self, admitted=None):
        admitted = admitted or self.admit()
        batch, rendered = self.batch(admitted)
        return admitted.execute(receipts=self.receipts, batch=batch, rendered_questions=rendered, executor=self.executor,
            allocation=self.stage.reservation, model_binding={"model": "synthetic-fixed", "resolution": component("fixed-resolution")})

    def publish_attention(self, status="supported", *, additional=()):
        # Local synthetic host interpretation, not a learned-provider admission.
        # History is compared by AttentionService's verified baseline. Do not
        # declare a superseded historical assessment a current semantic input.
        current_refs = [ref for ref in self.references if ref["record_type"] != "assessment"]
        with self.f.storage.snapshot() as view:
            current_refs = [ref for ref in current_refs if ref["record_type"] != "observation" or
                (view.get(ref)["body"]["available_at"]["state"] == "known" and
                 compare_times(view.get(ref)["body"]["available_at"], self.req["evidence"]["knowledge_cut"]) <= 0)]
            current_context = self.access.capture(view, token=self.token, audience=self.a.audience_ref,
                provider=self.provider, references=current_refs)
        request = self.f.request(evidence=[pin(self.claim), *[pin(c) for c in additional], pin(self.occurrence)])
        request["body"].update(purpose=self.a.purpose_ref, audience=self.a.audience_ref, control_epoch=self.token["control_epoch"])
        request["body"]["budget"]["max_elapsed_ms"] = 30000
        prepared = self.f.service.prepare(request, token=self.token, plan=self.f.plan,
            extra_dependencies=current_refs, access_context=current_context)
        command = self.f.command(prepared, interpretations=[{"node": "evidence", "claim": pin(claim),
            "labels": {"example:positive": status if claim == self.claim else "supported"},
            "evidence_standard": self.f.profile.component_references["evidence"]} for claim in [self.claim, *additional]])
        result = self.f.service.commit(command)
        if result["status"] != "success":
            raise AssertionError(result)
        assessment = self.f.storage.get(result["body"]["assessment"])
        self.e.remember(assessment)
        for ref in assessment["body"]["judgments"]:
            self.e.remember(self.f.storage.get(ref))
        return self.evaluate_attention(assessment)

    def evaluate_attention(self, assessment):
        refs = [*self.references, pin(assessment)]
        targets = list({canonical_bytes(entity_ref(r)): entity_ref(r) for r in
            [*self.a.targets(assessment), *[entity_ref(r) for r in self.references if _public(r)]]}.values())
        token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
            capability="assessment", targets=targets)
        with self.f.storage.snapshot() as view:
            context = self.access.capture(view, token=token, audience=self.a.audience_ref, provider=self.provider, references=refs)
        attention_command = self.a.prepare(assessment, token=token, access_context=context)
        completed = self.a.service.evaluate(attention_command)
        if completed["status"] != "success":
            raise AssertionError(completed)
        read_token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
            capability="read", targets=token["targets"])
        return {"attention": self.a.service, "read_token": read_token,
                "access_context": context, "source_finding": pin(self.claim)}


class MonitoringHandoffTests(unittest.TestCase):
    def setUp(self):
        self.h = MonitoringFixture(self)

    def test_actual_packet_adds_only_approved_context_and_preserves_source_cut(self):
        h = self.h
        admitted = h.admit()
        packet = admitted.audience_packet()
        self.assertEqual(packet.state["evidence"], h.packet.state["evidence"])
        self.assertEqual(packet.state["as_of"], h.packet.state["as_of"])
        self.assertNotIn("monitoring", h.packet.state)
        text = canonical_bytes(packet.state["monitoring"])
        for forbidden in (b"capture_binding", b"host_binding", b"approval", b"contact_email", b"client_notes", b"control-token"):
            self.assertNotIn(forbidden, text)

    def test_guarded_recorded_execution_and_exact_durable_retry(self):
        h = self.h
        admitted = h.admit()
        first = h.execute(admitted)
        self.assertEqual(first["status"], "completed", first)
        self.assertTrue(first["result"].primitive_valid)
        again = h.execute(h.admit())
        self.assertFalse(again["dispatched"])
        self.assertEqual(len(h.calls), 1)
        self.assertEqual(first["execution"], again["execution"])
        changed = deepcopy(h.req)
        changed["request_id"] = "different-body-same-logical-key"
        with self.assertRaises(ContractError) as conflict:
            h.execute(h.admit(changed))
        self.assertEqual(conflict.exception.code, "E_IDEMPOTENCY_CONFLICT")
        self.assertEqual(len(h.calls), 1)
        batch, rendered = h.batch(h.admit())
        h.f.now = {"state": "known", "value": "2050-01-01T00:00:20Z", "precision": "second"}
        recovered = h.admit().execute(receipts=h.receipts, batch=batch, rendered_questions=rendered,
            executor=None, allocation=h.stage.reservation, model_binding={"model": "synthetic-fixed", "resolution": component("fixed-resolution")})
        self.assertEqual(recovered["execution"], first["execution"])
        self.assertFalse(recovered["dispatched"])
        self.assertEqual(len(h.calls), 1)

    def test_target_draft_pause_revoke_mute_and_scope_refuse_before_execution(self):
        h = self.h
        original = h.state
        for changes in ({"capture_exists": False}, {"capture_authorized": False}, {"capture_muted": True},
                        {"status": "draft"}, {"status": "paused"}, {"status": "revoked"}):
            with self.subTest(changes=changes), self.assertRaises(ContractError) as refused:
                h.state = replace(original, **changes)
                h.admit()
            if changes == {"capture_exists": False}:
                self.assertEqual(monitoring_refusal(refused.exception, request_id=h.req["request_id"])["reason"], "capture_binding_missing")
        h.state = original
        foreign = deepcopy(h.req)
        foreign["host_binding"]["client_id"] = "other-client"
        with self.assertRaises(ContractError) as error:
            h.admit(foreign)
        self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
        self.assertEqual(h.calls, [])
        h.executor = None
        with self.assertRaises(ContractError) as unconfigured:
            h.execute()
        wire = monitoring_refusal(unconfigured.exception, request_id=h.req["request_id"])
        self.assertEqual((wire["code"], wire["reason"]), ("E_POLICY_INVALID", "provider_not_configured"))
        self.assertEqual(h.calls, [])

    def test_intent_edit_during_io_withholds_answer_and_retains_attempt(self):
        h = self.h
        def edit():
            projection = deepcopy(h.state.projection)
            projection["intent"]["revision_id"] = "new-approved-revision"
            h.state = replace(h.state, projection=projection)
        h.on_execute = edit
        with self.assertRaises(ContractError) as error:
            h.execute()
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.assertEqual(len(h.calls), 1)
        logical = canonical_digest({"host": h.host.binding, "key": h.req["idempotency_key"]}, "matter.monitoring-logical.v1")
        phases = [r["body"]["details"]["value"]["phase"] for r in h.receipts.history(logical, "initial")]
        self.assertEqual(phases, ["started", "completed"])

    def test_unknown_prior_outcome_is_not_absent_history(self):
        h = self.h
        req = deepcopy(h.req)
        req["baseline"] = {"status": "outcome_unknown", "attempt_id": "interrupted-capture"}
        projection = deepcopy(h.state.projection)
        projection["baseline"] = req["baseline"]
        h.state = replace(h.state, projection=projection)
        with self.assertRaises(ContractError) as error:
            h.admit(req)
        self.assertEqual(error.exception.code, "E_DELIVERY_UNKNOWN")
        self.assertEqual(h.calls, [])

    def test_current_core_decision_projects_capture_only_and_rejects_forged_handoff(self):
        h = self.h
        admitted = h.admit()
        parameters = h.publish_attention()
        result = admitted.project(**parameters)
        self.assertEqual(result["treatment"], "digest")
        self.assertEqual(result["qualification"], "unqualified")
        self.assertEqual(result["permitted_use"], "capture_only")
        calls = []
        def capture(**args):
            args["require_current"]()
            calls.append(args)
            return {"status": "captured", "fixture": True}
        forged = deepcopy(result)
        forged["treatment"] = "update"
        with self.assertRaises(ContractError):
            admitted.handoff(forged, capture=capture)
        admitted.handoff(result, capture=capture)
        self.assertEqual(calls[0]["channels"], ["in_app"])
        self.assertEqual(len(calls[0]["assessment_key"]), 64)
        self.assertEqual(calls[0]["binding"], h.req["capture_binding"])
        h.state = replace(h.state, capture_authorized=False)
        with self.assertRaises(ContractError):
            admitted.handoff(result, capture=capture)
        self.assertEqual(len(calls), 1)

    def test_replay_and_live_projection_have_identical_treatment_and_capture_identity(self):
        h = self.h
        late_at = {"state": "known", "value": "2050-01-02T00:00:00Z", "precision": "second"}
        late_source, _ = h.e.event("FUTURE-PARITY-CANARY", at=h.f.now, available_at=late_at)
        h.refresh(extra=[pin(late_source)])
        locator = late_source["body"]["content"]["locator"]
        h.packet = h.prepare_source_packet(h.access, h.access_context, additional_evidence=[{
            "reference": pin(late_source), "roles": [], "locator": locator, "quotation": None,
            "validation": h.f.adapter.validate(late_source, locator, checked_at=h.f.now)}])
        h.req["evidence"]["packet_digest"] = h.packet.digest
        h.state = replace(h.state, projection={k: deepcopy(h.req[k]) for k in HOST_FIELDS})
        self.assertTrue(any(item["reference"] == pin(late_source) for item in h.packet.source_manifest["excluded"]))
        h.renew_allocation()
        replay = h.admit()
        replay_state = replay.audience_packet().state
        replay_execution = h.execute(replay)
        self.assertTrue(replay_execution["result"].primitive_valid)
        arguments = h.publish_attention()
        before = replay.project(**arguments)
        keys = []
        def capture(**args):
            args["require_current"]()
            keys.append(args["assessment_key"])
        replay.handoff(before, capture=capture)
        h.req.update(mode="live_shadow_capture", request_id="live-equivalent", idempotency_key="live-equivalent")
        h.req["context_selection"]["policy"] = "current"
        h.state = replace(h.state, projection={k: deepcopy(h.req[k]) for k in HOST_FIELDS})
        live = h.admit()
        live_state = live.audience_packet().state
        h.renew_allocation()
        live_execution = h.execute(live)
        self.assertTrue(live_execution["result"].primitive_valid)
        assessment = h.f.storage.get(before["assessment_reference"])
        after = live.project(**h.evaluate_attention(assessment))
        live.handoff(after, capture=capture)
        for key in ("treatment", "reasons", "citations", "assessment_reference", "source_finding_reference"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(len(h.calls), 2)
        self.assertNotEqual(replay_state["monitoring"]["context_selection"], live_state["monitoring"]["context_selection"])
        replay_state["monitoring"].pop("context_selection")
        live_state["monitoring"].pop("context_selection")
        self.assertEqual(replay_state, live_state)
        for call in h.calls:
            self.assertNotIn(b"FUTURE-PARITY-CANARY", canonical_bytes(call))
            self.assertEqual(call["state"]["evidence"], h.packet.state["evidence"])

    def test_native_observed_baseline_suppresses_repeat_and_preserves_linked_correction(self):
        h = self.h
        first_args = h.publish_attention()
        before = h.admit().project(**first_args)
        self.assertEqual(before["treatment"], "digest")
        material = h.observe(first_args)
        duplicate = h.admit()
        self.assertEqual(duplicate.audience_packet().state["monitoring"]["observed_baseline"], material["material"])
        repeat_parameters = h.publish_attention()
        repeated = duplicate.project(**repeat_parameters)
        self.assertEqual(repeated["treatment"], "quiet")
        self.assertIn("already_delivered", repeated["reasons"])
        observed = deepcopy(h.req["baseline"])
        h.req["baseline"] = {"status": "no_observed_output"}
        h.state = replace(h.state, projection={k: deepcopy(h.req[k]) for k in HOST_FIELDS})
        with self.assertRaises(ContractError) as omitted_history:
            h.admit().project(**repeat_parameters)
        self.assertEqual(omitted_history.exception.code, "E_DEPENDENCY_STALE")
        h.req["baseline"] = observed
        h.state = replace(h.state, projection={k: deepcopy(h.req[k]) for k in HOST_FIELDS})
        original = h.claim
        from integration import test_lifecycle_episodes as lifecycle_fixtures
        future_end = {"state": "known", "value": "2051-01-01T00:00:00Z", "precision": "second"}
        with patch.object(lifecycle_fixtures, "FUTURE", future_end):
            h.claim = h.e.claim("linked-retraction", h.e.condition_a, "retracted", h.source,
                effective=h.f.now, supersedes=[original])
        h.req["evidence"]["correction_of"] = [pin(original)]
        h.refresh(extra=[pin(h.claim)])
        corrected = h.admit().project(**h.publish_attention("unknown"))
        self.assertEqual(corrected["treatment"], "correction")
        self.assertIn("correction_delta", corrected["reasons"])
        self.assertIn("insufficient_evidence", corrected["reasons"])

    def test_real_access_policy_revocation_expiry_and_budget_refuse_before_io(self):
        h = self.h
        admitted = h.admit()
        original = h.state
        h.state = replace(original, reserved_cost_usd="100")
        with self.assertRaises(ContractError) as cost:
            admitted.require_current()
        self.assertEqual(cost.exception.code, "E_BUDGET_EXHAUSTED")
        h.state = original
        h.req["intent"]["active_until"] = deepcopy(h.f.now)
        h.state = replace(original, projection={k: deepcopy(h.req[k]) for k in HOST_FIELDS})
        with self.assertRaises(ContractError) as expired:
            h.admit()
        self.assertEqual(expired.exception.code, "E_CANCELLED")
        h.req["intent"]["active_until"] = None
        h.state = original
        policy = h.access.policy.value
        h.access.policy = HostAccessPolicy(scope_id=h.access.scope_id, audiences=policy["audiences"],
            providers=policy["providers"], grants=[g for g in policy["grants"] if g["reference"] != pin(h.source)])
        with self.assertRaises(ContractError) as revoked:
            admitted.audience_packet()
        self.assertEqual(revoked.exception.code, "E_AUTHORITY_REQUIRED")
        self.assertEqual(h.calls, [])

    def test_personal_binding_and_denied_foreign_context_read(self):
        h = self.h
        h.req["host_binding"]["client_id"] = None
        h.state = replace(h.state, projection={k: deepcopy(h.req[k]) for k in HOST_FIELDS})
        h.host = replace(h.host, binding=deepcopy(h.req["host_binding"]))
        admitted = h.admit()
        self.assertIsNone(admitted.request["host_binding"]["client_id"])
        with h.f.storage.snapshot() as view, self.assertRaises(ContractError) as foreign:
            h.access.require_current(view, h.access_context, references=[h.other_contexts["purpose"]])
        self.assertEqual(foreign.exception.code, "E_AUTHORITY_REQUIRED")
        # A fresh complete control token removes missing-target/capture as an
        # alternative explanation: the actual audience grant must refuse it.
        foreign_refs = [*h.references, h.other_contexts["purpose"]]
        token = h.f.controls.capture(actor=h.f.actor, authority=entity_ref(h.f.authority), capability="assessment",
            targets=list({canonical_bytes(entity_ref(r)): entity_ref(r) for r in foreign_refs if _public(r)}.values()))
        with h.f.storage.snapshot() as view, self.assertRaises(ContractError) as grant:
            h.access.capture(view, token=token, audience=h.a.audience_ref, provider=h.provider, references=foreign_refs)
        self.assertEqual(grant.exception.code, "E_AUTHORITY_REQUIRED")

    def test_broad_objective_accepts_an_authorized_candidate_created_after_context_activation(self):
        h = self.h
        # Publish reusable broad templates before creating the new candidate.
        with h.f.storage.snapshot() as view:
            definitions = {k: _binding(view, h.f.storage.scope_id, ref)["definition"] for k, ref in h.contexts.items()}
        for kind, definition in definitions.items():
            definition.update(semantic_version="2.0", applies_to=[])
            record, _, _ = h.a.contexts.publish(ContextDefinition(definition), previous=h.contexts[kind])
            h.contexts[kind] = pin(record)
            h.e.remember(record)
        from integration.helpers import create_command
        command = create_command("late-candidate", "create-late-candidate", scope_id=h.f.storage.scope_id)
        with h.f.storage.snapshot() as view, self.assertRaises(StorageError):
            view.get(entity_ref(command["body"]["matter"]))
        def create(tx):
            record = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(record)})
        result = h.f.storage.execute(command, create)
        self.assertEqual(result["status"], "success", result)
        h.f.subject = h.f.storage.get(result["body"]["matter"])
        h.e.remember(h.f.subject)
        h.source, h.occurrence = h.e.event("late-candidate-source", at=h.f.now, available_at=h.f.now)
        from integration import test_lifecycle_episodes as lifecycle_fixtures
        end = {"state": "known", "value": "2051-01-01T00:00:00Z", "precision": "second"}
        with patch.object(lifecycle_fixtures, "FUTURE", end):
            h.claim = h.e.claim("late-candidate-finding", h.e.condition_a, "present", h.source, effective=h.f.now)
        h.f.source = h.source
        with h.f.storage.snapshot() as view:
            h.req["context_components"] = {k: _binding(view, h.f.storage.scope_id, ref)["reference"] for k, ref in h.contexts.items()}
            dependencies = []
            for ref in h.contexts.values():
                bound = _binding(view, h.f.storage.scope_id, ref)
                dependencies += [bound["context"], bound["version"], pin(view.get(bound["control"]))]
        h.a.purpose_ref, h.a.audience_ref = (h.req["context_components"][k] for k in ("purpose", "audience"))
        h.references = [pin(r) for r in (h.f.subject, h.source, h.occurrence, h.claim)] + dependencies
        h.access.policy = HostAccessPolicy(scope_id=h.access.scope_id, audiences=[h.a.audience_ref],
            providers=h.access.policy.value["providers"], grants=[{"reference": ref, "audiences": [h.a.audience_ref],
                "providers": [h.provider]} for ref in h.references if _public(ref)])
        h.state = replace(h.state, candidate=pin(h.f.subject), contexts=deepcopy(h.contexts))
        h.req["evidence"]["occurrences"] = [pin(h.occurrence)]
        source = h.req["evidence"]["sources"][0]
        source.update(reference=pin(h.source), available_at=h.source["body"]["available_at"], occurred_at=h.source["body"]["occurred_at"],
            published_at=h.source["body"]["source_published_at"], artifact_sha256=h.source["body"]["content"]["digest"],
            origin=h.source["provenance"]["origin"], parents=h.source["provenance"]["parents"])
        h.refresh()
        selected = h.packet.state["evidence"][0]
        source.update(selected_text_sha256=selected["text_digest"], locator=selected["locator"])
        h.state = replace(h.state, projection={k: deepcopy(h.req[k]) for k in HOST_FIELDS})
        admitted = h.admit()
        self.assertEqual(admitted.source_packet.state["binding"]["claim"], pin(h.claim))
        self.assertEqual(h.req["intent"]["scope"]["kind"], "objective")
        self.assertNotIn("entity_id", h.req["intent"]["scope"])
        policy = h.access.policy.value
        h.access.policy = HostAccessPolicy(scope_id=h.access.scope_id, audiences=policy["audiences"], providers=policy["providers"],
            grants=[g for g in policy["grants"] if g["reference"] != pin(h.f.subject)])
        with self.assertRaises(ContractError):
            admitted.require_current()

    def test_capture_failure_stays_unknown_and_does_not_resend(self):
        h = self.h
        admitted = h.admit()
        parameters = h.publish_attention()
        result = admitted.project(**parameters)
        calls = []
        def interrupted(**args):
            args["require_current"]()
            calls.append(args["assessment_key"])
            raise RuntimeError("SYNTHETIC-SECRET-DETAIL")
        for _ in range(2):
            with self.assertRaises(ContractError) as failure:
                admitted.handoff(result, capture=interrupted)
            self.assertEqual(failure.exception.code, "E_DELIVERY_UNKNOWN")
            self.assertNotIn("SECRET", str(failure.exception))
        self.assertEqual(len(calls), 1)
        self.assertEqual(h.req["baseline"]["status"], "no_observed_output")
        guarded = h.admit()
        proposal = guarded.project(**parameters)
        original = h.state
        def revoked_before_write(**args):
            h.state = replace(h.state, capture_authorized=False)
            args["require_current"]()
            self.fail("revoked capture reached its write")
        with self.assertRaises(ContractError) as refusal:
            guarded.handoff(proposal, capture=revoked_before_write)
        self.assertEqual(refusal.exception.code, "E_AUTHORITY_REQUIRED")
        h.state = original
        def successful(**args):
            args["require_current"]()
            return "captured"
        self.assertEqual(guarded.handoff(proposal, capture=successful), "captured")

    def test_scoped_old_acknowledgement_does_not_silence_a_new_typed_deadline(self):
        h = self.h
        value = h.a.policy.value
        value["fields"].append({**deepcopy(value["fields"][0]), "name": "deadline", "condition": h.e.condition_b,
            "value_pointer": "/confidence", "roles": ["material"], "accepted_values": ["2050-02-01", "2050-02-08"]})
        h.a.policy = AttentionPolicy(value)
        h.a.service = AttentionService(h.f.storage, assessments=h.f.service, policies=[h.a.policy], controls=h.f.controls,
            clock=lambda: deepcopy(h.f.now), lifecycle=h.e.lifecycle, access=h.access)
        h.host = replace(h.host, attention=h.a.service)
        h.req["evaluation"]["policy"] = h.a.policy.reference
        from integration import test_lifecycle_episodes as lifecycle_fixtures
        end = {"state": "known", "value": "2051-01-01T00:00:00Z", "precision": "second"}
        with patch.object(lifecycle_fixtures, "FUTURE", end):
            first_deadline = h.e.claim("deadline-one", h.e.condition_b, "present", h.source,
                effective=h.f.now, confidence="2050-02-01")
        h.refresh(extra=[pin(first_deadline)])
        arguments = h.publish_attention(additional=[first_deadline])
        initial = h.admit().project(**arguments)
        self.assertEqual(initial["treatment"], "digest")
        h.observe(arguments)
        prior_assessment = h.req["baseline"]["assessment_reference"]
        definition = h.a.contexts.disposition("acknowledgement", h.a.purpose, h.a.audience, subject=prior_assessment)
        disposition, _, _ = h.a.contexts.publish(definition, service=h.a.contexts.dispositions)
        h.req["dispositions"] = [pin(disposition)]
        with patch.object(lifecycle_fixtures, "FUTURE", end):
            new_deadline = h.e.claim("deadline-two", h.e.condition_b, "present", h.source,
                effective=h.f.now, confidence="2050-02-08", supersedes=[first_deadline])
        h.refresh(extra=[pin(disposition), pin(new_deadline)])
        admitted = h.admit()
        self.assertEqual(admitted.audience_packet().state["monitoring"]["dispositions"][0]["subject"], prior_assessment)
        result = admitted.project(**h.publish_attention(additional=[new_deadline]))
        self.assertIn(result["treatment"], {"digest", "correction"})
        self.assertNotEqual(result["treatment"], "quiet")
        self.assertIn(pin(disposition), result["dependencies"])

    def test_provider_failure_is_retained_as_failure_and_creates_no_attention_decision(self):
        h = self.h
        def outage():
            raise RuntimeError("SYNTHETIC-SECRET-DETAIL")
        h.on_execute = outage
        result = h.execute()
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["result"].primitive_valid)
        self.assertEqual(result["result"].value["execution_status"], "failed")
        self.assertNotIn("SECRET", str(result["result"].value))
        self.assertEqual(len(h.calls), 1)
        h.execute()
        self.assertEqual(len(h.calls), 1)

    def test_pause_at_dispatch_boundary_records_known_cancellation_without_transport(self):
        h = self.h
        run = h.receipts.run
        def pause_at_boundary(*args, dispatch, **kwargs):
            def paused(**parameters):
                h.state = replace(h.state, status="paused")
                return dispatch(**parameters)
            return run(*args, dispatch=paused, **kwargs)
        with patch.object(h.receipts, "run", pause_at_boundary), self.assertRaises(ContractError) as refused:
            h.execute()
        self.assertEqual(refused.exception.code, "E_CANCELLED")
        self.assertEqual(h.calls, [])
        logical = canonical_digest({"host": h.host.binding, "key": h.req["idempotency_key"]}, "matter.monitoring-logical.v1")
        history = h.receipts.history(logical, "initial")
        details = [r["body"]["details"]["value"] for r in history]
        self.assertEqual([r["phase"] for r in details], ["started", "completed"])
        self.assertEqual(details[-1]["result"]["execution_status"], "cancelled")
        h.state = replace(h.state, status="active")
        with self.assertRaises(ContractError) as retry:
            h.execute()
        self.assertEqual(retry.exception.code, "E_CANCELLED")
        self.assertEqual(h.calls, [])

    def test_source_grant_revocation_at_dispatch_and_during_io_withholds_and_never_resends(self):
        h = self.h
        original_policy = h.access.policy
        policy = original_policy.value
        def revoke():
            h.access.policy = HostAccessPolicy(scope_id=h.access.scope_id, audiences=policy["audiences"],
                providers=policy["providers"], grants=[g for g in policy["grants"] if g["reference"] != pin(h.source)])
        run = h.receipts.run
        def revoke_at_boundary(*args, dispatch, **kwargs):
            def withheld(**parameters):
                revoke()
                return dispatch(**parameters)
            return run(*args, dispatch=withheld, **kwargs)
        with patch.object(h.receipts, "run", revoke_at_boundary), self.assertRaises(ContractError) as queued:
            h.execute()
        self.assertEqual(queued.exception.code, "E_AUTHORITY_REQUIRED")
        self.assertEqual(h.calls, [])
        # Explicit synthetic owner regrant permits inspection, never a blind retry.
        h.access.policy = original_policy
        with self.assertRaises(ContractError) as queued_retry:
            h.execute()
        self.assertEqual(queued_retry.exception.code, "E_DELIVERY_UNKNOWN")
        self.assertEqual(h.calls, [])
        h.req.update(request_id="revoke-during-io", idempotency_key="revoke-during-io")
        h.renew_allocation()
        h.on_execute = revoke
        with self.assertRaises(ContractError) as inflight:
            h.execute()
        self.assertEqual(inflight.exception.code, "E_AUTHORITY_REQUIRED")
        self.assertEqual(len(h.calls), 1)
        h.access.policy = original_policy
        h.on_execute = None
        with self.assertRaises(ContractError) as inflight_retry:
            h.execute()
        self.assertEqual(inflight_retry.exception.code, "E_DELIVERY_UNKNOWN")
        self.assertEqual(len(h.calls), 1)

    def test_recording_refusals_preserve_budget_and_unknown_outcomes(self):
        h = self.h
        commit = h.receipts.commit
        refused_phase = ["started"]
        failure_code = ["E_BUDGET_EXHAUSTED"]
        def refuse_recording(command, *args, **kwargs):
            phase = command["body"]["receipt"]["body"]["details"]["value"]["phase"]
            if phase == refused_phase[0]:
                return {"status": "failure", "error": {"code": failure_code[0]}}
            return commit(command, *args, **kwargs)
        with patch.object(h.receipts, "commit", refuse_recording):
            for native, wire in (("E_BUDGET_EXHAUSTED", "E_BUDGET_EXHAUSTED"),
                                 ("E_STORAGE_UNAVAILABLE", "E_EVIDENCE_UNAVAILABLE"),
                                 ("E_NOT_FOUND", "E_EVIDENCE_UNAVAILABLE"),
                                 ("E_REVISION_CONFLICT", "E_DEPENDENCY_STALE")):
                with self.subTest(native=native):
                    failure_code[0] = native
                    with self.assertRaises(ContractError) as no_start:
                        h.execute()
                    self.assertEqual(no_start.exception.code, native)
                    self.assertEqual(monitoring_refusal(no_start.exception,
                        request_id=h.req["request_id"])["code"], wire)
                    self.assertEqual(h.calls, [])
            refused_phase[0] = "completed"
            with self.assertRaises(ContractError) as unrecorded:
                h.execute()
            self.assertEqual(unrecorded.exception.code, "E_DELIVERY_UNKNOWN")
        batch, rendered = h.batch(h.admit())
        h.f.now = {"state": "known", "value": "2050-01-01T00:00:20Z", "precision": "second"}
        with self.assertRaises(ContractError) as retry:
            h.admit().execute(receipts=h.receipts, batch=batch, rendered_questions=rendered,
                executor=None, allocation=h.stage.reservation, model_binding={"model": "synthetic-fixed", "resolution": component("fixed-resolution")})
        self.assertEqual(retry.exception.code, "E_DELIVERY_UNKNOWN")
        self.assertEqual(len(h.calls), 1)

    def test_sink_cannot_report_guarded_success_after_skipping_or_swallowing_guard(self):
        h = self.h
        parameters = h.publish_attention()
        original = h.state
        writes = []
        for behavior in ("skip", "swallow", "partial"):
            with self.subTest(behavior=behavior):
                admitted = h.admit()
                proposal = admitted.project(**parameters)
                def invalid_sink(**args):
                    if behavior == "partial":
                        args["require_current"]()
                        writes.append("partial-write")
                        h.state = replace(h.state, capture_authorized=False)
                        args["require_current"]()
                    if behavior == "swallow":
                        h.state = replace(h.state, capture_authorized=False)
                        try:
                            args["require_current"]()
                        except ContractError:
                            pass
                    return "not-a-verified-capture"
                with self.assertRaises(ContractError) as unknown:
                    admitted.handoff(proposal, capture=invalid_sink)
                self.assertEqual(unknown.exception.code, "E_DELIVERY_UNKNOWN")
                h.state = original
                before = len(writes)
                with self.assertRaises(ContractError) as retry:
                    admitted.handoff(proposal, capture=invalid_sink)
                self.assertEqual(retry.exception.code, "E_DELIVERY_UNKNOWN")
                self.assertEqual(len(writes), before)
        self.assertEqual(writes, ["partial-write"])

    def test_partial_coverage_cannot_project_an_ordinary_positive(self):
        h = self.h
        arguments = h.publish_attention()
        h.packet = h.prepare_source_packet(h.access, h.access_context, coverage={"status": "partial",
            "snapshot": component("partial-cohort"), "reason": "Synthetic collection is incomplete."})
        h.req["evidence"].update(packet_digest=h.packet.digest, coverage="partial", coverage_reason="Incomplete supplied collection.")
        h.state = replace(h.state, projection={k: deepcopy(h.req[k]) for k in HOST_FIELDS})
        with self.assertRaises(ContractError) as incomplete:
            h.admit().project(**arguments)
        self.assertEqual(incomplete.exception.code, "E_EVIDENCE_UNAVAILABLE")

    def test_same_actual_finding_has_two_current_audiences_and_expected_silence(self):
        h = self.h
        first = h.admit()
        first_packet = first.audience_packet()
        first_args = h.publish_attention("supported")
        first_result = first.project(**first_args)
        h.activate_other()
        second = h.admit()
        second_result = second.project(**h.publish_attention("not_applicable"))
        self.assertEqual(first_result["source_finding_reference"], second_result["source_finding_reference"])
        self.assertEqual(first_packet.state["evidence"], second.audience_packet().state["evidence"])
        self.assertEqual((first_result["treatment"], second_result["treatment"]), ("digest", "quiet"))
        def forbidden_capture(**args):
            self.fail("quiet is not a capture")
        self.assertIsNone(second.handoff(second_result, capture=forbidden_capture))
        # An unrelated objective's host pause cannot invalidate the first one.
        h.state = replace(h.state, status="paused")
        first.require_current()
        with self.assertRaises(ContractError):
            second.require_current()

    def test_forged_scope_and_future_manifest_fail_even_if_host_projection_echoes_them(self):
        h = self.h
        original = h.state
        req = deepcopy(h.req)
        req["evidence"]["sources"][0]["available_at"]["value"] = "2050-01-02T00:00:00Z"
        projection = deepcopy(original.projection)
        projection["evidence"] = req["evidence"]
        h.state = replace(original, projection=projection)
        with self.assertRaises(ContractError) as error:
            h.admit(req)
        self.assertEqual(error.exception.code, "E_EVIDENCE_UNAVAILABLE")
        h.state = original
        raw = deepcopy(h.req)
        raw["intent"]["client_notes"] = "SYNTHETIC-UNRELATED-CLIENT-NOTES"
        with self.assertRaises(ContractError) as error:
            h.admit(raw)
        self.assertEqual(error.exception.code, "E_SCHEMA_INVALID")
        self.assertEqual(h.calls, [])

    def test_preference_only_edit_reuses_semantics_under_still_current_source_grants(self):
        h = self.h
        h.split_semantic_scope()
        first = h.admit()
        packet = first.audience_packet()
        h.on_execute = h.edit_preference
        with self.assertRaises(ContractError) as edited:
            h.execute(first)
        self.assertEqual(edited.exception.code, "E_DEPENDENCY_STALE")
        h.on_execute = None
        with self.assertRaises(ContractError):
            first.require_current()
        second = h.admit()
        self.assertEqual(packet.state, second.audience_packet().state)
        reused = h.execute(second)
        self.assertEqual(reused["status"], "reused", reused)
        self.assertFalse(reused["dispatched"])
        self.assertEqual(len(h.calls), 1)
        self.assertEqual(first.source_packet.state["evidence"], second.source_packet.state["evidence"])


class MonitoringWireValidationTests(unittest.TestCase):
    def test_installed_validator_refuses_wrong_version_size_kind_and_extra_fields(self):
        request = json.loads((ROOT / "tests/fixtures/civic/handoff/client-a-request.json").read_text())
        self.assertEqual(validate_handoff(request), request)
        wrong = deepcopy(request)
        wrong["contract_version"] = "monitoring-handoff/999"
        extra = deepcopy(request)
        extra["client_notes"] = "SYNTHETIC-PRIVATE-CANARY"
        for value, kind, code in ((wrong, "request", "E_VERSION_UNSUPPORTED"),
                                  (b" " * 65537, "request", "E_SCHEMA_INVALID"),
                                  (request, "invalid", "E_POLICY_INVALID"),
                                  (extra, "request", "E_SCHEMA_INVALID")):
            with self.subTest(kind=kind, code=code), self.assertRaises(ContractError) as error:
                validate_handoff(value, kind)
            self.assertEqual(error.exception.code, code)

    def test_refusals_map_native_codes_without_leaking_details_or_invalid_correlation(self):
        for code, expected, reason in (("E_NOT_FOUND", "E_EVIDENCE_UNAVAILABLE", "source_unavailable"),
                                      ("E_STORAGE_UNAVAILABLE", "E_EVIDENCE_UNAVAILABLE", "source_unavailable"),
                                      ("E_BUDGET_EXHAUSTED", "E_BUDGET_EXHAUSTED", "resource_limit"),
                                      ("E_CANCELLED", "E_CANCELLED", "host_cancelled")):
            with self.subTest(code=code):
                wire = monitoring_refusal(ContractError(code, "SYNTHETIC-PRIVATE-DETAIL"), request_id="known-request")
                self.assertEqual((wire["code"], wire["reason"]), (expected, reason))
                self.assertNotIn("PRIVATE", str(wire))
        invalid = monitoring_refusal(ContractError("E_DELIVERY_UNKNOWN"), request_id="bad id\n")
        self.assertIsNone(invalid["request_id"])
        self.assertEqual(invalid["code"], "E_SCHEMA_INVALID")
        self.assertEqual(monitoring_refusal(ContractError("E_VERSION_UNSUPPORTED"))["code"], "E_VERSION_UNSUPPORTED")
