# StateCivics dev17 receiving acceptance

Owner-relayed receipt, retained verbatim below; SHA-256 `2fceabad128335f2e3e584bfa89b1593087127761cd4e5cc28cbdfccca46d179`. Matter independently checked StateCivics main `eb8195320`, its byte-equal src/tests against receiving-test commit `314daf0a6`, the exact image ID and all 205 installed runtime file hashes against the pinned Matter source, plus the six private predicate call sites. Test results, rebuilt-wheel digest and elapsed times below remain reported by StateCivics, not rerun here. Concurrent-load receiving timings are not directly comparable to Matter's standalone prototype. No live interpretation, qualification or deployment is established.

StateCivics receiving check for Matter dev17 (PR #32, main `f2ce051`, runtime `eb6f563`), 2026-10-31.

**Freeze**
`git diff 1f525c6 35f330a -- src schemas pyproject.toml` is empty: the frozen 1.1 is the runtime StateCivics tested.
KS-1146 is closed on it.

**Identity**
- **Wheel:** rebuilt offline from `f2ce051` with Python 3.11.17, `SOURCE_DATE_EPOCH` set to the commit time, and
  `--no-index --no-deps --no-build-isolation`.
  - `matter_foundation-0.1.0.dev17-py3-none-any.whl`, SHA-256
    `559532627326b958533eee5e8471539ee426d83b63e9f572fc7e90b9a3ba544a`.
  - All 205 packaged files are byte-equal to `f2ce051`: 96 from `src/` and 109 from `schemas/`.
  - The digest differs from Matter's `19196815…` because the builds ran in different environments; the files are
    the same.
- **Image:** `ks-test-runner:matter-f2ce051`, ID `sha256:d4bb40f071325c7450cdb65e88f996b68013ff7b89530cbb26355256344c16e4`.
  It imports `0.1.0.dev17` from site-packages.

**Public milestone builder**
StateCivics' 1.0 host path now calls `matter.attention.build_delivery_milestone_details` and no longer imports
`matter._rule_values.domain` (KS-1148).

**One small ask:** StateCivics still uses one private name, `matter.access._public(ref)`, in 6 places. It chooses
which pinned references are access targets: not receipts, controls or Matter's own `matter.*` projections. Could Matter
expose it under a public name, as it did for the milestone builder? StateCivics would rather not copy the rule and
let it drift from Matter's.

**Results on dev17,** at StateCivics `314daf0a6`. The test files ran each test in its own container, six at a time; the proof ran as one process:
- **Matter's capture tests** from `f2ce051` (integration, policy and vectors, with the repository's `pyproject.toml`):
  **30 passed**, in 224 s wall.
- **StateCivics' Matter dispatch tests** (each in its own container): **11 passed**, in 220 s wall. That covers the 1.0 host rule, the 1.1 model
  path, mixed baselines, pause and revocation during the call, provider failure, refusals, and stale or capped
  attempts.
- **The PostgreSQL proof with Matter:** 35 cases, exact identities, in 198 s.

**Speed, under concurrent load** (the statewide suite and the proof running alongside):

| | dev16 | dev17 |
|---|---|---|
| The 11 dispatch tests, wall | 1,269 s | **220 s** |
| The 11 dispatch tests, summed per test | 5,523 s | **1,007 s** (5.5×) |
| Matter's capture tests, wall | 1,227 s (29 tests) | **224 s** (30 tests) |
| The PostgreSQL proof | 634 s | **199 s** |

**Not claimed:** live JEV interpretation, qualification, or MAT-083 (still open on Matter's side).
