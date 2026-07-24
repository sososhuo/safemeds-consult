"""
模块用途：验证完整药物分析 Pipeline 从识别到报告生成的端到端行为。
Pipeline 端到端集成测试
=========================
验证完整分析管线从输入到输出的每一环节。
使用预设测试用例覆盖常见场景。
"""

import json
import unittest
from pathlib import Path

from app.services.agent_service import SafeMedsPipeline

TEST_DIR = Path(__file__).resolve().parent
DATA_PATH = TEST_DIR.parent / "data" / "processed" / "drug_knowledge_zh.json"


def load_test_records():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestSafeMedsPipeline(unittest.TestCase):
    """完整 Pipeline 集成测试。"""

    @classmethod
    def setUpClass(cls):
        cls.records = load_test_records()
        cls.pipeline = SafeMedsPipeline(cls.records)

    def test_full_analysis_returns_report(self):
        """完整分析应返回 AnalysisReport。"""
        report = self.pipeline.analyze("华法林和布洛芬一起吃可以吗")
        self.assertIsNotNone(report)
        self.assertIn(report.risk_level, ["High", "Medium", "Low", "Unknown"])

    def test_high_risk_interaction(self):
        """已知高危组合应返回 High。"""
        report = self.pipeline.analyze("华法林和布洛芬")
        self.assertEqual(report.risk_level, "High")
        self.assertGreaterEqual(report.confidence, 0.8)

    def test_medium_risk_interaction(self):
        """中风险组合。"""
        report = self.pipeline.analyze("氨氯地平 辛伐他汀")
        self.assertEqual(report.risk_level, "Medium")

    def test_elderly_population_detected(self):
        """老年人群应被识别。"""
        report = self.pipeline.analyze("65岁男性，服用华法林")
        self.assertIn("老年人", report.extracted_context.population)

    def test_agent_trace_present(self):
        """Agent Trace 应按顺序包含所有阶段。"""
        report = self.pipeline.analyze("华法林和布洛芬")
        expected_stages = [
            "药物识别 Stage",
            "RAG 检索 Stage",
            "风险评估 Stage",
            "报告生成 Stage",
        ]
        trace_names = [t.agent for t in report.agent_trace]
        self.assertEqual(trace_names, expected_stages)

    def test_all_traces_completed(self):
        """所有 Trace 应标记为完成。"""
        report = self.pipeline.analyze("华法林和布洛芬")
        for t in report.agent_trace:
            self.assertEqual(t.status, "完成")

    def test_evidence_in_report(self):
        """报告应包含证据溯源。"""
        report = self.pipeline.analyze("华法林和布洛芬")
        self.assertGreater(len(report.evidence), 0)

    def test_safety_notice_present(self):
        """报告应包含安全声明。"""
        report = self.pipeline.analyze("华法林")
        self.assertIn("不提供诊断", report.safety_notice)

    def test_confidence_range(self):
        """置信度应在 0-1 之间。"""
        report = self.pipeline.analyze("华法林和布洛芬")
        self.assertGreaterEqual(report.confidence, 0.0)
        self.assertLessEqual(report.confidence, 1.0)

    def test_unknown_risk_question(self):
        """知识库中不存在的药物应返回 Unknown。"""
        report = self.pipeline.analyze("吃了某种不存在的药物")
        # 不会识别到任何药物，因此无法判定
        self.assertIn(report.risk_level, ["Unknown", "Low"])

    def test_extracted_context_structure(self):
        """抽取的结构化信息应包含所有字段。"""
        report = self.pipeline.analyze("65岁糖尿病患者服用二甲双胍")
        ctx = report.extracted_context
        self.assertIsNotNone(ctx.drugs)
        self.assertIsNotNone(ctx.normalized_drugs)
        self.assertIsNotNone(ctx.population)
        self.assertIsNotNone(ctx.conditions)
        self.assertIsNotNone(ctx.risk_factors)

    def test_limitations_generated(self):
        """报告应包含局限性说明。"""
        report = self.pipeline.analyze("华法林")
        self.assertGreater(len(report.limitations), 0)

    def test_demo_question_warfarin_ibuprofen(self):
        """演示问题：华法林+布洛芬（面试经典场景）。"""
        report = self.pipeline.analyze(
            "65岁男性，长期服用华法林，最近感冒发热想吃布洛芬，可以吗？"
        )
        self.assertEqual(report.risk_level, "High")
        self.assertIn("warfarin", report.extracted_context.normalized_drugs)
        self.assertIn("ibuprofen", report.extracted_context.normalized_drugs)

    def test_demo_question_simvastatin_clarithromycin(self):
        """演示问题：辛伐他汀+克拉霉素。"""
        report = self.pipeline.analyze(
            "患者正在吃辛伐他汀，医生开了克拉霉素，会有什么风险？"
        )
        self.assertEqual(report.risk_level, "High")
        self.assertIn("simvastatin", report.extracted_context.normalized_drugs)
        self.assertIn("clarithromycin", report.extracted_context.normalized_drugs)

    def test_demo_question_sildenafil_nitroglycerin(self):
        """演示问题：硝酸甘油+西地那非。"""
        report = self.pipeline.analyze(
            "冠心病患者用了硝酸甘油，还能服用西地那非吗？"
        )
        self.assertIn("nitroglycerin", report.extracted_context.normalized_drugs)
        self.assertIn("sildenafil", report.extracted_context.normalized_drugs)

    def test_demo_question_metformin_contrast(self):
        """演示问题：二甲双胍+造影剂。"""
        report = self.pipeline.analyze(
            "糖尿病患者服用二甲双胍，明天要做增强CT，有什么需要注意？"
        )
        self.assertIn("metformin", report.extracted_context.normalized_drugs)
        self.assertIn("contrast media", report.extracted_context.normalized_drugs)


if __name__ == "__main__":
    unittest.main()
