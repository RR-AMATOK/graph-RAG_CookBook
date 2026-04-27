# Evaluation Harness

This directory holds the evaluation infrastructure that gates every publish (SPEC §12, DEC-007). The pipeline is:

```
┌──────────────┐   ┌────────────┐   ┌─────────────┐   ┌─────────────┐
│  golden_set  │──▶│  harness   │──▶│   gates     │──▶│  publish?   │
│   .jsonl     │   │  (runner)  │   │ (thresholds)│   │  yes / no   │
└──────────────┘   └────────────┘   └─────────────┘   └─────────────┘
                          │
                          ▼
                  ┌──────────────┐
                  │ history.jsonl│  (append-only metric trend)
                  └──────────────┘
```

## Files

| File | Purpose |
|---|---|
| `golden_set.jsonl` | Hand-labeled ground-truth entries. **You author this.** Production target ≥ 50 entries (DEC-011). |
| `thresholds.yaml` | Publish-gate thresholds. Edit to tune per project. |
| `history.jsonl` | Append-only run-by-run metrics. Never edit by hand. |
| `harness/` | Python package implementing the runner, metrics, and gate logic. |

## Golden entry schema (Sprint 1 v0)

Each line in `golden_set.jsonl` is a JSON object with this shape:

```json
{
  "doc_id": "bbt_pilot_episode",
  "canonical_path": "examples/reference-corpus/bigbangtheory/episodes/pilot.md",
  "expected_entities": [
    {"name": "Sheldon Cooper", "type": "Character", "aliases": ["Dr. Sheldon Cooper"]},
    {"name": "Caltech",        "type": "Organization"}
  ],
  "expected_relationships": [
    {"source": "Sheldon Cooper", "target": "Caltech",      "predicate": "WORKS_AT"},
    {"source": "Sheldon Cooper", "target": "Leonard Hofstadter", "predicate": "ROOMMATES_WITH"}
  ],
  "expected_top_doc_for_query": {
    "What is Sheldon's profession?": "bbt_sheldon_character"
  },
  "notes": "Pilot — establishes core characters."
}
```

**Authoring guidelines:**

- **Entity names:** use the most canonical surface form found in the document. Variants go in `aliases`.
- **Entity types:** stick to a small, consistent vocabulary (e.g., `Character`, `Organization`, `Location`, `Concept`). Don't invent new types per doc.
- **Relationships:** use UPPER_SNAKE_CASE predicates. Be conservative — only mark a relationship as expected if it's clearly stated in the doc.
- **Coverage:** aim for breadth (many docs, ~3–5 entities each) over depth (one doc with 30 entities). The harness measures recall across the corpus.
- **Avoid ambiguous cases:** if a fact is borderline INFERRED vs AMBIGUOUS, leave it out of the golden set rather than guess. The golden set should reward confident extractions.

## Warmup mode (DEC-011)

Until `golden_set.jsonl` reaches `warmup.min_golden_entries` (default 50), the harness:

- Computes and logs all metrics
- Appends to `history.jsonl`
- **Does NOT block publish** (warmup gate bypass)
- Marks each `history.jsonl` entry with `"warmup": true`

This lets us exercise the full pipeline end-to-end during Sprint 1+2 with a partial golden set, without false-positive publish blocks.

## Running

```bash
make eval   # invokes evals.harness.runner
```

In Sprint 1, the runner exercises the gate logic against synthetic inputs (no real extraction outputs yet). Sprint 2+ wires in real extractor output.
