"""
风险评估 Stage 单元测试
========================
测试 RiskAssessmentStage 的判级逻辑：
  1. 已知药物对交互匹配 (pair_hit)
  2. 基于证据关键词的 High/Medium/Low/Unknown 判定
  3. 边界情况：无药物、无证据、空列表
"""

import json
import unittest
from pathlib import Path

from app.schemas.analysis import Evidence, ExtractedContext
from app.services.stages.risk_assessment import RiskAssessmentStage
from app.services.stages.base import StageContext

TEST_DIR = Path(__file__).resolve().parent
DATA_PATH = TEST_DIR.parent / "data" / "processed" / "drug_knowledge_zh.json"


def load_test_records():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestRiskAssessmentStage(unittest.TestCase):
    """风险评估判级逻辑测试。"""

    @classmethod
    def setUpClass(cls):
        cls.records = load_test_records()
        cls.stage = RiskAssessmentStage(cls.records)

    def _make_ctx(self, drugs, evidence=None, risk_factors=None) -> StageContext:
        ctx = StageContext(question="")
        ctx.extracted = ExtractedContext(
            drugs=drugs,
            normalized_drugs=drugs,
            population=[],
            conditions=[],
            risk_factors=risk_factors or [],
        )
        ctx.evidence = evidence or []
        return ctx

    @staticmethod
    def _evidence(snippet: str, score: float = 0.5) -> Evidence:
        return Evidence(
            source="test",
            drug="test",
            section="test",
            snippet=snippet,
            score=score,
        )

    # ─── 已知药物交互对匹配 ────────────────────────────────────

    def test_known_pair_high(self):
        """已知 High 级交互对对返回 High。"""
        ctx = self._make_ctx(["warfarin", "ibuprofen"])
        result = self.stage.execute(ctx)
        self.assertEqual(result.risk_level, "High")
        self.assertIn("warfarin", str(result.pair_hit))
        self.assertIn("ibuprofen", str(result.pair_hit))

    def test_known_pair_medium(self):
        """已知 Medium 级交互对。"""
        ctx = self._make_ctx(["amlodipine", "simvastatin"])
        result = self.stage.execute(ctx)
        self.assertEqual(result.risk_level, "Medium")

    def test_known_pair_recommendation(self):
        """已知交互对返回具体建议。"""
        ctx = self._make_ctx(["warfarin", "aspirin"])
        result = self.stage.execute(ctx)
        self.assertEqual(result.risk_level, "High")
        self.assertIn("INR", result.mechanism)

    # ─── 基于证据关键词 ───────────────────────────────────────

    def test_no_evidence_unknown(self):
        """无证据返回 Unknown。"""
        ctx = self._make_ctx(["warfarin"], evidence=[])
        result = self.stage.execute(ctx)
        self.assertEqual(result.risk_level, "Unknown")

    def test_high_keyword_in_evidence(self):
        """证据含严重关键词返回 High。"""
        evidence = [self._evidence("可能导致严重不良反应和禁忌")]
        ctx = self._make_ctx(["warfarin"], evidence=evidence)
        result = self.stage.execute(ctx)
        self.assertEqual(result.risk_level, "High")

    def test_medium_keyword_in_evidence(self):
        """证据含中风险关键词返回 Medium。"""
        evidence = [self._evidence("需要监测肾功能和出血情况")]
        ctx = self._make_ctx(["warfarin"], evidence=evidence)
        result = self.stage.execute(ctx)
        self.assertEqual(result.risk_level, "Medium")

    def test_no_risk_keyword_low(self):
        """证据无风险关键词返回 Low。"""
        evidence = [self._evidence("在正常剂量下耐受良好")]
        ctx = self._make_ctx(["warfarin"], evidence=evidence)
        result = self.stage.execute(ctx)
        self.assertEqual(result.risk_level, "Low")

    # ─── 边界情况 ─────────────────────────────────────────────

    def test_single_drug_only(self):
        """单一药物（无交互对）应基于证据判断。"""
        evidence = [self._evidence("需要监测出血倾向")]
        ctx = self._make_ctx(["warfarin"], evidence=evidence)
        result = self.stage.execute(ctx)
        self.assertEqual(result.risk_level, "Medium")

    def test_no_drugs(self):
        """空药物列表应返回 Unknown。"""
        ctx = self._make_ctx([], evidence=[])
        result = self.stage.execute(ctx)
        self.assertEqual(result.risk_level, "Unknown")

    def test_multiple_evidence_aggregation(self):
        """多条证据综合判断。"""
        evidence = [
            self._evidence("普通感冒对症治疗", 0.3),
            self._evidence("避免与肝素合用", 0.6),
            self._evidence("肾功能监测", 0.4),
        ]
        ctx = self._make_ctx(["aspirin"], evidence=evidence)
        result = self.stage.execute(ctx)
        # "避免合用" 在 HIGH_PATTERNS 中？
        # "避免合用" -> in HIGH_PATTERNS? Yes: "避免合用" is in HIGH_PATTERNS
        self.assertEqual(result.risk_level, "High")

    def test_pair_hit_overrides_evidence(self):
        """药物对匹配优先级高于证据关键词。"""
        evidence = [self._evidence("耐受良好安全")]
        ctx = self._make_ctx(["warfarin", "ibuprofen"], evidence=evidence)
        result = self.stage.execute(ctx)
        # pair_hit 应为 High（无论证据说什么）
        self.assertEqual(result.risk_level, "High")


if __name__ == "__main__":
    unittest.main()
