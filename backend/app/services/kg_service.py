from __future__ import annotations

from typing import Iterable, List

from app.core.config import NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER
from app.schemas.consultation import KnowledgeRelation


RELATION_LABELS = {
    "INTERACTS_WITH": "相互作用",
    "BELONGS_TO": "属于",
    "CONTRAINDICATED_FOR": "禁用于",
    "CONTRAINDICATED_WITH": "禁忌合用",
    "USE_WITH_CAUTION_IN": "慎用于",
    "CAUTION_FOR": "慎用于",
    "COMMON_DRUG": "常用药",
    "MAY_CAUSE": "风险",
    "MONITOR": "监测指标",
    "EXAM_CAUTION": "检查注意",
}


class MedicationKnowledgeGraph:
    """Neo4j-backed medication knowledge graph.

    SafeMeds treats Neo4j as the formal KG backend. The driver is created
    lazily so importing the FastAPI app does not fail before Docker services
    are started, but chat-time KG queries require Neo4j to be available.
    """

    def __init__(
        self,
        records: List[dict],
        uri: str = NEO4J_URI,
        user: str = NEO4J_USER,
        password: str = NEO4J_PASSWORD,
        database: str = NEO4J_DATABASE,
    ):
        self.records = records
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self._driver = None

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def _get_driver(self):
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:
                raise RuntimeError(
                    "Neo4j KG backend requires the neo4j Python package. "
                    "Install backend requirements first."
                ) from exc
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self._driver

    def health(self) -> dict:
        try:
            stats = self.stats()
            return {
                "kg_status": "ok",
                "kg_backend": "neo4j",
                "kg_nodes": stats["nodes"],
                "kg_relations": stats["relations"],
                "neo4j_uri": self.uri,
                "neo4j_database": self.database,
            }
        except Exception as exc:
            return {
                "kg_status": "unavailable",
                "kg_backend": "neo4j",
                "kg_nodes": 0,
                "kg_relations": 0,
                "neo4j_uri": self.uri,
                "neo4j_database": self.database,
                "kg_error": str(exc),
            }

    def stats(self) -> dict[str, int]:
        query = """
        MATCH (n)
        WITH count(n) AS nodes
        MATCH ()-[r]->()
        RETURN nodes, count(r) AS relations
        """
        with self._get_driver().session(database=self.database) as session:
            row = session.run(query).single()
            if row is None:
                return {"nodes": 0, "relations": 0}
            return {"nodes": int(row["nodes"]), "relations": int(row["relations"])}

    def query(self, entities: Iterable[str], depth: int = 1, limit: int = 16) -> list[KnowledgeRelation]:
        normalized_entities = [item for item in dict.fromkeys(entities) if item]
        if not normalized_entities:
            return []

        cypher = """
        UNWIND $entities AS raw_entity
        MATCH (start)
        WHERE any(label IN labels(start) WHERE label IN ["Drug", "DrugClass", "Condition", "Scenario"])
          AND (
            toLower(start.name) = toLower(raw_entity)
            OR toLower(raw_entity) IN [alias IN coalesce(start.aliases, []) | toLower(alias)]
          )
        MATCH path = (start)-[rel*1..2]-(neighbor)
        WITH relationships(path) AS rels
        UNWIND rels AS r
        WITH DISTINCT r
        WITH startNode(r) AS s, type(r) AS relation, endNode(r) AS o, r
        RETURN
          coalesce(s.name, elementId(s)) AS subject,
          relation,
          coalesce(o.name, elementId(o)) AS object,
          coalesce(r.source, "neo4j_kg") AS source,
          coalesce(r.weight, 1.0) AS weight,
          r.risk_level AS risk_level,
          coalesce(r.mechanism, "") AS mechanism,
          coalesce(r.recommendation, "") AS recommendation
        ORDER BY weight DESC, subject ASC, relation ASC, object ASC
        LIMIT $limit
        """
        max_depth = max(1, min(depth, 2))
        query_text = cypher.replace("*1..2", f"*1..{max_depth}")
        with self._get_driver().session(database=self.database) as session:
            rows = session.run(query_text, entities=normalized_entities, limit=limit)
            return [
                KnowledgeRelation(
                    subject=row["subject"],
                    relation=RELATION_LABELS.get(row["relation"], row["relation"].lower()),
                object=row["object"],
                source=row["source"],
                weight=float(row["weight"]),
                risk_level=row["risk_level"],
                mechanism=row["mechanism"],
                recommendation=row["recommendation"],
            )
            for row in rows
        ]
