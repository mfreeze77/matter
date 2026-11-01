# MAT-084 receiving acceptance

Owner-relayed final StateCivics receipt, retained verbatim below. Matter inspected the receipt, image identity and raw profile; the consumer test counts are attributed to StateCivics, not a Matter rerun.

Original external receipt SHA-256: `7df409b605eb39bd188a4c54715c138786d8311e304b0046fc46f76752ecd406`.

StateCivics KS-1146 receiving receipt for MAT-084 (PR #31), 2026-10-31.

**Identity**
- **Source:** Matter `1f525c6a66593573f2ae5d2af1eaf2bd00460a35`. Tests, vectors and docs read from PR head `3e70eca`.
- **Wheel:** StateCivics rebuilt `matter_foundation-0.1.0.dev16-py3-none-any.whl` offline, with Python 3.11,
  `SOURCE_DATE_EPOCH` set and `--no-index --no-deps --no-build-isolation`. Its SHA-256 is
  `19b1dfe6253d5912119436b623de9bf85cf848454186de35482a9a338e545aa2`. All 204 packaged files are byte-equal to
  `1f525c6`; the digest differs from Matter's 3.12 build, as the handoff expects.
- **Image:** `ks-test-runner:matter-1f525c6`, ID `sha256:e6d1f7c98e5735e5dde8e74d121f4067391f40d18d65e8c1c4e5752eec72ef6e`.
  It installs `matter-foundation 0.1.0.dev16` into site-packages.
- **Shared identity:** `statecivics_capture.conveyed_capture_identity` is `statecivics_monitoring.conveyed_capture_identity`.

**Matter's own tests in this image**
- `3e70eca`'s `tests/integration/test_monitoring_capture.py` (11), `tests/unit/test_monitoring_capture_policy.py` (16)
  and `tests/contract/test_monitoring_capture_vectors.py` (2): **29 passed**, each in its own container, with no
  network, against the installed SDK. The integration file includes the native `prepare` and delivery ports refusing
  study output.
- The version test needs the repository's `pyproject.toml` beside `tests/`. It passed once that was supplied from
  `3e70eca`.

**Vectors**
- `tests/contract/test_monitoring_capture_vectors.py` ran from `3e70eca`'s tests, docs and schemas against the
  installed SDK: **2 passed**. These cover the published schema matching the installed resource, and the recorded
  candidate vectors with 1.0 refusing 1.1.
- Every loaded `matter` module came from site-packages.
- Fixture SHA-256s:

  | Fixture | SHA-256 |
  |---|---|
  | `audience-a-positive` | `429453da…` |
  | `audience-b-quiet` | `082ab846…` |
  | `audience-b-unknown` | `1849bf82…` |
  | `manifest` | `fc530791…` |
  | `mixed-native-study-baseline` | `2c40bc0c…` |
  | `study-baseline-duplicate` | `7f668cd5…` |
  | `study-baseline-linked-correction` | `3e5368b8…` |

**Host mapping in StateCivics** (branch `ks1146-model-capture`): the real host projection and records, not wire
rehydration.
- **The policy:** the owner's thresholds, 0.8 positive and 0.2 negative, unknown between, for both objective and
  novelty. Precision is `PrecisionProfile().value`. The material paths are the source finding's signal and version,
  with an explicit `native_baseline` mapping to the host-rule material contract. It is installed through
  `CaptureAdmissionService.install_policy`.
- **The basis:** chosen per dispatch. `host_rule` is 1.0 and unchanged; `model_capture` is 1.1, with
  `source_reading: null` for now.
- **The capture row:** the in-app `AlertDelivery`. Its receipt is a digest-pinned row reference.
- **The history resolver:** reads that real row fresh and checks its owner before returning
  `ObservedMonitoringCapture`.

**Host outcomes** (recorded executor, no live calls), in `tests/services/test_monitoring_model_capture.py`:
- **Unqualified positives:** 0.9 is positive, unqualified, with a null assessment reference and a capture-admission
  reference. It captures once in-app as a digest.
- **Quiet and unknown never become irrelevance or captures:** 0.1 is quiet (objective negative); 0.5 is unknown
  (`semantic_unknown`). Neither captures.
- **Duplicates are suppressed:** the same development again (live origin) is quiet, `no_material_change`, against
  the study baseline read through the resolver. There is still exactly one capture.
- **Mixed baselines:** a native host-rule capture, then the study path, is quiet (the material is mapped). A study
  capture is refused as a 1.0 baseline (`baseline_basis_mismatch`), never downgraded, with no provider call.
- **Changed controls withhold:** a pause during the provider call refuses `host_cancelled` and captures nothing.
  The 1.0 path also covers an edit and a grant revocation during I/O.
- **Unknown outcomes:** a stale running attempt or a capture without its recorded baseline is refused as an unknown
  outcome until reconciled, never resent. This dispatcher logic is shared by both bases.
- **Not yet exercised:**
  - corrections, because StateCivics does not yet emit `correction_of` (KS-1125);
  - the shared source reading (`source_reading` stays null);
  - the indexed-candidate handoff (KS-1145).

**Final run, at StateCivics `bccca8b17`** (the KS-1146 branch tip):
- The model path: 4 passed (dev16).
- The 1.0 dispatch tests: 7 passed on dev16, and 7 passed on dev15 (`10a7d9a`).
- The PostgreSQL proof with Matter (dev16): 35 cases, exact identities.
- The full StateCivics statewide suite: unchanged from main's baseline by failure identity.

**Performance, still open**
- The standalone prototype (Matter's public SDK only, synthetic records, a recorded executor) spends **85.1%** of its
  time on dev16 in `jsonschema iter_errors`, across 28.7 million calls.
- It makes 63,671 `contracts._validate` calls, 50,629 `validate_record` calls and 67,234 `snapshot_digest` calls.
  `access.require_current` / `capture` account for 67%.
- On dev15 the same script spent 83% there.
- The script and its rerun command come with this receipt, so the figures can be checked rather than taken on trust.
- Under test load, one Matter command takes about 2 minutes. StateCivics now runs each Matter test in its own
  container to cope (KS-1147), but each evaluation still needs to be fast.

**Earlier the same day (superseded by the final run above)**
- The existing 1.0 path on the dev16 image: the dispatch and historical-replay tests passed 236 from StateCivics
  main's archive (`21a317dfd`). The gate then exited 78, because HEAD moved during the run; the counts are for the
  archived commit.
- The PostgreSQL proof with Matter passed 35 cases at `581cfe306`.
