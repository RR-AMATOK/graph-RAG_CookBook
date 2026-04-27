# Sprint 2 Security Checklist (advisory, pre-implementation)

This is an advisory list of security concerns that **must** be addressed before the code in scope lands on `main`. Authored at Sprint 1 close by `@security-auditor` (advisory pass — no code yet to audit).

The Sprint 2/3 implementation owners are responsible for closing each item; `@security-auditor` will perform a binding review during the relevant PR.

## Extraction prompt → LLM (Sprint 2, FR-3)

- [ ] **Prompt-injection surface from corpus content.** Markdown source can contain instructions disguised as content (e.g., `Ignore previous instructions and...`). The extractor prompt MUST sandbox source content (e.g., via XML tags, role separation) and treat extracted JSON as data, not instructions.
- [ ] **No source-content echo into prompts that downstream agents see.** The extractor's job is to *describe* content into typed entities/edges, not to forward it. Audit the prompt template for raw passthrough.
- [ ] **Schema-bound parsing.** The extractor MUST validate every LLM response against a pinned JSON Schema before merging into the graph. Reject and log; do not best-effort parse.
- [ ] **Cost ceilings enforced at the call site.** A runaway prompt that silently expands chunk size could blow the $0.05/doc cost gate. Track tokens per call and fail loud.

## Playwright scrapers (Sprint 6, FR-9)

- [ ] **`robots.txt` compliance.** Every scrape job MUST consult `robots.txt` and honor disallowed paths. Document override policy explicitly.
- [ ] **Rate limiting per host.** Default 1 req/s + jitter; configurable in `sources.yaml` but NEVER zero.
- [ ] **`storageState.json` encryption at rest.** Playwright auth state contains session cookies. Encrypt at rest (e.g., age, gpg) or store outside the repo's filesystem.
- [ ] **Scraped HTML treated as untrusted.** HTML→MD conversion strips scripts; the resulting markdown is then fed to the extractor (above). Both layers are prompt-injection points; defense-in-depth applies.
- [ ] **Per-site allow-list.** Scrapers MUST refuse to follow links outside the configured site. Document escape-hatch policy.

## Artifacts repo + GitHub Pages (Sprint 3, DEC-005, DEC-006)

- [ ] **Fine-grained PAT scoping.** The `GITHUB_ARTIFACTS_TOKEN` MUST be scoped to the artifacts repo only — `contents: write` + `metadata: read`. No org-wide access. No classic PATs.
- [ ] **Token in environment, not config files.** `config/publishing.yaml` references `token_env: GITHUB_ARTIFACTS_TOKEN`; the value lives only in env / GH Actions secrets.
- [ ] **PAT rotation policy.** Document a 90-day rotation schedule; record in `.claude/state/MEMORY.md`.
- [ ] **Pages branch protection.** The artifacts repo's `main` branch (which serves Pages) MUST require status checks (the publish workflow) before merge. No direct push from a developer's laptop.
- [ ] **No secrets in the artifact.** `graph.json`, `graph.meta.json`, `index.json` are world-readable via Pages. Verify nothing in the canonical frontmatter (e.g., `source_url`) leaks internal hostnames or credentials.

## CI / GitHub Actions (Sprint 1, this repo)

- [ ] **SHA-pin all third-party actions** before any publish workflow lands. Currently `actions/checkout@v4` and `actions/setup-python@v5` use floating tags — acceptable for lint/test, **not** for any job that touches secrets.
- [ ] **`permissions:` declared per job, not just workflow.** Default to `contents: read`; opt in narrowly per job.
- [ ] **No `pull_request_target` triggers** on this repo without an explicit threat-model review.
- [ ] **`secrets.GITHUB_TOKEN` minimal scope.** Confirm `permissions:` blocks default-write tokens.
- [ ] **`concurrency:` group on every workflow** to prevent race conditions during parallel pushes.

## API keys (Anthropic, Voyage, etc.)

- [ ] **Env vars only.** No keys in `config/*.yaml`, `.env` checked into git, or container images.
- [ ] **Rate-limit awareness.** Anthropic + Voyage have per-minute caps; publish runs in CI MUST not exhaust org-wide quotas. Use isolated sub-keys per environment.
- [ ] **Audit log retention.** Track per-call cost and token usage in `runs/<timestamp>/report.json`. Required for billing reconciliation.

## MCP server (Sprint 2, FR-7)

- [ ] **Local-only binding.** The MCP server MUST bind to `127.0.0.1` (or stdio); never `0.0.0.0`.
- [ ] **No raw extraction prompts in tool responses (FR-7.4).** The server returns structured graph data, not LLM I/O.
- [ ] **No API keys exposed via tools (FR-7.4).** Tools query the local graph; they do not pass credentials.

## Sign-off

`@security-auditor` performs a binding review during each Sprint 2/3 PR that touches the items above. This advisory list is the input; the binding review produces the green light.
