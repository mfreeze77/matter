# Rule, profile, and assessment contract

MAT-012 implements the bounded rule/evaluator interface described in [the runtime API](../rules.md): immutable definitions, detached inputs, deterministic and recorded bindings, direct prerequisite admission, and uncommitted attempt receipts. Policy composition, assessment publication, transitive invalidation, live providers, and qualification issuance remain later milestones. The governing sections below include those planned contracts; structural or deterministic interface conformance does not qualify the assessment engine.

Sources: [matterbrainstormspec](../../matterbrainstormspec), sections 2–7, and [matterjevmesh](../../matterjevmesh), sections 1–8. Read [core](core.md) for identities and time, and [lifecycle](lifecycle.md) for consequences and delivery. The core is provider-neutral. No Jev-specific client behavior is specified here.

## 1. Common rule families

Profiles compose rule families whose outputs have explicit meanings. A family is a question category, not a universal classifier or shared threshold.

| Family | Required question | Domain-owned semantics |
|---|---|---|
| association | What subject or occurrence does this evidence concern? | Candidate keys, allowed associations, ambiguity |
| evidence | What does this evidence justify concluding about this proposition? | Eligibility, authority, proof, counterevidence |
| change | Which relevant facts, relations, or interpretations changed? | Material differences and their consequences |
| recurrence | What condition persisted or happened again? | Distinct occurrences, windows, dependence groups |
| consequence | Which purpose, obligation, or dependency is affected? | Impact, actionability, commitments |
| temporal | Is a known condition due, expired, missing, or stale? | Calendars, coverage, deadlines |
| resolution | What establishes a permitted domain transition? | Matching success, dispositions, withdrawals |
| attention | What does this audience need at this time? | Responsibility, delivery history, preferences, cost |

New families MAY be added through versioned schemas. The engine MUST NOT require every profile to use every family. Deterministic comparisons, exact identity joins, arithmetic, date computation, and authority checks SHOULD use code. Semantic evaluators may contribute bounded judgments where the declared rule needs interpretation.

No rule family requires a global importance number. Relevance, impact, recurrence, uncertainty, urgency, authority, and interruption cost remain separate dimensions. A profile may define a local ranking function after required gates, with units and order semantics. Its values cannot be compared with another profile's values unless an explicit, qualified mapping defines that comparison.

## 2. Rule definition

Each immutable rule definition MUST include:

| Field | Contract |
|---|---|
| rule_id and semantic_version | Stable identity and version of the meaning, not only executable code |
| family and description | Declared question category and intended use |
| input_schema and output_schema | Exact versioned structural contracts |
| proposition_template | Which claim or relation is being evaluated, including relevant qualifiers |
| evidence_requirements | Eligible source classes, scope, availability boundary, mandatory checks, counterevidence |
| preconditions | Deterministic prerequisites and allowed behavior when missing |
| dependencies | Named upstream rules, accepted output states, and exact outputs consumed |
| outcomes | Defined labels and what each establishes or leaves unresolved |
| evaluator_binding | Deterministic function or provider-neutral evaluator descriptor |
| qualification_requirement | Required certificate scope and acceptance criteria, or reason no learned judgment is used |
| conflict_policy | Named resolver for incompatible results; never execution order |
| consequence_permissions | Proposals this rule may emit; authoritative transitions remain separate |
| resource_limits | Input size, candidates, calls, retries, elapsed time, and cost limits |
| temporal_dependencies | As-of semantics, expiry, relevant scheduled transitions |
| conformance_cases | Inputs with required outputs or required invariants |

A rule must expose its full meaning to an evaluator. An opaque ID is not a substitute for proposition text, label definitions, scope, or evidence. A change to labels, ordered options, prompt rendering, eligibility, evidence truncation, or accepted outcome implications is a semantic change if it can alter behavior. The version or binding digest must change accordingly.

A definition may reference an immutable shared component rather than repeat its bytes. It must be possible to reconstruct the exact executed definition. Missing referenced versions yield E_POLICY_INVALID or E_EVIDENCE_UNAVAILABLE, not a best-effort reinterpretation using the latest version.

## 3. Evaluation input

An evaluation input binds:

- Rule and evaluator-binding versions.
- Matter ID and the revision used, if the rule concerns a matter.
- A proposition or relation and its versioned scope.
- Evidence packet references, selected passages, omitted eligible evidence, and coverage.
- Accepted association and occurrence-group revisions.
- Dependency outputs and their qualification status.
- Purpose, objective, audience, or disposition versions only when they influence this rule.
- Knowledge boundary and relevant event/effective intervals.
- Resource budget and cancellation/control epoch.

Evidence preparation is a declared part of the rule contract. It must not silently drop contradictory evidence because it ranks below agreeing passages. Bounded selection must record truncation and mandatory omissions. A required source outside the packet produces incomplete evaluation unless the rule explicitly allows a weaker conclusion.

Direct instructions and credentials do not enter this data packet as executable authority. Host-accepted controls are referenced through their scoped effective state. An instruction embedded in a source remains quoted evidence.

A fixed evidence packet may support independent concurrent judgments. A dependent judgment must receive the validated upstream result as part of a later input. Merely including both questions in one request does not satisfy the dependency.

## 4. Judgment result and qualification

The result separates execution status, semantic outcome, and qualification:

| Dimension | Values and meaning |
|---|---|
| execution_status | completed, failed, cancelled, timed_out, budget_exhausted |
| evaluation_status | applicable, not_applicable, insufficient_evidence, ambiguous, conflicting |
| semantic_output | Schema-defined conclusion, labels, exact decimals, ranking, gap, or proposal |
| qualification_status | not_required, qualified, unqualified, expired, mismatched, unknown |
| provenance | Exact input, question, evaluator, attempts, timing, raw result reference |
| evidence | Used references and locators; unsupported claims cannot invent source IDs |
| limitations | Omissions, failed prerequisites, disagreement, and unresolved scope |
| dependency_manifest | Positive read set, negative watches, time conditions |
| proposed_consequences | Typed proposals permitted by the definition, never external actions |

A failed execution cannot claim a completed semantic output. A partial response may retain completed independent components, but dependents requiring a missing component remain unevaluated. Retrying one component must not erase earlier failed attempt receipts or count multiple answers as independent evidence.

A qualification certificate binds a rule meaning and evidence preparation, evaluator implementation/model, output interpretation, applicable task/domain strata, threshold policy, validity period, and evaluation evidence. High reported confidence does not substitute for a missing or failed certificate. A certificate for same-topic cannot qualify same-matter or same-occurrence decisions.

Deterministic rules can use qualification_status not_required only if their binding declares exact semantics and conformance cases. A model result may be retained unqualified for analysis. It must not satisfy a required qualified prerequisite.

Independent scores MUST NOT be multiplied or summed into an asserted joint probability unless a separately specified and validated probabilistic model justifies the calculation. Logical consistency is checked by composition rules. Multiple agreeing interpretations derived from one source remain correlated evidence.

## 5. Profiles and audience bindings

A policy profile is an immutable, named, versioned assembly of rule definitions, parameters, allowed data/authority scopes, lifecycle extensions, conflict resolvers, resource budgets, and conformance cases. It names required and optional outputs, conditional paths, and what incomplete evaluation permits.

A matter can have recommended default profiles but is not owned by one interpretation. Every assessment binds the exact selected profile, purpose revision, and relevant audience-context revision. Several assessments may coexist for the same matter and evidence.

Separate profile components are encouraged:

- Evidence profile: eligibility, authority, proof, claim relationships.
- Domain lifecycle profile: transitions, resolution, reopening, supersession.
- Purpose profile: objectives, consequence and dependency meaning.
- Audience profile: responsibility, preferences, prior delivery, interruption budget.

Changing an audience's delivery cadence must not alter source truth or automatically rerun unchanged evidence judgments. Changing an evidence standard may invalidate claim assessments without creating a new source event. A profile update cannot mutate historical assessments in place.

Profile validation rejects missing rule versions, cycles, incompatible schemas, undefined outcome labels, references to unauthorized capabilities, ambiguous conflict resolution, required outputs with no path, and impossible budget configurations. Validation must explain the offending path. Profile source text is data; it cannot execute arbitrary code. An explicitly installed deterministic evaluator is invoked through the host's permitted binding registry.

## 6. Composition and dependency order

The default sequence is scope and evidence availability, association, evidence interpretation, consequence, material change, and attention. A profile declares the actual dependency graph; sequence is not inferred from file order, question IDs, or completion time.

The planner MUST:

1. Validate an acyclic graph, including conditional edges.
2. Resolve typed inputs and permitted evidence before execution.
3. Schedule independent nodes concurrently within the shared budget.
4. Run dependent nodes only after all required predecessors produce admissible results.
5. Record skipped, blocked, and unqualified paths separately from negative semantic conclusions.
6. Reject stale reads or cancelled control epochs when committing results.
7. Apply an explicit conflict resolver and preserve the original disagreeing results.

A deterministic resolver may choose precedence by source authority or rule specificity if the profile declares it. Majority vote, higher confidence, recency, or last writer is not an implicit fallback. An unresolved conflict remains a conflict, even when a delivery policy chooses to withhold it.

A mandatory authority or permission gate is not an item in a weighted ranking. A large consequence score cannot offset its failure. Required source coverage cannot be offset by a confident semantic answer.

## 7. Assessment operation and result

The assess operation accepts the matter revision, profile revision, purpose/context references, evidence selection or query definition, as-of boundary, and resource/cancellation context. The result records:

- Assessment identity and prior applicable assessment, if any.
- Full input and dependency manifest, including omitted evidence and negative scopes.
- Component judgments with execution and qualification status.
- Supported, refuted, mixed, or unresolved propositions under the profile.
- Domain transition proposals and why they qualify or remain held.
- Consequence dimensions for the declared purpose.
- Material changes separated by cause.
- Evidence gaps and optional bounded investigation proposals.
- Proposed attention treatment, if this profile includes attention.
- Expiry and scheduled reconsideration conditions.
- Resource use and the exact reason evaluation stopped.

Cause labels include new_evidence, evidence_correction, association_correction, policy_change, purpose_change, audience_change, disposition_change, and temporal_transition. A policy change must not be rendered as a newly observed external event.

Assessment commit uses optimistic concurrency against every declared positive dependency, watched negative scope revision, relevant control epoch, and contextual revision. If any input changed, return E_DEPENDENCY_STALE and retain the attempted result as non-current evidence of the attempt. Never publish it as a current assessment and promise to repair it later.

## 8. Cache identity and invalidation

Caching is per semantic computation. Its key includes rule definition, evaluator binding, evidence preparation, exact selected evidence and association versions, upstream qualified outputs, relevant context, and temporal equivalence class. A timestamp changing by a millisecond need not invalidate a timeless comparison; crossing a declared deadline must invalidate the affected temporal result.

Two audience delivery policies can reuse one evidence judgment when that judgment has no audience dependency. A changed interpretation or material evidence revision must not reuse a result simply because the matter ID is unchanged.

Dependencies include positive object references, query/candidate-set revisions, and absence watches. Examples:

- New evidence arriving in a previously empty eligible query invalidates an absence conclusion.
- A new candidate matching an association query invalidates a prior unique-match assessment.
- A source becoming inaccessible invalidates conclusions requiring its currently readable locator.
- A corrected occurrence grouping changes recurrence counts even if source texts are identical.
- A new accepted disposition changes applicable attention or lifecycle behavior.

Invalidation is transitive through judgments, assessments, transitions pending commitment, attention candidates, and queued deliveries. Historical results remain inspectable with reasons and revision boundaries. A changing audience preference should reach only dependencies that actually read it.

## 9. Bounded investigation contract

An investigation proposal names a specific unresolved proposition, the evidence requirement it would address, permitted source/read candidates, expected information gain as a labeled hypothesis rather than proof, and a shared resource budget.

The core may nominate reads; the host authorizes and executes them. A proposal does not grant tool access, expand source permissions, or authorize messages or other external writes. Results enter as observations with provenance and availability.

Stop reasons are evidence_satisfied, no_eligible_source, conflict_persists, budget_exhausted, cancelled, source_unavailable, or decision_required. Evidence_satisfied means the declared requirement is met; it does not imply every downstream rule succeeds. Budget exhaustion must not be relabeled sufficient evidence.

Repeated investigation of the same unchanged gap requires a new eligible source, changed input, scheduled condition, or a declared retry policy. Shared per-matter and per-run budgets prevent several concurrent rules from independently exhausting the user's resources. An unresolved result can remain quiet; it is not automatically a human escalation.

## 10. Portability and qualification boundary

Language independence requires interoperable schemas, canonical encoding vectors, operation histories, conflict cases, and deterministic conformance episodes. Structural validation is necessary but insufficient. Provider replacement requires separate semantic qualification, even when output shapes match.

The reference engine must support domain-neutral examples through profiles rather than branches checking application names. Two synthetic profiles must prove the same machinery can preserve evidence, distinguish recurrence, produce contextual assessments, and apply different resolution rules. These fixtures are not permission to modify OIL, StateCivics, or DIAT.

Conformance evidence must include omitted counterevidence, ambiguous identity, changed semantics with unchanged schema, stale dependency races, negative-scope invalidation, deadline-only changes, and unresolved evaluations that remain quiet. Actual provider accuracy and production attention usefulness are separate qualifications and must not be inferred from deterministic core tests.
