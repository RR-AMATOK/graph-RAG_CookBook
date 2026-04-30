# Extraction Prompt (v1 current; v0 retained for A/B)

The extractor lives in `src/knowledge_graph/extractor/`. Sprint 2 shipped **prompt v0**, the first production-target prompt; Sprint 2.6 ships **prompt v1**, a tightened revision targeting four specific failure modes observed during the Qwen3-30B-A3B local pilot. Both files coexist (`config/extraction_prompts/v0.txt` and `v1.txt`); `PROMPT_VERSION = "v1"` makes v1 the default. v0 stays loadable via `load_system_prompt("v0")` for A/B comparison runs.

This document captures what each prompt does, why it's shaped the way it is, and the change-control rules.

## v1 changes (Sprint 2.6)

Four targeted edits, all addressing structural model-behavior bugs observed in the v0 pilot — **not** corpus-tuning. Each lever is one we can reason about without a golden set; thresholds and per-corpus phrasing are deliberately left for a later v2 once goldens exist.

1. **PORTRAYS direction lock with worked example.** v0 listed PORTRAYS as a generic predicate. Qwen3 systematically inverted it (`Character → Person` and `Character → Work` violations). v1 adds an explicit "Edge direction (STRICT)" section with PORTRAYS, AUTHORED, FOUNDED_BY, WORKS_AT pinned by direction, plus a worked negative example using a domain-neutral acting scene. Includes the heuristic "write the predicate as a sentence; if it reads as nonsense in English, you have the direction wrong."

2. **Chunk-membership constraint for relationship endpoints.** v0 said "do not invent entities not mentioned in the chunk" but allowed relationships whose endpoints were emitted from outside-knowledge. v1 adds an explicit hard constraint: *"Do not emit a relationship if either endpoint's name (or alias) is absent from the chunk."* Plus a worked negative example showing the temptation (a CEO mentioned generically) and the correct behavior (omit).

3. **Verbatim-citation tightening.** v0 required `evidence_span` to be a verbatim substring; v1 adds *"the evidence_span MUST contain at least one surface form of BOTH endpoints (or one name + an unambiguous pronoun for the other, with the referent established in the immediately preceding text)."* This directly attacks the v0 pilot's `span_grounding=0.45` (the model was citing supporting-but-name-free spans) without breaking the chunk-grounding semantics.

4. **Soft predicate vocabulary lock.** v0 left predicates open-ended; the pilot saw escape-hatch synonyms (`PORTRAYS_CHARACTER_IN`, `HAS_RELATIONSHIP_WITH`, `IS_A_TYPE_OF`). v1 ships a 13-row preferred-predicate table with subject/object types, plus the rule *"only invent a new predicate if none of the above genuinely fit. Do not invent escape-hatch synonyms."* Unknown predicates are still allowed (we want recall on novel domains), but the soft-list reduces vocabulary drift.

What v1 deliberately does NOT change: type vocabulary, provenance-tag rules, conservative extraction stance, domain-specific phrasing (none added; worked examples use domain-neutral scenes). The discipline: every v1 change must read as a stricter restatement of v0's intent.

Expected qualitative impact (no golden set yet — empirical comparison comes when full-corpus runs of both prompts are scored against goldens):
- `span_grounding` should rise from 0.45 toward ~0.80+ (model forced to cite name-containing spans).
- `predicate_type_ok_rate` should rise from 0.955 toward ~0.99 (direction errors and escape-hatch predicates drop).
- `chunk_grounding_rate` should hold at ~0.97.
- Total relationships per chunk may drop slightly (recall trade-off from the chunk-membership constraint).

## Pointer (current = v1)

| Item | Where |
|---|---|
| Prompt body (current) | `config/extraction_prompts/v1.txt` |
| Prompt body (v0, retained for A/B) | `config/extraction_prompts/v0.txt` |
| Loader + version constant | `src/knowledge_graph/extractor/prompts.py` (`PROMPT_VERSION`, `load_system_prompt`) |
| Tool definition | `src/knowledge_graph/extractor/schemas.py` (`record_extractions_tool()`) |
| Output validation | `src/knowledge_graph/extractor/schemas.py` (`Extraction` Pydantic model) |
| Cache | `cache/extraction/` keyed by `hash(prompt_version + chunk_text)` (FR-3.5) |
| Backend implementations | `src/knowledge_graph/extractor/backends/{anthropic,openai_compat,mock}.py` |
| Backend choice guide | [`docs/llm-backends.md`](llm-backends.md) |

## Design intent

- **Backend-agnostic prompt + tool definition.** The same `record_extractions` tool works against Anthropic's tools API and OpenAI's function-calling API — the OpenAI backend translates `{name, description, input_schema}` into `{type: function, function: {name, description, parameters}}` at call time. Switching backends does not require touching the prompt.
- **Force structured output via tool use**, not free-text JSON. Both backends use `tool_choice` to pin the model to one schema-validated call. Free-text JSON regresses on every long output and requires `json-repair` patching — we avoided that path entirely.
- **System prompt cached** (`cache_control: ephemeral` on the system text block). The prompt is ~1.5KB and is reused across every chunk in a corpus run. Without caching, each chunk pays for re-tokenizing the entire prompt; with caching, only the first chunk pays.
- **Conservative provenance calibration.** EXTRACTED requires the chunk to *directly state* the relationship in the cited evidence span. INFERRED requires the span to *support* the inference. AMBIGUOUS is the default for borderline cases. The prompt explicitly says "when in doubt between two tiers, choose the lower" — over-extraction is the most common LLM failure mode in entity extraction and the most harmful downstream.
- **Verbatim evidence spans.** The prompt requires `evidence_span` to be the *exact substring* of the chunk that supports the relationship. This makes the evidence-grounding metric (`evals/harness/hallucination.py`, TODO-110.a) cheap and correct: a fact whose entities don't appear in its cited span is a hallucination.

## Type vocabulary

The prompt locks the model to a small entity-type list:

```
Character, Person, Organization, Location, Event, Concept, Work
```

Predicates are constrained to `UPPER_SNAKE_CASE` matching `^[A-Z][A-Z0-9_]*$`. The prompt does **not** lock the predicate vocabulary — domain-specific predicates emerge organically. The hallucination metric (TODO-110.c, `_DEFAULT_PREDICATE_TYPES` in `hallucination.py`) carries a small set of canonical predicates with type signatures (`WORKS_AT: (Person|Character) → (Organization|Location)`); unknown predicates pass the type check (precision over recall).

## Hard constraints encoded in v0

1. Don't extract pronouns alone — link them to a named entity or skip.
2. Don't extract generic nouns ("a scientist", "the show").
3. Don't invent entities not mentioned in the chunk.
4. Don't generalize beyond the chunk (no outside knowledge of famous entities).
5. EXTRACTED requires literal containment in the evidence span.
6. Every relationship's source/target must also appear in the entities list.
7. If the chunk has no extractable content, return empty arrays — don't pad.

Constraints 1–6 are reflected in both the prompt text and the runtime Pydantic validation, so a model that ignores the prompt can't smuggle bad output past the type system. Constraint 7 is enforced by the prompt only; the schema permits empty arrays.

## Change control

This is the project's **first versioned prompt** (mandatory rule #8 — prompt versioning). The rules:

- Every change to `v0.txt` requires a bump to `PROMPT_VERSION` in `prompts.py`. The cache key is `hash(prompt_version + chunk_text)`, so bumping the version invalidates every cached extraction.
- New versions are added as new files (`v1.txt`, `v2.txt`), not as edits in place — this keeps the diff history of "the prompt that produced graph X" trivially recoverable.
- Each ingest run records `prompt_version` in `runs/<id>/report.json`. When the eval harness gates on regression, it compares runs at the same prompt version (or flags the version change explicitly).
- The prompt-engineering team owns this file. Backend / pipeline changes that don't touch the prompt body don't bump the version.

## What v0 does not do (yet)

- **No few-shot examples.** The prompt is purely instructional. Adding 1–2 worked examples is the highest-leverage v1 change once we have golden-set signal on which extraction patterns are weak.
- **No retrieval augmentation.** The model sees one chunk at a time, with the document's `canonical_path` and `chunk_id` for context. No entity-history-from-prior-chunks, no neighborhood from the existing graph. Both are Sprint 3+ extensions.
- **No domain-specific tuning.** v0 is generic markdown extraction. Per-corpus prompt subclasses (e.g., a LeanIX-tuned variant) would inherit from v0 and add domain examples — Sprint 4+ if domain-specific runs need it.
- **No self-consistency sampling.** v0 makes one call per chunk at default temperature. Sampling 3× and intersecting (TODO-110.d alternative) would catch low-confidence extractions but ~3× the cost; defer until variance becomes a real publish-gate problem.

## Cost expectations

- System prompt: ~400 tokens (cached after first chunk → cheap reads at $0.30/M).
- User message per chunk: chunk text (≤1500 tokens by chunker design) + ~50 tokens of metadata.
- Tool response: typically 200–800 tokens depending on chunk content.

For a 13-doc BBT reference corpus at ~50 chunks total: roughly $0.40–$0.60 in extraction cost on Claude Sonnet 4.7 at 2026-04 prices. Re-runs at the same prompt version hit the local cache — $0.

## Related

- [`SPEC.md` §FR-3](../SPEC.md) — extraction requirements
- [`docs/architecture.md`](architecture.md) — pipeline data flow
- [`evals/README.md`](../evals/README.md) — golden set authoring conventions (calibration target)
- [`evals/harness/hallucination.py`](../evals/harness/hallucination.py) — evidence-grounding + predicate-type-signature metrics
- [`.claude/state/TODOS.md`](../.claude/state/TODOS.md) — TODO-110 hallucination metrics suite
