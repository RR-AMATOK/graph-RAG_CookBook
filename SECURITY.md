# Security Policy

## Supported versions

`graph-RAG_CookBook` is in active development. The latest release on `main` is the only supported version; older versions do not receive security backports.

| Version | Supported |
|---------|-----------|
| `main` (latest) | ✅ |
| Older releases | ❌ |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them privately through one of:

1. **GitHub Security Advisories** (preferred): use the ["Report a vulnerability"](https://github.com/<owner>/graph-RAG_CookBook/security/advisories/new) link in this repo's Security tab.
2. **Email**: `<your-security-email>` with subject line beginning `[SECURITY]`.

When reporting, please include:

- A description of the vulnerability and its impact
- Steps to reproduce, ideally with a minimal proof of concept
- Affected versions or commits
- Any suggested fixes or mitigations

## What to expect

- **Acknowledgement** within 7 days of report
- **Initial assessment** within 14 days
- **Fix or mitigation plan** within 30 days for high-severity issues, longer for lower-severity
- **Public disclosure** coordinated with the reporter; you'll be credited unless you prefer otherwise

## Scope

The following are in-scope for security reports:

- **Code execution vulnerabilities** in the framework or scrapers
- **Secrets leakage** — anywhere API keys or tokens might be written to logs, error messages, or published artifacts
- **Path traversal** in canonicalization, vault emission, or scraper file writes
- **Injection vulnerabilities** in graph queries, MCP tool calls, or extracted prompts
- **Schema validation bypasses** that could let a malicious published artifact compromise consumers
- **PAT scope escalation** — scenarios where the publishing PAT could be used beyond its intended scope

The following are **not** considered vulnerabilities:

- LLM hallucination producing inaccurate graph edges (this is a quality issue, not a security issue; see `evals/` for the regression-gate framework)
- Scraping content from sites that block automated access (the framework respects robots.txt by default)
- Cost overruns from misconfigured rate limits or scrape patterns (configurable; not a vulnerability)
- Bugs that only affect users who have explicitly disabled safety features (e.g., `--force-publish`, `ignore_robots_txt: true`)

## Coordinated disclosure

We follow a 90-day coordinated disclosure model by default. The reporter and maintainers can agree on a different timeline for unusual cases (e.g., issues affecting upstream dependencies or requiring multi-party coordination).

## Preventive practices

The framework follows these security defaults — please don't disable them without understanding the implications:

- **API keys via environment variables only** — never hardcoded in code, never written to logs at INFO level or above
- **PAT scoping to dedicated artifacts repo** — the publishing token cannot push to the framework repo
- **`robots.txt` compliance enabled by default** for all Playwright scrapers
- **Atomic publishes** — partial publishes are impossible; consumers never see half-state
- **Schema validation required by reference consumer** — downstream code that follows the documented pattern validates before use
- **Eval gate blocks bad publishes** — extraction regressions cannot reach consumers
- **Pinned dependencies** in `uv.lock` / `pyproject.toml`

## Acknowledgements

Security reporters are credited in release notes unless they request anonymity.
