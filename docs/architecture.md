# Architecture

graph-RAG_CookBook is the **upstream graph builder + publisher** in a deliberately decoupled two-repo design (DEC-004). This document describes the boundary, the dataflow, and the contract the publisher upholds for downstream consumers.

## Two-repo split

```
┌────────────────────────────────────────────┐         ┌────────────────────────────────────────────┐
│ THIS REPO — graph-RAG_CookBook              │         │ FUTURE CONSUMER REPO (separate, NG7)        │
│                                             │         │                                             │
│ • Ingest markdown (corpus-a, corpus-b)      │         │ • Reads graph(s) via HTTP or local path    │
│ • Canonicalize + chunk + extract            │         │ • Multiple graph sources supported          │
│ • Build graph (FalkorDB) + vectors (Qdrant) │         │ • Agents consume; never write back          │
│ • Emit Obsidian vault (human UI)            │         │ • Out of scope for this repo                │
│ • Publish portable artifact (json/jsonld/   │         │                                             │
│   graphml + meta)                           │         │                                             │
│ • CI eval gate blocks bad publishes         │         │                                             │
└─────────────────────┬───────────────────────┘         └─────────────────────┬───────────────────────┘
                      │ publishes                                              │ fetches
                      ▼                                                        ▼
            ┌────────────────────────┐                              ┌──────────────────┐
            │ Storage backend        │◄──────────  HTTP GET ────────│ Consumer config  │
            │ • Local FS (v1)        │                              │  sources:        │
            │ • GitHub artifacts repo│                              │   - file:///...  │
            │   + Pages (v1)         │                              │   - https://...  │
            │ • S3, SharePoint (v2+) │                              └──────────────────┘
            └────────────────────────┘
```

## What lives in this repo

- The framework code (canonicalizer → chunker → extractor → graph/vector → emitter → exporter → publisher).
- The eval harness with publish-blocking gates.
- The MCP server (local-only, for Claude Code direct use against the in-progress graph).
- Playwright scrapers for dynamic source ingestion.
- Schedulers (Make targets + GitHub Actions; Dagster deferred to v2 per DEC-009).

## What lives in the future consumer repo

- Agent teams, tool definitions, retrieval strategy, multi-hop reasoning.
- User-facing chat, web UIs, IDE integrations.
- Cross-graph reasoning that combines artifacts from multiple framework instances.

## Dataflow

```
┌───────────┐   ┌──────────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐
│ corpus-a/ │──▶│ canonicalizer│──▶│ chunker  │──▶│ extractor│──▶│ graph builder│
│ corpus-b/ │   │              │   │          │   │  (LLM)   │   │  (FalkorDB)  │
│ scrapers  │   │ frontmatter  │   │ header-  │   │ JSON-mode│   │ entity merge │
└───────────┘   │ schema check │   │  aware   │   │ provenance│   │ + edges      │
                └──────────────┘   └──────────┘   └──────────┘   └──────┬───────┘
                                                          │              │
                                                          ▼              ▼
                                                   ┌──────────┐    ┌──────────┐
                                                   │ vector   │    │ emitter  │
                                                   │ (Qdrant) │    │ (Obsidian│
                                                   └──────────┘    │  vault)  │
                                                                   └──────────┘
                                                                          │
                                                                          ▼
                                                                   ┌──────────────┐
                                                                   │ exporter     │
                                                                   │ json/jsonld/ │
                                                                   │ graphml      │
                                                                   └──────┬───────┘
                                                                          │
                                                                          ▼
                                                                   ┌──────────────┐
                                                                   │ eval harness │
                                                                   │  pass? ──────┼──▶ block / publish
                                                                   └──────────────┘
```

Each stage caches by content hash (SPEC §6.3): `rm -rf cache/` is always safe and forces a full rebuild.

## Component map (SPEC §6.2)

| Component (path)                                    | Responsibility                                            |
|-----------------------------------------------------|-----------------------------------------------------------|
| `src/knowledge_graph/canonicalizer/`                | Walk corpora, parse `__` hierarchy, normalize frontmatter |
| `src/knowledge_graph/chunker/`                      | Header-aware chunking, content-hash cache                 |
| `src/knowledge_graph/extractor/`                    | Claude entity/relationship extraction with retries        |
| `src/knowledge_graph/graph/`                        | FalkorDB client (DEC-002), entity resolution, upserts     |
| `src/knowledge_graph/vector/`                       | Qdrant client, deterministic chunk IDs                    |
| `src/knowledge_graph/emitter/`                      | Obsidian vault writer (frontmatter, wikilinks, entities)  |
| `src/knowledge_graph/exporter/`                     | Multi-format export (json, jsonld, graphml)               |
| `src/knowledge_graph/publisher/` + `adapters/`      | Pluggable storage backends + retention pruning            |
| `src/knowledge_graph/mcp_server/`                   | Local MCP server with 5 tools                             |
| `src/knowledge_graph/staleness/`                    | Upstream-doc change detection                             |
| `src/knowledge_graph/scrapers/`                     | Playwright scrapers + HTML→MD                             |
| `src/knowledge_graph/cli.py`                        | `kg` CLI entry point                                      |
| `src/knowledge_graph/config.py`                     | Pydantic-settings + YAML config                           |

## The publish gate

Every pipeline run executes the eval harness *after* graph merge and *before* publish (SPEC §12.3). If any threshold in `evals/thresholds.yaml` is violated:

- The run is marked `FAILED (eval gate)` in `runs/<timestamp>/report.json`
- The publish step is **skipped**
- The previously published artifact **remains live and unchanged** (URL stability, FR-13.6)
- The CI workflow goes red

The gate has three modes:

1. **Warmup** (DEC-011) — golden set has < 50 entries; metrics logged, publish *not* gated. Sprint 1+2 default.
2. **Active** — full gating per DEC-007 thresholds (absolute floors + regression deltas).
3. **Override** — `make publish FORCE=1` bypasses gates with loud warnings and an audit entry in `graph.meta.json` (`forced_publish: true`).

## Storage adapter pattern (SPEC §6.4)

Publishing is abstracted behind a `StorageAdapter` protocol. v1 ships:

- `LocalFileStorage` — writes to `./publish/`. For local development and air-gapped deployments.
- `GitHubArtifactsStorage` — pushes to a dedicated artifacts repo (DEC-005) with optional Pages enablement (DEC-006).

v2+ stubs (interface defined, implementation deferred): `S3Storage`, `SharePointStorage`.

## Cost guardrails (G9, DEC-007)

- Steady-state ceiling: **$50/month** (assumes < 5% daily corpus churn).
- One-off initial ingestion ceiling: **$150** for a 5k-doc corpus.
- Cost-creep guard: per-doc cost > $0.05 blocks publish.

Cost is tracked in every `graph.meta.json` and `evals/history.jsonl` row.

## Out of scope (SPEC §2.2)

Multi-user editing (NG1) · real-time sync (NG2) · web UI (NG3) · cloud-only deployment (NG4) · model training/fine-tuning (NG5) · non-markdown sources in v1 (NG6) · agent logic (NG7) · non-GH/non-local storage in v1 (NG8) · bidirectional consumer→framework sync (NG9).

## Related documents

- [SPEC.md](../SPEC.md) — the source of truth for everything in this document.
- [docs/consumer-guide.md](consumer-guide.md) — downstream-facing consumer contract.
- [.claude/state/DECISIONS.md](../.claude/state/DECISIONS.md) — DEC-001..012.
- [examples/consumer/](../examples/consumer/) — reference consumer implementation.
