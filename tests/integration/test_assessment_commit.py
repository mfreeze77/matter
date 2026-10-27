"""Real scoped SQLite publication and declared semantic cache behavior (MAT-015)."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
import unittest

from matter.assessments import AssessmentService, PUBLICATION_EXTENSION
from matter.authority import AuthorityPolicy, CAPABILITIES, CONTROL_KINDS
from matter.cache import SemanticCache, SemanticComputationDefinition, cache_ref
from matter.canonical import source_digest
from matter.controls import ControlService, command_targets
from matter.contracts import ContractError
from matter.evaluators import BindingRegistry, QualificationRegistry, RecordedBinding, prepare_input
from matter.executor import GraphExecutor
from matter.planner import RulePlan
from matter.profiles import ProfileDefinition, ProfileRegistry
from matter.rules import RuleRegistry
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from claim_helpers import claim_command, relation_command, acceptance_command
from control_helpers import control_command
from integration.helpers import _in_scope, create_command, domain_value, fixture, record_input
from matter_helpers import metadata_command
from rule_helpers import RuleTestCase, NOW, LATE, component


class AssessmentCommitTests(RuleTestCase):
    def setUp(self):
        super().setUp()
        self.now = deepcopy(NOW)
        self.actor = {"scope_id": self.storage.scope_id, "namespace": "example:host", "id": "assessment-operator"}
        command = create_command("authority-bootstrap", "authority-bootstrap-subject", scope_id=self.storage.scope_id)
        authority = record_input("receipt", "assessment-authority", scope_id=self.storage.scope_id)
        authority["namespace"] = "example:host"
        authority["provenance"]["origin"] = "host"
        authority["body"].update(stage="authority", operation_id=command["command_id"], outcome="example:granted", evidence=[],
                                 details=domain_value({"synthetic": "explicit host authority fixture"}))
        def bootstrap(tx):
            tx.insert(authority)
            stored = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(stored)})
        self.assertEqual(self.storage.execute(command, bootstrap)["status"], "success")
        self.authority = self.storage.get(entity_ref(authority))
        policy = AuthorityPolicy(self.storage.scope_id, actors=[self.actor], authorities=[pin(self.authority)],
                                 capabilities=CAPABILITIES, control_kinds=CONTROL_KINDS)
        self.controls = ControlService(self.storage, policy=policy, clock=lambda: deepcopy(self.now))
        self.binding_instance = self.binding()
        self.rule_instance = self.rule(self.binding_instance)
        self.rules = RuleRegistry([self.rule_instance])
        self.bindings = BindingRegistry([self.binding_instance])
        self.profile = self.make_profile(self.rule_instance)
        self.profiles = ProfileRegistry([self.profile])
        self.plan = RulePlan(self.profile, rules=self.rules, schemas=self.schemas, nodes={"evidence": self.rule_instance.reference})
        self.service = self.make_service()
        self.purpose, self.audience = component("purpose"), component("audience-a")
        self.sequence = 0

    def make_profile(self, rule, *, identity="assessment-policy", version="1.0", description="Synthetic assessment policy."):
        limits = deepcopy(rule.value["resource_limits"])
        limits.pop("max_retries")
        component_value = {"semantic_version": version, "description": description, "rules": [rule.reference],
            "parameters": {}, "dependencies": [], "outputs": [{"name": "example:conclusion", "rule": rule.reference,
                "schema": rule.value["output_schema"], "accepted_labels": ["example:positive"], "accepted_statuses": ["applicable"]}],
            "data_scopes": [self.storage.scope_id], "capabilities": rule.value["consequence_permissions"],
            "conflict_resolvers": [rule.value["conflict_policy"]], "resource_limits": limits, "lifecycle_extensions": [],
            "conformance_cases": [{"name": "bounded", "invariant": "Only an admitted declared result is current."}]}
        return ProfileDefinition({"schema_version": "1.0", "namespace": "example", "profile_id": identity,
            "semantic_version": version, "description": description, "components": {"evidence": component_value},
            "required_outputs": ["example:conclusion"], "resource_limits": limits, "incomplete_evaluation": "retain_unresolved"},
            rules=RuleRegistry([rule]), schemas=self.schemas, allowed_data_scopes=[self.storage.scope_id],
            allowed_capabilities=rule.value["consequence_permissions"], conflict_resolvers=[rule.value["conflict_policy"]])

    def make_service(self, *, storage=None, profiles=None, cache=None, qualifications=None):
        return AssessmentService(storage or self.storage, profiles=profiles or self.profiles, rules=self.rules,
            bindings=self.bindings, schemas=self.schemas, controls=self.controls, clock=lambda: deepcopy(self.now),
            cache=cache, qualifications=qualifications)

    def request(self, *, profile=None, audience=None, evidence=(), assessed_as_of=None):
        self.sequence += 1
        command = _in_scope(fixture("commands/assess.json"), self.storage.scope_id)
        command.update(command_id=f"assess-{self.sequence}", idempotency_key=f"assess-key-{self.sequence}",
                       actor=self.actor, authority=entity_ref(self.authority), expected_revisions=[])
        command["body"].update(matter=pin(self.subject), profile=(profile or self.profile).reference,
            purpose=self.purpose, audience=audience or self.audience, assessed_as_of=assessed_as_of or deepcopy(self.now),
            evidence={"references": [pin(self.source), *evidence], "omitted": [],
                      "coverage": {"status": "complete", "snapshot": component("coverage")}},
            control_epoch=0, budget={"max_calls": 8, "max_candidates": 16, "max_bytes": 2097152,
                "max_elapsed_ms": 10000, "max_cost": "0", "cost_unit": "example:currency"})
        return command

    def prepare(self, *, request=None, service=None, plan=None, extra=(), cache_context=(), negative=(), control_contexts=()):
        service = service or self.service
        request = request or self.request()
        scoped_request = deepcopy(request)
        scoped_request["expected_revisions"] = [*request["expected_revisions"], *extra]
        targets = command_targets(scoped_request)
        token = self.controls.capture(actor=self.actor, authority=entity_ref(self.authority), capability="assessment", targets=targets)
        request["body"]["control_epoch"] = token["control_epoch"]
        queries = []
        if service.cache is not None:
            for definition in service.cache.definitions:
                roles = {item["record"] for item in definition.value["fields"]}
                records = {role: pin(self.subject if role == "subject" else self.source) for role in roles}
                queries.append({"definition": definition.reference, "records": records,
                    "context": {"audience": request["body"]["audience"], "delivery_wrapper": "must_not_reach_compute"},
                    "qualification_context": list(cache_context), "citations": [], "negative_dependencies": []})
        return service.prepare(request, token=token, plan=plan or self.plan, extra_dependencies=extra, cache_queries=queries,
                               negative_dependencies=negative, control_contexts=control_contexts)

    def graph_run(self, prepared, *, binding=None, rule=None, runner=None, unavailable_node=None):
        rule = rule or self.rule_instance
        runner = runner or self.runner([self.rules.resolve(ref) for ref in self.plan.value["nodes"].values()],
            [binding or self.binding_instance], qualifications=self.service.qualifications, clock=lambda: deepcopy(self.now))
        def build(name, upstream):
            if name == unavailable_node:
                raise StorageError("E_EVIDENCE_UNAVAILABLE", "Synthetic unavailable independent graph input.")
            return prepare_input(prepared.view, rule, schemas=self.schemas, scope_id=self.storage.scope_id,
                proposition={"schema": self.input_schema.reference, "value": {"enabled": True}},
                evidence=[self.evidence()], coverage={"status": "complete", "snapshot": component("coverage")},
                as_of=prepared.value["request"]["body"]["assessed_as_of"], subject=pin(self.subject), control_token=prepared.token,
                context=[] if rule.value["qualification_requirement"]["kind"] == "deterministic" else [component("task-scope")])
        return GraphExecutor(runner, clock=lambda: deepcopy(self.now)).execute(self.plan, prepare=build,
            run_id="graph-" + prepared.value["request"]["command_id"], max_workers=1,
            check_current=lambda material, as_of: self.service.check_current(prepared, material, as_of=as_of),
            check_control=self.controls.check)

    def command(self, prepared, run=None, *, service=None, interpretations=(), cache_entries=()):
        service = service or self.service
        run = run or self.graph_run(prepared)
        suffix = prepared.value["request"]["command_id"]
        return service.prepare_commit(prepared, run, command_id="commit-" + suffix, idempotency_key="key-commit-" + suffix,
            assessment_id="assessment-" + suffix, interpretations=interpretations, cache_entries=cache_entries)

    def publish(self, **options):
        prepared = self.prepare(**options)
        command = self.command(prepared)
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        return prepared, command, self.storage.get(result["body"]["assessment"])

    def rename_subject(self, title="Changed synthetic title."):
        current = self.storage.get(entity_ref(self.subject))
        command = metadata_command("rename-" + str(current["revision"]), current,
            {"title": title, "extensions": {}})
        result = self.matters.update_metadata(self.matters.prepare(command))
        self.assertEqual(result["status"], "success", result)
        self.subject = self.storage.get(entity_ref(self.subject))

    def test_atomic_children_current_pointer_restart_and_exact_retry(self):
        prepared, command, stored = self.publish()
        self.assertEqual(len(stored["body"]["judgments"]), 1)
        judgment = self.storage.get(stored["body"]["judgments"][0])
        attempt = self.storage.get(judgment["body"]["attempt_receipts"][0])
        self.assertEqual(judgment["creation_receipt"], stored["creation_receipt"])
        self.assertEqual(attempt["creation_receipt"], stored["creation_receipt"])
        self.assertEqual(command["body"]["assessment"]["body"]["judgments"], [])
        self.assertEqual(source_digest(self.service.input_artifact(command["idempotency_key"])), stored["body"]["input_artifact"]["digest"])
        with SQLiteStore(self.database, scope_id=self.storage.scope_id) as restarted:
            service = self.make_service(storage=restarted)
            self.assertEqual(service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience), stored)
            self.assertEqual(service.commit(command), self.service.attempt(command["idempotency_key"])["result"])

    def test_stale_matter_attempt_is_durable_and_never_current(self):
        prepared = self.prepare()
        command = self.command(prepared)
        self.rename_subject()
        result = self.service.commit(command)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        journal = self.service.attempt(command["idempotency_key"])
        self.assertEqual(journal["command"]["extensions"][PUBLICATION_EXTENSION]["value"]["graph"]["nodes"]["evidence"]["judgment"],
                         command["extensions"][PUBLICATION_EXTENSION]["value"]["graph"]["nodes"]["evidence"]["judgment"])
        self.assertEqual(self.service.commit(command), result)
        self.assertIsNone(self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience))

    def test_two_profile_identities_have_independent_current_lanes(self):
        other_profile = self.make_profile(self.rule_instance, identity="other-policy")
        self.profiles = ProfileRegistry([self.profile, other_profile])
        self.service = self.make_service()
        _, _, first = self.publish()
        other_plan = RulePlan(other_profile, rules=self.rules, schemas=self.schemas, nodes={"evidence": self.rule_instance.reference})
        prepared = self.prepare(request=self.request(profile=other_profile), plan=other_plan)
        original_plan = self.plan
        self.plan = other_plan
        try:
            command = self.command(prepared)
        finally:
            self.plan = original_plan
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        second = self.storage.get(result["body"]["assessment"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience)["id"], first["id"])
        self.assertEqual(self.service.current(self.subject, profile=other_profile.reference, purpose=self.purpose, audience=self.audience)["id"], second["id"])

    def test_real_evidence_acceptance_race_retains_noncurrent_attempt(self):
        claim_result = self.claims.append(self.claims.prepare(claim_command("claim-for-race", "race-claim", self.subject, self.source)))
        claim = self.storage.get(claim_result["body"]["claim"])
        relation_result = self.relations.relate(self.relations.prepare(relation_command("relation-for-race", "race-relation", claim, self.source)))
        relation = self.storage.get(relation_result["body"]["relation"])
        entered, release = Event(), Event()
        original = self.binding_instance
        def pause(request):
            entered.set()
            if not release.wait(10):
                raise TimeoutError()
            return self.response()
        binding = self.binding(pause)
        self.binding_instance = binding
        self.bindings = BindingRegistry([binding])
        self.service.bindings = self.bindings
        prepared = self.prepare(request=self.request(evidence=[pin(relation)]), extra=[pin(claim)])
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.graph_run, prepared)
            self.assertTrue(entered.wait(10))
            writer = SQLiteStore(self.database, scope_id=self.storage.scope_id)
            self.addCleanup(writer.close)
            from matter.evidence_relations import EvidenceRelationService
            changes = EvidenceRelationService(writer, locator_adapter=self.adapter)
            change = acceptance_command("withdraw-during-evaluation", relation, "rejected")
            changed = changes.revise_acceptance(changes.prepare(change))
            self.assertEqual(changed["status"], "success", changed)
            release.set()
            run = future.result(10)
        command = self.command(prepared, run)
        result = self.service.commit(command)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.service.attempt(command["idempotency_key"])["result"], result)
        self.assertIsNone(self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience))

    def test_policy_change_and_new_source_have_distinct_causes(self):
        self.publish()
        replacement = self.make_profile(self.rule_instance, version="2.0", description="Revised synthetic policy meaning.")
        self.profiles = ProfileRegistry([self.profile, replacement])
        self.service = self.make_service()
        self.profile = replacement
        self.plan = RulePlan(replacement, rules=self.rules, schemas=self.schemas, nodes={"evidence": self.rule_instance.reference})
        _, _, changed_policy = self.publish()
        self.assertEqual(changed_policy["body"]["causes"], ["policy_change"])
        self.source = self.observe("source-b")
        _, _, changed_source = self.publish()
        self.assertEqual(changed_source["body"]["causes"], ["new_evidence"])
        self.assertEqual(changed_policy["body"]["evidence_selection"]["references"][0]["id"], "source-a")

    def test_current_refuses_old_profile_version_without_hiding_history(self):
        _, command, old = self.publish()
        old_profile = self.profile
        self.profile = self.make_profile(self.rule_instance, version="2.0")
        self.profiles = ProfileRegistry([old_profile, self.profile])
        self.service = self.make_service()
        self.plan = RulePlan(self.profile, rules=self.rules, schemas=self.schemas, nodes={"evidence": self.rule_instance.reference})
        self.publish()
        with self.assertRaises(StorageError) as error:
            self.service.current(self.subject, profile=old_profile.reference, purpose=self.purpose, audience=self.audience)
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.assertEqual(self.storage.get(pin(old)), old)
        self.assertEqual(self.service.commit(command)["status"], "success")

    def test_current_rechecks_source_changes_before_general_invalidation_exists(self):
        _, _, old = self.publish()
        self.rename_subject()
        with self.assertRaises(StorageError) as error:
            self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience)
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.assertEqual(self.storage.get(pin(old)), old)

    def test_competing_publications_have_one_current_and_one_durable_stale_refusal(self):
        first, second = self.prepare(), self.prepare()
        one, two = self.command(first), self.command(second)
        self.assertEqual(self.service.commit(one)["status"], "success")
        result = self.service.commit(two)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.service.attempt(two["idempotency_key"])["result"], result)
        self.assertEqual(self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience)["id"],
                         one["body"]["assessment"]["id"])

    def test_tampered_propositions_child_pins_and_schema_do_not_publish(self):
        prepared = self.prepare()
        command = self.command(prepared)
        modifications = (
            lambda c: c["body"]["assessment"]["body"].update(causes=["policy_change"]),
            lambda c: c["body"]["assessment"]["body"]["judgments"].append({"scope_id": self.storage.scope_id,
                "namespace": "example", "record_type": "judgment", "id": "unearned-result", "digest": "b" * 64}),
            lambda c: c["extensions"][PUBLICATION_EXTENSION]["schema"].update(digest="f" * 64),
        )
        for change in modifications:
            corrupted = deepcopy(command)
            change(corrupted)
            with self.assertRaises(StorageError):
                self.service.commit(corrupted)
        self.assertIsNone(self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience))

    def test_original_control_change_is_not_renewed_by_new_equal_epoch_token(self):
        prepared = self.prepare()
        command = self.command(prepared)
        correction = _in_scope(control_command("invalidate-original-work", self.authority, targets=[self.subject],
            action="invalidate", now=self.now), self.storage.scope_id)
        correction["actor"] = self.actor
        correction["body"]["control"]["body"]["actor"] = self.actor
        result = self.controls.apply(self.controls.prepare(correction))
        self.assertEqual(result["status"], "success", result)
        fresh = self.controls.capture(actor=self.actor, authority=entity_ref(self.authority), capability="assessment",
            targets=[entity_ref(self.subject), entity_ref(self.source)])
        self.assertNotEqual(fresh, prepared.token)
        result = self.service.commit(command)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.service.attempt(command["idempotency_key"])["result"], result)

    def cache_fixture(self, *, audience_sensitive=False, title_sensitive=False, boundaries=(), rule=None, binding=None, qualifications=None):
        rule, binding = rule or self.rule_instance, binding or self.binding_instance
        definition = SemanticComputationDefinition({"namespace": "example", "id": "semantic-projection-" + str(audience_sensitive) + str(title_sensitive),
            "version": "1.0", "rule": rule.reference, "binding": binding.reference,
            "preparation": rule.value["evidence_preparation"],
            "fields": [{"name": "source_digest", "record": "source", "pointer": "/body/content/digest"},
                {"name": "subject_value", "record": "subject", "pointer": "/body/title" if title_sensitive else "/body/domain_kind"}],
            "context_fields": [{"name": "audience", "pointer": "/audience"}] if audience_sensitive else [],
            "time_boundaries": list(boundaries)}, rules=RuleRegistry([rule]), bindings=BindingRegistry([binding]))
        cache = SemanticCache(definitions=[definition], rules=RuleRegistry([rule]), bindings=BindingRegistry([binding]),
            schemas=self.schemas, controls=self.controls, qualifications=qualifications)
        return definition, cache

    def cache_compute(self, prepared, definition, cache, calls, *, label="example:positive", status="applicable", qualification=None):
        request = next(value for value in prepared.cache_inputs if value.value["definition"] == definition.reference)
        def compute(projected):
            calls.append(deepcopy(projected))
            return {"response": self.response(label=label, status=status, qualification=qualification),
                    "raw_result": {"state": "not_applicable", "reason": "Synthetic local computation."}}
        result = cache.get_or_compute(prepared.view, request, compute=compute, attempt_id="cache-attempt-" + str(self.sequence), as_of=self.now)
        return result

    def test_audience_independent_cache_reuses_but_sensitive_projection_recomputes(self):
        for sensitive in (False, True):
            definition, cache = self.cache_fixture(audience_sensitive=sensitive)
            self.service.cache = cache
            calls = []
            first = self.prepare(request=self.request(audience=component("audience-first-" + str(sensitive))))
            result = self.cache_compute(first, definition, cache, calls)
            command = self.command(first, cache_entries=[result])
            self.assertEqual(self.service.commit(command)["status"], "success")
            stored_cache = self.storage.get(cache_ref(self.storage.scope_id, result.entry["key"]))
            second_audience = component("audience-second-" + str(sensitive))
            second = self.prepare(request=self.request(audience=second_audience), extra=[pin(stored_cache)])
            result2 = self.cache_compute(second, definition, cache, calls)
            self.assertEqual(len(calls), 2 if sensitive else 1)
            self.assertEqual(result2.cache_hit, not sensitive)
            self.assertNotIn("delivery_wrapper", str(calls))
            if not sensitive:
                self.assertEqual(result2.value["source_attempt_id"], result.value["source_attempt_id"])

    def test_title_only_change_reuses_only_title_independent_computation(self):
        for sensitive in (False, True):
            definition, cache = self.cache_fixture(title_sensitive=sensitive)
            self.service.cache = cache
            calls = []
            first = self.prepare(request=self.request(audience=component("title-first-" + str(sensitive))))
            result = self.cache_compute(first, definition, cache, calls)
            self.assertEqual(self.service.commit(self.command(first, cache_entries=[result]))["status"], "success")
            cached = self.storage.get(cache_ref(self.storage.scope_id, result.entry["key"]))
            self.rename_subject("Title changed " + str(sensitive))
            second = self.prepare(request=self.request(audience=component("title-second-" + str(sensitive))), extra=[pin(cached)])
            result2 = self.cache_compute(second, definition, cache, calls)
            self.assertEqual(len(calls), 2 if sensitive else 1)
            self.assertEqual(result2.cache_hit, not sensitive)

    def test_clock_movement_reuses_timeless_support_but_deadline_class_changes(self):
        deadline = {**NOW, "value": "2026-10-10T13:00:00Z"}
        for boundaries in ((), (deadline,)):
            self.now = deepcopy(NOW)
            definition, cache = self.cache_fixture(boundaries=boundaries)
            self.service.cache = cache
            calls = []
            first = self.prepare(request=self.request(audience=component("clock-first-" + str(bool(boundaries)))))
            result = self.cache_compute(first, definition, cache, calls)
            self.assertEqual(self.service.commit(self.command(first, cache_entries=[result]))["status"], "success")
            cached = self.storage.get(cache_ref(self.storage.scope_id, result.entry["key"]))
            self.now = deepcopy(deadline)
            second = self.prepare(request=self.request(audience=component("clock-second-" + str(bool(boundaries)))), extra=[pin(cached)])
            result2 = self.cache_compute(second, definition, cache, calls)
            self.assertEqual(len(calls), 2 if boundaries else 1)
            self.assertEqual(result2.cache_hit, not boundaries)

    def test_same_lane_cache_deadline_crossing_is_temporal_transition_without_evidence_change(self):
        deadline = {**NOW, "value": "2026-10-10T13:00:00Z"}
        definition, cache = self.cache_fixture(boundaries=[deadline])
        self.service.cache = cache
        calls = []
        first = self.prepare()
        first_result = self.cache_compute(first, definition, cache, calls)
        published = self.service.commit(self.command(first, cache_entries=[first_result]))
        self.assertEqual(published["status"], "success", published)
        prior = self.storage.get(published["body"]["assessment"])
        original_cache = self.storage.get(cache_ref(self.storage.scope_id, first_result.entry["key"]))
        self.now = deepcopy(deadline)
        second = self.prepare()
        second_result = self.cache_compute(second, definition, cache, calls)
        self.assertFalse(second_result.cache_hit)
        self.assertEqual(len(calls), 2)
        command = self.command(second, cache_entries=[second_result])
        self.assertEqual(command["body"]["assessment"]["body"]["causes"], ["temporal_transition"])
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        current = self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience)
        self.assertEqual(current["body"]["evidence_selection"], prior["body"]["evidence_selection"])
        self.assertEqual(current["body"]["causes"], ["temporal_transition"])
        self.assertEqual([change["cause"] for change in current["body"]["material_changes"]], ["temporal_transition"])
        self.assertEqual(current["body"]["prior_assessment"], pin(prior))
        self.assertEqual(self.storage.get(pin(prior)), prior)
        self.assertEqual(self.storage.get(pin(original_cache)), original_cache)

    def test_same_lane_added_cache_query_at_same_cut_is_not_temporal_transition(self):
        _, _, prior = self.publish()
        definition, cache = self.cache_fixture()
        self.service.cache = cache
        calls = []
        prepared = self.prepare()
        cached = self.cache_compute(prepared, definition, cache, calls)
        command = self.command(prepared, cache_entries=[cached])
        self.assertEqual(command["body"]["assessment"]["body"]["causes"], ["evidence_correction"])
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        current = self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience)
        self.assertEqual(current["body"]["causes"], ["evidence_correction"])
        self.assertEqual(current["body"]["assessed_as_of"], prior["body"]["assessed_as_of"])
        self.assertEqual(current["body"]["evidence_selection"], prior["body"]["evidence_selection"])
        self.assertEqual(current["body"]["prior_assessment"], pin(prior))
        self.assertEqual(self.storage.get(pin(prior)), prior)
        self.assertEqual(len(calls), 1)

    def test_cached_unknown_stays_unknown_and_does_not_invent_a_source_attempt(self):
        recorded = self.recorded(identity="unknown-cache-model")
        rule = self.rule(recorded)
        definition, cache = self.cache_fixture(rule=rule, binding=recorded)
        self.service.cache = cache
        calls = []
        first = self.prepare(cache_context=[component("task-scope")])
        result = self.cache_compute(first, definition, cache, calls, label="example:unknown", status="insufficient_evidence")
        self.assertEqual(self.service.commit(self.command(first, cache_entries=[result]))["status"], "success")
        second = self.prepare(request=self.request(audience=component("unknown-second")), cache_context=[component("task-scope")])
        reused = self.cache_compute(second, definition, cache, calls)
        self.assertTrue(reused.cache_hit)
        self.assertEqual(len(calls), 1)
        self.assertEqual(reused.response["evaluation_status"], "insufficient_evidence")
        self.assertEqual(reused.response["semantic_output"]["value"]["label"], "example:unknown")
        self.assertEqual(reused.response["qualification"]["status"], "unknown")
        self.assertEqual(reused.value["source_attempt_id"], result.value["source_attempt_id"])

    def test_expired_certificate_is_not_revived_by_cache_hit(self):
        recorded = self.recorded(identity="qualified-cache-model")
        rule = self.rule(recorded)
        cert = self.certificate(rule, recorded)
        qualification = {"status": "qualified", "certificate": cert["reference"]}
        registry = QualificationRegistry([cert])
        definition, cache = self.cache_fixture(rule=rule, binding=recorded, qualifications=registry)
        self.service.cache = cache
        calls = []
        first = self.prepare(cache_context=[component("task-scope")])
        result = self.cache_compute(first, definition, cache, calls, qualification=qualification)
        self.assertEqual(result.response["qualification"]["status"], "qualified")
        self.assertEqual(self.service.commit(self.command(first, cache_entries=[result]))["status"], "success")
        self.now = deepcopy(LATE)
        second = self.prepare(request=self.request(audience=component("expiry-second")), cache_context=[component("task-scope")])
        reused = self.cache_compute(second, definition, cache, calls)
        self.assertTrue(reused.cache_hit)
        self.assertEqual(len(calls), 1)
        self.assertEqual(reused.response["qualification"]["status"], "expired")
        self.assertEqual(reused.entry["returned"]["response"]["qualification"], qualification)
        self.assertEqual(reused.value["source_attempt_id"], result.value["source_attempt_id"])

    def test_cache_hit_cannot_replace_original_target_token_with_equal_epoch_other_target(self):
        definition, _ = self.cache_fixture()
        raw = definition.value
        raw["fields"] = raw["fields"][:1]
        definition = SemanticComputationDefinition(raw, rules=self.rules, bindings=self.bindings)
        cache = SemanticCache(definitions=[definition], rules=self.rules, bindings=self.bindings, schemas=self.schemas, controls=self.controls)
        self.service.cache = cache
        calls = []
        original_subject = self.subject
        first = self.prepare()
        result = self.cache_compute(first, definition, cache, calls)
        self.assertEqual(self.service.commit(self.command(first, cache_entries=[result]))["status"], "success")
        correction = _in_scope(control_command("cache-original-target-correction", self.authority, targets=[original_subject],
            action="invalidate", now=self.now), self.storage.scope_id)
        correction["actor"] = self.actor
        correction["body"]["control"]["body"]["actor"] = self.actor
        self.assertEqual(self.controls.apply(self.controls.prepare(correction))["status"], "success")
        self.subject = self.make_matter("other-target")
        fresh = self.controls.capture(actor=self.actor, authority=entity_ref(self.authority), capability="assessment",
            targets=[entity_ref(self.subject), entity_ref(self.source)])
        self.assertEqual(fresh["control_epoch"], first.token["control_epoch"])
        with self.storage.snapshot() as view:
            with self.assertRaises(StorageError) as error:
                cache.get_or_compute(view, first.cache_inputs[0], compute=lambda value: self.fail("stale input compute"),
                    attempt_id="stale-original-must-not-run", as_of=self.now)
            self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        second = self.prepare(request=self.request(audience=component("different-target-audience")))
        fresh_result = self.cache_compute(second, definition, cache, calls)
        self.assertFalse(fresh_result.cache_hit)
        self.assertNotEqual(fresh_result.entry["key"], result.entry["key"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.service.commit(self.command(second, cache_entries=[fresh_result]))["status"], "success")
        self.assertEqual(self.storage.get(cache_ref(self.storage.scope_id, result.entry["key"]))["value"]["value"], result.entry)

    def test_same_cut_control_generation_refresh_computes_new_slot_without_renewing_old_attempt(self):
        definition, cache = self.cache_fixture()
        self.service.cache = cache
        calls = []
        first = self.prepare()
        original = self.cache_compute(first, definition, cache, calls)
        published = self.service.commit(self.command(first, cache_entries=[original]))
        self.assertEqual(published["status"], "success", published)
        old_assessment = self.storage.get(published["body"]["assessment"])
        old_cache = self.storage.get(cache_ref(self.storage.scope_id, original.entry["key"]))
        correction = _in_scope(control_command("fresh-cache-generation", self.authority, targets=[self.subject],
            action="invalidate", now=self.now), self.storage.scope_id)
        correction["actor"] = self.actor
        correction["body"]["control"]["body"]["actor"] = self.actor
        self.assertEqual(self.controls.apply(self.controls.prepare(correction))["status"], "success")
        fresh = self.prepare()
        recomputed = self.cache_compute(fresh, definition, cache, calls)
        self.assertFalse(recomputed.cache_hit)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(original.entry["key"], recomputed.entry["key"])
        result = self.service.commit(self.command(fresh, cache_entries=[recomputed]))
        self.assertEqual(result["status"], "success", result)
        current = self.storage.get(result["body"]["assessment"])
        self.assertEqual(current["body"]["causes"], ["disposition_change"])
        self.assertEqual(current["body"]["assessed_as_of"], old_assessment["body"]["assessed_as_of"])
        self.assertEqual(current["body"]["prior_assessment"], pin(old_assessment))
        self.assertEqual(self.storage.get(pin(old_assessment)), old_assessment)
        self.assertEqual(self.storage.get(pin(old_cache)), old_cache)

    def test_same_cut_extra_claim_change_is_evidence_correction_and_prior_basis_is_checked(self):
        first_result = self.claims.append(self.claims.prepare(claim_command("extra-first", "extra-first", self.subject, self.source)))
        first_claim = self.storage.get(first_result["body"]["claim"])
        _, _, prior = self.publish(extra=[pin(first_claim)])
        second_result = self.claims.append(self.claims.prepare(claim_command("extra-second", "extra-second", self.subject, self.source,
            value="corrected synthetic proposition")))
        second_claim = self.storage.get(second_result["body"]["claim"])
        prepared = self.prepare(extra=[pin(second_claim)])
        command = self.command(prepared)
        self.assertIn("evidence_correction", command["body"]["assessment"]["body"]["causes"])
        self.assertNotIn("new_evidence", command["body"]["assessment"]["body"]["causes"])
        self.assertNotIn("temporal_transition", command["body"]["assessment"]["body"]["causes"])
        # Rebuild an internally consistent command with a forged flat previous
        # basis: only the writer's actual previous-lane check can reject it.
        from matter.assessments import PreparedAssessment, _PREPARED
        altered = prepared.value
        altered["prior_basis"]["extra_dependencies"] = []
        forged = PreparedAssessment(altered, _admission=_PREPARED)
        refused = self.service.commit(self.service.prepare_commit(forged, self.graph_run(prepared),
            command_id="forged-prior-basis", idempotency_key="forged-prior-basis", assessment_id="forged-prior-basis"))
        self.assertEqual(refused["error"]["code"], "E_EVIDENCE_INVALID", refused)
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self.storage.get(result["body"]["assessment"])["body"]["prior_assessment"], pin(prior))
        self.assertEqual(self.storage.get(pin(prior)), prior)

    def test_same_cut_added_negative_scope_is_coverage_change_and_unchanged_refresh_is_refused(self):
        _, _, prior = self.publish()
        watch = self.absence_watch()
        prepared = self.prepare(negative=[pin(watch)])
        command = self.command(prepared)
        self.assertEqual(command["body"]["assessment"]["body"]["causes"], ["coverage_change"])
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        stored = self.storage.get(result["body"]["assessment"])
        self.assertEqual(stored["body"]["prior_assessment"], pin(prior))
        self.assertEqual(self.storage.get(pin(prior)), prior)
        unchanged = self.prepare(negative=[pin(watch)])
        with self.assertRaises(StorageError) as error:
            self.command(unchanged)
        self.assertIn("Unchanged assessment inputs", str(error.exception))

    def test_frozen_view_refuses_uncaptured_reference_instead_of_claiming_absence(self):
        prepared = self.prepare()
        unknown = {"scope_id": self.storage.scope_id, "namespace": "example", "record_type": "matter", "id": "not-captured"}
        with self.assertRaises(StorageError) as error:
            prepared.view.get(unknown)
        self.assertEqual(error.exception.code, "E_EVIDENCE_UNAVAILABLE")

    def qualified_graph(self, prepared, *, proposals=(), unavailable_node=None):
        packet = self.packet(self.rule_instance, view=prepared.view, subject=pin(self.subject), control_token=prepared.token,
                             as_of=prepared.value["request"]["body"]["assessed_as_of"])
        recorded = self.recorded([{"input_digest": packet.digest, "response": self.response(
            qualification={"status": "qualified", "certificate": self.active_certificate["reference"]},
            proposals=list(proposals))}], identity="qualified-assessment")
        self.binding_instance = recorded
        self.bindings = BindingRegistry([recorded])
        self.service.bindings = self.bindings
        return self.graph_run(prepared, binding=recorded, unavailable_node=unavailable_node)

    def configure_qualified_rule(self, *, proposals=False, incomplete=False):
        self.binding_instance = self.recorded(identity="qualified-assessment")
        def permissions(value):
            if proposals:
                value["consequence_permissions"] = [self.proposal_schema.reference]
                value["outcomes"][0]["implications"] = [self.proposal_schema.reference]
        self.rule_instance = self.rule(self.binding_instance, change=permissions)
        self.rules, self.bindings = RuleRegistry([self.rule_instance]), BindingRegistry([self.binding_instance])
        self.profile = self.make_profile(self.rule_instance)
        if incomplete:
            raw = self.profile.value
            unavailable = self.rule(self.binding_instance, identity="unavailable-rule")
            self.rules = RuleRegistry([self.rule_instance, unavailable])
            raw["components"]["evidence"]["rules"].append(unavailable.reference)
            raw["components"]["evidence"]["outputs"].append({"name": "example:unavailable", "rule": unavailable.reference,
                "schema": unavailable.value["output_schema"], "accepted_labels": ["example:positive"], "accepted_statuses": ["applicable"]})
            for limits in (raw["resource_limits"], raw["components"]["evidence"]["resource_limits"]):
                for field in ("max_calls", "max_input_bytes", "max_output_bytes", "max_elapsed_ms"):
                    limits[field] *= 2
            self.profile = ProfileDefinition(raw, rules=self.rules, schemas=self.schemas,
                allowed_data_scopes=[self.storage.scope_id], allowed_capabilities=self.rule_instance.value["consequence_permissions"],
                conflict_resolvers=[self.rule_instance.value["conflict_policy"]])
        self.profiles = ProfileRegistry([self.profile])
        nodes = {"evidence": self.rule_instance.reference}
        if incomplete:
            nodes["unavailable"] = unavailable.reference
        self.plan = RulePlan(self.profile, rules=self.rules, schemas=self.schemas, nodes=nodes)
        self.active_certificate = self.certificate(self.rule_instance, self.binding_instance)
        self.service = self.make_service(qualifications=QualificationRegistry([self.active_certificate]))
        result = self.claims.append(self.claims.prepare(claim_command("qualified-claim", "qualified-claim", self.subject, self.source)))
        claim = self.storage.get(result["body"]["claim"])
        mapping = {"node": "evidence", "claim": pin(claim), "labels": {"example:positive": "supported"},
                   "evidence_standard": self.profile.component_references["evidence"]}
        return claim, mapping

    def test_fresh_qualified_claim_materializes_but_expiry_prevents_later_current_use(self):
        claim, mapping = self.configure_qualified_rule()
        prepared = self.prepare(extra=[pin(claim)])
        run = self.qualified_graph(prepared)
        command = self.command(prepared, run, interpretations=[mapping])
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        stored = self.storage.get(result["body"]["assessment"])
        self.assertEqual(stored["body"]["propositions"][0]["status"], "supported")
        self.now = deepcopy(LATE)
        with self.assertRaises(StorageError) as error:
            self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience)
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.assertEqual(self.storage.get(pin(stored)), stored)

    def test_serialized_claim_cannot_be_demoted_to_proof_only_dependency(self):
        claim, mapping = self.configure_qualified_rule()
        prepared = self.prepare(extra=[pin(claim)])
        command = self.command(prepared, self.qualified_graph(prepared), interpretations=[mapping])
        preparation = command["extensions"][PUBLICATION_EXTENSION]["value"]["preparation"]
        preparation["current_dependencies"]["positive"].remove(pin(claim))
        preparation["proof_reads"].append(pin(claim))
        with self.assertRaises(StorageError) as error:
            self.service.commit(command)
        self.assertIn("explicitly guarded semantic claim", str(error.exception))
        with self.assertRaises(StorageError) as missing:
            self.storage.get(prepared.value["lane"])
        self.assertEqual(missing.exception.code, "E_NOT_FOUND")

    def test_qualification_expiring_between_evaluation_and_commit_is_durable_stale(self):
        claim, mapping = self.configure_qualified_rule()
        prepared = self.prepare(extra=[pin(claim)])
        run = self.qualified_graph(prepared)
        command = self.command(prepared, run, interpretations=[mapping])
        self.now = deepcopy(LATE)
        result = self.service.commit(command)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.service.attempt(command["idempotency_key"])["result"], result)
        self.assertIsNone(self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience))

    def expiry_without_mapping(self, *, incomplete, publish_first):
        claim, _ = self.configure_qualified_rule(proposals=True, incomplete=incomplete)
        prepared = self.prepare()
        proposal = {"schema": self.proposal_schema.reference, "value": {"reason": "Synthetic qualified review proposal."}}
        graph = self.qualified_graph(prepared, proposals=[proposal],
            unavailable_node="unavailable" if incomplete else None)
        command = self.command(prepared, graph)
        self.assertEqual(command["body"]["assessment"]["body"]["propositions"], [])
        self.assertEqual(command["body"]["assessment"]["body"]["proposals"], [proposal])
        self.assertEqual(command["body"]["assessment"]["body"]["evaluation_state"], "incomplete" if incomplete else "complete")
        stored = None
        if publish_first:
            result = self.service.commit(command)
            self.assertEqual(result["status"], "success", result)
            stored = self.storage.get(result["body"]["assessment"])
            self.assertEqual(self.service.current(self.subject, profile=self.profile.reference,
                purpose=self.purpose, audience=self.audience), stored)
        self.now = deepcopy(LATE)
        if publish_first:
            with self.assertRaises(StorageError) as error:
                self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience)
            self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
            self.assertEqual(self.storage.get(pin(stored)), stored)
        else:
            result = self.service.commit(command)
            self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE", result)
            self.assertEqual(self.service.attempt(command["idempotency_key"])["result"], result)
            with self.assertRaises(StorageError) as missing:
                self.storage.get(prepared.value["lane"])
            self.assertEqual(missing.exception.code, "E_NOT_FOUND")

    def test_complete_unmapped_qualified_proposal_expiry_prevents_publication(self):
        self.expiry_without_mapping(incomplete=False, publish_first=False)

    def test_incomplete_unmapped_qualified_proposal_expiry_prevents_publication(self):
        self.expiry_without_mapping(incomplete=True, publish_first=False)

    def test_complete_unmapped_qualified_proposal_expiry_prevents_current_use(self):
        self.expiry_without_mapping(incomplete=False, publish_first=True)

    def test_incomplete_unmapped_qualified_proposal_expiry_prevents_current_use(self):
        self.expiry_without_mapping(incomplete=True, publish_first=True)

    def test_cache_stage_rejects_edited_result_metadata_against_actual_state(self):
        definition, cache = self.cache_fixture()
        self.service.cache = cache
        prepared = self.prepare()
        result = self.cache_compute(prepared, definition, cache, [])
        graph = self.graph_run(prepared)
        for index, changes in enumerate((
            {"cache_hit": True}, {"cache_hit": 0}, {"stored": pin(self.source)},
            {"source_attempt_id": "invented-attempt"}, {"qualification": {"status": "qualified"}},
        )):
            with self.subTest(changes=changes):
                edited = result.value
                edited.update(changes)
                command = self.service.prepare_commit(prepared, graph, command_id=f"edited-cache-{index}",
                    idempotency_key=f"edited-cache-key-{index}", assessment_id=f"edited-cache-assessment-{index}", cache_entries=[edited])
                refused = self.service.commit(command)
                self.assertEqual(refused["error"]["code"], "E_DEPENDENCY_STALE" if "qualification" in changes else "E_EVIDENCE_INVALID", refused)
                with self.assertRaises(StorageError) as missing:
                    self.storage.get(prepared.value["lane"])
                self.assertEqual(missing.exception.code, "E_NOT_FOUND")
        self.assertEqual(self.service.commit(self.command(prepared, graph, cache_entries=[result]))["status"], "success")
        second = self.prepare(request=self.request(audience=component("cache-hit-metadata-audience")))
        hit = self.cache_compute(second, definition, cache, [])
        self.assertTrue(hit.cache_hit)
        second_graph = self.graph_run(second)
        for index, changes in enumerate(({"cache_hit": False}, {"cache_hit": 1}, {"stored": None})):
            edited = hit.value
            edited.update(changes)
            command = self.service.prepare_commit(second, second_graph, command_id=f"edited-hit-{index}",
                idempotency_key=f"edited-hit-key-{index}", assessment_id=f"edited-hit-assessment-{index}", cache_entries=[edited])
            refused = self.service.commit(command)
            self.assertEqual(refused["error"]["code"], "E_EVIDENCE_INVALID", refused)

    def test_concurrent_cache_fill_refuses_original_attempt_then_fresh_attempt_reuses_winner(self):
        definition, cache = self.cache_fixture()
        self.service.cache = cache
        calls = []
        first = self.prepare(request=self.request(audience=component("cache-race-first")))
        second = self.prepare(request=self.request(audience=component("cache-race-second")))
        first_result = self.cache_compute(first, definition, cache, calls)
        second_result = self.cache_compute(second, definition, cache, calls)
        self.assertFalse(first_result.cache_hit)
        self.assertFalse(second_result.cache_hit)
        self.assertEqual(first_result.entry["key"], second_result.entry["key"])
        first_command = self.command(first, cache_entries=[first_result])
        second_command = self.command(second, cache_entries=[second_result])
        self.assertEqual(self.service.commit(first_command)["status"], "success")
        winner = self.storage.get(cache_ref(self.storage.scope_id, first_result.entry["key"]))
        refused = self.service.commit(second_command)
        self.assertEqual(refused["error"]["code"], "E_DEPENDENCY_STALE", refused)
        journal = self.service.attempt(second_command["idempotency_key"])
        self.assertEqual(journal["command"]["extensions"][PUBLICATION_EXTENSION]["value"]["cache_entries"][0]["entry"]["source_attempt_id"],
            second_result.entry["source_attempt_id"])
        self.assertEqual(journal["result"], refused)
        self.assertEqual(self.service.commit(second_command), refused)
        self.assertIsNone(self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose,
            audience=component("cache-race-second")))
        fresh = self.prepare(request=self.request(audience=component("cache-race-second")))
        reused = self.cache_compute(fresh, definition, cache, calls)
        self.assertTrue(reused.cache_hit)
        self.assertEqual(len(calls), 2)
        self.assertEqual(reused.value["source_attempt_id"], first_result.value["source_attempt_id"])
        result = self.service.commit(self.command(fresh, cache_entries=[reused]))
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self.storage.get(result["body"]["assessment"])["body"]["resource_use"]["value"]["cache_hits"], 1)
        self.assertEqual(self.storage.get(pin(winner)), winner)

    def test_declared_time_condition_crossing_prevents_commit(self):
        deadline = {**NOW, "value": "2026-10-10T13:00:00Z"}
        condition = {"condition": component("deadline"), "next_check_at": deadline,
                     "expires_at": {"state": "unknown", "reason": "not_applicable"}}
        self.rule_instance = self.rule(self.binding_instance, change=lambda value: value.update(temporal_dependencies=[condition]))
        self.rules = RuleRegistry([self.rule_instance])
        self.profile = self.make_profile(self.rule_instance)
        self.profiles = ProfileRegistry([self.profile])
        self.plan = RulePlan(self.profile, rules=self.rules, schemas=self.schemas, nodes={"evidence": self.rule_instance.reference})
        self.service = self.make_service()
        prepared = self.prepare()
        command = self.command(prepared)
        self.now = deepcopy(deadline)
        with self.assertRaises(StorageError) as error:
            self.service.extend_staged(prepared, references=[])
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        result = self.service.commit(command)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.service.attempt(command["idempotency_key"])["result"], result)

    def absence_watch(self):
        from matter.coverage import CoveragePolicy, CoverageService
        from coverage_helpers import ADAPTER, T2, publish_command, register_command, specification
        from integration.helpers import projection_ref
        policy = CoveragePolicy(self.storage.scope_id, actors=[self.actor], authorities=[pin(self.authority)], adapters=[ADAPTER])
        service = CoverageService(self.storage, policy=policy)
        spec = specification()
        baselines = [{"source": source, "observations": [], "history_complete": True} for source in spec["eligible_sources"]]
        command = _in_scope(publish_command("assessment-coverage", self.authority, policy, spec, baselines=baselines), self.storage.scope_id)
        command["actor"] = self.actor
        result = service.publish(service.prepare(command))
        self.assertEqual(result["status"], "success", result)
        coverage = self.storage.get(result["body"]["coverage"])
        target_ref = projection_ref("assessment-absence-host", self.storage.scope_id)
        bootstrap = create_command("absence-host-bootstrap", "absence-host-subject", scope_id=self.storage.scope_id)
        def host(tx):
            target = tx.put_projection(target_ref, domain_value({"synthetic": "explicit host-owned absence derivative"}))
            matter = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(matter)})
        self.assertEqual(self.storage.execute(bootstrap, host)["status"], "success")
        target = self.storage.get(target_ref)
        command = _in_scope(register_command("assessment-watch", self.authority, policy, target, coverage,
            as_of=T2, expires_at=LATE), self.storage.scope_id)
        command["actor"] = self.actor
        result = service.register(service.prepare(command))
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(result["body"]["registration"])

    def coverage_arrival(self, identity, event):
        from coverage_helpers import SOURCE_NAMESPACE, T1
        from observation_helpers import observation_command
        payload = b"Synthetic late coverage evidence.\n"
        command = observation_command(identity, identity, payload=payload, scope_id=self.storage.scope_id,
            source_namespace=SOURCE_NAMESPACE, event_id=event, revision_id=identity, available_at=self.now)
        command["body"]["observation"]["body"]["occurred_at"] = deepcopy(T1)
        result = self.ingestor.ingest(self.ingestor.prepare(command), payload=payload)
        self.assertEqual(result["status"], "success", result)

    def test_negative_scope_arrival_refuses_current_but_unrelated_arrival_does_not(self):
        watch = self.absence_watch()
        prepared = self.prepare(negative=[pin(watch)])
        command = self.command(prepared)
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        original = self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience)
        self.coverage_arrival("unrelated-absence-arrival", "another-event")
        self.assertEqual(self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience), original)
        self.coverage_arrival("matching-absence-arrival", "expected-event")
        with self.assertRaises(StorageError) as error:
            self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience)
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.assertEqual(self.storage.get(pin(original)), original)

    def test_negative_scope_change_between_evaluation_and_commit_retains_attempt(self):
        watch = self.absence_watch()
        prepared = self.prepare(negative=[pin(watch)])
        command = self.command(prepared)
        self.coverage_arrival("matching-before-assessment-commit", "expected-event")
        result = self.service.commit(command)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.service.attempt(command["idempotency_key"])["result"], result)

    def test_staged_existing_judgment_has_real_original_receipt_and_no_reinsert(self):
        first = self.prepare()
        graph = self.graph_run(first)
        command = self.command(first, graph)
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        assessment = self.storage.get(result["body"]["assessment"])
        judgment = self.storage.get(assessment["body"]["judgments"][0])
        receipt = self.storage.get(judgment["body"]["attempt_receipts"][0])
        narrow = self.prepare(request=self.request(audience=component("unstaged-narrow-audience")))
        with self.assertRaises(StorageError) as error:
            self.service.extend_staged(narrow, references=[pin(judgment), pin(receipt)])
        self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")
        second = self.prepare(request=self.request(audience=component("staged-second-audience")),
            extra=[pin(judgment)], control_contexts=[first.token])
        extended = self.service.extend_staged(second, references=[pin(judgment), pin(receipt)])
        self.assertEqual(extended.value["captured_at"], second.value["captured_at"])
        self.assertEqual(extended.value["request"], second.value["request"])
        result2 = self.service.commit(self.command(extended, graph))
        self.assertEqual(result2["status"], "success", result2)
        stored = self.storage.get(result2["body"]["assessment"])
        self.assertEqual(stored["body"]["judgments"], [pin(judgment)])
        self.assertEqual(self.storage.get(pin(judgment)), judgment)
        self.assertNotEqual(stored["creation_receipt"], judgment["creation_receipt"])

    def test_staging_cannot_admit_mutable_records_or_refresh_changed_originals(self):
        prepared = self.prepare()
        with self.assertRaises(StorageError):
            self.service.extend_staged(prepared, references=[pin(self.subject)])
        self.rename_subject()
        with self.assertRaises(StorageError) as error:
            self.service.extend_staged(prepared, references=[])
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")

    def test_raw_receipt_tampering_is_refused_before_publication(self):
        prepared = self.prepare()
        command = self.command(prepared)
        for change in (
            lambda c: c["extensions"][PUBLICATION_EXTENSION]["value"]["graph"]["nodes"]["evidence"]["attempt_receipt"]["body"]["details"]["value"].update(input_digest="d" * 64),
            lambda c: c["extensions"][PUBLICATION_EXTENSION]["value"]["graph"]["nodes"]["evidence"]["judgment"]["body"]["qualification"].update(status="qualified"),
            lambda c: c["extensions"][PUBLICATION_EXTENSION]["value"]["graph"]["inputs"]["evidence"]["packet"]["evidence"][0]["record"]["body"].update(source_event_id="forged"),
        ):
            corrupt = deepcopy(command)
            change(corrupt)
            with self.assertRaises(ContractError):
                self.service.commit(corrupt)
        self.assertIsNone(self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience))

    def test_preparation_enforces_assessment_budget_and_captures_no_live_fallback(self):
        request = self.request()
        request["body"]["budget"]["max_calls"] = 0
        with self.assertRaises(StorageError) as error:
            self.prepare(request=request)
        self.assertEqual(error.exception.code, "E_BUDGET_EXHAUSTED")
        request = self.request()
        request["body"]["budget"]["max_bytes"] = 1
        with self.assertRaises(StorageError) as error:
            self.prepare(request=request)
        self.assertEqual(error.exception.code, "E_BUDGET_EXHAUSTED")

    def test_present_read_denial_blocks_current_history_and_exact_replay_disclosure(self):
        _, command, stored = self.publish()
        denial = _in_scope(control_command("deny-assessment-source-read", self.authority, targets=[self.source],
            action="deny", capabilities=["read"], now=self.now), self.storage.scope_id)
        denial["actor"] = self.actor
        denial["body"]["control"]["body"]["actor"] = self.actor
        self.assertEqual(self.controls.apply(self.controls.prepare(denial))["status"], "success")
        for read in (
            lambda: self.service.current(self.subject, profile=self.profile.reference, purpose=self.purpose, audience=self.audience),
            lambda: self.service.attempt(command["idempotency_key"]),
        ):
            with self.assertRaises(StorageError) as error:
                read()
            self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")
        result = self.service.commit(command)
        self.assertEqual(result["error"]["code"], "E_AUTHORITY_REQUIRED")
        self.assertEqual(self.storage.get(pin(stored)), stored)  # privileged host storage retains history

    def test_source_read_denial_prevents_frozen_input_with_matter_only_assessment_token(self):
        denial = _in_scope(control_command("deny-source-before-preparation", self.authority, targets=[self.source],
            action="deny", capabilities=["read"], now=self.now), self.storage.scope_id)
        denial["actor"] = self.actor
        denial["body"]["control"]["body"]["actor"] = self.actor
        self.assertEqual(self.controls.apply(self.controls.prepare(denial))["status"], "success")
        token = self.controls.capture(actor=self.actor, authority=entity_ref(self.authority), capability="assessment",
            targets=[entity_ref(self.subject)])
        request = self.request()
        request["body"]["control_epoch"] = token["control_epoch"]
        with self.assertRaises(StorageError) as error:
            self.service.prepare(request, token=token, plan=self.plan)
        self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")

    def test_original_token_must_cover_source_without_any_read_denial(self):
        token = self.controls.capture(actor=self.actor, authority=entity_ref(self.authority), capability="assessment",
            targets=[entity_ref(self.subject)])
        request = self.request()
        request["body"]["control_epoch"] = token["control_epoch"]
        with self.assertRaises(StorageError) as error:
            self.service.prepare(request, token=token, plan=self.plan)
        self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")

    def test_source_targeted_assessment_denial_between_evaluation_and_commit_prevents_publication(self):
        prepared = self.prepare()
        command = self.command(prepared)
        denial = _in_scope(control_command("deny-source-assessment-after-evaluation", self.authority,
            targets=[self.source], action="deny", capabilities=["assessment"], now=self.now), self.storage.scope_id)
        denial["actor"] = self.actor
        denial["body"]["control"]["body"]["actor"] = self.actor
        self.assertEqual(self.controls.apply(self.controls.prepare(denial))["status"], "success")
        result = self.service.commit(command)
        self.assertEqual(result["status"], "failure", result)
        self.assertIn(result["error"]["code"], {"E_DEPENDENCY_STALE", "E_AUTHORITY_REQUIRED"})
        self.assertEqual(self.service.attempt(command["idempotency_key"])["result"], result)
        with self.assertRaises(StorageError) as missing:
            self.storage.get(prepared.value["lane"])
        self.assertEqual(missing.exception.code, "E_NOT_FOUND")

    def test_public_cache_checks_read_permission_before_capture_and_after_denied_hit(self):
        definition, cache = self.cache_fixture()
        self.service.cache = cache
        calls = []
        prepared = self.prepare()
        result = self.cache_compute(prepared, definition, cache, calls)
        self.assertEqual(self.service.commit(self.command(prepared, cache_entries=[result]))["status"], "success")
        original_input = prepared.cache_inputs[0]
        denial = _in_scope(control_command("deny-public-cache-source-read", self.authority, targets=[self.source],
            action="deny", capabilities=["read"], now=self.now), self.storage.scope_id)
        denial["actor"] = self.actor
        denial["body"]["control"]["body"]["actor"] = self.actor
        self.assertEqual(self.controls.apply(self.controls.prepare(denial))["status"], "success")
        fresh_token = self.controls.capture(actor=self.actor, authority=entity_ref(self.authority), capability="assessment",
            targets=[entity_ref(self.subject), entity_ref(self.source)])
        with self.storage.snapshot() as view:
            with self.assertRaises(StorageError) as error:
                cache.capture(view, definition, records={"source": pin(self.source), "subject": pin(self.subject)}, context={},
                    token=fresh_token, as_of=self.now)
            self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")
        with self.storage.snapshot() as view:
            with self.assertRaises(StorageError) as error:
                cache.get_or_compute(view, original_input, compute=lambda value: self.fail("denied cache compute"),
                    attempt_id="must-not-run-after-denial", as_of=self.now)
            self.assertIn(error.exception.code, {"E_AUTHORITY_REQUIRED", "E_DEPENDENCY_STALE"})
        self.assertEqual(len(calls), 1)

    def test_unresolved_explicit_composition_cannot_publish_one_selected_raw_claim(self):
        from matter.conflicts import ConflictResolver, ConflictResolverRegistry
        resolver = ConflictResolver("example", "retain-for-assessment", "1.0")
        first_binding = self.binding(lambda request: self.response(), identity="first-opinion")
        second_binding = self.binding(lambda request: self.response(label="example:negative"), identity="second-opinion")
        first_rule = self.rule(first_binding, identity="first-rule", change=lambda value: value.update(conflict_policy=resolver.reference))
        second_rule = self.rule(second_binding, identity="second-rule", change=lambda value: value.update(conflict_policy=resolver.reference))
        self.rules = RuleRegistry([first_rule, second_rule])
        self.bindings = BindingRegistry([first_binding, second_binding])
        single = self.make_profile(first_rule).value
        component_value = single["components"]["evidence"]
        component_value["rules"].append(second_rule.reference)
        component_value["outputs"].append({**component_value["outputs"][0], "name": "example:other-conclusion", "rule": second_rule.reference})
        for limits in (component_value["resource_limits"], single["resource_limits"]):
            for field in ("max_calls", "max_input_bytes", "max_output_bytes", "max_elapsed_ms"):
                limits[field] *= 2
        self.profile = ProfileDefinition(single, rules=self.rules, schemas=self.schemas,
            allowed_data_scopes=[self.storage.scope_id], conflict_resolvers=[resolver.reference])
        self.profiles = ProfileRegistry([self.profile])
        self.plan = RulePlan(self.profile, rules=self.rules, schemas=self.schemas,
            nodes={"first": first_rule.reference, "second": second_rule.reference}, compositions=[
                {"id": "conflict", "resolver": resolver.reference, "nodes": ["first", "second"], "mandatory_gates": []}])
        self.service = self.make_service()
        self.service.conflicts = ConflictResolverRegistry([resolver])
        result = self.claims.append(self.claims.prepare(claim_command("conflicting-claim", "conflicting-claim", self.subject, self.source)))
        claim = self.storage.get(result["body"]["claim"])
        prepared = self.prepare(extra=[pin(claim)])
        runner = self.runner([first_rule, second_rule], [first_binding, second_binding], clock=lambda: deepcopy(self.now))
        def build(name, upstream):
            rule = first_rule if name == "first" else second_rule
            return self.packet(rule, view=prepared.view, subject=pin(self.subject), control_token=prepared.token)
        graph = GraphExecutor(runner, conflicts=ConflictResolverRegistry([resolver]), clock=lambda: deepcopy(self.now)).execute(
            self.plan, prepare=build, run_id="conflicting-assessment-graph", max_workers=1,
            check_current=lambda material, as_of: self.service.check_current(prepared, material, as_of=as_of), check_control=self.controls.check)
        self.assertEqual(graph.value["compositions"][0]["status"], "conflicting")
        mapping = {"node": "first", "claim": pin(claim), "labels": {"example:positive": "supported"},
                   "evidence_standard": self.profile.component_references["evidence"]}
        command = self.command(prepared, graph, interpretations=[mapping])
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        assessment = self.storage.get(result["body"]["assessment"])
        self.assertEqual(assessment["body"]["evaluation_state"], "incomplete")
        self.assertEqual(assessment["body"]["propositions"][0]["status"], "unknown")
        self.assertEqual(len(assessment["body"]["judgments"]), 2)


if __name__ == "__main__":
    unittest.main()
