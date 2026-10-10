"""Independent integrity checks on temporal coverage and negative registrations."""

from copy import deepcopy

from matter.coverage import coverage_at, read_coverage
from matter.negative_dependencies import (
    collect_arrival_watches, negative_status, read_negative_dependency, require_current_negative_dependency,
)
from matter.source_catalogs import source_catalog_ref, source_key
from matter.storage import StorageError, entity_ref, pin, snapshot_digest

from association_helpers import SCOPE
from coverage_helpers import (
    ADAPTER, SOURCE_NAMESPACE, T2, T3, T4, CoverageTestCase, publish_command, register_command, specification,
)
from integration.helpers import create_command, domain_value
from matter_helpers import assessment_fixture_command, store_assessment_fixture


class SubstitutedView:
    """Present one structurally valid damaged projection at its original pin."""

    def __init__(self, view, original, replacement):
        self.view, self.original, self.replacement = view, original, replacement

    def __getattr__(self, name):
        return getattr(self.view, name)

    def substitute(self, record):
        return deepcopy(self.replacement) if entity_ref(record) == entity_ref(self.original) else record

    def get(self, reference):
        return self.substitute(self.view.get(reference))

    def lookup_identity(self, reference):
        return self.substitute(self.view.lookup_identity(reference))

    def watchers(self, key):
        return [self.substitute(record) for record in self.view.watchers(key)]


class CoverageIntegrityTests(CoverageTestCase):
    def assert_invalid(self, function, *args, **kwargs):
        with self.assertRaises(StorageError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")

    def test_frozen_coverage_cannot_omit_an_observation_from_its_selected_catalog(self):
        observation, _, _ = self.arrival("present-before-coverage")
        covered, _, _ = self.publish_coverage(observations=[observation])
        self.assertEqual(self.value(covered)["matches"], [pin(observation)])
        altered = deepcopy(covered)
        self.value(altered).update(observations=[], matches=[], result="adequate_empty")
        with self.storage.snapshot() as snapshot:
            self.assertEqual(read_coverage(snapshot, SCOPE, pin(covered)), covered)
            view = SubstitutedView(snapshot, covered, altered)
            self.assert_invalid(read_coverage, view, SCOPE, pin(covered))
            self.assert_invalid(coverage_at, view, SCOPE, pin(covered))

    def test_unattested_catalog_cannot_be_relabelled_complete_by_a_coverage_projection(self):
        covered, _, _ = self.publish_coverage(baselines=[])
        self.assertFalse(self.value(covered)["history_complete"])
        altered = deepcopy(covered)
        self.value(altered).update(history_complete=True, result="adequate_empty")
        with self.storage.snapshot() as snapshot:
            self.assert_invalid(read_coverage, SubstitutedView(snapshot, covered, altered), SCOPE, pin(covered))

    def test_later_admissions_and_baseline_do_not_rewrite_frozen_population_or_completeness(self):
        old, _, _ = self.publish_coverage(baselines=[])
        observation, _, _ = self.arrival("admitted-after-old-coverage", available_at=T3)
        today, _, _ = self.publish_coverage(command_id="attested-today", previous=old, as_of=T3,
            baselines=[{"source": source_key(SOURCE_NAMESPACE), "observations": [], "history_complete": True}])
        self.assertTrue(self.value(today)["history_complete"])
        self.assertEqual(self.value(today)["matches"], [pin(observation)])
        with self.storage.snapshot() as snapshot:
            historical = coverage_at(snapshot, SCOPE, pin(old))
            self.assertEqual(historical, old)
            self.assertFalse(self.value(historical)["history_complete"])
            self.assertEqual(self.value(historical)["observations"], [])

    def test_publication_proof_binds_its_actual_write_and_selected_catalog_reads(self):
        first, _, first_result = self.publish_coverage()
        observation, _, _ = self.arrival("published-later", available_at=T3)
        catalog = self.storage.get(source_catalog_ref(SCOPE, source_key(SOURCE_NAMESPACE)))
        # The service retains explicit caller digest pins. Provenance checking
        # must recognize this exact snapshot as the generated revision-form pin.
        command = publish_command("second-publication", self.authority, self.coverage_policy,
                                  specification(), previous=first, as_of=T3)
        digest_pin = {**entity_ref(catalog), "digest": snapshot_digest(catalog)}
        command["expected_revisions"] = [digest_pin]
        prepared = self.coverage.prepare(command)
        self.assertIn(digest_pin, prepared["expected_revisions"])
        second_result = self.coverage.publish(prepared)
        self.assertEqual(second_result["status"], "success", second_result)
        second = self.storage.get(second_result["body"]["coverage"])
        self.assertEqual(self.value(second)["matches"], [pin(observation)])
        old_receipt = self.storage.get(first_result["receipt"])
        current_receipt = self.storage.get(second_result["receipt"])
        self.assertIn(pin(first), old_receipt["body"]["details"]["value"]["writes"])
        self.assertNotIn(pin(second), old_receipt["body"]["details"]["value"]["writes"])
        old_catalog = self.value(first)["catalogs"][0]
        current_proof = current_receipt["body"]["details"]["value"]
        self.assertNotIn(old_catalog, current_proof["read_set"] + current_proof["writes"])
        self.arrival("catalog-advanced-after-publication", event="unrelated-event", available_at=T3)

        wrong_receipt = deepcopy(second)
        self.value(wrong_receipt)["publication_receipt"] = first_result["receipt"]
        wrong_population = deepcopy(second)
        self.value(wrong_population).update(catalogs=[old_catalog], observations=[], matches=[],
                                            indeterminate=[], excluded=[], result="adequate_empty")
        copied_receipt = deepcopy(current_receipt)
        copied_receipt.update(namespace="example:copied-proofs", id="copied-publication-receipt")
        copied_receipt["creation_receipt"] = entity_ref(copied_receipt)
        wrong_receipt_kind = deepcopy(second)
        self.value(wrong_receipt_kind)["publication_receipt"] = entity_ref(copied_receipt)
        with self.storage.snapshot() as snapshot:
            self.assertEqual(read_coverage(snapshot, SCOPE, pin(second)), second)

            class CopiedReceiptView(SubstitutedView):
                def get(self, reference):
                    if reference == entity_ref(copied_receipt):
                        return deepcopy(copied_receipt)
                    return super().get(reference)

            cases = (("other-publication-receipt", SubstitutedView(snapshot, second, wrong_receipt)),
                     ("catalog-not-read-by-publication", SubstitutedView(snapshot, second, wrong_population)),
                     ("operation-shaped-copy", CopiedReceiptView(snapshot, second, wrong_receipt_kind)))
            for label, view in cases:
                with self.subTest(provenance=label):
                    self.assert_invalid(read_coverage, view, SCOPE, pin(second))
                    self.assert_invalid(coverage_at, view, SCOPE, pin(second))

    def test_digest_pinned_publication_and_registration_survive_later_catalog_append(self):
        first, _, _ = self.publish_coverage()
        catalog = self.storage.get(source_catalog_ref(SCOPE, source_key(SOURCE_NAMESPACE)))
        digest_pin = {**entity_ref(catalog), "digest": snapshot_digest(catalog)}
        publish = publish_command("publish-digest-proof", self.authority, self.coverage_policy,
                                  specification(), previous=first)
        publish["expected_revisions"] = [digest_pin]
        prepared = self.coverage.prepare(publish)
        self.assertIn(digest_pin, prepared["expected_revisions"])
        published = self.coverage.publish(prepared)
        self.assertEqual(published["status"], "success", published)
        covered = self.storage.get(published["body"]["coverage"])
        self.assertEqual(self.value(covered)["result"], "adequate_empty")

        target = self.host_projection("digest-proof-result")
        register = register_command("register-digest-proof", self.authority, self.coverage_policy, target, covered)
        register["expected_revisions"] = [digest_pin]
        prepared_registration = self.coverage.prepare(register)
        self.assertIn(digest_pin, prepared_registration["expected_revisions"])
        registered = self.coverage.register(prepared_registration)
        self.assertEqual(registered["status"], "success", registered)
        registration = self.storage.get(registered["body"]["registration"])
        self.arrival("unrelated-after-digest-proof", event="different-event", available_at=T3)
        with self.storage.snapshot() as snapshot:
            self.assertEqual(coverage_at(snapshot, SCOPE, pin(covered)), covered)
            self.assertEqual(read_coverage(snapshot, SCOPE, pin(covered)), covered)
            self.assertEqual(require_current_negative_dependency(snapshot, SCOPE, pin(registration), as_of=T3),
                             registration)
        self.assertEqual(self.coverage.publish(prepared), published)
        self.assertEqual(self.coverage.register(prepared_registration), registered)

    def test_malformed_watch_descriptor_keys_and_scopes_are_not_empty_arrival_sets(self):
        covered, _, _ = self.publish_coverage()
        registration, _, _ = self.register_watch(covered)
        arrival, _ = self.arrival_command("watch-integrity-probe")
        observation = arrival["body"]["observation"]
        mutations = (
            lambda record: record["value"]["schema"].update(digest="0" * 64),
            lambda record: record.update(watch_keys=[]),
            lambda record: self.value(record)["watch"].update(scope_id="synthetic:foreign"),
            lambda record: self.value(record)["coverage_snapshot"].update(scope_id="synthetic:foreign"),
        )
        with self.storage.snapshot() as snapshot:
            for mutate in mutations:
                altered = deepcopy(registration)
                mutate(altered)
                with self.subTest(mutation=mutate):
                    view = SubstitutedView(snapshot, registration, altered)
                    with self.assertRaises(StorageError) as error:
                        collect_arrival_watches(view, SCOPE, observation)
                    self.assertIn(error.exception.code, {"E_EVIDENCE_INVALID", "E_SCOPE_FORBIDDEN"})

        self.arrival("real-arrival-before-copied-receipt")
        invalidated = self.current(registration)
        copied_receipt = self.storage.get(self.value(invalidated)["invalidation"]["receipt"])
        copied_receipt.update(namespace="example:copied-proofs", id="copied-arrival-receipt")
        copied_receipt["creation_receipt"] = entity_ref(copied_receipt)
        altered = deepcopy(invalidated)
        self.value(altered)["invalidation"]["receipt"] = entity_ref(copied_receipt)
        with self.storage.snapshot() as snapshot:
            class CopiedArrivalReceiptView(SubstitutedView):
                def get(self, reference):
                    if reference == entity_ref(copied_receipt):
                        return deepcopy(copied_receipt)
                    return super().get(reference)

            view = CopiedArrivalReceiptView(snapshot, invalidated, altered)
            self.assert_invalid(read_negative_dependency, view, SCOPE, pin(invalidated))

    def test_assessment_negative_manifest_requires_canonical_predicate_equality(self):
        spec = specification(clauses=[{"field": "extension", "key": "example:flag", "schema": ADAPTER,
                                      "value": {"approved": 1}}])
        covered, _, _ = self.publish_coverage(spec=spec)
        matter = self.matter("assessment-matter")
        for label, approved in (("boolean", True), ("integer", 1)):
            identity = "typed-watch-" + label
            watch = {"id": identity, "scope_id": SCOPE, **deepcopy(spec),
                     "catalog": self.value(covered)["catalog"], "coverage": self.value(covered)["coverage"],
                     "assessed_as_of": T2, "expires_at": T4}
            watch["query"]["value"]["clauses"][0]["value"]["approved"] = approved
            command = assessment_fixture_command("assessment-" + label, matter,
                                                  purpose="synthetic-coverage", audience="synthetic-host")
            command["body"]["assessment"]["body"]["dependency_manifest"].update(
                positive=[pin(matter), pin(covered)], negative=[watch])
            stored = self.storage.execute(command, store_assessment_fixture)
            assessment = self.storage.get(stored["body"]["assessment"])
            register = register_command("register-" + label, self.authority, self.coverage_policy,
                                        assessment, covered, identity=identity)
            if label == "boolean":
                self.assert_invalid(self.coverage.prepare, register)
            else:
                result = self.coverage.register(self.coverage.prepare(register))
                self.assertEqual(result["outcome"], "registered", result)

    def test_stored_watch_cannot_substitute_boolean_predicate_for_integer_coverage(self):
        spec = specification(clauses=[{"field": "extension", "key": "example:flag", "schema": ADAPTER,
                                      "value": {"approved": 1}}])
        covered, _, _ = self.publish_coverage(spec=spec)
        registration, _, _ = self.register_watch(covered)
        altered = deepcopy(registration)
        self.value(altered)["watch"]["query"]["value"]["clauses"][0]["value"]["approved"] = True
        with self.storage.snapshot() as snapshot:
            view = SubstitutedView(snapshot, registration, altered)
            self.assert_invalid(negative_status, view, SCOPE, pin(registration), as_of=T2)

    def test_catalog_and_watch_backend_errors_retain_their_codes(self):
        covered, _, _ = self.publish_coverage()
        self.register_watch(covered)
        arrival, _ = self.arrival_command("backend-probe")
        catalog_ref = source_catalog_ref(SCOPE, source_key(SOURCE_NAMESPACE))
        with self.storage.snapshot() as snapshot:
            for code in ("E_STORAGE_UNAVAILABLE", "E_REVISION_CONFLICT"):
                class FailingCatalog:
                    def __getattr__(self, name):
                        return getattr(snapshot, name)

                    def lookup_identity(self, reference):
                        if entity_ref(reference) == catalog_ref:
                            raise StorageError(code, retriable=code == "E_STORAGE_UNAVAILABLE")
                        return snapshot.lookup_identity(reference)

                class FailingWatch:
                    def watchers(self, key):
                        raise StorageError(code, retriable=code == "E_STORAGE_UNAVAILABLE")

                for function, args in (
                    (read_coverage, (FailingCatalog(), SCOPE, pin(covered))),
                    (collect_arrival_watches, (FailingWatch(), SCOPE, arrival["body"]["observation"])),
                ):
                    with self.subTest(code=code, function=function), self.assertRaises(StorageError) as error:
                        function(*args)
                    self.assertEqual(error.exception.code, code)
                    self.assertEqual(error.exception.retriable, code == "E_STORAGE_UNAVAILABLE")

    def test_changed_target_stales_use_without_blocking_unrelated_intake(self):
        covered, _, _ = self.publish_coverage()
        target = self.host_projection("mutable-derivative")
        registration, _, _ = self.register_watch(covered, target=target)
        command = create_command("revise-derivative", "revision-helper", scope_id=SCOPE,
                                 expected_revisions=[pin(target)])

        def revise(tx):
            tx.put_projection(entity_ref(target), domain_value({"synthetic_fact": "new current version"}))
            record = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(record)})

        self.assertEqual(self.storage.execute(command, revise)["status"], "success")
        self.arrival("unrelated-after-target-revision", event="different-event")
        with self.storage.snapshot() as snapshot:
            self.assertEqual(read_negative_dependency(snapshot, SCOPE, pin(registration)), registration)
            self.assertEqual(negative_status(snapshot, SCOPE, pin(registration), as_of=T3), "dependency_stale")
            with self.assertRaises(StorageError) as error:
                require_current_negative_dependency(snapshot, SCOPE, pin(registration), as_of=T3)
            self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.assertEqual(self.current(registration), registration)
