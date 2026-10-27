"""MAT-014 bounded typed graph compilation, including every conditional edge."""
from copy import deepcopy

from ._rule_values import FrozenValue, checked, descriptor, fragment
from .canonical import canonical_bytes
from .contracts import ContractError
from .profiles import ProfileDefinition
from .rules import RuleRegistry, SchemaRegistry


class PlanError(ContractError):
    def __init__(self, path, reason):
        self.path = path
        super().__init__("E_POLICY_INVALID", path + ": " + reason)


def _fail(path, reason):
    raise PlanError(path, reason)


def _pointer(value, path):
    if type(value) is not str or len(value) > 1024 or (value and not value.startswith("/")):
        _fail(path, "A bounded JSON Pointer is required.")
    import re
    if re.search(r"~(?![01])", value):
        _fail(path, "A JSON Pointer uses only ~0 and ~1 escapes.")
    return value


def read_pointer(value, pointer):
    """Read exact JSON data; unavailable paths never synthesize a value."""
    for part in pointer.split("/")[1:] if pointer else ():
        part = part.replace("~1", "/").replace("~0", "~")
        if type(value) is list:
            if not part.isascii() or not part.isdigit() or (len(part) > 1 and part.startswith("0")):
                raise ContractError("E_EVIDENCE_INVALID", "A consumed output pointer is unavailable.")
            try:
                value = value[int(part)]
            except IndexError:
                raise ContractError("E_EVIDENCE_INVALID", "A consumed output pointer is unavailable.") from None
        elif type(value) is dict and part in value:
            value = value[part]
        else:
            raise ContractError("E_EVIDENCE_INVALID", "A consumed output pointer is unavailable.")
    return deepcopy(value)


class RulePlan(FrozenValue):
    """Content-bound profile graph; compiling it dispatches no evaluation."""
    __slots__ = ()

    def __init__(self, profile, *, rules, schemas, nodes, input_bindings=(), conditions=(), compositions=()):
        if not isinstance(profile, ProfileDefinition) or not isinstance(rules, RuleRegistry) or not isinstance(schemas, SchemaRegistry):
            _fail("/", "Exact profile, rule and schema registries are required.")
        canonical_bytes(nodes)
        if type(nodes) is not dict or len(nodes) > 128 or any(type(name) is not str or not name or len(name) > 128 for name in nodes):
            _fail("/nodes", "At most 128 explicitly named rule nodes may be selected.")
        for name in nodes:
            try:
                fragment(name, "identifier")
            except ContractError:
                _fail("/nodes", "Node identities must be whitespace-free identifiers.")
        selected, owners = {}, {}
        for kind, component in profile.value["components"].items():
            for reference in component["rules"]:
                owners[canonical_bytes(reference)] = kind
        references = [canonical_bytes(reference) for reference in nodes.values()]
        if set(references) != set(owners) or len(set(references)) != len(references):
            _fail("/nodes", "The graph must select each exact profile rule once.")
        names = {canonical_bytes(reference): name for name, reference in nodes.items()}
        for name in sorted(nodes):
            rule = rules.resolve(nodes[name])
            schemas.resolve(rule.value["input_schema"])
            schemas.resolve(rule.value["output_schema"])
            selected[name] = rule
        edges = []
        for position, (name, rule) in enumerate(selected.items()):
            for dependency in rule.value["dependencies"]:
                predecessor = names.get(canonical_bytes(dependency["rule"]))
                if predecessor is None:
                    _fail("/nodes/" + str(position), "A declared exact predecessor is absent.")
                edges.append({"from": predecessor, "to": name, "kind": "required",
                    "accepted_labels": dependency["accepted_labels"], "accepted_statuses": dependency["accepted_statuses"],
                    "require_qualified": dependency["require_qualified"], "source_schema": selected[predecessor].value["output_schema"]})
        if not isinstance(conditions, (list, tuple)) or len(conditions) > 128:
            _fail("/conditions", "Conditional edges must be bounded.")
        for index, raw in enumerate(conditions):
            edge = checked(raw, required=("from", "to", "accepted_labels", "accepted_statuses", "require_qualified"), code="E_POLICY_INVALID")
            self._edge(edge, selected, "/conditions/" + str(index))
            edges.append({**edge, "kind": "conditional", "source_schema": selected[edge["from"]].value["output_schema"]})
        for edge in edges:
            self._edge(edge, selected, "/edges")
        graph = {name: set() for name in selected}
        for edge in edges:
            graph[edge["to"]].add(edge["from"])
        components = profile.value["components"]
        for name, rule in selected.items():
            kind = owners[canonical_bytes(rule.reference)]
            pending, seen = list(components[kind]["dependencies"]), set()
            while pending:
                other = pending.pop()
                if other in seen:
                    continue
                seen.add(other)
                pending.extend(components[other]["dependencies"])
            for other_name, other_rule in selected.items():
                if owners[canonical_bytes(other_rule.reference)] in seen:
                    graph[name].add(other_name)
        order, pending = [], {name: set(value) for name, value in graph.items()}
        while pending:
            ready = sorted(name for name, dependencies in pending.items() if not dependencies)
            if not ready:
                _fail("/edges", "The union of unconditional, conditional and component edges contains a cycle.")
            order.extend(ready)
            for name in ready:
                del pending[name]
            for dependencies in pending.values():
                dependencies.difference_update(ready)
        if not isinstance(input_bindings, (list, tuple)) or len(input_bindings) > 128:
            _fail("/input_bindings", "Consumed-output bindings must be bounded.")
        mappings, destinations = [], set()
        required_pairs = {(edge["from"], edge["to"]) for edge in edges if edge["kind"] == "required"}
        for index, raw in enumerate(input_bindings):
            value = checked(raw, required=("from", "to", "source_pointer", "target_pointer"), code="E_POLICY_INVALID")
            path = "/input_bindings/" + str(index)
            if (type(value["from"]) is not str or type(value["to"]) is not str
                    or (value["from"], value["to"]) not in required_pairs):
                _fail(path, "A consumed output must follow a declared typed rule prerequisite.")
            for key in ("source_pointer", "target_pointer"):
                _pointer(value[key], path + "/" + key)
            destination = value["to"], value["target_pointer"]
            if destination in destinations:
                _fail(path, "One input location cannot silently choose between predecessor outputs.")
            destinations.add(destination)
            mappings.append(value)
        if {(value["from"], value["to"]) for value in mappings} != required_pairs:
            _fail("/input_bindings", "Every required predecessor needs an explicit consumed-output mapping.")
        admitted_resolvers = {canonical_bytes(reference) for component in components.values() for reference in component["conflict_resolvers"]}
        if not isinstance(compositions, (list, tuple)) or len(compositions) > 128:
            _fail("/compositions", "Composition declarations must be bounded.")
        groups, identifiers = [], set()
        for index, raw in enumerate(compositions):
            value = checked(raw, required=("id", "resolver", "nodes", "mandatory_gates"), code="E_POLICY_INVALID")
            path = "/compositions/" + str(index)
            fragment(value["id"], "identifier")
            if value["id"] in identifiers:
                _fail(path, "Composition identities must be unique.")
            identifiers.add(value["id"])
            if canonical_bytes(fragment(value["resolver"], "component_ref")) not in admitted_resolvers:
                _fail(path + "/resolver", "The profile has not explicitly admitted this conflict resolver.")
            group_nodes = value["nodes"]
            if type(group_nodes) is not list or not group_nodes or len(group_nodes) > 128 or any(type(name) is not str or name not in selected for name in group_nodes) or len(set(group_nodes)) != len(group_nodes):
                _fail(path + "/nodes", "Composition requires distinct selected nodes.")
            output_schemas = {canonical_bytes(selected[name].value["output_schema"]) for name in group_nodes}
            if len(output_schemas) != 1:
                _fail(path + "/nodes", "A composition must compare one exact output type.")
            if type(value["mandatory_gates"]) is not list or len(value["mandatory_gates"]) > 128:
                _fail(path + "/mandatory_gates", "Mandatory gates must be bounded.")
            for gate_index, raw_gate in enumerate(value["mandatory_gates"]):
                gate = checked(raw_gate, required=("node", "accepted_labels", "accepted_statuses", "require_qualified"), code="E_POLICY_INVALID")
                self._edge({**gate, "from": gate["node"], "to": gate["node"]}, selected, path + "/mandatory_gates/" + str(gate_index), allow_self=True)
            groups.append(value)
        self._freeze({"schema_version": "1.0", "profile": profile.reference, "nodes": {name: selected[name].reference for name in selected},
            "edges": edges, "order": order, "dependencies": {name: sorted(value) for name, value in graph.items()},
            "input_bindings": mappings, "compositions": groups, "resource_limits": profile.value["resource_limits"],
            "incomplete_evaluation": profile.value["incomplete_evaluation"]})

    @staticmethod
    def _edge(edge, selected, path, allow_self=False):
        if type(edge["from"]) is not str or type(edge["to"]) is not str or edge["from"] not in selected or edge["to"] not in selected:
            _fail(path, "An edge names an unselected node.")
        if not allow_self and edge["from"] == edge["to"]:
            _fail(path, "A node cannot require itself, even conditionally.")
        if type(edge["require_qualified"]) is not bool:
            _fail(path, "Qualification admission must be an explicit boolean.")
        outcomes = {item["label"]: item["evaluation_status"] for item in selected[edge["from"]].value["outcomes"]}
        labels, statuses = edge["accepted_labels"], edge["accepted_statuses"]
        if (type(labels) is not list or not labels or len(labels) > 64 or any(type(label) is not str or label not in outcomes for label in labels)
                or len(set(labels)) != len(labels) or type(statuses) is not list
                or any(type(status) is not str for status in statuses)
                or len(set(statuses)) != len(statuses) or set(statuses) != {outcomes[label] for label in labels}):
            _fail(path, "The edge must select defined predecessor labels and their exact statuses.")

    @property
    def reference(self):
        return descriptor("matter", "rule-plan", "1.0", self.value, "matter.rule-plan.v1")
