"""Immutable, source-aware observation intake on the transactional storage port.

Prepare a command once, then retain and retry that exact prepared command.
A new delivery has a new command identity but can resolve to an old observation.
The source index is a revisioned projection; evidence records are never replaced.
This module does not associate observations, count occurrences, interpret source
text, authorize host controls, or infer absence from an empty source history.
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .canonical import canonical_digest, source_digest
from .contracts import ContractError, command_digest, schema_for, validate_command
from .payloads import PayloadRead, PayloadStore
from .storage import PROJECTION_TYPE, Snapshot, Storage, StorageError, Transaction, entity_ref, pin
from .storage.base import _validate_fragment
from .time import known_time_key as _known_time_key, validate_interval


INDEX_NAMESPACE = "matter.observations"
_INDEX_FILE = "observation-source-index.schema.json"


def _family(scope_id: str, source: dict[str, Any]) -> dict[str, str]:
    _validate_fragment(scope_id, "identifier")
    source = _validate_fragment(source, "source_identity")
    return {"scope_id": scope_id, "namespace": source["namespace"], "event_id": source["event_id"]}


def source_index_ref(scope_id: str, source_identity: dict[str, Any]) -> dict[str, Any]:
    """Reference the source family; revision IDs do not create another family."""
    family = _family(scope_id, source_identity)
    return {
        "scope_id": scope_id, "namespace": INDEX_NAMESPACE, "record_type": PROJECTION_TYPE,
        "id": "source-" + canonical_digest(family, "observation.source-identity.v1"),
    }


@lru_cache(maxsize=1)
def _index_contract() -> tuple[dict[str, Any], Draft202012Validator]:
    content = files("matter._schemas").joinpath(_INDEX_FILE).read_bytes()
    schema = json.loads(content)
    Draft202012Validator.check_schema(schema)
    core = schema_for("record")
    registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
    descriptor = {
        "namespace": "matter", "id": "observation-source-index", "version": "1.0",
        "digest": source_digest(content),
    }
    return descriptor, Draft202012Validator(schema, registry=registry)


def _evidence_digest(observation: dict[str, Any]) -> str:
    """Compare declared evidence, excluding only documented delivery metadata.

    Observation IDs/namespaces are proposals, not source identity. Earliest
    availability, source times, locator, media type, availability status/reason,
    extractor, producer, lineage, supersession and extensions remain evidence.
    """
    provenance = deepcopy(observation["provenance"])
    provenance.pop("recorded_at")
    provenance.pop("run_id", None)
    body = deepcopy(observation["body"])
    body.pop("ingested_at")
    body["content"]["availability"].pop("checked_at")
    value = {
        "schema_version": observation["schema_version"], "scope_id": observation["scope_id"],
        "provenance": provenance, "body": body,
    }
    for key in ("extensions", "supersedes"):
        if key in observation:
            value[key] = observation[key]
    return canonical_digest(value, "observation.evidence.v1")


def _integrity_error() -> StorageError:
    return StorageError("E_STORAGE_UNAVAILABLE", "The observation source index could not be verified.")


def _index(view: Snapshot | Transaction, scope_id: str, source: dict[str, Any]) -> dict[str, Any] | None:
    reference = source_index_ref(scope_id, source)
    try:
        value = view.get(reference)
    except StorageError as exc:
        if exc.code == "E_NOT_FOUND":
            return None
        raise
    descriptor, validator = _index_contract()
    contents = value["value"]
    if (
        contents["schema"] != descriptor
        or not validator.is_valid(contents["value"])
        or contents["value"]["source"] != _family(scope_id, source)
    ):
        raise _integrity_error()
    return value


def _indexed_records(
    view: Snapshot | Transaction, index: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    family = index["value"]["value"]["source"]
    for entry in index["value"]["value"]["entries"]:
        reference = entry["observation"]
        if reference["scope_id"] != family["scope_id"]:
            raise _integrity_error()
        try:
            record = view.get(reference)
        except StorageError as exc:
            if exc.code == "E_NOT_FOUND":
                raise _integrity_error() from None
            raise
        identity = (record["scope_id"], record["namespace"], record["id"])
        source = record["body"]["source_identity"]
        if (
            identity in seen or _family(record["scope_id"], source) != family
            or source.get("revision_id") != entry.get("revision_id")
            or _evidence_digest(record) != entry["evidence_digest"]
            or record["body"]["content"]["digest"] != entry["payload_digest"]
        ):
            raise _integrity_error()
        # Every correction targets an already committed observation in this
        # family. Immutable append order also makes cycles impossible.
        for prior in record.get("supersedes", []):
            key = (prior["scope_id"], prior["namespace"], prior["id"])
            if key not in seen or pin(seen[key]) != prior:
                raise _integrity_error()
        seen[identity] = record
        records.append(record)
    return records


def _command(value: dict[str, Any]) -> dict[str, Any]:
    command = validate_command(value)
    if command["operation"] != "ingest_observation":
        raise ContractError("E_SCHEMA_INVALID", "Observation intake requires an ingest_observation command.")
    return command


class ObservationIngestor:
    """A trusted host's source-data handler, bound to one readable scope.

    The host remains responsible for admission/authority and truthful source
    classification. Source bytes never execute and cannot mint host controls.
    The payload port is separate from SQL; keep its immutable blobs when backing
    up a database. An interrupted transaction can leave an unreferenced blob.
    """

    def __init__(self, storage: Storage, payloads: PayloadStore) -> None:
        _validate_fragment(storage.scope_id, "identifier")
        if storage.scope_id != payloads.scope_id:
            raise StorageError("E_SCOPE_FORBIDDEN")
        self._storage, self._payloads = storage, payloads

    @property
    def scope_id(self) -> str:
        return self._storage.scope_id

    def _check_scope(self, command: dict[str, Any]) -> None:
        observation = command["body"]["observation"]
        if any(value != self.scope_id for value in (
            command["scope_id"], command["actor"]["scope_id"], command["authority"]["scope_id"],
            observation["scope_id"],
        )):
            raise StorageError("E_SCOPE_FORBIDDEN")

    def prepare(self, command: dict[str, Any]) -> dict[str, Any]:
        """Add dependency pins in one snapshot without replacing caller pins.

        Preparation is read-only and grants no authority. Retain its returned
        command for exact retries. A concurrent index change is an explicit
        E_REVISION_CONFLICT at execution; start a NEW command to prepare again.
        A journaled command is never silently rebuilt against newer evidence.
        """
        command = _command(command)
        self._check_scope(command)
        observation = command["body"]["observation"]
        expected = command["expected_revisions"]
        identities = set()
        for reference in expected:
            identity = (reference["scope_id"], reference["namespace"], reference["id"])
            if reference["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")
            if identity in identities:
                raise StorageError("E_SCHEMA_INVALID", "Expected revisions contain a duplicate identity.")
            identities.add(identity)

        def include(reference: dict[str, Any]) -> None:
            if reference["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")
            identity = (reference["scope_id"], reference["namespace"], reference["id"])
            if identity not in identities:
                expected.append(deepcopy(reference))
                identities.add(identity)

        with self._storage.snapshot() as view:
            try:
                journal = view.command_receipt(command["idempotency_key"])
            except StorageError as exc:
                if exc.code != "E_NOT_FOUND":
                    raise
            else:
                if command_digest(command) != journal["command_digest"]:
                    raise StorageError("E_IDEMPOTENCY_CONFLICT")
                return command
            index = _index(view, self.scope_id, observation["body"]["source_identity"])
            if index is not None:
                include(pin(index))
                for record in _indexed_records(view, index):
                    include(pin(record))
            # Explicit input pins are retained exactly, including stale/missing
            # pins; the transaction turns them into durable revision refusals.
            for reference in observation["provenance"]["parents"] + observation.get("supersedes", []):
                include(reference)
            # The source bucket covers future event IDs. Both catalog reads and
            # watch discovery are repeated under the write transaction, so a
            # first arrival/registration cannot pass an older prepared command.
            from .occurrences import _ReadCollector
            from .source_catalogs import read_catalog, source_key
            from .negative_dependencies import collect_arrival_watches
            guarded = _ReadCollector(view, include)
            read_catalog(guarded, self.scope_id, source_key(observation["body"]["source_identity"]["namespace"]))
            collect_arrival_watches(guarded, self.scope_id, observation)
        return validate_command(command)

    def ingest(self, command: dict[str, Any], *, payload: bytes | None = None) -> dict[str, Any]:
        """Execute a frozen command; raw bytes must match its declared digest.

        An exact journal replay precedes payload checks. A new source duplicate
        preserves the original snapshot without refreshing its availability.
        Use read_payload for the current local availability of those bytes.
        """
        command = _command(command)

        def handle(tx: Transaction) -> dict[str, Any]:
            return self._ingest(tx, payload)

        return self._storage.execute(command, handle)

    def _ingest(self, tx: Transaction, payload: bytes | None) -> dict[str, Any]:
        command = tx.command
        self._check_scope(command)
        observation = command["body"]["observation"]
        source = observation["body"]["source_identity"]
        content = observation["body"]["content"]
        if (observation["namespace"] in {INDEX_NAMESPACE, "matter.source_catalogs", "matter.coverage", "matter.negative_dependencies", "matter.controls"}
                or observation["namespace"].startswith("matter.controls.")):
            raise StorageError("E_SCOPE_FORBIDDEN", "The observation service namespaces are reserved.")
        if "occurred_interval" in observation["body"]:
            validate_interval(observation["body"]["occurred_interval"])
        if payload is not None:
            if type(payload) is not bytes:
                raise StorageError("E_SCHEMA_INVALID", "Original payloads must be bytes.")
            if (
                source_digest(payload) != content["digest"]
                or ("byte_length" in content and len(payload) != content["byte_length"])
                or content["availability"]["status"] != "available"
            ):
                raise StorageError("E_EVIDENCE_INVALID")

        index = _index(tx, self.scope_id, source)
        records = _indexed_records(tx, index) if index is not None else []
        digest = _evidence_digest(observation)
        same_revision = [
            record for record in records
            if record["body"]["source_identity"].get("revision_id") == source.get("revision_id")
        ]
        for prior in same_revision:
            if _evidence_digest(prior) == digest:
                return tx.success("duplicate", {
                    "observation": pin(prior), "observation_receipt": prior["creation_receipt"],
                })

        # Lineage is evidence. Check every declared parent; a generated summary
        # retains these pins and its declared producer/extractor unchanged.
        proposed_ref = entity_ref(observation)
        for parent in observation["provenance"]["parents"]:
            if parent["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")
            if entity_ref(parent) == proposed_ref:
                raise StorageError("E_EVIDENCE_INVALID", "An observation cannot be its own parent.")
            tx.get(parent)

        prior_pins = [pin(record) for record in records]
        supersedes = observation.get("supersedes", [])
        if len({canonical_digest(ref, "reference.v1") for ref in supersedes}) != len(supersedes):
            raise StorageError("E_EVIDENCE_INVALID", "A correction must cite each predecessor once.")
        for prior in supersedes:
            if prior["scope_id"] != self.scope_id:
                raise StorageError("E_SCOPE_FORBIDDEN")
            if (
                prior["record_type"] != "observation" or entity_ref(prior) == proposed_ref
                or prior not in prior_pins
            ):
                raise StorageError("E_EVIDENCE_INVALID", "A correction must supersede existing observations in its source family.")
            tx.get(prior)
        if same_revision and not any(pin(record) in supersedes for record in same_revision):
            raise StorageError(
                "E_SOURCE_IDENTITY_CONFLICT", affected_references=tuple(entity_ref(record) for record in same_revision),
            )

        # Verify payloads before publishing SQL references. Blob publication is
        # immutable and durable; a later SQL rollback may leave an orphan blob.
        if content["availability"]["status"] == "available":
            if payload is not None:
                if self._payloads.put(payload) != content["digest"]:
                    raise StorageError("E_EVIDENCE_INVALID")
            else:
                available = self._payloads.read(content)
                if available.status != "available":
                    raise StorageError("E_EVIDENCE_UNAVAILABLE")

        stored = tx.insert(observation)
        entry = {"observation": pin(stored), "evidence_digest": digest, "payload_digest": content["digest"]}
        if "revision_id" in source:
            entry["revision_id"] = source["revision_id"]
        entries = deepcopy(index["value"]["value"]["entries"]) if index is not None else []
        entries.append(entry)
        descriptor, validator = _index_contract()
        value = {"source": _family(self.scope_id, source), "entries": entries}
        if not validator.is_valid(value):
            raise StorageError("E_SCHEMA_INVALID")
        tx.put_projection(source_index_ref(self.scope_id, source), {"schema": descriptor, "value": value})
        from .source_catalogs import append_observation
        from .negative_dependencies import record_arrival
        append_observation(tx, stored)
        changes = record_arrival(tx, stored)
        result_body = {
            "observation": pin(stored), "observation_receipt": stored["creation_receipt"],
        }
        if changes:
            result_body["changes"] = changes
        return tx.success("committed", result_body)

    def revisions(
        self, source_identity: dict[str, Any], *, as_of: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Read this family's immutable revisions in commit order.

        An optional known-time boundary is inclusive and uses available_at,
        preserving unknown availability in unfiltered history but excluding it
        from a dated view. This is a source-history query, not coverage evidence.
        A supplied revision_id does not narrow the source family.
        """
        boundary = _known_time_key(as_of) if as_of is not None else None
        with self._storage.snapshot() as view:
            index = _index(view, self.scope_id, source_identity)
            records = _indexed_records(view, index) if index is not None else []
        if boundary is None:
            return records
        return [
            record for record in records
            if record["body"]["available_at"]["state"] == "known"
            and _known_time_key(record["body"]["available_at"]) <= boundary
        ]

    def heads(
        self, source_identity: dict[str, Any], *, as_of: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return revisions not explicitly superseded in the selected view.

        Revision labels and publication times establish no implicit ordering
        or retirement. Multiple unlinked revisions remain separate heads.
        """
        records = self.revisions(source_identity, as_of=as_of)
        superseded = [reference for record in records for reference in record.get("supersedes", [])]
        return [record for record in records if pin(record) not in superseded]

    def read_payload(self, reference: dict[str, Any]) -> PayloadRead:
        """Resolve current local bytes without changing historical availability."""
        if entity_ref(reference)["record_type"] != "observation":
            raise StorageError("E_EVIDENCE_INVALID", "Payload reads require an observation reference.")
        record = self._storage.get(reference)
        return self._payloads.read(record["body"]["content"])
