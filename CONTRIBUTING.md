# Contributing to graph-RAG_CookBook

Thanks for considering a contribution. This document covers how to set up a development environment, the conventions the project follows, and how PRs land.

## Quick links

- **Bug reports**: open an [Issue](https://github.com/<owner>/graph-RAG_CookBook/issues/new?template=bug_report.yml)
- **Feature ideas**: open a [Discussion](https://github.com/<owner>/graph-RAG_CookBook/discussions) before submitting a PR
- **Security issues**: see [SECURITY.md](./SECURITY.md) — do not open public issues for security reports
- **Code of Conduct**: see [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)

## Development setup

```bash
# Clone and enter
git clone https://github.com/<owner>/graph-RAG_CookBook
cd graph-RAG_CookBook

# Install with dev extras (uv recommended)
uv venv
uv pip install -e ".[dev]"

# Or with plain pip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Pre-commit hooks (linting, formatting, type checks)
pre-commit install

# Storage services
docker compose up -d

# Verify your setup
make test
```

## Project conventions

- **Python 3.11+** with type hints on all public functions
- **`uv` for dependency management** (falls back to pip)
- **`ruff` for linting and formatting** — run `make lint` before pushing
- **`pytest` for tests** — every module under `src/` has a corresponding `tests/test_<module>.py`
- **`structlog` for logging** — never use bare `print()` in `src/`; use the project logger
- **One concern per PR** — easier review, easier revert if needed

## What makes a good PR

1. **Linked issue or discussion** — for non-trivial changes, surface the idea in an Issue or Discussion first so we can align on approach before code is written.
2. **Tests** — every new function gets a unit test; every bug fix gets a regression test.
3. **Eval impact noted** — if the change touches the extractor, prompt, or chunker, run `make eval` and include the delta in the PR description.
4. **Docs updated** — README, docs/, or the relevant SKILL.md if behavior changes.
5. **CHANGELOG entry** — append to `CHANGELOG.md` under the "Unreleased" heading.
6. **Conventional commit message** — `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:` — used to auto-generate the changelog at release time.

## What's out of scope

The framework is intentionally narrow. These are explicitly out of scope and PRs adding them will be politely declined:

- **Web UI** — Obsidian is the human UI; downstream consumer repos build their own UIs
- **Agent logic / orchestration** — that lives in consumer repos, not here
- **Format-of-the-week support** — markdown + images in v1; PDF, video, code formats deferred to v2
- **Built-in vector store implementations** — Qdrant is the v1 dependency; alternatives can be added behind the existing adapter interface but core code stays Qdrant-shaped
- **Wholesale migration to a different graph database** — FalkorDB and Neo4j are supported via the adapter; another would need very strong justification

If you have a use case that requires one of these, a separate downstream project that consumes the graph artifact is usually the better path. The whole point of the artifact contract is to enable this.

## Running the agent team locally

This framework was designed and built with a 14-agent Claude Code delegation system. You don't need to use it to contribute — direct human contributions are completely fine. But if you want to leverage it:

1. Install the agent skills: `cd skills && ./install.sh`
2. Read the agent conventions in `.claude/state/MEMORY.md`
3. Delegate specific tasks via `/agent <agent-name>` in Claude Code

## Release process

Maintainers tag releases following [SemVer](https://semver.org/):

- **Patch** (`0.1.0` → `0.1.1`): bug fixes, doc updates, no API changes
- **Minor** (`0.1.0` → `0.2.0`): new features, additive schema changes, backward-compatible
- **Major** (`0.1.0` → `1.0.0`): breaking schema or API changes; requires consumer migration notice

Schema changes have their own versioning track — see `docs/consumer-guide.md`.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](./LICENSE) that covers the project.
