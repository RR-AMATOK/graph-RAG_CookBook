# Reference Corpus — The Big Bang Theory

This directory holds the reference example corpus used by `make example`. It's a small set of Wikipedia articles about the 2007 sitcom *The Big Bang Theory*, chosen because:

- **Rich entity structure** — main characters, recurring characters, episodes, seasons, locations, running gags
- **Real hierarchy** — Wikipedia's article tree gives genuine parent/child relationships (`Series → Season → Episode → Character`)
- **Public domain attribution model** — CC BY-SA 4.0 means freely reusable with attribution
- **Familiar to most users** — easier to evaluate "did the graph get this right?" against content you already know
- **Manageable scale** — ~15-20 articles is enough to demonstrate the pipeline without burning hours of API time

## Contents

After running `python scripts/fetch_reference_corpus.py`, this directory will contain:

```
reference-corpus/
├── README.md                                        ← this file
├── manifest.yaml                                    ← list of fetched articles
├── flat/                                            ← Repo A style (flat with __ delimiters)
│   ├── BBT__Series__Overview.md                     ← The Big Bang Theory
│   ├── BBT__Characters__Sheldon_Cooper.md
│   ├── BBT__Characters__Leonard_Hofstadter.md
│   ├── BBT__Characters__Penny.md
│   ├── BBT__Characters__Howard_Wolowitz.md
│   ├── BBT__Characters__Rajesh_Koothrappali.md
│   ├── BBT__Characters__Amy_Farrah_Fowler.md
│   ├── BBT__Characters__Bernadette_Rostenkowski.md
│   └── BBT__Cast__Jim_Parsons.md
└── nested/                                          ← Repo B style (folders + images)
    ├── series/
    │   ├── overview.md
    │   ├── seasons/
    │   │   ├── season_1.md
    │   │   ├── season_5.md
    │   │   └── season_12.md
    │   └── images/
    │       └── (article images, downloaded if available)
    └── related/
        ├── young_sheldon.md                          ← spinoff
        └── images/
```

The flat directory mimics Repo A from the SPEC (`parent__child__grandchild.md` naming). The nested directory mimics Repo B (folders + embedded images). This lets you exercise both ingestion paths from a single corpus.

## Why two layouts from one source?

The framework supports two source-repo styles:

- **Flat with `__` delimiters** — common when exporting from systems that don't preserve folder structure (e.g., flat dumps from CMSes, single-folder Notion exports, etc.)
- **Folder-based with embedded images** — typical of git-managed wikis, MkDocs sites, etc.

By fetching the same Wikipedia content into both layouts, the example corpus exercises both code paths and demonstrates how the framework merges them into a single canonical graph.

## Attribution

All content in this directory is fetched from English Wikipedia and licensed under the [Creative Commons Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/).

Each fetched article preserves its `source-url` in YAML frontmatter pointing to the original Wikipedia page. That field satisfies CC BY-SA's attribution requirement when the corpus or derivative graph is redistributed.

If you redistribute this corpus or graphs derived from it, you must:

1. Preserve the `source-url` field in each document's frontmatter.
2. License the redistributed work under CC BY-SA 4.0 or compatible terms.

This affects only the **example corpus and graphs derived from it**. The framework code itself is Apache-2.0 (see top-level `LICENSE`), and graphs you build from your own corpora carry whatever licensing your sources require — not CC BY-SA.

## Refreshing the corpus

```bash
python scripts/fetch_reference_corpus.py
```

The fetch script:
- Downloads the latest version of each article via the Wikipedia API
- Converts HTML → markdown via `trafilatura`
- Writes both the flat and nested layouts
- Records article revision IDs in `manifest.yaml` so subsequent fetches can detect upstream changes
- Respects Wikipedia's API rate limits (1 request/second by default)

If you want to extend the example to other Wikipedia trees, edit the `ARTICLES` list at the top of `scripts/fetch_reference_corpus.py`.

## Notes for evaluators

When inspecting graph quality on this corpus, useful sanity checks:

- **Sheldon Cooper** should connect to Leonard (roommate), Amy (spouse), Caltech (employer), Texas (origin)
- **Penny** should connect to Leonard (spouse), Cheesecake Factory (former workplace), Pharmaceutical Sales (later career)
- **Episode/season** entities should chain via `part_of` to their season → series
- **Jim Parsons** should connect to Sheldon Cooper via `portrays`, not `is_a` (an actor is not their character)
- The graph should NOT have edges between characters who never interact in the source articles (a common over-extraction failure)

These are the kinds of checks the `evals/golden_set.jsonl` formalizes for your own corpus once you replace this example.
