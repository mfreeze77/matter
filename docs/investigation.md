# Bounded evidence-gap investigation

MAT-022 adds `InvestigationDefinition` and `InvestigationService`. A definition
pins the matter and inputs, names the proposition and mandatory evidence
requirements (including counterevidence), and declares bounded candidate reads.
Expected information gain is a hypothesis, never proof. This is an optional
host port over existing controls, budgets, intake and payload storage.

The host installs exact candidate declarations and supplies the reader. A
nomination cannot add a URI, source namespace or permission. The caller commits
an existing `BudgetService` reservation before starting; one allocation can fund
only one read across gap identities. The original assessment token, exact input
pins and any installed MAT-072 access context are checked before and after I/O.
Returned observations require current READ/assessment rights, actual matching
payload bytes, declared source identity/URI and eligible availability. A new
source needs explicit host admission; a returned reference cannot grant access.

Call `prepare(..., action='nominate')` and `commit`, then
`execute_read(..., previous=..., candidate=..., allocation=..., reader=...)`.
The injected reader enforces the declared transport timeout and byte bound,
ingests through `ObservationIngestor`, and returns at most 32 exact observation
pins. This synchronous port cannot preempt arbitrary Python callbacks. It checks
elapsed time on return and refuses late evidence. There is no connector,
provider client, timer scheduler or external-write operation here.

The durable start is claimed before I/O. Exact retries, including a recreated
service, do not invoke the reader again. An interrupted read remains `started`
and unknown; it is not automatically retried or declared satisfied. Successful
acquisition fulfils only the candidate's declared requirements. Supporting
material cannot displace missing mandatory counterevidence, and acquired
evidence need not resolve a downstream conflict.

Stop reasons are `evidence_satisfied`, `no_eligible_source`, `conflict_persists`,
`budget_exhausted`, `cancelled`, `source_unavailable`, and `decision_required`.
Budget exhaustion never means sufficient evidence. Renewing a quota or token,
changing a cosmetic version, or changing an information-gain hypothesis cannot
restart an unchanged stopped gap. Changed inputs, a new eligible source, or a
newly due declared retry boundary can nominate new work. The host owns any
subsequent scheduling. `inspect` always reports `human_question=False`; an
unresolved gap does not automatically become a question to the operator.

The [follow-through receipt](validation/civic-followthrough.md) records actual
checks. These synthetic host/read tests establish protocol behavior, not the
usefulness of a retrieval strategy or semantic correctness of acquired sources.

A failed candidate does not consume another already-approved alternative: the
host can request that unattempted candidate using a separate committed allocation
within the same finite gap. Each failed attempt remains in its control receipt.
After all alternatives are unavailable the gap stops; quota renewal alone cannot
restart it. No fallback is executed automatically.

A control/budget race at finish commitment retains the failed receipt and permits
one empty bookkeeping recovery under a distinct key, with the original work
token and no second read. Further contention or loss of READ rights can still
require the host to finalize the retained started record through the existing
explicit `prepare(..., action='finish')` port; it is never labelled satisfied or
blindly reread. A lost acknowledgement of a pre-read budget stop replays its exact
recorded outcome and checks the original request arguments.
