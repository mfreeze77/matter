"""Source catalogs retain exact observations without inventing a legacy baseline."""

from copy import deepcopy
import hashlib
from importlib.resources import files
from pathlib import Path
import tempfile
import unittest

from matter.canonical import canonical_bytes
from matter.source_catalogs import (
    CATALOG_NAMESPACE, MAX_CATALOG_OBSERVATIONS, append_observation,
    catalog_observations, catalog_population, catalog_schema_ref, catalog_snapshot, ensure_catalog, initialize_catalog,
    read_catalog, source_catalog_ref, source_key, source_watch_key,
)
from matter.storage import SQLiteStore, StorageError, entity_ref, pin, snapshot_digest

from integration.helpers import create_command, ingest_command


SCOPE = "synthetic:source-catalogs"
SOURCE = source_key("example:source")
TIME = {"state": "known", "value": "2026-10-08T12:00:00Z", "precision": "second"}
ADAPTER = {"namespace": "example", "id": "legacy-catalog-adapter", "version": "1.0", "digest": "a" * 64}


class ReadPort:
    """Only malformed read responses; durable writes use the actual SQLite port."""

    def __init__(self, *, lookup=None, records=None, error=None):
        self.lookup = lookup
        self.records = records or {}
        self.error = error

    def lookup_identity(self, reference):
        if self.error:
            raise self.error
        if self.lookup is None:
            raise StorageError("E_NOT_FOUND")
        return deepcopy(self.lookup)

    def get(self, reference):
        if self.error:
            raise self.error
        try:
            return deepcopy(self.records[canonical_bytes(reference)])
        except KeyError:
            raise StorageError("E_NOT_FOUND") from None

    def history(self, reference):
        raise AssertionError("Catalog helpers must use exact checked reads, never transaction history.")


class SourceCatalogTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "catalog.sqlite"
        self.storage = SQLiteStore(self.database, scope_id=SCOPE)
        self.addCleanup(self.storage.close)
        self.sequence = 0

    def assert_error(self, code, operation, *args, **kwargs):
        with self.assertRaises(StorageError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def current(self, source=SOURCE):
        with self.storage.snapshot() as view:
            return read_catalog(view, SCOPE, source)

    def ingest(self, identity, *, capture=True, source="example:source", expected=()):
        command = ingest_command("intake-" + identity, identity, scope_id=SCOPE, expected_revisions=expected)
        command["body"]["observation"]["body"]["source_identity"]["namespace"] = source

        def handle(tx):
            record = tx.insert(tx.command["body"]["observation"])
            if capture:
                append_observation(tx, record)
            return tx.success("committed", {"observation": pin(record), "observation_receipt": record["creation_receipt"]})

        result = self.storage.execute(command, handle)
        self.assertEqual("success", result["status"], result)
        return self.storage.get(result["body"]["observation"])

    def mutate(self, operation, *, expected=()):
        self.sequence += 1
        identity = "mutation-" + str(self.sequence)
        command = create_command(identity, identity, scope_id=SCOPE, expected_revisions=expected)
        output = []

        def handle(tx):
            output.append(operation(tx))
            matter = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(matter)})

        result = self.storage.execute(command, handle)
        return result, output[0] if result["status"] == "success" else None

    def initialize(self, observations, *, source=SOURCE, authority=None, declared_at=TIME, expected=None):
        authority = authority or pin(self.storage.get(observations[0]["creation_receipt"]))
        catalog = self.current(source)
        if expected is None:
            expected = [pin(record) for record in observations] + [authority]
            if catalog is not None:
                expected.append(pin(catalog))
                with self.storage.snapshot() as view:
                    expected += [pin(record) for record in catalog_observations(view, SCOPE, catalog)]
            expected = list({canonical_bytes(ref): ref for ref in expected}.values())
        return self.mutate(lambda tx: initialize_catalog(
            tx, source, [pin(record) for record in observations], adapter=ADAPTER,
            authority=authority, declared_at=declared_at,
        ), expected=expected)

    def test_source_addresses_are_exact_scoped_and_only_support_namespace_selectors(self):
        selectors = [source_key(value) for value in ("example:source", "example:Source", "example.source", "example_source")]
        refs = [source_catalog_ref(SCOPE, value) for value in selectors]
        self.assertEqual(len(refs), len({value["id"] for value in refs}))
        self.assertEqual(CATALOG_NAMESPACE, refs[0]["namespace"])
        self.assertNotEqual(refs[0]["id"], source_catalog_ref("synthetic:other", SOURCE)["id"])
        self.assertNotEqual(source_watch_key(SCOPE, SOURCE), source_watch_key("synthetic:other", SOURCE))
        self.assertEqual(source_watch_key(SCOPE, SOURCE), source_watch_key(SCOPE, deepcopy(SOURCE)))
        for source in ({"namespace": "example:source", "value": "example:source"},
                       {**SOURCE, "value": " space "}, {**SOURCE, "extra": True}):
            with self.subTest(source=source):
                self.assert_error("E_SCHEMA_INVALID", source_catalog_ref, SCOPE, source)
                self.assert_error("E_SCHEMA_INVALID", source_watch_key, SCOPE, source)

    def test_descriptor_binds_exact_packaged_schema_and_is_detached(self):
        content = files("matter._schemas").joinpath("source-catalog.schema.json").read_bytes()
        expected = {"namespace": "matter", "id": "source-catalog", "version": "1.0", "digest": hashlib.sha256(content).hexdigest()}
        self.assertEqual(expected, catalog_schema_ref())
        changed = catalog_schema_ref()
        changed["digest"] = "0" * 64
        self.assertEqual(expected, catalog_schema_ref())

    def test_fresh_capture_and_reopen_retain_exact_pins_without_certifying_history(self):
        first = self.ingest("z-observation")
        initial = self.current()
        self.assertEqual(1, initial["revision"])
        second = self.ingest("a-observation", expected=[pin(initial)])
        catalog = self.current()
        self.assertEqual(2, catalog["revision"])
        self.assertIsNone(catalog["value"]["value"]["baseline"])
        self.assertEqual([], catalog["watch_keys"])
        expected = sorted([pin(first), pin(second)], key=canonical_bytes)
        self.assertEqual(expected, catalog["value"]["value"]["observations"])
        with SQLiteStore(self.database, scope_id=SCOPE) as reopened:
            with reopened.snapshot() as view:
                verified = read_catalog(view, SCOPE, SOURCE)
                self.assertEqual(catalog, verified)
                self.assertEqual(expected, [pin(record) for record in catalog_observations(view, SCOPE, verified)])

    def test_ensure_empty_catalog_is_uninitialized_and_existing_ensure_does_not_write(self):
        self.ingest("legacy-invisible", capture=False)
        self.assertIsNone(self.current())
        result, catalog = self.mutate(lambda tx: ensure_catalog(tx, SOURCE))
        self.assertEqual("success", result["status"])
        self.assertEqual([], catalog["value"]["value"]["observations"])
        self.assertEqual([], catalog["value"]["value"]["admissions"])
        self.assertEqual({"observations": [], "history_complete": False}, catalog_population(catalog, 1))
        self.assertIsNone(catalog["value"]["value"]["baseline"])
        result, repeated = self.mutate(lambda tx: ensure_catalog(tx, SOURCE), expected=[pin(catalog)])
        self.assertEqual("success", result["status"])
        self.assertEqual(catalog, repeated)
        self.assertEqual(1, len(self.storage.history(entity_ref(catalog))))

    def test_initialization_merges_declared_legacy_and_current_intake_once_then_preserves_baseline(self):
        legacy = self.ingest("legacy", capture=False)
        current = self.ingest("current")
        original = self.current()
        result, initialized = self.initialize([legacy, current])
        self.assertEqual("success", result["status"], result)
        self.assertEqual(original["revision"] + 1, initialized["revision"])
        self.assertEqual(sorted([pin(legacy), pin(current)], key=canonical_bytes), initialized["value"]["value"]["observations"])
        baseline = deepcopy(initialized["value"]["value"]["baseline"])
        self.assertEqual(ADAPTER, baseline["adapter"])
        self.assertEqual(TIME, baseline["declared_at"])
        later = self.ingest("later", expected=[pin(initialized)])
        updated = self.current()
        self.assertEqual(baseline, updated["value"]["value"]["baseline"])
        self.assertIn(pin(later), updated["value"]["value"]["observations"])
        result, _ = self.initialize([legacy])
        self.assertEqual("E_POLICY_INVALID", result["error"]["code"])
        self.assertEqual(updated, self.current())

    def test_repeated_exact_append_is_a_noop_and_does_not_rewrite_creation_receipt(self):
        record = self.ingest("captured")
        before = self.current()
        result, duplicate = self.mutate(lambda tx: append_observation(tx, record), expected=[pin(record), pin(before)])
        self.assertEqual("success", result["status"], result)
        self.assertEqual(before, duplicate)
        self.assertEqual(1, len(self.storage.history(entity_ref(before))))

    def test_historical_population_survives_new_arrivals_and_later_baseline_initialization(self):
        legacy = self.ingest("legacy-before-catalog", capture=False)
        first = self.ingest("first-admitted")
        revision_one = self.current()
        first_population = {"observations": [pin(first)], "history_complete": False}
        self.assertEqual(first_population, catalog_population(revision_one, 1))
        second = self.ingest("second-admitted", expected=[pin(revision_one)])
        revision_two = self.current()
        second_population = {"observations": sorted([pin(first), pin(second)], key=canonical_bytes), "history_complete": False}
        self.assertEqual(second_population, catalog_population(revision_two, 2))
        result, initialized = self.initialize([legacy, first])
        self.assertEqual("success", result["status"], result)
        self.assertEqual(3, initialized["revision"])
        self.assertEqual(3, initialized["value"]["value"]["baseline"]["catalog_revision"])
        expected_admissions = sorted([
            {"observation": pin(first), "catalog_revision": 1},
            {"observation": pin(second), "catalog_revision": 2},
            {"observation": pin(legacy), "catalog_revision": 3},
        ], key=canonical_bytes)
        self.assertEqual(expected_admissions, initialized["value"]["value"]["admissions"])
        self.assertEqual(first_population, catalog_population(initialized, 1))
        self.assertEqual(second_population, catalog_population(initialized, 2))
        self.assertEqual({"observations": sorted([pin(first), pin(second), pin(legacy)], key=canonical_bytes),
                          "history_complete": True}, catalog_population(initialized, 3))
        later = self.ingest("after-baseline", expected=[pin(initialized)])
        current = self.current()
        self.assertEqual(first_population, catalog_population(current, 1))
        self.assertEqual(catalog_population(initialized, 3), catalog_population(current, 3))
        self.assertIn(pin(later), catalog_population(current, 4)["observations"])
        # Reconstruct inside an actual current-read-only transaction using only
        # the current catalog pin; no historical catalog read is authorized.
        result, selected = self.mutate(lambda tx: catalog_population(read_catalog(tx, SCOPE, SOURCE), 1),
                                       expected=[pin(current)])
        self.assertEqual("success", result["status"], result)
        self.assertEqual(first_population, selected)
        selected["observations"][0]["id"] = "changed"
        self.assertEqual(first_population, catalog_population(current, 1))

    def test_admission_membership_sort_revision_and_baseline_bindings_are_checked(self):
        first = self.ingest("first")
        before = self.current()
        self.ingest("second", expected=[pin(before)])
        result, initialized = self.initialize([first])
        self.assertEqual("success", result["status"], result)
        for change in (
            lambda value: value["value"]["value"]["admissions"].pop(),
            lambda value: value["value"]["value"]["admissions"].reverse(),
            lambda value: value["value"]["value"]["admissions"].append(deepcopy(value["value"]["value"]["admissions"][0])),
            lambda value: value["value"]["value"]["admissions"][0].update(catalog_revision=4),
            lambda value: value["value"]["value"]["admissions"][0].update(catalog_revision=True),
            lambda value: value["value"]["value"]["admissions"][0]["observation"].update(digest="0" * 64),
            lambda value: value["value"]["value"]["baseline"].update(catalog_revision=4),
            lambda value: value["value"]["value"]["baseline"].pop("catalog_revision"),
        ):
            changed = deepcopy(initialized)
            change(changed)
            with self.subTest(changed=changed):
                self.assert_error("E_STORAGE_UNAVAILABLE", read_catalog, ReadPort(lookup=changed), SCOPE, SOURCE)
                self.assert_error("E_STORAGE_UNAVAILABLE", catalog_population, changed, 1)
                self.assert_error("E_STORAGE_UNAVAILABLE", catalog_snapshot, changed, 1)
        for revision in (0, -1, True, "1", None):
            self.assert_error("E_SCHEMA_INVALID", catalog_population, initialized, revision)
            self.assert_error("E_SCHEMA_INVALID", catalog_snapshot, initialized, revision)
        self.assert_error("E_REVISION_CONFLICT", catalog_population, initialized, 4)
        self.assert_error("E_REVISION_CONFLICT", catalog_snapshot, initialized, 4)

    def test_reconstructed_snapshots_and_digests_match_exact_persisted_revision_history(self):
        legacy = self.ingest("legacy-outside-catalog", capture=False)
        result, empty = self.mutate(lambda tx: ensure_catalog(tx, SOURCE))
        self.assertEqual("success", result["status"], result)
        first = self.ingest("first-after-ensure", expected=[pin(empty)])
        appended = self.current()
        result, initialized = self.initialize([legacy, first])
        self.assertEqual("success", result["status"], result)
        self.ingest("last-after-baseline", expected=[pin(initialized)])
        current = self.current()
        actual_history = self.storage.history(entity_ref(current))
        self.assertEqual([empty, appended, initialized, current], actual_history)
        self.assertEqual([1, 2, 3, 4], [item["revision"] for item in actual_history])
        for actual in actual_history:
            with self.subTest(revision=actual["revision"]):
                reconstructed = catalog_snapshot(current, actual["revision"])
                self.assertEqual(actual, reconstructed)
                self.assertEqual(snapshot_digest(actual), snapshot_digest(reconstructed))
                self.assertEqual({"observations": actual["value"]["value"]["observations"],
                                  "history_complete": actual["value"]["value"]["baseline"] is not None},
                                 catalog_population(current, actual["revision"]))
        # A real current-read-only transaction can verify an old caller digest
        # using the reconstructed snapshot, with no old revision authorization.
        old_digest = snapshot_digest(appended)
        result, recovered = self.mutate(lambda tx: catalog_snapshot(read_catalog(tx, SCOPE, SOURCE), 2),
                                        expected=[pin(current)])
        self.assertEqual("success", result["status"], result)
        self.assertEqual(old_digest, snapshot_digest(recovered))
        recovered["value"]["value"]["admissions"][0]["observation"]["id"] = "changed"
        recovered["creation_receipt"]["id"] = "changed"
        self.assertEqual(appended, catalog_snapshot(current, 2))
        self.assertEqual(current, self.current())

    def test_initialization_rejects_wrong_source_and_unknown_or_invalid_declared_time_without_writes(self):
        record = self.ingest("legacy", capture=False)
        for source, declared_at, code in (
            (source_key("example:other"), TIME, "E_EVIDENCE_INVALID"),
            (SOURCE, {"state": "unknown", "reason": "not_reported"}, "E_SCHEMA_INVALID"),
            (SOURCE, {**TIME, "value": "2026-02-30T12:00:00Z"}, "E_SCHEMA_INVALID"),
        ):
            with self.subTest(source=source, declared_at=declared_at):
                result, _ = self.initialize([record], source=source, declared_at=declared_at)
                self.assertEqual(code, result["error"]["code"])
                self.assertIsNone(self.current(source))
        foreign_authority = {**pin(self.storage.get(record["creation_receipt"])), "scope_id": "synthetic:foreign"}
        # An undeclared foreign pin is refused before any evidence lookup.
        result, _ = self.initialize([record], authority=foreign_authority, expected=[])
        self.assertEqual("E_SCOPE_FORBIDDEN", result["error"]["code"])

    def test_initialization_rejects_duplicate_pins_and_explicit_overflow_without_truncation(self):
        record = self.ingest("legacy", capture=False)
        authority = pin(self.storage.get(record["creation_receipt"]))
        for refs, code in (([pin(record), pin(record)], "E_EVIDENCE_INVALID"),
                           ([{**pin(record), "id": str(index)} for index in range(MAX_CATALOG_OBSERVATIONS + 1)], "E_BUDGET_EXHAUSTED")):
            result, _ = self.mutate(lambda tx: initialize_catalog(
                tx, SOURCE, refs, adapter=ADAPTER, authority=authority, declared_at=TIME,
            ))
            self.assertEqual(code, result["error"]["code"])
            self.assertIsNone(self.current())

    def test_existing_catalog_shape_binding_and_watch_corruption_never_become_absence(self):
        self.ingest("captured")
        original = self.current()
        cases = []
        for change in (
            lambda value: value.update(record_type="observation"),
            lambda value: value.update(watch_keys=["unregistered-watch"]),
            lambda value: value["value"]["schema"].update(digest="0" * 64),
            lambda value: value["value"]["value"].update(extra=True),
            lambda value: value["value"]["value"].update(source=source_key("example:other")),
            lambda value: value["value"]["value"]["observations"].append(deepcopy(value["value"]["value"]["observations"][0])),
            lambda value: value["value"]["value"]["observations"][0].update(scope_id="synthetic:other"),
            lambda value: value["creation_receipt"].update(scope_id="synthetic:other"),
        ):
            changed = deepcopy(original)
            change(changed)
            cases.append(changed)
        cases += [None, [], {"value": {}}]
        for changed in cases:
            with self.subTest(changed=changed):
                if changed is None:
                    # A wrong-shaped non-absence response, not the port's absence sentinel.
                    changed = {"not": "a projection"}
                self.assert_error("E_STORAGE_UNAVAILABLE", read_catalog, ReadPort(lookup=changed), SCOPE, SOURCE)

    def test_missing_or_mismatched_catalog_observations_refuse_instead_of_returning_partial_results(self):
        record = self.ingest("captured")
        catalog = self.current()
        self.assert_error("E_STORAGE_UNAVAILABLE", catalog_observations, ReadPort(), SCOPE, catalog)
        changed = deepcopy(record)
        changed["body"]["source_identity"]["namespace"] = "example:wrong"
        self.assert_error("E_STORAGE_UNAVAILABLE", catalog_observations,
                          ReadPort(records={canonical_bytes(pin(record)): changed}), SCOPE, catalog)
        wrong_source = deepcopy(catalog)
        wrong_source["value"]["value"]["observations"] = [pin(changed)]
        self.assert_error("E_STORAGE_UNAVAILABLE", catalog_observations,
                          ReadPort(records={canonical_bytes(pin(changed)): changed}), SCOPE, wrong_source)

    def test_actual_backend_and_revision_refusals_propagate_unchanged(self):
        self.ingest("captured")
        catalog = self.current()
        for code in ("E_STORAGE_UNAVAILABLE", "E_REVISION_CONFLICT", "E_SCOPE_FORBIDDEN"):
            error = StorageError(code, "Synthetic port refusal.", retriable=True)
            for operation, args in ((read_catalog, (SCOPE, SOURCE)), (catalog_observations, (SCOPE, catalog))):
                with self.subTest(code=code, operation=operation):
                    raised = self.assert_error(code, operation, ReadPort(error=error), *args)
                    self.assertIs(error, raised)

    def test_historical_catalog_is_explicit_and_current_lookup_does_not_silently_use_it(self):
        first = self.ingest("first")
        before = self.current()
        self.ingest("second", expected=[pin(before)])
        with self.storage.snapshot() as view:
            self.assertEqual([pin(first)], [pin(value) for value in catalog_observations(view, SCOPE, before)])
            self.assertEqual(2, read_catalog(view, SCOPE, SOURCE)["revision"])
        stale_command = create_command("stale-catalog", "stale-catalog", scope_id=SCOPE, expected_revisions=[pin(before)])
        called = []

        def handler(tx):
            called.append(True)
            ensure_catalog(tx, SOURCE)
            return tx.success("created", {"matter": pin(tx.insert(tx.command["body"]["matter"]))})

        refused = self.storage.execute(stale_command, handler)
        self.assertEqual("E_REVISION_CONFLICT", refused["error"]["code"])
        self.assertEqual([], called)

    def test_catalog_results_are_detached_and_baseline_authority_cannot_cross_scope(self):
        record = self.ingest("captured")
        result, initialized = self.initialize([record])
        self.assertEqual("success", result["status"], result)
        with self.storage.snapshot() as view:
            retrieved = catalog_observations(view, SCOPE, initialized)
            retrieved[0]["body"]["source_identity"]["event_id"] = "changed"
            self.assertEqual(record, catalog_observations(view, SCOPE, initialized)[0])
        changed = deepcopy(initialized)
        changed["value"]["value"]["baseline"]["authority"]["scope_id"] = "synthetic:foreign"
        self.assert_error("E_STORAGE_UNAVAILABLE", read_catalog, ReadPort(lookup=changed), SCOPE, SOURCE)


if __name__ == "__main__":
    unittest.main()
