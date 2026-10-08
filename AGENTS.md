# Working in Matter

Follow the user's current task and scope. Read README.md, the relevant governing contract, and the selected canonical ticket before implementation.

- Keep the common core independent of Oil, civic vocabulary, JEV, and speaker identity. Put specialized meaning in explicit profiles and adapters.
- Preserve evidence origin, scope, availability, uncertainty, and derivation. A model judgment does not acquire source authority or permission to act.
- Direct user instructions, corrections, and stop signals use the host control path. Do not buffer them as ordinary evidence awaiting importance.
- Treat the root starter notes as design history. Governing contracts and recorded decisions resolve their older shorthand; user instructions take precedence.
- Scope tickets to their declared owner. This repository's roadmap does not by itself authorize changes or deployment in Oil, StateCivics, the crawler, or DIAT.
- Keep real audio, transcripts, embeddings, identity labels, credentials, and evaluation corpora out of this repository. Use synthetic examples and external artifact references.
- Inspect the existing owners and reuse maps before introducing replacement clients, retrieval, storage, or orchestration infrastructure.
- Edit canonical ticket JSON. Regenerate its Markdown/index, run validation, and record actual evidence before marking work done.
- Use behavioral tests that can detect incorrect outcomes. Keep source review, synthetic checks, provider evaluation, and live usefulness separate in reports.
- Preserve unrelated concurrent changes. Commit coherent progress on a task branch; provide a reviewable PR and accurate limitations.

## Local checks

```bash
python -m matter render --check
python -m matter validate
python -m unittest discover -s tests -v
```

Full implementation targets remain in the backlog. Do not describe the scaffold's synthetic walkthrough as a qualified runtime or identity system.
