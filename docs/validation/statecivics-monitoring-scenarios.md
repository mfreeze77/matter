# StateCivics monitoring scenario preparation

Date: October 27, 2026. Base Matter commit: `acc7b0cad2`.
Scope: synthetic scenario authoring, integration intent and existing replay
source/configuration discovery. No production runtime implementation changed.

## Executed checks

- `.venv/bin/python -m matter render` regenerated MAT-049's page from canonical
  JSON. Its status remains `planned`, completion `not_run`; no dependency changed.
- `.venv/bin/python -m matter render --check`: passed, no stale generated files.
- `.venv/bin/python -m matter validate`: passed; 80 tickets, 104 requirements,
  98 schemas and the three existing walkthroughs. That walkthrough count does
  not include the new planning scenario.
- `PYTHONPATH=tests .venv/bin/python -m unittest test_repository test_hardening -v`:
  **39 tests passed**. These verify repository/scaffold behavior, not the proposed
  monitoring outcomes. The full runtime suite was not rerun for documentation
  and synthetic planning data changes.
- An in-memory standard-library authoring check parsed the new JSON, checked
  three client/four context references, twelve unique ordered checkpoints,
  48 declared attention treatments, source correction/reprint references,
  occurrence-before-availability ordering and representative quiet/context-change
  expectations. Passed. No Matter executor evaluated those expectations.
- `git diff --cached --check`: passed on the initial five-file change. Final
  staged whitespace, generated-file and repository validation checks also passed
  after adding this receipt and the replay discovery results.

The default shell Python could not import `matter`. The existing `.venv` has the
checkout package and `jsonschema`; it ran the checks above without installing
dependencies or creating another environment.

## Existing replay discovery

StateCivics HEAD during inspection: `d28663cc0`. The inspected replay manifest,
runtime, API router, config and frontend console are unchanged from `1f7011fd8`.
The API selects only `hb2560` and `hearing829`; responses name model mode
`unavailable`. Existing KS-698/704/705/706 owners and implementation are reused
in the handoff; no sibling repository was edited.

Docker inventory confirmed running `ks-rehearsal` services and a local edge at
`127.0.0.1:8080`. A bounded GET of `/dashboard/admin/replay` timed out at five
seconds. `printenv` for only `HISTORICAL_REPLAY_ENABLED`,
`HISTORICAL_REPLAY_SCENARIO_ROOT` and `HISTORICAL_REPLAY_INSTANCE_FILE` returned
none from the backend. This is not a complete settings/health audit and makes no
claim that replay is enabled, disabled, broken or ready. No credentials, broader
process environment or environment file were displayed; no configuration,
service, replay run or database was changed.

## Evidence limits

The synthetic expected treatments are proposals authored for implementation,
not independent labels, executed assertions or paid-provider responses.
Integrated replay, newly qualified JEV judgments, the optional LLM writer,
receiving acceptance and external notification delivery remain **not_run**.
Independent civic labels and actual sink receipts will be needed later.

The separate installed walkthrough-schema lookup failure remains unresolved;
these checkout checks do not repair or requalify the installed walkthrough.

## Independent review

The subscription-backed OpenCodeReview bridge completed its default **two
rounds**: two JSON files reviewed, zero findings and zero warnings, 72.3 seconds.
The files were the new scenario pack and canonical MAT-049 record. Its existing
rules excluded the four Markdown files (including the generated ticket and this
receipt). Documentation self-review and link validation remain separate from
that independent JSON review. No runtime code changed.

Command: `INTENT_OIL_PROMPT_AUTHOR=agent python3 ../ocr-bridge/run_review.py
-B tickets/MAT-049.md -f json -o /tmp/matter-monitoring-review-claude.json`.
Session: `/Users/mfrieson/.ocr-bridge/sessions/20261027-192926-4da2dc`.

The earlier Codex-provider bridge attempt reviewed zero files because its MCP
environment override failed CLI configuration parsing (`expected a map`). Its
zero-finding summary is not review evidence. Switching to the bridge's default
Claude subscription provider produced the completed result above; no bridge or
CLI configuration was edited and no metered review API was used.
