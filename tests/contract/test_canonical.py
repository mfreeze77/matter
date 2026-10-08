"""Behavioral and independently declared golden checks for matter-json-v1."""

import copy
import hashlib
import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import unittest

from matter.canonical import (
    ENCODING_VERSION,
    MAX_SAFE_INTEGER,
    CanonicalError,
    canonical_bytes,
    canonical_digest,
    loads,
    source_digest,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "canonical"


class CanonicalEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))
        cls.invalid = json.loads((FIXTURES / "invalid.json").read_text(encoding="utf-8"))

    def test_published_bytes_and_digests(self):
        self.assertEqual(ENCODING_VERSION, self.golden["encoding_version"])
        for vector in self.golden["vectors"]:
            with self.subTest(vector=vector["name"]):
                expected = bytes.fromhex(vector["canonical_utf8_hex"])
                # Check the readable oracle against the committed byte oracle.
                self.assertEqual(vector["canonical_json"].encode("utf-8"), expected)
                value = loads(vector["input_json"])
                self.assertEqual(canonical_bytes(value), expected)
                self.assertEqual(canonical_bytes(loads(expected)), expected)
                self.assertEqual(canonical_digest(value, vector["kind"]), vector["sha256"])
                self.assertEqual(
                    source_digest(vector["input_json"].encode("utf-8")),
                    vector["source_sha256"],
                )

    def test_published_inputs_accept_both_utf8_bytes_and_text(self):
        for vector in self.golden["vectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(
                    loads(vector["input_json"].encode("utf-8")),
                    loads(vector["input_json"]),
                )

    def test_published_invalid_inputs_are_refused(self):
        for vector in self.invalid["vectors"]:
            with self.subTest(vector=vector["name"]):
                value = (
                    bytes.fromhex(vector["input_hex"])
                    if "input_hex" in vector
                    else vector["input_json"]
                )
                with self.assertRaises(CanonicalError):
                    loads(value)

    def test_object_order_is_irrelevant_at_every_depth(self):
        left = {"z": 1, "a": {"z": 2, "a": 3}, "items": [{"y": 0, "x": 1}]}
        right = {"items": [{"x": 1, "y": 0}], "a": {"a": 3, "z": 2}, "z": 1}
        self.assertEqual(canonical_bytes(left), canonical_bytes(right))
        self.assertEqual(canonical_digest(left, "matter"), canonical_digest(right, "matter"))

    def test_ordered_arrays_keep_order_and_repetitions(self):
        self.assertEqual(canonical_bytes([2, 1, 2]), b"[2,1,2]")
        self.assertNotEqual(
            canonical_digest([2, 1, 2], "observation"),
            canonical_digest([1, 2, 2], "observation"),
        )

    def test_scalar_sorting_is_not_utf16_code_unit_sorting(self):
        value = {"\U00010000": 2, "\ue000": 1}
        self.assertEqual(canonical_bytes(value), b'{"\xee\x80\x80":1,"\xf0\x90\x80\x80":2}')

    def test_normalization_is_never_applied_to_keys_or_values(self):
        self.assertNotEqual(canonical_bytes("é"), canonical_bytes("e\u0301"))
        self.assertNotEqual(canonical_digest("é", "claim"), canonical_digest("e\u0301", "claim"))
        self.assertEqual(loads(r'{"\u00e9":1,"e\u0301":2}'), {"é": 1, "e\u0301": 2})

    def test_equivalent_escapes_have_one_canonical_form_but_distinct_source_digests(self):
        escaped = br'{"name":"\u00e9"}'
        literal = '{"name":"é"}'.encode("utf-8")
        self.assertEqual(canonical_bytes(loads(escaped)), canonical_bytes(loads(literal)))
        self.assertNotEqual(source_digest(escaped), source_digest(literal))

    def test_all_control_characters_have_exact_escape_spellings(self):
        value = "".join(chr(codepoint) for codepoint in range(32))
        expected = (
            br'"\u0000\u0001\u0002\u0003\u0004\u0005\u0006\u0007\b\t\n\u000b\f\r'
            br'\u000e\u000f\u0010\u0011\u0012\u0013\u0014\u0015\u0016\u0017'
            br'\u0018\u0019\u001a\u001b\u001c\u001d\u001e\u001f"'
        )
        self.assertEqual(canonical_bytes(value), expected)

    def test_surrogate_pairs_are_decoded_but_raw_python_surrogates_are_rejected(self):
        self.assertEqual(loads(r'"\ud83d\ude00"'), "😀")
        for value in ["\ud800", "\udfff", "\ud83d\ude00", {"\ud800": 1}, ["\udfff"]]:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(CanonicalError):
                    canonical_bytes(value)
                if type(value) is str:
                    with self.assertRaises(CanonicalError):
                        loads('"' + value + '"')

    def test_integers_are_bounded_and_booleans_stay_booleans(self):
        for value in [-MAX_SAFE_INTEGER, MAX_SAFE_INTEGER, -1, 0, 1]:
            with self.subTest(value=value):
                self.assertEqual(loads(str(value)), value)
                self.assertEqual(canonical_bytes(value), str(value).encode("ascii"))
                self.assertIs(type(loads(str(value))), int)
        self.assertEqual(canonical_bytes([True, False]), b"[true,false]")
        for value in [-MAX_SAFE_INTEGER - 1, MAX_SAFE_INTEGER + 1, 10**5000]:
            with self.assertRaises(CanonicalError):
                canonical_bytes(value)

    def test_huge_integer_token_is_rejected_without_unbounded_conversion(self):
        for sign in ["", "-"]:
            with self.subTest(sign=sign):
                with self.assertRaises(CanonicalError):
                    loads(sign + "9" * 5000)

    def test_integer_negative_zero_normalizes_to_zero(self):
        self.assertIs(type(loads("-0")), int)
        self.assertEqual(canonical_bytes(loads("-0")), b"0")
        self.assertEqual(
            canonical_digest(loads("-0"), "observation"),
            canonical_digest(loads("0"), "observation"),
        )
        self.assertNotEqual(source_digest(b"-0"), source_digest(b"0"))

    def test_no_float_value_is_coerced_to_an_integer_or_string(self):
        for value in [0.0, -0.0, 1.0, 0.25, float("nan"), float("inf"), -float("inf")]:
            for container in [value, [value], {"value": value}]:
                with self.subTest(value=value, value_type=type(container).__name__):
                    with self.assertRaises(CanonicalError):
                        canonical_bytes(container)

    def test_non_json_types_and_custom_subclasses_are_refused(self):
        class CustomInt(int):
            pass

        class CustomString(str):
            pass

        class CustomDict(dict):
            pass

        class CustomList(list):
            pass

        values = [
            b"bytes", bytearray(b"bytes"), memoryview(b"bytes"), (1,), {1}, frozenset({1}),
            Decimal("1"), Fraction(1, 2), object(), CustomInt(1), CustomString("text"),
            CustomDict(), CustomList(),
        ]
        for value in values:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(CanonicalError):
                    canonical_bytes(value)
        for key in [1, True, None, 1.5, CustomString("key")]:
            with self.subTest(key_type=type(key).__name__):
                with self.assertRaises(CanonicalError):
                    canonical_bytes({key: "value"})

    def test_decoder_rejects_non_text_input_without_coercion(self):
        for value in [None, 1, 1.0, [], {}, bytearray(b"{}"), memoryview(b"{}")]:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(CanonicalError):
                    loads(value)

    def test_reference_cycles_are_refused_but_repeated_subtrees_are_valid(self):
        loop_list = []
        loop_list.append(loop_list)
        loop_dict = {}
        loop_dict["self"] = loop_dict
        for value in [loop_list, loop_dict]:
            with self.assertRaises(CanonicalError):
                canonical_bytes(value)
        child = [1, 2]
        self.assertEqual(canonical_bytes([child, child]), b"[[1,2],[1,2]]")

    def test_nesting_resource_failures_remain_safe_canonical_errors(self):
        with self.assertRaises(CanonicalError):
            loads("[" * 2000 + "0" + "]" * 2000)
        value = 0
        for _ in range(2000):
            value = [value]
        with self.assertRaises(CanonicalError):
            canonical_bytes(value)

    def test_encoding_does_not_mutate_values(self):
        value = {"z": [3, 2, 1], "a": {"b": True, "a": None}}
        before = copy.deepcopy(value)
        keys_before = list(value)
        canonical_bytes(value)
        canonical_digest(value, "matter")
        self.assertEqual(value, before)
        self.assertEqual(list(value), keys_before)

    def test_digest_binds_version_and_kind_with_unambiguous_nul_framing(self):
        value = {"a": 1}
        expected = hashlib.sha256(b'matter-json-v1\x00observation\x00{"a":1}').hexdigest()
        self.assertEqual(canonical_digest(value, "observation"), expected)
        self.assertNotEqual(expected, canonical_digest(value, "claim"))
        self.assertNotEqual(expected, source_digest(b'{"a":1}'))
        self.assertNotEqual(
            expected,
            hashlib.sha256(b'matter-json-v2\x00observation\x00{"a":1}').hexdigest(),
        )

    def test_digest_kind_grammar_does_not_allow_framing_injection(self):
        for kind in ["matter", "operation-result", "evidence_relation", "example.record_v1", "a" * 128]:
            with self.subTest(kind=kind):
                self.assertRegex(canonical_digest({}, kind), r"^[a-f0-9]{64}$")
        for kind in [
            "", "a" * 129, "Matter", "1matter", "é", "a\x00b", "a\nb", " a", "a ",
            "a/b", "a:b", "a.", "a-", "a..b", "a--b", None, b"matter", 1,
        ]:
            with self.subTest(kind_type=type(kind).__name__):
                with self.assertRaises(CanonicalError):
                    canonical_digest({}, kind)

    def test_errors_do_not_echo_source_content_or_custom_representations(self):
        sensitive = "synthetic-sensitive-payload"
        invalid_inputs = [
            sensitive,
            '{"' + sensitive + '":1,"' + sensitive + '":2}',
            '"' + sensitive + "\ud800" + '"',
        ]
        for value in invalid_inputs:
            with self.assertRaises(CanonicalError) as caught:
                loads(value)
            self.assertNotIn(sensitive, str(caught.exception))
            self.assertNotIn(sensitive, repr(caught.exception.args))

        class UnsafeRepr:
            def __repr__(self):
                raise AssertionError("must not inspect a source object's representation")

        with self.assertRaises(CanonicalError):
            canonical_bytes(UnsafeRepr())
        with self.assertRaises(CanonicalError) as caught:
            canonical_digest({}, sensitive + "\x00")
        self.assertNotIn(sensitive, str(caught.exception))

    def test_published_source_digests_are_over_exact_arbitrary_bytes(self):
        for vector in self.golden["source_vectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(source_digest(bytes.fromhex(vector["source_hex"])), vector["sha256"])
        self.assertNotEqual(source_digest(b'{"a":1}'), source_digest(b'{"a":1}\n'))
        self.assertNotEqual(source_digest('"é"'.encode()), source_digest('"e\u0301"'.encode()))

    def test_source_digest_refuses_text_instead_of_choosing_an_encoding(self):
        for value in ["{}", None, 0, bytearray(b"{}"), memoryview(b"{}")]:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(CanonicalError):
                    source_digest(value)


if __name__ == "__main__":
    unittest.main()
