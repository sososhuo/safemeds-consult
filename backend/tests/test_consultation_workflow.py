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
from app.schemas.analysis import Evidence, ExtractedContext
from app.schemas.consultation import KnowledgeRelation, SessionSnapshot
from app.services.llm_service import build_consultation_prompt
from app.services.consultation_service import MedicationConsultationService
from app.services.metrics_service import SystemMetrics, system_metrics
from app.services.stages.risk_assessment import RiskAssessmentStage

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


def load_population_test_records():
    return [
        {
            "drug": "阿魏酸哌嗪片",
            "aliases": [],
            "source": "population-test",
            "sections": [
                {
                    "title": "禁忌",
                    "content": "对阿魏酸哌嗪类药物过敏者禁用。",
                },
                {
                    "title": "警告与注意事项",
                    "content": "本品禁与阿苯达唑类和双羟萘酸噻嘧啶类药物合用。",
                },
                {
                    "title": "老年用药",
                    "content": "老人应在专业医师指导下使用。",
                },
            ],
            "interactions": [],
        }
    ]


class TestMedicationRagWorkflow(unittest.TestCase):
    def test_current_child_age_population_overrides_previous_elderly_snapshot(self):
        service = MedicationConsultationService.__new__(MedicationConsultationService)
        extracted = ExtractedContext(
            drugs=[],
            normalized_drugs=[],
            population=["儿童"],
            conditions=[],
            risk_factors=[],
            ambiguous_entities=[],
        )
        snapshot = SessionSnapshot(population=["老年人"])

        merged = service._merge_snapshot(snapshot, extracted, "我7岁，发烧了")

        self.assertIn("儿童", merged.population)
        self.assertNotIn("老年人", merged.population)

    def test_consultation_prompt_limits_special_population_to_current_context(self):
        messages = build_consultation_prompt(
            conclusion="不建议自行合用",
            risk_level="High",
            mechanism="儿童使用需成人监护。",
            recommendation="咨询医生或药师。",
            flags=[],
            evidence=[],
            kg_relations=[],
            current_population=["儿童"],
            safety_notice="安全声明",
        )
        prompt = messages[-1]["content"]

        self.assertIn("本次问题识别到的特殊人群：儿童", prompt)
        self.assertIn("不要把证据中出现但本次问题未识别到的人群", prompt)

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
                "retrieve_evidence",
                "query_kg",
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

    def test_population_terms_are_added_to_evidence_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = ConsultationRepository(db_path=Path(tmpdir) / "consultation.sqlite3")
            service = MedicationConsultationService(records=load_test_records(), repository=repo)
            extracted = ExtractedContext(
                drugs=["levofloxacin"],
                normalized_drugs=["levofloxacin"],
                population=["儿童"],
                conditions=[],
                risk_factors=[],
            )

            query = service._build_evidence_query(
                "儿童可以吃左氧氟沙星吗",
                kg_relations=[],
                drugs=["levofloxacin"],
                extracted=extracted,
            )

        self.assertIn("儿童", query)
        self.assertIn("18岁以下", query)
        self.assertIn("特殊人群", query)

    def test_kg_high_relation_uplifts_risk_without_downgrading(self):
        service = MedicationConsultationService.__new__(MedicationConsultationService)
        service.risk_engine = RiskAssessmentStage([])
        evidence = [
            Evidence(
                source="unit",
                drug="drug_a",
                section="一般信息",
                snippet="当前资料提示可按说明书使用。",
                score=1.0,
            )
        ]
        kg_relations = [
            KnowledgeRelation(
                subject="drug_a",
                relation="禁忌合用",
                object="drug_b",
                source="unit_kg",
                weight=1.3,
                risk_level="High",
                mechanism="图谱提示 drug_a 与 drug_b 禁忌合用。",
                recommendation="避免合用。",
            )
        ]

        risk_level, mechanism, _ = service._assess(
            ["drug_a", "drug_b"],
            evidence,
            kg_relations=kg_relations,
        )

        self.assertEqual(risk_level, "High")
        self.assertIn("图谱提示", mechanism)

    def test_missing_kg_relation_does_not_downgrade_high_rag_risk(self):
        service = MedicationConsultationService.__new__(MedicationConsultationService)
        service.risk_engine = RiskAssessmentStage([])
        evidence = [
            Evidence(
                source="unit",
                drug="drug_a",
                section="药物相互作用",
                snippet="合用可能显著增加严重出血风险，应避免合用。",
                score=1.0,
            )
        ]

        risk_level, _, _ = service._assess(
            ["drug_a", "drug_b"],
            evidence,
            kg_relations=[],
        )

        self.assertEqual(risk_level, "High")

    def test_child_population_restriction_affects_single_drug_risk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = ConsultationRepository(db_path=Path(tmpdir) / "consultation.sqlite3")
            service = MedicationConsultationService(records=load_test_records(), repository=repo)
            service.kg = FakeKnowledgeGraph()

            response = service.chat("儿童可以吃左氧氟沙星吗")

        self.assertEqual(response.risk_level, "High")
        self.assertIn("儿童", response.extracted_context.population)
        self.assertIn("levofloxacin", response.extracted_context.normalized_drugs)
        self.assertTrue(any("18 岁以下" in item.snippet for item in response.evidence))
        self.assertTrue(any(flag.level == "danger" and "儿童" in flag.message for flag in response.safety_flags))

    def test_elderly_population_risk_affects_single_drug_risk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = ConsultationRepository(db_path=Path(tmpdir) / "consultation.sqlite3")
            service = MedicationConsultationService(records=load_test_records(), repository=repo)
            service.kg = FakeKnowledgeGraph()

            response = service.chat("老年人正在服用华法林，需要注意什么")

        self.assertEqual(response.risk_level, "Medium")
        self.assertIn("老年人", response.extracted_context.population)
        self.assertIn("warfarin", response.extracted_context.normalized_drugs)
        self.assertTrue(any("老年" in item.snippet for item in response.evidence))
        self.assertTrue(any(flag.level == "warning" and "老年人" in flag.message for flag in response.safety_flags))

    def test_population_specific_sections_are_forced_into_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = ConsultationRepository(db_path=Path(tmpdir) / "consultation.sqlite3")
            service = MedicationConsultationService(records=load_population_test_records(), repository=repo)
            service.kg = FakeKnowledgeGraph()

            response = service.chat("老人正在服用阿魏酸哌嗪片，需要注意什么")

        self.assertEqual(response.risk_level, "Medium")
        self.assertIn("老年人", response.extracted_context.population)
        self.assertIn("阿魏酸哌嗪片", response.extracted_context.normalized_drugs)
        self.assertTrue(any(item.section == "老年用药" and "专业医师指导" in item.snippet for item in response.evidence))
        self.assertTrue(any(flag.level == "warning" and "老年人" in flag.message for flag in response.safety_flags))


if __name__ == "__main__":
    unittest.main()
