"""MAT-014 exact deterministic composition policies, without action authority."""
from copy import deepcopy
from ._rule_values import FrozenValue, descriptor, fragment
from .canonical import canonical_bytes
from .contracts import ContractError


class ConflictResolver(FrozenValue):
    """Installed code selects one declared policy; source text is never invoked."""
    __slots__ = ()

    def __init__(self, namespace, identity, version, *, mode="retain_conflict", precedence=()):
        if mode not in {"retain_conflict", "precedence"}:
            raise ContractError("E_POLICY_INVALID", "An explicit supported conflict policy is required.")
        names = list(precedence)
        if len(names) > 128 or any(type(name) is not str or not name for name in names) or len(set(names)) != len(names):
            raise ContractError("E_POLICY_INVALID", "Conflict precedence must name distinct bounded nodes.")
        if (mode == "precedence") != bool(names):
            raise ContractError("E_POLICY_INVALID", "Only precedence policies declare an explicit complete order.")
        value = {"namespace": namespace, "id": identity, "version": version, "mode": mode, "precedence": names}
        descriptor(namespace, identity, version, value, "matter.conflict-resolver.v1")
        self._freeze(value)

    @property
    def reference(self):
        value = self.value
        return descriptor(value["namespace"], value["id"], value["version"], value, "matter.conflict-resolver.v1")

    def compose(self, originals):
        values = deepcopy(list(originals))
        if not values or len(values) > 128 or len({item["node"] for item in values}) != len(values):
            raise ContractError("E_POLICY_INVALID", "Composition requires distinct bounded node results.")
        values.sort(key=lambda item: item["node"])
        outputs = [item["judgment"]["body"]["semantic_output"] for item in values]
        agrees = len({canonical_bytes(output) for output in outputs}) == 1
        mode = self.value["mode"]
        if not agrees and mode == "retain_conflict":
            return {"status": "conflicting", "treatment": "quiet", "selected_node": None,
                    "semantic_output": None, "originals": values, "resolver": self.reference}
        if mode == "precedence":
            order = self.value["precedence"]
            if any(item["node"] not in order for item in values):
                raise ContractError("E_POLICY_INVALID", "The explicit resolver order does not cover every result.")
            values.sort(key=lambda item: order.index(item["node"]))
        selected = values[0]
        return {"status": "resolved", "treatment": "proposed_only", "selected_node": selected["node"],
                "semantic_output": selected["judgment"]["body"]["semantic_output"],
                "originals": sorted(values, key=lambda item: item["node"]), "resolver": self.reference}


class ConflictResolverRegistry:
    """Host-installed exact immutable resolvers; no implicit confidence fallback."""
    __slots__ = ("_resolvers",)

    def __init__(self, resolvers=()):
        values = tuple(resolvers)
        if len(values) > 128 or any(not isinstance(value, ConflictResolver) for value in values):
            raise ContractError("E_POLICY_INVALID")
        identities = [(value.reference["namespace"], value.reference["id"], value.reference["version"]) for value in values]
        if len(set(identities)) != len(identities):
            raise ContractError("E_POLICY_INVALID", "An exact resolver identity/version may be installed only once.")
        object.__setattr__(self, "_resolvers", values)

    def __setattr__(self, name, value):
        raise AttributeError("ConflictResolverRegistry is immutable.")

    def resolve(self, reference):
        requested = fragment(reference, "component_ref")
        for resolver in self._resolvers:
            if resolver.reference == requested:
                return resolver
        raise ContractError("E_POLICY_INVALID", "The exact conflict resolver is not installed.")
