"""Explicit candidate catalogs, exact current pins, and query integrity."""

from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from matter import candidate_sets
from matter.canonical import canonical_bytes
from matter.candidate_sets import (
    CANDIDATE_NAMESPACE, build_candidate_snapshot, candidate_set_ref, candidate_set_schema_ref,
    candidate_set_value, exact_candidates, read_candidate_set, read_dependency, read_member,
    require_current_candidates, unavailable_evidence,
)
from matter.storage import StorageError, entity_ref, pin, snapshot_digest


SCOPE = "synthetic:candidate-catalog"
TIME = {"state": "known", "value": "2026-10-08T15:00:00Z", "precision": "second"}
KEY = {"namespace": "example:catalog-subject", "value": "adapter-declared-key"}
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/contracts/records"


def component(identity):
    return {"namespace": "example", "id": identity, "version": "1.0", "digest": "0" * 64}


def record(kind="matter", identity="candidate", **updates):
    def scoped(value):
        if isinstance(value, dict):
            return {key: SCOPE if key == "scope_id" else scoped(child) for key, child in value.items()}
        if isinstance(value, list):
            return [scoped(child) for child in value]
        return value
    value = scoped(json.loads((FIXTURES / f"{kind}.json").read_text()))
    value.update(id=identity, **updates)
    return value


def query(subject, *, keys=None, mode="exact_keys"):
    return {
        "source": component("catalog-publisher"), "subject": entity_ref(subject), "candidate_type": "matter",
        "mode": mode, "matching_rule": component("exact-matching"),
        "selector": {"schema": component("catalog-selector"), "value": {"cohort": "explicit"}},
        "keys": deepcopy([KEY] if keys is None and mode == "exact_keys" else keys or []),
    }


def entry(candidate, *, keys=None, basis=()):
    return {"candidate": pin(candidate), "keys": deepcopy([KEY] if keys is None else keys), "basis": deepcopy(list(basis))}


def publication(subject, entries=(), *, mode="exact_keys", evidence=()):
    return {
        "query": query(subject, mode=mode), "entries": deepcopy(list(entries)),
        "coverage": {"status": "complete", "snapshot": component("catalog-coverage")},
        "evidence": deepcopy(list(evidence)), "as_of": deepcopy(TIME), "previous": None,
    }


def identity(value):
    return value["scope_id"], value["namespace"], value["id"]


class Port:
    def __init__(self, records=(), error=None):
        self.records = {identity(value): value for value in records}
        self.error, self.reads = error, []

    def lookup_identity(self, reference):
        self.reads.append(deepcopy(reference))
        if self.error is not None:
            raise self.error
        try:
            return self.records[identity(reference)]
        except KeyError:
            raise StorageError("E_NOT_FOUND") from None

    def get(self, reference):
        raise AssertionError("Historical snapshot reads must not satisfy a current candidate guard.")


class CandidateSetTests(unittest.TestCase):
    def setUp(self):
        self.subject = record("observation", "subject")
        self.candidate = record()
        self.evidence = record("observation", "key-evidence")
        self.authority = entity_ref(record("receipt", "host-authority"))
        self.policy = component("host-association-policy")
        self.port = Port([self.subject, self.candidate, self.evidence])

    def assert_error(self, code, operation, *args, **kwargs):
        with self.assertRaises(StorageError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def build(self, body=None, port=None):
        value = body if body is not None else publication(self.subject, [entry(self.candidate)], evidence=[pin(self.evidence)])
        return build_candidate_snapshot(port or self.port, SCOPE, value, self.policy, self.authority)

    def catalog(self, body=None, *, revision=1):
        snapshot = self.build(body)
        value = {
            "schema_version": "1.0", **candidate_set_ref(SCOPE, snapshot["query"]), "revision": revision,
            "creation_receipt": deepcopy(self.authority), "value": candidate_set_value(snapshot), "watch_keys": [],
        }
        self.port.records[identity(value)] = value
        return value

    def test_descriptor_binds_packaged_schema_and_returns_detached_values(self):
        data = files("matter._schemas").joinpath("candidate-set.schema.json").read_bytes()
        expected = {"namespace": "matter", "id": "candidate-set", "version": "1.0", "digest": hashlib.sha256(data).hexdigest()}
        self.assertEqual(expected, candidate_set_schema_ref())
        changed = candidate_set_schema_ref()
        changed["digest"] = "changed"
        self.assertEqual(expected, candidate_set_schema_ref())

    def test_query_address_binds_scope_subject_selector_source_rule_and_exact_values(self):
        base = query(self.subject)
        cases = [base]
        for field in ("source", "matching_rule"):
            value = deepcopy(base)
            value[field]["version"] = "2.0"
            cases.append(value)
        for selected in (1, True, "é", "e\u0301", ["a", "b"], ["b", "a"]):
            value = deepcopy(base)
            value["selector"]["value"] = selected
            cases.append(value)
        value = deepcopy(base)
        value["subject"]["id"] = "other-subject"
        cases.append(value)
        ids = [candidate_set_ref(SCOPE, value)["id"] for value in cases]
        self.assertEqual(len(ids), len(set(ids)))
        other = deepcopy(base)
        other["subject"]["scope_id"] = "synthetic:other"
        self.assertNotEqual(ids[0], candidate_set_ref("synthetic:other", other)["id"])
        second_key = {**KEY, "value": "second"}
        first_order = query(self.subject, keys=[KEY, second_key])
        reverse_order = query(self.subject, keys=[second_key, KEY])
        self.assertEqual(candidate_set_ref(SCOPE, first_order), candidate_set_ref(SCOPE, reverse_order))

    def test_publication_freezes_current_subject_and_canonical_sets_without_identity_rebinding(self):
        second = record("matter", "second")
        self.port.records[identity(second)] = second
        different = {**KEY, "value": "unrelated"}
        body = publication(self.subject, [entry(second, keys=[different, KEY]), entry(self.candidate)],
                           evidence=[pin(self.evidence), pin(self.subject)])
        original = deepcopy(body)
        snapshot = self.build(body)
        self.assertEqual(pin(self.subject), snapshot["subject"])
        self.assertEqual(self.policy, snapshot["policy"])
        self.assertEqual(self.authority, snapshot["authority"])
        self.assertNotIn("previous", snapshot)
        self.assertEqual(original, body)
        for name in ("entries", "evidence"):
            self.assertEqual(sorted(snapshot[name], key=canonical_bytes), snapshot[name])
        self.assertNotIn(KEY, self.candidate["body"]["identity_keys"])
        self.assertEqual([KEY], next(e for e in snapshot["entries"] if e["candidate"]["id"] == self.candidate["id"])["keys"])

    def test_exact_nominees_match_any_key_and_retain_nonmatching_catalog_entries(self):
        other = record("matter", "nonmatching")
        self.port.records[identity(other)] = other
        evidence = pin(self.evidence)
        body = publication(self.subject, [entry(other, keys=[{**KEY, "value": "other"}]),
                                        entry(self.candidate, keys=[{**KEY, "value": "alternative"}, KEY], basis=[evidence])])
        catalog = self.catalog(body)
        self.assertEqual(2, len(catalog["value"]["value"]["entries"]))
        self.assertEqual([{"candidate": pin(self.candidate), "basis": [evidence]}], exact_candidates(catalog))
        semantic = publication(self.subject, [entry(other, keys=[]), entry(self.candidate, keys=[])], mode="semantic")
        semantic["query"].pop("keys")
        self.assertEqual(2, len(exact_candidates(self.catalog(semantic))))

    def test_unmatched_empty_and_incomplete_catalogs_remain_distinct_explicit_inputs(self):
        empty = self.catalog(publication(self.subject))
        self.assertEqual([], exact_candidates(empty))
        self.assertEqual("complete", empty["value"]["value"]["coverage"]["status"])
        incomplete = publication(self.subject)
        incomplete["coverage"].update(status="partial", reason="Key source not yet available.")
        partial = self.catalog(incomplete, revision=2)
        self.assertEqual([], exact_candidates(partial))
        self.assertEqual("partial", partial["value"]["value"]["coverage"]["status"])
        self.assertTrue(partial["value"]["value"]["coverage"]["reason"])

    def test_duplicate_keys_candidate_identities_and_basis_references_are_rejected(self):
        cases = []
        body = publication(self.subject, [entry(self.candidate)])
        body["query"]["keys"].append(deepcopy(KEY))
        cases.append(body)
        cases.append(publication(self.subject, [entry(self.candidate, keys=[KEY, deepcopy(KEY)])]))
        cases.append(publication(self.subject, [entry(self.candidate), entry(self.candidate, keys=[])]))
        cases.append(publication(self.subject, [entry(self.candidate, basis=[pin(self.evidence), pin(self.evidence)])]))
        cases.append(publication(self.subject, evidence=[pin(self.evidence), pin(self.evidence)]))
        for body in cases:
            with self.subTest(body=body):
                self.assert_error("E_SCHEMA_INVALID", self.build, body)

    def test_wrong_candidate_type_self_nomination_and_unknown_ids_are_refused(self):
        self.assert_error("E_EVIDENCE_INVALID", self.build, publication(self.subject, [entry(self.evidence)]))
        own = publication(self.subject, [entry(self.subject)])
        own["query"]["candidate_type"] = "observation"
        self.assert_error("E_EVIDENCE_INVALID", self.build, own)
        missing = record("matter", "missing")
        self.assert_error("E_NOT_FOUND", self.build, publication(self.subject, [entry(missing)]))
        no_keys = publication(self.subject)
        no_keys["query"]["keys"] = []
        self.assert_error("E_SCHEMA_INVALID", self.build, no_keys)

    def test_all_considered_dependencies_are_current_even_for_nonmatching_entries(self):
        unrelated = record("matter", "nonmatch")
        self.port.records[identity(unrelated)] = unrelated
        body = publication(self.subject, [entry(unrelated, keys=[]), entry(self.candidate)], evidence=[pin(self.evidence)])
        catalog = self.catalog(body)
        newer = deepcopy(unrelated)
        newer["revision"] += 1
        newer["body"]["title"] = "Revised nonmatching candidate"
        self.port.records[identity(newer)] = newer
        self.assertEqual(catalog, read_candidate_set(self.port, SCOPE, pin(catalog)))
        self.assert_error("E_REVISION_CONFLICT", require_current_candidates, self.port, SCOPE, pin(catalog))
        self.assert_error("E_REVISION_CONFLICT", self.build, body)

    def test_current_revision_and_digest_pins_work_without_historical_reads(self):
        catalog = self.catalog()
        for reference in (pin(catalog), {**entity_ref(catalog), "digest": snapshot_digest(catalog)}):
            self.assertEqual(catalog, require_current_candidates(self.port, SCOPE, reference))
        digest_entry = entry(self.candidate)
        digest_entry["candidate"] = {**entity_ref(self.candidate), "digest": snapshot_digest(self.candidate)}
        body = publication(self.subject, [digest_entry])
        built = self.build(body)
        self.assertEqual(digest_entry["candidate"], built["entries"][0]["candidate"])
        newer = deepcopy(self.candidate)
        newer["revision"] += 1
        self.port.records[identity(newer)] = newer
        self.assert_error("E_REVISION_CONFLICT", self.build, body)

    def test_new_publication_and_new_matching_member_invalidate_old_catalog_pin(self):
        old = self.catalog()
        newcomer = record("matter", "new-matching-candidate")
        self.port.records[identity(newcomer)] = newcomer
        # Discovery is explicitly the publisher's duty; merely inserting an
        # unseen record does not falsely claim that this catalog was refreshed.
        self.assertEqual(old, require_current_candidates(self.port, SCOPE, pin(old)))
        body = publication(self.subject, [entry(self.candidate), entry(newcomer)])
        body["previous"] = pin(old)
        latest = self.catalog(body, revision=2)
        self.assertEqual(entity_ref(old), entity_ref(latest))
        self.assertEqual(2, len(exact_candidates(latest)))
        self.assert_error("E_REVISION_CONFLICT", read_candidate_set, self.port, SCOPE, pin(old))
        self.assert_error("E_REVISION_CONFLICT", read_candidate_set, self.port, SCOPE,
                          {**entity_ref(old), "digest": snapshot_digest(old)})

    def test_subject_basis_and_explicit_evidence_changes_are_not_refreshed(self):
        subject = record("matter", "mutable-subject")
        basis = record("matter", "mutable-basis")
        explicit = record("matter", "mutable-evidence")
        for value in (subject, basis, explicit):
            self.port.records[identity(value)] = value
        body = publication(subject, [entry(self.candidate, basis=[pin(basis)])], evidence=[pin(explicit)])
        catalog = self.catalog(body)
        for value in (subject, basis, explicit):
            with self.subTest(changed=value["id"]):
                changed = deepcopy(value)
                changed["revision"] += 1
                self.port.records[identity(value)] = changed
                self.assert_error("E_REVISION_CONFLICT", require_current_candidates, self.port, SCOPE, pin(catalog))
                self.port.records[identity(value)] = value

    def test_previous_publication_must_address_same_query(self):
        old = self.catalog()
        body = publication(self.subject, [entry(self.candidate)])
        body["previous"] = pin(old)
        self.build(body)
        body["previous"]["id"] = "another-query"
        self.assert_error("E_EVIDENCE_INVALID", self.build, body)
        body.pop("previous")
        self.assert_error("E_SCHEMA_INVALID", self.build, body)

    def test_stored_catalog_descriptor_address_shape_and_watch_integrity_are_enforced(self):
        original = self.catalog()
        mutations = [
            lambda v: v.update(watch_keys=["unexpected-watch"]),
            lambda v: v["value"]["schema"].update(digest="f" * 64),
            lambda v: v["value"]["value"].update(extra=True),
            lambda v: v["value"]["value"]["query"]["selector"].update(value={"cohort": True}),
            lambda v: v["value"]["value"]["subject"].update(id="different-subject"),
            lambda v: v["creation_receipt"].update(scope_id="foreign"),
            lambda v: v["value"]["value"]["as_of"].update(value="2026-02-30T00:00:00Z"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                broken = deepcopy(original)
                mutate(broken)
                self.port.records[identity(original)] = broken
                self.assert_error("E_EVIDENCE_INVALID", read_candidate_set, self.port, SCOPE, entity_ref(original))

    def test_cross_scope_is_refused_before_the_foreign_lookup(self):
        foreign = {**pin(self.candidate), "scope_id": "foreign"}
        self.port.reads.clear()
        self.assert_error("E_SCOPE_FORBIDDEN", read_dependency, self.port, SCOPE, foreign)
        self.assertEqual([], self.port.reads)
        query_value = query(self.subject)
        query_value["subject"]["scope_id"] = "foreign"
        self.assert_error("E_SCOPE_FORBIDDEN", candidate_set_ref, SCOPE, query_value)
        body = publication(self.subject, [entry(self.candidate, basis=[foreign])])
        self.assert_error("E_SCOPE_FORBIDDEN", self.build, body)
        self.assertTrue(all(ref["scope_id"] == SCOPE for ref in self.port.reads))

    def test_read_dependencies_handles_projections_and_wrong_kind_occupancy(self):
        catalog = self.catalog()
        self.assertEqual(catalog, read_dependency(self.port, SCOPE, pin(catalog)))
        self.assertEqual(self.subject, read_member(self.port, SCOPE, entity_ref(self.subject)))
        wrong = record("observation", self.candidate["id"])
        self.port.records[identity(self.candidate)] = wrong
        self.assert_error("E_EVIDENCE_INVALID", read_member, self.port, SCOPE, pin(self.candidate))
        self.assert_error("E_SCHEMA_INVALID", read_dependency, self.port, SCOPE, entity_ref(catalog))

    def test_port_errors_propagate_unchanged_instead_of_becoming_empty_candidates(self):
        catalog = self.catalog()
        for code in ("E_STORAGE_UNAVAILABLE", "E_REVISION_CONFLICT", "E_NOT_FOUND"):
            error = StorageError(code, retriable=True)
            port = Port(error=error)
            self.assertIs(error, self.assert_error(code, read_candidate_set, port, SCOPE, pin(catalog)))
            self.assertIs(error, self.assert_error(code, read_dependency, port, SCOPE, pin(self.evidence)))
            self.assertIs(error, self.assert_error(code, self.build, None, port))

    def test_availability_uses_only_explicit_observation_evidence_without_payload_access(self):
        unavailable = record("observation", "unavailable-evidence")
        unavailable["body"]["content"]["availability"].update(status="unavailable", reason="Private source reason.")
        withheld = record("observation", "withheld-evidence")
        withheld["body"]["content"]["availability"].update(status="withheld", reason="Private withholding reason.")
        for value in (unavailable, withheld):
            self.port.records[identity(value)] = value
        body = publication(self.subject, [entry(self.candidate, basis=[pin(withheld)])], evidence=[pin(unavailable)])
        catalog = self.catalog(body)
        self.assertEqual(["observation_evidence_unavailable", "observation_evidence_withheld"], unavailable_evidence(self.port, SCOPE, catalog))
        member_only = publication(unavailable, [entry(self.candidate)])
        self.assertEqual([], unavailable_evidence(self.port, SCOPE, self.catalog(member_only)))

    def test_results_are_detached_and_missing_packaged_schema_remains_storage_error(self):
        catalog = self.catalog()
        expected = deepcopy(catalog)
        result = read_candidate_set(self.port, SCOPE, pin(catalog))
        result["value"]["value"]["entries"][0]["keys"][0]["value"] = "changed"
        nominees = exact_candidates(catalog)
        nominees[0]["candidate"]["id"] = "changed"
        self.assertEqual(expected, catalog)
        candidate_sets._contract.cache_clear()
        self.addCleanup(candidate_sets._contract.cache_clear)
        with patch.object(candidate_sets, "files", side_effect=OSError("Synthetic missing package")):
            self.assert_error("E_STORAGE_UNAVAILABLE", read_candidate_set, self.port, SCOPE, pin(catalog))


if __name__ == "__main__":
    unittest.main()
