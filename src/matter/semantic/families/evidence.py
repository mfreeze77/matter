"""MAT-033 shadow association and independent claim-relative evidence heads."""

from ..questions import QuestionSpecification, association_specification, comparison_specification
from . import with_packet


def association_questions():
    """Reuse MAT-027's fixed alternatives and separate identity propositions."""
    return (with_packet(association_specification(revision="1.1",
                observation_path=("binding", "left"), candidate_path=("binding", "right"))),
            *(with_packet(comparison_specification(kind, revision="1.1",
                left_path=("binding", "left"), right_path=("binding", "right")))
              for kind in ("topic", "matter", "occurrence")))


def claim_evidence_questions():
    definitions = (
        ("support", "Does the selected evidence support any declared component of {{claim}}?",
         "An identified claim component has source support, even if other components remain unverified.",
         "The selected evidence provides no support for a declared claim component; uncertainty is not disproof."),
        ("contradiction", "Does the selected evidence contradict any declared component of {{claim}}?",
         "A source-backed statement is incompatible with an identified component under the same scope and time.",
         "No incompatible component is established by the supplied evidence; omission alone is not contradiction."),
        ("qualification", "Does the selected evidence limit, condition or leave a material part of {{claim}} unresolved?",
         "An identified limitation, condition, missing requirement or counterexample restricts the claim's interpretation.",
         "No such material limitation is supported by the bounded evidence; completeness is not assumed."),
        ("established", "Does the selected evidence establish that the event asserted by {{claim}} occurred?",
         "Evidence under the declared scope and proof conditions supports occurrence of the asserted event itself.",
         "The passage merely asserts, predicts, plans or recommends the event, or lacks the required proof of occurrence."),
    )
    return tuple(with_packet(QuestionSpecification({
        "schema_version": "1.0", "namespace": "matter", "id": "evidence-" + name,
        "family": "evidence." + name, "revision": "1.0", "primitive": "proposition_probability",
        "instructions": instruction + " Support, contradiction and qualification are independent propositions, "
            "not mutually exclusive labels. Do not upgrade an assertion, source origin or model summary into authority.",
        "criteria": {"true": yes, "false": no},
        "required_fields": [{"name": "claim", "path": ["binding"],
                             "description": "The exact claim pin, components and proposition from the prepared packet."}],
        "renderer": {"id": "canonical-json-bindings", "version": "1.0"},
    })) for name, instruction, yes, no in definitions)
