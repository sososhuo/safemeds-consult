#!/usr/bin/env python3
"""
知识图谱候选导入脚本：把说明书候选关系写入 Neo4j 图数据库。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER


DEFAULT_KNOWLEDGE_PATH = BACKEND_ROOT / "data" / "processed" / "instruction_knowledge_from_xlsx.json"
DEFAULT_KG_CANDIDATES_PATH = BACKEND_ROOT / "data" / "processed" / "instruction_kg_candidates.jsonl"

ALLOWED_RELATIONS = {"CONTRAINDICATED_FOR", "USE_WITH_CAUTION_IN", "INTERACTS_WITH"}
OBJECT_LABELS = {
    "Drug": "Drug",
    "DrugClass": "DrugClass",
    "Population": "Population",
    "Condition": "Condition",
    "Risk": "Risk",
}


def load_knowledge(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_candidates(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def create_constraints(session) -> None:
    statements = [
        "CREATE CONSTRAINT drug_name IF NOT EXISTS FOR (n:Drug) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT drug_class_name IF NOT EXISTS FOR (n:DrugClass) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT population_name IF NOT EXISTS FOR (n:Population) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT condition_name IF NOT EXISTS FOR (n:Condition) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT risk_name IF NOT EXISTS FOR (n:Risk) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT source_name IF NOT EXISTS FOR (n:Source) REQUIRE n.name IS UNIQUE",
    ]
    for statement in statements:
        session.run(statement)


def reset_graph(session) -> None:
    session.run("MATCH (n) DETACH DELETE n")


def upsert_drugs(session, records: Iterable[dict[str, Any]]) -> int:
    count = 0
    for record in records:
        name = record.get("drug")
        if not name:
            continue
        session.run(
            """
            MERGE (d:Drug {name: $name})
            SET d.aliases = $aliases,
                d.source = $source,
                d.source_row_count = $source_row_count,
                d.source_urls = $source_urls,
                d.approval_numbers = $approval_numbers,
                d.updated_at = datetime()
            """,
            name=name,
            aliases=record.get("aliases", []),
            source=record.get("source", "instruction_xlsx"),
            source_row_count=int(record.get("source_row_count", 0) or 0),
            source_urls=record.get("source_urls", []),
            approval_numbers=record.get("approval_numbers", []),
        )
        count += 1
    return count


def upsert_candidates(session, candidates: Iterable[dict[str, Any]], min_confidence: float) -> int:
    count = 0
    for row in candidates:
        relation = row.get("relation")
        object_type = row.get("object_type")
        subject = row.get("subject")
        object_name = row.get("object")
        confidence = float(row.get("confidence", 0.0) or 0.0)
        if (
            relation not in ALLOWED_RELATIONS
            or object_type not in OBJECT_LABELS
            or not subject
            or not object_name
            or confidence < min_confidence
        ):
            continue

        label = OBJECT_LABELS[object_type]
        statement = f"""
        MERGE (s:Drug {{name: $subject}})
        MERGE (o:{label} {{name: $object}})
        MERGE (s)-[r:{relation}]->(o)
        SET r.risk_level = $risk_level,
            r.evidence_text = $evidence_text,
            r.section = $section,
            r.source_rows = $source_rows,
            r.source_urls = $source_urls,
            r.confidence = $confidence,
            r.source = "instruction_xlsx",
            r.weight = CASE $risk_level
                WHEN "High" THEN 1.3
                WHEN "Medium" THEN 1.1
                ELSE 0.8
            END
        """
        session.run(
            statement,
            subject=subject,
            object=object_name,
            risk_level=row.get("risk_level", "Unknown"),
            evidence_text=row.get("evidence_text", ""),
            section=row.get("section", ""),
            source_rows=row.get("source_rows", []),
            source_urls=row.get("source_urls", []),
            confidence=confidence,
        )
        count += 1
    return count


def import_graph(
    knowledge_path: Path,
    candidates_path: Path,
    reset: bool,
    min_confidence: float,
) -> dict[str, int]:
    from neo4j import GraphDatabase

    records = load_knowledge(knowledge_path)
    candidates = load_candidates(candidates_path)

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            create_constraints(session)
            if reset:
                reset_graph(session)
                create_constraints(session)
            imported_drugs = upsert_drugs(session, records)
            imported_relations = upsert_candidates(session, candidates, min_confidence=min_confidence)
            row = session.run(
                """
                MATCH (n)
                WITH count(n) AS nodes
                MATCH ()-[r]->()
                RETURN nodes, count(r) AS relations
                """
            ).single()
            return {
                "input_drugs": len(records),
                "input_candidates": len(candidates),
                "imported_drugs": imported_drugs,
                "imported_candidate_relations": imported_relations,
                "nodes": int(row["nodes"]),
                "relations": int(row["relations"]),
            }
    finally:
        driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import xlsx-derived instruction KG candidates into Neo4j.")
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE_PATH)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_KG_CANDIDATES_PATH)
    parser.add_argument("--reset", action="store_true", help="Delete existing graph before import.")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    args = parser.parse_args()

    stats = import_graph(
        knowledge_path=args.knowledge,
        candidates_path=args.candidates,
        reset=args.reset,
        min_confidence=args.min_confidence,
    )
    print(
        "Instruction KG import completed: "
        f"input_drugs={stats['input_drugs']} input_candidates={stats['input_candidates']} "
        f"imported_drugs={stats['imported_drugs']} "
        f"imported_candidate_relations={stats['imported_candidate_relations']} "
        f"nodes={stats['nodes']} relations={stats['relations']}"
    )


if __name__ == "__main__":
    main()
