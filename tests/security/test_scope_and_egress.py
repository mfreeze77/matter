"""MAT-072: actual SQLite/core operations and synthetic sharing restrictions."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import logging
import unittest

from matter.access import AccessContext, AccessService, HostAccessPolicy
from matter.canonical import canonical_bytes, source_digest
from matter.contracts import ContractError
from matter.semantic import Batch, Capabilities, RawExecution
from matter.semantic.packets import PacketProfile, prepare_packet
from matter.semantic.questions import QuestionSpecification
from matter.semantic.rendering import render_question
from matter.executor import GraphExecutor
from matter.storage import SQLiteStore, entity_ref, pin

from control_helpers import control_command
from integration.helpers import _in_scope
from integration import test_assessment_commit as assessment_fixtures
from observation_helpers import observation_command
from rule_helpers import component


MARKER = "SYNTHETIC-RESTRICTED-CONTENT-7281"


class ScopeAndEgressTests(unittest.TestCase):
    def setUp(self):
        # Compose the existing real-core fixture without inheriting/rerunning its
        # separate assessment test collection.
        self.core = assessment_fixtures.AssessmentCommitTests("test_atomic_children_current_pointer_restart_and_exact_retry")
        self.core.setUp()
        self.addCleanup(self.core.doCleanups)
        self.live_reader = SQLiteStore(self.core.database, scope_id=self.core.storage.scope_id)
        self.addCleanup(self.live_reader.close)
        self.core.source = self.core.observe("restricted-source", payload=(MARKER + "\n").encode())
        self.audience = self.core.audience
        self.other_audience = component("more-restrictive-audience")
        self.provider = component("provider-a")
        self.other_provider = component("provider-b")
        self.access = self.make_access()

    def make_access(self, *, source_audiences=None, source_providers=None, extra=()):
        grants = [{"reference": pin(self.core.subject), "audiences": [self.audience, self.other_audience],
                   "providers": [self.provider, self.other_provider]},
                  {"reference": pin(self.core.source), "audiences": [self.audience] if source_audiences is None else source_audiences,
                   "providers": [self.provider] if source_providers is None else source_providers}, *extra]
        policy = HostAccessPolicy(scope_id=self.core.storage.scope_id, audiences=[self.audience, self.other_audience],
            providers=[{"reference": self.provider, "provider": "synthetic", "transport": "fixture"},
                       {"reference": self.other_provider, "provider": "other", "transport": "fixture"}], grants=grants)
        return AccessService(policy=policy, controls=self.core.controls, current_read=self.live_reader.snapshot)

    def context(self, *, access=None, audience=None, provider="default", references=None, token_references=None):
        references = [pin(self.core.subject), pin(self.core.source)] if references is None else references
        token = self.core.controls.capture(actor=self.core.actor, authority=entity_ref(self.core.authority),
            capability="assessment", targets=[entity_ref(ref) for ref in (references if token_references is None else token_references)])
        with self.core.storage.snapshot() as view:
            return (access or self.access).capture(view, token=token, audience=audience or self.audience,
                provider=self.provider if provider == "default" else provider, references=references)

    def packet(self, context, *, access=None, evidence=None):
        access = access or self.access
        profile = PacketProfile({"namespace": "example", "id": "access-test", "version": "1.0",
            "required_roles": [], "allowed_origins": ["source", "derived"], "locator_adapters": [self.core.adapter.reference],
            "max_sources": 16, "max_source_bytes": 65536, "max_packet_bytes": 262144})
        with self.core.storage.snapshot() as view:
            return prepare_packet(view, profile, payloads=self.core.payloads, scope_id=self.core.storage.scope_id,
                binding={"kind": "candidate_relation", "left": pin(self.core.source), "right": pin(self.core.source), "relation": "example:same_source"},
                as_of=self.core.now, coverage={"status": "complete", "snapshot": component("coverage")},
                evidence=[self.core.evidence()] if evidence is None else evidence, access=access, access_context=context)

    def render(self, context, packet):
        spec = QuestionSpecification({"schema_version": "1.0", "namespace": "example", "id": "access-test",
            "family": "example.access-test", "revision": "1.0", "primitive": "proposition_probability",
            "instructions": "Does {{evidence}} support the declared relation?",
            "criteria": {"true": "Support is present.", "false": "Support is absent."},
            "required_fields": [{"name": "evidence", "path": ["evidence"], "description": "Only eligible sources."}],
            "renderer": {"id": "canonical-json-bindings", "version": "1.0"}})
        with self.core.storage.snapshot() as view:
            return render_question(spec, packet.state, "access-question", source_manifest=packet.source_manifest,
                access=self.access, access_context=context, access_view=view)

    def batch(self, packet, rendered):
        return Batch({"schema_version": "1.0", "id": "access-batch", "scope_id": self.core.storage.scope_id,
            "run_id": "access-run", "stage_id": "access-stage", "state": packet.state, "packet_digest": packet.digest,
            "questions": [rendered.question.value], "context": {"provider": "synthetic", "transport": "fixture",
                "requested_model": "synthetic", "adapter_version": "1.0", "mode": "offline_fixture",
                "deadline": {**self.core.now, "value": "2026-10-10T13:00:00Z"}, "max_request_bytes": 262144, "max_response_bytes": 65536}})

    def executor(self, callback=None):
        calls = []
        class Spy:
            capabilities = Capabilities({"provider": "synthetic", "transport": "fixture", "adapter_version": "1.0",
                "primitives": ["proposition_probability"], "modes": ["offline_fixture"], "max_questions": 128,
                "max_request_bytes": 262144, "max_response_bytes": 65536})
            def execute(inner, batch):
                calls.append(batch.canonical)
                if callback:
                    callback()
                return RawExecution(b'{"answers":[{"id":"access-question","primitive":"proposition_probability","probability":"0.5"}],"resolved_model":"synthetic"}')
        return Spy(), calls

    def revoke(self, *, capability="read"):
        command = _in_scope(control_command("revoke-access-" + capability, self.core.authority,
            targets=[self.core.source], action="deny", capabilities=[capability], now=self.core.now), self.core.storage.scope_id)
        command["actor"] = self.core.actor
        command["body"]["control"]["body"]["actor"] = self.core.actor
        self.assertEqual(self.core.controls.apply(self.core.controls.prepare(command))["status"], "success")

    def prepare_assessment(self, context, *, definition=None):
        self.core.service.access = self.access
        request = self.core.request(audience=context.value["audience"])
        request["body"]["control_epoch"] = context.value["token"]["control_epoch"]
        queries = [] if definition is None else [{"definition": definition.reference,
            "records": {"source": pin(self.core.source), "subject": pin(self.core.subject)},
            "context": {}, "qualification_context": [], "citations": [], "negative_dependencies": []}]
        return self.core.service.prepare(request, token=context.value["token"], plan=self.core.plan,
            access_context=context, cache_queries=queries)

    def test_source_audience_provider_matrix_never_returns_denied_content_or_identifiers(self):
        output, errors, logs = io.StringIO(), io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        with redirect_stdout(output), redirect_stderr(errors):
            for audience in (self.audience, self.other_audience):
                for provider in (self.provider, self.other_provider):
                    with self.subTest(audience=audience["id"], provider=provider["id"]):
                        if audience == self.audience and provider == self.provider:
                            context = self.context(audience=audience, provider=provider)
                            packet = self.packet(context)
                            rendered = self.render(context, packet)
                            executor, calls = self.executor()
                            prepared = self.prepare_assessment(context)
                            result = self.access.dispatch(prepared.view, context, self.batch(packet, rendered), executor,
                                rendered_questions=[rendered], clock=lambda: self.core.now)
                            self.assertTrue(result.primitive_valid)
                            self.assertIn(MARKER.encode(), packet.canonical)
                            self.assertIn(MARKER.encode(), calls[0])
                        else:
                            with self.assertRaises(ContractError) as error:
                                self.context(audience=audience, provider=provider)
                            public = self.access.public_failure(error.exception)
                            self.assertEqual(public["status"], "forbidden")
                            serialized = canonical_bytes(public) + str(error.exception).encode()
                            self.assertNotIn(MARKER.encode(), serialized)
                            self.assertNotIn(self.core.source["id"].encode(), serialized)
        self.assertEqual(output.getvalue() + errors.getvalue() + logs.getvalue(), "")

    def test_cross_scope_reference_cannot_enter_actual_assessment_or_explanation(self):
        context = self.context()
        request = self.core.request()
        foreign = pin(self.core.source)
        foreign["scope_id"] = "foreign-scope"
        request["body"]["evidence"]["references"] = [foreign]
        self.core.service.access = self.access
        with self.assertRaises(ContractError) as error:
            self.core.service.prepare(request, token=context.value["token"], plan=self.core.plan, access_context=context)
        self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
        self.assertNotIn(MARKER, str(error.exception))
        prepared = self.prepare_assessment(context)
        command = self.core.command(prepared)
        result = self.core.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        with self.core.storage.snapshot() as view:
            explained = self.access.explain(view, context, result["body"]["assessment"])
            self.assertEqual(explained["status"], "permitted")
        self.revoke()
        with self.core.storage.snapshot() as view:
            with self.assertRaises(ContractError) as error:
                self.access.explain(view, context, result["body"]["assessment"])
        self.assertNotIn(MARKER, str(error.exception))
        for read in (lambda: self.core.service.current(self.core.subject, profile=self.core.profile.reference,
                         purpose=self.core.purpose, audience=self.audience),
                     lambda: self.core.service.attempt(command["idempotency_key"])):
            with self.assertRaises(ContractError) as denied:
                read()
            self.assertNotIn(MARKER, str(denied.exception))

    def test_revocation_between_packet_preparation_and_dispatch_stops_executor_even_with_frozen_view(self):
        context = self.context()
        prepared = self.prepare_assessment(context)
        packet = self.packet(context)
        rendered = self.render(context, packet)
        executor, calls = self.executor()
        self.revoke()
        with self.assertRaises(ContractError):
            self.access.dispatch(prepared.view, context, self.batch(packet, rendered), executor, rendered_questions=[rendered], clock=lambda: self.core.now)
        self.assertEqual(calls, [])
        with self.core.storage.snapshot() as view:
            with self.assertRaises(ContractError):
                render_question(QuestionSpecification({"schema_version": "1.0", "namespace": "example", "id": "refused",
                    "family": "example.test", "revision": "1.0", "primitive": "proposition_probability", "instructions": "Fixed question.",
                    "criteria": {"true": "Present.", "false": "Absent."}, "required_fields": [],
                    "renderer": {"id": "canonical-json-bindings", "version": "1.0"}}), packet.state, "denied",
                    access=self.access, access_context=context, access_view=view)

    def test_cached_hit_cannot_bypass_revocation_or_a_more_restrictive_audience(self):
        context = self.context()
        definition, cache = self.core.cache_fixture()
        cache.access = self.access
        self.core.service.cache = cache
        calls = []
        first = self.prepare_assessment(context, definition=definition)
        result = self.core.cache_compute(first, definition, cache, calls)
        self.assertEqual(self.core.service.commit(self.core.command(first, cache_entries=[result]))["status"], "success")
        second = self.prepare_assessment(context, definition=definition)
        hit = self.core.cache_compute(second, definition, cache, calls)
        self.assertTrue(hit.cache_hit)
        self.assertEqual(len(calls), 1)
        altered = context.value
        altered["audience"] = self.other_audience
        with self.core.storage.snapshot() as view:
            with self.assertRaises(ContractError):
                self.access.require_current(view, AccessContext(altered))
        self.revoke()
        with self.assertRaises(ContractError) as error:
            self.core.cache_compute(second, definition, cache, calls)
        self.assertEqual(len(calls), 1)
        self.assertNotIn(MARKER, str(error.exception))

    def test_derived_excerpt_inherits_stricter_actual_parent_egress(self):
        raw = ("Derived " + MARKER + "\n").encode()
        command = observation_command("derived-excerpt", "derived-excerpt", payload=raw,
            scope_id=self.core.storage.scope_id, event_id="derived-excerpt")
        command["body"]["observation"]["provenance"].update(origin="derived", parents=[pin(self.core.source)])
        result = self.core.ingestor.ingest(self.core.ingestor.prepare(command), payload=raw)
        self.assertEqual(result["status"], "success", result)
        child = self.core.storage.get(result["body"]["observation"])
        self.access = self.make_access(source_providers=[], extra=[{"reference": pin(child),
            "audiences": [self.audience], "providers": [self.provider]}])
        refs = [pin(child)]
        token_refs = [pin(child), pin(self.core.source)]
        with self.assertRaises(ContractError) as error:
            self.context(references=refs, token_references=token_refs)
        self.assertNotIn(MARKER, str(error.exception))
        local = self.context(references=refs, token_references=token_refs, provider=None)
        self.assertEqual(local.value["references"], refs)
        self.assertEqual(local.value["dependencies"], sorted(token_refs, key=canonical_bytes))

    def test_authorized_empty_forbidden_and_unavailable_are_distinct_and_safe(self):
        empty = self.context(references=[], provider=None)
        self.assertEqual(empty.status, "permitted_empty")
        with self.assertRaises(ContractError) as denied:
            self.context(audience=self.other_audience)
        missing = pin(self.core.source)
        missing["id"] = "unavailable-synthetic-source"
        service = self.make_access(extra=[{"reference": missing, "audiences": [self.audience], "providers": [self.provider]}])
        with self.assertRaises(ContractError) as unavailable:
            self.context(access=service, references=[missing])
        self.assertEqual(service.public_failure(denied.exception)["status"], "forbidden")
        self.assertEqual(service.public_failure(unavailable.exception)["status"], "unavailable")
        for error in (denied.exception, unavailable.exception):
            self.assertNotIn(MARKER, str(error))
            self.assertNotIn(missing["id"], json.dumps(service.public_failure(error)))

    def test_access_context_is_immutable_and_missing_installed_context_fails_closed(self):
        context = self.context()
        modified = context.value
        modified["audience"] = self.other_audience
        self.assertEqual(context.value["audience"], self.audience)
        with self.assertRaises(AttributeError):
            context.value = modified
        self.core.service.access = self.access
        with self.assertRaises(ContractError):
            self.core.service.prepare(self.core.request(), token=context.value["token"], plan=self.core.plan)
        packet = self.packet(context)
        changed = packet.state
        changed["access_context"] = component("invented-context")
        with self.core.storage.snapshot() as view:
            with self.assertRaises(ContractError):
                self.access.require_packet(view, context, changed)

    def test_exact_access_context_binds_packet_and_cache_identity(self):
        self.access = self.make_access(source_audiences=[self.audience, self.other_audience])
        first = self.context()
        second = self.context(audience=self.other_audience)
        self.assertNotEqual(first.reference, second.reference)
        self.assertNotEqual(self.packet(first).digest, self.packet(second).digest)
        definition, cache = self.core.cache_fixture()
        cache.access = self.access
        self.core.service.cache = cache
        prepared_first = self.prepare_assessment(first, definition=definition)
        prepared_second = self.prepare_assessment(second, definition=definition)
        self.assertNotEqual(prepared_first.cache_inputs[0].key, prepared_second.cache_inputs[0].key)

    def test_dispatch_refuses_changed_questions_and_unbound_provider_before_executor(self):
        context = self.context()
        packet = self.packet(context)
        rendered = self.render(context, packet)
        prepared = self.prepare_assessment(context)
        executor, calls = self.executor()
        for field in ("question", "provider"):
            raw = self.batch(packet, rendered).value
            if field == "question":
                raw["questions"][0]["instructions"] += " UNADMITTED-SYNTHETIC-FOREIGN-CONTENT"
            else:
                raw["context"]["provider"] = "other"
            with self.assertRaises(ContractError) as error:
                self.access.dispatch(prepared.view, context, Batch(raw), executor,
                    rendered_questions=[rendered], clock=lambda: self.core.now)
            self.assertNotIn("UNADMITTED", str(error.exception))
        self.assertEqual(calls, [])

    def test_actual_ineligible_node_input_is_refused_before_any_evaluation(self):
        denied = self.core.observe("ineligible-in-scope", payload=b"SYNTHETIC denied source body.\n")
        # Generic READ/assessment ceilings cover this source; only the specific
        # audience/provider access context excludes it. No wire bytes are edited.
        context = self.context(token_references=[pin(self.core.subject), pin(self.core.source), pin(denied)])
        prepared = self.prepare_assessment(context)
        self.core.controls.check(context.value["token"])
        with self.core.storage.snapshot() as view:
            material = self.core.packet(self.core.rule_instance, view=view, subject=pin(self.core.subject),
                control_token=context.value["token"], evidence=[self.core.evidence(denied)], as_of=self.core.now)
        self.assertIn(pin(denied), material.value["packet"]["dependencies"]["positive"])
        with self.assertRaises(ContractError) as error:
            self.core.service.check_current(prepared, material, as_of=self.core.now)
        self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")
        runner = self.core.runner([self.core.rule_instance], [self.core.binding_instance], clock=lambda: self.core.now)
        graph = GraphExecutor(runner, clock=lambda: self.core.now).execute(self.core.plan,
            prepare=lambda name, upstream: material, run_id="untampered-ineligible", max_workers=1,
            check_current=lambda value, as_of: self.core.service.check_current(prepared, value, as_of=as_of),
            check_control=self.core.controls.check)
        events = graph.value["nodes"]["evidence"]["attempt_receipt"]["body"]["details"]["value"]["events"]
        self.assertIn({"stage": "pre_gate", "status": "failed", "code": "E_AUTHORITY_REQUIRED"}, events)
        self.assertEqual(graph.value["resource_reservations"]["actual_invocations"], 0)
        self.assertEqual(self.core.calls, [])

    def test_duplicate_dependency_occurrences_do_not_spend_unique_source_budget(self):
        context = self.context()
        with self.core.storage.snapshot() as view:
            checked = self.access.require_current(view, context, references=[pin(self.core.source)] * 1024)
        self.assertEqual(checked.reference, context.reference)
        conflicting = pin(self.core.source)
        conflicting["digest"] = "f" * 64
        with self.core.storage.snapshot() as view:
            with self.assertRaises(ContractError):
                self.access.require_current(view, context, references=[pin(self.core.source), conflicting])

    def test_actual_host_context_projection_requires_its_own_exact_grant(self):
        from matter.contexts import ContextDefinition, ContextService, context_ref
        definition = ContextDefinition({"schema_version": "1.0", "namespace": "example:contexts", "id": "access-audience",
            "semantic_version": "1.0", "kind": "audience", "description": "Synthetic audience metadata.",
            "applies_to": [entity_ref(self.core.subject)], "effective_from": self.core.now,
            "effective_until": {"state": "unknown", "reason": "not_applicable"},
            "content": {"audience_id": "synthetic-audience", "audience_kind": "human", "purposes": [],
                        "responsibilities": [], "preferences": []}})
        service = ContextService(self.core.storage, controls=self.core.controls)
        result = service.commit(service.prepare(definition, command_id="access-context-metadata", idempotency_key="access-context-metadata",
            actor=self.core.actor, authority=entity_ref(self.core.authority)))
        self.assertEqual(result["status"], "success", result)
        metadata = self.core.storage.get(context_ref(self.core.storage.scope_id, definition))
        self.assertNotIn("provenance", metadata)
        granted = self.make_access(extra=[{"reference": pin(metadata), "audiences": [self.audience], "providers": [self.provider]}])
        admitted = self.context(access=granted, references=[pin(metadata)])
        self.assertEqual(admitted.value["dependencies"], [pin(metadata)])
        with self.assertRaises(ContractError) as error:
            self.context(references=[pin(metadata)])
        self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")

    def test_stale_and_cancelled_controls_keep_safe_distinct_public_outcomes(self):
        context = self.context()
        prepared = self.prepare_assessment(context)
        command = self.core.command(prepared)
        for identity, action, expected, status in (("benign-correction", "invalidate", "E_DEPENDENCY_STALE", "stale"),
                                                    ("explicit-cancel", "cancel", "E_CANCELLED", "cancelled")):
            control = _in_scope(control_command(identity, self.core.authority, targets=[self.core.source], action=action,
                now=self.core.now), self.core.storage.scope_id)
            control["actor"] = self.core.actor
            control["body"]["control"]["body"]["actor"] = self.core.actor
            self.assertEqual(self.core.controls.apply(self.core.controls.prepare(control))["status"], "success")
            with self.core.storage.snapshot() as view:
                with self.assertRaises(ContractError) as error:
                    self.access.require_current(view, context)
            self.assertEqual(error.exception.code, expected)
            self.assertEqual(self.access.public_failure(error.exception)["status"], status)
            self.assertNotIn(MARKER, str(error.exception))
            if action == "invalidate":
                result = self.core.service.commit(command)
                self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE", result)
                self.assertEqual(self.core.service.attempt(command["idempotency_key"])["result"], result)

    def test_success_history_survives_benign_revision_but_not_present_grant_revocation(self):
        context = self.context()
        prepared = self.prepare_assessment(context)
        command = self.core.command(prepared)
        result = self.core.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        assessment = self.core.storage.get(result["body"]["assessment"])
        original_subject = pin(self.core.subject)
        self.core.rename_subject()
        self.assertEqual(self.core.service.attempt(command["idempotency_key"])["result"], result)
        self.assertEqual(source_digest(self.core.service.input_artifact(command["idempotency_key"])),
            assessment["body"]["input_artifact"]["digest"])
        # Current host grants, not the old policy digest, govern historical READ.
        old_grant = {"reference": original_subject, "audiences": [self.audience], "providers": [self.provider]}
        self.access.policy = self.make_access(extra=[old_grant]).policy
        self.assertEqual(self.core.service.attempt(command["idempotency_key"])["result"], result)
        self.access.policy = self.make_access(source_audiences=[], extra=[old_grant]).policy
        with self.assertRaises(ContractError) as error:
            self.core.service.attempt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")

    def test_failed_stale_attempt_and_artifact_remain_readable_until_read_revocation(self):
        context = self.context()
        prepared = self.prepare_assessment(context)
        command = self.core.command(prepared)
        original_bytes = canonical_bytes({"preparation": prepared.value,
            "inputs": command["extensions"]["matter:assessment_publication"]["value"]["graph"]["inputs"]})
        self.core.rename_subject()
        result = self.core.service.commit(command)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE", result)
        self.assertEqual(self.core.service.attempt(command["idempotency_key"])["result"], result)
        self.assertEqual(self.core.service.input_artifact(command["idempotency_key"]), original_bytes)
        self.revoke()
        with self.assertRaises(ContractError) as error:
            self.core.service.attempt(command["idempotency_key"])
        self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")

    def test_fresh_access_capture_time_does_not_defeat_timeless_cache_reuse(self):
        first_context = self.context()
        definition, cache = self.core.cache_fixture()
        cache.access = self.access
        self.core.service.cache = cache
        calls = []
        first = self.prepare_assessment(first_context, definition=definition)
        original = self.core.cache_compute(first, definition, cache, calls)
        self.assertEqual(self.core.service.commit(self.core.command(first, cache_entries=[original]))["status"], "success")
        self.core.now = {**self.core.now, "value": "2026-10-10T12:10:00Z"}
        fresh_context = self.context()
        self.assertNotEqual(first_context.reference, fresh_context.reference)
        self.assertEqual(first_context.eligibility_reference, fresh_context.eligibility_reference)
        second = self.prepare_assessment(fresh_context, definition=definition)
        self.assertEqual(first.cache_inputs[0].key, second.cache_inputs[0].key)
        hit = self.core.cache_compute(second, definition, cache, calls)
        self.assertTrue(hit.cache_hit)
        self.assertEqual(len(calls), 1)
        self.assertEqual(hit.entry["source_attempt_id"], original.entry["source_attempt_id"])
        self.revoke()
        with self.assertRaises(ContractError):
            self.core.cache_compute(second, definition, cache, calls)
        self.assertEqual(len(calls), 1)

    def test_response_is_not_returned_if_access_is_revoked_during_injected_execution(self):
        context = self.context()
        packet = self.packet(context)
        rendered = self.render(context, packet)
        executor, calls = self.executor(lambda: self.revoke())
        prepared = self.prepare_assessment(context)
        with self.assertRaises(ContractError) as error:
            self.access.dispatch(prepared.view, context, self.batch(packet, rendered), executor,
                rendered_questions=[rendered], clock=lambda: self.core.now)
        self.assertEqual(len(calls), 1)
        self.assertNotIn(MARKER, str(error.exception))


if __name__ == "__main__":
    unittest.main()
