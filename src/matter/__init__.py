"""Matter portable contracts, durable evidence, and continuing subject identity.

Structural contracts live in ``matter.contracts`` and canonical encoding in
``matter.canonical``. Transactional persistence lives in ``matter.storage``;
immutable source intake and payloads live in ``matter.observations`` and
``matter.payloads``. Persistent subject identity and metadata live in
``matter.matters`` and ``matter.identity_keys``. Accepted occurrence membership
and evidence dependence live in ``matter.occurrences`` and
``matter.provenance_groups``. Immutable scoped assertions and cited relations
live in ``matter.claims``, ``matter.evidence_relations`` and ``matter.citations``.
Host-published candidate sets and authorized association decisions live in
``matter.associations``, ``matter.candidate_sets`` and ``matter.association_policy``.
Typed links and guarded equivalence/correction live in ``matter.relations``,
``matter.identity_groups`` and ``matter.identity_corrections``. Explicit host
derivatives use the atomic ``matter.identity_dependencies`` validity hook.
Semantic ranking, assessment execution and integrations remain backlog work.
"""

__version__ = "0.1.0.dev8"
