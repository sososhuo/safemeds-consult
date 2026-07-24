"""
知识数据加载模块：从本地 JSON 知识库读取药品说明书结构化记录。
"""

import json
from typing import Dict, List

from app.core.config import DATA_PATH


def load_knowledge() -> List[Dict]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"知识库不存在: {DATA_PATH}")
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def load_alias_map(records: List[Dict]) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    for item in records:
        canonical = item["drug"]
        alias_map[canonical.lower()] = canonical
        for alias in item.get("aliases", []):
            alias_map[alias.lower()] = canonical
    return alias_map
