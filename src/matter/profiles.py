"""MAT-013 immutable policy assemblies; declarations never authorize execution.

Exact rule meanings are supplied by the host's RuleRegistry. Components declare
all cross-component reads so independent audience changes need not invalidate
evidence semantics. Graph execution/publication are MAT-014/MAT-015 work.
"""

from copy import deepcopy

from .canonical import canonical_bytes
from .contracts import ContractError
from ._rule_values import FrozenValue, descriptor, fragment, runtime_schema
from .rules import RuleRegistry, SchemaRegistry


__all__ = ["ProfileDefinition", "ProfileRegistry", "ProfileValidationError", "compare_profiles"]
_KINDS = ("evidence", "lifecycle", "purpose", "audience")


class ProfileValidationError(ContractError):
    """Safe JSON Pointer location without echoing rejected source content."""

    def __init__(self, path, reason):
        self.path = path or "/"
        self.reason = reason
        super().__init__("E_POLICY_INVALID", self.path + ": " + reason)


def _fail(path, reason):
    raise ProfileValidationError(path, reason)


def _pointer(parts):
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _refs(values, path):
    if not isinstance(values, (tuple, list)) or len(values) > 128:
        _fail(path, "A bounded host-installed reference list is required.")
    try:
        refs = [fragment(value, "component_ref") for value in values]
        keys = [canonical_bytes(ref) for ref in refs]
    except (ContractError, TypeError, ValueError, RecursionError):
        _fail(path, "An exact installed reference is malformed.")
    if len(set(keys)) != len(keys):
        _fail(path, "Duplicate installed references are ambiguous.")
    return set(keys)


def _ordered(graph, path):
    order, visiting, visited = [], set(), set()

    def visit(node):
        if node in visiting:
            _fail(path(node), "Dependency cycle has no admissible execution path.")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            if dependency not in graph:
                _fail(path(node), "A required dependency is absent.")
            visit(dependency)
        visiting.remove(node)
        visited.add(node)
        order.append(node)

    for node in graph:
        visit(node)
    return order


class ProfileDefinition(FrozenValue):
    """Complete immutable profile with explicit host admission ceilings.

    Construction validates declarations only. Host allowlists admit named
    scopes/proposal schemas/resolvers; they are not user permission receipts.
    Resource envelopes cover every selected node once, with no retry planner.
    """
    __slots__ = ("_component_refs", "_dependencies")

    def __init__(self, value, *, rules, schemas, allowed_data_scopes=(),
                 allowed_capabilities=(), conflict_resolvers=()):
        if not isinstance(rules, RuleRegistry) or not isinstance(schemas, SchemaRegistry):
            _fail("/", "Exact rule and schema registries are required.")
        try:
            encoded = canonical_bytes(value)
        except (TypeError, ValueError, RecursionError):
            _fail("/", "The profile must be canonical JSON data.")
        if len(encoded) > 1048576:
            _fail("/", "The profile exceeds the one-MiB declaration bound.")
        _, validator = runtime_schema("policy-profile")
        error = next(validator.iter_errors(value), None)
        if error is not None:
            parts = list(error.absolute_path)
            if error.validator == "required":
                missing = next((key for key in error.validator_value if key not in error.instance), None)
                if missing is not None:
                    parts.append(missing)
            _fail(_pointer(parts), "The profile field does not satisfy its declared schema.")
        definition = deepcopy(value)
        capabilities = _refs(allowed_capabilities, "/host/capabilities")
        resolvers = _refs(conflict_resolvers, "/host/conflict_resolvers")
        if not isinstance(allowed_data_scopes, (list, tuple)) or len(allowed_data_scopes) > 128:
            _fail("/host/data_scopes", "A bounded host scope list is required.")
        if any(type(scope) is not str for scope in allowed_data_scopes):
            _fail("/host/data_scopes", "Host scope identifiers must be strings.")
        scopes = set(allowed_data_scopes)
        components = definition["components"]
        component_graph = {kind: component["dependencies"] for kind, component in components.items()}
        component_order = _ordered(component_graph, lambda kind: "/components/" + kind + "/dependencies")
        closure = {}
        for kind in component_order:
            closure[kind] = set(component_graph[kind])
            for dependency in component_graph[kind]:
                closure[kind].update(closure[dependency])
        installed, owners, rule_paths, outputs = {}, {}, {}, {}
        for kind, component in components.items():
            base = "/components/" + kind
            for index, scope in enumerate(component["data_scopes"]):
                if scope not in scopes:
                    _fail(base + "/data_scopes/" + str(index), "The host has not admitted this data scope.")
            component_caps = _refs(component["capabilities"], base + "/capabilities")
            if not component_caps <= capabilities:
                _fail(base + "/capabilities", "A declared capability exceeds the host ceiling.")
            component_resolvers = _refs(component["conflict_resolvers"], base + "/conflict_resolvers")
            if not component_resolvers <= resolvers:
                _fail(base + "/conflict_resolvers", "A resolver is not explicitly installed by the host.")
            if kind != "lifecycle" and component["lifecycle_extensions"]:
                _fail(base + "/lifecycle_extensions", "Lifecycle meaning belongs in the lifecycle component.")
            for index, extension in enumerate(component["lifecycle_extensions"]):
                try:
                    schemas.validate(extension)
                except ContractError:
                    _fail(base + "/lifecycle_extensions/" + str(index), "The exact extension schema/value is unavailable or invalid.")
            for index, reference in enumerate(component["rules"]):
                path = base + "/rules/" + str(index)
                key = canonical_bytes(reference)
                if key in installed:
                    _fail(path, "Select a shared rule once and declare a component dependency.")
                try:
                    rule = rules.resolve(reference)
                except ContractError:
                    _fail(path, "The exact rule meaning/version is not installed.")
                meaning = rule.value
                try:
                    schemas.resolve(meaning["input_schema"])
                    schemas.resolve(meaning["output_schema"])
                except ContractError:
                    _fail(path, "The exact rule input/output schema is not installed.")
                if canonical_bytes(meaning["conflict_policy"]) not in component_resolvers:
                    _fail(path + "/conflict_policy", "The rule requires an explicit admitted conflict resolver.")
                if any(canonical_bytes(ref) not in component_caps for ref in meaning["consequence_permissions"]):
                    _fail(path + "/consequence_permissions", "A rule proposal exceeds the component capability ceiling.")
                installed[key], owners[key], rule_paths[key] = rule, kind, path
            for index, output in enumerate(component["outputs"]):
                path = base + "/outputs/" + str(index)
                if output["name"] in outputs:
                    _fail(path + "/name", "Output names must be unique across components.")
                key = canonical_bytes(output["rule"])
                if key not in installed or owners[key] != kind:
                    _fail(path + "/rule", "The output has no selected local rule path.")
                rule = installed[key]
                if output["schema"] != rule.value["output_schema"]:
                    _fail(path + "/schema", "The output schema differs from its exact producer schema.")
                self._labels(rule, output, path)
                outputs[output["name"]] = (kind, output)
        for index, name in enumerate(definition["required_outputs"]):
            if name not in outputs:
                _fail("/required_outputs/" + str(index), "The required output has no declared producer path.")
        graph = {}
        for key, rule in installed.items():
            graph[key] = []
            for index, dependency in enumerate(rule.value["dependencies"]):
                path = rule_paths[key] + "/dependencies/" + str(index)
                predecessor = canonical_bytes(dependency["rule"])
                if predecessor not in installed:
                    _fail(path, "The required exact predecessor rule is not selected.")
                if owners[predecessor] != owners[key] and owners[predecessor] not in closure[owners[key]]:
                    _fail(path, "A cross-component rule read requires an explicit component dependency.")
                self._labels(installed[predecessor], dependency, path)
                graph[key].append(predecessor)
        order = _ordered(graph, lambda key: rule_paths[key] + "/dependencies")
        # Component dependencies also order components with no direct rule edge.
        # Calculate a declared worst-case critical-path envelope, not observed cost.
        elapsed, component_elapsed = {}, {}
        for kind in component_order:
            keys = [key for key in order if owners[key] == kind]
            start = max((component_elapsed[other] for other in component_graph[kind]), default=0)
            for key in keys:
                elapsed[key] = max([start] + [elapsed[parent] for parent in graph[key]]) + installed[key].value["resource_limits"]["max_elapsed_ms"]
            finish = max([start] + [elapsed[key] for key in keys])
            component_elapsed[kind] = finish
            limits = components[kind]["resource_limits"]
            self._budget(limits, [installed[key] for key in keys], finish - start, "/components/" + kind + "/resource_limits")
            for field, limit in limits.items():
                if limit > definition["resource_limits"][field]:
                    _fail("/components/" + kind + "/resource_limits/" + field, "The component envelope exceeds the profile envelope.")
        self._budget(definition["resource_limits"], list(installed.values()), max(component_elapsed.values(), default=0), "/resource_limits")
        refs, dependencies = {}, {}
        for kind in component_order:
            exact_dependencies = [refs[dependency] for dependency in components[kind]["dependencies"]]
            material = {"kind": kind, "definition": components[kind], "dependencies": exact_dependencies}
            # No profile identity enters a reusable component's semantic binding.
            refs[kind] = descriptor(definition["namespace"], "policy-component-" + kind,
                components[kind]["semantic_version"], material, "matter.policy-component.v1")
            rule_refs = [installed[key].reference for key in sorted(installed) if owners[key] in closure[kind] | {kind}]
            dependencies[kind] = {"components": exact_dependencies, "rules": rule_refs}
        self._freeze(definition)
        object.__setattr__(self, "_component_refs", canonical_bytes(refs))
        object.__setattr__(self, "_dependencies", canonical_bytes(dependencies))

    @staticmethod
    def _labels(rule, binding, path):
        outcomes = {item["label"]: item for item in rule.value["outcomes"]}
        for index, label in enumerate(binding["accepted_labels"]):
            if label not in outcomes:
                _fail(path + "/accepted_labels/" + str(index), "The referenced rule does not define this outcome label.")
        actual = {outcomes[label]["evaluation_status"] for label in binding["accepted_labels"]}
        if actual != set(binding["accepted_statuses"]):
            _fail(path + "/accepted_statuses", "Accepted statuses must describe the selected labels exactly.")

    @staticmethod
    def _budget(limits, rules, elapsed, path):
        needs = {"max_calls": sum(rule.value["resource_limits"]["max_calls"] for rule in rules),
                 "max_input_bytes": sum(rule.value["resource_limits"]["max_input_bytes"] for rule in rules),
                 "max_output_bytes": sum(rule.value["resource_limits"]["max_output_bytes"] for rule in rules),
                 "max_evidence": max((rule.value["resource_limits"]["max_evidence"] for rule in rules), default=0),
                 "max_elapsed_ms": elapsed}
        for field, required in needs.items():
            if limits[field] < required:
                _fail(path + "/" + field, "The selected rule graph cannot fit its declared resource envelope.")

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["profile_id"], value["semantic_version"], value, "matter.policy-profile.v1")

    @property
    def component_references(self):
        from .canonical import loads
        return loads(self._component_refs)

    @property
    def dependencies(self):
        from .canonical import loads
        return loads(self._dependencies)

    def assessment_binding(self, matter, *, purpose, audience=None):
        """Detached exact inputs for later assessment; no write/currentness claim."""
        subject = fragment(matter, "matter_dependency")
        result = {"matter": subject, "profile": self.reference,
                  "purpose": fragment(purpose, "component_ref")}
        if audience is not None:
            result["audience"] = fragment(audience, "component_ref")
        if "audience" in self.value["components"] and audience is None:
            _fail("/assessment/audience", "This profile requires an exact audience-context binding.")
        return deepcopy(result)


def compare_profiles(previous, replacement):
    """Structural compatibility is descriptive and never transfers qualification."""
    if not isinstance(previous, ProfileDefinition) or not isinstance(replacement, ProfileDefinition):
        _fail("/", "Profile definitions are required for comparison.")
    before, after = previous.component_references, replacement.component_references
    changed = [kind for kind in _KINDS if before.get(kind) != after.get(kind)]
    profile_changes = [field for field in ("description", "required_outputs", "resource_limits", "incomplete_evaluation")
                       if previous.value[field] != replacement.value[field]]
    def output_shapes(profile):
        return {output["name"]: output["schema"] for component in profile.value["components"].values()
                for output in component["outputs"]}
    shapes = output_shapes(previous), output_shapes(replacement)
    return {"structurally_compatible": shapes[0] == shapes[1],
            "semantic_equivalent": not changed and not profile_changes,
            "changed_components": changed, "profile_changes": profile_changes,
            "qualification_transfer": False}


class ProfileRegistry:
    """Immutable history: exact references only, without a mutable 'latest' alias."""
    __slots__ = ("_profiles",)

    def __init__(self, profiles=()):
        values = tuple(profiles)
        if len(values) > 128 or any(not isinstance(profile, ProfileDefinition) for profile in values):
            _fail("/profiles", "At most 128 immutable profile definitions may be installed.")
        identities = [(profile.reference["namespace"], profile.reference["id"], profile.reference["version"]) for profile in values]
        if len(set(identities)) != len(identities):
            _fail("/profiles", "A profile identity/version may be installed only once.")
        object.__setattr__(self, "_profiles", values)

    def __setattr__(self, name, value):
        raise AttributeError("ProfileRegistry is immutable.")

    def resolve(self, reference):
        try:
            requested = fragment(reference, "component_ref")
        except ContractError:
            _fail("/profile", "An exact profile reference is required.")
        for profile in self._profiles:
            if profile.reference == requested:
                return profile
        _fail("/profile", "The exact historical profile is not installed.")

    def supersede(self, reference, replacement):
        """Return a new history and a policy-change notice; mutate no assessment."""
        previous = self.resolve(reference)
        if not isinstance(replacement, ProfileDefinition):
            _fail("/replacement", "An immutable profile definition is required.")
        before, after = previous.reference, replacement.reference
        if any(before[field] != after[field] for field in ("namespace", "id")) or before["version"] == after["version"]:
            _fail("/replacement", "Supersession requires the same profile identity and a new exact version.")
        updated = ProfileRegistry((*self._profiles, replacement))
        notice = {"cause": "policy_change", "before": before, "after": after,
                  **compare_profiles(previous, replacement)}
        return updated, notice
