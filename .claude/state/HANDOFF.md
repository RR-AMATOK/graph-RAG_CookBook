# Session Handoff

<!-- This file is OVERWRITTEN each session. It captures current state only. -->
<!-- The last active agent updates this at the end of every session. -->
<!-- The first agent in the next session reads this first. -->

**Last Updated:** 2026-04-28
**Last Active Agent:** @ai-product-owner (Sprint 2 closeout — code complete, awaiting end-to-end run)
**Current Branch:** `sprint-2/extraction-pipeline` (off `main`)

## Sprint 2 — Extraction Pipeline (code complete)

The single end-to-end goal of Sprint 2 — *ingest the BBT reference corpus into FalkorDB with eval gating* — is **code-complete and unit-tested with 89/89 tests passing**. End-to-end run against live Anthropic API + the actual fetched BBT corpus is the only remaining step before merge, and it requires the user's `ANTHROPIC_API_KEY`.

## Code Delivered

| Component | Module | Tests |
|---|---|---|
| Canonicalizer (FR-2) | `src/knowledge_graph/canonicalizer/{paths,schema,canonicalizer}.py` | 19 |
| Chunker (FR-3.1) | `src/knowledge_graph/chunker/{tokens,chunker}.py` | 14 |
| Extractor v0 (FR-3.2..3.5) | `src/knowledge_graph/extractor/{prompts,schemas,cache,dedup,extractor}.py` + `config/extraction_prompts/v0.txt` | 8 |
| Graph builder (FR-4) | `src/knowledge_graph/graph/{ids,client,schema,builder}.py` | 4 |
| Hallucination metrics (TODO-110.a + .c) | `evals/harness/hallucination.py` | 8 |
| Pipeline orchestrator | `src/knowledge_graph/pipeline.py` | (covered by component tests) |
| `kg ingest` CLI | `src/knowledge_graph/cli.py` | (smoke via `kg --help`) |
| Sprint 1 carry-over (smoke + harness) | `tests/test_smoke.py`, `evals/harness/test_{gates,metrics}.py` | 36 |

**Total: 89 tests passing on Python 3.13. Mypy strict clean. Ruff clean. CLI bootable.**

## Verification (this session)

| # | Check | Status |
|---|---|---|
| 1 | `make install` succeeds | ✅ |
| 2 | `make lint` clean | ✅ |
| 3 | `make typecheck` clean (mypy strict on 46 files) | ✅ |
| 4 | `make test` — 89/89 pass | ✅ |
| 5 | `kg --help` / `kg version` / `kg info` work | ✅ |
| 6 | Local stack up (FalkorDB on `:6390`, Qdrant on `:6333`) | ✅ |
| 7 | CI green on push (will trigger when branch is pushed) | ⏳ |
| 8 | End-to-end run on BBT corpus | ⛔ requires `ANTHROPIC_API_KEY` + corpus fetch (next step, user) |

## Deliberately Out of Scope (Sprint 3+)

- TODO-105 vector indexer (Qdrant emit) — only matters when retrieval ships in consumer repo
- TODO-106 Obsidian vault emitter — human UI, not on critical path for graph artifact
- TODO-110.b calibration ECE — needs ≥50 golden entries to be meaningful
- TODO-110.d LLM-as-judge faithfulness — Sprint 4+
- FR-4.7 re-ingest delete/recreate — Sprint 3
- FR-1.6 manifest SQLite — Sprint 3
- FR-1.4 image handling — Sprint 3
- Multi-format export, MCP server, scrapers, scheduling — Sprint 3+

## Next Steps (in order)

1. **User action:** populate the BBT reference corpus
   ```bash
   pip install -e ".[fetch]"
   python scripts/fetch_reference_corpus.py
   ```
2. **User action:** end-to-end run
   ```bash
   export ANTHROPIC_API_KEY=...
   make up   # if not still running
   kg ingest --reference
   ```
   Expected: ~13 docs canonicalized, ~30–60 chunks extracted, entities + edges in FalkorDB, run report at `runs/<timestamp>/report.json`.
3. Inspect the run report; confirm `evidence_grounding_rate` ≥ 0.85 and `predicate_type_ok_rate` ≥ 0.95 (rough sanity).
4. Optional: hand-author 10–20 BBT golden entries (TODO-008/108) for harness warmup-mode → calibration.
5. Push branch + open PR `sprint-2/extraction-pipeline → main`.
6. Merge after CI green.

## Notes

- Default branch: `main`. Feature branch: `sprint-2/extraction-pipeline`.
- Venv: `.venv.nosync/` (iCloud `UF_HIDDEN` workaround).
- FalkorDB host port: `6390`. Container internally on 6379.
- No `Co-Authored-By: Claude` trailer on commits.
- Prompt v0 is the first production-target prompt — every change requires `PROMPT_VERSION` bump (mandatory rule #8). See [`docs/extraction-prompt.md`](../docs/extraction-prompt.md).
- `evals/` is now a runtime package (shipped in the wheel) because the pipeline imports the hallucination scorer.
