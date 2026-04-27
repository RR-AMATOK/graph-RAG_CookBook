# graph-RAG_CookBook

> A framework for turning markdown corpora into LLM-queryable knowledge graphs, with daily updates, scraped upstream sources, and portable graph artifacts that any agent or app can consume.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/<owner>/graph-RAG_CookBook/actions/workflows/ci.yml/badge.svg)](https://github.com/<owner>/graph-RAG_CookBook/actions)
[![Artifacts](https://img.shields.io/badge/artifacts-live-brightgreen)](https://<owner>.github.io/graph-RAG_CookBook-artifacts/)

`graph-RAG_CookBook` ingests markdown documentation, extracts entities and typed relationships with an LLM, builds a knowledge graph, emits an Obsidian vault for human browsing, and **publishes a portable, versioned graph artifact** that downstream agents and apps fetch over HTTP. A daily scheduled job keeps the graph in sync with source changes and scraped upstream documentation.

## Why this and not [other tools]?

| | LightRAG | Microsoft GraphRAG | graphify | **graph-RAG_CookBook** |
|---|---|---|---|---|
| Incremental updates | ✅ Best-in-class | ⚠️ Append-only, no delete | ✅ SHA256 cache | ✅ git-diff + SHA256 |
| Obsidian vault output | ❌ | ❌ | ✅ Native | ✅ Native (Breadcrumbs + Bases) |
| Portable graph artifact for downstream consumers | ❌ Engine-coupled | ❌ Parquet-only | ❌ Local only | ✅ JSON + JSON-LD + GraphML, HTTP-served |
| Public consumer contract (JSON Schema, versioned) | ❌ | ❌ | ❌ | ✅ |
| Eval gates blocking bad publishes | ❌ | ❌ | ❌ | ✅ |
| Playwright upstream scraping | ❌ | ❌ | ❌ | ✅ |
| Filename hierarchy parsing (`parent__child__grandchild.md`) | ❌ | ❌ | ❌ | ✅ |
| Cost on 5k docs | $10–50 | $80–150 | varies | $10–50 (Sonnet) |
| Best for | Pure RAG | Global summarization | AI coding skill | **Cross-tool corpus → consumer agents** |

If your need is "build one graph, query it locally, never share it" — LightRAG is excellent. If it's "publish a graph that other repos and agent teams consume on a schedule" — that's the gap this fills.

## Architecture

Two repos, HTTP contract, no bidirectional coupling:

```
┌──────────────────────────────────────┐         ┌──────────────────────────────────────┐
│ graph-RAG_CookBook (this repo)        │         │ Your consumer repo (separate)         │
├──────────────────────────────────────┤         ├──────────────────────────────────────┤
│ Ingest → Extract → Build graph        │         │ Fetch graph(s) via HTTP / file://    │
│ Emit Obsidian vault                   │         │ Validate against published schema    │
│ Publish multi-format artifact         │ ──HTTP─▶│ Query with your agents / app          │
│ Schedule via cron OR GitHub Actions  │         │ Combine multiple graph sources       │
│ CI eval gates block bad publishes    │         │                                       │
└────────────────┬──────────────────────┘         └──────────────────────────────────────┘
                 │
                 ▼
        ┌────────────────────┐
        │ Storage backend    │
        │  • Local filesystem │
        │  • Dedicated GitHub │
        │    artifacts repo   │
        │    + Pages          │
        └────────────────────┘
```

See [docs/architecture.md](./docs/architecture.md) for the full data flow and component breakdown.

## Quickstart (5 minutes, ~$0.50 in API cost)

This walks you through building a graph from the bundled example corpus (Wikipedia articles about *The Big Bang Theory*) and querying it locally — no upstream sources of your own required.

### Prerequisites

- Python 3.11+ and [uv](https://github.com/astral-sh/uv) (or pip)
- Docker (for the local FalkorDB + Qdrant services)
- An [Anthropic API key](https://console.anthropic.com/) (for entity extraction)
- A [Voyage AI API key](https://www.voyageai.com/) (for embeddings) — or OpenAI as fallback

### Three commands

```bash
# 1. Clone, install, and start storage services
git clone https://github.com/<owner>/graph-RAG_CookBook
cd graph-RAG_CookBook
make bootstrap

# 2. Fetch the example corpus and build the graph
make example   # Downloads Big Bang Theory Wikipedia pages → builds graph → emits vault

# 3. Query interactively
make query     # Opens a REPL connected to the local graph + MCP server
```

After step 2 finishes, you'll have:

- A working knowledge graph in FalkorDB (~50 entities, ~150 edges from 10 articles)
- An Obsidian vault at `vault/` you can open in Obsidian
- A multi-format export at `publish/` (graph.json, graph.jsonld, graph.graphml)
- A run report at `runs/<timestamp>/report.json`

Cost: roughly $0.40–$0.60 with Claude Sonnet 4.7 + Voyage-3-large for the 10-document example.

### Sample query results

```bash
> Who lives across the hall from Sheldon and Leonard?
Penny (confidence: 0.95, source: Penny.md)

> What's the relationship between Sheldon and Amy?
Amy Farrah Fowler dating_partner_of Sheldon Cooper (confidence: 0.98)
... (eventually married_to, see Amy_Farrah_Fowler.md)

> Where does Howard work?
Howard Wolowitz works_at California Institute of Technology
  (confidence: 0.93, evidence: "an aerospace engineer at Caltech")
```

## Going further

Once the example works end-to-end, swap in your own corpus:

1. **Drop your markdown files into `corpus-a/` and/or `corpus-b/`**
   - `corpus-a/` for flat layout with `parent__child__grandchild.md` naming
   - `corpus-b/` for folder-based layout with embedded images
2. **Edit `config/sources.yaml`** to add upstream sites for Playwright scraping (optional)
3. **Edit `evals/golden_set.jsonl`** with 50+ hand-labeled documents from your corpus to enable publish gates
4. **Run `make ingest`** to build the graph
5. **Run `make publish`** to push to your dedicated GitHub artifacts repo

See [docs/getting-started.md](./docs/getting-started.md) for the full walkthrough.

## Publishing your graph

The framework supports two storage backends in v1:

- **`local`** — writes to a configured filesystem path. Use for private/local workflows.
- **`github`** — commits to a dedicated artifacts repo (`<owner>/<your-project>-artifacts`) and serves via GitHub Pages.

Configure in `config/publishing.yaml`:

```yaml
storage_backend: github
github:
  artifacts_repo: <your-username>/graph-RAG_CookBook-artifacts
  branch: main
  token_env: GITHUB_ARTIFACTS_TOKEN
  enable_pages: true
retention:
  keep_days: 30
  keep_last_n_always: 3
```

Then bootstrap the artifacts repo once:

```bash
export GITHUB_ARTIFACTS_TOKEN=ghp_xxx     # fine-grained PAT, scoped to the artifacts repo only
./scripts/setup-artifacts-repo.sh <your-username>/graph-RAG_CookBook-artifacts
./scripts/setup-pages.sh <your-username>/graph-RAG_CookBook-artifacts
```

After this, every `make publish` writes the graph to:

- `https://<your-username>.github.io/graph-RAG_CookBook-artifacts/graph.json` (latest)
- `https://raw.githubusercontent.com/<your-username>/graph-RAG_CookBook-artifacts/main/graph.json` (latest, raw)
- Git-tagged historical versions: `tree/graph-vYYYYMMDDHHMMSS/`

See [docs/publishing.md](./docs/publishing.md) for details, including S3 and SharePoint paths planned for v2.

## Consuming the published graph

Downstream consumer code lives in a *separate* repo. The framework ships a reference example at `examples/consumer/`:

```python
from examples.consumer.fetch_and_query import load_graph, neighbors_of

g = load_graph(
    graph_uri="https://<your-username>.github.io/graph-RAG_CookBook-artifacts/graph.json",
    schema_uri="https://<your-username>.github.io/graph-RAG_CookBook-artifacts/schemas/graph-v1.schema.json",
)
print(neighbors_of(g, "Sheldon Cooper"))
# ['Leonard Hofstadter', 'Amy Farrah Fowler', 'Penny', ...]
```

Multi-graph consumers (combining multiple framework instances) are supported — see `examples/consumer/multi_graph_merge.py`.

The full consumer contract is documented in [docs/consumer-guide.md](./docs/consumer-guide.md), including the JSON Schema, versioning rules, URL stability guarantees, and ETag-cache patterns.

## Daily updates

Two equivalent scheduling paths ship with the framework — pick whichever fits your environment:

### Local (cron / systemd)

```bash
# Add to crontab
0 3 * * * cd /path/to/graph-RAG_CookBook && make daily >> ~/graph-rag.log 2>&1
```

### GitHub Actions

`.github/workflows/daily-update.yml` runs the pipeline on GitHub-hosted runners daily at 03:00 UTC. Set repo secrets `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `GITHUB_ARTIFACTS_TOKEN` and the workflow picks them up.

Both paths produce identical artifacts. CI eval gates run on every update; if extraction quality regresses (configurable thresholds), the previous good artifact stays live and the run is marked failed.

## Built with Claude Code

This framework was designed and built with [Claude Code](https://www.anthropic.com/claude-code) and a multi-agent delegation system. The agent skills referenced by the build pipeline (`obsidian-vault-emission`, `knowledge-graph-construction`, `rag-evaluation`, `playwright-documentation-scraping`, `graph-artifact-publishing`) are installed globally into your Claude Code skills directory rather than bundled in this repo — see [CLAUDE.md](./CLAUDE.md) for details and [`.claude/state/DECISIONS.md`](./.claude/state/DECISIONS.md) DEC-012 for the rationale.

## Contributing

Contributions welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup, testing, and PR conventions. Please read [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) before participating.

For security issues, see [SECURITY.md](./SECURITY.md) — please don't open public issues for security reports.

## License

Apache License 2.0 — see [LICENSE](./LICENSE).

The reference example corpus (Wikipedia content) is licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) — see [NOTICE](./NOTICE) for attribution.

## Acknowledgements

`graph-RAG_CookBook` builds on prior art from [LightRAG](https://github.com/HKUDS/LightRAG), [Microsoft GraphRAG](https://github.com/microsoft/graphrag), [graphify](https://github.com/safishamsi/graphify), and [Graphiti](https://github.com/getzep/graphiti). Each influenced specific design decisions documented in [.claude/state/DECISIONS.md](./.claude/state/DECISIONS.md). The framework's existence is owed to the open-source work of those teams.
