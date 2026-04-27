# Decision Log

<!-- Append-only. To reverse a decision, add a new entry that supersedes the old one. -->
<!-- Format: DEC-NNN sequential. Status: Active / Superseded by DEC-XXX / Deprecated -->

## DEC-001 — Build custom, do not adopt graphify/LightRAG/GraphRAG
- **Date:** 2026-04-20
- **Status:** Active
- **Decided by:** @architect
- **Context:** Requirements include hierarchical filename parsing, two-repo merge with image handling, upstream staleness checks against external docs, tight Claude Code MCP integration, and Playwright extraction layer.
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
- **Re-confirmed 2026-04-26 (Sprint 1 kickoff):** README v1 commits to FalkorDB; SPEC §6.2 hedge resolved in favor of this DEC.

## DEC-003 — Obsidian as secondary human UI only
- **Date:** 2026-04-20
- **Status:** Active
- **Decided by:** @architect, @product-owner
- **Context:** Primary consumer is Claude Code via MCP. Humans want a way to browse.
- **Decision:** Emit an Obsidian vault as a derived artifact. Vault is read-only from the user's perspective; any edits are NOT fed back into the graph (one-way).
- **Alternatives:**
  - Build a web UI — rejected, out of scope (NG3).
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
- **Decision:** Use a **dedicated artifacts repo** (e.g., `<owner>/graph-rag-artifacts`). Framework repo stays focused on code; artifacts repo stays focused on data.
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
- **Decision:** Ship `evals/thresholds.yaml` with defaults. User edits the file to tune per project.
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

---

## DEC-009 — Dagster orchestration deferred to v2
- **Date:** 2026-04-26
- **Status:** Active
- **Decided by:** @ai-product-owner (Sprint 1 kickoff)
- **Context:** SPEC §8 lists Dagster as the production orchestrator alongside cron and GitHub Actions. Three equivalent schedulers in v1 means triplicate maintenance and integration testing.
- **Decision:** v1 ships with Make targets + GitHub Actions only. Dagster integration deferred to v2 if a real workflow demands it (e.g., cross-asset freshness policies, multi-tenant scheduling).
- **Alternatives:**
  - Build all three orchestration paths from v1 — matches SPEC §10 as written but inflates Sprint 2/3 surface area.
  - Drop GitHub Actions and rely on cron only — too local; loses the cloud/CI scheduling story.
- **Trade-offs:** No asset-graph view in v1. Cron + GH Actions cover scheduled runs adequately for the stated scale (1k–10k docs, daily cadence).

## DEC-010 — Dual-corpus strategy: BBT reference for evals, real corpus for production
- **Date:** 2026-04-26
- **Status:** Active
- **Decided by:** @ai-product-owner (Sprint 1 kickoff)
- **Context:** Eval harness needs a reproducible, public corpus that ships with the framework so the publish gate is self-testable on any clone. Real-world deployments need a separate target corpus.
- **Decision:** `examples/reference-corpus/` (Big Bang Theory Wikipedia bundle) drives evals + CI publish gate. A real internal corpus (e.g., LeanIX docs as referenced in SPEC examples) is a separate deployment target with its own golden set.
- **Alternatives:**
  - BBT only — limits real-world signal, but cleanest CI story.
  - Real internal corpus only — private data complicates open-source distribution and CI.
- **Trade-offs:** Two golden sets to maintain. BBT golden set is the canonical regression detector; production deployments derive their own.

## DEC-011 — Golden set v0 = 10–20 hand-authored BBT entries; production target ≥50 deferred
- **Date:** 2026-04-26
- **Status:** Active
- **Decided by:** @ai-product-owner (Sprint 1 kickoff), user authoring
- **Context:** SPEC §12 / SC2 calls for ≥50 golden entries. Authoring 50 entries by hand is multi-day work. Sprint 1 needs *some* golden data to validate harness wiring without blocking on full set.
- **Decision:** Sprint 1 ships a 10–20 entry seed set, hand-authored by user from BBT corpus. Harness operates in **warmup mode** until the production set (≥50) is authored. Warmup mode logs metrics but does not block publish.
- **Alternatives:**
  - LLM-generated golden set with manual review — faster but risks circularity (the LLM judges itself).
  - Defer all golden authoring to Sprint 2 — harness can't be exercised end-to-end in Sprint 1 demo.
- **Trade-offs:** First 3 publishes are effectively un-gated (per SPEC §12.6 variance). Harness self-tests on synthetic inputs to compensate.

## DEC-012 — install.sh removed; skills bundle out of scope for this repo
- **Date:** 2026-04-26
- **Status:** Active
- **Decided by:** user
- **Context:** Original `install.sh` (committed earlier) expected a `./skills/` source dir to bundle and install into `~/.claude/skills/`. User has skills installed globally and removed `install.sh` to eliminate the dangling dependency.
- **Decision:** This repo does not author or distribute Claude Code skills. The `graph-rag-skills` bundle described in SPEC §10.2 is a *consumer* of installed skills, not a producer. Skills referenced (`obsidian-vault-emission`, `graph-artifact-publishing`, `playwright-documentation-scraping`, `knowledge-graph-construction`, `rag-evaluation`) live in the user's global `~/.claude/skills/` already.
- **Alternatives:**
  - Re-author `install.sh` to fetch skills from a sibling location — adds installer complexity for no gain.
  - Bundle skills inside this repo — duplicates files that exist globally.
- **Trade-offs:** Anyone cloning this repo who does not already have the skills installed will need to install them separately. Document this in `CONTRIBUTING.md` when developer onboarding is written.
