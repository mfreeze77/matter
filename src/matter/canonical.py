"""Strict, domain-neutral ``matter-json-v1`` encoding and content digests.

This module implements the wire encoding, not record-schema validation. The
scaffold's more permissive :mod:`matter.jsonio` remains separate. See
``docs/contracts/canonical.md`` for framing, limits, and portable test vectors.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

__all__ = [
    "ENCODING_VERSION",
    "MAX_SAFE_INTEGER",
    "CanonicalError",
    "canonical_bytes",
    "canonical_digest",
    "loads",
    "source_digest",
]

ENCODING_VERSION = "matter-json-v1"
MAX_SAFE_INTEGER = (1 << 53) - 1
_MAX_INTEGER_DIGITS = str(MAX_SAFE_INTEGER)
_SURROGATE = re.compile("[\ud800-\udfff]")
_KIND = re.compile(r"[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*", re.ASCII)


class CanonicalError(ValueError):
    """An invalid encoding, value, or digest kind, with no payload in its message."""


def _check_string(value: str) -> None:
    if _SURROGATE.search(value) is not None:
        raise CanonicalError("canonical JSON requires Unicode scalar values")


def _check_value(value: Any, ancestors: set[int]) -> None:
    """Accept only JSON-native builtins, without coercion or custom hooks."""
    value_type = type(value)
    if value is None or value_type is bool:
        return
    if value_type is int:
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise CanonicalError("integer is outside the interoperable range")
        return
    if value_type is str:
        _check_string(value)
        return
    if value_type is not dict and value_type is not list:
        raise CanonicalError("canonical JSON does not support this value type")

    identity = id(value)
    if identity in ancestors:
        raise CanonicalError("canonical JSON cannot contain a reference cycle")
    ancestors.add(identity)
    try:
        if value_type is dict:
            for key, child in value.items():
                if type(key) is not str:
                    raise CanonicalError("canonical JSON requires string object keys")
                _check_string(key)
                _check_value(child, ancestors)
        else:
            for child in value:
                _check_value(child, ancestors)
    finally:
        ancestors.remove(identity)


def canonical_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 bytes for a JSON-native Python value.

    Only exact ``dict``, ``list``, ``str``, ``int``, ``bool``, and ``None`` values
    are accepted. Keys are scalar-value sorted at every depth. Arrays keep their
    input order. Integers are bounded; even integral ``float`` values are refused.
    Call :func:`loads` at an untrusted JSON boundary before syntax information
    such as duplicate keys or exponent notation can be lost by another decoder.
    """
    try:
        _check_value(value, set())
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except RecursionError:
        raise CanonicalError("JSON nesting exceeds implementation capacity") from None


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalError("canonical JSON forbids duplicate object keys")
        result[key] = value
    return result


def _integer(token: str) -> int:
    # The JSON parser has checked the integer grammar. Bound before int() so
    # enormous untrusted tokens cannot trigger Python's decimal conversion limit.
    digits = token[1:] if token.startswith("-") else token
    if len(digits) > len(_MAX_INTEGER_DIGITS) or (
        len(digits) == len(_MAX_INTEGER_DIGITS) and digits > _MAX_INTEGER_DIGITS
    ):
        raise CanonicalError("integer is outside the interoperable range")
    # JSON integer -0 has the same value as 0, and canonicalizes to ASCII 0.
    return int(token)


def _floating_number(token: str) -> None:
    raise CanonicalError("canonical JSON forbids floating-point number tokens")


def _constant(token: str) -> None:
    raise CanonicalError("canonical JSON forbids non-finite number tokens")


def loads(value: str | bytes) -> Any:
    """Decode strict UTF-8 JSON without BOM, duplicate keys, or float tokens.

    Input may use JSON whitespace and alternate valid escapes. The returned
    value is suitable for :func:`canonical_bytes`; it is not schema-validated.
    ``bytes`` are decoded explicitly as UTF-8, never auto-detected as UTF-16/32.
    """
    if type(value) is bytes:
        try:
            text = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise CanonicalError("canonical JSON input must be valid UTF-8") from None
    elif type(value) is str:
        text = value
    else:
        raise CanonicalError("canonical JSON input must be str or bytes")

    if text.startswith("\ufeff"):
        raise CanonicalError("canonical JSON input must not have a BOM")
    # Python str can contain raw surrogate code points. Reject them even before
    # parsing; an escaped, well-formed surrogate pair remains valid JSON input.
    _check_string(text)
    try:
        result = json.loads(
            text,
            object_pairs_hook=_object,
            parse_int=_integer,
            parse_float=_floating_number,
            parse_constant=_constant,
        )
        _check_value(result, set())
        return result
    except json.JSONDecodeError:
        raise CanonicalError("invalid JSON syntax") from None
    except RecursionError:
        raise CanonicalError("JSON nesting exceeds implementation capacity") from None


def canonical_digest(value: Any, kind: str) -> str:
    """Return lowercase SHA-256 for the version/kind-framed canonical bytes.

    Framing is ``ASCII(version) + NUL + ASCII(kind) + NUL + canonical_bytes``.
    Kind is 1..128 ASCII characters matching
    ``[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*``. No aliases or normalization apply.
    """
    if type(kind) is not str or not 1 <= len(kind) <= 128 or _KIND.fullmatch(kind) is None:
        raise CanonicalError("invalid canonical digest contract kind")
    preimage = (
        ENCODING_VERSION.encode("ascii")
        + b"\x00"
        + kind.encode("ascii")
        + b"\x00"
        + canonical_bytes(value)
    )
    return hashlib.sha256(preimage).hexdigest()


def source_digest(value: bytes) -> str:
    """Return lowercase SHA-256 over exact original bytes, without framing.

    Arbitrary encodings, invalid JSON, BOMs, and binary content are valid source
    bytes. This operation neither decodes nor normalizes the source.
    """
    if type(value) is not bytes:
        raise CanonicalError("source digest input must be bytes")
    return hashlib.sha256(value).hexdigest()
