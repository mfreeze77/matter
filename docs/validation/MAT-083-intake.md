# MAT-083: SQLite contention and intermittent-failure intake

Recorded 2026-10-31 (UTC). Ticket filing only: no SQLite/semantic implementation fix,
new reproduction, provider call, StateCivics edit, image build or deployment.
The canonical [MAT-083 ticket](../../tickets/MAT-083.md) remains planned, with
implementation validation `not_run`. Prior failing receipts remain failures.

## Matter merges verified in this follow-up

GitHub reports all four PRs merged on 2026-10-31, at the reviewed heads:

- [#26](https://github.com/mfreeze77/matter/pull/26):
  `05708639235142c4b1d360595b15610580394fbb`, head `9cf444a86c238dc135736f7a8b6dfe7e062c2e2c`.
- [#27](https://github.com/mfreeze77/matter/pull/27):
  `4360de50eddc571886ae61af57e8e5b58470fa26`, head `85284851f21b13f4eb3117dd67efb0441f807fe7`.
- [#28](https://github.com/mfreeze77/matter/pull/28):
  `ff4fc08cfc3e0fba41390f3d148e9ebc797240ee`, head `f95a57e04848626237ab162ed98f8d4d25fe0b4d`.
- [#29](https://github.com/mfreeze77/matter/pull/29):
  `10a7d9ac02807ab91db1966b1795e4bc1f7484d1`, head `e28cdeba4206e2019cc3f4986ac0963490ff4f3a`.

After fetching main, `git diff --exit-code MERGE CANDIDATE -- src schemas
pyproject.toml` is empty for #26/`9cf444a` and main `10a7d9a`/runtime `59bfed9`.
This verifies source equivalence, not the external image or wheel bytes.
The earlier [SDK handoff](../adapters/statecivics-sdk-handoff.md) and
[validation closeout](dashboard-matter-handoff.md) describe pre-merge candidates;
their open-PR statements are historical snapshots, superseded here.

## Existing local failure: reproduced, unresolved

`integration.test_dispatch_races.DispatchRaces.test_distinct_equivalent_intents_compete_across_real_sqlite_handles`
uses two actual SQLite handles against one database and two distinct equivalent
intent IDs. It expects one ready winner and one withheld or stale loser, followed
by exactly one winner delivery.

Retained command:

```sh
PYTHONPATH=tests .venv/bin/python -m unittest integration.test_dispatch_races.DispatchRaces.test_distinct_equivalent_intents_compete_across_real_sqlite_handles -v
```

The prior run failed in **30.536s**, at `test_dispatch_races.py:126`. The loser
`prepare_delivery` operation `intent-a` returned `status: failure`,
`E_STORAGE_UNAVAILABLE`, `retriable: true`, detail “Storage could not establish a
durable outcome.” It did not return withheld or `E_DEPENDENCY_STALE`.
The existing receipt names Python 3.12.14, SQLite 3.53.1, Darwin/arm64.
This was the pre-merge `284047a` inspection, not a new run of merged main.
Raw evidence: gitignored `data/validation/sdk-handoff-20261030/race-reproduction.log`.
The storage/delivery/test files were unchanged by the reviewed stack; that does
not establish a cause or dismiss the failing behavior.

## Two intermittent findings: retained CI evidence, not local reproductions

Both appear in retained #26/Python 3.12 and #27/Python 3.11 logs:

1. `integration.test_dispatch_races.DispatchRaces.test_cancelled_never_authorized_work_can_be_withdrawn_then_replaced_without_renewing_old_token`.
   At test line 245, `enqueue(identity="new-after-withdrawal")` reached
   `delivery_helpers.py:75` and returned **withheld instead of ready**. The
   operation was successful `prepare_delivery`, with `reasons:
   ["insufficient_evidence"]`, unknown/not-applicable reconsideration and
   delivery reason `delivery:insufficient_evidence`. It was not a storage error.
2. `semantic.test_stages.StageTests.test_one_expired_member_does_not_abort_compatible_independent_member`.
   At `test_stages.py:415`, independent stage `c_contradiction` was **blocked
   instead of completed**. The scenario intentionally expires the selection
   member, expects `b_recovery` to report `E_DEPENDENCY_STALE`, and expects the
   independent contradiction branch to complete (three executor calls total,
   final question `contradiction`). The failed status assertion does not prove
   the later call-count assertions passed.

Raw evidence: `data/validation/sdk-handoff-20261030/ci-pr26-py312.log` and
`ci-pr27.log`; prior triage is in the
[existing CI gap](dashboard-matter-handoff.md#existing-ci-validation-gap).
Source jobs: [#26/Python 3.12](https://github.com/mfreeze77/matter/actions/runs/40788435853/job/123167347211)
and [#27/Python 3.11](https://github.com/mfreeze77/matter/actions/runs/40798017787/job/123199093056).
No local reproduction or shared SQLite/clock cause is claimed. MAT-083 requires
an explicit disposition for each, with a linked follow-up if distinct scope is
demonstrated. Passing a repeated run alone does not establish a repair.

## StateCivics receiving evidence: reported, not independently run here

The owner supplied this handoff:

- Image `ks-test-runner:matter-10a7d9a` was built from merged Matter main
  `10a7d9a`, with all **202 packaged files byte-equal** to that commit.
- Both #26 civic source and #29 saved-objective interfaces are exported.
- **219 historical-replay tests passed, none skipped** in that image.
- The wheel digest was supplied only as **`3d19879b…`**, an incomplete prefix,
  not a usable SHA-256 pin. StateCivics attributes the different wheel bytes
  to its Python 3.11 build. Matter has not inspected that image/wheel or
  independently verified that build explanation. Obtain the full digest and
  build receipt before treating it as a pinned external artifact.

These receiving results do not clear the neutral SQLite failure and are not
live-provider interpretation, empirical qualification or production readiness.
At the time of the supplied report, StateCivics KS-1121 was in progress on
`ks1121-civic-monitoring`, with its full statewide suite and merge-against-main
review still running. StateCivics owns those results and any merge/closure.
Nothing goes live: the study remains rehearsal-only, with activation joint with
the Workbench and state intel. No outcome of the pending work is inferred here.

## Ticket filing checks

The canonical record was rendered with `python -m matter render`;
`render --check`, `validate` (83 tickets, 104 requirements, 107 schemas and
three walkthroughs) and `git diff --check` pass. These checks validate ticket
structure/projections and whitespace, not a SQLite repair. The named behavioral
failures and StateCivics suite were not rerun in this follow-up.
The independent two-pass ticket/index JSON review covered both selected files
in 97.2s with zero findings or warnings. Raw filing-check and review receipts
are retained in gitignored `data/validation/MAT-083-intake/`.
