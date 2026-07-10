#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import DATA_PATH, NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER


DRUG_CLASSES = {
    "ibuprofen": "NSAIDs",
    "aspirin": "抗血小板药",
    "warfarin": "抗凝药",
    "clopidogrel": "抗血小板药",
    "nitroglycerin": "硝酸酯类",
    "sildenafil": "PDE5 抑制剂",
    "metformin": "双胍类降糖药",
    "insulin": "胰岛素制剂",
    "atorvastatin": "他汀类",
    "simvastatin": "他汀类",
    "clarithromycin": "大环内酯类抗生素",
    "fluconazole": "唑类抗真菌药",
}

DISEASE_DRUGS = {
    "糖尿病": ["metformin", "insulin"],
    "冠心病": ["aspirin", "clopidogrel", "nitroglycerin"],
    "房颤": ["warfarin"],
    "高血脂": ["atorvastatin", "simvastatin"],
    "高脂血症": ["atorvastatin", "simvastatin"],
    "感冒": ["ibuprofen"],
}

DISEASE_CAUTIONS = {
    "肾功能不全": ["metformin", "NSAIDs"],
    "活动性消化道出血": ["aspirin", "ibuprofen", "warfarin"],
    "妊娠/备孕": ["warfarin", "atorvastatin", "simvastatin"],
}


def load_records(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def create_constraints(session) -> None:
    statements = [
        "CREATE CONSTRAINT drug_name IF NOT EXISTS FOR (n:Drug) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT drug_class_name IF NOT EXISTS FOR (n:DrugClass) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT condition_name IF NOT EXISTS FOR (n:Condition) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT scenario_name IF NOT EXISTS FOR (n:Scenario) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT risk_name IF NOT EXISTS FOR (n:Risk) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT source_name IF NOT EXISTS FOR (n:Source) REQUIRE n.name IS UNIQUE",
    ]
    for statement in statements:
        session.run(statement)


def reset_graph(session) -> None:
    session.run("MATCH (n) DETACH DELETE n")


def upsert_drugs(session, records: list[dict[str, Any]]) -> None:
    for record in records:
        session.run(
            """
            MERGE (d:Drug {name: $name})
            SET d.aliases = $aliases,
                d.source = $source,
                d.updated_at = datetime()
            MERGE (s:Source {name: $source})
            MERGE (d)-[:SUPPORTED_BY {source: $source, weight: 0.6}]->(s)
            """,
            name=record["drug"],
            aliases=record.get("aliases", []),
            source=record.get("source", "local_dataset"),
        )


def upsert_classes(session) -> None:
    for drug, class_name in DRUG_CLASSES.items():
        session.run(
            """
            MERGE (d:Drug {name: $drug})
            MERGE (c:DrugClass {name: $class_name})
            MERGE (d)-[r:BELONGS_TO]->(c)
            SET r.source = "clinical_rule",
                r.weight = 0.9
            """,
            drug=drug,
            class_name=class_name,
        )


def upsert_interactions(session, records: list[dict[str, Any]]) -> None:
    for record in records:
        left = record["drug"]
        for rule in record.get("interactions", []):
            right = rule.get("with")
            if not right:
                continue
            relation = "CONTRAINDICATED_WITH" if rule.get("risk_level") == "High" else "INTERACTS_WITH"
            statement = f"""
            MERGE (left:Drug {{name: $left}})
            MERGE (right:Drug {{name: $right}})
            MERGE (left)-[r:{relation}]->(right)
            SET r.risk_level = $risk_level,
                r.mechanism = $mechanism,
                r.recommendation = $recommendation,
                r.source = "ddi_rules",
                r.weight = CASE $risk_level WHEN "High" THEN 1.3 WHEN "Medium" THEN 1.1 ELSE 0.9 END
            MERGE (risk:Risk {{name: $risk_level}})
            MERGE (left)-[risk_rel:MAY_CAUSE]->(risk)
            SET risk_rel.source = "ddi_rules",
                risk_rel.weight = 0.8
            """
            session.run(
                statement,
                left=left,
                right=right,
                risk_level=rule.get("risk_level", "Unknown"),
                mechanism=rule.get("mechanism", ""),
                recommendation=rule.get("recommendation", ""),
            )


def upsert_clinical_rules(session) -> None:
    statements = [
        (
            """
            MERGE (d:Drug {name: "warfarin"})
            MERGE (risk:Risk {name: "INR"})
            MERGE (d)-[r:MONITOR]->(risk)
            SET r.source = "clinical_rule", r.weight = 1.0
            """,
            {},
        ),
        (
            """
            MERGE (c:DrugClass {name: "NSAIDs"})
            MERGE (risk:Risk {name: "胃肠道出血"})
            MERGE (c)-[r:MAY_CAUSE]->(risk)
            SET r.source = "clinical_rule", r.weight = 1.0
            """,
            {},
        ),
        (
            """
            MERGE (left:DrugClass {name: "硝酸酯类"})
            MERGE (right:DrugClass {name: "PDE5 抑制剂"})
            MERGE (left)-[r:CONTRAINDICATED_WITH]->(right)
            SET r.source = "clinical_rule",
                r.risk_level = "High",
                r.mechanism = "硝酸酯类与 PDE5 抑制剂共同增强血管扩张作用，可能导致严重低血压。",
                r.recommendation = "禁忌合用；出现胸痛或低血压症状应立即就医。",
                r.weight = 1.3
            """,
            {},
        ),
        (
            """
            MERGE (d:Drug {name: "metformin"})
            MERGE (s:Scenario {name: "增强 CT / 造影剂"})
            MERGE (d)-[r:EXAM_CAUTION]->(s)
            SET r.source = "clinical_rule",
                r.risk_level = "Medium",
                r.mechanism = "含碘造影剂相关肾功能变化可能增加二甲双胍蓄积和乳酸酸中毒风险。",
                r.recommendation = "造影前后应由医生根据 eGFR 和检查类型决定是否暂停二甲双胍。",
                r.weight = 1.2
            """,
            {},
        ),
    ]
    for statement, params in statements:
        session.run(statement, **params)


def upsert_disease_relations(session) -> None:
    for disease, drugs in DISEASE_DRUGS.items():
        for drug in drugs:
            session.run(
                """
                MERGE (c:Condition {name: $disease})
                MERGE (d:Drug {name: $drug})
                MERGE (c)-[r:COMMON_DRUG]->(d)
                SET r.source = "disease_drug_kg",
                    r.weight = 0.8
                """,
                disease=disease,
                drug=drug,
            )
    for condition, drugs in DISEASE_CAUTIONS.items():
        for drug in drugs:
            label = "DrugClass" if drug == "NSAIDs" else "Drug"
            statement = f"""
            MERGE (d:{label} {{name: $drug}})
            MERGE (c:Condition {{name: $condition}})
            MERGE (d)-[r:CAUTION_FOR]->(c)
            SET r.source = "condition_caution_kg",
                r.weight = 1.0
            """
            session.run(statement, drug=drug, condition=condition)


def import_graph(records: list[dict[str, Any]], reset: bool = False) -> dict[str, int]:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            create_constraints(session)
            if reset:
                reset_graph(session)
                create_constraints(session)
            upsert_drugs(session, records)
            upsert_classes(session)
            upsert_interactions(session, records)
            upsert_clinical_rules(session)
            upsert_disease_relations(session)
            row = session.run(
                """
                MATCH (n)
                WITH count(n) AS nodes
                MATCH ()-[r]->()
                RETURN nodes, count(r) AS relations
                """
            ).single()
            return {"nodes": int(row["nodes"]), "relations": int(row["relations"])}
    finally:
        driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import SafeMeds medication KG into Neo4j.")
    parser.add_argument("--data", type=Path, default=DATA_PATH, help="Path to processed drug knowledge JSON.")
    parser.add_argument("--reset", action="store_true", help="Delete existing graph before import.")
    args = parser.parse_args()

    records = load_records(args.data)
    stats = import_graph(records, reset=args.reset)
    print(f"Neo4j KG import completed: nodes={stats['nodes']} relations={stats['relations']}")


if __name__ == "__main__":
    main()
