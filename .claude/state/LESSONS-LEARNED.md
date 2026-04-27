# LESSONS-LEARNED.md — Cross-Project Knowledge Base

> A durable, additive repository of principle-level lessons. Not a diary; not a changelog.
> Every entry is a lesson that should transfer to the next project.

---

## Meta — Contribution Protocol

### What belongs here
- Principles, patterns, traps, and methodologies that transfer across projects.
- Framework / hardware gotchas that are not obvious from documentation.
- Debugging methodologies that proved their worth on a real bug.
- Sprint / process lessons that improved delivery cadence.
- Error loop resolutions — what was tried, what failed, what eventually worked.
- Negative results — approaches that were disproven with evidence.

### What does NOT belong here
- Project-specific file paths, function names, or commit hashes (use only in `(source: …)` footer).
- Results tables scoped to one benchmark harness.
- Architecture summaries (those belong in ARCHITECTURE.md).
- Open TODOs or active-sprint state (those belong in `.claude/state/`).

### How to append
- **New lesson in existing category** → add an `h3` under the matching `h2`.
- **New category** → add an `h2`, and log it in the Contribution Log below.
- **Superseding a prior lesson** → do not delete; append `Superseded YYYY-MM-DD by: …` and add the new lesson below.
- Each `h3` entry must have: one-line principle as the title, 2-3 sentences of context, optional code/formula, and a `(source: …)` footer.

---

<!-- Add categories and lessons below as the project progresses -->

---

## Contribution Log

| Date | Change | Contributor |
|------|--------|-------------|
| | Initial creation | |
