# Scaffold validation receipt

**Executed on 2026-10-08: local scaffold checks passed.** This receipt covers the repository tooling and synthetic walkthroughs delivered by MAT-001. The production, integration, research, and qualification tickets retain their own future acceptance obligations.

## Environment and commands

Local execution used Python **3.12.14**, setuptools **84.0.0**, and jsonschema **4.26.0**, with dependency constraints recorded in [requirements-test.txt](../requirements-test.txt).

| Executed command | Result |
|---|---|
| `python -m pip install --no-build-isolation -e . -c requirements-test.txt` | Editable package built and installed successfully |
| `python -m matter render --check` | Passed; no stale generated projections |
| `python -m matter validate` | Passed; 80 tickets, 104 requirements, 3 schemas, 3 walkthroughs, zero errors |
| `python -m unittest discover -s tests -v` | **39 tests passed** |
| `python -m matter demo all` | All three synthetic scenarios executed successfully and matched their independently declared expected results during validation/tests |

The local verification commands used `PYTHONDONTWRITEBYTECODE=1` to avoid incidental bytecode files. The module commands work after installation without setting `PYTHONPATH`. The local package installer placed the optional `matter` executable outside the shell's PATH; `python -m matter` is the documented and verified entry point.

The [GitHub Actions workflow](../.github/workflows/validate.yml) defines Python 3.11 and 3.12 checks with pinned action revisions. Both jobs completed successfully in [run 37750500591](https://github.com/mfreeze77/matter/actions/runs/37750500591) for the first published scaffold commit, `2f541a5caeae9f8a279390007d7704b801b98332`. This is executed remote evidence in addition to the local Python 3.12 checks. Later commits have their own head-specific results in [PR #1](https://github.com/mfreeze77/matter/pull/1).

## Roadmap integrity

The canonical records contain **80 tickets, 104 requirements, 271 acceptance criteria, and 340 specified future/scaffold test cases**. The 340 listed cases are backlog obligations, not 340 executed tests. Every requirement maps to at least one ticket; every dependency exists; the graph is acyclic; no ticket's phase precedes a prerequisite; and generated ticket pages, indexes, and coverage match their sources.

| Target owner | Tickets |
|---|---:|
| `mfreeze77/matter` | 58 |
| `mfreeze77/statecivics-local-crawler` | 1 |
| `mfreeze77/statecivicsai-diat` | 15 |
| `mfreeze77/oil` | 6 |

Ownership records planned downstream responsibility. They do not imply that any downstream repository was modified. MAT-001's completion evidence is recorded in its [canonical record](../tickets/records/MAT-001.json); the other 79 tickets remain planned and unqualified by this scaffold execution.

The scaffold is published in [PR #1](https://github.com/mfreeze77/matter/pull/1) on `build/matter-foundation-roadmap`. The initial commit added 201 files, and its uploaded tree `8a3c65b255e977f068be6b896c7fe62a33da8cc7` matched the local index exactly. The completion update records this reviewable result and derives the ready-to-start tickets from the completed MAT-001 milestone.

## Behavior exercised

The tests include malformed and unknown ticket fields, duplicate IDs, invalid dependencies and cycles, phase inversions, unknown or uncovered requirements, completion without evidence, readiness semantics, strict JSON rejection, unsafe output paths, and preflight-before-write behavior.

Lifecycle tests cover scope isolation, immutable duplicate event content, stable identity across context changes, audience-specific pending updates, coalescing at delivery boundaries, wrong or old recovery, future-evidence rejection, unqualified hints, immediate controls, and rollback after invalid events. In particular, the executable review found and fixed cases where unqualified material could advance state or block an otherwise valid recovery.

| Synthetic fixture | Declared outcome |
|---|---|
| Oil: 21 input events | 2 simulated deliveries; 1 immediately forwarded stop; stable matter identity across 12 observations, 7 distinct occurrences, and 2 episodes; no queued update remains |
| Civic: 11 input events | 1 simulated delivery; 7 observations, 4 occurrences, and 2 episodes; prior resolution and late evidence do not prevent a genuine later recurrence |
| DIAT: 8 input events | 1 research hint; an unqualified hint does not establish state; the anonymous matter ends resolved after 6 observations and 2 occurrences |

The fixtures contain invented identifiers and trusted, preclassified host input. A simulated delivery records a local outcome; it does not establish transport success, consumption, action, identity, or usefulness in a live session.

## Review and practical limits

The governing documents and assembled roadmap were reviewed for core/domain ownership, provider replaceability, numeric representation, authority, stale evidence, recovery, dispatch freshness, and implementation-status accuracy. The three original design notes and LICENSE remain byte-for-byte unchanged relative to the inspected starter snapshot.

No remote evaluator, real meeting corpus, native Oil hook, persistent matter store, or production deployment was exercised. Domain accuracy, latency, cost, attention usefulness, acoustic identity, and cross-language runtime conformance require the explicitly scoped future tickets and their own measured evidence.
