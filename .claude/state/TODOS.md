# Task Tracker

<!-- @ai-product-owner creates tasks. All agents update status. -->
<!-- IDs: TODO-NNN sequential. Status: Backlog → In Progress → In Review → Done / Blocked -->
<!-- Move completed tasks to Done section — don't delete. -->

## Active (Sprint 1 — Scaffolding)

### TODO-001 — Populate state files (DECISIONS, MEMORY, TODOS, HANDOFF)
- **Assigned to:** @ai-product-owner
- **Priority:** Critical
- **Status:** In Progress
- **Depends on:** none
- **Acceptance:** DEC-001..012 recorded; conventions captured in MEMORY.md; this file populated; HANDOFF.md updated.

### TODO-002 — Fill project-root CLAUDE.md from SPEC v1.1
- **Assigned to:** @ai-product-owner
- **Priority:** Critical
- **Status:** Backlog
- **Depends on:** TODO-001
- **Acceptance:** Zero `[placeholder]` strings remaining; tech stack, system goal, quality bar, cost target match SPEC.

### TODO-003 — Build Python project scaffolding
- **Assigned to:** @backend-developer + @devops-engineer (via @product-owner)
- **Priority:** Critical
- **Status:** Backlog
- **Depends on:** TODO-002
- **Acceptance:** `make install && make lint && make test` succeeds on a fresh checkout; `docker-compose up` brings FalkorDB + Qdrant up cleanly; package layout per SPEC §6.2 in place with `__init__.py` only.

### TODO-004 — Build eval harness skeleton
- **Assigned to:** @eval-engineer
- **Priority:** Critical
- **Status:** Backlog
- **Depends on:** TODO-003
- **Acceptance:** `evals/thresholds.yaml` matches DEC-007 defaults; `evals/harness/` package with runner, metrics (F1, recall@k, MRR, nDCG), gates (regression + warmup-mode); `pytest evals/harness/` green on synthetic inputs.

### TODO-005 — Author graph-v1 schema + consumer reference
- **Assigned to:** @rag-engineer
- **Priority:** High
- **Status:** Backlog
- **Depends on:** TODO-003
- **Acceptance:** `schemas/graph-v1.schema.json` per SPEC §7.4; `examples/consumer/fetch_and_query.py` validates a hand-crafted fixture against the schema and prints expected output.

### TODO-006 — Set up CI workflow (lint + test only)
- **Assigned to:** @devops-engineer
- **Priority:** High
- **Status:** Backlog
- **Depends on:** TODO-003
- **Acceptance:** `.github/workflows/ci.yml` runs lint + type-check + test on push/PR; actions pinned to SHAs; least-privilege permissions; no publish job in Sprint 1.

### TODO-007 — Author docs (architecture, consumer-guide, security checklist)
- **Assigned to:** @technical-writer + @security-auditor (advisory)
- **Priority:** High
- **Status:** Backlog
- **Depends on:** TODO-005
- **Acceptance:** `docs/architecture.md`, `docs/consumer-guide.md`, `docs/security-checklist-sprint2.md` all present and cross-linked from README.

### TODO-008 — Hand-author 10–20 BBT golden entries
- **Assigned to:** user (with agent-provided template)
- **Priority:** High
- **Status:** Backlog
- **Depends on:** TODO-004
- **Acceptance:** `evals/golden_set.jsonl` has ≥10 entries, all schema-valid; agent provides authoring guide in `evals/README.md`.

### TODO-009 — Verify Sprint 1 acceptance + open PR
- **Assigned to:** @ai-product-owner
- **Priority:** Critical
- **Status:** Backlog
- **Depends on:** TODO-001..008
- **Acceptance:** All Sprint 1 verification checks pass; PR `sprint-1/scaffolding → main` opened with descriptive body.

## Backlog (Sprint 2 — Phase 1 Core Pipeline)

### TODO-101 — Implement canonicalizer (FR-2)
- Schema validation, frontmatter normalization, parent wikilink derivation, image resolution.

### TODO-102 — Implement chunker (FR-3.1)
- Header-aware splitting (H2/H3), 1500-token soft cap, 200-token overlap.

### TODO-103 — Implement extractor v0 + prompt versioning (FR-3.2..3.6)
- Claude Sonnet typed prompt, JSON mode, content-hash cache, `prompt_version` field. **Owned by @prompt-engineer.**

### TODO-104 — Implement graph builder (FR-4)
- FalkorDB schema, cross-doc entity resolution (rapidfuzz threshold 90), MENTIONS edge management on re-ingest.

### TODO-105 — Implement vector indexer (FR-5)
- Qdrant collections (chunks, entities), upsert by deterministic chunk_id, cascade delete by doc_id.

### TODO-106 — Implement Obsidian vault emitter (FR-6)
- Use `obsidian-vault-emission` skill. Absolute wikilinks, plural keys, entity pages for ≥2 mentions only.

### TODO-107 — Author extraction prompt v0 + provenance rubric
- EXTRACTED / INFERRED / AMBIGUOUS tagging rules. Versioned. Domain-tuned.

### TODO-108 — Expand golden set to ≥50 entries
- Move from warmup mode to live eval gating.

### TODO-110 — Hallucination metrics suite (faithfulness, calibration, structure)
- **Assigned to:** @eval-engineer + @prompt-engineer
- **Priority:** High — must land before extraction prompt v0 ships any production output.
- **Status:** Backlog
- **Depends on:** TODO-103 (extractor v0), TODO-108 (≥50 golden entries for calibration to be meaningful)
- **Why:** the existing per-edge `confidence` field is the LLM's self-report and is poorly calibrated. We need *measurements* of hallucination, not assertions. Block publish on regression in any of these.
- **Sub-tasks (Sprint 2 scope, cheap):**
  - **TODO-110.a — Evidence grounding rate.** For each extracted fact, verify that source + target entity surface forms appear in the cited `evidence_span`. If "Sheldon WORKS_AT Caltech" cites a span that doesn't mention either, the fact is ungrounded → flag. Pure string/fuzzy matching post-extraction. Add `evidence_grounding_rate` to every run; threshold-gate at e.g. ≥ 0.90.
  - **TODO-110.b — Confidence calibration error (ECE).** Bin facts by self-reported `confidence` (e.g., 0.7–0.8, 0.8–0.9, 0.9–1.0). Compute actual F1 per bin against the golden set. Track `expected_calibration_error` per run; surface a calibration plot in run reports. Catches systemic over/underconfidence.
  - **TODO-110.c — Predicate type-signature check.** Maintain a small `predicate → (subject_type, object_type)` map. Reject structurally invalid edges (e.g., `Person WORKS_AT Concept`) at graph-build. Free, structural, surfaces obvious LLM mistakes the eval set won't catch.
- **Sub-tasks (Sprint 4+ scope, expensive):**
  - **TODO-110.d — LLM-as-judge faithfulness.** Separate Haiku call asks "does evidence X support claim Y?" yes/no per fact. ~1.5× extraction cost. RAGAS-style. Optional / opt-in.
  - **TODO-110.e — Cross-document recurrence.** Entities mentioned in exactly one chunk auto-tagged `AMBIGUOUS`. Cheap; defer to after the main metrics land.
- **Deliverable:** `evals/harness/hallucination.py` module + new `hallucination_risk` block in every `history.jsonl` row + extension to `gates.py` to threshold-block on regression. Update `docs/architecture.md` "publish gate" section.

## Backlog (Sprint 3+ — Publishing, MCP, Scraping, Scheduling)

- TODO-201 — MCP server (FR-7, 5 tools, SPEC §11)
- TODO-202 — Multi-format export (JSON-LD, GraphML; SPEC §7.5–7.6)
- TODO-203 — Storage adapters (Local FS + GitHub artifacts repo; SPEC §6.4)
- TODO-204 — Publishing pipeline + retention pruning (SPEC §6.6, DEC-008)
- TODO-205 — Bootstrap scripts: `setup-artifacts-repo.sh`, `setup-pages.sh`
- TODO-206 — Staleness detection (FR-8, LLM-as-judge optional)
- TODO-207 — Playwright scrapers (FR-9, robots.txt + rate limiting; use `playwright-documentation-scraping` skill)
- TODO-208 — Local + GitHub Actions scheduling (FR-10)
- TODO-209 — End-to-end consumer reference example (`examples/consumer/` agent loop)

## Blocked

(none)

## Done (Current Sprint)

(none yet)
