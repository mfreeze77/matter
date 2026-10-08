"""Exact temporal boundaries and separate knowledge/effective views."""

from copy import deepcopy
import unittest

from matter.storage import StorageError
from matter.time import (
    MAX_TEMPORAL_PACKETS, compare_times, contains, known_time_key,
    knowledge_eligible, overlaps, select_effective, select_knowledge, validate_interval,
)


UNKNOWN = {"state": "unknown", "reason": "not_reported", "detail": "The source did not supply this time."}
BOUNDS = ("closed", "closed_open", "open_closed", "open")


def known(stamp="2026-10-08T12:00:00Z"):
    digits = len(stamp.split(".", 1)[1][:-1]) if "." in stamp else 0
    return {"state": "known", "value": stamp,
            "precision": {0: "second", 3: "millisecond", 6: "microsecond", 9: "nanosecond"}[digits]}


def interval(start=None, end=None, bounds="closed"):
    return {"start": deepcopy(start if start is not None else known()),
            "end": deepcopy(end if end is not None else known("2026-10-08T13:00:00Z")), "bounds": bounds}


def reference(label, revision=1):
    return {"scope_id": "synthetic:time", "namespace": "example:temporal", "record_type": "matter",
            "id": label, "revision": revision}


def packet(label, *, available=None, effective=None, revision=1):
    return {"reference": reference(label, revision),
            "available_at": deepcopy(available if available is not None else known()),
            "effective": deepcopy(effective if effective is not None else interval())}


class KnowledgeTimeTests(unittest.TestCase):
    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(StorageError) as error:
            function(*args, **kwargs)
        self.assertEqual(code, error.exception.code)

    def test_precision_is_retained_while_equivalent_instants_compare_equal(self):
        times = [known("2026-10-08T12:00:00" + fraction + "Z")
                 for fraction in ("", ".000", ".000000", ".000000000")]
        before = deepcopy(times)
        for first in times:
            for second in times:
                self.assertEqual(0, compare_times(first, second))
                self.assertEqual(known_time_key(first), known_time_key(second))
        self.assertEqual(before, times)
        selected = select_knowledge([], as_of=times[2])
        self.assertEqual(times[2], selected["as_of"])
        self.assertEqual("microsecond", selected["as_of"]["precision"])

    def test_nanoseconds_are_not_rounded_to_microseconds_or_floats(self):
        earlier = known("2026-10-08T12:00:00.123456000Z")
        later = known("2026-10-08T12:00:00.123456001Z")
        self.assertEqual(-1, compare_times(earlier, later))
        self.assertEqual(1, compare_times(later, earlier))
        self.assertFalse(knowledge_eligible(later, earlier))
        self.assertTrue(knowledge_eligible(later, later))
        self.assertEqual(-1, compare_times(known("0001-01-01T00:00:00Z"), known("9999-12-31T23:59:59.999999999Z")))
        self.assertEqual(-1, compare_times(known("2024-02-29T23:59:59.999999999Z"), known("2024-03-01T00:00:00Z")))

    def test_known_times_reject_bad_calendars_offsets_leap_seconds_and_wrong_precision(self):
        for stamp in ("2026-02-29T12:00:00Z", "0000-01-01T00:00:00Z", "2026-10-08T24:00:00Z", "2026-10-08T12:00:60Z"):
            self.assert_error("E_SCHEMA_INVALID", known_time_key, {"state": "known", "value": stamp, "precision": "second"})
        for value in (
            {"state": "known", "value": "2026-10-08T12:00:00+00:00", "precision": "second"},
            {"state": "known", "value": "2026-10-08T12:00:00.123Z", "precision": "microsecond"},
            {"state": "known", "value": "2026-10-08T12:00:00Z", "precision": "second", "ingested_at": known()},
            UNKNOWN, None, True,
        ):
            self.assert_error("E_SCHEMA_INVALID", known_time_key, value)

    def test_unknown_times_have_no_inferred_order_or_ingestion_fallback(self):
        for first, second in ((UNKNOWN, known()), (known(), UNKNOWN), (UNKNOWN, UNKNOWN)):
            self.assertIsNone(compare_times(first, second))
        self.assertIsNone(knowledge_eligible(UNKNOWN, known()))
        self.assert_error("E_SCHEMA_INVALID", knowledge_eligible, known(), UNKNOWN)
        self.assert_error("E_SCHEMA_INVALID", compare_times, UNKNOWN, {"state": "known", "value": "bad", "precision": "second"})
        retained = validate_interval(interval(UNKNOWN, UNKNOWN))
        self.assertEqual(UNKNOWN, retained["start"])
        retained["start"]["detail"] = "changed returned value"
        self.assertEqual("The source did not supply this time.", UNKNOWN["detail"])

    def test_each_open_closed_membership_boundary_is_explicit(self):
        start, end = known(), known("2026-10-08T13:00:00Z")
        middle = known("2026-10-08T12:30:00Z")
        for bounds in BOUNDS:
            value = interval(start, end, bounds)
            with self.subTest(bounds=bounds):
                self.assertEqual(bounds in {"closed", "closed_open"}, contains(value, start))
                self.assertEqual(bounds in {"closed", "open_closed"}, contains(value, end))
                self.assertTrue(contains(value, middle))
                self.assertFalse(contains(value, known("2026-10-08T11:59:59.999999999Z")))
                self.assertFalse(contains(value, known("2026-10-08T13:00:00.000000001Z")))

    def test_reversed_intervals_refuse_but_equal_open_intervals_are_empty(self):
        at = known()
        later = known("2026-10-08T12:00:00.000000001Z")
        self.assert_error("E_EVIDENCE_INVALID", validate_interval, interval(later, at))
        self.assert_error("E_EVIDENCE_INVALID", contains, interval(later, at), UNKNOWN)
        for bounds in BOUNDS:
            value = interval(at, at, bounds)
            self.assertEqual(value, validate_interval(value))
            self.assertEqual(bounds == "closed", contains(value, at))
            self.assertEqual(bounds == "closed", overlaps(value, interval()))
            if bounds != "closed":
                self.assertFalse(contains(value, UNKNOWN))
                self.assertFalse(overlaps(value, interval(UNKNOWN, UNKNOWN)))

    def test_adjacent_interval_overlap_requires_both_touching_bounds_closed(self):
        start, touching, end = known(), known("2026-10-08T13:00:00Z"), known("2026-10-08T14:00:00Z")
        for first_bounds in BOUNDS:
            for second_bounds in BOUNDS:
                first, second = interval(start, touching, first_bounds), interval(touching, end, second_bounds)
                expected = first_bounds in {"closed", "open_closed"} and second_bounds in {"closed", "closed_open"}
                with self.subTest(left=first_bounds, right=second_bounds):
                    self.assertEqual(expected, overlaps(first, second))
                    self.assertEqual(expected, overlaps(second, first))
        self.assertTrue(overlaps(interval(), interval(known("2026-10-08T12:59:59.999999999Z"), end)))

    def test_unknown_interval_endpoints_are_not_infinite_bounds(self):
        at, earlier, later = known(), known("2026-10-08T11:00:00Z"), known("2026-10-08T14:00:00Z")
        unknown_start = interval(UNKNOWN, at)
        self.assertIsNone(contains(unknown_start, earlier))
        self.assertIsNone(contains(unknown_start, at))
        self.assertFalse(contains(unknown_start, later))
        unknown_end = interval(at, UNKNOWN)
        self.assertFalse(contains(unknown_end, earlier))
        self.assertIsNone(contains(unknown_end, later))
        self.assertFalse(contains(interval(at, UNKNOWN, "open"), at))
        self.assertIsNone(contains(interval(), UNKNOWN))
        self.assertIsNone(overlaps(unknown_start, interval(earlier, at)))
        self.assertFalse(overlaps(unknown_start, interval(later, later)))
        self.assertFalse(overlaps(interval(UNKNOWN, at, "closed_open"), interval(at, UNKNOWN)))
        self.assertIsNone(overlaps(interval(UNKNOWN, UNKNOWN), interval()))

    def test_late_discovery_changes_present_understanding_without_rewriting_old_knowledge(self):
        past = known("2026-10-06T10:00:00Z")
        yesterday = known("2026-10-07T12:00:00Z")
        discovery = known("2026-10-08T12:00:00Z")
        cancellation = packet("late-cancellation", available=discovery,
                              effective=interval(past, known("2026-10-10T00:00:00Z")))
        original = deepcopy(cancellation)
        old = select_effective([cancellation], effective_at=past, as_of=yesterday)
        self.assertEqual([], old["included"])
        self.assertEqual([{"reference": cancellation["reference"], "reason": "not_yet_available"}], old["excluded"])
        current = select_effective([cancellation], effective_at=past, as_of=discovery)
        self.assertEqual([cancellation["reference"]], current["included"])
        self.assertEqual(old, select_effective([cancellation], effective_at=past, as_of=yesterday))
        self.assertEqual(original, cancellation)

    def test_knowledge_and_effective_cuts_are_independent_and_clock_reads_create_no_events(self):
        earlier = known("2026-10-07T12:00:00Z")
        expired = packet("expired-effect", available=earlier, effective=interval(earlier, known(), "closed_open"))
        self.assertEqual([expired["reference"]], select_knowledge([expired], as_of=known())["included"])
        later = select_effective([expired], effective_at=known(), as_of=known())
        self.assertEqual([], later["included"])
        self.assertEqual("outside_effective_interval", later["excluded"][0]["reason"])
        for boundary in (earlier, known(), known("2026-10-09T12:00:00Z")):
            view = select_effective([], effective_at=boundary, as_of=boundary)
            self.assertEqual([], view["included"])
            self.assertEqual([], view["excluded"])
            self.assertEqual([], view["unknown"])

    def test_views_keep_unknown_reasons_and_apply_knowledge_before_effective_filtering(self):
        unavailable = packet("unknown-availability", available=UNKNOWN, effective=interval(UNKNOWN, UNKNOWN))
        future = packet("future", available=known("2026-10-09T00:00:00Z"), effective=interval(UNKNOWN, UNKNOWN))
        unclear = packet("unknown-effect", effective=interval(UNKNOWN, UNKNOWN))
        selected = packet("eligible")
        view = select_effective([unavailable, future, unclear, selected], effective_at=known(), as_of=known())
        self.assertEqual([selected["reference"]], view["included"])
        self.assertEqual([{"reference": future["reference"], "reason": "not_yet_available"}], view["excluded"])
        self.assertEqual([
            {"reference": unavailable["reference"], "reason": "unknown_availability"},
            {"reference": unclear["reference"], "reason": "unknown_effective_interval"},
        ], view["unknown"])
        self.assertEqual([unclear["reference"]], select_knowledge([unclear], as_of=known())["included"])

    def test_packets_are_closed_and_views_require_known_explicit_cuts(self):
        base = packet("valid")
        cases = []
        for field in ("reference", "available_at", "effective"):
            changed = deepcopy(base)
            changed.pop(field)
            cases.append(changed)
        changed = deepcopy(base)
        changed["ingested_at"] = known()
        cases.append(changed)
        changed = deepcopy(base)
        changed["reference"].pop("revision")
        cases.append(changed)
        for value in cases:
            self.assert_error("E_SCHEMA_INVALID", select_knowledge, [value], as_of=known())
        for items in (None, "source-record", {"source": "record"}):
            self.assert_error("E_SCHEMA_INVALID", select_knowledge, items, as_of=known())
        self.assert_error("E_SCHEMA_INVALID", select_knowledge, [], as_of=UNKNOWN)
        self.assert_error("E_SCHEMA_INVALID", select_effective, [], as_of=known(), effective_at=UNKNOWN)
        self.assert_error("E_SCHEMA_INVALID", select_effective, [], as_of=known(), effective_at=None)

    def test_distinct_versions_and_input_order_are_preserved_without_supersession_inference(self):
        first, revised, second = packet("same-identity", revision=1), packet("same-identity", revision=2), packet("another")
        values = [second, revised, first]
        result = select_knowledge(iter(values), as_of=known())
        self.assertEqual([item["reference"] for item in values], result["included"])
        self.assertEqual([], result["excluded"])
        altered_time = deepcopy(first)
        altered_time["available_at"] = UNKNOWN
        self.assert_error("E_SCHEMA_INVALID", select_knowledge, [first, altered_time], as_of=known())
        # Returned references and boundaries cannot mutate the caller's corpus.
        result["included"][0]["id"] = "mutated"
        result["as_of"]["value"] = "mutated"
        self.assertEqual("another", second["reference"]["id"])
        self.assertEqual(known(), select_knowledge([], as_of=known())["as_of"])

    def test_packet_budget_is_explicit_and_never_returns_a_truncated_view(self):
        calls = []

        def corpus(count):
            for number in range(count):
                calls.append(number)
                yield packet(str(number))

        accepted = select_knowledge(corpus(MAX_TEMPORAL_PACKETS), as_of=known())
        self.assertEqual(MAX_TEMPORAL_PACKETS, len(accepted["included"]))
        calls.clear()
        self.assert_error("E_BUDGET_EXHAUSTED", select_knowledge, corpus(MAX_TEMPORAL_PACKETS + 10), as_of=known())
        self.assertEqual(MAX_TEMPORAL_PACKETS + 1, len(calls))


if __name__ == "__main__":
    unittest.main()
