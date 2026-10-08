"""Explicit temporal comparisons and knowledge/effective views.

Known UTC timestamps retain their declared precision and original spelling.
Comparison pads fractional digits internally, without rounding or rewriting
the input. Equal timestamps provide no ordering between concurrent events.
Unknown endpoints are neither invented timestamps nor infinite bounds.

Views accept explicit host-supplied temporal packets. They do not infer fields
from source records, establish corpus completeness, order source revisions,
apply supersession, or decide whether an observation establishes a fact. An
event's occurrence time is not automatically a proposition's effective time.
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from .canonical import canonical_bytes
from .storage import StorageError
from .storage.base import _validate_fragment


MAX_TEMPORAL_PACKETS = 4096
_CLOSED_START = frozenset({"closed", "closed_open"})
_CLOSED_END = frozenset({"closed", "open_closed"})

__all__ = [
    "MAX_TEMPORAL_PACKETS", "known_time_key", "compare_times", "validate_interval",
    "contains", "overlaps", "knowledge_eligible", "select_knowledge", "select_effective",
]


def _key(value: dict[str, Any]) -> tuple[str, str]:
    stamp = value["value"]
    return stamp[:19], stamp[20:-1].ljust(9, "0") if "." in stamp else "000000000"


def known_time_key(value: dict[str, Any]) -> tuple[str, str]:
    """Compare validated Gregorian UTC instants without losing nanoseconds.

    The result is an internal ordering key, not a rewritten time value. Missing
    fraction digits compare as zero; declared precision remains on the input.
    """
    return _key(_validate_fragment(value, "known_time"))


def _compare(left, right):
    if left["state"] == "unknown" or right["state"] == "unknown":
        return None
    first, second = _key(left), _key(right)
    return (first > second) - (first < second)


def compare_times(left: dict[str, Any], right: dict[str, Any]) -> int | None:
    """Return -1, 0, 1, or None when either explicit time is unknown."""
    first = _validate_fragment(left, "time_value")
    second = _validate_fragment(right, "time_value")
    return _compare(first, second)


def validate_interval(value: dict[str, Any]) -> dict[str, Any]:
    """Return a detached interval; refuse a known end before its known start.

    Equal endpoints describe a singleton only with closed bounds. Equal
    endpoints with any open bound describe an empty interval. Unknown endpoints
    remain explicit and do not become an unbounded interval.
    """
    interval = _validate_fragment(value, "time_interval")
    if _compare(interval["start"], interval["end"]) == 1:
        raise StorageError("E_EVIDENCE_INVALID", "A known interval end cannot precede its start.")
    return interval


def _empty(interval):
    return _compare(interval["start"], interval["end"]) == 0 and interval["bounds"] != "closed"


def _contains(interval, instant):
    if _empty(interval):
        return False
    if instant["state"] == "unknown":
        return None
    lower = _compare(instant, interval["start"])
    upper = _compare(instant, interval["end"])
    if lower == -1 or (lower == 0 and interval["bounds"] not in _CLOSED_START):
        return False
    if upper == 1 or (upper == 0 and interval["bounds"] not in _CLOSED_END):
        return False
    return None if lower is None or upper is None else True


def contains(interval: dict[str, Any], instant: dict[str, Any]) -> bool | None:
    """Test interval membership without treating unknown endpoints as infinity.

    A known violated bound proves exclusion even if the other bound is unknown.
    Otherwise unresolved bounds return None. An empty interval contains no
    instant, including when the proposed instant's time is unknown.
    """
    validated = validate_interval(interval)
    time = _validate_fragment(instant, "time_value")
    return _contains(validated, time)


def overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool | None:
    """Return definite overlap/exclusion, or None for unresolved endpoints.

    Known disjoint bounds and empty intervals prove exclusion. A positive
    overlap is asserted only when both intervals have fully known endpoints.
    """
    first, second = validate_interval(left), validate_interval(right)
    if _empty(first) or _empty(second):
        return False
    for before, after in ((first, second), (second, first)):
        order = _compare(before["end"], after["start"])
        if order == -1 or (order == 0 and (
            before["bounds"] not in _CLOSED_END or after["bounds"] not in _CLOSED_START
        )):
            return False
    if any(interval[field]["state"] == "unknown" for interval in (first, second) for field in ("start", "end")):
        return None
    return True


def knowledge_eligible(available_at: dict[str, Any], as_of: dict[str, Any]) -> bool | None:
    """Apply an inclusive known availability cut; unknown availability is None.

    Publication, ingestion, occurrence, and today's payload access do not supply
    this timestamp. The host must declare the earliest evidenced availability
    to the system or replay corpus being queried.
    """
    availability = _validate_fragment(available_at, "time_value")
    boundary = _validate_fragment(as_of, "known_time")
    order = _compare(availability, boundary)
    return None if order is None else order <= 0


def _packet(value):
    if type(value) is not dict or set(value) != {"reference", "available_at", "effective"}:
        raise StorageError("E_SCHEMA_INVALID", "A temporal packet requires a reference, availability and explicit effective interval.")
    return {
        "reference": _validate_fragment(value["reference"], "pinned_ref"),
        "available_at": _validate_fragment(value["available_at"], "time_value"),
        "effective": validate_interval(value["effective"]),
    }


def _select(items, as_of, effective_at=None):
    boundary = _validate_fragment(as_of, "known_time")
    effective_cut = _validate_fragment(effective_at, "known_time") if effective_at is not None else None
    result = {"as_of": boundary, "included": [], "excluded": [], "unknown": []}
    if effective_cut is not None:
        result["effective_at"] = effective_cut
    if isinstance(items, (str, bytes, bytearray, dict)):
        raise StorageError("E_SCHEMA_INVALID", "Temporal selection requires a collection of explicit packets.")
    try:
        iterator = iter(items)
    except TypeError:
        raise StorageError("E_SCHEMA_INVALID", "Temporal selection requires a collection of explicit packets.") from None
    seen = set()
    for index, value in enumerate(iterator):
        if index >= MAX_TEMPORAL_PACKETS:
            raise StorageError("E_BUDGET_EXHAUSTED", "The temporal view exceeds its supported packet bound.")
        packet = _packet(value)
        reference = packet["reference"]
        identity = canonical_bytes(reference)
        if identity in seen:
            raise StorageError("E_SCHEMA_INVALID", "A temporal view cannot repeat the same exact reference pin.")
        seen.add(identity)
        knowledge = _compare(packet["available_at"], boundary)
        if knowledge is None:
            result["unknown"].append({"reference": reference, "reason": "unknown_availability"})
        elif knowledge == 1:
            result["excluded"].append({"reference": reference, "reason": "not_yet_available"})
        elif effective_cut is None:
            result["included"].append(reference)
        else:
            applies = _contains(packet["effective"], effective_cut)
            if applies is None:
                result["unknown"].append({"reference": reference, "reason": "unknown_effective_interval"})
            elif applies:
                result["included"].append(reference)
            else:
                result["excluded"].append({"reference": reference, "reason": "outside_effective_interval"})
    return deepcopy(result)


def select_knowledge(items: Iterable[dict[str, Any]], *, as_of: dict[str, Any]) -> dict[str, Any]:
    """Partition a supplied corpus by knowledge, preserving input order.

    Packets are closed ``{reference, available_at, effective}`` values. The
    effective interval is validated and retained by the caller; it does not
    filter this view. Distinct explicit versions remain distinct inputs. No
    claim of complete coverage, source independence, or truth follows from an
    included pin or an empty result.
    """
    return _select(items, as_of)


def select_effective(
    items: Iterable[dict[str, Any]], *, effective_at: dict[str, Any], as_of: dict[str, Any],
) -> dict[str, Any]:
    """Select effective claims using an explicit, independently known corpus cut.

    Knowledge gating is first: a later discovery cannot appear in an earlier
    knowledge view even if its effective interval includes that earlier date.
    The function reads no clock and applies no source correction or lifecycle
    transition. A caller requesting today's understanding supplies today's
    explicit knowledge cut and the intended corpus itself.
    """
    effective_cut = _validate_fragment(effective_at, "known_time")
    return _select(items, as_of, effective_cut)
