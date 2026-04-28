# Choosing an LLM Backend

The extractor delegates to a pluggable :class:`LLMBackend`. This document is the cheat-sheet for picking one. The pipeline is the same regardless — the differences are quality, cost, latency, and what you need on your machine to make it run.

## At a glance

| Backend | Models | Setup | Quality | Cost / 5k-doc run | Notes |
|---|---|---|---|---|---|
| `anthropic` | `claude-sonnet-4-7` (default), `claude-haiku-4-5`, etc. | `ANTHROPIC_API_KEY` (~$5 prepay) | **best** | ~$10–50 | Default. Prompt caching halves repeated runs. |
| `openai` (OpenAI) | `gpt-4o`, `gpt-4.1`, `o3-mini`, ... | `OPENAI_API_KEY` | very good | ~$15–60 (gpt-4o) | Function calling proven; cache stats often hidden. |
| `openai` (Ollama) | `llama3.1:70b`, `qwen2.5:32b`, ... | `make up-ollama` (local) | varies sharply | $0 | Tool support model-dependent; quality drop on smaller models. |
| `openai` (OpenRouter) | `anthropic/claude-sonnet-4-7`, `openai/gpt-4o`, hundreds more | `OPENROUTER_API_KEY` | matches model | OpenRouter pricing | Best path if you have OpenRouter credits but no direct Anthropic/OpenAI account. |
| `mock` | (none) | (none) | (test-only) | $0 | Replays canned responses. Used by unit tests and demos. |

## Picking one

**Default to `anthropic`** if you can. Sonnet 4.7 is the model the extraction prompt v0 was designed around — it follows the conservative provenance calibration rules the closest, and ephemeral system-prompt caching makes batch ingest cost-effective.

**Use `openai` against OpenAI** when you have an OpenAI API key but not an Anthropic one. `gpt-4o` is roughly competitive on extraction quality; expect slightly more aggressive INFERRED tagging — manually inspect the first run's `flagged[]` list.

**Use `openai` against OpenRouter** when you want Sonnet quality but only have OpenRouter credits (e.g., from a Claude.ai-adjacent integration). Set `--base-url https://openrouter.ai/api/v1` and `--model anthropic/claude-sonnet-4-7`. OpenRouter does not pass through Anthropic's prompt-caching semantics, so cost will be ~2× a direct Anthropic call, but the resulting graph is identical.

**Use `openai` against Ollama** when you want zero-cost local extraction. Caveats:
- Tool/function-calling support is model-dependent. Currently good: `llama3.1:70b`, `qwen2.5-coder:32b`, `mistral-large`. Weak: most 7B-class models.
- Quality degrades visibly. Conservative provenance calibration is harder for smaller models — expect more `INFERRED` tags being mis-tagged as `EXTRACTED`. The hallucination metrics (`evidence_grounding_rate`) will catch the worst cases.
- You need ~64GB RAM for a useful model and a beefy GPU for tolerable latency.
- Cost reporting will show `$0` (the backend has no pricing knowledge for local models). Real cost is your hardware.

## Concrete invocations

### Default (Anthropic)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
kg ingest --reference
```

### OpenAI (`gpt-4o`)

```bash
export OPENAI_API_KEY=sk-...
kg ingest --reference --backend openai --model gpt-4o
```

### Ollama (local, free)

```bash
# In a separate shell:
ollama serve
ollama pull qwen2.5-coder:32b      # or llama3.1:70b — make sure your model supports tools

kg ingest --reference \
  --backend openai \
  --model qwen2.5-coder:32b \
  --base-url http://localhost:11434/v1
```

The `OPENAI_API_KEY` is required by the SDK but ignored by Ollama — the extractor sends a placeholder. No real key needed.

### OpenRouter (any model on the internet)

```bash
export OPENAI_API_KEY=sk-or-v1-...     # OpenRouter key
kg ingest --reference \
  --backend openai \
  --model anthropic/claude-sonnet-4-7 \
  --base-url https://openrouter.ai/api/v1 \
  --api-key-env OPENAI_API_KEY
```

### Custom env var name

```bash
export MY_KEY=...
kg ingest --reference --backend openai --api-key-env MY_KEY
```

## What the prompt expects

[`docs/extraction-prompt.md`](extraction-prompt.md) documents the prompt v0 design. It is **backend-agnostic**: same prompt, same tool definition, same validation rules. The backend's only job is to make the model emit one call to `record_extractions` with the schema-validated input. If a backend can do that reliably, the rest of the pipeline doesn't care which one it was.

Failure modes that show up backend-by-backend:

- **Anthropic refuses to call the tool**: rare; usually a temporary outage. Tenacity retries.
- **OpenAI returns malformed JSON arguments**: very rare with `gpt-4o+`; the extractor's JSON parse + Pydantic validation catches and triggers a retry.
- **Ollama returns text instead of a tool call**: common with weaker models. Pick a model with proven tool support; if it persists, try a larger one or switch backend.

The extractor surfaces all of these as `BackendError` and retries with exponential backoff. Repeated failures across `max_retries` (default 4) raise `ExtractorError`, which the pipeline propagates as a non-zero exit.

## Pricing-table maintenance

Each backend has a small built-in pricing table. When prices change:

- `src/knowledge_graph/extractor/backends/anthropic.py`: `_PRICE_PER_M_*_USD` constants.
- `src/knowledge_graph/extractor/backends/openai_compat.py`: `_PRICING_USD_PER_M` dict. Add a new entry for any model you're using whose price isn't there yet. Unknown models report `$0` (treat as "unknown", not "free") — adding the entry gives you accurate cost reports.

OpenRouter prices vary per model and aren't tracked by us; if you're using OpenRouter for cost tracking, treat the per-run cost reported by the framework as a lower bound and check OpenRouter's dashboard for the authoritative number.

## Related

- [`docs/extraction-prompt.md`](extraction-prompt.md) — prompt v0 design + change-control rules
- [`docs/architecture.md`](architecture.md) — pipeline overview
- `src/knowledge_graph/extractor/backends/` — backend implementations
- `src/knowledge_graph/extractor/extractor.py` — the orchestrator that consumes any backend
