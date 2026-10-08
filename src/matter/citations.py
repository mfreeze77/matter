"""Frozen, declared locator validation without source-truth inference.

Adapters run before the write transaction. A receipt records validation-time
availability, not a promise that bytes remain accessible. Descriptor equality
is declared provenance, not a cryptographic signature: the trusted host must
admit declarations from the configured adapter. No URI is followed here.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
import json
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from .canonical import canonical_bytes, canonical_digest, source_digest
from .contracts import _FORMAT_CHECKER, schema_for, validate_record
from .payloads import PayloadStore
from .storage import StorageError, pin
from .storage.base import _validate_fragment


__all__ = ["LocatorAdapter", "Utf8LineLocatorAdapter", "line_selector",
           "locator_validation_schema_ref", "verify_locator_validation"]


def _invalid() -> StorageError:
    return StorageError("E_EVIDENCE_INVALID", "The citation validation binding is invalid.")


@lru_cache(maxsize=3)
def _contract(name: str) -> tuple[dict[str, str], Draft202012Validator]:
    try:
        data = files("matter._schemas").joinpath(name + ".schema.json").read_bytes()
        schema = json.loads(data)
        Draft202012Validator.check_schema(schema)
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        return {
            "namespace": "matter", "id": name, "version": "1.0", "digest": source_digest(data),
        }, Draft202012Validator(schema, registry=registry, format_checker=_FORMAT_CHECKER)
    except (OSError, ValueError, TypeError, KeyError, SchemaError):
        raise StorageError("E_STORAGE_UNAVAILABLE", "The installed citation schema is unavailable.") from None


def _domain(name: str, body: dict[str, Any]) -> dict[str, Any]:
    descriptor, validator = _contract(name)
    canonical_bytes(body)
    if not validator.is_valid(body):
        raise _invalid()
    return {"schema": deepcopy(descriptor), "value": deepcopy(body)}


def line_selector(start: int, end: int) -> dict[str, Any]:
    """Select inclusive physical lines; validation reports reversed ranges."""
    _validate_fragment(start, "revision")
    _validate_fragment(end, "revision")
    return _domain("text-line-selector", {"start_line": start, "end_line": end})


def locator_validation_schema_ref() -> dict[str, str]:
    return deepcopy(_contract("locator-validation")[0])


def _locator(value: dict[str, Any]) -> dict[str, Any]:
    result = _validate_fragment(value, "locator")
    if "validation_receipt" in result:
        raise _invalid()
    return result


def _evidence(value: dict[str, Any]) -> dict[str, Any]:
    result = validate_record(value)
    if result["record_type"] not in {"observation", "judgment", "assessment", "claim"}:
        raise _invalid()
    return result


def _refs(values: list[dict[str, Any]], scope_id: str) -> list[dict[str, Any]]:
    if type(values) is not list:
        raise _invalid()
    found = {}
    for raw in values:
        ref = _validate_fragment(raw, "pinned_ref")
        if ref["scope_id"] != scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        key = (ref["scope_id"], ref["namespace"], ref["id"])
        if key in found:
            raise _invalid()
        found[key] = ref
    return sorted(found.values(), key=canonical_bytes)


def verify_locator_validation(
    value: dict[str, Any], *, evidence: dict[str, Any], locator: dict[str, Any],
    quotation: str | None, adapter: dict[str, Any], dependencies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pure binding check; dependency pins must also be read through storage.

    Returns the detached declaration body. This does not rerun an adapter or
    authenticate a provider; the configured host owns receipt admission.
    """
    # Schema loading remains outside malformed-evidence catches.
    descriptor, validator = _contract("locator-validation")
    try:
        canonical_bytes(value)
        source = _evidence(evidence)
        target = _locator(locator)
        expected_adapter = _validate_fragment(adapter, "component_ref")
        if quotation is not None:
            _validate_fragment(quotation, "text")
        if type(value) is not dict or set(value) != {"schema", "value"} or value["schema"] != descriptor:
            raise _invalid()
        body = value["value"]
        if not validator.is_valid(body):
            raise _invalid()
        refs = _refs(body["dependencies"], source["scope_id"])
        if (
            body["scope_id"] != source["scope_id"] or body["evidence"] != pin(source)
            or canonical_bytes(body["locator"]) != canonical_bytes(target) or body["quotation"] != quotation
            or body["adapter"] != expected_adapter or body["dependencies"] != refs
            or pin(source) not in refs
        ):
            raise _invalid()
        if source["record_type"] == "observation" and canonical_bytes(body["content"]) != canonical_bytes(source["body"]["content"]):
            raise _invalid()
        if dependencies is not None and refs != _refs(dependencies, source["scope_id"]):
            raise _invalid()
        result = body["result"]
        if result["status"] == "valid":
            expected_kind = {"selected_span": "exact_passage", "whole_artifact": "whole_artifact"}.get(target["kind"])
            if (result["kind"] != expected_kind or body["content"] is None
                    or body["content"]["availability"]["status"] != "available"):
                raise _invalid()
            if target["kind"] == "selected_span" and not quotation:
                raise _invalid()
            if target["kind"] == "whole_artifact" and (
                quotation is not None or result["selection_digest"] != body["content"]["digest"]
            ):
                raise _invalid()
        return deepcopy(body)
    except StorageError as error:
        if error.code in {"E_STORAGE_UNAVAILABLE", "E_SCOPE_FORBIDDEN"}:
            raise
        raise _invalid() from None
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _invalid() from None


class LocatorAdapter(Protocol):
    @property
    def reference(self) -> dict[str, Any]: ...

    def validate(
        self, evidence_snapshot: dict[str, Any], locator: dict[str, Any],
        *, quotation: str | None = None, checked_at: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class Utf8LineLocatorAdapter:
    """Exact original bytes, strict UTF-8 passages, and deliberate whole blobs.

    LF alone delimits lines. CRLF, BOM characters, Unicode normalization and
    spaces remain unchanged. The final LF does not create an extra empty line.
    Line numbers refer to a whole-artifact payload; excerpt-relative or other
    coordinate systems need a separate explicitly configured adapter.
    """

    def __init__(self, payloads: PayloadStore) -> None:
        _validate_fragment(payloads.scope_id, "identifier")
        self._payloads = payloads

    @property
    def scope_id(self) -> str:
        return self._payloads.scope_id

    @property
    def reference(self) -> dict[str, str]:
        definition = {
            "algorithm": "matter.utf8-line-locator.v1", "source": "observation_whole_artifact",
            "encoding": "utf-8-strict", "line_separator": "LF", "lines": "one_based_inclusive",
            "normalization": "none", "quotation": "exact_nonempty_substring_of_selected_bytes",
            "whole_artifact": "verified_exact_bytes_no_quotation", "uri": "exact_declared_identifier_no_fetch",
            "selector_schema": _contract("text-line-selector")[0],
        }
        return {"namespace": "matter", "id": "utf8-line-locator", "version": "1.0",
                "digest": canonical_digest(definition, "matter.locator-adapter.v1")}

    def validate(
        self, evidence_snapshot: dict[str, Any], locator: dict[str, Any],
        *, quotation: str | None = None, checked_at: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        evidence = _evidence(evidence_snapshot)
        if evidence["scope_id"] != self.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        target = _locator(locator)
        if quotation is not None:
            _validate_fragment(quotation, "text")
        checked = _validate_fragment(checked_at if checked_at is not None else {
            "state": "known", "value": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "precision": "second",
        }, "known_time")
        body = {
            "scope_id": self.scope_id, "evidence": pin(evidence),
            "content": deepcopy(evidence["body"]["content"]) if evidence["record_type"] == "observation" else None,
            "locator": target, "quotation": quotation, "adapter": self.reference,
            "dependencies": [pin(evidence)], "checked_at": checked,
        }

        def finish(status: str, reason: str | None = None, *, kind: str | None = None, data: bytes | None = None):
            body["result"] = ({"status": status, "reason": reason} if status != "valid" else {
                "status": status, "kind": kind, "selection_digest": source_digest(data),
            })
            return _domain("locator-validation", body)

        if body["content"] is None:
            return finish("unavailable", "unsupported_evidence_kind")
        content = body["content"]
        if target["kind"] == "unavailable":
            return finish("unavailable", "locator_unavailable")
        source_locator = content["locator"]
        if source_locator["kind"] != "whole_artifact":
            return finish("unavailable", "unsupported_source_locator")
        if target["uri"] != source_locator["uri"]:
            return finish("invalid", "source_uri_mismatch")
        if target["kind"] == "whole_artifact" and quotation is not None:
            return finish("invalid", "whole_artifact_has_quotation")
        if target["kind"] == "selected_span":
            descriptor, validator = _contract("text-line-selector")
            selector = target["selector"]
            if selector["schema"] != descriptor:
                return finish("unavailable", "unsupported_line_selector")
            if not validator.is_valid(selector["value"]):
                return finish("invalid", "malformed_line_selector")
            start, end = selector["value"]["start_line"], selector["value"]["end_line"]
            if end < start:
                return finish("invalid", "reversed_line_range")
            if quotation is None or not quotation:
                return finish("invalid", "quotation_required")
        try:
            read = self._payloads.read(content)
        except StorageError as error:
            if error.code == "E_EVIDENCE_INVALID":
                return finish("invalid", "payload_digest_or_length_mismatch")
            raise
        if read.digest != content["digest"]:
            return finish("invalid", "payload_digest_or_length_mismatch")
        if read.status != "available":
            return finish("unavailable", "payload_withheld" if read.status == "withheld" else "payload_unavailable")
        data = read.data
        if (type(data) is not bytes or source_digest(data) != content["digest"]
                or ("byte_length" in content and len(data) != content["byte_length"])):
            return finish("invalid", "payload_digest_or_length_mismatch")
        if target["kind"] == "whole_artifact":
            return finish("valid", kind="whole_artifact", data=data)
        try:
            data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return finish("unavailable", "unsupported_text_encoding")
        parts = data.split(b"\n")
        lines = [part + b"\n" for part in parts[:-1]]
        if parts[-1]:
            lines.append(parts[-1])
        if end > len(lines):
            return finish("invalid", "line_range_out_of_bounds")
        selected = b"".join(lines[start - 1:end])
        if quotation.encode("utf-8") not in selected:
            return finish("invalid", "quotation_absent_from_selected_lines")
        return finish("valid", kind="exact_passage", data=selected)
