"""Exact local citation ranges and immutable adapter declaration bindings."""

from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import tempfile
import unittest

from matter.canonical import source_digest
from matter.citations import (
    Utf8LineLocatorAdapter, line_selector, locator_validation_schema_ref, verify_locator_validation,
)
from matter.payloads import FilePayloadStore, PayloadRead
from matter.storage import StorageError, pin


SCOPE = "synthetic:citations"
URI = "urn:example:exact-source"
TIME = {"state": "known", "value": "2026-10-08T15:00:00Z", "precision": "second"}
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/contracts/records"


def observation(data=b"First line.\nExact qualification.\nLast line.\n"):
    value = json.loads((FIXTURES / "observation.json").read_text())
    value["scope_id"] = value["creation_receipt"]["scope_id"] = SCOPE
    value["body"]["content"].update(digest=source_digest(data), byte_length=len(data),
                                   locator={"kind": "whole_artifact", "uri": URI})
    return value


def selected(start=2, end=2):
    return {"kind": "selected_span", "uri": URI, "selector": line_selector(start, end)}


class ReadPort:
    scope_id = SCOPE

    def __init__(self, value=None, error=None):
        self.value, self.error, self.calls = value, error, []

    def read(self, content):
        self.calls.append(deepcopy(content))
        if self.error:
            raise self.error
        return self.value


class CitationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.payloads = FilePayloadStore(Path(temporary.name) / "payloads", scope_id=SCOPE)
        self.adapter = Utf8LineLocatorAdapter(self.payloads)

    def assert_error(self, code, operation, *args, **kwargs):
        with self.assertRaises(StorageError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def validate(self, source, locator, quotation=None, *, adapter=None):
        return (adapter or self.adapter).validate(source, locator, quotation=quotation, checked_at=TIME)

    def source(self, data=b"First line.\nExact qualification.\nLast line.\n"):
        self.payloads.put(data)
        return observation(data)

    def verify(self, declaration, source, locator, quotation=None, *, adapter=None, dependencies=None):
        return verify_locator_validation(declaration, evidence=source, locator=locator, quotation=quotation,
                                         adapter=adapter or self.adapter.reference, dependencies=dependencies)

    def test_descriptors_hash_exact_packaged_assets_and_are_detached(self):
        for filename, descriptor in (("locator-validation", locator_validation_schema_ref()),
                                     ("text-line-selector", line_selector(1, 2)["schema"])):
            data = files("matter._schemas").joinpath(filename + ".schema.json").read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), descriptor["digest"])
            self.assertEqual(filename, descriptor["id"])
        first = self.adapter.reference
        first["digest"] = "0" * 64
        self.assertNotEqual(first, self.adapter.reference)
        descriptor = locator_validation_schema_ref()
        descriptor["id"] = "changed"
        self.assertEqual("locator-validation", locator_validation_schema_ref()["id"])

    def test_selected_passage_binds_source_bytes_range_quote_and_versioned_adapter(self):
        source, locator = self.source(), selected()
        declaration = self.validate(source, locator, "Exact qualification.")
        body = self.verify(declaration, source, locator, "Exact qualification.", dependencies=[pin(source)])
        self.assertEqual({"status": "valid", "kind": "exact_passage",
                          "selection_digest": source_digest(b"Exact qualification.\n")}, body["result"])
        self.assertEqual(pin(source), body["evidence"])
        self.assertEqual(source["body"]["content"], body["content"])
        self.assertEqual([pin(source)], body["dependencies"])
        self.assertEqual(TIME, body["checked_at"])
        self.assertEqual(locator, body["locator"])
        self.assertEqual(self.adapter.reference, body["adapter"])

    def test_quote_elsewhere_reversed_and_out_of_bounds_are_explicit_invalid(self):
        source = self.source()
        cases = [(selected(), "First line.", "quotation_absent_from_selected_lines"),
                 (selected(3, 1), "First line.", "reversed_line_range"),
                 (selected(1, 4), "First line.", "line_range_out_of_bounds"),
                 (selected(), None, "quotation_required")]
        for locator, quote, reason in cases:
            with self.subTest(reason=reason):
                result = self.validate(source, locator, quote)["value"]["result"]
                self.assertEqual({"status": "invalid", "reason": reason}, result)
                self.assertNotIn("selection_digest", result)

    def test_unicode_case_spaces_and_line_endings_are_never_normalized(self):
        data = "\ufeffé One\r\ne\u0301 Two\n spaced \n".encode()
        source = self.source(data)
        for locator, quote in ((selected(1, 1), "\ufeffé One\r\n"),
                               (selected(2, 2), "e\u0301 Two\n"),
                               (selected(3, 3), " spaced \n")):
            self.assertEqual("valid", self.validate(source, locator, quote)["value"]["result"]["status"])
        for locator, quote in ((selected(1, 1), "é One\n"),
                               (selected(2, 2), "é Two"),
                               (selected(1, 1), "é one")):
            self.assertEqual("invalid", self.validate(source, locator, quote)["value"]["result"]["status"])
        bom = self.validate(source, selected(1, 1), "é One")["value"]["result"]
        self.assertEqual(source_digest("\ufeffé One\r\n".encode()), bom["selection_digest"])

    def test_only_lf_delimits_lines_and_trailing_lf_has_no_phantom_line(self):
        data = "one\rtwo\u2028three\n\nfour".encode()
        source = self.source(data)
        self.assertEqual("valid", self.validate(source, selected(1, 1), "one\rtwo\u2028three")["value"]["result"]["status"])
        self.assertEqual("valid", self.validate(source, selected(2, 2), "\n")["value"]["result"]["status"])
        self.assertEqual("valid", self.validate(source, selected(3, 3), "four")["value"]["result"]["status"])
        trailing = self.source(b"one\n")
        self.assertEqual("line_range_out_of_bounds", self.validate(trailing, selected(2, 2), "one")["value"]["result"]["reason"])

    def test_deliberate_whole_artifact_supports_binary_and_empty_bytes_without_quote(self):
        locator = {"kind": "whole_artifact", "uri": URI}
        for data in (b"", b"\xff\x00\xfe", b"one\ntwo\n"):
            source = self.source(data)
            result = self.validate(source, locator)
            self.assertEqual({"status": "valid", "kind": "whole_artifact", "selection_digest": source_digest(data)}, result["value"]["result"])
            self.verify(result, source, locator)
        quoted = self.validate(self.source(), locator, "First line.")
        self.assertEqual("whole_artifact_has_quotation", quoted["value"]["result"]["reason"])
        empty = self.source(b"")
        self.assertEqual("line_range_out_of_bounds", self.validate(empty, selected(1, 1), "anything")["value"]["result"]["reason"])

    def test_non_utf8_passage_is_unavailable_without_replacement_decoding(self):
        source = self.source(b"one\n\xffbroken\n")
        result = self.validate(source, selected(1, 1), "one")["value"]["result"]
        self.assertEqual({"status": "unavailable", "reason": "unsupported_text_encoding"}, result)

    def test_missing_withheld_and_declared_unavailable_payloads_remain_distinct_from_invalid(self):
        source = observation()
        result = self.validate(source, selected(), "Exact qualification.")
        self.assertEqual({"status": "unavailable", "reason": "payload_unavailable"}, result["value"]["result"])
        for status in ("withheld", "unavailable"):
            source["body"]["content"]["availability"].update(status=status, reason="Explicit synthetic restriction.")
            result = self.validate(source, selected(), "Exact qualification.")
            self.assertEqual("unavailable", result["value"]["result"]["status"])
            self.assertEqual("payload_withheld" if status == "withheld" else "payload_unavailable", result["value"]["result"]["reason"])
            self.verify(result, source, selected(), "Exact qualification.")

    def test_locator_unavailable_uri_mismatch_and_excerpt_coordinates_do_not_fallback(self):
        source = self.source()
        unknown = {"kind": "unavailable", "reason": "Source cannot be located."}
        self.assertEqual("locator_unavailable", self.validate(source, unknown)["value"]["result"]["reason"])
        wrong = selected()
        wrong["uri"] = URI + ":different"
        self.assertEqual("source_uri_mismatch", self.validate(source, wrong, "Exact qualification.")["value"]["result"]["reason"])
        source["body"]["content"]["locator"] = selected()
        self.assertEqual("unsupported_source_locator", self.validate(source, selected(), "Exact qualification.")["value"]["result"]["reason"])

    def test_unknown_coordinate_system_is_unavailable_but_malformed_known_selector_invalid(self):
        source = self.source()
        foreign = selected()
        foreign["selector"]["schema"]["id"] = "audio-time-selector"
        self.assertEqual({"status": "unavailable", "reason": "unsupported_line_selector"}, self.validate(source, foreign, "Exact qualification.")["value"]["result"])
        for start in (0, True, "1"):
            malformed = selected()
            malformed["selector"]["value"]["start_line"] = start
            self.assertEqual({"status": "invalid", "reason": "malformed_line_selector"}, self.validate(source, malformed, "Exact qualification.")["value"]["result"])
        for start in (0, True, 1.0, "1"):
            self.assert_error("E_SCHEMA_INVALID", line_selector, start, 2)

    def test_payload_port_digest_length_and_integrity_failures_cannot_validate(self):
        data, source = b"Exact qualification.\n", observation(b"Exact qualification.\n")
        outputs = [PayloadRead("available", "0" * 64, data, None),
                   PayloadRead("available", source_digest(data), b"different", None),
                   PayloadRead("available", source_digest(data), None, None)]
        for output in outputs:
            result = self.validate(source, selected(1, 1), "Exact qualification.", adapter=Utf8LineLocatorAdapter(ReadPort(output)))
            self.assertEqual("invalid", result["value"]["result"]["status"])
        corrupt = ReadPort(error=StorageError("E_EVIDENCE_INVALID"))
        self.assertEqual("invalid", self.validate(source, selected(1, 1), "Exact qualification.", adapter=Utf8LineLocatorAdapter(corrupt))["value"]["result"]["status"])
        source["body"]["content"]["byte_length"] += 1
        correct_bytes = ReadPort(PayloadRead("available", source_digest(data), data, None))
        self.assertEqual("invalid", self.validate(source, selected(1, 1), "Exact qualification.", adapter=Utf8LineLocatorAdapter(correct_bytes))["value"]["result"]["status"])

    def test_storage_outage_propagates_original_error_instead_of_invalid_citation(self):
        error = StorageError("E_STORAGE_UNAVAILABLE", retriable=True)
        adapter = Utf8LineLocatorAdapter(ReadPort(error=error))
        caught = self.assert_error("E_STORAGE_UNAVAILABLE", self.validate, observation(), selected(), "Exact qualification.", adapter=adapter)
        self.assertIs(error, caught)
        self.assertTrue(caught.retriable)

    def test_non_observation_has_explicit_unsupported_receipt_and_no_payload_access(self):
        claim = json.loads((FIXTURES / "claim.json").read_text())
        claim["scope_id"] = claim["creation_receipt"]["scope_id"] = SCOPE
        port = ReadPort(error=AssertionError("No implicit artifact field selection"))
        adapter = Utf8LineLocatorAdapter(port)
        result = adapter.validate(claim, {"kind": "whole_artifact", "uri": URI}, checked_at=TIME)
        self.assertIsNone(result["value"]["content"])
        self.assertEqual({"status": "unavailable", "reason": "unsupported_evidence_kind"}, result["value"]["result"])
        self.assertEqual([], port.calls)

    def test_scopes_calendar_and_legacy_receipt_links_are_checked(self):
        source = self.source()
        foreign = deepcopy(source)
        foreign["scope_id"] = foreign["creation_receipt"]["scope_id"] = "foreign"
        self.assert_error("E_SCOPE_FORBIDDEN", self.validate, foreign, selected(), "Exact qualification.")
        self.assert_error("E_SCHEMA_INVALID", self.adapter.validate, source, selected(), quotation="Exact qualification.", checked_at={**TIME, "value": "2026-02-30T00:00:00Z"})
        linked = selected()
        linked["validation_receipt"] = {"scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "old"}
        self.assert_error("E_EVIDENCE_INVALID", self.validate, source, linked, "Exact qualification.")

    def test_frozen_binding_rejects_source_quote_locator_adapter_schema_and_pin_changes(self):
        source, locator, quote = self.source(), selected(), "Exact qualification."
        valid = self.validate(source, locator, quote)
        mutations = [
            lambda d: d["schema"].update(digest="0" * 64),
            lambda d: d["value"].update(quotation="changed"),
            lambda d: d["value"]["locator"].update(uri="urn:changed"),
            lambda d: d["value"]["evidence"].update(digest="0" * 64),
            lambda d: d["value"]["content"].update(digest="0" * 64),
            lambda d: d["value"]["adapter"].update(version="2.0"),
            lambda d: d["value"].update(dependencies=[]),
            lambda d: d["value"]["dependencies"].append(deepcopy(d["value"]["dependencies"][0])),
            lambda d: d["value"].update(extra="unexpected"),
            lambda d: d["value"]["result"].update(kind="whole_artifact"),
            lambda d: d["value"]["checked_at"].update(value="2026-02-30T00:00:00Z"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                broken = deepcopy(valid)
                mutate(broken)
                self.assert_error("E_EVIDENCE_INVALID", self.verify, broken, source, locator, quote)
        self.assert_error("E_EVIDENCE_INVALID", self.verify, valid, source, locator, quote, dependencies=[])

    def test_domain_json_bindings_distinguish_boolean_and_integer_values(self):
        source = self.source()
        locator = selected()
        locator["selector"]["value"] = {"offset": 1}
        declaration = self.validate(source, locator, "Exact qualification.")
        self.verify(declaration, source, locator, "Exact qualification.")
        bool_locator = deepcopy(locator)
        bool_locator["selector"]["value"]["offset"] = True
        self.assert_error("E_EVIDENCE_INVALID", self.verify, declaration, source, bool_locator, "Exact qualification.")
        excerpt_source = deepcopy(source)
        excerpt_source["body"]["content"]["locator"] = deepcopy(locator)
        value = self.validate(excerpt_source, selected(), "Exact qualification.")
        value["value"]["content"]["locator"]["selector"]["value"]["offset"] = True
        self.assert_error("E_EVIDENCE_INVALID", self.verify, value, excerpt_source, selected(), "Exact qualification.")

    def test_valid_result_cannot_hide_unavailable_content_or_omit_passage_quotation(self):
        source = self.source()
        source["body"]["content"]["availability"].update(status="withheld", reason="Synthetic restriction.")
        result = self.validate(source, selected(), "Exact qualification.")
        result["value"]["result"] = {"status": "valid", "kind": "exact_passage", "selection_digest": "0" * 64}
        self.assert_error("E_EVIDENCE_INVALID", self.verify, result, source, selected(), "Exact qualification.")
        source = self.source()
        result = self.validate(source, selected(), "Exact qualification.")
        result["value"]["quotation"] = None
        self.assert_error("E_EVIDENCE_INVALID", self.verify, result, source, selected())

    def test_validation_results_and_input_values_are_defensively_detached(self):
        source, locator = self.source(), selected()
        originals = deepcopy((source, locator))
        result = self.validate(source, locator, "Exact qualification.")
        verified = self.verify(result, source, locator, "Exact qualification.")
        verified["content"]["locator"]["uri"] = "changed"
        result["value"]["locator"]["selector"]["value"]["end_line"] = 7
        self.assertEqual(originals, (source, locator))
        self.assertEqual(2, self.validate(source, locator, "Exact qualification.")["value"]["locator"]["selector"]["value"]["end_line"])


if __name__ == "__main__":
    unittest.main()
