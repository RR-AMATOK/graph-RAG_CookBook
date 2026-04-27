# Consumer Guide

This guide is for downstream repos that **consume** a graph artifact published by graph-RAG_CookBook. If you're building an agent team, a chatbot, an analytics tool, or any other system that needs to read the graph, start here.

## TL;DR

1. Pin to a major schema version (e.g., `graph-v1.schema.json`).
2. Fetch `graph.json` from the publisher's URL.
3. Validate against the schema **before use** (FR-13.1) — never skip.
4. Walk the graph with stdlib + `jsonschema`, or load into `networkx` for richer queries.
5. Use ETag / `Last-Modified` caching on repeat fetches.

A copy-pasteable starting point lives at [`examples/consumer/fetch_and_query.py`](../examples/consumer/fetch_and_query.py).

## The contract

graph-RAG_CookBook commits to the following stability guarantees (SPEC §13):

| Guarantee | What it means |
|---|---|
| **Schema major version** | Breaking changes bump major (`graph-v1` → `graph-v2`) and publish to a new URL. Pinned consumers fail closed on major bump. |
| **URL stability (FR-13.6)** | `graph.json` (no version suffix) always points to the latest *good* version. Historical versions live at tag-qualified URLs. |
| **Eval gate (FR-12)** | A failed publish leaves the previous good artifact live. You will never receive a regression-tainted artifact at the unqualified URL. |
| **Read-only (NG9)** | The artifact is immutable for the lifetime of a fetch. No write path exists. |
| **Provenance** | Every edge carries `confidence` (0..1), `provenance_tag` (EXTRACTED / INFERRED / AMBIGUOUS), and `source_doc_ids[]`. |

## Discovery

A future `index.json` (FR-13.2) at the artifacts repo root will list available graphs:

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-04-26T00:00:00Z",
  "graphs": [
    {
      "name": "leanix-training",
      "latest_url": "https://<owner>.github.io/<artifacts-repo>/graph.json",
      "latest_version": "graph-v20260426-030000",
      "schema_url": "https://<owner>.github.io/<artifacts-repo>/schemas/graph-v1.schema.json",
      "formats": {
        "json":    "https://<owner>.github.io/<artifacts-repo>/graph.json",
        "jsonld":  "https://<owner>.github.io/<artifacts-repo>/graph.jsonld",
        "graphml": "https://<owner>.github.io/<artifacts-repo>/graph.graphml"
      }
    }
  ]
}
```

This lets a single consumer aggregate multiple graphs from multiple framework instances.

## Format choice

| Format | When to use |
|---|---|
| `graph.json` | Default. Compact, NetworkX-serializable, schema-validated. Ideal for Python consumers. |
| `graph.jsonld` | When you need RDF/OWL semantics, semantic-web tooling, or want to merge with other LD sources. |
| `graph.graphml` | When you want to visualize in Gephi/yEd or use existing GraphML pipelines. |

All three formats represent the same graph; pick the one your tools speak natively.

## Multi-graph aggregation (FR-13.5)

### Pattern A: separate queries
Each graph answers some subset of questions. Your agent picks the right graph per query and the LLM fuses results. **Recommended** when graphs cover non-overlapping domains.

### Pattern B: merged in-memory graph
Load each `graph.json`, union nodes (dedup by `(name, type)`) and edges into a single in-memory graph (NetworkX `MultiDiGraph` works well). **Recommended** when graphs cover overlapping domains and multi-hop queries need a unified view.

A reference `multi_graph_merge.py` ships with the publishing pipeline (Sprint 3+).

## Caching

The publisher serves artifacts via GitHub Pages with standard HTTP caching headers. Use:

- **ETag** — most efficient; the server replies `304 Not Modified` if your cached copy is current.
- **`Last-Modified` / `If-Modified-Since`** — fallback when ETag isn't honored.

Caching is essential at scale: a 10-MB graph fetched 1k times an hour = 10 GB/hour of pointless egress.

## Validation strategy

```python
import json
import jsonschema

with open("graph-v1.schema.json") as f:
    schema = json.load(f)
with open("graph.json") as f:
    graph = json.load(f)

jsonschema.validate(graph, schema)  # raises jsonschema.ValidationError on bad input
```

For draft-2020-12 features (used in this schema), pass the appropriate validator class explicitly:

```python
from jsonschema import Draft202012Validator
Draft202012Validator(schema).validate(graph)
```

## Working with provenance tags

Every relationship edge carries a `provenance_tag`:

- `EXTRACTED` — direct quote support in the source. Trust at face value.
- `INFERRED` — reasonable LLM inference, confidence ≥ 0.7. Reasonable to use; flag in citations.
- `AMBIGUOUS` — confidence < 0.7. **Do not surface to users without manual review.** Useful for analytics and follow-up data quality work.

Filter by tag in your retrieval logic:

```python
high_confidence = [e for e in graph["edges"]
                   if e["properties"].get("confidence", 0) >= 0.8
                   and e["properties"].get("provenance_tag") != "AMBIGUOUS"]
```

## Error handling

| Failure mode | What you should do |
|---|---|
| Schema validation fails | Fail closed. Log the validation error. Do not fall back to "best effort" — a malformed artifact is a publisher bug. |
| HTTP 5xx from artifacts URL | Retry with exponential backoff. Treat repeated failure as artifact unavailable. |
| Major schema bump | Fail closed. Your code is pinned to v1; v2 may have semantic changes you haven't reviewed. |
| Stale artifact (no `If-Modified-Since` benefit) | Acceptable for read-only consumers. Refresh on a cadence that fits your domain. |

## Related documents

- [docs/architecture.md](architecture.md) — what the publisher does and what its boundaries are.
- [examples/consumer/README.md](../examples/consumer/README.md) — copy-paste consumer starter.
- [schemas/graph-v1.schema.json](../schemas/graph-v1.schema.json) — the contract.
- [SPEC.md §13](../SPEC.md) — formal consumer contract.
