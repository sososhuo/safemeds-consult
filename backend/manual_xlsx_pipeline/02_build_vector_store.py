#!/usr/bin/env python3
"""
手工 Excel 流水线第二步：将清洗后的说明书知识构建为向量库。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import CHROMA_PERSIST_DIR, VECTOR_BACKEND  # noqa: E402
from app.services.rag_service import ChromaRagIndex, build_documents  # noqa: E402
from manual_xlsx_pipeline.pipeline_settings import RESET_VECTOR_STORE  # noqa: E402
from scripts.build_instruction_knowledge_from_xlsx import DEFAULT_KNOWLEDGE_OUTPUT  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Step 2: rebuild the local vector store from the extracted knowledge JSON. "
            "Use --reset to keep only this run's Chroma data."
        )
    )
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE_OUTPUT)
    parser.add_argument(
        "--reset",
        action=argparse.BooleanOptionalAction,
        default=RESET_VECTOR_STORE,
        help="Delete the existing Chroma persist directory first.",
    )
    parser.add_argument("--report-output", type=Path, default=BACKEND_ROOT / "data" / "processed" / "vector_build_report.json")
    return parser.parse_args()


def load_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def main() -> None:
    args = parse_args()
    if args.reset and CHROMA_PERSIST_DIR.exists():
        shutil.rmtree(CHROMA_PERSIST_DIR)

    records = load_records(args.knowledge)
    document_count = len(build_documents(records))

    if VECTOR_BACKEND != "chroma":
        print(f"VECTOR_BACKEND is {VECTOR_BACKEND!r}; Chroma will still be built for the current knowledge file.")

    index = ChromaRagIndex(records)
    index._ensure_populated()

    report = {
        "knowledge": str(args.knowledge),
        "chroma_persist_dir": str(CHROMA_PERSIST_DIR),
        "collection": index.collection_name,
        "drug_records": len(records),
        "documents": document_count,
        "collection_count": index.collection.count(),
        "reset": args.reset,
    }
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Step 2 completed: vector store rebuilt.")
    print(f"Drug records: {len(records)}")
    print(f"Documents/chunks: {document_count}")
    print(f"Chroma collection: {index.collection_name}")
    print(f"Collection count: {index.collection.count()}")
    print(f"Chroma directory: {CHROMA_PERSIST_DIR}")
    print(f"Build report: {args.report_output}")


if __name__ == "__main__":
    main()
