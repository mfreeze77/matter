"""MAT-027 immutable question specifications and semantic identity.

Registry data is never executable code. Registry membership establishes exact
installed meaning, not source truth, model qualification or host authority.
"""

from __future__ import annotations

from ..canonical import canonical_bytes, canonical_digest, loads
from ..contracts import ContractError
from .._rule_values import fragment
from .contracts import MAX_WIRE_BYTES, PRIMITIVES, Question, _Frozen

import re


MAX_SPECIFICATIONS = 256
MAX_FIELDS = 128
RENDERER_ID = "canonical-json-bindings"
RENDERER_VERSION = "1.0"
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z", re.ASCII)
_MARKER = re.compile(r"\{\{([a-z][a-z0-9_]{0,63})\}\}", re.ASCII)
ASSOCIATION_OUTCOMES = ("same_matter", "related", "different", "insufficient")


class QuestionError(ContractError):
    """A structural spec/render path with no caller field names or values."""

    def __init__(self, path, detail, code="E_POLICY_INVALID"):
        self.path = tuple(path)
        super().__init__(code, "/".join(str(part) for part in path) + ": " + detail)


def _fail(path, detail, code="E_POLICY_INVALID"):
    raise QuestionError(path, detail, code)


def _object(value, required, path):
    if type(value) is not dict or set(value) != set(required):
        _fail(path, "Unexpected or missing fields.")


def _text(value, path):
    if type(value) is not str or not value.strip() or len(value) > 65536:
        _fail(path, "A bounded nonempty string is required.")


def _canonical(value, path, maximum=MAX_WIRE_BYTES):
    try:
        encoded = canonical_bytes(value)
    except (ValueError, TypeError, RecursionError):
        _fail(path, "Portable canonical JSON is required.")
    if len(encoded) > maximum:
        _fail(path, "The byte budget is exceeded.", "E_BUDGET_EXHAUSTED")
    return loads(encoded)


def _markers(text, path):
    matches = list(_MARKER.finditer(text))
    remainder = _MARKER.sub("", text)
    if "{{" in remainder or "}}" in remainder:
        _fail(path, "Only explicit named field markers are supported.")
    return [match.group(1) for match in matches]


def _static_criteria(value, path):
    if type(value) is str:
        if "{{" in value or "}}" in value or "[[level:" in value or "[[level." in value:
            _fail(path, "Criteria must be static and each Score level self-contained.")
        # Explicit reference-only aliases, not a claim to understand arbitrary
        # natural language. Richer semantic review still belongs to the host.
        if value.strip().lower().rstrip(".") in {
            "previous level", "next level", "same as previous level", "same as next level",
            "as above", "as below", "same as above", "same as below",
        }:
            _fail(path, "A reference-only criterion has no self-contained meaning.")
    elif type(value) is list:
        for index, child in enumerate(value):
            _static_criteria(child, path + [index])
    elif type(value) is dict:
        for key, child in value.items():
            _static_criteria(child, path + [key])


class QuestionSpecification(_Frozen):
    """Complete declared meaning; opaque catalogue identity is kept separate."""
    __slots__ = ()

    def __init__(self, value):
        data = _canonical(value, ["specification"], 262144)
        _object(data, ("schema_version", "namespace", "id", "family", "revision", "primitive", "instructions",
                       "criteria", "required_fields", "renderer"), ["specification"])
        if data["schema_version"] != "1.0":
            _fail(["specification", "schema_version"], "Unsupported question specification version.")
        for field in ("namespace", "id", "family", "revision", "primitive", "instructions"):
            _text(data[field], ["specification", field])
        if data["primitive"] not in PRIMITIVES:
            _fail(["specification", "primitive"], "The primitive has no supported question semantics.")
        _object(data["renderer"], ("id", "version"), ["specification", "renderer"])
        for field in ("id", "version"):
            _text(data["renderer"][field], ["specification", "renderer", field])
        fields = data["required_fields"]
        if type(fields) is not list or len(fields) > MAX_FIELDS:
            _fail(["specification", "required_fields"], "A bounded ordered binding list is required.")
        names = []
        for index, binding in enumerate(fields):
            path = ["specification", "required_fields", index]
            _object(binding, ("name", "path", "description"), path)
            if type(binding["name"]) is not str or _NAME.fullmatch(binding["name"]) is None:
                _fail(path + ["name"], "A simple lowercase binding name is required.")
            names.append(binding["name"])
            _text(binding["description"], path + ["description"])
            pointer = binding["path"]
            if type(pointer) is not list or len(pointer) > 32:
                _fail(path + ["path"], "An exact bounded packet path is required.")
            for position, part in enumerate(pointer):
                if not ((type(part) is str and part and len(part) <= 256) or
                        (type(part) is int and 0 <= part < 4096)):
                    _fail(path + ["path", position], "Path segments must be object keys or nonnegative array indices.")
        if len(set(names)) != len(names):
            _fail(["specification", "required_fields"], "Binding names must be unique.")
        markers = _markers(data["instructions"], ["specification", "instructions"])
        if set(markers) != set(names):
            _fail(["specification", "instructions"], "Every declared binding must be named and every marker declared.")
        # Reuse the executable MAT-026 primitive shape rather than create a
        # parallel type system. Its opaque placeholders are validated below.
        try:
            Question({"id": data["id"], "family": data["family"], "revision": data["revision"],
                      "primitive": data["primitive"], "instructions": data["instructions"],
                      "criteria": data["criteria"], "specification_digest": "0" * 64,
                      "rendering_revision": data["renderer"]["version"], "packet_digest": "0" * 64, "bound_ids": []})
        except ValueError:
            _fail(["specification", "criteria"], "The specification must satisfy its exact primitive contract.")
        try:
            fragment({"namespace": data["namespace"], "id": data["id"], "version": data["revision"],
                      "digest": "0" * 64}, "component_ref")
        except ValueError:
            _fail(["specification", "reference"], "The catalogue identity and revision must form a valid exact reference.")
        _static_criteria(data["criteria"], ["specification", "criteria"])
        if data["family"] == "association":
            if data["primitive"] != "choice" or tuple(option["id"] for option in data["criteria"]) != ASSOCIATION_OUTCOMES:
                _fail(["specification", "criteria"], "The initial association outcome set and order are fixed.")
        self._freeze(data)

    @property
    def semantic_digest(self):
        return canonical_digest({key: value for key, value in self.value.items() if key not in ("id", "namespace")},
                                "matter.semantic.question-meaning.v1")

    @property
    def reference(self):
        value = self.value
        return {"namespace": value["namespace"], "id": value["id"], "version": value["revision"],
                "digest": self.semantic_digest}


class QuestionRegistry:
    """An immutable bounded catalogue with one exact definition per family/revision."""
    __slots__ = ("_specifications",)

    def __init__(self, specifications=()):
        if not isinstance(specifications, (list, tuple)) or len(specifications) > MAX_SPECIFICATIONS:
            _fail(["registry"], "A bounded specification list is required.")
        checked = []
        families, identities = set(), set()
        for index, spec in enumerate(specifications):
            if not isinstance(spec, QuestionSpecification):
                _fail(["registry", index], "A validated immutable specification is required.")
            value = spec.value
            family = (value["family"], value["revision"])
            identity = (value["namespace"], value["id"], value["revision"])
            if family in families or identity in identities:
                _fail(["registry", index], "A family/revision or catalogue identity is already installed.")
            families.add(family)
            identities.add(identity)
            checked.append(spec.canonical)
        object.__setattr__(self, "_specifications", tuple(checked))

    def __setattr__(self, name, value):
        raise AttributeError("QuestionRegistry is immutable.")

    @property
    def specifications(self):
        return tuple(QuestionSpecification(loads(value)) for value in self._specifications)

    def resolve(self, reference):
        try:
            exact = fragment(reference, "component_ref")
        except ValueError:
            _fail(["registry", "reference"], "An exact version and semantic digest are required.")
        for spec in self.specifications:
            if spec.reference == exact:
                return spec
        _fail(["registry", "reference"], "The exact historical question specification is not installed.")


def semantic_diff(before, after, *, certificates=()):
    """Compare declared fields and flag matching certificate declarations for review.

    Certificate declarations are ``{reference, specification}`` component refs,
    not issued/trusted certificates. Reporting applicability review never
    verifies their existence, transfers qualification or grants authority.
    """
    if not isinstance(before, QuestionSpecification) or not isinstance(after, QuestionSpecification):
        _fail(["diff"], "Two validated question specifications are required.")
    if not isinstance(certificates, (list, tuple)) or len(certificates) > 256:
        _fail(["diff", "certificates"], "A bounded certificate declaration list is required.")
    changes = []
    def walk(left, right, path):
        if type(left) is dict and type(right) is dict:
            for key in sorted(set(left) | set(right)):
                if key not in left or key not in right:
                    changes.append({"path": path + [key], "kind": "added" if key not in left else "removed"})
                else:
                    walk(left[key], right[key], path + [key])
        elif type(left) is list and type(right) is list:
            for index in range(max(len(left), len(right))):
                if index >= len(left) or index >= len(right):
                    changes.append({"path": path + [index], "kind": "added" if index >= len(left) else "removed"})
                else:
                    walk(left[index], right[index], path + [index])
        elif canonical_bytes(left) != canonical_bytes(right):
            changes.append({"path": path, "kind": "changed"})
    walk(before.value, after.value, [])
    review = []
    changed = bool(changes)
    for index, declaration in enumerate(certificates):
        path = ["diff", "certificates", index]
        _object(declaration, ("reference", "specification"), path)
        try:
            ref = fragment(declaration["reference"], "component_ref")
            spec_ref = fragment(declaration["specification"], "component_ref")
        except ValueError:
            _fail(path, "Exact certificate and specification references are required.")
        if changed and spec_ref == before.reference and ref not in review:
            review.append(ref)
    return {"before": before.reference, "after": after.reference,
            "meaning_changed": before.semantic_digest != after.semantic_digest,
            "identity_changed": before.reference != after.reference,
            "changes": changes, "certificates_requiring_review": review,
            "qualification_transfer": "not_granted"}


def association_specification(*, namespace="matter", identity="association", revision="1.0",
                              observation_path=("observation",), candidate_path=("candidate",)):
    """Original unqualified initial association definition; static alternatives only."""
    if type(observation_path) not in (list, tuple) or type(candidate_path) not in (list, tuple):
        _fail(["association", "path"], "Packet paths must be explicit lists or tuples of segments.")
    return QuestionSpecification({
        "schema_version": "1.0", "namespace": namespace, "id": identity, "family": "association", "revision": revision,
        "primitive": "choice",
        "instructions": "Compare {{observation}} with {{candidate}}. Decide which relationship the supplied evidence supports. "
            "A shared topic alone does not establish continuing subject identity. Retain uncertainty when identity evidence is missing.",
        "criteria": [
            {"id": "same_matter", "description": "Both accounts concern one continuing subject under the supplied identity evidence."},
            {"id": "related", "description": "The accounts have a specific relevant connection while continuing identities remain distinct."},
            {"id": "different", "description": "The supplied evidence establishes distinct subjects without the proposed relevant connection."},
            {"id": "insufficient", "description": "The bounded evidence does not establish which declared relationship applies."},
        ],
        "required_fields": [
            {"name": "observation", "path": list(observation_path), "description": "The new account and its declared identity evidence."},
            {"name": "candidate", "path": list(candidate_path), "description": "One fixed candidate subject and its declared identity evidence."},
        ], "renderer": {"id": RENDERER_ID, "version": RENDERER_VERSION},
    })


def comparison_specification(kind, *, revision="1.0", left_path=("left",), right_path=("right",)):
    """Separate original topic, continuing-subject and event propositions for conformance."""
    meanings = {
        "topic": ("Do the two accounts discuss the same specific topic?", "A specific shared subject of discussion is supported.",
                  "The accounts do not share that specific topic; identity of a matter or event is not asked."),
        "matter": ("Do the two accounts concern one continuing subject across reports and time?",
                   "Supplied subject identity evidence supports one continuing matter.",
                   "Distinct continuing subjects are supported; shared terminology or a shared topic is insufficient."),
        "occurrence": ("Do the two accounts describe the same particular happening?",
                       "Supplied event identity evidence supports one actual occurrence.",
                       "Distinct happenings are supported, even if they concern one matter or repeat identical wording."),
    }
    if type(kind) is not str or kind not in meanings:
        _fail(["comparison", "kind"], "An explicit topic, matter or occurrence meaning is required.")
    if type(left_path) not in (list, tuple) or type(right_path) not in (list, tuple):
        _fail(["comparison", "path"], "Packet paths must be explicit lists or tuples of segments.")
    instruction, affirmative, negative = meanings[kind]
    return QuestionSpecification({
        "schema_version": "1.0", "namespace": "matter", "id": "same-" + kind,
        "family": "relationship." + kind, "revision": revision, "primitive": "proposition_probability",
        "instructions": "Compare {{left}} and {{right}}. " + instruction + " Judge the declared proposition from supplied evidence only.",
        "criteria": {"true": affirmative, "false": negative},
        "required_fields": [
            {"name": "left", "path": list(left_path), "description": "The first bounded account and its identity evidence."},
            {"name": "right", "path": list(right_path), "description": "The second bounded account and its identity evidence."},
        ], "renderer": {"id": RENDERER_ID, "version": RENDERER_VERSION},
    })
