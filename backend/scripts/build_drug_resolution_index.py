#!/usr/bin/env python3
"""
药物标准化索引构建脚本：从说明书知识库生成短名、别名和候选制剂索引。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import DATA_PATH, DRUG_ALIAS_OVERRIDES_PATH, DRUG_RESOLUTION_INDEX_PATH  # noqa: E402
from app.services.drug_resolution import build_resolution_index, load_alias_overrides  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the standalone drug-name resolution index.")
    parser.add_argument("--knowledge", type=Path, default=DATA_PATH)
    parser.add_argument("--aliases", type=Path, default=DRUG_ALIAS_OVERRIDES_PATH)
    parser.add_argument("--output", type=Path, default=DRUG_RESOLUTION_INDEX_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = json.loads(args.knowledge.read_text(encoding="utf-8"))
    overrides = load_alias_overrides(args.aliases)
    index = build_resolution_index(records, overrides)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Drug resolution index built.")
    print(f"Knowledge records: {index['record_count']}")
    print(f"Exact names: {len(index['exact_names'])}")
    print(f"Derived base names: {len(index['base_names'])}")
    print(f"Aliases: {len(index['aliases'])}")
    print(f"Alias conflicts: {len(index['alias_conflicts'])}")
    print(f"Rejected overrides: {len(index['rejected_alias_overrides'])}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
