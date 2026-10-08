# Synthetic contract walkthroughs

Run `python -m matter demo all` or select `oil`, `civic`, or `diat`. Each JSON fixture declares its expected outputs separately from the implementation. `python -m matter validate` compares the actual result to that declaration.

These are executable examples of a small subset of the future contract. They are intentionally based on synthetic, already-classified host inputs. The `host_qualified` flag is fixture input, not proof or a model confidence statistic. A real adapter must establish and validate qualification and authorization; untrusted observations cannot promote themselves into the control path.

| Example | Behaviors illustrated |
|---|---|
| [Oil](oil.json) | Same-event redelivery, correlated reports, quiet routine work, useful changes, context invalidation, unmatched/unqualified recovery, matching recovery, historical evidence, recurrence, and immediate stop forwarding |
| [Civic](civic.json) | Repeated reporting, a late-received official disposition, cancellation of pending advice, later reopening, and preservation of an earlier event's history |
| [DIAT](diat.json) | Anonymous evidence-review matter, unqualified semantic hints staying quiet, a qualified research hint, and reviewed resolution without identity mutation |

The implementation in `src/matter/demo.py` is an in-memory, single-process walkthrough. Its identities are deterministic within synthetic scope, occurrence counts do not establish independent corroboration, and delivery means a recorded simulated emission only. It has no durable transport, concurrent workers, semantic evaluator, identity resolver, or production authority model. Full implementation and qualification remain in the backlog.

The example `classification` and `condition_id` fields describe already-prepared inputs. MAT-002 supplies the general observation, evidence, rule, and assessment structural schemas; `walkthrough.schema.json` is not their replacement. Runtime operation semantics remain in their individual tickets.

## Installed API examples

These standalone Python examples exercise implemented services with synthetic
inputs and temporary local storage. They also run from an installed wheel
outside the checkout, without loading test fixtures:

| Example | Behaviors verified |
|---|---|
| [Observation intake](observation_intake.py) | Exact payloads, duplicate delivery, explicit corrections, evidence history, and restart |
| [Matter identity](matter_identity.py) | Persistent exact subject keys, new-run continuity, revisioned metadata, scope isolation, exact retries, and backup/restore |

Run `python examples/observation_intake.py` and `python examples/matter_identity.py`.
Both use synthetic host authority references. They do not establish domain
authority, semantic identity, or a qualified assessment engine.
