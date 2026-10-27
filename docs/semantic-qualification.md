# Runtime semantic qualification

`matter.semantic.qualification` consumes actual MAT-030 execution receipts. Raw
execution, exact numeric admission, method qualification and host authority stay
separate. Every original BatchResult remains `qualification_status=unknown` and
`consequential_use=false`. A certificate does not make evidence true or grant a
capability. The existing rule `QualificationRegistry` is unchanged.

Install `SemanticQualificationService(storage, controls=..., receipts=...,
reviewers=[exact_host_review_producer], clock=...)` on the same scoped store as
its actual `ExecutionReceiptStore`. Review producers are explicitly configured
by the trusted host. The raw storage/payload ports remain privileged machinery;
an arbitrary user cannot mint a review by supplying certificate JSON.

`SemanticCertificate` is immutable, content-addressed data. It binds requested
and observed concrete model, host model-resolution declaration, provider,
transport, adapter version/mode, exact question semantic reference (including
wording, rubric and ordered options), criteria digest, renderer, packet profile,
preparation algorithm, explicit eligible domain, measure/unit, trusted precision
profile, positive/negative regions and exact held-out evaluation receipt. Packet
values and source instance IDs are not substituted for a domain definition.
Model aliases without an observed resolved model cannot qualify.

`prepare_install` and `prepare_revoke`, followed by `commit`, use the existing
host `record_control` transaction. Only the exact public certificate slot gets
a control fence. Complete public consumed targets still need current host
capability and READ authority. Installation reads a real host-origin receipt
from a configured review producer and exact pinned artifacts. Its report binds
the same identity/regions, held-out passed status, independent labels, separate
polarity support/minimum support, target/lower accuracy and an explicit interval
method. Each polarity minimum counts independent accepted episode decisions,
not its larger pre-threshold cohort: `minimum_episodes <= accepted <= episodes`.
Runtime checks support and exact arithmetic consistency; it does not fit
confidence intervals, manufacture evaluation reports or verify empirical accuracy.
Failed/not-run/teacher-only/insufficient reports remain recordable but unusable.
Revocation needs present host authority and never waits for model work.

`preflight(view, request, question_id=..., certificate=..., domain_scope=...,
measure=..., token=..., access_context=..., as_of=...)` checks known applicability
before execution. Success is only `applicable_pending_execution`: actual resolved
model, exact whole-batch admission and region selection still require the observed
execution. Applicability always uses the actual injected host clock: an earlier
`as_of` sample cannot backdate eligibility, and future hints are refused. No token
is captured or renewed inside any qualification method.

`inspect(view, execution_pin, question_id=..., certificate=exact_ref_or_none,
domain_scope=..., measure=..., token=..., as_of=...)` rereads the actual stored
receipt and validates its original wire/result, source/current controls and access
context. It returns `SemanticAdmission`: explicit method status, refusal reason,
positive/negative/abstained decision, exact decimal measure and pinned provenance.
It checks applicability again at consumption. Closed positive and negative regions
must be disjoint; a gap such as Noul `0.5` remains abstained. A valid partial head
cannot rescue a failed whole batch. Contradictory heads are not combined into
truth or silently reconciled by this service.

`classifier(...)` supplies MAT-030's actual `(view, execution, request, as_of)`
reuse callback. An expired/revoked/mismatched/abstained method cannot qualify a
cache hit. `stage_classifier(certificates={question_id: exact_certificate_ref},
domain_scope=..., measure=..., token=...)` supplies MAT-029's callback. It accepts
only an actual persisted MAT-030 `view_result` with the exact current Batch and
prepared input; a raw detached result remains unknown. It rereads original
receipt data and refuses altered diagnostics. Undecided/unqualified regions map
to unknown and cannot unlock a qualified parent edge. Reuse observations resolve
to the original execution; they add no independent trial or provider call.

For durable current consumption, prepare the typed `admit_semantic_result`
command with body `{execution, question_id, certificate, domain}` using
`prepare_admission(command, token=original_work_token, measure=...)`, then `admit`.
The result returns the actual original execution pin, admission projection pin
and recorded qualification status. `recorded` means the decision was persisted;
it can explicitly be unqualified. Its strict extension retains original token,
measure, access context and exact previous state/recomputation fence. The atomic
writer recomputes applicability from the actual records and registers source,
certificate and time dependencies. Revocation races refuse stale publication.

Install the existing `InvalidationHook` for proactive transitive invalidation.
Real assessments can consume the registered admission pin as an explicit semantic
dependency. Certificate revocation invalidates that admission and its dependent
assessment/current lane in the same control transaction. Historical execution,
review and then-applicable admission snapshots remain unchanged. `current` checks
registration freshness; `history` checks present READ/access authority over an
exact retained admission, without relabeling it as currently eligible. A raw
store opened without the host hook remains privileged; current freshness gates
still refuse stale registered results.

All included reports and cases are synthetic. This work issues no real certificate,
measures no provider accuracy, grants no permission/action authority and does not
bypass MAT-039/040 evaluation or release gates. No network call, private evaluation
corpus, replacement registry, fitting pipeline or transport is introduced.
