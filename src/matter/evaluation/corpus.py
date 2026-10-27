"""Frozen, source-linked episode manifests (MAT-036).

These contracts prepare data for later evaluation. They run no evaluator,
retrieve no external artifact and establish neither source truth nor model
ignorance of later facts. Only synthetic text may be embedded in a manifest.
"""

from __future__ import annotations

from copy import deepcopy
import re

from .._rule_values import FrozenValue, fragment
from ..canonical import canonical_bytes, canonical_digest, loads, source_digest
from ..contracts import ContractError
from ..time import compare_times, contains, known_time_key, knowledge_eligible, validate_interval


MAX_CORPUS_BYTES = 8_388_608
MAX_EPISODES = 256
MAX_ITEMS = 4096
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_FAMILIES = {"association", "recovery", "attention"}


def _fail(path, detail, code="E_EVIDENCE_INVALID"):
    raise ContractError(code, f"{path}: {detail}")


def _object(value, keys, path, optional=()):
    if type(value) is not dict or not set(keys) <= set(value) <= set(keys) | set(optional):
        _fail(path, "Unexpected or missing fields.", "E_SCHEMA_INVALID")
    return value


def _text(value, path):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        _fail(path, "A bounded nonempty string is required.", "E_SCHEMA_INVALID")
    return value


def _enum(value, choices, path):
    if type(value) is not str or value not in choices:
        _fail(path, "An explicitly supported value is required.", "E_SCHEMA_INVALID")
    return value


def _list(value, path, *, nonempty=False):
    if type(value) is not list or len(value) > MAX_ITEMS or (nonempty and not value):
        _fail(path, "A bounded array is required.", "E_SCHEMA_INVALID")
    return value


def _ids(value, path, *, nonempty=False):
    values = _list(value, path, nonempty=nonempty)
    for item in values:
        _text(item, path)
    if len(set(values)) != len(values):
        _fail(path, "Duplicate identities are forbidden.")
    return values


def _hash(value, path):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        _fail(path, "A lowercase SHA-256 is required.", "E_SCHEMA_INVALID")
    return value


def _source_key(value, path):
    _object(value, {"id", "revision", "sha256"}, path)
    _text(value["id"], path)
    if type(value["revision"]) is not int or not 1 <= value["revision"] <= (1 << 53) - 1:
        _fail(path, "A positive interoperable revision is required.", "E_SCHEMA_INVALID")
    _hash(value["sha256"], path)
    return value["id"], value["revision"]


def _time(value, path, *, known=False):
    try:
        return fragment(value, "known_time" if known else "time_value")
    except ValueError:
        _fail(path, "An explicit valid UTC time or unknown-time reason is required.", "E_SCHEMA_INVALID")


def _snapshot_source(source, path):
    _object(source, {"reference", "available_at", "artifact"}, path)
    key = _source_key(source["reference"], path + "/reference")
    _time(source["available_at"], path + "/available_at")
    artifact = source["artifact"]
    if type(artifact) is not dict:
        _fail(path + "/artifact", "An explicit artifact descriptor is required.")
    if artifact.get("kind") == "synthetic":
        _object(artifact, {"kind", "text"}, path + "/artifact")
        if type(artifact["text"]) is not str:
            _fail(path + "/artifact/text", "Synthetic text must be a string.")
        if source_digest(artifact["text"].encode("utf-8")) != source["reference"]["sha256"]:
            _fail(path + "/reference/sha256", "Synthetic source bytes do not match their declared hash.")
    elif artifact.get("kind") == "external":
        _object(artifact, {"kind", "reference", "permission_reference"}, path + "/artifact")
        _text(artifact["reference"], path + "/artifact/reference")
        _text(artifact["permission_reference"], path + "/artifact/permission_reference")
    else:
        _fail(path + "/artifact/kind", "Only synthetic text or external references are supported.")
    return key


def validate_episode(value):
    """Validate a closed, scoped episode and return a detached JSON value.

    Source revisions and label evidence are exact. Derived reports inherit all
    declared parent provenance groups; copies also retain parent occurrences.
    A declaration of independence is retained, not empirically established.
    """
    try:
        raw = canonical_bytes(value)
    except (ValueError, TypeError, RecursionError):
        _fail("episode", "Portable canonical JSON is required.", "E_SCHEMA_INVALID")
    if len(raw) > MAX_CORPUS_BYTES:
        _fail("episode", "Episode exceeds its byte bound.", "E_BUDGET_EXHAUSTED")
    episode = loads(raw)
    _object(episode, {"id", "scope_id", "boundary", "sources", "observations", "occurrences", "cases", "labels"}, "episode")
    _text(episode["id"], "episode/id")
    _text(episode["scope_id"], "episode/scope_id")
    try:
        interval = validate_interval(episode["boundary"])
    except ValueError:
        _fail("episode/boundary", "A valid episode interval is required.")
    _time(interval["start"], "episode/boundary/start", known=True)
    _time(interval["end"], "episode/boundary/end", known=True)
    if interval["bounds"] != "closed":
        _fail("episode/boundary", "Episode boundaries must be closed.")
    sources = {}
    for i, source in enumerate(_list(episode["sources"], "episode/sources")):
        path = f"episode/sources/{i}"
        key = _snapshot_source(source, path)
        if key in sources:
            _fail(path, "A source revision may be declared only once.")
        sources[key] = source
    observations = {}
    order = []
    for i, observation in enumerate(_list(episode["observations"], "episode/observations")):
        path = f"episode/observations/{i}"
        _object(observation, {"id", "source", "available_at", "occurred_at", "occurrence_ids", "provenance_groups", "derivation", "parents"}, path)
        identity = _text(observation["id"], path + "/id")
        if identity in observations:
            _fail(path, "An observation identity may be declared only once.")
        key = _source_key(observation["source"], path + "/source")
        source = sources.get(key)
        if source is None or source["reference"] != observation["source"]:
            _fail(path + "/source", "Unknown or altered source revision/hash.")
        _time(observation["available_at"], path + "/available_at")
        _time(observation["occurred_at"], path + "/occurred_at")
        # Unknown source availability never becomes known through a report.
        if (observation["available_at"]["state"] == "known" and
                (source["available_at"]["state"] != "known" or
                 compare_times(observation["available_at"], source["available_at"]) == -1)):
            _fail(path + "/available_at", "An observation cannot precede its source availability.")
        if observation["available_at"]["state"] == "known" and contains(interval, observation["available_at"]) is not True:
            _fail(path + "/available_at", "Known observation availability lies outside the episode boundary.")
        _ids(observation["occurrence_ids"], path + "/occurrence_ids")
        _ids(observation["provenance_groups"], path + "/provenance_groups", nonempty=True)
        parents = _ids(observation["parents"], path + "/parents")
        derivation = _enum(observation["derivation"], {"root", "copy", "summary", "correction"}, path + "/derivation")
        if (derivation == "root") != (not parents):
            _fail(path + "/derivation", "Root and derived reports require consistent explicit parents.")
        observations[identity] = observation
        order.append(identity)
    # Manifest order declares equal-time ordering; it never invents order for
    # timestamps. Require parents earlier in this declared sequence.
    seen = set()
    previous = None
    for identity in order:
        observation = observations[identity]
        path = "episode/observations/" + identity
        if not set(observation["parents"]) <= seen:
            _fail(path + "/parents", "Parents must be earlier declared observations in this episode.")
        if observation["available_at"]["state"] == "known":
            key = known_time_key(observation["available_at"])
            if previous is not None and key < previous:
                _fail(path + "/available_at", "Known observation availability must be chronological.")
            previous = key
        if observation["parents"]:
            parents = [observations[parent] for parent in observation["parents"]]
            groups = {group for parent in parents for group in parent["provenance_groups"]}
            if set(observation["provenance_groups"]) != groups:
                _fail(path + "/provenance_groups", "Derived reports must preserve every parent's provenance group.")
            for parent in parents:
                if (observation["available_at"]["state"] == "known" and
                        (parent["available_at"]["state"] != "known" or
                         compare_times(observation["available_at"], parent["available_at"]) == -1)):
                    _fail(path + "/available_at", "Derived availability cannot precede a parent.")
            if observation["derivation"] == "copy" and set(observation["occurrence_ids"]) != {item for parent in parents for item in parent["occurrence_ids"]}:
                _fail(path + "/occurrence_ids", "Copied reports must retain the original occurrences.")
        seen.add(identity)
    occurrences = {}
    for i, occurrence in enumerate(_list(episode["occurrences"], "episode/occurrences")):
        path = f"episode/occurrences/{i}"
        _object(occurrence, {"id", "observation_ids"}, path)
        identity = _text(occurrence["id"], path + "/id")
        members = _ids(occurrence["observation_ids"], path + "/observation_ids", nonempty=True)
        if identity in occurrences or not set(members) <= observations.keys():
            _fail(path, "Repeated occurrence or unknown observation membership.")
        occurrences[identity] = occurrence
    for identity, observation in observations.items():
        actual = {key for key, item in occurrences.items() if identity in item["observation_ids"]}
        if actual != set(observation["occurrence_ids"]):
            _fail("episode/observations/" + identity + "/occurrence_ids", "Occurrence memberships must agree in both directions.")
    cases = {}
    for i, case in enumerate(_list(episode["cases"], "episode/cases", nonempty=True)):
        path = f"episode/cases/{i}"
        _object(case, {"id", "family", "target_observation_ids", "eligibility"}, path)
        identity = _text(case["id"], path + "/id")
        _enum(case["family"], _FAMILIES, path + "/family")
        if identity in cases:
            _fail(path, "Cases require unique IDs and a supported outcome family.")
        if not set(_ids(case["target_observation_ids"], path + "/target_observation_ids")) <= observations.keys():
            _fail(path, "Unknown target observation.")
        eligibility = _object(case["eligibility"], {"state", "reason"}, path + "/eligibility")
        _enum(eligibility["state"], {"eligible", "excluded"}, path + "/eligibility/state")
        _text(eligibility["reason"], path + "/eligibility/reason")
        cases[identity] = case
    label_ids = set()
    for i, label in enumerate(_list(episode["labels"], "episode/labels")):
        path = f"episode/labels/{i}"
        _object(label, {"id", "revision", "case_id", "origin", "status", "outcome", "reviewer", "reviewed_at", "evidence", "reason"}, path)
        identity = _text(label["id"], path + "/id")
        if identity in label_ids or type(label["revision"]) is not int or label["revision"] < 1:
            _fail(path, "Label IDs must be unique and revisions positive.")
        label_ids.add(identity)
        _text(label["case_id"], path + "/case_id")
        if label["case_id"] not in cases:
            _fail(path + "/case_id", "Unknown case identity.")
        _enum(label["origin"], {"independent", "teacher", "derived"}, path + "/origin")
        _enum(label["status"], {"accepted", "disputed", "unresolved"}, path + "/status")
        _text(label["outcome"], path + "/outcome")
        _text(label["reason"], path + "/reason")
        reviewer = _object(label["reviewer"], {"kind", "role"}, path + "/reviewer")
        _enum(reviewer["kind"], {"human", "model"}, path + "/reviewer/kind")
        _text(reviewer["role"], path + "/reviewer/role")
        if (label["origin"] == "independent" and reviewer["kind"] != "human") or (label["origin"] == "teacher" and reviewer["kind"] != "model"):
            _fail(path + "/origin", "Label origin and reviewer provenance disagree.")
        _time(label["reviewed_at"], path + "/reviewed_at", known=True)
        for evidence in _list(label["evidence"], path + "/evidence", nonempty=True):
            _object(evidence, {"observation_id", "source"}, path + "/evidence")
            _text(evidence["observation_id"], path + "/evidence/observation_id")
            _source_key(evidence["source"], path + "/evidence/source")
            observation = observations.get(evidence["observation_id"])
            if observation is None or evidence["source"] != observation["source"]:
                _fail(path + "/evidence", "Label evidence must pin an exact observed source revision/hash.")
            if knowledge_eligible(observation["available_at"], label["reviewed_at"]) is not True:
                _fail(path + "/evidence", "Reviewer evidence was unavailable at its declared review time.")
    return deepcopy(episode)


class FrozenCorpus(FrozenValue):
    """Immutable canonical manifest plus separately retained verification facts."""
    __slots__ = ("_verified",)

    def __init__(self, manifest, *, source_payloads=None):
        try:
            encoded = canonical_bytes(manifest)
        except (ValueError, TypeError, RecursionError):
            _fail("corpus", "Portable canonical JSON is required.", "E_SCHEMA_INVALID")
        if len(encoded) > MAX_CORPUS_BYTES:
            _fail("corpus", "Corpus exceeds its byte bound.", "E_BUDGET_EXHAUSTED")
        value = loads(encoded)
        _object(value, {"schema_version", "id", "scope_id", "extraction_profile", "episodes"}, "corpus")
        if value["schema_version"] != "matter.episode-corpus.v1":
            _fail("corpus/schema_version", "Unsupported corpus version.", "E_VERSION_UNSUPPORTED")
        _text(value["id"], "corpus/id")
        _text(value["scope_id"], "corpus/scope_id")
        fragment(value["extraction_profile"], "component_ref")
        episodes = _list(value["episodes"], "corpus/episodes", nonempty=True)
        if len(episodes) > MAX_EPISODES:
            _fail("corpus/episodes", "Too many episodes.", "E_BUDGET_EXHAUSTED")
        if source_payloads is None:
            payloads = {}
        elif type(source_payloads) is dict:
            payloads = source_payloads.copy()
        else:
            _fail("corpus/source_payloads", "A mapping of exact source keys to bytes is required.", "E_SCHEMA_INVALID")
        identities, verified, declared_payload_keys = set(), set(), set()
        source_meanings, observation_meanings, occurrence_meanings = {}, {}, {}
        item_count = 0
        for episode in episodes:
            validate_episode(episode)
            identity = episode["id"]
            if identity in identities or episode["scope_id"] != value["scope_id"]:
                _fail("corpus/episodes", "Episode identities must be unique and scopes must match.")
            identities.add(identity)
            item_count += sum(len(episode[name]) for name in ("sources", "observations", "occurrences", "cases", "labels"))
            if item_count > MAX_ITEMS:
                _fail("corpus/episodes", "Corpus exceeds its item bound.", "E_BUDGET_EXHAUSTED")
            # Repeated shared evidence across episodes keeps its exact meaning.
            # This retains leakage grouping; partitioning is later MAT-037 work.
            for kind, entries, meanings in (("source", episode["sources"], source_meanings),
                                          ("observation", episode["observations"], observation_meanings),
                                          ("occurrence", episode["occurrences"], occurrence_meanings)):
                for entry in entries:
                    key = (entry["reference"]["id"], entry["reference"]["revision"]) if kind == "source" else entry["id"]
                    encoded_entry = canonical_bytes(entry)
                    if key in meanings and meanings[key] != encoded_entry:
                        _fail("corpus/episodes", "A shared " + kind + " identity has inconsistent content.")
                    meanings[key] = encoded_entry
            for source in episode["sources"]:
                ref = source["reference"]
                key = (identity, ref["id"], ref["revision"])
                declared_payload_keys.add(key)
                if source["artifact"]["kind"] == "synthetic":
                    verified.add(key)
                if key in payloads:
                    if type(payloads[key]) is not bytes or source_digest(payloads[key]) != ref["sha256"]:
                        _fail("corpus/source_payloads", "Supplied source bytes do not match their exact declaration.")
                    verified.add(key)
        if not payloads.keys() <= declared_payload_keys:
            _fail("corpus/source_payloads", "Supplied bytes name an unknown source revision.")
        self._freeze(value)
        object.__setattr__(self, "_verified", frozenset(verified))

    @property
    def sha256(self):
        return canonical_digest(self.value, "matter.episode-corpus.v1")

    @property
    def source_verification(self):
        """Byte verification is explicit; a manifest hash alone proves no bytes."""
        return [{"episode_id": episode["id"], "source": deepcopy(source["reference"]),
                 "status": "verified" if (episode["id"], source["reference"]["id"], source["reference"]["revision"]) in self._verified else "not_checked"}
                for episode in self.value["episodes"] for source in episode["sources"]]

    def prefix(self, *, as_of):
        """Return only available, byte-verified inputs, never reference labels.

        Future episode metadata, labels, cases and occurrence memberships are
        not included. Existing occurrence IDs remain as declared on each input;
        a future report does not leak through a complete membership list.
        """
        boundary = _time(as_of, "as_of", known=True)
        included, excluded, unknown = [], [], []
        for episode in self.value["episodes"]:
            seen = set()
            for observation in episode["observations"]:
                ref = {"episode_id": episode["id"], "observation_id": observation["id"]}
                eligible = knowledge_eligible(observation["available_at"], boundary)
                if eligible is None:
                    unknown.append({**ref, "reason": "unknown_availability"})
                elif not eligible:
                    excluded.append({**ref, "reason": "not_yet_available"})
                elif (episode["id"], observation["source"]["id"], observation["source"]["revision"]) not in self._verified:
                    unknown.append({**ref, "reason": "source_bytes_not_verified"})
                elif not set(observation["parents"]) <= seen:
                    unknown.append({**ref, "reason": "parent_not_admitted"})
                else:
                    included.append({"episode_id": episode["id"], "scope_id": episode["scope_id"], "observation": observation})
                    seen.add(observation["id"])
        return {"as_of": boundary, "included": included, "excluded": excluded, "unknown": unknown,
                "limits": ["Input availability does not establish model ignorance of later facts.",
                           "A manifest prefix does not simulate wall-clock latency or concurrent completion."]}

    def denominators(self):
        """Count frozen reference cases; no prediction or accuracy is measured.

        Primary eligibility needs an eligible case, verified target/evidence
        bytes, a unique accepted independent outcome and no unresolved/disputed
        independent labels. Teacher and derived labels never qualify a case.
        Every case belongs to exactly one case-count category.
        """
        categories = ("eligible", "excluded", "unlabeled", "teacher_only", "derived_only", "disputed", "unresolved", "unverified")
        counts = {name: 0 for name in categories}
        labels = {"independent": 0, "teacher": 0, "derived": 0}
        cases = []
        for episode in self.value["episodes"]:
            observations = {item["id"]: item for item in episode["observations"]}
            def verified(observation):
                source = observation["source"]
                return (episode["id"], source["id"], source["revision"]) in self._verified
            for label in episode["labels"]:
                labels[label["origin"]] += 1
            for case in episode["cases"]:
                selected = [item for item in episode["labels"] if item["case_id"] == case["id"]]
                independent = [item for item in selected if item["origin"] == "independent"]
                status = "eligible"
                if case["eligibility"]["state"] == "excluded":
                    status = "excluded"
                elif not selected:
                    status = "unlabeled"
                elif not independent:
                    status = "teacher_only" if any(item["origin"] == "teacher" for item in selected) else "derived_only"
                elif any(item["status"] == "disputed" for item in independent) or len({item["outcome"] for item in independent if item["status"] == "accepted"}) > 1:
                    status = "disputed"
                elif any(item["status"] == "unresolved" for item in independent):
                    status = "unresolved"
                elif not all(verified(observations[key]) for key in case["target_observation_ids"]) or not all(verified(observations[ref["observation_id"]]) for item in independent for ref in item["evidence"]):
                    status = "unverified"
                counts[status] += 1
                entry = {"episode_id": episode["id"], "case_id": case["id"], "family": case["family"], "category": status,
                         "label_ids": [item["id"] for item in selected]}
                if status == "eligible":
                    entry["reference_outcome"] = independent[0]["outcome"]
                cases.append(entry)
        return {"total": len(cases), "counts": counts, "label_counts": labels, "cases": cases}


def freeze_corpus(manifest, *, expected_sha256=None, source_payloads=None):
    """Capture detached metadata and verify optional host-supplied source bytes."""
    corpus = FrozenCorpus(manifest, source_payloads=source_payloads)
    if expected_sha256 is not None:
        _hash(expected_sha256, "expected_sha256")
        if corpus.sha256 != expected_sha256:
            _fail("corpus", "Frozen corpus differs from its expected digest.")
    return corpus


def load_jsonl(data, *, expected_sha256=None, source_payloads=None):
    """Load a bounded byte snapshot: header line followed by episode lines.

    The caller reads the file once and supplies exact bytes. No paths are opened
    here, no external content is fetched and later filesystem edits cannot
    change this snapshot. ``expected_sha256`` binds normalized manifest meaning;
    ``source_digest(data)`` separately binds original file bytes if needed.
    """
    if type(data) is not bytes:
        _fail("jsonl", "An original bytes snapshot is required.", "E_SCHEMA_INVALID")
    if len(data) > MAX_CORPUS_BYTES:
        _fail("jsonl", "Corpus exceeds its byte bound.", "E_BUDGET_EXHAUSTED")
    lines = data.splitlines()
    if not lines or not data.endswith(b"\n") or any(not line.strip() for line in lines):
        _fail("jsonl", "Nonempty complete JSONL rows are required.", "E_SCHEMA_INVALID")
    if len(lines) > MAX_EPISODES + 1:
        _fail("jsonl", "Too many episode rows.", "E_BUDGET_EXHAUSTED")
    try:
        header = loads(lines[0])
        _object(header, {"schema_version", "id", "scope_id", "extraction_profile"}, "jsonl/header")
        manifest = {**header, "episodes": [loads(line) for line in lines[1:]]}
    except (ValueError, TypeError, RecursionError):
        _fail("jsonl", "Strict canonical JSON rows are required.", "E_SCHEMA_INVALID")
    return freeze_corpus(manifest, expected_sha256=expected_sha256, source_payloads=source_payloads)
