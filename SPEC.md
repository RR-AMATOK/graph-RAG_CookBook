# Graph-RAG Knowledge System — Project Specification

**Status:** Draft v1.1
**Owner:** @product-owner
**Last updated:** 2026-04-24
**Related:** `.claude/state/MEMORY.md`, `.claude/state/DECISIONS.md`, `.claude/state/TODOS.md`

### Changelog

- **v1.1 (2026-04-24)** — Repo separation: this framework is now a standalone, reusable, agent-agnostic tool. Added §6.4 (storage adapters), §6.5 (multi-format graph export), §6.6 (CI eval gates with publish blocking), §6.7 (consumer contract), §7.5 (graph export schemas), and §10bis (local + GitHub Actions scheduling). Agent consumer (formerly part of scope) moved to a separate future repository. Previous "14-agent team" references reframed as "consuming agents of the published artifact".
- **v1.0 (2026-04-20)** — Initial spec.

---

## 1. Executive Summary

Build a self-hosted, reusable **framework** for constructing an LLM-queryable knowledge graph over a corpus of markdown training and documentation files (1k–10k scale). The framework unifies source repositories with differing structures into a single canonical form, extracts entities and relationships with an LLM, stores them in a graph database, emits an Obsidian vault for human browsing, and **publishes a versioned, portable graph artifact** (JSON-LD + GraphML + JSON) to a configurable storage backend. A Playwright-based extraction layer supplements static corpora with content scraped from external documentation sources.

This framework **does not contain agent logic**. Consumers — typically agent teams or other knowledge systems living in separate repositories — fetch the published graph artifact over HTTP and use it to answer questions. The framework's obligation is a stable, versioned, documented graph contract; consumers handle retrieval strategy, agent orchestration, and user interaction.

**Primary consumers:**
- Agent teams in downstream repositories (via published graph artifacts — HTTP fetch from GitHub Pages, raw GitHub URLs, or local file paths)
- Claude Code (via optional built-in MCP server running locally against the graph)
- Human readers (via the emitted Obsidian vault)

**Secondary consumers:** Ad-hoc Cypher/graph queries for analytics; any future consumer implementing the documented graph schema.

**Not consumers:** End users via a web app (out of scope for v1).

### 1.1 Two-repo architecture

```
┌──────────────────────────────────────┐         ┌──────────────────────────────────────┐
│ Repo 1: THIS FRAMEWORK               │         │ Repo 2: CONSUMER (future, separate)  │
│ (graph-rag-framework)                 │         │ (e.g., knowledge-agents)              │
├──────────────────────────────────────┤         ├──────────────────────────────────────┤
│ • Ingest, extract, build graph        │         │ • Reads graph(s) via HTTP or local   │
│ • Emit vault + multi-format exports  │         │ • Supports multiple graph sources    │
│ • Publish to local FS or dedicated   │         │ • Agents consume, never write back   │
│   artifacts repo (GitHub)             │         │ • Not built in this project           │
│ • Schedule via cron or GH Actions    │         │                                       │
│ • CI eval gates block bad publishes  │         │                                       │
└────────────────┬──────────────────────┘         └───────────────┬──────────────────────┘
                 │ publishes                                        │ fetches
                 ▼                                                  ▼
        ┌────────────────────┐                            ┌────────────────────┐
        │ Storage backend    │◄─────── HTTP GET ──────────│ Consumer config    │
        │                    │                            │                    │
        │ v1: local FS       │                            │ sources:           │
        │ v1: GitHub repo    │                            │  - file:///...     │
        │     (dedicated)    │                            │  - https://raw...  │
        │ v1: GitHub Pages   │                            │  - https://*.github.io/... │
        │                    │                            │                    │
        │ v2+: S3, SharePoint│                            │                    │
        └────────────────────┘                            └────────────────────┘
```

**What lives in this repo:** the framework, scheduler, eval harness, publishing logic, Playwright scrapers, vault emitter, MCP server (for local use).

**What lives in a future separate repo:** agent teams, retrieval strategy, user-facing workflows, cross-graph reasoning.

---

## 2. Goals & Non-Goals

### 2.1 Goals

- **G1** — Unify source markdown repositories (flat with `__`-delimited hierarchy + folder-based with embedded images) into one canonical corpus.
- **G2** — Extract entities and typed relationships from markdown content using an LLM, with provenance tags (`EXTRACTED` / `INFERRED` / `AMBIGUOUS`).
- **G3** — Store the graph in a queryable graph database and embeddings in a vector database; keep both in sync with source-file changes.
- **G4** — Emit an Obsidian vault with frontmatter metadata, wikilinks, entity pages, and Breadcrumbs-compatible hierarchy fields.
- **G5** — Expose the graph to Claude Code via an MCP server with `query_graph`, `get_node`, `get_neighbors`, `shortest_path`, and `find_stale` tools.
- **G6** — Detect staleness against upstream official documentation using HTTP conditional requests, sitemap polling, and (optionally) LLM-as-judge material-change detection.
- **G7** — Run a scheduled job that incrementally updates the graph from changed source files only (no full reindex). Support local scheduling (cron/systemd) and cloud scheduling (GitHub Actions).
- **G8** — Scrape external documentation sources via Playwright, convert to canonical markdown, feed into the same pipeline, and auto-categorize by URL/content.
- **G9** — Keep total monthly LLM cost under $50 at steady state (initial ingestion may be up to $150 one-off).
- **G10** — **Publish the graph as a portable, versioned artifact** (JSON-LD + GraphML + `graph.json`) to a configurable storage backend (local filesystem or dedicated GitHub artifacts repo with Pages enabled), so that external consumers can fetch it via HTTP or local path.
- **G11** — **Block publish on quality regressions.** Every run executes an eval harness against a golden set; if configured thresholds are violated, the previous good artifact remains live and the run is marked failed.
- **G12** — **Document the consumer contract.** Publish a stable JSON Schema for the graph format, a discovery `index.json` listing available graphs, and versioning guarantees so any downstream consumer — including the future agent-team repo — can code against a fixed interface.

### 2.2 Non-Goals

- **NG1** — Multi-user concurrent editing of the vault. Single-writer assumed.
- **NG2** — Real-time sync. Daily cadence is the minimum viable refresh rate.
- **NG3** — Web UI. Obsidian is the human UI; Claude Code is the local agent UI; downstream consumer repos handle any other UI.
- **NG4** — Cloud-only deployment. Everything runs locally or on a single VPS. GitHub Actions is supported for scheduling but not required.
- **NG5** — Training or fine-tuning models. Off-the-shelf Claude + embedding API only.
- **NG6** — Supporting file types other than markdown + images in v1. Code, PDFs, video deferred to v2.
- **NG7** — **Agent logic.** This repo does not contain agent teams, orchestration, or user-facing chat workflows. Those live in a separate consumer repo.
- **NG8** — **Non-GitHub / non-local storage backends in v1.** S3, SharePoint, and other backends are defined in the adapter interface but deferred to v2+.
- **NG9** — **Bidirectional sync from consumer back to framework.** The published graph is read-only. Consumers cannot mutate it.

### 2.3 Success Criteria

- **SC1** — A fresh clone + `make bootstrap` + `make ingest` produces a browsable vault and a working MCP server in under 30 minutes on a representative 1k-document subset.
- **SC2** — Claude Code, configured with the MCP server, can answer a benchmark set of 20 hand-curated queries with correct retrieval in ≥16/20 cases (80%).
- **SC3** — Daily incremental runs complete in under 15 minutes for a corpus of 5k documents with <5% churn.
- **SC4** — Playwright scraper produces canonical markdown that passes the same frontmatter validator as static sources, for at least 3 target sites.
- **SC5** — Every edge in the graph has a `source_doc_id` and `confidence_score`; no orphan edges.
- **SC6** — `make publish` with the GitHub backend configured pushes `graph.json`, `graph.jsonld`, `graph.graphml`, and `graph.meta.json` to the dedicated artifacts repo on a tagged commit; GitHub Pages URL resolves within 5 minutes.
- **SC7** — A downstream consumer (tested via a reference fetcher script) can pull the published graph from either a local path or an HTTP URL and validate it against the published JSON Schema with zero errors.
- **SC8** — Eval gate: a seeded regression (artificially degraded extraction prompt) correctly blocks publish, keeps the previous good artifact live, and produces a failure report.

---

## 3. Scope & Phases

| Phase | Goal | Deliverable | Exit criteria |
|---|---|---|---|
| **0 — Discovery** | Understand what's in the source repos and propose canonical schemas | `DISCOVERY_REPORT.md`, schema proposal | @architect approves schema |
| **1 — Core pipeline** | Static corpus → graph + vector DBs + Obsidian vault | Working `ingest` command, vault, graph DB populated | 100-doc test set produces valid output |
| **2 — MCP server (local)** | Claude Code can query the graph locally | MCP server with 5 tools | Claude Code connects and returns benchmark-correct answers |
| **3 — Multi-format export + publishing** | Graph packaged and published to storage backend | `export` + `publish` commands; local FS and GitHub backends work | Published artifact fetchable via HTTP + validates against published schema |
| **4 — CI eval gates** | Quality regressions block publish | Eval harness; `thresholds.yaml`; publish blocker | Seeded bad extraction is blocked and raises alert |
| **5 — Staleness** | Upstream doc change detection | `check-staleness` command, frontmatter `stale:` flag | Detects synthetic upstream change in test |
| **6 — Playwright extraction** | Dynamic source ingestion | Scraper for 1 target site feeding the pipeline | Scraped site produces vault pages matching schema |
| **7 — Scheduling** | Automated runs with observability | Local cron/systemd timer + `.github/workflows/daily-update.yml` | 7 consecutive green runs from each scheduler path |
| **8 — Hardening** | Production readiness | Monitoring, error handling, backup/restore, retention pruning | All items in acceptance checklist pass |

**Phase gates** are enforced by @product-owner. A phase cannot start until the previous phase's exit criteria are met and recorded in `DECISIONS.md`.

---

## 4. Functional Requirements

### FR-1 — Source ingestion

- **FR-1.1** — Read all `.md` files under `corpus-a/` (flat, `__`-delimited names).
- **FR-1.2** — Parse each filename of the form `prefix__segment1__segment2__...__leaf.md` into a logical path `[prefix, segment1, ..., leaf]`.
- **FR-1.3** — Read all `.md` files under `corpus-b/` (folder-based), preserving their relative folder paths.
- **FR-1.4** — For repo B, resolve embedded image references (`![alt](./img/foo.png)` or `![[foo.png]]`) and copy referenced images to `vault/attachments/`, rewriting links.
- **FR-1.5** — Handle basename collisions across repos by prefixing with repo identifier (`A_` / `B_`) in the canonical path.
- **FR-1.6** — Produce a manifest (`.cache/manifest.sqlite`) recording each source file's path, SHA256, last-seen commit, and canonical destination path.

### FR-2 — Canonicalization

- **FR-2.1** — Emit each source file to `corpus/` with standardized frontmatter (schema in §7.1).
- **FR-2.2** — Preserve original basename in the `aliases:` list of frontmatter.
- **FR-2.3** — Populate `parent:` frontmatter field with a wikilink to the logical parent (derived from `__` delimiters or folder path).
- **FR-2.4** — Populate `source_url:` frontmatter field from body metadata if present, otherwise null.
- **FR-2.5** — Leave body content unchanged; canonicalization touches frontmatter only.
- **FR-2.6** — Validate every emitted file against the frontmatter schema; fail fast with a file-path-indexed error list.

### FR-3 — Entity & relationship extraction

- **FR-3.1** — Chunk each canonical markdown file using header-aware splitting (H2/H3 boundaries) with a 1500-token soft cap and 200-token overlap.
- **FR-3.2** — For each chunk, call the extraction LLM (Claude Sonnet 4.5) with a typed prompt that returns JSON: entities (name, type, aliases, description) and relationships (source, target, predicate, confidence, evidence_span).
- **FR-3.3** — Tag each extracted fact with `EXTRACTED` (direct quote support), `INFERRED` (reasonable inference, confidence ≥ 0.7), or `AMBIGUOUS` (flag for review, confidence < 0.7).
- **FR-3.4** — Deduplicate entities within a single document by name + fuzzy match (rapidfuzz, threshold 90).
- **FR-3.5** — Cache extraction results keyed by `hash(prompt_version + chunk_content)`; do not re-extract unchanged chunks.
- **FR-3.6** — Compute embeddings for each chunk using the configured embedding model; upsert by stable chunk ID (`hash(doc_id + offset + text)`).

### FR-4 — Graph construction

- **FR-4.1** — Cross-document entity resolution: merge entities with matching normalized names (lowercase, stripped punctuation) within the same type. Preserve the union of aliases.
- **FR-4.2** — Write entity nodes with properties: `name`, `type`, `aliases[]`, `description`, `first_seen_doc`, `mention_count`.
- **FR-4.3** — Write relationship edges with properties: `predicate`, `confidence`, `provenance_tag`, `source_doc_ids[]`, `evidence_spans[]`.
- **FR-4.4** — Write document nodes with properties: `doc_id`, `canonical_path`, `source_url`, `content_hash`, `updated_at`.
- **FR-4.5** — Connect document nodes to their extracted entities via `MENTIONS` edges (carrying chunk offset).
- **FR-4.6** — Connect document nodes to their parent document via `PARENT_OF` edges (derived from hierarchy).
- **FR-4.7** — On re-ingestion of a changed document, delete all `MENTIONS` edges from that doc before re-inserting; preserve entities that are still mentioned elsewhere.

### FR-5 — Vector indexing

- **FR-5.1** — Store chunk embeddings in the vector DB with payload: `doc_id`, `chunk_id`, `offset`, `text`, `canonical_path`.
- **FR-5.2** — Support upsert by `chunk_id`; support delete by `doc_id` (cascade to all chunks of that doc).
- **FR-5.3** — Store entity description embeddings separately (collection `entities`) for entity-level semantic search.

### FR-6 — Obsidian vault emission

- **FR-6.1** — Emit every canonical document as `vault/<canonical_path>.md` with enriched frontmatter (§7.1) including `related:` field populated from graph edges.
- **FR-6.2** — For each entity with ≥2 mentions across the corpus, emit `vault/Entities/<Type>/<Name>.md` with frontmatter, a description section, and an auto-generated "Mentioned in" list of backlinks.
- **FR-6.3** — Emit singleton entities (1 mention) as inline wikilinks only; do NOT create pages for them (avoid graph-view noise).
- **FR-6.4** — Use absolute wikilinks (`[[corpus-a/parent/child|child]]`) to avoid basename collision bugs in Obsidian.
- **FR-6.5** — Write `.obsidian/app.json` with `"attachmentFolderPath": "attachments"`, `"newLinkFormat": "absolute"`, `"useMarkdownLinks": false`.
- **FR-6.6** — All frontmatter uses Obsidian 1.9 conventions: plural list-valued keys (`tags:`, `aliases:`, `cssclasses:`).

### FR-7 — MCP server for Claude Code

- **FR-7.1** — Expose an MCP stdio server (`python -m knowledge_graph.mcp_server`).
- **FR-7.2** — Tools exposed:
  - `query_graph(question: str, max_hops: int = 2) -> SubgraphResult`
  - `get_node(name: str, type: str | None) -> NodeResult`
  - `get_neighbors(node_id: str, edge_type: str | None, direction: "in" | "out" | "both") -> NeighborsResult`
  - `shortest_path(from_node: str, to_node: str, max_length: int = 6) -> PathResult`
  - `find_stale(since_days: int = 7) -> list[DocId]`
- **FR-7.3** — All tools return structured JSON with `confidence_score` and `source_doc_ids` fields preserved.
- **FR-7.4** — The server never exposes raw extraction prompts or API keys.

### FR-8 — Staleness detection

- **FR-8.1** — For every document with a non-null `source_url`, perform a weekly staleness check (configurable).
- **FR-8.2** — Check strategy order: (a) HTTP conditional GET with `If-Modified-Since`/`If-None-Match`, (b) HEAD fallback, (c) GET + content hash compare, (d) optional LLM material-change judge.
- **FR-8.3** — Mark stale docs by setting `stale: true` in frontmatter and adding a `last_checked` timestamp.
- **FR-8.4** — Never mutate stale docs automatically — flag for human review only.
- **FR-8.5** — Emit a `STALENESS_REPORT.md` listing stale docs with their URLs and last-check timestamps.

### FR-9 — Playwright dynamic extraction

- **FR-9.1** — Configurable list of target sites in `sources.yaml` with per-site: base URL, sitemap URL, URL patterns to include/exclude, auth config (if any), rate limit.
- **FR-9.2** — For each target site, discover URLs via sitemap.xml or recursive link following (bounded depth, same-origin only).
- **FR-9.3** — Render each target page with Playwright (Chromium headless), wait for network idle, extract main content using readability-style DOM heuristics.
- **FR-9.4** — Convert HTML to markdown using `markdownify` or equivalent; preserve code blocks, tables, and images.
- **FR-9.5** — Assign canonical path based on site config (URL → path mapping rule).
- **FR-9.6** — Populate `source_url:` with the scraped URL; `scraped_at:` with the timestamp.
- **FR-9.7** — Respect robots.txt; honor `Crawl-delay`; default to 1 request/second; configurable back-off on 429.
- **FR-9.8** — Support authenticated scraping via a pre-captured auth state (`storageState.json`).
- **FR-9.9** — Auto-categorization: assign `tags:` and `category:` frontmatter fields via configurable URL-pattern rules, fallback to LLM categorization for unmatched pages.

### FR-10 — Scheduling & automation

- **FR-10.1** — Provide **three** independently usable scheduling paths, all producing identical results:
  - **(a) `make daily`** — idempotent shell invocation suitable for `cron` or `systemd-timer` on the user's local machine
  - **(b) `.github/workflows/daily-update.yml`** — GitHub Actions workflow with cron trigger, runs on GitHub-hosted runners, uses repository secrets for API keys
  - **(c) Dagster job definition** — for users who want an orchestrator UI and asset observability
- **FR-10.2** — Daily job: (1) git-pull source repos, (2) detect changed files, (3) run Playwright scrapers, (4) canonicalize, (5) incrementally extract, (6) update graph + vector DBs, (7) emit vault delta, (8) run staleness check if scheduled day, (9) **run eval harness (FR-12)**, (10) **publish artifact if eval gates pass (FR-11)**, (11) write run report.
- **FR-10.3** — Every run produces a `runs/<timestamp>/report.json` with counts, duration, cost, errors, eval results, and publish status.
- **FR-10.4** — On failure, the previous good state is preserved; graph DB is never left in a half-updated state (use transactions). **The previously published artifact remains live.**
- **FR-10.5** — Alert on: run duration > 2× rolling average, error rate > 5%, LLM cost > 2× rolling average, **publish blocked by eval gate**.

### FR-11 — Graph artifact publishing

- **FR-11.1** — Implement a **Storage Adapter interface** with the following Python protocol:
  ```python
  class StorageAdapter(Protocol):
      def publish(self, artifact_dir: Path, metadata: dict) -> PublishResult: ...
      def fetch(self, uri: str) -> bytes: ...
      def exists(self, uri: str) -> bool: ...
      def list_versions(self) -> list[VersionInfo]: ...
      def prune(self, keep_days: int) -> list[str]: ...
  ```
- **FR-11.2** — v1 implementations:
  - **`LocalFileStorage`** — writes to a configured directory; `publish_uri` is a `file://` path
  - **`GitHubArtifactsStorage`** — commits to a **dedicated artifacts repository** (separate from the framework repo), configured as `github_artifacts_repo: owner/repo`. Uses a service-account PAT or a fine-grained token scoped to that repo only.
- **FR-11.3** — v2+ placeholders (interface defined, implementation stubbed): `S3Storage`, `SharePointStorage`, `AzureBlobStorage`. Each fails with a clear `NotImplementedError` if selected in v1.
- **FR-11.4** — GitHub backend behavior:
  - Commits to `main` branch of the artifacts repo with message `"Publish graph artifact {version} [auto]"`
  - Creates an annotated git tag `graph-vYYYYMMDDHHMMSS` pointing at the commit
  - Optionally enables **GitHub Pages** on the artifacts repo (configured by a one-off `make setup-pages` command). When enabled, the artifact is simultaneously reachable via:
    - Raw URL: `https://raw.githubusercontent.com/<owner>/<artifacts-repo>/main/graph.json`
    - Pages URL: `https://<owner>.github.io/<artifacts-repo>/graph.json`
  - Both URLs work; documentation recommends Pages URL for HTTP caching benefits and raw URL as fallback for direct git-based consumers.
- **FR-11.5** — **Retention policy (configurable, default: 30 days):**
  - After each publish, prune git tags older than `retention_days` in the artifacts repo
  - Never delete the `main` branch HEAD; the latest artifact is always accessible at the unqualified URL
  - Historical versions remain accessible via tag URLs until pruned
- **FR-11.6** — Every publish writes a `graph.meta.json` sidecar containing:
  ```json
  {
    "version": "graph-v20260424-030000",
    "schema_version": "1.0",
    "published_at": "2026-04-24T03:00:00Z",
    "framework_commit_sha": "abc123...",
    "source_manifest_hashes": {"corpus-a": "...", "corpus-b": "..."},
    "eval_results": {"f1_overall": 0.89, "coverage": 0.94, ...},
    "doc_count": 4823,
    "entity_count": 12407,
    "edge_count": 38291,
    "formats": ["json", "jsonld", "graphml"]
  }
  ```
- **FR-11.7** — Publishing is **atomic**: all files (`graph.json`, `graph.jsonld`, `graph.graphml`, `graph.meta.json`, `index.json`) land in a single commit or not at all.
- **FR-11.8** — The framework repo contains **no published artifacts** (they live in the dedicated artifacts repo only). `.gitignore` excludes the `publish/` staging directory.

### FR-12 — CI eval gates with publish blocking

- **FR-12.1** — Maintain `evals/golden_set.jsonl`: a hand-labeled set of ≥50 source documents with expected entities and relationships, plus a benchmark set of ≥20 retrieval queries with expected top-result doc IDs.
- **FR-12.2** — `evals/thresholds.yaml` — user-configurable thresholds, with sensible v1 defaults:
  ```yaml
  # Any threshold violated blocks publish.
  # Defaults are conservative starting points; tune per-project.
  extraction:
    f1_overall_min: 0.80
    f1_drop_max: 0.03           # F1 drop vs. last published > 3% blocks
    coverage_min: 0.90           # <90% expected entities found blocks
    per_type_f1_drop_max: 0.05   # any single type F1 drop > 5% blocks
  retrieval:
    recall_at_5_min: 0.75
    recall_at_5_drop_max: 0.05
    mrr_min: 0.50
  cost:
    per_doc_usd_max: 0.05        # cost creep guard
  variance:
    min_runs_for_regression: 3   # declare regression only with ≥3-sigma confidence
  ```
- **FR-12.3** — Every pipeline run executes the eval harness after graph merge and before publish.
- **FR-12.4** — If any threshold is violated:
  - The current run is marked `FAILED (eval gate)` in `runs/<timestamp>/report.json`
  - The publish step is **skipped**
  - The previously published artifact **remains live and unchanged**
  - An alert is emitted (log level ERROR; GitHub Actions marks workflow red; local cron logs include a machine-grep-able marker)
- **FR-12.5** — **Override mechanism:** `make publish FORCE=1` bypasses gates with loud warnings in logs and in the `graph.meta.json` (`forced_publish: true`, `forced_reason: <string>`). Emergency use only; triggers an audit entry.
- **FR-12.6** — Variance handling: before declaring regression, require the eval to be consistent across `min_runs_for_regression` (default 3) consecutive runs. This prevents LLM non-determinism from producing false positives.
- **FR-12.7** — Eval results are appended to `evals/history.jsonl` for trend analysis and are included in every `graph.meta.json`.

### FR-13 — Consumer contract

- **FR-13.1** — Publish a **JSON Schema** at `schemas/graph-v1.schema.json` (also published alongside the artifact) that defines the structure of `graph.json`. Consumers MUST validate against this schema before use.
- **FR-13.2** — Publish an **`index.json`** alongside the graph artifact containing a list of available graph datasets:
  ```json
  {
    "schema_version": "1.0",
    "updated_at": "2026-04-24T03:00:00Z",
    "graphs": [
      {
        "name": "leanix-training",
        "description": "LeanIX training and documentation corpus",
        "latest_url": "https://<owner>.github.io/<artifacts-repo>/graph.json",
        "latest_version": "graph-v20260424-030000",
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
  This lets a single consumer repo aggregate multiple graphs from multiple framework instances.
- **FR-13.3** — Schema versioning: breaking changes to the graph schema bump the major version and publish to a new URL (`graph-v2.schema.json`). Consumers can pin to a major version for stability.
- **FR-13.4** — Ship a **reference consumer example** under `examples/consumer/`:
  - A minimal Python script that fetches the published graph from local path or HTTP URL
  - Validates against the schema
  - Demonstrates a 3-line query
  - Serves as a copy-paste starting point for downstream agent-team projects
- **FR-13.5** — **Multi-graph support documentation:** explicit guidance (in README + example) for consumers that need to combine multiple published graphs (e.g., one for SAP docs + one for internal training). Two patterns documented:
  - **Separate queries** — consumer asks each graph independently, LLM fuses results
  - **Merged graph** — consumer loads multiple `graph.json` files into a single in-memory NetworkX object, deduplicated by entity name+type, before querying. Reference code provided.
- **FR-13.6** — URL stability guarantee: the unqualified URLs (`graph.json`, `graph.jsonld`, `graph.graphml`) always point to the latest good version. Historical versions accessible via tag-qualified URLs (`tree/graph-vYYYYMMDDHHMMSS/graph.json`).

---

## 5. Non-Functional Requirements

| Dimension | Target | Notes |
|---|---|---|
| **Scale** | 10k docs, 100k entities, 500k edges | Headroom for 2× growth without re-architecture |
| **Ingestion throughput** | ≥50 docs/minute (incremental) | Bounded by LLM API latency |
| **MCP query latency** | P95 < 500ms for `query_graph(max_hops=2)` | Local graph DB, local vector DB |
| **Initial indexing cost** | < $150 one-off for 5k docs | Claude Sonnet 4.5 for extraction |
| **Steady-state cost** | < $50/month | <5% daily churn assumption |
| **Availability** | Best-effort single-host | No HA requirement in v1 |
| **Backup** | Daily snapshot of graph DB + vector DB + manifest | Retention: 7 days rolling |
| **Observability** | Structured logs (JSON), run reports, Dagster UI | No APM required |
| **Security** | API keys via env vars, no secrets in repo, scraping state encrypted at rest | See §10 |
| **Portability** | Runs on macOS (dev) and Linux (prod) | Windows not supported in v1 |

---

## 6. Architecture

### 6.1 High-level data flow

```
                      ┌─────────────────────┐
                      │   Corpus Repo A     │ (flat, __-delimited)
                      └──────────┬──────────┘
                                 │
                      ┌──────────▼──────────┐      ┌──────────────────┐
                      │   Corpus Repo B     │      │  Playwright      │
                      │   (folders + imgs)  │      │  Scrapers        │
                      └──────────┬──────────┘      └─────────┬────────┘
                                 │                            │
                                 └──────────────┬─────────────┘
                                                │
                                       ┌────────▼────────┐
                                       │ Canonicalizer   │ (Stage 1)
                                       │ → vault/        │
                                       │   frontmatter   │
                                       └────────┬────────┘
                                                │
                                       ┌────────▼────────┐
                                       │ Chunker +       │ (Stage 2)
                                       │ Extractor       │
                                       │  (Claude LLM)   │
                                       └────┬───────┬────┘
                                            │       │
                              ┌─────────────▼──┐ ┌──▼─────────────┐
                              │ Graph DB       │ │ Vector DB      │ (Stage 3)
                              │ (FalkorDB or   │ │ (Qdrant)       │
                              │  Neo4j)        │ │                │
                              └────────┬───────┘ └────┬───────────┘
                                       │              │
                                       └──────┬───────┘
                                              │
                                   ┌──────────▼──────────┐
                                   │ Obsidian Emitter    │ (Stage 4)
                                   │ → vault/ (final)    │
                                   │   + Entities/       │
                                   └──────────┬──────────┘
                                              │
                                   ┌──────────▼──────────┐
                                   │ MCP Server          │ (Stage 5)
                                   │ (Python MCP SDK)    │
                                   └──────────┬──────────┘
                                              │
                                      Claude Code agents
```

### 6.2 Component responsibilities

| Component | Language | Responsibility |
|---|---|---|
| `canonicalizer/` | Python | Walks source repos, parses `__` hierarchy, normalizes frontmatter, writes `corpus/` |
| `chunker/` | Python | Header-aware markdown chunking with caching by content hash |
| `extractor/` | Python | LLM calls for entity + relationship extraction with retry/backoff |
| `graph/` | Python | Graph DB client (FalkorDB or Neo4j), upsert/delete operations |
| `vector/` | Python | Qdrant client, chunk & entity collections |
| `emitter/` | Python | Writes Obsidian vault with frontmatter, wikilinks, entity pages |
| `mcp_server/` | Python | Python MCP SDK server exposing 5 tools |
| `staleness/` | Python | HTTP conditional GETs, sitemap polling, optional LLM judge |
| `scrapers/` | Python | Playwright scrapers per target site + HTML→MD conversion |
| `cli/` | Python | `ingest`, `update`, `scrape`, `check-staleness`, `emit-vault`, `serve-mcp` |
| `orchestration/` | Python (Dagster) | Daily job, asset graph, retries |

### 6.3 Cache strategy

Every expensive operation is cached by content hash:

- Extraction: `cache/extraction/<prompt_version>_<chunk_hash>.json`
- Embeddings: stored in vector DB keyed by chunk_id
- Canonicalization: skipped if `(source_hash, target_hash)` in manifest matches
- Playwright: `cache/scrape/<url_hash>/<timestamp>.html` kept for 7 days

Cache is content-addressable, so `rm -rf cache/` is always safe and forces a full rebuild.

### 6.4 Storage adapter architecture

Publishing is abstracted behind a pluggable adapter. v1 ships two implementations; v2+ will add more without requiring changes to the publishing pipeline.

```
┌─────────────────────────────────────┐
│  Publisher (stage after merge+eval) │
└──────────────────┬──────────────────┘
                   │ StorageAdapter protocol
        ┌──────────┴──────────┬──────────────────┬─────────────────┐
        ▼                     ▼                  ▼                 ▼
┌──────────────────┐  ┌────────────────┐  ┌─────────────┐  ┌───────────────┐
│ LocalFileStorage │  │ GitHubArtifacts│  │ S3Storage   │  │ SharePoint    │
│                  │  │ Storage        │  │ (v2+, stub) │  │ Storage       │
│ v1               │  │ v1             │  │             │  │ (v2+, stub)   │
└──────────────────┘  └────────────────┘  └─────────────┘  └───────────────┘
```

**Adapter selection** is via `config/publishing.yaml`:

```yaml
storage_backend: github   # local | github | s3 (v2+) | sharepoint (v2+)

local:
  output_dir: ./publish/

github:
  artifacts_repo: mygithubuser/graph-rag-artifacts    # DEDICATED repo
  branch: main
  token_env: GITHUB_ARTIFACTS_TOKEN                    # fine-grained PAT
  enable_pages: true                                    # serve via Pages URL
  pages_branch: main
  commit_author_name: "graph-rag-framework"
  commit_author_email: "noreply@example.com"

retention:
  keep_days: 30                                         # prune tags older than this
  keep_last_n_always: 3                                 # safety floor

override:
  allow_force_publish: false                            # require explicit --force flag
```

**Why a dedicated artifacts repo (not a branch in the framework repo):**

- Clean separation: framework repo stays focused on code; artifacts repo stays focused on data.
- GitHub Pages: a dedicated repo can enable Pages on `main` without conflicting with framework docs/tooling.
- Access control: artifacts repo can have a different visibility, collaborators, and PAT scope than the framework repo.
- Size hygiene: graph artifacts can grow large over time; keeping them out of the framework repo keeps clone size small for contributors.
- Multi-framework support: one consumer repo can aggregate artifacts from multiple framework instances, each with their own dedicated artifacts repo.

### 6.5 Graph export formats

The `emitter` stage produces the Obsidian vault. A parallel `exporter` stage produces three machine-readable formats plus metadata, all written to `publish/` before handoff to the storage adapter.

| Format | File | Purpose | Consumer |
|---|---|---|---|
| **Native JSON** | `graph.json` | Compact, schema-validated, NetworkX-serializable | Python consumers, MCP server |
| **JSON-LD** | `graph.jsonld` | W3C Linked Data, RDF-compatible | Semantic web tooling, SPARQL endpoints, generic RDF consumers |
| **GraphML** | `graph.graphml` | Standard XML graph format | Gephi, Cytoscape, yEd, academic analysis |
| **Metadata** | `graph.meta.json` | Version, schema, eval results, counts | Discovery + provenance (always fetched first) |
| **Discovery index** | `index.json` | List of available graphs at this publishing target | Multi-graph consumers |
| **Schema** | `schemas/graph-v1.schema.json` | JSON Schema for `graph.json` | Consumer validation |
| **Human report** | `GRAPH_REPORT.md` | High-degree nodes, surprising connections, stats | Humans auditing each publish |

All formats contain the same information; they differ only in serialization. The export stage produces them from the same in-memory graph object (one pass, three writers).

### 6.6 Publishing pipeline

```
  Graph merged ──► Eval harness ──► Thresholds pass? ──┬── No ──► SKIP publish
                        │                                │          Log FAILED
                        │                                │          Keep last good live
                        │                                │          Alert
                        ▼                                │
                  Eval results                           │
                  appended to history                    │
                                                         Yes
                                                          │
                                                          ▼
                                             Multi-format export to publish/
                                                          │
                                                          ▼
                                             StorageAdapter.publish(publish/, metadata)
                                                          │
                                             ┌────────────┼─────────────┐
                                             ▼            ▼             ▼
                                        LocalFileStorage  GitHubArtifactsStorage
                                        (copy files)     (git add, commit, tag, push,
                                                          optionally trigger Pages build)
                                                          │
                                                          ▼
                                             Retention prune
                                             (drop tags > retention_days old)
                                                          │
                                                          ▼
                                             Run report updated, artifact live
```

### 6.7 Consumer-side flow (documented for reference)

This repo does NOT implement consumers, but documents the expected flow for them:

```
Consumer startup ──► Read consumer config (list of graph source URLs)
                               │
                               ▼
                     For each source:
                         Fetch index.json  (HTTP GET or file read)
                         Fetch graph.meta.json
                         Check schema_version against pinned version
                         Fetch graph.json  (or graph.jsonld / .graphml if preferred)
                         Validate against JSON Schema
                         Load into in-memory graph object
                               │
                               ▼
                     (Optional) Merge multiple graphs
                         Dedup by (entity_name, entity_type)
                         Union edges
                               │
                               ▼
                     Answer user/agent questions
                     ETag / Last-Modified caching on repeat fetches
```

A reference `examples/consumer/fetch_and_query.py` script demonstrates this flow against both a local-path and HTTP source.

---

## 7. Data Model

### 7.1 Canonical frontmatter schema

```yaml
---
# Identity
title: "Fact Sheet Types in LeanIX"              # Required
aliases:                                          # Optional; includes original basename
  - "LeanIX__EA__Fact_Sheet_Types"
  - "Fact Sheet Types"

# Classification (Obsidian 1.9 plural list form)
tags: [leanix, ea, metamodel]                     # Required; at least 1
cssclasses: []                                    # Optional

# Hierarchy (Breadcrumbs-compatible)
parent: "[[corpus-a/LeanIX/EA/index]]"            # Optional; absolute wikilink
up: "[[corpus-a/LeanIX/EA/index]]"                # Breadcrumbs alias of parent
related:                                           # Optional; populated by emitter
  - "[[corpus-a/LeanIX/EA/Fact_Sheet_Relations]]"

# Provenance
source_url: "https://docs.leanix.net/..."         # Optional; null if internal
source_repo: "corpus-a"                           # Required
source_path: "LeanIX__EA__Fact_Sheet_Types.md"    # Required; original path

# Freshness
created: 2024-05-01                               # Required
updated: 2026-04-20                               # Required; touched on content change
last_checked: 2026-04-15                          # Populated by staleness checker
stale: false                                      # true if upstream changed

# Graph metadata
entity_type: "concept"                            # concept | entity | process | reference
doc_id: "doc_7fa3c0d1"                            # Stable hash-based ID

# Scraping metadata (Playwright-sourced docs only)
scraped_at: null                                  # ISO 8601 or null
scrape_source: null                               # Site config name or null
---
```

### 7.2 Graph schema

**Node labels:**
- `Document` — one per canonical .md file
- `Entity` — one per resolved entity (subtypes: `Concept`, `Person`, `System`, `Process`, `Artifact`)
- `Chunk` — one per extracted chunk (optional; can be omitted if using vector DB as source of truth)

**Edge types:**
- `MENTIONS` — Document → Entity (props: `chunk_offset`, `confidence`, `provenance_tag`)
- `PARENT_OF` — Document → Document (from hierarchy)
- `RELATES_TO` — Entity → Entity (props: `predicate`, `confidence`, `provenance_tag`, `source_doc_ids[]`)
- `DEFINED_IN` — Entity → Document (for canonical definition doc)
- `SUPERSEDES` — Document → Document (from frontmatter, if authored)

**Required edge properties:** `created_at`, `updated_at`, `source_doc_ids[]`, `confidence`, `provenance_tag`.

### 7.3 Manifest schema (SQLite)

```sql
CREATE TABLE source_files (
  source_repo     TEXT NOT NULL,
  source_path     TEXT NOT NULL,
  content_hash    TEXT NOT NULL,
  canonical_path  TEXT NOT NULL,
  last_commit     TEXT,
  last_seen_at    TIMESTAMP NOT NULL,
  PRIMARY KEY (source_repo, source_path)
);

CREATE TABLE extractions (
  chunk_id         TEXT PRIMARY KEY,
  doc_id           TEXT NOT NULL,
  prompt_version  TEXT NOT NULL,
  content_hash    TEXT NOT NULL,
  extracted_at    TIMESTAMP NOT NULL,
  cost_usd        REAL
);

CREATE TABLE staleness_checks (
  doc_id          TEXT NOT NULL,
  checked_at      TIMESTAMP NOT NULL,
  status          TEXT NOT NULL,  -- 'fresh' | 'stale' | 'error'
  etag            TEXT,
  last_modified   TEXT,
  PRIMARY KEY (doc_id, checked_at)
);

CREATE TABLE runs (
  run_id          TEXT PRIMARY KEY,
  started_at      TIMESTAMP NOT NULL,
  finished_at     TIMESTAMP,
  status          TEXT NOT NULL,
  docs_processed  INTEGER,
  cost_usd        REAL,
  error_count     INTEGER
);

CREATE TABLE publishes (
  publish_id      TEXT PRIMARY KEY,
  run_id          TEXT NOT NULL REFERENCES runs(run_id),
  published_at    TIMESTAMP NOT NULL,
  storage_backend TEXT NOT NULL,       -- 'local' | 'github'
  publish_uri     TEXT NOT NULL,        -- file:// or https://
  version_tag     TEXT NOT NULL,        -- 'graph-vYYYYMMDDHHMMSS'
  artifact_hash   TEXT NOT NULL,        -- hash of graph.json
  forced          BOOLEAN NOT NULL DEFAULT 0,
  forced_reason   TEXT,
  eval_summary    TEXT                   -- JSON blob
);
```

### 7.4 Graph export — native JSON schema

`graph.json` structure (validated by `schemas/graph-v1.schema.json`):

```json
{
  "schema_version": "1.0",
  "metadata": {
    "generated_at": "2026-04-24T03:00:00Z",
    "framework_commit": "abc123",
    "source_manifest_hashes": {"corpus-a": "...", "corpus-b": "..."},
    "doc_count": 4823,
    "entity_count": 12407,
    "edge_count": 38291
  },
  "nodes": [
    {
      "id": "doc_7fa3c0d1",
      "type": "Document",
      "properties": {
        "canonical_path": "corpus-a/LeanIX/EA/Fact_Sheet_Types",
        "source_url": "https://docs.leanix.net/...",
        "content_hash": "sha256:...",
        "updated_at": "2026-04-24"
      }
    },
    {
      "id": "ent_business_capability",
      "type": "Entity",
      "subtype": "Concept",
      "properties": {
        "name": "Business Capability",
        "aliases": ["BC", "Business Cap"],
        "description": "A high-level business function...",
        "mention_count": 47
      }
    }
  ],
  "edges": [
    {
      "id": "edge_mentions_7fa3c0d1_business_capability",
      "type": "MENTIONS",
      "source": "doc_7fa3c0d1",
      "target": "ent_business_capability",
      "properties": {
        "confidence": 0.92,
        "provenance_tag": "EXTRACTED",
        "chunk_offset": 1240,
        "evidence_span": "a Business Capability represents..."
      }
    }
  ]
}
```

### 7.5 Graph export — JSON-LD context

`graph.jsonld` uses a stable context URL:

```json
{
  "@context": "https://<owner>.github.io/<artifacts-repo>/schemas/graph-v1.context.jsonld",
  "@id": "urn:graph:leanix-training:v20260424",
  "@type": "kg:KnowledgeGraph",
  "kg:generatedAt": "2026-04-24T03:00:00Z",
  "kg:nodes": [ ... ],
  "kg:edges": [ ... ]
}
```

The `@context` file defines term mappings to RDF/OWL predicates; published alongside the schema.

### 7.6 Graph export — GraphML

Standard GraphML XML per yWorks spec, with:
- Node attributes: `type`, `subtype`, `name`, `canonical_path`
- Edge attributes: `type`, `confidence`, `provenance_tag`
- Designed to open cleanly in Gephi for visual analysis.

---

## 8. Technology Stack

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Matches LLM/graph ecosystem, user's Python stack |
| Graph DB | **FalkorDB** (primary), Neo4j Community (fallback) | FalkorDB: faster, lower ops; Neo4j: better tooling if we need Bloom |
| Vector DB | **Qdrant** (standalone) | Strong payload filtering, proven at scale |
| Embeddings | **Voyage-3** (text) or `text-embedding-3-large` (fallback) | Voyage leads retrieval benchmarks; OpenAI if simpler |
| Extraction LLM | **Claude Sonnet 4.5** | Best JSON-mode reliability; user's stack |
| Categorization LLM | **Claude Haiku 4.5** | Cheap; enough for URL/content → category |
| Markdown parsing | `mistune` 3.x | Fastest Python parser; CommonMark-compliant |
| Frontmatter | `python-frontmatter` | Roundtrip-clean; preserves comments |
| HTML→MD | `markdownify` + `beautifulsoup4` | Simple; customizable rules |
| Graph algorithms | `networkx` for in-memory; `rustworkx` for heavy ops | Standard Python graph tooling |
| Fuzzy match | `rapidfuzz` | Fast; ~30× faster than fuzzywuzzy |
| Scraping | `playwright` (Python) | Handles dynamic content; user's stack |
| Orchestration | **Dagster** (prod), cron (MVP) | Asset model fits the DAG; freshness policies |
| MCP | `mcp` Python SDK | Official |
| CLI | `typer` | Click-based, clean ergonomics |
| Config | `pydantic-settings` + YAML | Type-safe config with env overrides |
| Logging | `structlog` | Structured JSON out of the box |
| Testing | `pytest` + `pytest-asyncio` | Standard |

**Not using:** LightRAG, graphify, Microsoft GraphRAG, LlamaIndex, LangChain. We deliberately build the pipeline ourselves for fit and control. (See `DECISIONS.md` → `DEC-001`.)

---

## 9. Agent Assignments

**Existing 14-agent team** from `~/.claude/claude-agent-team/` builds THIS framework repo. Consuming agents (who use the published artifact) live in a separate future repo and are out of scope for this project.

### 9.1 Existing agents — primary assignments

| Agent | Responsibility on this project |
|---|---|
| `@product-owner` | Owns SPEC.md; phase gating; manages TODOS.md; resolves open questions with human |
| `@architect` | System design sign-off; data model; DECISIONS.md entries for DEC-001 through DEC-00N; owns the consumer contract (schemas, index.json, versioning) |
| `@researcher` | **Phase 0 owner** — corpus discovery, pattern mining, schema proposal (see Phase 0 prompt in Appendix A) |
| `@backend-developer` | Main pipeline code: canonicalizer, chunker, extractor, emitter, exporter, CLI |
| `@database-engineer` | FalkorDB/Neo4j schema, Qdrant setup, migration scripts, backup/restore |
| `@systems-developer` | Playwright scrapers, HTML→MD conversion, MCP server, **storage adapters (Local + GitHub)**, daemonization |
| `@devops` | **Dual scheduling: local cron/systemd AND GitHub Actions workflows.** Artifacts repo bootstrapping, GitHub Pages setup, retention pruning, monitoring, VPS provisioning |
| `@qa-engineer` | **Eval harness for extraction quality (Phase 4 owner)**; 50-doc labeled golden set; benchmark 20 queries; threshold tuning; publish-gate regression tests |
| `@performance-engineer` | Batch size tuning, cache hit rate, LLM cost monitoring, parallelization |
| `@security-auditor` | API key handling, **PAT scoping for GitHub artifacts repo**, scraping etiquette review, robots.txt compliance, auth storage encryption |
| `@code-reviewer` | All PRs; every module merged through review |
| `@technical-writer` | README, **consumer contract docs, JSON Schema authoring, reference consumer example**, user-facing docs on Obsidian conventions, MCP tool docs |
| `@troubleshooter` | On-call for pipeline failures; root-cause analysis |
| `@frontend-developer` | **Not used in v1** (no web UI scope) |

### 9.2 Should we create new agents? — Honest assessment

**Recommendation: one new agent is worth creating. The other "maybes" are not.**

#### Recommended: `@knowledge-extraction-engineer` (NEW)

- **Why:** The single highest-leverage quality lever is the extraction prompt. Whoever owns it needs to treat prompt engineering as a craft, maintain the 50-doc golden set, iterate against extraction metrics (precision, recall, F1 on entity types), and own the `prompt_version` field. This role also owns `evals/thresholds.yaml` tuning.
- **Alternative:** Let `@backend-developer` own it. Viable but dilutes focus — backend also owns pipeline plumbing.
- **Shape:** Specializes in prompt design, eval curation, schema evolution of extracted JSON. Owns `extractor/` module, eval harness, and `cache/extraction/`.
- **Suggested skills to attach:** `knowledge-graph-construction` (already being built), `rag-evaluation` (already being built), the existing `leanix-automations` skill (for domain terminology).

#### Considered and rejected:

- **`@scraping-specialist`** for Playwright — `@systems-developer` covers browser automation, rate limits, and scheduling adequately. Only create if Playwright work grows into multi-site tenancy with complex auth.
- **`@graph-specialist`** for Cypher — `@database-engineer` is fine. Cypher is their domain.
- **`@prompt-engineer`** as distinct from `@knowledge-extraction-engineer` — overkill. Collapse both into the one agent above.
- **`@publishing-engineer`** for storage adapters + GitHub Actions — `@systems-developer` + `@devops` split this cleanly. Storage adapter interface + implementations = systems-developer; scheduling + CI + retention pruning = devops. No new agent needed.
- **`@consumer-contract-owner`** — `@architect` + `@technical-writer` cover this. Schema authoring is architecture; documentation is technical writing.

### 9.3 Agent workflow patterns for this project

Following your established hub-and-spoke pattern:

- **Phase 0:** `@product-owner` → `@researcher` → `@architect` (sign-off) → `@product-owner`
- **Phase 1:** `@product-owner` → `@architect` → `@database-engineer` (infra) + `@backend-developer` (pipeline) in parallel → `@knowledge-extraction-engineer` (prompts) → `@qa-engineer` (validation) → `@code-reviewer` → `@product-owner`
- **Phase 3 (publishing):** `@product-owner` → `@architect` (consumer contract + schemas) → `@systems-developer` (adapters) → `@devops` (GitHub setup + Pages + retention) → `@security-auditor` (PAT review) → `@technical-writer` (reference consumer + docs) → `@code-reviewer` → `@product-owner`
- **Phase 4 (eval gates):** `@product-owner` → `@qa-engineer` (harness + golden set + thresholds) → `@knowledge-extraction-engineer` (baseline metrics) → `@devops` (CI wiring) → `@product-owner`
- **Phase 6 (Playwright):** `@product-owner` → `@systems-developer` (scrapers) → `@security-auditor` (review) → `@code-reviewer` → `@product-owner`
- **Phase 7 (scheduling):** `@product-owner` → `@devops` (both local and GH Actions paths) → `@performance-engineer` (tuning) → `@product-owner`

Each agent follows the standard UNDERSTAND → PLAN → IMPLEMENT → VERIFY → REPORT workflow. Worktree isolation per agent per task.

---

## 10. Skills Required

### 10.1 Existing skills — reused

- **`project-state`** — session protocol, state files, conventions
- **`leanix-automations`** — LeanIX terminology, for extraction prompt domain tuning

### 10.2 New skills already created (delivered as `graph-rag-skills` bundle)

1. **`knowledge-graph-construction`**
   - Entity + relationship extraction prompt templates
   - Deduplication pipeline (normalize → fuzzy → LLM tiebreaker)
   - Provenance tagging rules (EXTRACTED / INFERRED / AMBIGUOUS)
   - Confidence calibration guidance
   - **Owner:** `@knowledge-extraction-engineer` (new)

2. **`obsidian-vault-emission`**
   - Obsidian 1.9 frontmatter conventions (plural keys, Bases-queryable)
   - Absolute wikilink emission, Breadcrumbs integration
   - Entity page templates, attachment collision handling
   - **Owner:** `@backend-developer` / `@technical-writer`

3. **`rag-evaluation`**
   - Golden set construction, per-type F1
   - Retrieval metrics (Recall@k, MRR, nDCG)
   - CI regression gates and variance handling
   - **Owner:** `@qa-engineer` / `@performance-engineer`

4. **`playwright-documentation-scraping`**
   - Ethical scraping, robots.txt, rate limiting
   - Sitemap-first discovery, HTML→markdown normalization
   - Auto-categorization into existing taxonomies
   - **Owner:** `@systems-developer`

### 10.3 New skill to create for Phase 3 (publishing)

5. **`graph-artifact-publishing`** (NEW — create during Phase 3)
   - Storage adapter protocol definition and v1 implementations (Local, GitHub)
   - GitHub dedicated artifacts repo setup pattern (bootstrap, PAT scoping, Pages enablement)
   - JSON Schema authoring for `graph-v1.schema.json`
   - JSON-LD context design and publishing
   - GraphML export patterns
   - Consumer-side fetch + validate reference pattern
   - Retention pruning strategy (tag lifecycle management)
   - **Owner:** `@systems-developer` / `@architect`

Each skill lives in `~/.claude/claude-agent-team/skills/` and is installed via the provided `install.sh` script.

---

## 11. Project State Initialization

At project init, create the following under `.claude/state/`:

### 11.1 `MEMORY.md` — seed entries

```markdown
# Project Memory

## Codebase Patterns
- [2026-04-20] Canonical path format: `<repo>/<hierarchy-segments>/<leaf>`. Repo A uses `__` delimiters in original filenames; Repo B uses real folders. Canonicalizer unifies both.
- [2026-04-20] Every .md file MUST have frontmatter matching SPEC §7.1. Files without required fields are rejected by the canonicalizer.

## Gotchas & Pitfalls
- [2026-04-20] Obsidian 1.9 requires plural, list-valued YAML keys (tags:, aliases:, cssclasses:). Singular/scalar forms break.
- [2026-04-20] FalkorDB is Redis-based — watch memory config in docker-compose.
- [2026-04-20] Claude API returns JSON mode with occasional trailing commas — parse defensively with json-repair as fallback.

## Dependencies & Tools
- [2026-04-20] Graph DB: FalkorDB primary; Neo4j Community fallback. Never use Kùzu (archived Oct 2025).
- [2026-04-20] Vector DB: Qdrant. Chunk IDs are deterministic (hash of doc_id + offset + text).

## Performance Notes
- [2026-04-20] Extraction is the bottleneck. Batch chunks within a single LLM call up to ~6k output tokens; anything above that fragments.
```

### 11.2 `DECISIONS.md` — seed entries

```markdown
# Decision Log

## DEC-001 — Build custom, do not adopt graphify/LightRAG/GraphRAG
- **Date:** 2026-04-20
- **Status:** Active
- **Decided by:** @architect
- **Context:** Requirements include hierarchical filename parsing, two-repo merge with image handling, upstream staleness checks against SAP docs, tight Claude Code MCP integration, and Playwright extraction layer.
- **Decision:** Build the pipeline in-house. Use well-maintained libraries for components (markdown parsing, embeddings, graph DB drivers) but not an end-to-end framework.
- **Alternatives:**
  - graphify — MIT, well-designed, but tightly coupled to AI coding assistant workflow and Leiden recompute on update is opaque.
  - LightRAG — Excellent incremental updates but Python-only engine, no Obsidian output, and we'd end up writing a similar emitter anyway.
  - Microsoft GraphRAG — Rejected: expensive to reindex, weak incremental story, LazyGraphRAG not in OSS repo.
- **Trade-offs:** More code to maintain (~700 LOC), but perfect fit, smaller dependency footprint, and evolvability.

## DEC-002 — FalkorDB as primary graph store
- **Date:** 2026-04-20
- **Status:** Active
- **Decided by:** @architect, @database-engineer
- **Context:** Need a local, performant, actively maintained embedded/lightweight graph store.
- **Decision:** FalkorDB (Redis-based) as primary; Neo4j Community Edition as documented fallback if we need Bloom visualization or more operational tooling.
- **Alternatives:**
  - Kùzu — REJECTED: archived October 10, 2025.
  - Memgraph — viable; FalkorDB chosen for lower ops footprint.
  - NetworkX + pickle — MVP only; not for steady-state.
- **Trade-offs:** FalkorDB is younger than Neo4j but active and funded. Escape hatch is clean: Cypher is portable.

## DEC-003 — Obsidian as secondary human UI only
- **Date:** 2026-04-20
- **Status:** Active
- **Decided by:** @architect, @product-owner
- **Context:** Primary consumer is Claude Code via MCP. Humans want a way to browse.
- **Decision:** Emit an Obsidian vault as a derived artifact. Vault is read-only from the user's perspective; any edits are NOT fed back into the graph (one-way).
- **Alternatives:**
  - Build a web UI — rejected, out of scope.
  - Obsidian as primary with vault-native RAG — rejected, weaker for LLM consumption.
- **Trade-offs:** Users edit-wanting-to-persist get confused. Mitigate with README and a top-banner note in each vault page.

## DEC-004 — Framework repo separation from agent consumer repo
- **Date:** 2026-04-24
- **Status:** Active
- **Decided by:** @architect, @product-owner
- **Context:** Original scope conflated "build the graph" and "agents that use the graph" into one project. User clarified that agent teams belong in a separate downstream repo with a stable HTTP contract to this framework.
- **Decision:** This repo produces a framework and a published graph artifact. It contains no agent logic beyond the optional built-in local MCP server. Consumer agents live in a separate repo, fetch the artifact via HTTP or local path, and validate against a published JSON Schema.
- **Alternatives:**
  - Monolithic repo with agents + framework — rejected, blocks multi-consumer reuse.
  - Framework publishes to a branch in its own repo — rejected in favor of DEC-005.
- **Trade-offs:** More repos to coordinate, but clean boundaries, independent versioning, and clear consumer contract.

## DEC-005 — Dedicated artifacts repo for GitHub publishing
- **Date:** 2026-04-24
- **Status:** Active
- **Decided by:** @architect, @devops
- **Context:** Publishing graph artifacts to GitHub can use either (a) a branch in this repo or (b) a dedicated separate repo.
- **Decision:** Use a **dedicated artifacts repo** (e.g., `mygithubuser/graph-rag-artifacts`). Framework repo stays focused on code; artifacts repo stays focused on data.
- **Alternatives:**
  - Branch in framework repo (`graph-artifacts` branch) — simpler, but clutters framework repo history and complicates Pages setup.
  - Release assets on framework repo tags — works but limited to 2GB per asset, and discovery is worse than a browsable repo.
- **Trade-offs:** One more repo to manage. PAT scoping, visibility, and collaborator lists are independent (feature, not bug). First-time setup requires `make setup-artifacts-repo` bootstrap command.

## DEC-006 — GitHub Pages enabled by default for artifacts repo
- **Date:** 2026-04-24
- **Status:** Active
- **Decided by:** @architect, @devops
- **Context:** Consumers need HTTP URL access to the graph. Raw GitHub URLs work but have no CDN and no custom headers; Pages adds caching and nicer URLs.
- **Decision:** Enable Pages by default on the artifacts repo. Both URLs work simultaneously:
  - Pages: `https://<owner>.github.io/<artifacts-repo>/graph.json`
  - Raw: `https://raw.githubusercontent.com/<owner>/<artifacts-repo>/main/graph.json`
- **Alternatives:**
  - Raw URL only — fewer moving parts but no caching.
  - Pages only — removes fallback if Pages build fails.
- **Trade-offs:** One-time Pages setup step (`make setup-pages` after `make setup-artifacts-repo`). Users who forget this step still have working raw URLs as fallback.

## DEC-007 — User-configurable eval thresholds with sensible defaults
- **Date:** 2026-04-24
- **Status:** Active
- **Decided by:** @qa-engineer, @architect, @product-owner
- **Context:** Publish-blocking thresholds need to balance "catches real regressions" vs "doesn't block on noise". Different projects will have different tolerances.
- **Decision:** Ship `evals/thresholds.yaml` with defaults (F1 drop > 3% blocks, coverage < 90% blocks, per-type F1 drop > 5% blocks). User edits the file to tune per project.
- **Defaults (v1):**
  - F1 overall drop > 3% — blocks
  - Coverage < 90% (< 90% of golden entities found) — blocks
  - Per-type F1 drop > 5% — blocks
  - Recall@5 drop > 5% — blocks
  - Cost per doc > $0.05 — blocks (cost creep guard)
  - Variance: require 3-sigma confidence before declaring regression
- **Alternatives:**
  - Hardcoded thresholds — rigid, not appropriate across domains.
  - No defaults (require user to configure before first run) — high friction, users will skip it.
- **Trade-offs:** Defaults may be too strict for small corpora or too loose for critical ones. Doc clearly explains how to tune.

## DEC-008 — Retention: keep 30 days of tags + prune
- **Date:** 2026-04-24
- **Status:** Active
- **Decided by:** @devops, @architect
- **Context:** Every publish creates a git tag on the artifacts repo. Unchecked, tags accumulate indefinitely.
- **Decision:** Prune tags older than 30 days after each successful publish. Always keep the last 3 tags regardless of age (safety floor).
- **Rationale:** 30 days = enough history for debugging recent regressions, short enough to keep the repo tidy. `main` HEAD always has the latest artifact, so "latest" access never depends on tags.
- **Configurable** via `retention.keep_days` and `retention.keep_last_n_always` in `config/publishing.yaml`.
- **Trade-offs:** Long-term historical analysis requires external snapshots. Users who care can symlink `keep_days: 365` or mirror to another backend.
```

### 11.3 `TODOS.md` — seed backlog

Seeded with 30+ tasks covering all six phases. See `TODOS-seed.md` appendix (generated separately during init).

### 11.4 `CHANGELOG-DEV.md` and `HANDOFF.md`

Initialized empty; populated as work begins.

---

## 12. Milestones & Deliverables

| Milestone | Deliverable | Target duration | Owner |
|---|---|---|---|
| M0 | `DISCOVERY_REPORT.md` approved | 2–3 days | @researcher |
| M1 | Canonicalizer passes on 100-doc subset | 3–5 days | @backend-developer |
| M2 | Extraction runs end-to-end, graph DB populated | 4–6 days | @knowledge-extraction-engineer + @database-engineer |
| M3 | Obsidian vault opens cleanly with entity pages and wikilinks | 2–3 days | @backend-developer |
| M4 | MCP server answers all 20 benchmark queries | 3–4 days | @systems-developer |
| M5 | Multi-format export + LocalFileStorage + GitHubArtifactsStorage working | 3–5 days | @systems-developer + @architect |
| M6 | Consumer contract (schema + index.json + reference example) published | 2–3 days | @architect + @technical-writer |
| M7 | Eval harness with publish gate; seeded regression correctly blocked | 3–4 days | @qa-engineer + @devops |
| M8 | Playwright scraper produces vault-valid docs for 1 target site | 4–6 days | @systems-developer |
| M9 | Daily scheduled runs green for 7 days via BOTH local and GitHub Actions | 3–5 days | @devops |
| M10 | Retention pruning runs correctly; old tags removed, recent preserved | 1–2 days | @devops |
| M11 | All acceptance criteria pass; handoff to steady-state | 2–3 days | @product-owner |

**Total estimate: 5–7 weeks elapsed, ~30–45 focused development days.**

---

## 13. Open Questions (need human input before M1 starts)

- **Q1** — Confirm the two source repos are git-tracked. If not, what's the change-detection mechanism?
- **Q2** — List of target sites for Playwright scraping. Does SAP docs require authenticated access?
- **Q3** — LLM budget cap: hard stop at $X/month, or just alerting?
- **Q4** — Which embedding provider do you have an API key for already (Voyage, OpenAI, Cohere)?
- **Q5** — Deployment target: local machine always-on, home server, VPS, GitHub Actions, or combination?
- **Q6** — Do the existing docs already have any frontmatter? If so, what fields, and how should conflicts resolve?
- **Q7** — Is there a preferred Obsidian theme/plugin baseline to target for the emitted vault? (Breadcrumbs, Dataview/Bases, Copilot, etc.)
- **Q8** — What's the policy for LLM extraction errors: retry-then-skip, retry-then-fail, or retry-then-human-review?
- **Q9** — **GitHub artifacts repo name.** Default suggestion: `<username>/graph-rag-artifacts`. Confirm or provide preferred name.
- **Q10** — **GitHub artifacts repo visibility.** Public (consumer agents can fetch without auth) or private (consumer agents need PAT)?
- **Q11** — **Fine-grained PAT scope.** Should the publishing PAT be scoped to the artifacts repo only, or to the framework repo as well? (Recommendation: artifacts repo only, least-privilege.)
- **Q12** — **Initial threshold tuning.** Accept v1 defaults (F1 drop > 3% blocks, coverage < 90% blocks) or tighter/looser for first 30 days while baselining?
- **Q13** — **Multi-graph reality check.** Is a second graph (e.g., internal non-LeanIX training material) already on the roadmap, or is this a single-graph deployment for the foreseeable future? Affects how much multi-graph tooling to polish in v1.

These are tracked as TODO-Q1 through TODO-Q13 in TODOS.md under status `Blocked — waiting on user input`.

---

## 14. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Extraction prompt quality is poor; low F1 on eval set | Medium | High | @knowledge-extraction-engineer builds 50-doc eval set first; iterate before scaling |
| Target scraping sites block us / rate-limit aggressively | Medium | Medium | Respect robots.txt; per-site auth state; fall back to manual capture if blocked |
| LLM costs exceed budget | Medium | Medium | Hard cap + alerts; cache extraction aggressively; use Haiku for categorization |
| Graph DB becomes bottleneck at 10k+ docs | Low | Medium | Indexes on frequent-query fields; escape hatch via Cypher portability (DEC-002) |
| Obsidian vault becomes too large to open | Low | Medium | Don't emit singleton entity pages; split into multiple vaults by top-level hierarchy if > 50k nodes |
| Daily job non-determinism (LLM output variability) | Medium | Low | Cache by prompt version + content hash; version pin the extraction prompt |
| Claude Sonnet API deprecation mid-project | Low | High | Model name in config; regression-test on model change |
| Upstream docs change structure and break scrapers | Medium | Medium | Per-site config with selectors; monitor scrape success rate; alert on drops |
| **GitHub Actions runner limits hit (6hr job timeout)** | Low | Medium | Incremental-only runs on GH Actions; fall back to local scheduler for full reindex |
| **GitHub PAT leaked or expired** | Low | High | Fine-grained PAT scoped to artifacts repo only; 90-day expiry; rotation in DECISIONS.md runbook |
| **GitHub Pages build delay (can be 5–10 min)** | Low | Low | Publish step reports both Pages URL and raw URL; consumers fall back to raw URL if Pages stale |
| **Schema breaking change breaks consumers** | Medium | High | JSON Schema versioning (DEC docs in §FR-13.3); major-version URLs; deprecation notice period ≥ 30 days |
| **Eval gate too strict, blocks legitimate publishes** | Medium | Medium | User-configurable thresholds; variance handling requires 3-sigma; `--force` override with audit trail |
| **Eval gate too loose, misses real regressions** | Medium | High | Baseline defaults conservative; expand golden set as corpus grows; monthly review of eval history |
| **Retention pruning deletes a tag still in use** | Low | Medium | Safety floor (keep last 3 tags regardless of age); `main` HEAD always has latest; consumers should pin by date, not tag |

---

## 15. Acceptance Checklist (final gate)

### Functional
- [ ] SC1: Fresh clone → working system in < 30 min on 1k docs
- [ ] SC2: 16/20 benchmark queries answered correctly via MCP
- [ ] SC3: Daily incremental run < 15 min on 5k docs with <5% churn
- [ ] SC4: Playwright scraper produces schema-valid output for ≥3 sites
- [ ] SC5: Zero orphan edges in graph DB
- [ ] SC6: `make publish` successfully commits to dedicated artifacts repo + Pages URL resolves
- [ ] SC7: Reference consumer (`examples/consumer/fetch_and_query.py`) fetches and validates the published graph from both local path and HTTP URL
- [ ] SC8: Seeded extraction regression correctly blocks publish; previous good artifact remains live; alert fires

### Publishing
- [ ] GitHub artifacts repo bootstrapped via `scripts/setup-artifacts-repo.sh`
- [ ] GitHub Pages enabled; both Pages and raw URLs return `graph.json` with `Content-Type: application/json`
- [ ] `index.json` lists the published graph with correct URLs
- [ ] `graph.meta.json` populated with all required fields (version, schema_version, eval_results, counts)
- [ ] JSON Schema at `schemas/graph-v1.schema.json` validates the published `graph.json` with zero errors
- [ ] Retention pruning: tags older than 30 days deleted after publish; last 3 tags always preserved
- [ ] Atomic publish: simulated mid-publish failure leaves the previous artifact unchanged

### Eval gates
- [ ] Golden set (≥50 docs) committed to `evals/golden_set.jsonl`
- [ ] Benchmark queries (≥20) committed to `evals/benchmark_queries.yaml`
- [ ] `evals/thresholds.yaml` present with v1 defaults
- [ ] Eval harness runs as part of daily pipeline
- [ ] `evals/history.jsonl` growing with each run
- [ ] Seeded regression test (artificially degrade prompt) blocks publish in both local and GH Actions flows
- [ ] `--force` override works and records `forced_publish: true` in metadata

### Scheduling
- [ ] `make daily` runs end-to-end locally with exit code 0 on happy path
- [ ] `make daily` exits non-zero when eval gate blocks publish
- [ ] `.github/workflows/daily-update.yml` runs green on GitHub-hosted runner
- [ ] 7 consecutive green runs from local scheduler path
- [ ] 7 consecutive green runs from GitHub Actions path
- [ ] Retention prune step runs at end of every successful publish
- [ ] Alerts fire on: duration > 2× rolling avg, error rate > 5%, cost > 2× rolling avg, publish blocked

### Consumer contract
- [ ] `schemas/graph-v1.schema.json` published alongside artifact
- [ ] `schemas/graph-v1.context.jsonld` published alongside artifact
- [ ] `schemas/index-v1.schema.json` and `schemas/meta-v1.schema.json` published
- [ ] `examples/consumer/fetch_and_query.py` works against both `file://` and `https://` URLs
- [ ] `examples/consumer/multi_graph_merge.py` demonstrates multi-graph combine pattern
- [ ] Consumer README explains schema versioning, URL stability guarantees, and multi-graph patterns

### Operations
- [ ] All 14 agents have onboarded via their respective skills
- [ ] 5 new skills delivered and installed (4 from initial bundle + `graph-artifact-publishing`)
- [ ] All open questions (Q1–Q13) resolved and recorded in DECISIONS.md
- [ ] README, CONTRIBUTING, and skill docs complete
- [ ] Backup/restore tested end-to-end
- [ ] PAT rotation runbook documented in DECISIONS.md

---

## Appendix A — Phase 0 Discovery Prompt (run this with @researcher)

```
You are @researcher. Read .claude/state/HANDOFF.md, then .claude/SPEC.md in full.

Goal: Produce `.claude/DISCOVERY_REPORT.md` that answers the questions below, grounded in
actual file inspection. Do not guess — sample real files.

Inputs:
- `corpus-a/` — flat markdown repo with `__`-delimited filenames
- `corpus-b/` — folder-based markdown repo with embedded images

Method:
1. Enumerate both repos. Count files, total size, image count.
2. Sample 30 random files from each repo. For each, record:
   - Original path / filename
   - Derived logical path (from __ delimiters or folders)
   - Presence and shape of existing frontmatter
   - Inline link patterns (wikilinks? markdown links? bare URLs?)
   - Any explicit cross-references to other docs
   - Language, tone, typical length
3. For repo A specifically:
   - Enumerate distinct top-level prefixes (the first __-segment)
   - For each prefix, count files and sample 5
   - Identify any filename patterns that DON'T follow the __ convention (edge cases)
4. For repo B specifically:
   - Produce a directory tree (depth ≤ 3)
   - Enumerate image formats and approximate counts
   - Identify any files that reference images outside their folder (broken-relative cases)
5. Cross-repo overlap:
   - Are there concepts appearing in both repos? Sample some.
   - What's the likely deduplication challenge?
6. Propose a unified frontmatter schema. Start from SPEC §7.1 and propose deltas (fields to
   add/remove/rename) based on what you found.
7. Flag open questions for the human.

Output: `.claude/DISCOVERY_REPORT.md` with these sections:
- Inventory (counts, sizes, types)
- Repo A structural analysis
- Repo B structural analysis
- Cross-repo patterns and overlaps
- Proposed canonical frontmatter schema (with deltas from SPEC)
- Proposed canonical path mapping rules (with concrete examples)
- Edge cases and exceptions
- Hierarchical relationship patterns observed (beyond __ and folders)
- Implicit taxonomies (inferred from content, not just structure)
- Open questions for the human
- Recommended Phase 1 prep tasks

Do NOT modify any files in corpus-a/ or corpus-b/. Read-only.

When done, append to CHANGELOG-DEV.md and update HANDOFF.md. Flag @architect for review.
```

---

## Appendix B — Repository Layout (planned)

```
graph-rag-framework/
├── .claude/
│   ├── SPEC.md                    ← this file
│   ├── DISCOVERY_REPORT.md        ← Phase 0 output
│   └── state/
│       ├── MEMORY.md
│       ├── DECISIONS.md
│       ├── TODOS.md
│       ├── CHANGELOG-DEV.md
│       └── HANDOFF.md
├── .github/
│   └── workflows/
│       ├── daily-update.yml       ← FR-10.1(b) — scheduled pipeline
│       ├── ci.yml                  ← PR checks: lint, test, eval smoke
│       └── setup-artifacts-repo.yml  ← one-off bootstrap (manual dispatch)
├── src/
│   └── knowledge_graph/
│       ├── canonicalizer/
│       ├── chunker/
│       ├── extractor/
│       ├── graph/
│       ├── vector/
│       ├── emitter/               ← Obsidian vault writer
│       ├── exporter/              ← NEW: JSON / JSON-LD / GraphML multi-format
│       ├── publisher/             ← NEW: storage adapters + orchestration
│       │   ├── adapters/
│       │   │   ├── base.py        ← StorageAdapter protocol
│       │   │   ├── local_fs.py    ← LocalFileStorage
│       │   │   ├── github.py      ← GitHubArtifactsStorage
│       │   │   ├── s3.py          ← v2+ stub
│       │   │   └── sharepoint.py  ← v2+ stub
│       │   ├── retention.py       ← tag pruning
│       │   └── pages.py           ← GitHub Pages bootstrap
│       ├── mcp_server/            ← optional local MCP for Claude Code
│       ├── staleness/
│       ├── scrapers/
│       ├── cli.py
│       └── config.py
├── schemas/                        ← NEW: published consumer contract
│   ├── graph-v1.schema.json       ← JSON Schema for graph.json
│   ├── graph-v1.context.jsonld    ← JSON-LD context for graph.jsonld
│   ├── index-v1.schema.json       ← JSON Schema for index.json
│   └── meta-v1.schema.json        ← JSON Schema for graph.meta.json
├── examples/
│   └── consumer/                   ← NEW: reference downstream consumer
│       ├── fetch_and_query.py     ← minimal fetcher + validator + querier
│       ├── multi_graph_merge.py   ← reference multi-graph combine pattern
│       ├── requirements.txt
│       └── README.md
├── corpus-a/                       ← source repo A (submodule or symlink)
├── corpus-b/                       ← source repo B (submodule or symlink)
├── corpus/                         ← canonicalized (derived, .gitignored)
├── vault/                          ← Obsidian vault (derived, .gitignored)
├── publish/                        ← NEW: export staging (.gitignored)
│   ├── graph.json
│   ├── graph.jsonld
│   ├── graph.graphml
│   ├── graph.meta.json
│   ├── index.json
│   ├── GRAPH_REPORT.md
│   └── schemas/                   ← copied from ../schemas/ for self-contained publish
├── cache/                          ← content-addressable caches (.gitignored)
├── runs/                           ← run reports (.gitignored)
├── config/
│   ├── sources.yaml               ← Playwright scraper configs
│   ├── publishing.yaml            ← NEW: storage backend + retention config
│   ├── extraction_prompts/
│   └── site_rules/
├── evals/
│   ├── golden_set.jsonl           ← 50-doc labeled eval set
│   ├── benchmark_queries.yaml     ← 20 benchmark queries
│   ├── thresholds.yaml            ← NEW: publish-gate thresholds
│   ├── history.jsonl              ← NEW: append-only eval history
│   └── harness.py
├── tests/
├── orchestration/
│   └── dagster_defs.py
├── scripts/
│   ├── setup-artifacts-repo.sh    ← NEW: bootstrap dedicated artifacts repo
│   ├── setup-pages.sh             ← NEW: enable GitHub Pages on artifacts repo
│   └── verify-consumer.sh          ← NEW: runs examples/consumer/ as smoke test
├── docker-compose.yml              ← FalkorDB + Qdrant
├── pyproject.toml
├── Makefile                        ← targets: bootstrap, ingest, export, publish, daily, eval, prune
└── README.md
```

### Separate artifacts repo layout (bootstrapped by `scripts/setup-artifacts-repo.sh`)

```
graph-rag-artifacts/                ← dedicated repo, published via GitHub Pages
├── README.md                       ← auto-generated; explains contents, consumer contract link
├── index.json                      ← discovery document (FR-13.2)
├── graph.json                      ← latest JSON (FR-11.4 unqualified URL)
├── graph.jsonld                    ← latest JSON-LD
├── graph.graphml                   ← latest GraphML
├── graph.meta.json                 ← latest metadata
├── GRAPH_REPORT.md                 ← human-readable summary
└── schemas/
    ├── graph-v1.schema.json
    ├── graph-v1.context.jsonld
    ├── index-v1.schema.json
    └── meta-v1.schema.json

# Historical versions accessible via git tags:
# https://github.com/<owner>/<repo>/tree/graph-v20260424-030000/
```

---

## Appendix C — Daily Job Skeleton

```python
# orchestration/dagster_defs.py (abbreviated)

@asset
def source_manifest() -> Manifest: ...

@asset(deps=[source_manifest])
def scraped_pages() -> ScrapedPages: ...                     # Playwright

@asset(deps=[source_manifest, scraped_pages])
def canonical_corpus() -> CanonicalCorpus: ...               # Stage 1

@asset(deps=[canonical_corpus])
def chunks() -> Chunks: ...

@asset(deps=[chunks])
def extractions() -> Extractions: ...                        # Stage 2 (LLM)

@asset(deps=[extractions])
def graph_updated() -> GraphState: ...                       # Stage 3a

@asset(deps=[chunks])
def vectors_updated() -> VectorState: ...                    # Stage 3b

@asset(deps=[graph_updated, canonical_corpus])
def vault_emitted() -> VaultState: ...                       # Stage 4

@asset(deps=[graph_updated])
def multi_format_export() -> ExportState: ...                # Stage 5 (NEW)
# produces graph.json, graph.jsonld, graph.graphml, graph.meta.json, index.json

@asset(deps=[multi_format_export])
def eval_gate() -> EvalGateResult: ...                       # Stage 6 (NEW)
# runs harness, returns PASS / BLOCK; if BLOCK, downstream assets skip

@asset(deps=[eval_gate])
def artifact_published(storage_backend) -> PublishResult: ...# Stage 7 (NEW)
# only runs if eval_gate == PASS; calls StorageAdapter.publish()

@asset(deps=[artifact_published])
def retention_pruned() -> PruneResult: ...                   # Stage 8 (NEW)
# removes tags older than retention.keep_days

@asset(deps=[source_manifest])
def staleness_report(weekly_schedule) -> StalenessReport: ...# FR-8

@schedule(cron="0 3 * * *", target=daily_job)
def daily_schedule(): pass
```

### GitHub Actions equivalent skeleton

```yaml
# .github/workflows/daily-update.yml
name: Daily Graph Update
on:
  schedule:
    - cron: '0 3 * * *'        # 03:00 UTC daily
  workflow_dispatch:             # manual trigger

jobs:
  update:
    runs-on: ubuntu-latest
    timeout-minutes: 180          # well below 6hr limit
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - name: Install
        run: pip install -e .
      - name: Start services (FalkorDB, Qdrant)
        run: docker compose up -d
      - name: Run daily pipeline
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          VOYAGE_API_KEY: ${{ secrets.VOYAGE_API_KEY }}
          GITHUB_ARTIFACTS_TOKEN: ${{ secrets.GITHUB_ARTIFACTS_TOKEN }}
        run: make daily
      - name: Upload run report (always)
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: run-report-${{ github.run_id }}
          path: runs/*/report.json
      - name: Fail workflow on publish block
        if: ${{ steps.daily.outputs.eval_gate_status == 'BLOCKED' }}
        run: exit 1
```

---

## Appendix D — Reference Consumer Example

A minimal downstream-consumer starting point, shipped in `examples/consumer/`:

```python
# examples/consumer/fetch_and_query.py
"""
Minimal reference consumer. Fetches the published graph from a local path or
HTTP URL, validates against the schema, and answers a basic query.
Copy-paste as the starting point for a downstream agent-team repo.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
import httpx
import jsonschema
import networkx as nx


def fetch(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("", "file"):
        return Path(parsed.path or uri).read_bytes()
    elif parsed.scheme in ("http", "https"):
        r = httpx.get(uri, timeout=30.0)
        r.raise_for_status()
        return r.content
    raise ValueError(f"Unsupported URI scheme: {parsed.scheme}")


def load_graph(graph_uri: str, schema_uri: str) -> nx.MultiDiGraph:
    schema = json.loads(fetch(schema_uri))
    graph_doc = json.loads(fetch(graph_uri))
    jsonschema.validate(graph_doc, schema)  # raises on invalid

    g = nx.MultiDiGraph()
    for node in graph_doc["nodes"]:
        g.add_node(node["id"], **node.get("properties", {}), _type=node["type"])
    for edge in graph_doc["edges"]:
        g.add_edge(edge["source"], edge["target"],
                   key=edge["id"], **edge.get("properties", {}),
                   _type=edge["type"])
    return g


def neighbors_of(g: nx.MultiDiGraph, entity_name: str) -> list[str]:
    # Find node by name property
    matches = [n for n, d in g.nodes(data=True) if d.get("name") == entity_name]
    if not matches:
        return []
    return list(g.neighbors(matches[0]))


if __name__ == "__main__":
    # Example invocation:
    #   python fetch_and_query.py https://user.github.io/graph-rag-artifacts/graph.json \
    #                             https://user.github.io/graph-rag-artifacts/schemas/graph-v1.schema.json \
    #                             "Business Capability"
    graph_uri, schema_uri, query = sys.argv[1], sys.argv[2], sys.argv[3]
    g = load_graph(graph_uri, schema_uri)
    print(f"Loaded graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")
    print(f"Neighbors of '{query}': {neighbors_of(g, query)}")
```

The multi-graph variant (`examples/consumer/multi_graph_merge.py`) takes a list of `graph_uri` values, loads each, and unions them into a single NetworkX graph with entity deduplication by `(name, type)`.

---

**End of SPEC.md**
