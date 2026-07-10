#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ingestion_service import DocumentIngestionService


DEFAULT_OUTPUT = BACKEND_ROOT / "data" / "processed" / "document_chunks.json"
DEFAULT_REPORT = BACKEND_ROOT / "data" / "processed" / "ingestion_report.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest PDF/JSON/CSV/TXT documents into SafeMeds chunks.")
    parser.add_argument("input", type=Path, help="Input file or directory.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output chunks JSON path.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Output ingestion report JSON path.")
    parser.add_argument(
        "--knowledge-output",
        type=Path,
        default=None,
        help="Optional output path for drug_knowledge_zh.json-compatible records.",
    )
    args = parser.parse_args()

    service = DocumentIngestionService()
    chunks, report = service.ingest_path(args.input)
    report.output_path = str(args.output)

    service.export_chunks(chunks, args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    if args.knowledge_output is not None:
        service.export_knowledge_records(chunks, args.knowledge_output)

    print(
        "Document ingestion completed: "
        f"sources={report.source_count} chunks={report.chunk_count} "
        f"failed={report.failed_count} skipped={report.skipped_count}"
    )
    print(f"chunks: {args.output}")
    print(f"report: {args.report}")
    if args.knowledge_output is not None:
        print(f"knowledge_records: {args.knowledge_output}")


if __name__ == "__main__":
    main()
