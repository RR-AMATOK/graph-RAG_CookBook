# Session Handoff

<!-- This file is OVERWRITTEN each session. It captures current state only. -->
<!-- The last active agent updates this at the end of every session. -->
<!-- The first agent in the next session reads this first. -->

**Last Updated:** 2026-04-26
**Last Active Agent:** @ai-product-owner (Sprint 1 closeout)
**Current Branch:** `sprint-1/scaffolding` (off `main`)

## Completed This Session

- SPEC.md v1.1 reviewed end-to-end; Sprint 1 plan written and approved (`/Users/ramos/.claude/plans/zippy-wiggling-rabin.md`).
- Feature branch `sprint-1/scaffolding` created.
- `.gitignore` rewritten — now tracks `SPEC.md`, `CLAUDE.md`, `.claude/`; properly ignores Python/build artifacts; globally ignores `.DS_Store`.
- `examples/.DS_Store` untracked.
- `.claude/state/{DECISIONS,MEMORY,TODOS,HANDOFF}.md` populated. SPEC seed entries DEC-001..008 + Sprint 1 decisions DEC-009..012 recorded.
- Project-root `CLAUDE.md` filled from SPEC v1.1 (zero `[placeholder]` strings).
- Python project scaffolding: `pyproject.toml`, `Makefile`, `docker-compose.yml`, `.python-version`, full `src/knowledge_graph/` package layout per SPEC §6.2.
- Eval harness skeleton: `evals/{thresholds.yaml, golden_set.jsonl, history.jsonl, README.md}` + `evals/harness/{runner,metrics,gates,types}.py` + 32 unit tests.
- Schema + consumer reference: `schemas/graph-v1.schema.json`, `examples/consumer/{fetch_and_query.py, fixture-graph.json, README.md}`.
- CI workflow: `.github/workflows/ci.yml` (lint + typecheck + test + consumer-smoke). Floating-tag actions noted for Sprint 3 SHA-pinning.
- Docs: `docs/{architecture.md, consumer-guide.md, security-checklist-sprint2.md}`. README cross-links updated and skills section corrected per DEC-012.
- **macOS iCloud Drive `UF_HIDDEN` gotcha discovered and fixed.** Venv lives at `.venv.nosync/` (excluded from iCloud sync) — see MEMORY.md.

## Verification Status (acceptance checks from plan)

| # | Check | Status |
|---|---|---|
| 1 | `make install` succeeds | ✅ |
| 2 | `make lint` clean | ✅ |
| 3 | `make typecheck` clean (mypy strict) | ✅ |
| 4 | `make test` — 36/36 pass | ✅ |
| 5 | `python examples/consumer/fetch_and_query.py` validates fixture, prints expected output | ✅ |
| 6 | `python -m evals.harness.runner` reports `warmup_bypass` (n=0 entries) | ✅ |
| 7 | `kg version` / `kg info` CLI works | ✅ |
| 8 | CLAUDE.md filled (zero `[placeholder]` strings) | ✅ |
| 9 | DEC-001..012 recorded in `.claude/state/DECISIONS.md` | ✅ |
| 10 | Branch-only confirmed (working on `sprint-1/scaffolding`, not `main`) | ✅ |
| 11 | `.github/workflows/ci.yml` runs green on the feature branch | ⏳ runs on push |
| 12 | `docker-compose up` brings FalkorDB + Qdrant up cleanly | ✅ FalkorDB on `localhost:6390` (PONG), Qdrant on `localhost:6333` (healthz). Host port 6390 used to avoid conflict with another local Redis on 6379. |
| 13 | ≥10 BBT golden entries in `evals/golden_set.jsonl` | ⛔ requires user authoring (TODO-008) |

## In Progress

(none — Sprint 1 work is verified locally; awaiting user decision on commit/PR)

## Blocked

- TODO-008 (BBT golden entries) — needs user hand-authoring against the BBT reference corpus. Harness operates in warmup mode until ≥50 entries exist.

## Next Steps (in order)

1. **User decides commit cadence.** Recommended: 4–5 logical commits on `sprint-1/scaffolding`, then open PR `sprint-1/scaffolding → main`.
2. Verify CI passes on push.
3. User hand-authors 10–20 BBT golden entries (TODO-008) — can land in same PR or a follow-up.
4. Merge to `main` once review passes.
5. Sprint 2 kickoff: extraction prompt v0 (TODO-103, @prompt-engineer lead) + canonicalizer (TODO-101).

## Notes

- **Default branch is `main`** (renamed from `Diagrams` on 2026-04-27).
- **No `Co-Authored-By: Claude` trailer** on commits (global user rule).
- Harness is in warmup mode; first 3 publishes will be effectively ungated per SPEC §12.6.
- `.venv.nosync/` is the venv path on macOS+iCloud (Makefile default). On Linux/CI the suffix is harmless.
- Floating-tag GitHub Actions in `ci.yml` should be SHA-pinned before any publish workflow lands (tracked in `docs/security-checklist-sprint2.md`).
- Two follow-up README polish items observed but not scoped into Sprint 1: `docs/getting-started.md` and `docs/publishing.md` are linked but don't exist (Sprint 2/3 deliverables).
