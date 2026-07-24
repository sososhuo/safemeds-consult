#!/usr/bin/env python3
"""
手工 Excel 流水线总入口：按顺序执行清洗、向量库和知识图谱构建。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from manual_xlsx_pipeline.pipeline_settings import (  # noqa: E402
    MAX_ROWS,
    MIN_KG_CONFIDENCE,
    MIN_SECTION_CHARS,
    RESET_KNOWLEDGE_GRAPH,
    RESET_VECTOR_STORE,
    SHEET_NAME,
    XLSX_INPUT_PATHS,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all manual XLSX pipeline steps: extract, rebuild vector store, rebuild Neo4j KG."
    )
    parser.add_argument("input", type=Path, nargs="*", help="Input .xlsx file(s), or directories containing .xlsx files.")
    parser.add_argument("--sheet", default=SHEET_NAME)
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS, help="Optional row limit for test runs.")
    parser.add_argument("--min-section-chars", type=int, default=MIN_SECTION_CHARS)
    parser.add_argument(
        "--reset-vector",
        action=argparse.BooleanOptionalAction,
        default=RESET_VECTOR_STORE,
        help="Delete existing Chroma data before rebuild.",
    )
    parser.add_argument(
        "--reset-kg",
        action=argparse.BooleanOptionalAction,
        default=RESET_KNOWLEDGE_GRAPH,
        help="Delete existing Neo4j graph before import.",
    )
    parser.add_argument("--min-confidence", type=float, default=MIN_KG_CONFIDENCE)
    return parser.parse_args()


def run_step(command: list[str]) -> None:
    print("\n$ " + " ".join(command))
    subprocess.run(command, cwd=BACKEND_ROOT, check=True)


def main() -> None:
    args = parse_args()
    python = sys.executable
    input_paths = args.input or XLSX_INPUT_PATHS
    if not input_paths:
        raise SystemExit(
            "No XLSX input path configured. Edit backend/manual_xlsx_pipeline/pipeline_settings.py "
            "or pass paths on the command line."
        )

    step1 = [
        python,
        str(PIPELINE_ROOT / "01_deduplicate_extract.py"),
        *[str(path) for path in input_paths],
        "--min-section-chars",
        str(args.min_section_chars),
    ]
    if args.sheet:
        step1.extend(["--sheet", args.sheet])
    if args.max_rows is not None:
        step1.extend(["--max-rows", str(args.max_rows)])

    step2 = [python, str(PIPELINE_ROOT / "02_build_vector_store.py")]
    if args.reset_vector:
        step2.append("--reset")

    step3 = [
        python,
        str(PIPELINE_ROOT / "03_build_knowledge_graph.py"),
        "--min-confidence",
        str(args.min_confidence),
    ]
    if args.reset_kg:
        step3.append("--reset")

    run_step(step1)
    run_step(step2)
    run_step(step3)

    print("\nAll steps completed.")


if __name__ == "__main__":
    main()
