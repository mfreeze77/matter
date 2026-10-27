"""MAT-030 exact execution identity; distinct from declared projection reuse."""

from .._rule_values import checked, fragment
from ..canonical import canonical_digest
from ..storage import PROJECTION_TYPE


def execution_key(batch, *, rendered, precision, model_binding, parents=(), token, stage=None, dependencies=()):
    """No guessed resolution, ephemeral run ID, or capture-time cache identity.

    `model_binding` is an authenticated host's current concrete model/resolver
    declaration. None deliberately disables reuse for floating/unknown models.
    Correlation IDs remain conservative exact bindings; answers are not renamed.
    """
    if model_binding is None:
        return None
    binding = checked(model_binding, required=("model", "resolution"))
    fragment(binding["model"], "text")
    fragment(binding["resolution"], "component_ref")
    data = batch.value
    context = data["context"]
    return canonical_digest({"packet": data["packet_digest"], "dependencies": list(dependencies), "questions": data["questions"],
        "rendered": rendered, "execution": {key: context[key] for key in
            ("provider", "transport", "requested_model", "adapter_version", "mode")},
        "model_binding": binding, "precision": precision.value, "parents": list(parents),
        "stage": None if stage is None else {"plan": stage["plan"], "members": [
            {key: value for key, value in member.items() if key != "parent_traces"} for member in stage["members"]]},
        "control_generation": {key: value for key, value in token.items() if key != "captured_at"}},
        "matter.semantic-execution-key.v1")


def cache_ref(scope_id, key):
    return {"scope_id": scope_id, "namespace": "matter.semantic_execution_cache", "record_type": PROJECTION_TYPE, "id": key}


def attempt_ref(scope_id, logical_request_id, attempt_id):
    return {"scope_id": scope_id, "namespace": "matter.semantic_execution_attempts", "record_type": PROJECTION_TYPE,
            "id": canonical_digest({"logical_request_id": logical_request_id, "attempt_id": attempt_id}, "matter.semantic-attempt.v1")}
