# CLAUDE.md

## Project Overview

**graph-RAG_CookBook** — A self-hosted, reusable framework for constructing an LLM-queryable knowledge graph over a corpus of markdown training/documentation files (1k–10k scale). The framework unifies source repositories of differing structures into one canonical form, extracts entities and relationships with an LLM, stores them in a graph database + vector index, emits an Obsidian vault for human browsing, and **publishes a versioned, portable graph artifact** (`graph.json` + JSON-LD + GraphML + meta) to a configurable storage backend (local FS or dedicated GitHub artifacts repo with Pages).

**This repo contains no agent logic.** Consumers — typically agent teams or other knowledge systems in separate downstream repositories — fetch the published graph artifact over HTTP and use it to answer questions. The framework's obligation is a stable, versioned, documented graph contract; consumers handle retrieval strategy, agent orchestration, and user interaction. (See `.claude/state/DECISIONS.md` → DEC-004.)

**Source of truth:** `SPEC.md` v1.1.

## System Goal

- **What it does:** Ingests markdown corpora, extracts entities + typed relationships with provenance tags (EXTRACTED / INFERRED / AMBIGUOUS), and publishes a versioned graph artifact for downstream agent consumption.
- **Quality bar (publish gate, regression-based — DEC-007):**
  - F1 overall drop > 3% blocks publish
  - Coverage < 90% (golden entities found) blocks publish
  - Per-type F1 drop > 5% blocks publish
  - Recall@5 drop > 5% blocks publish
  - Cost per doc > $0.05 blocks publish (cost creep guard)
  - 3-sigma variance required before declaring regression
- **Benchmark target (SC2):** ≥16/20 hand-curated MCP queries answered correctly (80%).
- **Cost target (G9):** ≤ $50/month steady state; ≤ $150 one-off initial ingestion.
- **Latency targets:** SC1 — fresh `make bootstrap && make ingest` < 30 min on 1k docs. SC3 — daily incremental run < 15 min on 5k docs at < 5% churn.

## System Type

This is an unusual hybrid for an "AI engineering" repo — it is the **upstream graph builder + publisher** in a deliberately decoupled two-repo architecture (DEC-004). Conventional RAG happens in a future, separate consumer repo (NG7).

- [x] **Pure prompt** — entity/relationship extraction (Claude Sonnet, JSON output, content-hash cached) is the primary LLM call. High volume, low complexity per call.
- [x] **Optional LLM-as-judge** — staleness material-change detection (FR-8.2.d) and Haiku-based scrape categorization.
- [x] **Offline batch evaluation** — golden-set-driven publish gate (FR-12).
- [ ] RAG runtime — out of scope here; lives in consumer repo.
- [ ] Agent runtime — out of scope here; lives in consumer repo.
- [ ] Multi-agent orchestration — out of scope here; lives in consumer repo.

## Tech Stack

- **LLM Provider:** Anthropic. Claude Sonnet 4.5/4.7 for extraction (FR-3.2). Claude Haiku 4.5 for cheap categorization.
- **Embedding Model:** Voyage-3 (primary) with `text-embedding-3-large` (OpenAI) as documented fallback.
- **Vector Store:** Qdrant (standalone). Deterministic chunk IDs (hash of `doc_id + offset + text`).
- **Graph DB:** FalkorDB (primary, DEC-002). Neo4j Community Edition documented as fallback.
- **Reranker:** None at framework layer — consumer concern.
- **Agent Framework:** None — this repo contains no agents (NG7).
- **Eval Framework:** Custom harness (`evals/harness/`) with regression gates per DEC-007. Golden set in `evals/golden_set.jsonl`.
- **Backend:** Python 3.11+ (CLI: `typer`; config: `pydantic-settings` + YAML; logging: `structlog`).
- **Markdown / parsing:** `mistune` 3.x, `python-frontmatter`, `markdownify` + `beautifulsoup4` (HTML→MD).
- **Graph algorithms:** `networkx` (in-memory), `rustworkx` (heavy ops).
- **Scraping:** `playwright` (Python).
- **Orchestration v1:** Make targets + GitHub Actions. **Dagster deferred to v2** (DEC-009).
- **MCP:** `mcp` Python SDK (FR-7, 5 tools).
- **Observability:** `structlog` JSON logs; `evals/history.jsonl` for metric trends.
- **Testing:** `pytest` + `pytest-asyncio`.

## Agent Team

This project uses the AI engineering agent team. The `default-entry-point` skill routes prompts to `@ai-product-owner` automatically — just run `claude` and prompt naturally. Or invoke specific agents directly:

```
@ai-product-owner   Plan / orchestrate sprints
@rag-engineer       Graph schema, consumer contract, retrieval-side concerns (in consumer repo)
@prompt-engineer    Extraction prompt v0+, prompt versioning, provenance rubric
@eval-engineer      Golden set, harness, thresholds, regression gates
@backend-developer  Pipeline code (canonicalizer, chunker, extractor, emitter, exporter, CLI)
@devops-engineer    Docker compose, CI workflows, GitHub Actions, artifacts repo bootstrap
@security-auditor   Prompt-injection surface, PAT scoping, scraping etiquette, secrets
@technical-writer   SPEC, README, architecture docs, consumer guide, JSON Schema authoring
```

### Agent Pipeline

```
User → AI Product Owner →
       ┌──────────────────────────────┬──────────────────────────────┐
       ↓                              ↓                              ↓
   RAG Engineer                  Prompt Engineer              Eval Engineer
   (schema + consumer contract)  (extraction prompt + tags)   (golden set + gates)
       ↓                              ↓                              ↓
   (cross-team: → @product-owner for backend/CI/infra,
                → @ml-product-owner for any custom training (NG5: not used))
       ↓
   Code Reviewer → QA → Security Auditor → Technical Writer → Done
```

**Deliberately not used:** `@agent-architect` (no agent in this repo, NG7), `@ml-product-owner` (no training, NG5).

## Project State Files

State lives in `.claude/state/`:
- `HANDOFF.md` — Current state + blockers between sessions
- `TODOS.md` — Active task tracker (TODO-001..)
- `MEMORY.md` — Project knowledge (gotchas, conventions, key files)
- `DECISIONS.md` — Design decisions (DEC-001..012 active)
- `CHANGELOG-DEV.md` — Developer change log
- `LESSONS-LEARNED.md` — Cross-project knowledge base

## Skills Applied

Globally installed (per DEC-012, this repo does not bundle skills):
- `default-entry-point` — routes prompts to AI product owner
- `thinking-strategy` — agents self-direct extended thinking
- `project-state` — manages state files
- `code-standards`, `git-workflow`, `security-checklist`, `lessons-learned`
- `obsidian-vault-emission` — vault frontmatter, wikilinks, attachment handling
- `knowledge-graph-construction` — entity extraction, deduplication, provenance
- `rag-evaluation` — golden sets, retrieval metrics, regression gates
- `graph-artifact-publishing` — schemas, storage adapters, retention pruning
- `playwright-documentation-scraping` — robots.txt, rate limiting, sitemap-first

## Mandatory Rules (enforced by AI Product Owner)

1. **Branch-only development** — never commit to default branch (`main`). Every change goes through a feature branch + PR.
2. **No `Co-Authored-By: Claude` trailer** on any commit (global user rule).
3. **Eval set first** — eval harness ships before any extraction prompt iteration.
4. **Documentation is not optional** — `@technical-writer` invoked every sprint.
5. **Lessons-learned curation** — sprint-end review feeds `LESSONS-LEARNED.md`.
6. **Advisory board review** — required for novel architectures or production-bound features.
7. **Error loop escalation** — 3+ same-class failures triggers `@strategist` + `@devils-advocate`.
8. **Prompt versioning** — every production prompt has a `prompt_version` field, treated like code.
9. **Phase gating** — a phase cannot start until the previous phase's exit criteria are met and recorded in `DECISIONS.md` (SPEC §3).

## Key Architectural Constraints

- **No agent logic in this repo** (NG7, DEC-004). If a feature requires agent reasoning, it belongs in the consumer repo.
- **No web UI** (NG3). Obsidian is the human UI; Claude Code via MCP is the local agent UI.
- **No training / fine-tuning** (NG5). Off-the-shelf Claude + embedding API only.
- **Daily cadence is the floor** (NG2). Real-time sync is out of scope.
- **Markdown + images only in v1** (NG6). Code, PDFs, video deferred to v2.
- **Read-only published artifact** (NG9). Consumers cannot mutate the graph.

## Reference Corpus

`examples/reference-corpus/` ships a Big Bang Theory Wikipedia bundle as the canonical eval corpus (DEC-010). All CI publish-gate runs evaluate against this. Real production deployments use their own corpus + golden set.
