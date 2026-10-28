# Neutral-core synthetic qualification

MAT-025 reuses the existing actual SQLite, replay, controls, assessment,
lifecycle, attention, outbox and budget tests. It adds a frozen requirement map
and machine-readable receipt, rather than a second engine or rehearsal stack.
The selected assertions and fixture files supply expected and allowed outcomes;
the run freezes their hashes, the actual imported runtime and packaged schemas
before executing any selected test.

Run from the repository with the chosen runtime installed:

```bash
TMPDIR=/private/tmp PYTHONPATH=tests python examples/core_qualification.py --output data/validation/core-qualification-new
```

On systems without `/private/tmp`, use an existing platform temporary directory.
The output destination must be new. `frozen.json` preserves the plan and input
inventory before execution; `report.json` preserves each check's result and
elapsed time, CORE-01–24 and AC-1–4 mappings, source stability, declared SQLite
settings and unrun gates. Missing, skipped, failed or unrun required checks cannot
pass. A changed source inventory fails the run. A test assertion's temporary
SQLite database is not claimed to have been archived; its receipt is the named
executed assertion and frozen source, not a fabricated native database capture.

The two synthetic replay profiles use shared operations and different declared
lifecycle edges in the test host. The common engine contains no StateCivics/Oil
application dispatch. Shared frames check source availability, actual current
state, receipts, quiet reasons and zero external deliveries. Additional selected
cases cover recovery and later genuine recurrence, correction, source-role
spoofing, protected undo, absence uncertainty, critical first contribution,
delivered-versus-internal baseline, owned work, read freshness, cancellation,
process interruption and ambiguous delivery. Existing actual budget races and
idempotent intake checks supply concurrency and repeated-work evidence.

This is bounded synthetic conformance. It covers the specified assertion matrix,
not all workloads, physical power failures or other storage backends. It does
not qualify JEV interpretation, certify a civic authority or establish useful
production alerts. `provider_accuracy`, `live_usefulness`,
`domain_acceptance`, `other_storage_backends` and `physical_power_loss`
remain `not_run` even when the synthetic report passes.

[Actual follow-through checks and limits](../validation/civic-followthrough.md)
record the run and separate provider/domain work. MAT-040 still needs independent
held-out labels, appropriate support, approved targets and reviewed results;
MAT-047/048/049/050 and receiving acceptance retain their separate ownership.

The final report contract is `matter.core-qualification-report.v2`. Earlier
provisional v1 receipts are retained with their frozen schemas as historical
evidence; they are not advertised as validating against the final v2 contract.
