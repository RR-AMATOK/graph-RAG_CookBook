"""CLI entry point: ``kg`` command.

Subcommands (implementation lands in Sprint 2+):
- ``kg ingest`` — run the ingestion pipeline
- ``kg update`` — incremental refresh from changed source files
- ``kg scrape`` — Playwright dynamic source extraction
- ``kg check-staleness`` — detect outdated docs against upstream
- ``kg emit-vault`` — write Obsidian vault from current graph
- ``kg serve-mcp`` — start the local MCP server for Claude Code
- ``kg eval`` — run the eval harness against the current extraction
- ``kg export`` — produce multi-format graph artifacts (Sprint 3+)
- ``kg publish`` — publish artifacts to configured storage backend (Sprint 3+)
"""

from __future__ import annotations

import typer

from knowledge_graph import __version__

app = typer.Typer(
    name="kg",
    help="graph-RAG_CookBook — knowledge-graph builder + publisher.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def version() -> None:
    """Print the installed package version."""
    typer.echo(__version__)


@app.command()
def info() -> None:
    """Show project info and component status (Sprint 1 placeholder)."""
    typer.echo("graph-RAG_CookBook")
    typer.echo(f"  version: {__version__}")
    typer.echo("  status: Sprint 1 — scaffolding only.")
    typer.echo("  see SPEC.md for the roadmap; CLAUDE.md for project rules.")


if __name__ == "__main__":
    app()
