# Project Memory

<!-- Agents append learnings here. Do not delete entries — only correct errors. -->
<!-- Format: - [YYYY-MM-DD] <concise learning> -->
<!-- Max 200 lines. Consolidate older entries when approaching the limit. -->

## Codebase Patterns

- [2026-04-20] Canonical path format: `<repo>/<hierarchy-segments>/<leaf>`. Repo A uses `__` delimiters in original filenames; Repo B uses real folders. Canonicalizer unifies both.
- [2026-04-20] Every `.md` file MUST have frontmatter matching SPEC §7.1. Files without required fields are rejected by the canonicalizer.
- [2026-04-26] **Two-repo decoupled architecture (DEC-004).** This repo = upstream graph builder + publisher. Consumer repo (separate, future) = agents that fetch the published graph. Never add agent/chat/runtime code here.
- [2026-04-26] Default branch is `main`. All work goes through feature branches `sprint-N/<scope>` or `fix/<scope>` and lands via PR. (Branch was renamed from `Diagrams` → `main` on 2026-04-27.)

## Gotchas & Pitfalls

- [2026-04-20] Obsidian 1.9 requires plural, list-valued YAML keys (`tags:`, `aliases:`, `cssclasses:`). Singular/scalar forms break.
- [2026-04-20] FalkorDB is Redis-based — watch memory config in docker-compose.
- [2026-04-20] Claude API JSON mode occasionally returns trailing commas — parse defensively with `json-repair` as fallback.
- [2026-04-26] **Never add a `Co-Authored-By: Claude` trailer** to any commit (global user rule). Even when default tooling suggests it, omit the trailer.
- [2026-04-26] **iCloud Drive UF_HIDDEN gotcha (macOS).** This repo lives in `~/Library/Mobile Documents/com~apple~CloudDocs/...`. iCloud sets the `UF_HIDDEN` flag on synced files; Python 3.13's `site.py` silently skips hidden `.pth` files, breaking editable installs (`pip install -e .` succeeds but `import knowledge_graph` fails). **Fix:** the venv lives at `.venv.nosync/` — iCloud's `.nosync` suffix excludes the directory from sync entirely, so `UF_HIDDEN` is never set on the venv files. `chflags -R nohidden .venv` is a temporary workaround but iCloud re-applies the flag on every sync, so it's not durable.

## Dependencies & Tools

- [2026-04-20] Graph DB: FalkorDB primary; Neo4j Community fallback. Never use Kùzu (archived Oct 2025).
- [2026-04-27] **FalkorDB host port is 6390**, not the Redis default 6379. Reason: another project (`athra-redis`) on this machine already binds 6379. docker-compose maps host 6390 → container 6379. Connect via `redis://localhost:6390`.
- [2026-04-20] Vector DB: Qdrant. Chunk IDs are deterministic (hash of `doc_id + offset + text`).
- [2026-04-20] Extraction LLM: Claude Sonnet 4.5/4.7. Categorization LLM: Claude Haiku 4.5. Embeddings: Voyage-3 (primary) or `text-embedding-3-large` (fallback).
- [2026-04-26] Orchestration v1: Make targets + GitHub Actions only. Dagster deferred to v2 (DEC-009).

## Performance Notes

- [2026-04-20] Extraction is the bottleneck. Batch chunks within a single LLM call up to ~6k output tokens; anything above that fragments.
- [2026-04-20] Steady-state cost ceiling: $50/month. One-off ingestion ceiling: $150 (G9). Per-doc cost > $0.05 blocks publish (DEC-007).

## Testing Notes

- [2026-04-26] Eval gate runs against the BBT reference corpus, not the production corpus (DEC-010). BBT is the canonical regression detector for CI; production deployments derive their own golden set.
- [2026-04-26] Harness operates in **warmup mode** until ≥50 golden entries exist (DEC-011). Warmup mode logs metrics but does not block publish; first 3 publishes are effectively ungated per SPEC §12.6.

## Conventions & Mandatory Rules

- **Branch-only development** — never commit to default branch. Every change goes through a feature branch + PR (project rule, reiterated 2026-04-26).
- **Eval set first** — evaluation harness ships before any extraction prompt iteration.
- **`@technical-writer` invoked every sprint** — documentation is not optional.
- **Lessons-learned curation** — sprint close feeds `LESSONS-LEARNED.md`.
- **Prompt versioning** — all production prompts have a `prompt_version` field, treated like code.
- **No `Co-Authored-By: Claude` trailer** on commits (global user rule).
