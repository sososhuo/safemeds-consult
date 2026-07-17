#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.build_instruction_knowledge_from_xlsx import (  # noqa: E402
    DEFAULT_KG_OUTPUT,
    DEFAULT_KNOWLEDGE_OUTPUT,
    DEFAULT_REPORT_OUTPUT,
    build_records_from_paths,
)
from manual_xlsx_pipeline.pipeline_settings import (  # noqa: E402
    MAX_ROWS,
    MIN_SECTION_CHARS,
    SHEET_NAME,
    XLSX_INPUT_PATHS,
)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Step 1: read instruction XLSX files, merge duplicate rows by generic drug name, "
            "deduplicate section text, and extract structured RAG records plus KG candidates."
        )
    )
    parser.add_argument("input", type=Path, nargs="*", help="Input .xlsx file(s), or directories containing .xlsx files.")
    parser.add_argument("--sheet", default=SHEET_NAME, help="Sheet name. Defaults to the first sheet.")
    parser.add_argument("--knowledge-output", type=Path, default=DEFAULT_KNOWLEDGE_OUTPUT)
    parser.add_argument("--kg-output", type=Path, default=DEFAULT_KG_OUTPUT)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT_OUTPUT)
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS, help="Optional row limit for test runs.")
    parser.add_argument("--min-section-chars", type=int, default=MIN_SECTION_CHARS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_paths = args.input or XLSX_INPUT_PATHS
    if not input_paths:
        raise SystemExit(
            "No XLSX input path configured. Edit backend/manual_xlsx_pipeline/pipeline_settings.py "
            "or pass paths on the command line."
        )
    records, kg_candidates, report = build_records_from_paths(
        paths=input_paths,
        sheet_name=args.sheet,
        max_rows=args.max_rows,
        min_section_chars=args.min_section_chars,
    )
    write_json(args.knowledge_output, records)
    write_jsonl(args.kg_output, kg_candidates)
    write_json(args.report_output, report)

    print("Step 1 completed: XLSX deduplicated and extracted.")
    print(f"Input files: {report['input_file_count']}")
    print(f"Input rows read: {report['rows_read']}")
    print(f"Merged drug records: {report['drug_count']}")
    print(f"Structured chunks: {report['chunk_count']}")
    print(f"KG candidates: {report['kg_candidate_count']}")
    print(f"Knowledge JSON: {args.knowledge_output}")
    print(f"KG candidates JSONL: {args.kg_output}")
    print(f"Build report: {args.report_output}")


if __name__ == "__main__":
    main()
