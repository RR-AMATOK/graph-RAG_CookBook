# Reference Consumer

This directory is the **starting point** for any downstream repo that wants to consume a graph artifact published by graph-RAG_CookBook (SPEC §6.7, FR-13.4). Copy these files into your consumer project and adapt.

## What lives here

| File | Purpose |
|---|---|
| `fetch_and_query.py` | Stdlib-only fetcher + JSON-Schema validator + minimal entity query |
| `fixture-graph.json` | Hand-crafted artifact for offline testing (mirrors the BBT reference corpus) |
| `README.md` | This file |

## Quick start (offline, against the fixture)

```bash
# from project root
python examples/consumer/fetch_and_query.py \
    --graph examples/consumer/fixture-graph.json \
    --schema schemas/graph-v1.schema.json \
    --query "Sheldon Cooper"
```

Expected output:

```
Loaded graph schema_version=1.0
  generated_at=2026-04-26T00:00:00Z  docs=2  entities=3  edges=4

Entity: Sheldon Cooper (id=ent_sheldon_cooper, subtype=Character)
  Theoretical physicist at Caltech, roommate of Leonard Hofstadter.

Outgoing relationships:
  --[WORKS_AT]--> Caltech  (confidence=0.95, provenance=EXTRACTED)
  --[ROOMMATES_WITH]--> Leonard Hofstadter  (confidence=0.92, provenance=EXTRACTED)
```

## Quick start (online, against a published artifact)

When Sprint 3 publishes real artifacts:

```bash
python examples/consumer/fetch_and_query.py \
    --graph https://<owner>.github.io/<artifacts-repo>/graph.json \
    --schema https://<owner>.github.io/<artifacts-repo>/schemas/graph-v1.schema.json \
    --query "Business Capability"
```

## Consumer contract (what you can rely on)

1. **Schema stability (FR-13.3)** — `schema_version` in the artifact follows `MAJOR.MINOR`. Breaking changes bump MAJOR and publish to a new URL (e.g., `graph-v2.schema.json`). Pin to a major version.
2. **URL stability (FR-13.6)** — the unqualified URLs (`graph.json`, `graph.jsonld`, `graph.graphml`) always point to the latest *good* version. Historical versions are accessible via tag-qualified URLs.
3. **Read-only (NG9)** — consumers cannot mutate the graph. Treat `graph.json` as immutable for the lifetime of a fetch.
4. **Validate before use (FR-13.1)** — always validate against the published schema. Reject artifacts that fail validation.

## Multi-graph aggregation (FR-13.5)

Two patterns are documented for consuming multiple graphs simultaneously:

### Pattern A: separate queries
Ask each graph independently; the consumer LLM fuses results. Simpler; fits agentic retrieval workflows where each graph answers different question types.

### Pattern B: merged in-memory graph
Load multiple `graph.json` files; deduplicate entities by `(name, type)`; union edges. Fits topological/multi-hop queries that need a single coherent graph.

A reference `multi_graph_merge.py` lands in Sprint 3 alongside the published artifact pipeline.

## Schema validation in your consumer

The Sprint 1 reference uses `jsonschema` (stdlib-friendly, well-supported). Any draft-2020-12 validator works. **Do not** skip validation in production: a malformed artifact (e.g., from a manual edit) can crash downstream agents in subtle ways.

## Recommended runtime dependencies (consumer-side)

- **jsonschema** — schema validation (required)
- **networkx** — graph algorithms and traversal (recommended for non-trivial queries)
- **httpx** — richer HTTP than stdlib (recommended for production fetchers)

These are explicit consumer-side dependencies; the framework itself does not impose them.
