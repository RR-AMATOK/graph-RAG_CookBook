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
) -> None:
    """Run the canonicalize → chunk → extract → graph pipeline on a markdown corpus.

    Requires a running FalkorDB (``make up``) and ``ANTHROPIC_API_KEY``
    exported in the environment.
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

    settings = IngestSettings(
        flat_dir=flat_dir,
        nested_dir=nested_dir,
        flat_repo=flat_repo,
        nested_repo=nested_repo,
        corpus_out=corpus_out,
        runs_dir=runs_dir,
        cache_dir=cache_dir,
    )
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
        f"  hallucination: grounding={report.evidence_grounding_rate:.3f} "
        f"predicate_types_ok={report.predicate_type_ok_rate:.3f} "
        f"flagged={report.flagged_count}/{report.n_relationships_scored}"
    )
    typer.echo(f"  report: {runs_dir / report.run_id / 'report.json'}")

    if report.docs_failed > 0 or report.flagged_count > 0:
        # Surface non-zero exit so CI / cron jobs notice flagged extractions
        # without yet enforcing a hard threshold (Sprint 2.5+: gate on rate).
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
