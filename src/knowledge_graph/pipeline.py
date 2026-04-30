"""End-to-end ingest pipeline: canonicalize → chunk → extract → graph → metrics.

The orchestrator is a single function so it's easy to call from the CLI, from
tests, and from notebooks. It accepts pre-built collaborators (canonicalizer,
chunker, extractor, graph client) so tests can inject mocks without monkey-
patching module globals.

Sprint 2 scope: single-pass ingest. Re-ingest delete/recreate (FR-4.7) and
incremental updates (FR-7) land in Sprint 3.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from evals.harness.hallucination import (
    HallucinationReport,
    score_extraction,
)
from evals.harness.hallucination import (
    aggregate as aggregate_hallucination,
)

from knowledge_graph.canonicalizer import (
    CanonicalDoc,
    canonicalize_corpus,
)
from knowledge_graph.chunker import Chunk, ChunkerSettings, chunk_document
from knowledge_graph.extractor import Extractor, ExtractorSettings
from knowledge_graph.extractor.extractor import ExtractionResult
from knowledge_graph.graph import GraphBuilder, GraphClient, ensure_schema

logger = logging.getLogger(__name__)


@dataclass
class IngestSettings:
    flat_dir: Path | None = None
    nested_dir: Path | None = None
    flat_repo: str = "corpus-a"
    nested_repo: str = "corpus-b"
    corpus_out: Path = Path("corpus")
    runs_dir: Path = Path("runs")
    cache_dir: Path = Path("cache/extraction")
    chunker: ChunkerSettings = field(default_factory=ChunkerSettings)
    extractor: ExtractorSettings = field(default_factory=ExtractorSettings)


@dataclass
class IngestReport:
    run_id: str
    started_at: str
    finished_at: str
    docs_canonicalized: int
    docs_failed: int
    chunks_total: int
    chunks_extracted: int
    chunks_cache_hits: int
    entities_created: int
    entities_updated: int
    relationships_created: int
    relationships_updated: int
    mentions_created: int
    cost_input_tokens: int
    cost_output_tokens: int
    cost_cache_read_tokens: int
    cost_usd: float
    evidence_grounding_rate: float  # strict: name in cited span
    chunk_grounding_rate: float  # lenient: name anywhere in chunk (publish-gate signal)
    predicate_type_ok_rate: float
    n_relationships_scored: int
    flagged_count: int
    flagged_examples: list[str]
    canonicalization_errors: list[str]
    prompt_version: str

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True), encoding="utf-8")


def ingest_corpus(
    *,
    settings: IngestSettings,
    extractor: Extractor | None = None,
    graph_client: GraphClient | None = None,
) -> IngestReport:
    """Run the full Sprint 2 ingest pipeline.

    Args:
        settings: Paths and component-level settings.
        extractor: Pre-built :class:`Extractor`. Default constructs one from
            ``settings.extractor`` and ``settings.cache_dir``.
        graph_client: Pre-built :class:`GraphClient`. Default connects to
            FalkorDB on ``localhost:6390``.

    Returns:
        An :class:`IngestReport` describing the run; also written to
        ``settings.runs_dir/<run_id>/report.json``.
    """
    started = datetime.now(UTC)
    run_id = started.strftime("%Y%m%dT%H%M%SZ")

    sources = []
    if settings.flat_dir is not None:
        sources.append((settings.flat_dir, settings.flat_repo, "flat"))
    if settings.nested_dir is not None:
        sources.append((settings.nested_dir, settings.nested_repo, "nested"))
    if not sources:
        raise ValueError("ingest_corpus requires at least one of flat_dir / nested_dir")

    logger.info("canonicalizing %d source dir(s) into %s", len(sources), settings.corpus_out)
    docs, errors = canonicalize_corpus(sources, corpus_root=settings.corpus_out, write=True)
    logger.info("canonicalized %d docs (%d errors)", len(docs), len(errors))

    if extractor is None:
        ex_settings = settings.extractor
        if ex_settings.cache_root is None:
            ex_settings = ExtractorSettings(
                model=ex_settings.model,
                max_output_tokens=ex_settings.max_output_tokens,
                cache_root=settings.cache_dir,
                prompt_version=ex_settings.prompt_version,
                api_key=ex_settings.api_key,
                max_retries=ex_settings.max_retries,
            )
        extractor = Extractor(ex_settings)

    if graph_client is None:
        graph_client = GraphClient.connect()
    ensure_schema(graph_client)
    builder = GraphBuilder(client=graph_client)

    chunks_total = 0
    chunks_extracted = 0
    chunks_cache_hits = 0
    cost_input_tokens = 0
    cost_output_tokens = 0
    cost_cache_read_tokens = 0
    total_cost_usd = 0.0
    hallucination_reports: list[HallucinationReport] = []

    for doc in docs:
        builder.upsert_document(doc.frontmatter_obj)
        chunks = chunk_document(
            doc_id=doc.frontmatter_obj.doc_id,
            canonical_path=doc.frontmatter_obj.canonical_path,
            body=doc.body,
            settings=settings.chunker,
        )
        chunks_total += len(chunks)
        for chunk in chunks:
            result = extractor.extract(chunk)
            if result.cached:
                chunks_cache_hits += 1
            else:
                chunks_extracted += 1
                cost_input_tokens += result.usage.input_tokens
                cost_output_tokens += result.usage.output_tokens
                cost_cache_read_tokens += result.usage.cache_read_tokens
                total_cost_usd += result.usage.cost_usd

            builder.write_extraction(
                doc_fm=doc.frontmatter_obj, chunk=chunk, extraction=result.extraction
            )
            # Pass chunk.text so the scorer computes the lenient chunk-grounding
            # metric (the actual hallucination floor) alongside the strict
            # span-grounding writing-style metric.
            hallucination_reports.append(score_extraction(result.extraction, chunk_text=chunk.text))

    finished = datetime.now(UTC)
    halluc = aggregate_hallucination(hallucination_reports)
    report = IngestReport(
        run_id=run_id,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        docs_canonicalized=len(docs),
        docs_failed=len(errors),
        chunks_total=chunks_total,
        chunks_extracted=chunks_extracted,
        chunks_cache_hits=chunks_cache_hits,
        entities_created=builder.stats.entities_created,
        entities_updated=builder.stats.entities_updated,
        relationships_created=builder.stats.relationships_created,
        relationships_updated=builder.stats.relationships_updated,
        mentions_created=builder.stats.mentions_created,
        cost_input_tokens=cost_input_tokens,
        cost_output_tokens=cost_output_tokens,
        cost_cache_read_tokens=cost_cache_read_tokens,
        cost_usd=round(total_cost_usd, 6),
        evidence_grounding_rate=halluc.evidence_grounding_rate,
        chunk_grounding_rate=halluc.chunk_grounding_rate,
        predicate_type_ok_rate=halluc.predicate_type_ok_rate,
        n_relationships_scored=halluc.n_relationships,
        flagged_count=len(halluc.flagged),
        flagged_examples=halluc.flagged[:20],
        canonicalization_errors=errors,
        prompt_version=settings.extractor.prompt_version,
    )
    report.write(settings.runs_dir / run_id / "report.json")
    return report


def ingest_chunks(
    *,
    docs: Iterable[CanonicalDoc],
    extractor: Extractor,
    graph_client: GraphClient,
    chunker: ChunkerSettings | None = None,
) -> tuple[int, list[Chunk], list[ExtractionResult]]:
    """Chunk + extract for a pre-canonicalized doc set. Used by tests.

    Returns ``(n_docs, all_chunks, all_results)`` so tests can assert on the
    per-stage outputs without re-running canonicalization.
    """
    chunker = chunker or ChunkerSettings()
    ensure_schema(graph_client)
    builder = GraphBuilder(client=graph_client)

    all_chunks: list[Chunk] = []
    all_results: list[ExtractionResult] = []

    n = 0
    for doc in docs:
        n += 1
        builder.upsert_document(doc.frontmatter_obj)
        chunks = chunk_document(
            doc_id=doc.frontmatter_obj.doc_id,
            canonical_path=doc.frontmatter_obj.canonical_path,
            body=doc.body,
            settings=chunker,
        )
        all_chunks.extend(chunks)
        for chunk in chunks:
            result = extractor.extract(chunk)
            all_results.append(result)
            builder.write_extraction(
                doc_fm=doc.frontmatter_obj, chunk=chunk, extraction=result.extraction
            )

    return n, all_chunks, all_results
