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
Explicit temporal views, source catalogs, coverage and absence registrations
live in ``matter.time``, ``matter.source_catalogs``, ``matter.coverage`` and
``matter.negative_dependencies``.
Trusted host authority, scoped control fences and guarded execution live in
``matter.authority`` and ``matter.controls``.
Provider-neutral immutable rules and bounded deterministic/recorded attempts
live in ``matter.rules`` and ``matter.evaluators``. Immutable policy assemblies
live in ``matter.profiles``; staged typed execution and explicit conflict
composition live in ``matter.planner``, ``matter.executor`` and
``matter.conflicts``. Versioned semantic questions, bounded source packets and
offline typed execution live in ``matter.semantic``. Frozen corpus contracts
live in ``matter.evaluation``. Atomic assessment publication and declared caches
live in ``matter.assessments`` and ``matter.cache``. Registered transitive validity
and freshness gates live in ``matter.dependencies`` and ``matter.invalidation``.
Profile-backed lifecycle transitions live in ``matter.lifecycle``; independent
context and disposition state lives in ``matter.contexts`` and
``matter.dispositions``. Host-declared source/audience/provider guards live in
``matter.access``. Delivery, provider qualification issuance and downstream
usefulness retain separate validation milestones.
"""

__version__ = "0.1.0.dev14"
