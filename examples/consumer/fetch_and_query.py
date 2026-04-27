"""Reference downstream consumer for graph-RAG_CookBook artifacts.

This script is the **starting point** for a downstream agent-team repo. It:

1. Fetches the published ``graph.json`` from a local path or HTTP URL.
2. Validates it against the published JSON Schema (``schemas/graph-v1.schema.json``).
3. Demonstrates a minimal structure traversal — enough to copy-paste into a
   real consumer.

It deliberately uses **stdlib only** for HTTP (``urllib.request``) and dict
traversal, plus ``jsonschema`` for validation. Real consumers will likely add
``networkx`` for graph algorithms and ``httpx`` for richer HTTP; those are NOT
required to read the artifact.

Usage::

    # Local fixture (offline, works without infra)
    python fetch_and_query.py \\
        --graph examples/consumer/fixture-graph.json \\
        --schema schemas/graph-v1.schema.json \\
        --query "Sheldon Cooper"

    # Published artifact (Sprint 3+)
    python fetch_and_query.py \\
        --graph https://<owner>.github.io/<artifacts-repo>/graph.json \\
        --schema https://<owner>.github.io/<artifacts-repo>/schemas/graph-v1.schema.json \\
        --query "Business Capability"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

import jsonschema


def fetch(uri: str) -> bytes:
    """Fetch bytes from a local path or http(s) URL using stdlib only."""
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()

    if scheme in ("", "file"):
        path = parsed.path or uri
        return Path(path).read_bytes()

    if scheme in ("http", "https"):
        with urlopen(uri, timeout=30.0) as response:  # noqa: S310 — explicit scheme guard above
            data: bytes = response.read()
            return data

    raise ValueError(f"Unsupported URI scheme: {scheme!r}")


def load_and_validate(graph_uri: str, schema_uri: str) -> dict[str, Any]:
    """Fetch graph + schema, validate, and return the parsed graph document."""
    schema = json.loads(fetch(schema_uri))
    graph = json.loads(fetch(graph_uri))
    jsonschema.validate(graph, schema)
    return graph


def find_entity(graph: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Locate an Entity node by name (or alias). Case-sensitive."""
    for node in graph["nodes"]:
        if node["type"] != "Entity":
            continue
        props = node.get("properties", {})
        if props.get("name") == name or name in props.get("aliases", []):
            return node
    return None


def neighbors(graph: dict[str, Any], node_id: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Outgoing edges from ``node_id``. Returns ``(edge_type, target_id, edge_props)``."""
    out: list[tuple[str, str, dict[str, Any]]] = []
    for edge in graph["edges"]:
        if edge["source"] == node_id:
            out.append((edge["type"], edge["target"], edge.get("properties", {})))
    return out


def name_for(graph: dict[str, Any], node_id: str) -> str:
    """Return a human-readable name for a node id (falls back to id)."""
    for node in graph["nodes"]:
        if node["id"] == node_id:
            props = node.get("properties", {})
            return str(props.get("name") or props.get("title") or node_id)
    return node_id


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", required=True, help="Local path or http(s) URL to graph.json")
    parser.add_argument("--schema", required=True, help="Local path or http(s) URL to graph-v1.schema.json")
    parser.add_argument("--query", required=True, help="Entity name to look up")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    graph = load_and_validate(args.graph, args.schema)

    print(f"Loaded graph schema_version={graph['schema_version']}")
    md = graph["metadata"]
    print(f"  generated_at={md['generated_at']}  docs={md['doc_count']}  entities={md['entity_count']}  edges={md['edge_count']}")

    target = find_entity(graph, args.query)
    if target is None:
        print(f"\nEntity not found: {args.query!r}", file=sys.stderr)
        return 2

    print(f"\nEntity: {target['properties']['name']} (id={target['id']}, subtype={target.get('subtype', '-')})")
    description = target["properties"].get("description")
    if description:
        print(f"  {description}")
    print("\nOutgoing relationships:")
    for edge_type, target_id, props in neighbors(graph, target["id"]):
        confidence = props.get("confidence", "-")
        provenance = props.get("provenance_tag", "-")
        print(f"  --[{edge_type}]--> {name_for(graph, target_id)}  (confidence={confidence}, provenance={provenance})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
