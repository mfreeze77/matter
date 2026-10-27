"""MAT-072: actual SQLite/core operations and synthetic sharing restrictions."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import logging
import unittest

from matter.access import AccessContext, AccessService, HostAccessPolicy
from matter.canonical import canonical_bytes
from matter.contracts import ContractError
from matter.semantic import Batch, Capabilities, RawExecution
from matter.semantic.packets import PacketProfile, prepare_packet
from matter.semantic.questions import QuestionSpecification
from matter.semantic.rendering import render_question
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

    def context(self, *, access=None, audience=None, provider="default", references=None):
        references = [pin(self.core.subject), pin(self.core.source)] if references is None else references
        token = self.core.controls.capture(actor=self.core.actor, authority=entity_ref(self.core.authority),
            capability="assessment", targets=[entity_ref(ref) for ref in references])
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
        refs = [pin(self.core.source), pin(child)]
        with self.assertRaises(ContractError) as error:
            self.context(references=refs)
        self.assertNotIn(MARKER, str(error.exception))
        local = self.context(references=refs, provider=None)
        self.assertEqual(local.value["dependencies"], sorted(refs, key=canonical_bytes))

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

    def test_otherwise_valid_rule_attempt_cannot_publish_a_foreign_source_reference(self):
        from matter.assessments import PUBLICATION_EXTENSION
        context = self.context()
        prepared = self.prepare_assessment(context)
        command = self.core.command(prepared)
        material = command["extensions"][PUBLICATION_EXTENSION]["value"]["graph"]["inputs"]["evidence"]
        material["packet"]["evidence"][0]["reference"]["scope_id"] = "foreign-scope"
        with self.assertRaises(ContractError) as error:
            self.core.service.commit(command)
        self.assertNotIn(MARKER, str(error.exception))
        self.assertIsNone(self.core.service.current(self.core.subject, profile=self.core.profile.reference,
            purpose=self.core.purpose, audience=self.audience))

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
