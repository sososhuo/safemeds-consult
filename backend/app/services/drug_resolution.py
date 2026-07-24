"""
药物标准化模块：把口语药名、短名和无剂型名称映射到知识库候选制剂。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


INDEX_VERSION = 1

DOSAGE_FORM_SUFFIXES = tuple(
    sorted(
        {
            "口腔崩解片",
            "缓释混悬液",
            "口服混悬液",
            "混悬滴剂",
            "缓释胶囊",
            "肠溶胶囊",
            "软胶囊",
            "肠溶片",
            "分散片",
            "缓释片",
            "控释片",
            "咀嚼片",
            "泡腾片",
            "舌下片",
            "口含片",
            "薄膜衣片",
            "干混悬剂",
            "口服溶液",
            "口服液",
            "混悬液",
            "糖浆",
            "颗粒",
            "冲剂",
            "胶囊",
            "滴丸",
            "丸",
            "片",
            "乳膏",
            "软膏",
            "凝胶",
            "搽剂",
            "喷雾剂",
            "气雾剂",
            "滴眼液",
            "滴鼻液",
            "滴耳液",
            "注射液",
            "注射剂",
            "贴剂",
            "栓剂",
        },
        key=len,
        reverse=True,
    )
)

ORAL_CONTEXT_TERMS = ("吃", "服用", "口服", "吞服", "同服")
NON_ORAL_FORM_TERMS = (
    "乳膏",
    "软膏",
    "凝胶",
    "搽剂",
    "喷雾剂",
    "气雾剂",
    "滴眼液",
    "滴鼻液",
    "滴耳液",
    "注射液",
    "注射剂",
    "贴剂",
    "栓剂",
)
SALT_PREFIXES = tuple(
    sorted(
        {
            "盐酸",
            "硫酸",
            "硝酸",
            "枸橼酸",
            "马来酸",
            "苯磺酸",
            "甲磺酸",
            "富马酸",
            "酒石酸",
            "琥珀酸",
            "门冬氨酸",
            "赖氨酸",
            "氢溴酸",
            "磷酸",
            "醋酸",
        },
        key=len,
        reverse=True,
    )
)


def normalize_lookup_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def derive_base_name(drug_name: str) -> str:
    name = normalize_lookup_name(drug_name)
    name = re.sub(r"[（(][^（）()]{1,12}[）)]$", "", name).strip()
    for suffix in DOSAGE_FORM_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            return name[: -len(suffix)].strip()
    return name


def strip_salt_prefix(drug_name: str) -> str:
    name = normalize_lookup_name(drug_name)
    for prefix in SALT_PREFIXES:
        if name.startswith(prefix) and len(name) > len(prefix) + 1:
            return name[len(prefix):].strip()
    return name


def knowledge_name_fingerprint(records: list[dict[str, Any]]) -> str:
    payload = [
        {
            "drug": str(record.get("drug", "")),
            "aliases": sorted(str(alias) for alias in record.get("aliases", []) if alias),
        }
        for record in records
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_alias_overrides(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Drug alias override file must contain a JSON list: {path}")
    return payload


def build_resolution_index(
    records: list[dict[str, Any]],
    alias_overrides: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    known_drugs = {str(record.get("drug", "")).strip() for record in records if record.get("drug")}
    exact_names: dict[str, set[str]] = defaultdict(set)
    base_names: dict[str, set[str]] = defaultdict(set)
    aliases: dict[str, set[str]] = defaultdict(set)
    alias_sources: dict[str, set[str]] = defaultdict(set)

    for record in records:
        drug = str(record.get("drug", "")).strip()
        if not drug:
            continue
        exact_names[normalize_lookup_name(drug)].add(drug)
        base = derive_base_name(drug)
        if base and base != normalize_lookup_name(drug):
            base_names[base].add(drug)
        salt_stripped = strip_salt_prefix(drug)
        if salt_stripped and salt_stripped != normalize_lookup_name(drug):
            aliases[salt_stripped].add(drug)
            alias_sources[salt_stripped].add("derived_salt_short_name")
            salt_stripped_base = derive_base_name(salt_stripped)
            if salt_stripped_base and salt_stripped_base != salt_stripped:
                base_names[salt_stripped_base].add(drug)
        for alias in record.get("aliases", []) or []:
            key = normalize_lookup_name(alias)
            if not key:
                continue
            aliases[key].add(drug)
            alias_sources[key].add("source_alias")
            salt_stripped_alias = strip_salt_prefix(key)
            if salt_stripped_alias and salt_stripped_alias != key:
                aliases[salt_stripped_alias].add(drug)
                alias_sources[salt_stripped_alias].add("derived_salt_short_name")

    rejected_overrides: list[dict[str, Any]] = []
    for item in alias_overrides or []:
        alias = normalize_lookup_name(item.get("alias", ""))
        requested_targets = [str(value).strip() for value in item.get("targets", []) if value]
        valid_targets = [target for target in requested_targets if target in known_drugs]
        if not alias or not valid_targets:
            rejected_overrides.append(
                {
                    "alias": item.get("alias", ""),
                    "targets": requested_targets,
                    "reason": "empty alias or no target exists in the current knowledge file",
                }
            )
            continue
        aliases[alias].update(valid_targets)
        alias_sources[alias].add(str(item.get("source") or "manual_review"))

    def serialize(mapping: dict[str, set[str]]) -> dict[str, list[str]]:
        return {key: sorted(values) for key, values in sorted(mapping.items())}

    conflicts = [
        {"name": key, "targets": sorted(targets)}
        for key, targets in sorted(aliases.items())
        if len(targets) > 1
    ]
    return {
        "version": INDEX_VERSION,
        "knowledge_fingerprint": knowledge_name_fingerprint(records),
        "record_count": len(records),
        "exact_names": serialize(exact_names),
        "base_names": serialize(base_names),
        "aliases": serialize(aliases),
        "alias_sources": {key: sorted(values) for key, values in sorted(alias_sources.items())},
        "alias_conflicts": conflicts,
        "rejected_alias_overrides": rejected_overrides,
    }


class DrugNameResolver:
    def __init__(
        self,
        records: list[dict[str, Any]],
        index_path: Path | None = None,
        alias_overrides_path: Path | None = None,
    ):
        self.records = records
        self.index_path = index_path
        self.alias_overrides_path = alias_overrides_path
        self.index = self._load_index()

    def _load_index(self) -> dict[str, Any]:
        expected_fingerprint = knowledge_name_fingerprint(self.records)
        if self.index_path and self.index_path.exists():
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            if (
                payload.get("version") == INDEX_VERSION
                and payload.get("knowledge_fingerprint") == expected_fingerprint
            ):
                return payload
        return build_resolution_index(
            self.records,
            load_alias_overrides(self.alias_overrides_path),
        )

    def resolve(self, question: str) -> tuple[list[str], list[dict[str, Any]]]:
        text = normalize_lookup_name(question)
        if not text:
            return [], []

        matches: list[dict[str, Any]] = []
        sources = (
            ("exact_name", 3, self.index.get("exact_names", {})),
            ("alias", 2, self.index.get("aliases", {})),
            ("derived_base_name", 1, self.index.get("base_names", {})),
        )
        for source, priority, mapping in sources:
            for mention, targets in mapping.items():
                if len(mention) < 2:
                    continue
                start = text.find(mention)
                while start >= 0:
                    matches.append(
                        {
                            "start": start,
                            "end": start + len(mention),
                            "mention": mention,
                            "targets": list(targets),
                            "source": source,
                            "priority": priority,
                        }
                    )
                    start = text.find(mention, start + 1)

        selected: list[dict[str, Any]] = []
        occupied: list[tuple[int, int]] = []
        for item in sorted(matches, key=lambda value: (-len(value["mention"]), -value["priority"], value["start"])):
            span = (item["start"], item["end"])
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            selected.append(item)
            occupied.append(span)

        resolved: list[str] = []
        groups: list[dict[str, Any]] = []
        for item in sorted(selected, key=lambda value: value["start"]):
            targets = sorted(set(item["targets"]))
            if item["source"] == "derived_base_name" and any(term in text for term in ORAL_CONTEXT_TERMS):
                oral_targets = [
                    target
                    for target in targets
                    if not any(form in target for form in NON_ORAL_FORM_TERMS)
                ]
                if oral_targets:
                    targets = oral_targets
            if len(targets) == 1:
                resolved.extend(targets)
                continue
            groups.append(
                {
                    "mention": item["mention"],
                    "normalized": item["mention"],
                    "candidates": targets,
                    "source": item["source"],
                }
            )
        return sorted(set(resolved)), self._dedupe_groups(groups)

    @staticmethod
    def _dedupe_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for group in groups:
            key = (group["normalized"], tuple(group["candidates"]))
            if key in seen:
                continue
            seen.add(key)
            result.append(group)
        return result
