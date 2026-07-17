#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.build_instruction_knowledge_from_xlsx import DEFAULT_KG_OUTPUT, DEFAULT_KNOWLEDGE_OUTPUT  # noqa: E402
from scripts.import_instruction_kg_candidates import import_graph  # noqa: E402
from manual_xlsx_pipeline.pipeline_settings import MIN_KG_CONFIDENCE, RESET_KNOWLEDGE_GRAPH  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Step 3: import XLSX-derived drug nodes and KG candidate relations into Neo4j. "
            "Use --reset to keep only this run's graph."
        )
    )
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE_OUTPUT)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_KG_OUTPUT)
    parser.add_argument(
        "--reset",
        action=argparse.BooleanOptionalAction,
        default=RESET_KNOWLEDGE_GRAPH,
        help="Delete the existing Neo4j graph before import.",
    )
    parser.add_argument("--min-confidence", type=float, default=MIN_KG_CONFIDENCE)
    parser.add_argument("--report-output", type=Path, default=BACKEND_ROOT / "data" / "processed" / "kg_import_report.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = import_graph(
        knowledge_path=args.knowledge,
        candidates_path=args.candidates,
        reset=args.reset,
        min_confidence=args.min_confidence,
    )
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Step 3 completed: knowledge graph rebuilt.")
    print(f"Input drugs: {stats['input_drugs']}")
    print(f"Input candidates: {stats['input_candidates']}")
    print(f"Imported drug nodes: {stats['imported_drugs']}")
    print(f"Imported candidate relations: {stats['imported_candidate_relations']}")
    print(f"Graph nodes: {stats['nodes']}")
    print(f"Graph relations: {stats['relations']}")
    print(f"Import report: {args.report_output}")


if __name__ == "__main__":
    main()
