"""Immutable provider-neutral rule meanings and exact local schema registries.

These values declare semantics; they grant no host capability and execute no
source text. Registries are constructed by trusted host code, never a model.
"""

from copy import deepcopy
import re

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .canonical import canonical_bytes, source_digest
from .contracts import ContractError, _FORMAT_CHECKER, schema_for
from ._rule_values import FrozenValue, bounded, descriptor, domain, fragment, same, unique


__all__ = ["SchemaDefinition", "SchemaRegistry", "RuleDefinition", "RuleRegistry"]


class SchemaDefinition(FrozenValue):
    __slots__ = ("_reference",)

    def __init__(self, namespace, identity, version, schema):
        canonical_bytes(schema)
        if not isinstance(schema, dict) or schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ContractError("E_POLICY_INVALID", "A local Draft 2020-12 schema is required.")
        try:
            Draft202012Validator.check_schema(schema)
        except Exception:
            raise ContractError("E_POLICY_INVALID", "The local domain schema is invalid.") from None
        def closed(value, *, root=False):
            if isinstance(value, dict):
                if not root and "$id" in value:
                    raise ContractError("E_POLICY_INVALID", "Nested domain schema resource IDs are unsupported.")
                if any(keyword in value for keyword in ("$dynamicRef", "$recursiveRef", "$dynamicAnchor")):
                    raise ContractError("E_POLICY_INVALID", "Dynamic domain schema references are unsupported.")
                for keyword in ("$ref",):
                    if keyword in value and (not isinstance(value[keyword], str) or not value[keyword].startswith("#")):
                        raise ContractError("E_POLICY_INVALID", "Domain schemas permit only self-contained fragment references.")
                for keyword in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
                    for child in value.get(keyword, {}).values():
                        closed(child)
                for keyword in ("additionalProperties", "unevaluatedProperties", "propertyNames", "items",
                                "contains", "unevaluatedItems", "not", "if", "then", "else", "contentSchema"):
                    if keyword in value:
                        closed(value[keyword])
                for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
                    for child in value.get(keyword, []):
                        closed(child)
        closed(schema, root=True)
        self._freeze(schema)
        ref = fragment({"namespace": namespace, "id": identity, "version": version,
                        "digest": source_digest(self._encoded)}, "component_ref")
        object.__setattr__(self, "_reference", canonical_bytes(ref))

    @property
    def reference(self):
        from .canonical import loads
        return loads(self._reference)


class SchemaRegistry:
    """Frozen exact schema bindings; unknown references never fetch the network."""
    __slots__ = ("_entries",)

    def __init__(self, definitions=()):
        values = tuple(definitions)
        if len(values) > 128 or any(not isinstance(item, SchemaDefinition) for item in values):
            raise ContractError("E_POLICY_INVALID")
        identities, references = set(), set()
        core = schema_for("record")
        schema_ids = {core["$id"]}
        for item in values:
            ref = item.reference
            identity = (ref["namespace"], ref["id"], ref["version"])
            key = canonical_bytes(ref)
            if identity in identities or key in references:
                raise ContractError("E_POLICY_INVALID", "A schema meaning/version may be installed only once.")
            identities.add(identity)
            references.add(key)
            schema = item.value
            schema_id = schema.get("$id")
            if not isinstance(schema_id, str) or not schema_id or schema_id in schema_ids:
                raise ContractError("E_POLICY_INVALID", "Installed schema resource IDs must be explicit and unique.")
            schema_ids.add(schema_id)
        object.__setattr__(self, "_entries", tuple((canonical_bytes(item.reference), item) for item in values))

    def __setattr__(self, name, value):
        raise AttributeError("SchemaRegistry is immutable.")

    def resolve(self, reference):
        ref = fragment(reference, "component_ref")
        key = canonical_bytes(ref)
        for candidate, definition in self._entries:
            if candidate == key:
                return definition
        raise ContractError("E_POLICY_INVALID", "The exact domain schema is not installed.")

    def validate(self, value):
        candidate = fragment(value, "domain_value")
        definition = self.resolve(candidate["schema"])
        try:
            # Isolation also closes local JSON Pointers into annotation data:
            # a fragment can point at any JSON object, including one that was
            # not a schema-bearing keyword during construction. That object
            # must not gain access to another installed domain/core resource.
            schema = definition.value
            isolated = Registry().with_resources([(schema["$id"], Resource.from_contents(schema))])
            valid = Draft202012Validator(schema, registry=isolated,
                                        format_checker=_FORMAT_CHECKER).is_valid(candidate["value"])
        except Exception:
            raise ContractError("E_POLICY_INVALID", "A domain schema reference cannot be resolved locally.") from None
        if not valid:
            raise ContractError("E_EVIDENCE_INVALID", "A domain value does not satisfy its installed schema.")
        return deepcopy(candidate)


class RuleDefinition(FrozenValue):
    """Content-addressed complete rule meaning; public copies cannot mutate it."""
    __slots__ = ()

    def __init__(self, value, *, schemas):
        definition = domain("rule-definition", value)["value"]
        if not isinstance(schemas, SchemaRegistry):
            raise ContractError("E_POLICY_INVALID")
        schemas.resolve(definition["input_schema"])
        schemas.resolve(definition["output_schema"])
        outcomes = definition["outcomes"]
        labels = [item["label"] for item in outcomes]
        unique(labels)
        requirements = definition["evidence_requirements"]
        unique(requirements["allowed_kinds"])
        unique(requirements["allowed_origins"])
        unique(requirements["required_roles"])
        unique(requirements["locator_adapters"])
        incomplete = next((item for item in outcomes if item["label"] == requirements["incomplete_label"]), None)
        if incomplete is None or incomplete["evaluation_status"] != "insufficient_evidence":
            raise ContractError("E_POLICY_INVALID", "Missing evidence requires an explicit insufficient outcome.")
        if "fallback_output" not in incomplete:
            raise ContractError("E_POLICY_INVALID", "The insufficient outcome requires its explicit output value.")
        permissions = unique(definition["consequence_permissions"])
        for permission in permissions:
            schemas.resolve(permission)
        for item in outcomes:
            if "fallback_output" in item:
                output = schemas.validate(item["fallback_output"])
                if (output["schema"] != definition["output_schema"] or type(output["value"]) is not dict
                        or output["value"].get("label") != item["label"]):
                    raise ContractError("E_POLICY_INVALID", "Fallback output must bind its declared label and schema.")
            unique(item["implications"])
            if any(implication not in permissions for implication in item["implications"]):
                raise ContractError("E_POLICY_INVALID", "An outcome implication exceeds the declared proposal schemas.")
            if item["evaluation_status"] != "applicable" and item["implications"]:
                raise ContractError("E_POLICY_INVALID", "Unresolved or inapplicable outcomes cannot propose consequences.")
        for item in definition["preconditions"]:
            if re.search(r"~(?![01])", item["pointer"]):
                raise ContractError("E_POLICY_INVALID", "Precondition pointers use JSON Pointer escaping.")
            if item["otherwise_label"] not in labels:
                raise ContractError("E_POLICY_INVALID", "A precondition fallback label is undefined.")
            fallback = next(outcome for outcome in outcomes if outcome["label"] == item["otherwise_label"])
            if fallback["evaluation_status"] not in {"not_applicable", "insufficient_evidence"}:
                raise ContractError("E_POLICY_INVALID", "Missing prerequisites cannot imply a false domain conclusion.")
            if "fallback_output" not in fallback:
                raise ContractError("E_POLICY_INVALID", "A precondition fallback requires an exact output value.")
        unique([item["rule"] for item in definition["dependencies"]])
        for item in definition["dependencies"]:
            unique(item["accepted_labels"])
            unique(item["accepted_statuses"])
        if requirements["minimum"] > definition["resource_limits"]["max_evidence"]:
            raise ContractError("E_POLICY_INVALID", "The evidence minimum exceeds the rule budget.")
        self._freeze(definition)

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["rule_id"], value["semantic_version"],
                          value, "matter.rule-definition.v1")

    def outcome(self, label):
        for value in self.value["outcomes"]:
            if value["label"] == label:
                return value
        raise ContractError("E_EVIDENCE_INVALID", "The evaluator returned an undefined output label.")


class RuleRegistry:
    __slots__ = ("_rules",)

    def __init__(self, rules=()):
        values = tuple(rules)
        if len(values) > 128 or any(not isinstance(item, RuleDefinition) for item in values):
            raise ContractError("E_POLICY_INVALID")
        identities = [(item.reference["namespace"], item.reference["id"], item.reference["version"]) for item in values]
        if len(identities) != len(set(identities)):
            raise ContractError("E_POLICY_INVALID", "A rule meaning/version may be installed only once.")
        object.__setattr__(self, "_rules", values)

    def __setattr__(self, name, value):
        raise AttributeError("RuleRegistry is immutable.")

    def resolve(self, reference):
        ref = fragment(reference, "component_ref")
        for rule in self._rules:
            if same(rule.reference, ref):
                return rule
        raise ContractError("E_POLICY_INVALID", "The exact rule meaning/version is not installed.")

