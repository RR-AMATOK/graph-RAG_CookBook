"""CLI entry point: ``kg`` command.

Subcommands implemented:
- ``kg version`` — print package version
- ``kg info`` — project status overview
- ``kg ingest`` — Sprint 2: canonicalize → chunk → extract → write graph

Subcommands stubbed for later sprints:
- ``kg update``       — incremental refresh from changed source files
- ``kg scrape``       — Playwright dynamic source extraction
- ``kg check-staleness`` — detect outdated docs against upstream
- ``kg emit-vault``   — write Obsidian vault from current graph
- ``kg serve-mcp``    — start the local MCP server for Claude Code
- ``kg eval``         — run the eval harness against the current extraction
- ``kg export``       — produce multi-format graph artifacts
- ``kg publish``      — publish artifacts to configured storage backend
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer

from knowledge_graph import __version__
from knowledge_graph.extractor import ExtractorSettings
from knowledge_graph.pipeline import IngestSettings, ingest_corpus

app = typer.Typer(
    name="kg",
    help="graph-RAG_CookBook — knowledge-graph builder + publisher.",
    no_args_is_help=True,
    add_completion=False,
)

# typer.Option singletons hoisted out of function defaults to satisfy ruff B008.
_OPT_FLAT_DIR = typer.Option(
    None, "--flat-dir", help="Source directory with flat (__-delimited) markdown files."
)
_OPT_NESTED_DIR = typer.Option(
    None, "--nested-dir", help="Source directory with folder-based markdown files."
)
_OPT_FLAT_REPO = typer.Option("corpus-a", help="Logical repo identifier for the flat corpus.")
_OPT_NESTED_REPO = typer.Option("corpus-b", help="Logical repo identifier for the nested corpus.")
_OPT_CORPUS_OUT = typer.Option(Path("corpus"), help="Where to write canonicalized .md files.")
_OPT_RUNS_DIR = typer.Option(Path("runs"), help="Where to write the run report.")
_OPT_CACHE_DIR = typer.Option(
    Path("cache/extraction"), help="Per-prompt-version extraction cache directory."
)
_OPT_REFERENCE = typer.Option(
    False,
    "--reference",
    help=(
        "Shortcut: ingest examples/reference-corpus/{flat,nested}/ "
        "instead of supplying --flat-dir / --nested-dir."
    ),
)
_OPT_LOG_LEVEL = typer.Option("INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR).")
_OPT_BACKEND = typer.Option(
    "anthropic",
    "--backend",
    help=(
        "LLM backend. 'anthropic' (default) uses ANTHROPIC_API_KEY. "
        "'openai' uses OPENAI_API_KEY against api.openai.com, OR an Ollama "
        "server at --base-url http://localhost:11434/v1, OR OpenRouter at "
        "--base-url https://openrouter.ai/api/v1."
    ),
)
_OPT_MODEL = typer.Option(
    None,
    "--model",
    help="Override the default model. Defaults: claude-sonnet-4-7 (anthropic), gpt-4o (openai).",
)
_OPT_BASE_URL = typer.Option(
    None,
    "--base-url",
    help="Override the OpenAI-compatible base URL (only used by --backend openai).",
)
_OPT_API_KEY_ENV = typer.Option(
    None,
    "--api-key-env",
    help="Override the env var name for the API key. Defaults: ANTHROPIC_API_KEY / OPENAI_API_KEY.",
)
_OPT_NUM_CTX = typer.Option(
    None,
    "--num-ctx",
    help=(
        "Ollama context-window override (forwarded as `options.num_ctx` "
        "via extra_body). Ollama's default 4096 is too small for our "
        "system prompt + tool schema + 1500-token chunk; use 8192+ for "
        "reliable tool calls. Only takes effect with --backend openai and "
        "a custom --base-url. Ignored by OpenAI proper."
    ),
)
_OPT_COMPARE_PROMPTS = typer.Option(
    "v0,v1",
    "--compare-prompts",
    help=(
        "Comma-separated baseline,candidate prompt versions to A/B compare. "
        "Each version corresponds to a file at config/extraction_prompts/<v>.txt. "
        "The candidate's metrics are diffed against the baseline's; if "
        "regression thresholds are exceeded, exit code is non-zero."
    ),
)
_OPT_GOLDENS = typer.Option(
    Path("evals/golden_set.jsonl"),
    "--goldens",
    help=(
        "Path to golden_set.jsonl. When non-empty, enables reference-based "
        "metrics (entity F1, per-type F1, coverage, relationship F1). "
        "When the file is empty / missing, the comparison falls back to "
        "structural metrics only (chunk_grounding, span_grounding, etc.)."
    ),
)


@app.command()
def version() -> None:
    """Print the installed package version."""
    typer.echo(__version__)


@app.command()
def info() -> None:
    """Show project info and component status."""
    typer.echo("graph-RAG_CookBook")
    typer.echo(f"  version: {__version__}")
    typer.echo(
        "  status: Sprint 2 — extraction pipeline (canonicalizer + chunker + extractor + graph builder)."
    )
    typer.echo("  see SPEC.md for the roadmap; CLAUDE.md for project rules.")


_DEFAULT_MODEL_PER_BACKEND = {
    "anthropic": "claude-sonnet-4-7",
    "openai": "gpt-4o",
}


@app.command()
def ingest(
    flat_dir: Path | None = _OPT_FLAT_DIR,
    nested_dir: Path | None = _OPT_NESTED_DIR,
    flat_repo: str = _OPT_FLAT_REPO,
    nested_repo: str = _OPT_NESTED_REPO,
    corpus_out: Path = _OPT_CORPUS_OUT,
    runs_dir: Path = _OPT_RUNS_DIR,
    cache_dir: Path = _OPT_CACHE_DIR,
    reference: bool = _OPT_REFERENCE,
    log_level: str = _OPT_LOG_LEVEL,
    backend: str = _OPT_BACKEND,
    model: str | None = _OPT_MODEL,
    base_url: str | None = _OPT_BASE_URL,
    api_key_env: str | None = _OPT_API_KEY_ENV,
    num_ctx: int | None = _OPT_NUM_CTX,
) -> None:
    """Run the canonicalize → chunk → extract → graph pipeline on a markdown corpus.

    Requires a running FalkorDB (``make up``) and an API key for the chosen
    backend (``ANTHROPIC_API_KEY`` for ``--backend anthropic``,
    ``OPENAI_API_KEY`` for ``--backend openai``, or no key needed for a local
    Ollama server at ``--base-url http://localhost:11434/v1``).
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if reference:
        ref_root = Path("examples/reference-corpus")
        flat_dir = flat_dir or (ref_root / "flat")
        nested_dir = nested_dir or (ref_root / "nested")

    if flat_dir is None and nested_dir is None:
        typer.echo(
            "error: must supply --flat-dir, --nested-dir, or --reference",
            err=True,
        )
        raise typer.Exit(code=2)

    chosen_model = model or _DEFAULT_MODEL_PER_BACKEND.get(backend, "claude-sonnet-4-7")
    extractor_settings = ExtractorSettings(
        backend=backend,
        model=chosen_model,
        cache_root=cache_dir,
        base_url=base_url,
        api_key_env=api_key_env,
        num_ctx=num_ctx,
    )
    settings = IngestSettings(
        flat_dir=flat_dir,
        nested_dir=nested_dir,
        flat_repo=flat_repo,
        nested_repo=nested_repo,
        corpus_out=corpus_out,
        runs_dir=runs_dir,
        cache_dir=cache_dir,
        extractor=extractor_settings,
    )
    typer.echo(f"[ingest] backend={backend} model={chosen_model}", err=True)
    report = ingest_corpus(settings=settings)

    typer.echo("")
    typer.echo(f"[ingest:{report.run_id}] complete")
    typer.echo(
        f"  docs={report.docs_canonicalized} (errors={report.docs_failed}) "
        f"chunks={report.chunks_total} extracted={report.chunks_extracted} "
        f"cache_hits={report.chunks_cache_hits}"
    )
    typer.echo(
        f"  entities created={report.entities_created} updated={report.entities_updated}; "
        f"edges created={report.relationships_created} updated={report.relationships_updated}; "
        f"mentions={report.mentions_created}"
    )
    typer.echo(
        f"  tokens in={report.cost_input_tokens} out={report.cost_output_tokens} "
        f"cache_read={report.cost_cache_read_tokens}; cost=${report.cost_usd:.4f}"
    )
    typer.echo(
        f"  hallucination: chunk_grounding={report.chunk_grounding_rate:.3f} "
        f"span_grounding={report.evidence_grounding_rate:.3f} "
        f"predicate_types_ok={report.predicate_type_ok_rate:.3f} "
        f"flagged={report.flagged_count}/{report.n_relationships_scored}"
    )
    typer.echo(f"  report: {runs_dir / report.run_id / 'report.json'}")

    if report.docs_failed > 0 or report.flagged_count > 0:
        # Surface non-zero exit so CI / cron jobs notice flagged extractions
        # without yet enforcing a hard threshold (Sprint 2.5+: gate on rate).
        sys.exit(1)


@app.command(name="eval")
def eval_cmd(
    flat_dir: Path | None = _OPT_FLAT_DIR,
    nested_dir: Path | None = _OPT_NESTED_DIR,
    flat_repo: str = _OPT_FLAT_REPO,
    nested_repo: str = _OPT_NESTED_REPO,
    corpus_out: Path = _OPT_CORPUS_OUT,
    runs_dir: Path = _OPT_RUNS_DIR,
    cache_dir: Path = _OPT_CACHE_DIR,
    reference: bool = _OPT_REFERENCE,
    log_level: str = _OPT_LOG_LEVEL,
    backend: str = _OPT_BACKEND,
    model: str | None = _OPT_MODEL,
    base_url: str | None = _OPT_BASE_URL,
    api_key_env: str | None = _OPT_API_KEY_ENV,
    num_ctx: int | None = _OPT_NUM_CTX,
    compare_prompts: str = _OPT_COMPARE_PROMPTS,
    goldens: Path = _OPT_GOLDENS,
) -> None:
    """A/B-compare two prompt versions on the same corpus.

    Extracts the corpus once at each prompt version (cache-first; bumping
    the version forces a fresh extraction), aggregates per-doc predictions,
    and scores against goldens (when present) plus the existing structural
    metrics. Prints a side-by-side table and writes
    ``runs/<id>/comparison.json``. Exits non-zero on regression.
    """
    from datetime import UTC
    from datetime import datetime as _dt

    from evals.harness.prompt_eval import compare_prompts as _compare
    from evals.harness.prompt_eval import format_comparison

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if reference:
        ref_root = Path("examples/reference-corpus")
        flat_dir = flat_dir or (ref_root / "flat")
        nested_dir = nested_dir or (ref_root / "nested")

    if flat_dir is None and nested_dir is None:
        typer.echo("error: must supply --flat-dir, --nested-dir, or --reference", err=True)
        raise typer.Exit(code=2)

    versions = [v.strip() for v in compare_prompts.split(",") if v.strip()]
    if len(versions) != 2:
        typer.echo(
            f"error: --compare-prompts must be exactly two comma-separated versions; got {versions!r}",
            err=True,
        )
        raise typer.Exit(code=2)
    baseline_version, candidate_version = versions

    chosen_model = model or _DEFAULT_MODEL_PER_BACKEND.get(backend, "claude-sonnet-4-7")
    extractor_settings = ExtractorSettings(
        backend=backend,
        model=chosen_model,
        cache_root=cache_dir,
        base_url=base_url,
        api_key_env=api_key_env,
        num_ctx=num_ctx,
    )
    settings = IngestSettings(
        flat_dir=flat_dir,
        nested_dir=nested_dir,
        flat_repo=flat_repo,
        nested_repo=nested_repo,
        corpus_out=corpus_out,
        runs_dir=runs_dir,
        cache_dir=cache_dir,
        extractor=extractor_settings,
    )
    typer.echo(
        f"[eval] backend={backend} model={chosen_model} "
        f"baseline={baseline_version} candidate={candidate_version}",
        err=True,
    )

    report = _compare(
        baseline_version=baseline_version,
        candidate_version=candidate_version,
        settings=settings,
        goldens_path=goldens,
    )

    typer.echo("")
    typer.echo(format_comparison(report))

    run_id = _dt.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = runs_dir / run_id / "comparison.json"
    report.write_json(out_path)
    typer.echo(f"  comparison: {out_path}")

    # Default regression gates — pragmatic Sprint 2.6 thresholds. Sprint 3+
    # will pull these from evals/thresholds.yaml.
    regressions: list[str] = []
    if report.delta_chunk_grounding < -0.03:
        regressions.append(f"chunk_grounding regressed by {-report.delta_chunk_grounding:.3f}")
    if report.delta_predicate_type_ok < -0.03:
        regressions.append(f"predicate_type_ok regressed by {-report.delta_predicate_type_ok:.3f}")
    if report.delta_entity_f1 is not None and report.delta_entity_f1 < -0.05:
        regressions.append(f"entity_f1 regressed by {-report.delta_entity_f1:.3f}")
    if report.delta_relationship_f1 is not None and report.delta_relationship_f1 < -0.05:
        regressions.append(f"relationship_f1 regressed by {-report.delta_relationship_f1:.3f}")

    if regressions:
        typer.echo("")
        typer.echo(
            f"[eval] candidate {candidate_version} regresses vs {baseline_version}:",
            err=True,
        )
        for r in regressions:
            typer.echo(f"  - {r}", err=True)
        sys.exit(1)


@app.command()
def update() -> None:  # pragma: no cover — Sprint 3+ stub
    """Incremental refresh from changed source files (Sprint 3+)."""
    typer.echo("Not implemented yet — Sprint 3+ deliverable.")
    raise typer.Exit(code=1)


@app.command()
def scrape() -> None:  # pragma: no cover
    """Playwright dynamic source extraction (Sprint 6+)."""
    typer.echo("Not implemented yet — Sprint 6+ deliverable.")
    raise typer.Exit(code=1)


@app.command("check-staleness")
def check_staleness() -> None:  # pragma: no cover
    """Detect outdated docs against upstream (Sprint 5+)."""
    typer.echo("Not implemented yet — Sprint 5+ deliverable.")
    raise typer.Exit(code=1)


@app.command("emit-vault")
def emit_vault() -> None:  # pragma: no cover
    """Write Obsidian vault from current graph (Sprint 3)."""
    typer.echo("Not implemented yet — Sprint 3 deliverable.")
    raise typer.Exit(code=1)


@app.command("serve-mcp")
def serve_mcp() -> None:  # pragma: no cover
    """Start the local MCP server for Claude Code (Sprint 3+)."""
    typer.echo("Not implemented yet — Sprint 3+ deliverable.")
    raise typer.Exit(code=1)


@app.command()
def export() -> None:  # pragma: no cover
    """Produce multi-format graph artifacts (Sprint 3+)."""
    typer.echo("Not implemented yet — Sprint 3+ deliverable.")
    raise typer.Exit(code=1)


@app.command()
def publish() -> None:  # pragma: no cover
    """Publish artifacts to configured storage backend (Sprint 3+)."""
    typer.echo("Not implemented yet — Sprint 3+ deliverable.")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
