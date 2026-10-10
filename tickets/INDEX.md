# Implementation backlog

Generated from the canonical JSON records. Readiness means recorded dependencies are complete; it does not assert qualification or completion.

Future work in another repository remains owned by that repository. This scaffold does not execute those changes.

| Ticket | Track | Phase | Priority | Status | Readiness | Depends on |
|---|---|---:|---|---|---|---|
| [MAT-001: Establish the governing scaffold and validated implementation backlog](MAT-001.md) | foundation | 0 | P0 | done | done | — |
| [MAT-002: Define interoperable record schemas, canonical encoding, and error results](MAT-002.md) | core | 0 | P0 | done | done | MAT-001 |
| [MAT-003: Implement durable transactional storage and revision-checked commands](MAT-003.md) | core | 0 | P0 | done | done | MAT-002 |
| [MAT-004: Ingest immutable observations with source-aware deduplication](MAT-004.md) | core | 1 | P0 | done | done | MAT-002, MAT-003 |
| [MAT-005: Implement persistent matter identity and scope continuity](MAT-005.md) | core | 1 | P0 | done | done | MAT-003, MAT-004 |
| [MAT-006: Track occurrences and evidence dependence separately from observations](MAT-006.md) | core | 1 | P0 | done | done | MAT-004, MAT-005 |
| [MAT-007: Model scoped claims and cited evidence relationships](MAT-007.md) | core | 1 | P0 | done | done | MAT-004, MAT-005, MAT-006 |
| [MAT-008: Separate association proposals from authorized acceptance](MAT-008.md) | core | 1 | P0 | done | done | MAT-005, MAT-006, MAT-007 |
| [MAT-009: Implement matter links, guarded merges, and reversible identity correction](MAT-009.md) | core | 2 | P0 | done | done | MAT-005, MAT-007, MAT-008 |
| [MAT-010: Represent time, source coverage, and explicit negative evidence scopes](MAT-010.md) | core | 1 | P0 | done | done | MAT-003, MAT-004, MAT-006, MAT-007 |
| [MAT-011: Route trusted controls immediately and preserve authority boundaries](MAT-011.md) | core | 1 | P0 | done | done | MAT-002, MAT-003, MAT-005 |
| [MAT-012: Implement provider-neutral rule and judgment interfaces](MAT-012.md) | rules | 2 | P0 | planned | ready | MAT-002, MAT-007, MAT-010, MAT-011 |
| [MAT-013: Version policy profiles and validate semantic compatibility](MAT-013.md) | rules | 2 | P0 | planned | waiting | MAT-012 |
| [MAT-014: Execute staged rule graphs with explicit conflict composition](MAT-014.md) | rules | 2 | P0 | planned | waiting | MAT-012, MAT-013 |
| [MAT-015: Commit revision-bound assessments and reusable semantic caches](MAT-015.md) | rules | 2 | P0 | planned | waiting | MAT-003, MAT-008, MAT-010, MAT-013, MAT-014 |
| [MAT-016: Invalidate dependencies transitively including absence and candidate scopes](MAT-016.md) | core | 2 | P0 | planned | waiting | MAT-003, MAT-009, MAT-010, MAT-015 |
| [MAT-017: Apply evidence-backed lifecycle transitions, resolution, and reopening](MAT-017.md) | core | 3 | P0 | planned | waiting | MAT-007, MAT-009, MAT-010, MAT-011, MAT-013, MAT-015, MAT-016 |
| [MAT-018: Bind purposes, audiences, and dispositions independently](MAT-018.md) | rules | 3 | P0 | planned | waiting | MAT-005, MAT-011, MAT-013, MAT-015, MAT-016 |
| [MAT-019: Evaluate attention eligibility against the last delivered baseline](MAT-019.md) | rules | 3 | P0 | planned | waiting | MAT-015, MAT-016, MAT-017, MAT-018 |
| [MAT-020: Schedule temporal reevaluation with durable resource and attention budgets](MAT-020.md) | core | 3 | P0 | planned | waiting | MAT-003, MAT-010, MAT-011, MAT-014, MAT-016, MAT-019 |
| [MAT-021: Deliver through a freshness-checked outbox with independent outcome receipts](MAT-021.md) | core | 3 | P0 | planned | waiting | MAT-003, MAT-011, MAT-016, MAT-019, MAT-020 |
| [MAT-022: Support bounded evidence-gap investigation without forced human escalation](MAT-022.md) | rules | 4 | P1 | planned | waiting | MAT-010, MAT-011, MAT-012, MAT-014, MAT-016, MAT-020 |
| [MAT-023: Expose consistent projections and decision explanations](MAT-023.md) | core | 4 | P1 | planned | waiting | MAT-003, MAT-007, MAT-009, MAT-015, MAT-016, MAT-017, MAT-019, MAT-021 |
| [MAT-024: Build chronological replay and language-neutral conformance fixtures](MAT-024.md) | core | 4 | P0 | planned | waiting | MAT-002, MAT-010, MAT-014, MAT-015, MAT-016, MAT-017, MAT-019, MAT-020, MAT-021, MAT-023 |
| [MAT-025: Qualify the neutral core through adversarial multi-audience episodes](MAT-025.md) | core | 5 | P0 | planned | waiting | MAT-002, MAT-003, MAT-004, MAT-005, MAT-006, MAT-007, MAT-008, MAT-009, MAT-010, MAT-011, MAT-012, MAT-013, MAT-014, MAT-015, MAT-016, MAT-017, MAT-018, MAT-019, MAT-020, MAT-021, MAT-022, MAT-023, MAT-024 |
| [MAT-026: Define the provider-neutral typed executor](MAT-026.md) | jev | 2 | P0 | planned | waiting | MAT-001, MAT-002, MAT-012 |
| [MAT-027: Implement versioned question specifications and rendering](MAT-027.md) | jev | 2 | P0 | planned | waiting | MAT-026, MAT-007 |
| [MAT-028: Build bounded source-linked assessment packets](MAT-028.md) | jev | 2 | P0 | planned | waiting | MAT-027, MAT-004, MAT-006, MAT-010 |
| [MAT-029: Plan independent batches and validated semantic stages](MAT-029.md) | jev | 3 | P0 | planned | waiting | MAT-026, MAT-027, MAT-028, MAT-014, MAT-020 |
| [MAT-030: Persist judgment receipts and exact execution reuse](MAT-030.md) | jev | 3 | P0 | planned | waiting | MAT-026, MAT-029, MAT-003, MAT-015, MAT-016 |
| [MAT-031: Enforce qualification certificates at runtime admission](MAT-031.md) | jev | 3 | P0 | planned | waiting | MAT-027, MAT-028, MAT-030, MAT-013 |
| [MAT-032: Integrate an optional TypeSafe transport adapter](MAT-032.md) | jev | 3 | P1 | planned | waiting | MAT-026, MAT-027, MAT-028, MAT-030, MAT-031 |
| [MAT-033: Add shadow association and claim-evidence question families](MAT-033.md) | jev | 3 | P1 | planned | waiting | MAT-027, MAT-028, MAT-029, MAT-031, MAT-007, MAT-008 |
| [MAT-034: Add shadow change, recovery and audience-contribution families](MAT-034.md) | jev | 3 | P1 | planned | waiting | MAT-027, MAT-028, MAT-029, MAT-031, MAT-017, MAT-018, MAT-019, MAT-021 |
| [MAT-035: Add bounded investigation judgments and stopping outcomes](MAT-035.md) | jev | 4 | P1 | planned | waiting | MAT-028, MAT-029, MAT-031, MAT-033, MAT-034, MAT-022, MAT-040 |
| [MAT-036: Freeze episode corpora and independent label provenance](MAT-036.md) | evaluation | 2 | P0 | planned | ready | MAT-001, MAT-004, MAT-006, MAT-010 |
| [MAT-037: Create grouped splits and comparable baseline manifests](MAT-037.md) | evaluation | 4 | P0 | planned | waiting | MAT-036, MAT-024 |
| [MAT-038: Build the deterministic offline evaluation harness](MAT-038.md) | evaluation | 4 | P0 | planned | waiting | MAT-026, MAT-029, MAT-030, MAT-031, MAT-036, MAT-037 |
| [MAT-039: Run optional real-provider shadow replay with exact receipts](MAT-039.md) | evaluation | 4 | P1 | planned | waiting | MAT-032, MAT-033, MAT-034, MAT-036, MAT-037, MAT-038 |
| [MAT-040: Fit thresholds and issue support-aware qualification records](MAT-040.md) | evaluation | 4 | P0 | planned | waiting | MAT-031, MAT-037, MAT-039 |
| [MAT-041: Evaluate label, order, changed-question and coherence sensitivity](MAT-041.md) | evaluation | 4 | P1 | planned | waiting | MAT-027, MAT-037, MAT-039 |
| [MAT-042: Compare matter outcomes and audit justified silence](MAT-042.md) | evaluation | 4 | P0 | planned | waiting | MAT-033, MAT-034, MAT-039, MAT-040, MAT-041, MAT-019, MAT-021 |
| [MAT-043: Qualify availability, latency and concurrent completion behavior](MAT-043.md) | evaluation | 4 | P0 | planned | waiting | MAT-039, MAT-042, MAT-010, MAT-011, MAT-016, MAT-020, MAT-021, MAT-024 |
| [MAT-044: Measure overhead and qualify execution budgets](MAT-044.md) | evaluation | 4 | P1 | planned | waiting | MAT-032, MAT-039, MAT-042, MAT-020 |
| [MAT-045: Assemble reproducible qualification and release evidence](MAT-045.md) | evaluation | 5 | P0 | planned | waiting | MAT-035, MAT-040, MAT-041, MAT-042, MAT-043, MAT-044, MAT-025 |
| [MAT-046: Define civic profile and authority-manifest contracts](MAT-046.md) | civic | 2 | P0 | planned | waiting | MAT-001, MAT-002, MAT-012, MAT-013 |
| [MAT-047: Export crawler jurisdiction overrides and authority evidence](MAT-047.md) | civic | 3 | P1 | planned | waiting | MAT-001, MAT-046, MAT-007, MAT-010, MAT-011 |
| [MAT-048: Adapt civic source claims and stages into neutral matter history](MAT-048.md) | civic | 3 | P1 | planned | waiting | MAT-001, MAT-004, MAT-005, MAT-006, MAT-007, MAT-008, MAT-009, MAT-010, MAT-046, MAT-047 |
| [MAT-049: Assess civic developments by purpose and meaningful audience change](MAT-049.md) | civic | 4 | P1 | planned | waiting | MAT-001, MAT-015, MAT-016, MAT-017, MAT-018, MAT-019, MAT-021, MAT-048 |
| [MAT-050: Qualify civic temporal, authority and receiver boundaries](MAT-050.md) | civic | 5 | P0 | planned | waiting | MAT-001, MAT-024, MAT-025, MAT-037, MAT-042, MAT-048, MAT-049 |
| [MAT-051: Audit the private DIAT corpus and exported evidence views](MAT-051.md) | diat | 0 | P0 | planned | ready | MAT-001 |
| [MAT-052: Define source-linked formal-meeting procedural observations](MAT-052.md) | diat | 2 | P1 | planned | waiting | MAT-001, MAT-002, MAT-004, MAT-007, MAT-046, MAT-051 |
| [MAT-053: Implement an uncertain procedural state tracker](MAT-053.md) | diat | 3 | P1 | planned | waiting | MAT-001, MAT-012, MAT-014, MAT-015, MAT-016, MAT-017, MAT-052 |
| [MAT-054: Model anonymous floor, chair and role transitions](MAT-054.md) | diat | 4 | P1 | planned | waiting | MAT-001, MAT-051, MAT-052, MAT-053, MAT-063 |
| [MAT-055: Learn versioned jurisdiction and committee fingerprints](MAT-055.md) | diat | 4 | P1 | planned | waiting | MAT-001, MAT-013, MAT-037, MAT-046, MAT-051, MAT-052, MAT-054, MAT-063 |
| [MAT-056: Build longitudinal roster and verified-reference research profiles](MAT-056.md) | diat | 4 | P1 | planned | waiting | MAT-001, MAT-006, MAT-010, MAT-051, MAT-063 |
| [MAT-057: Evaluate prefix, suffix and grammar evidence without script leakage](MAT-057.md) | diat | 4 | P1 | planned | waiting | MAT-001, MAT-027, MAT-028, MAT-051, MAT-056, MAT-063 |
| [MAT-058: Evaluate acoustic prosody with room and microphone controls](MAT-058.md) | diat | 4 | P1 | planned | waiting | MAT-001, MAT-051, MAT-056, MAT-063 |
| [MAT-059: Evaluate pause, rhythm and interaction motifs across meetings](MAT-059.md) | diat | 4 | P1 | planned | waiting | MAT-001, MAT-051, MAT-052, MAT-054, MAT-056, MAT-063 |
| [MAT-060: Align agenda items and procedural phases to experimental turns](MAT-060.md) | diat | 4 | P1 | planned | waiting | MAT-001, MAT-010, MAT-027, MAT-028, MAT-051, MAT-052, MAT-053, MAT-063 |
| [MAT-061: Compose conflict-aware DIAT matter assessments without identity mutation](MAT-061.md) | diat | 4 | P1 | planned | waiting | MAT-001, MAT-015, MAT-016, MAT-018, MAT-019, MAT-021, MAT-027, MAT-028, MAT-031, MAT-034, MAT-052, MAT-053, MAT-054, MAT-056, MAT-063 |
| [MAT-062: Run versioned meeting-feature ablations on identical frozen cohorts](MAT-062.md) | diat | 4 | P0 | planned | waiting | MAT-001, MAT-036, MAT-037, MAT-039, MAT-040, MAT-041, MAT-055, MAT-057, MAT-058, MAT-059, MAT-060, MAT-061, MAT-063, MAT-064 |
| [MAT-063: Enforce temporal, source-group and identity leakage gates](MAT-063.md) | diat | 4 | P0 | planned | waiting | MAT-001, MAT-006, MAT-010, MAT-036, MAT-037, MAT-051, MAT-052 |
| [MAT-064: Create independent meeting labels and useful-attention outcomes](MAT-064.md) | diat | 2 | P0 | planned | waiting | MAT-001, MAT-051, MAT-052 |
| [MAT-065: Maintain fingerprint qualification, drift and reference revocation](MAT-065.md) | diat | 5 | P0 | planned | waiting | MAT-001, MAT-016, MAT-021, MAT-025, MAT-031, MAT-040, MAT-045, MAT-055, MAT-056, MAT-061, MAT-062, MAT-063, MAT-064 |
| [MAT-066: Capture complete Oil observations, check results and recovery events](MAT-066.md) | oil | 5 | P0 | planned | waiting | MAT-001, MAT-004, MAT-006, MAT-010, MAT-011, MAT-018, MAT-025 |
| [MAT-067: Implement Oil-owned durable matter state across cognition runs](MAT-067.md) | oil | 5 | P0 | planned | waiting | MAT-001, MAT-003, MAT-005, MAT-007, MAT-016, MAT-017, MAT-066 |
| [MAT-068: Adapt bounded claim-specific evidence and assessments into Matter](MAT-068.md) | oil | 5 | P0 | planned | waiting | MAT-001, MAT-007, MAT-010, MAT-012, MAT-014, MAT-015, MAT-027, MAT-028, MAT-029, MAT-032, MAT-066, MAT-067 |
| [MAT-069: Implement generic failure recurrence and recovery matter lifecycle](MAT-069.md) | oil | 5 | P0 | planned | waiting | MAT-001, MAT-008, MAT-009, MAT-011, MAT-013, MAT-016, MAT-017, MAT-019, MAT-020, MAT-034, MAT-066, MAT-067 |
| [MAT-070: Integrate native Oil controls, mailbox freshness and delivery receipts](MAT-070.md) | oil | 5 | P0 | planned | waiting | MAT-001, MAT-011, MAT-018, MAT-019, MAT-020, MAT-021, MAT-030, MAT-066, MAT-067, MAT-069 |
| [MAT-071: Qualify chronological and live Oil matter behavior against retained value](MAT-071.md) | oil | 5 | P0 | planned | waiting | MAT-001, MAT-024, MAT-025, MAT-036, MAT-037, MAT-038, MAT-039, MAT-040, MAT-041, MAT-042, MAT-043, MAT-044, MAT-045, MAT-066, MAT-067, MAT-068, MAT-069, MAT-070 |
| [MAT-072: Enforce host scope, access and provider egress contracts](MAT-072.md) | operations | 2 | P0 | planned | waiting | MAT-002, MAT-003, MAT-007, MAT-011, MAT-028 |
| [MAT-073: Implement retention, revocation and auditable archival](MAT-073.md) | operations | 3 | P1 | planned | waiting | MAT-003, MAT-007, MAT-016, MAT-021, MAT-072 |
| [MAT-074: Version schemas, migrations and cross-language conformance](MAT-074.md) | operations | 4 | P0 | planned | waiting | MAT-002, MAT-003, MAT-012, MAT-013, MAT-024 |
| [MAT-075: Expose neutral inspection and client operations](MAT-075.md) | operations | 4 | P1 | planned | waiting | MAT-015, MAT-018, MAT-023, MAT-072, MAT-074 |
| [MAT-076: Validate and distribute immutable policy bundles](MAT-076.md) | operations | 4 | P1 | planned | waiting | MAT-012, MAT-013, MAT-014, MAT-031, MAT-074 |
| [MAT-077: Harden package distribution, CI and reuse provenance](MAT-077.md) | operations | 5 | P1 | planned | waiting | MAT-025, MAT-032, MAT-038, MAT-074 |
| [MAT-078: Instrument lifecycle outcomes and bounded audit reports](MAT-078.md) | operations | 4 | P1 | planned | waiting | MAT-021, MAT-023, MAT-042, MAT-044, MAT-072 |
| [MAT-079: Define scoped rollout, rollback and recovery procedures](MAT-079.md) | operations | 5 | P1 | planned | waiting | MAT-003, MAT-021, MAT-071, MAT-073, MAT-076 |
| [MAT-080: Qualify the integrated Matter release across profiles](MAT-080.md) | operations | 5 | P1 | planned | waiting | MAT-025, MAT-045, MAT-050, MAT-071, MAT-074, MAT-077, MAT-078, MAT-079 |
