# Contributing

Start with a dependency-ready ticket in [the backlog](tickets/INDEX.md). The core contracts define required behavior; each ticket defines an implementation-sized deliverable and the evidence needed to establish it.

## Change workflow

1. Inspect the named owner and reuse sources. Record the actual commit and callable boundary before copying or adapting a component.
2. Keep changes within the authorized repository and task. Domain tickets identify future owners explicitly.
3. Implement the selected behavior and meaningful negative cases. Preserve the evidence/authority distinction and direct host controls.
4. Record commands, inputs, results, and limitations. A reference to a test file alone is not proof that it ran.
5. Update the canonical ticket. A `done` ticket needs `completion.state: passed`, nonempty evidence, and completed dependencies.
6. Regenerate and validate projections, then commit and push coherent progress for review.

## Ticket changes

The [ticket schema](schemas/ticket.schema.json) and [ticket guide](tickets/README.md) define required fields. Add a requirement to `docs/requirements.json` when scope expands. A requirement must have ticket coverage; a ticket may cover several related requirements. Separate implementation from empirical qualification when the latter needs different inputs or another runtime.

Priority P0 means foundational or a prerequisite for correct behavior, P1 means the next integration/research wave, and P2 means later extension or operational improvement. Phase is a planning grouping; the dependency graph controls execution order.

## Tests and reproducibility

Install with the checked-in test constraints, then run:

```bash
python -m matter render --check
python -m matter validate
python -m unittest discover -s tests -v
```

Synthetic fixtures must state their expected results explicitly. Do not generate expected outcomes by running the implementation under test. Model qualification needs pinned questions, preparation, models, data partitions, labels, and admission policies; a passing unit test cannot substitute for that evidence.

Keep local or remote live-provider execution opt-in. The scaffold makes no provider calls and requires no secrets. A third-party reuse proposal needs a source and license review before code is incorporated.
