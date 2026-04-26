#!/usr/bin/env python3
"""
Fetch the reference example corpus — Wikipedia articles about The Big Bang Theory.

Writes the same content to two layouts for testing both ingestion paths:
  examples/reference-corpus/flat/    — flat with __ delimiters (Repo A style)
  examples/reference-corpus/nested/  — folder-based with images (Repo B style)

Each article preserves its source-url and revision_id in YAML frontmatter for
CC BY-SA 4.0 attribution and change detection on subsequent fetches.

Usage:
    python scripts/fetch_reference_corpus.py [--dry-run] [--rate-limit 1.0]

Cost: ~$0.00 (Wikipedia API is free; respects 1 req/sec by default).
"""

from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Third-party deps. Install via: pip install httpx trafilatura python-frontmatter pyyaml
try:
    import httpx
    import trafilatura
    import frontmatter
    import yaml
except ImportError as e:
    sys.exit(
        f"Missing dependency: {e.name}\n"
        f"Install with: pip install httpx trafilatura python-frontmatter pyyaml"
    )

# ---------------------------------------------------------------------------
# Article catalog
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Article:
    """One Wikipedia article to fetch, with its mapping into both layouts."""
    title: str                           # exact Wikipedia article title
    flat_path: str                       # filename for flat layout
    nested_path: str                     # path for nested layout
    tags: tuple[str, ...] = ()
    parent_flat: str | None = None       # for hierarchy reconstruction
    parent_nested: str | None = None


ARTICLES: list[Article] = [
    # Series-level
    Article(
        title="The Big Bang Theory",
        flat_path="BBT__Series__Overview.md",
        nested_path="series/overview.md",
        tags=("series", "overview"),
    ),
    # Seasons
    Article(
        title="The Big Bang Theory season 1",
        flat_path="BBT__Series__Seasons__Season_1.md",
        nested_path="series/seasons/season_1.md",
        tags=("series", "season"),
        parent_flat="BBT__Series__Overview",
        parent_nested="series/overview",
    ),
    Article(
        title="The Big Bang Theory season 5",
        flat_path="BBT__Series__Seasons__Season_5.md",
        nested_path="series/seasons/season_5.md",
        tags=("series", "season"),
        parent_flat="BBT__Series__Overview",
        parent_nested="series/overview",
    ),
    Article(
        title="The Big Bang Theory season 12",
        flat_path="BBT__Series__Seasons__Season_12.md",
        nested_path="series/seasons/season_12.md",
        tags=("series", "season"),
        parent_flat="BBT__Series__Overview",
        parent_nested="series/overview",
    ),
    # Main characters
    Article(
        title="Sheldon Cooper",
        flat_path="BBT__Characters__Sheldon_Cooper.md",
        nested_path="characters/sheldon_cooper.md",
        tags=("character", "main"),
    ),
    Article(
        title="Leonard Hofstadter",
        flat_path="BBT__Characters__Leonard_Hofstadter.md",
        nested_path="characters/leonard_hofstadter.md",
        tags=("character", "main"),
    ),
    Article(
        title="Penny (The Big Bang Theory)",
        flat_path="BBT__Characters__Penny.md",
        nested_path="characters/penny.md",
        tags=("character", "main"),
    ),
    Article(
        title="Howard Wolowitz",
        flat_path="BBT__Characters__Howard_Wolowitz.md",
        nested_path="characters/howard_wolowitz.md",
        tags=("character", "main"),
    ),
    Article(
        title="Raj Koothrappali",
        flat_path="BBT__Characters__Rajesh_Koothrappali.md",
        nested_path="characters/rajesh_koothrappali.md",
        tags=("character", "main"),
    ),
    Article(
        title="Amy Farrah Fowler",
        flat_path="BBT__Characters__Amy_Farrah_Fowler.md",
        nested_path="characters/amy_farrah_fowler.md",
        tags=("character", "main"),
    ),
    Article(
        title="Bernadette Rostenkowski-Wolowitz",
        flat_path="BBT__Characters__Bernadette_Rostenkowski.md",
        nested_path="characters/bernadette_rostenkowski.md",
        tags=("character", "main"),
    ),
    # Cast member (tests Person → Character relationship)
    Article(
        title="Jim Parsons",
        flat_path="BBT__Cast__Jim_Parsons.md",
        nested_path="cast/jim_parsons.md",
        tags=("person", "cast"),
    ),
    # Spinoff (tests cross-series relationships)
    Article(
        title="Young Sheldon",
        flat_path="BBT__Related__Young_Sheldon.md",
        nested_path="related/young_sheldon.md",
        tags=("series", "spinoff"),
    ),
]


# ---------------------------------------------------------------------------
# Wikipedia API client
# ---------------------------------------------------------------------------

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "graph-RAG_CookBook/0.1 (+https://github.com/<owner>/graph-RAG_CookBook; reference-corpus-fetcher)"


@dataclass
class FetchedArticle:
    title: str
    revision_id: int
    canonical_url: str
    html: str
    markdown: str = ""
    content_hash: str = ""


def fetch_article(client: httpx.Client, title: str) -> FetchedArticle:
    """Fetch a single article via the Wikipedia API in HTML form."""
    # Use the parse endpoint for full HTML; revision endpoint for stable IDs
    response = client.get(
        WIKIPEDIA_API,
        params={
            "action": "parse",
            "page": title,
            "format": "json",
            "prop": "text|revid",
            "redirects": 1,
            "formatversion": 2,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Wikipedia API error for '{title}': {data['error']}")

    parse = data["parse"]
    return FetchedArticle(
        title=parse["title"],
        revision_id=parse["revid"],
        canonical_url=f"https://en.wikipedia.org/wiki/{parse['title'].replace(' ', '_')}",
        html=parse["text"],
    )


def html_to_markdown(html: str, url: str) -> str:
    """Convert Wikipedia HTML to clean markdown."""
    extracted = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_images=True,
        include_tables=True,
        favor_recall=True,  # Wikipedia content is structured; lean on recall
    )
    if not extracted or len(extracted) < 200:
        # Fallback if trafilatura is too aggressive on stripping
        import html2text
        h = html2text.HTML2Text()
        h.body_width = 0
        h.ignore_emphasis = False
        h.protect_links = True
        extracted = h.handle(html)
    return extracted.strip() + "\n"


# ---------------------------------------------------------------------------
# Frontmatter and file emission
# ---------------------------------------------------------------------------

def build_frontmatter(article: Article, fetched: FetchedArticle, layout: str) -> dict[str, Any]:
    """Produce frontmatter conforming to the canonical schema (SPEC §7.1)."""
    parent = article.parent_flat if layout == "flat" else article.parent_nested
    return {
        "title": fetched.title,
        "aliases": [article.flat_path.removesuffix(".md")] if layout == "flat" else [],
        "tags": list(article.tags),
        "source_repo": f"reference-corpus-{layout}",
        "source_path": article.flat_path if layout == "flat" else article.nested_path,
        "source_url": fetched.canonical_url,
        "revision_id": fetched.revision_id,
        "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "content_hash": fetched.content_hash,
        "parent": f"[[{parent}]]" if parent else None,
        "stale": False,
    }


def write_article(article: Article, fetched: FetchedArticle, base_dir: Path,
                  layout: str, dry_run: bool = False) -> Path:
    """Write one article into the target layout."""
    rel_path = article.flat_path if layout == "flat" else article.nested_path
    out_path = base_dir / layout / rel_path

    fm = build_frontmatter(article, fetched, layout)
    # Strip None values; Obsidian's YAML parser dislikes nulls
    fm = {k: v for k, v in fm.items() if v is not None}

    post = frontmatter.Post(content=fetched.markdown, **fm)
    body = frontmatter.dumps(post, sort_keys=False)

    if dry_run:
        print(f"  [dry-run] would write {out_path} ({len(body)} bytes)")
        return out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Manifest tracking
# ---------------------------------------------------------------------------

def write_manifest(manifest_path: Path, fetched_articles: list[tuple[Article, FetchedArticle]],
                   dry_run: bool = False) -> None:
    """Record what was fetched, for change detection on subsequent runs."""
    entries = []
    for article, fetched in fetched_articles:
        entries.append({
            "title": fetched.title,
            "wikipedia_url": fetched.canonical_url,
            "revision_id": fetched.revision_id,
            "content_hash": fetched.content_hash,
            "flat_path": article.flat_path,
            "nested_path": article.nested_path,
            "tags": list(article.tags),
        })

    manifest = {
        "schema_version": "1.0",
        "source": "en.wikipedia.org",
        "license": "CC BY-SA 4.0",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_agent": USER_AGENT,
        "articles": entries,
    }

    if dry_run:
        print(f"  [dry-run] would write manifest to {manifest_path}")
        return

    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the reference example corpus.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without writing files.")
    parser.add_argument("--rate-limit", type=float, default=1.0,
                        help="Seconds between API requests (default: 1.0; respects WP guidelines).")
    parser.add_argument("--corpus-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "examples" / "reference-corpus",
                        help="Target directory for the corpus.")
    parser.add_argument("--only", type=str, default=None,
                        help="Only fetch articles whose title contains this substring (debugging).")
    args = parser.parse_args()

    articles = ARTICLES
    if args.only:
        articles = [a for a in articles if args.only.lower() in a.title.lower()]
        if not articles:
            print(f"No articles matched filter '{args.only}'.")
            return 1

    print(f"Fetching {len(articles)} Wikipedia articles → {args.corpus_dir}")
    if args.dry_run:
        print("(dry run — no files will be written)")

    fetched: list[tuple[Article, FetchedArticle]] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for i, article in enumerate(articles, 1):
            print(f"[{i}/{len(articles)}] {article.title} ...", end=" ", flush=True)
            try:
                got = fetch_article(client, article.title)
                got.markdown = html_to_markdown(got.html, got.canonical_url)
                got.content_hash = "sha256:" + hashlib.sha256(got.markdown.encode()).hexdigest()
                print(f"rev {got.revision_id}, {len(got.markdown):,} chars")
            except Exception as exc:
                print(f"FAILED: {exc}")
                continue

            write_article(article, got, args.corpus_dir, layout="flat", dry_run=args.dry_run)
            write_article(article, got, args.corpus_dir, layout="nested", dry_run=args.dry_run)
            fetched.append((article, got))

            if i < len(articles):
                time.sleep(args.rate_limit)

    write_manifest(args.corpus_dir / "manifest.yaml", fetched, dry_run=args.dry_run)

    print()
    print(f"Done. Fetched {len(fetched)}/{len(articles)} articles.")
    if not args.dry_run:
        print(f"Corpus written to {args.corpus_dir}/")
        print("Next: `make ingest` to build the graph from this corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
