# Decision 0001: neutral contracts here, domain execution with its owner

**Status:** adopted for this scaffold, 2026-10-08.

## Context

The original brainstorm describes Oil and StateCivics consuming a shared foundation. The longer JEV note proposes building inside Oil first and extracting common mechanics later. A dedicated Matter repository now needs a single implementation boundary.

## Decision

Matter owns the neutral specification and new reusable core logic. Oil supplies the first operational adapter and evaluation workload. Existing Oil primitives may be reused through inspected boundaries; the complete Oil runtime is not copied here. Core portability is checked with an additional civic trace from the beginning.

DIAT owns its domain learning, longitudinal speaker evidence, jurisdiction/committee fingerprints, and private evaluation. The Matter roadmap may record DIAT-owned tickets and common evidence contracts. It does not move acoustic identity or enrollment authority into Matter.

The crawler owns source-specific jurisdiction/profile extraction. Reviewed receiver/operator authority continues to govern final civic dispositions. Parse hints such as a recommendation or final-action category do not create legal authority.

## Consequences

Core contracts must make sense without a code tree, civic body, speaker embedding, or provider-specific question object. Adapters supply those meanings. The reference implementation can initially use one language and embedded storage; additional implementations must satisfy the same behavioral examples and consistency guarantees.

The user-requested scaffold is complete only when its contracts, backlog, schemas, tooling, and examples are reviewable and checked. Runtime, cross-project integration, and empirical qualification remain separate ticketed work.
