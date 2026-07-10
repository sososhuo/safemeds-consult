"""
LangGraph 咨询工作流测试
========================
验证 /api/chat 内部 RAG workflow 的节点编排，不依赖 Neo4j 容器。
"""

import json
import tempfile
import unittest
from pathlib import Path

import app.services.stages.drug_recognition as drug_recognition
from app.repositories.consultation_repository import ConsultationRepository
from app.schemas.consultation import KnowledgeRelation
from app.services.consultation_service import MedicationConsultationService
from app.services.metrics_service import SystemMetrics, system_metrics

TEST_DIR = Path(__file__).resolve().parent
DATA_PATH = TEST_DIR.parent / "data" / "processed" / "drug_knowledge_zh.json"


class FakeKnowledgeGraph:
    def query(self, entities, depth=1, limit=16):
        return [
            KnowledgeRelation(
                subject="warfarin",
                relation="相互作用",
                object="ibuprofen",
                source="test_neo4j",
                weight=1.3,
            )
        ]

    def health(self):
        return {
            "kg_status": "ok",
            "kg_backend": "neo4j",
            "kg_nodes": 2,
            "kg_relations": 1,
            "neo4j_uri": "bolt://test",
            "neo4j_database": "neo4j",
        }


class FakeExtractionLLM:
    configured = True

    def extract_medication_entities(self, message):
        if "头孢" in message:
            return {
                "specific_drugs": [],
                "ambiguous_entities": [
                    {
                        "mention": "头孢",
                        "entity_type": "drug_class",
                        "normalized": "头孢菌素类抗生素",
                        "reason": "类别词，不是明确的单一药品名称。",
                        "user_message": "请补充具体药品名称。",
                    }
                ],
                "compound_products": [],
            }
        if "感冒灵" in message:
            return {
                "specific_drugs": [],
                "ambiguous_entities": [],
                "compound_products": [
                    {
                        "mention": "感冒灵",
                        "normalized": "复方感冒药",
                        "possible_ingredients": ["对乙酰氨基酚", "马来酸氯苯那敏"],
                        "reason": "不同厂家成分可能不同。",
                        "user_message": "不同厂家成分可能不同，实际以包装或说明书为准。",
                    }
                ],
            }
        return {"specific_drugs": [], "ambiguous_entities": [], "compound_products": []}


def load_test_records():
    with open(DATA_PATH, encoding="utf-8") as file:
        return json.load(file)


class TestMedicationRagWorkflow(unittest.TestCase):
    def test_chat_uses_langgraph_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = ConsultationRepository(db_path=Path(tmpdir) / "consultation.sqlite3")
            service = MedicationConsultationService(records=load_test_records(), repository=repo)
            service.kg = FakeKnowledgeGraph()

            response = service.chat("华法林和布洛芬一起吃可以吗")

        self.assertEqual(response.risk_level, "High")
        self.assertGreater(len(response.evidence), 0)
        self.assertEqual(response.kg_relations[0].source, "test_neo4j")
        self.assertIn("warfarin", response.extracted_context.normalized_drugs)
        self.assertIn("ibuprofen", response.extracted_context.normalized_drugs)
        self.assertEqual(
            [item["node"] for item in response.workflow_trace],
            [
                "extract_entities",
                "query_kg",
                "retrieve_evidence",
                "assess_risk",
                "prepare_answer",
            ],
        )
        retrieve_trace = next(item for item in response.workflow_trace if item["node"] == "retrieve_evidence")
        self.assertIn("返回证据", retrieve_trace["detail"])

    def test_system_metrics_records_chat(self):
        system_metrics.events.clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = ConsultationRepository(db_path=Path(tmpdir) / "consultation.sqlite3")
            service = MedicationConsultationService(records=load_test_records(), repository=repo)
            service.kg = FakeKnowledgeGraph()
            service.chat("华法林和布洛芬一起吃可以吗")

        snapshot = system_metrics.snapshot()
        self.assertEqual(snapshot["chat_count"], 1)
        self.assertGreater(snapshot["avg_latency_ms"], 0)
        self.assertGreater(snapshot["avg_evidence_count"], 0)
        self.assertEqual(snapshot["risk_distribution"]["High"], 1)

    def test_empty_metrics_snapshot(self):
        metrics = SystemMetrics()
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["chat_count"], 0)
        self.assertEqual(snapshot["fallback_rate"], 0)

    def test_ambiguous_drug_class_downgrades_to_unknown(self):
        original_flag = drug_recognition.LLM_ENABLE_EXTRACTION
        try:
            drug_recognition.LLM_ENABLE_EXTRACTION = True
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = ConsultationRepository(db_path=Path(tmpdir) / "consultation.sqlite3")
                service = MedicationConsultationService(records=load_test_records(), repository=repo)
                service.kg = FakeKnowledgeGraph()
                service.extractor.llm_client = FakeExtractionLLM()

                response = service.chat("布洛芬和头孢能一起吃吗")
        finally:
            drug_recognition.LLM_ENABLE_EXTRACTION = original_flag

        self.assertEqual(response.risk_level, "Unknown")
        self.assertIn("ibuprofen", response.extracted_context.normalized_drugs)
        self.assertEqual(response.extracted_context.ambiguous_entities[0]["mention"], "头孢")
        self.assertEqual(response.extracted_context.ambiguous_entities[0]["entity_type"], "drug_class")
        self.assertEqual(response.kg_relations, [])
        self.assertIn("具体药品名称", response.recommendation)

    def test_compound_product_downgrades_to_unknown(self):
        original_flag = drug_recognition.LLM_ENABLE_EXTRACTION
        try:
            drug_recognition.LLM_ENABLE_EXTRACTION = True
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = ConsultationRepository(db_path=Path(tmpdir) / "consultation.sqlite3")
                service = MedicationConsultationService(records=load_test_records(), repository=repo)
                service.kg = FakeKnowledgeGraph()
                service.extractor.llm_client = FakeExtractionLLM()

                response = service.chat("感冒灵和布洛芬能一起吃吗")
        finally:
            drug_recognition.LLM_ENABLE_EXTRACTION = original_flag

        self.assertEqual(response.risk_level, "Unknown")
        self.assertIn("ibuprofen", response.extracted_context.normalized_drugs)
        self.assertEqual(response.extracted_context.ambiguous_entities[0]["entity_type"], "compound_product")
        self.assertIn("possible_ingredients", response.extracted_context.ambiguous_entities[0])

    def test_current_turn_extraction_ignores_historical_drugs_when_ambiguous(self):
        original_flag = drug_recognition.LLM_ENABLE_EXTRACTION
        try:
            drug_recognition.LLM_ENABLE_EXTRACTION = True
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = ConsultationRepository(db_path=Path(tmpdir) / "consultation.sqlite3")
                service = MedicationConsultationService(records=load_test_records(), repository=repo)
                service.kg = FakeKnowledgeGraph()
                service.extractor.llm_client = FakeExtractionLLM()

                first = service.chat("芬太尼贴正在用", user_id="u1")
                second = service.chat(
                    "布洛芬和头孢能一起吃吗",
                    user_id="u1",
                    session_id=first.session_id,
                )
        finally:
            drug_recognition.LLM_ENABLE_EXTRACTION = original_flag

        self.assertIn("fentanyl", second.session_snapshot.drugs)
        self.assertIn("ibuprofen", second.extracted_context.normalized_drugs)
        self.assertNotIn("fentanyl", second.extracted_context.normalized_drugs)
        self.assertEqual(second.risk_level, "Unknown")
        self.assertEqual(second.kg_relations, [])


if __name__ == "__main__":
    unittest.main()
