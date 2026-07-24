"""
药物实体识别单元测试
=====================
测试 DrugRecognitionStage 的实体抽取能力：
  1. 标准药物匹配
  2. 别名匹配
  3. 否定语境过滤
  4. 组合提及拆分
  5. 特殊人群、疾病、风险因素提取
  6. 交互引用药物补充识别
  7. 边界情况
"""

import json
import unittest
from pathlib import Path

import app.services.stages.drug_recognition as drug_recognition
from app.services.stages.drug_recognition import DrugRecognitionStage

TEST_DIR = Path(__file__).resolve().parent
DATA_PATH = TEST_DIR.parent / "data" / "processed" / "drug_knowledge_zh.json"


def load_test_records():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


class FakeExtractionLLM:
    configured = True

    def __init__(self, payload):
        self.payload = payload

    def extract_medication_entities(self, message):
        return self.payload


class FakeConsultationContextLLM:
    configured = True

    def extract_consultation_context(self, message):
        return {
            "age": 68,
            "sex": "female",
            "population": ["妊娠/备孕"],
            "conditions": ["糖尿病", "高血压"],
            "symptoms": ["感冒", "发热"],
            "medications": [
                {"mention": "二甲双胍片", "normalized": "二甲双胍片", "status": "current", "confidence": 0.95},
                {"mention": "缬沙坦胶囊", "normalized": "缬沙坦胶囊", "status": "current", "confidence": 0.98},
                {"mention": "布洛芬", "normalized": "布洛芬", "status": "intended", "confidence": 0.98},
            ],
            "ambiguous_entities": [],
        }


class TestDrugRecognitionStage(unittest.TestCase):
    """药物实体识别核心能力测试。"""

    @classmethod
    def setUpClass(cls):
        cls.records = load_test_records()
        cls.stage = DrugRecognitionStage(cls.records)

    # ─── 基本药物识别 ────────────────────────────────────────

    def test_single_drug_by_canonical(self):
        """标准药名匹配。"""
        ctx = self.stage.execute_on_text("正在服用华法林")
        self.assertIn("warfarin", ctx.normalized_drugs)

    def test_single_drug_by_alias(self):
        """别名匹配。"""
        ctx = self.stage.execute_on_text("吃了拜阿司匹灵")
        self.assertIn("aspirin", ctx.normalized_drugs)

    def test_canonical_drug_name_wins_over_polluted_alias(self):
        records = [
            {"drug": "阿司匹林肠溶片", "aliases": [], "sections": []},
            {"drug": "阿魏酸钠片", "aliases": ["阿司匹林肠溶片"], "sections": []},
            {"drug": "阿魏酸哌嗪片", "aliases": [], "sections": []},
        ]
        stage = DrugRecognitionStage(records)

        ctx = stage.execute_on_text("我65岁，肠胃炎，想吃阿司匹林肠溶片和阿魏酸哌嗪片可以吗")

        self.assertIn("阿司匹林肠溶片", ctx.normalized_drugs)
        self.assertIn("阿魏酸哌嗪片", ctx.normalized_drugs)
        self.assertNotIn("阿魏酸钠片", ctx.normalized_drugs)
        self.assertIn("老年人", ctx.population)
        self.assertIn("肠胃炎", ctx.conditions)

    def test_aspirin_common_misspelling(self):
        records = [{"drug": "阿司匹林肠溶片", "aliases": [], "sections": []}]
        stage = DrugRecognitionStage(records)

        ctx = stage.execute_on_text("阿斯匹林肠溶片可以吃吗")

        self.assertIn("阿司匹林肠溶片", ctx.normalized_drugs)

    def test_single_character_drug_name_does_not_match_inside_long_drug(self):
        records = [
            {"drug": "氧", "aliases": [], "sections": []},
            {"drug": "氢氧化铝片", "aliases": [], "sections": []},
            {"drug": "布洛芬胶囊", "aliases": [], "sections": []},
        ]
        stage = DrugRecognitionStage(records)

        ctx = stage.execute_on_text("我7岁，发烧了，想吃布洛芬胶囊和氢氧化铝片可以吗")

        self.assertIn("布洛芬胶囊", ctx.normalized_drugs)
        self.assertIn("氢氧化铝片", ctx.normalized_drugs)
        self.assertNotIn("氧", ctx.normalized_drugs)

    def test_multiple_drugs(self):
        """多药物同时识别。"""
        ctx = self.stage.execute_on_text("华法林和布洛芬一起吃可以吗")
        self.assertIn("warfarin", ctx.normalized_drugs)
        self.assertIn("ibuprofen", ctx.normalized_drugs)

    def test_english_drug_name(self):
        """英文药名匹配。"""
        ctx = self.stage.execute_on_text("taking warfarin and ibuprofen")
        self.assertIn("warfarin", ctx.normalized_drugs)
        self.assertIn("ibuprofen", ctx.normalized_drugs)

    def test_combination_separator(self):
        """组合提及的各种分隔符。"""
        scenarios = [
            "华法林+布洛芬",
            "华法林、布洛芬",
            "华法林与布洛芬",
            "华法林及布洛芬",
        ]
        for q in scenarios:
            with self.subTest(q=q):
                ctx = self.stage.execute_on_text(q)
                self.assertIn("warfarin", ctx.normalized_drugs, f"Failed for: {q}")
                self.assertIn("ibuprofen", ctx.normalized_drugs, f"Failed for: {q}")

    # ─── 否定语境 ────────────────────────────────────────────

    def test_negation_not_taking(self):
        """'不吃' 否定语境。"""
        ctx = self.stage.execute_on_text("我不吃华法林，可以吃布洛芬吗")
        self.assertNotIn("warfarin", ctx.normalized_drugs,
                         "warfarin 应被否定语境排除")
        self.assertIn("ibuprofen", ctx.normalized_drugs)

    def test_negation_never_take(self):
        """'没吃' 否定语境。"""
        ctx = self.stage.execute_on_text("没吃华法林")
        self.assertNotIn("warfarin", ctx.normalized_drugs)

    def test_negation_stop_taking(self):
        """'停用' 否定语境。"""
        ctx = self.stage.execute_on_text("停了华法林")
        # "停用"模式应该能匹配
        self.assertNotIn("warfarin", ctx.normalized_drugs)

    def test_negation_not_recommended(self):
        """'不推荐服用' 否定语境。"""
        ctx = self.stage.execute_on_text("不推荐服用华法林")
        self.assertNotIn("warfarin", ctx.normalized_drugs)

    def test_negation_no_contradiction(self):
        """否定不应错误排除非目标药物。"""
        ctx = self.stage.execute_on_text("不吃阿司匹林，但还在吃华法林")
        self.assertNotIn("aspirin", ctx.normalized_drugs)
        self.assertIn("warfarin", ctx.normalized_drugs)

    # ─── 补充药物识别 ────────────────────────────────────────

    def test_interaction_ref_drug(self):
        """补齐的交互引用药物应被识别。"""
        ctx = self.stage.execute_on_text("吃了甲氨蝶呤")
        self.assertIn("methotrexate", ctx.normalized_drugs)

    def test_interaction_ref_chinese_name(self):
        """交互引用药物中文名。"""
        ctx = self.stage.execute_on_text("环孢素和他克莫司")
        self.assertIn("cyclosporine", ctx.normalized_drugs)

    def test_interaction_ref_lithium(self):
        """补充药物：锂剂。"""
        ctx = self.stage.execute_on_text("碳酸锂")
        self.assertIn("lithium", ctx.normalized_drugs)

    def test_interaction_ref_amiodarone(self):
        """补充药物：胺碘酮。"""
        ctx = self.stage.execute_on_text("可达龙")
        self.assertIn("amiodarone", ctx.normalized_drugs)

    # ─── 特殊人群识别 ────────────────────────────────────────

    def test_population_elderly(self):
        """老年人识别。"""
        ctx = self.stage.execute_on_text("65岁男性")
        self.assertIn("老年人", ctx.population)

    def test_population_child_by_arabic_age(self):
        """阿拉伯数字年龄应映射到儿童。"""
        ctx = self.stage.execute_on_text("我7岁，发烧了，想吃布洛芬胶囊和感冒清热颗粒可以吗")
        self.assertIn("儿童", ctx.population)
        self.assertNotIn("老年人", ctx.population)

    def test_population_child_by_chinese_age(self):
        """中文数字年龄应映射到儿童。"""
        ctx = self.stage.execute_on_text("我七岁，发烧了")
        self.assertIn("儿童", ctx.population)
        self.assertNotIn("老年人", ctx.population)

    def test_population_elderly_by_chinese_age(self):
        """中文数字老年年龄应映射到老年人。"""
        ctx = self.stage.execute_on_text("我六十五岁，想咨询用药")
        self.assertIn("老年人", ctx.population)

    def test_population_adult_age_not_special_population(self):
        """18 到 64 岁不应映射为儿童或老年人。"""
        ctx = self.stage.execute_on_text("我30岁，发烧了")
        self.assertNotIn("儿童", ctx.population)
        self.assertNotIn("老年人", ctx.population)

    def test_population_pregnant(self):
        """孕妇识别。"""
        ctx = self.stage.execute_on_text("怀孕期间")
        self.assertIn("妊娠/备孕", ctx.population)

    def test_population_children(self):
        """儿童识别。"""
        ctx = self.stage.execute_on_text("儿童用药")
        self.assertIn("儿童", ctx.population)

    def test_population_renal(self):
        """肾功能识别。"""
        ctx = self.stage.execute_on_text("肾功能不全患者")
        self.assertIn("肾功能相关", ctx.population)

    def test_llm_context_only_resolves_medication_mentions(self):
        original_flag = drug_recognition.LLM_ENABLE_EXTRACTION
        try:
            drug_recognition.LLM_ENABLE_EXTRACTION = True
            stage = DrugRecognitionStage(
                [
                    {"drug": "盐酸二甲双胍片", "aliases": [], "sections": []},
                    {"drug": "盐酸二甲双胍缓释片", "aliases": [], "sections": []},
                    {"drug": "缬沙坦胶囊", "aliases": [], "sections": []},
                    {"drug": "布洛芬片", "aliases": [], "sections": []},
                    {"drug": "布洛芬胶囊", "aliases": [], "sections": []},
                    {"drug": "感冒片", "aliases": [], "sections": []},
                ]
            )
            stage.llm_client = FakeConsultationContextLLM()

            ctx = stage.execute_on_text(
                "我今年68岁，女，正在怀孕，有糖尿病和高血压，最近感冒发热，"
                "长期吃二甲双胍片和缬沙坦胶囊，现在想吃布洛芬退烧，可以吗？"
            )
        finally:
            drug_recognition.LLM_ENABLE_EXTRACTION = original_flag

        self.assertIn("妊娠/备孕", ctx.population)
        self.assertIn("老年人", ctx.population)
        self.assertIn("糖尿病", ctx.conditions)
        self.assertIn("高血压", ctx.conditions)
        self.assertIn("感冒", ctx.conditions)
        self.assertIn("盐酸二甲双胍片", ctx.normalized_drugs)
        self.assertIn("缬沙坦胶囊", ctx.normalized_drugs)
        self.assertTrue(any(group.mention == "布洛芬" for group in ctx.candidate_drug_groups))
        self.assertFalse(any(group.mention == "感冒" for group in ctx.candidate_drug_groups))

    # ─── 疾病识别 ────────────────────────────────────────────

    def test_condition_diabetes(self):
        ctx = self.stage.execute_on_text("糖尿病患者")
        self.assertIn("糖尿病", ctx.conditions)

    def test_condition_atrial_fibrillation(self):
        ctx = self.stage.execute_on_text("房颤患者")
        self.assertIn("房颤", ctx.conditions)

    def test_condition_coronary_heart_disease(self):
        ctx = self.stage.execute_on_text("冠心病")
        self.assertIn("冠心病", ctx.conditions)

    # ─── 风险因素识别 ────────────────────────────────────────

    def test_risk_bleeding(self):
        ctx = self.stage.execute_on_text("有出血风险")
        self.assertIn("出血", ctx.risk_factors)

    def test_risk_hypotension(self):
        ctx = self.stage.execute_on_text("低血压")
        self.assertIn("低血压", ctx.risk_factors)

    # ─── 边界情况 ────────────────────────────────────────────

    def test_empty_question(self):
        """空输入应返回空结果。"""
        ctx = self.stage.execute_on_text("")
        self.assertEqual(ctx.normalized_drugs, [])

    def test_no_drug_mentioned(self):
        """未提及任何药物。"""
        ctx = self.stage.execute_on_text("我今天感觉不舒服")
        self.assertEqual(ctx.normalized_drugs, [])

    def test_short_question_with_drug(self):
        """极短输入。"""
        ctx = self.stage.execute_on_text("华法林")
        self.assertIn("warfarin", ctx.normalized_drugs)

    def test_very_long_question(self):
        """超长输入。"""
        long_q = "患者" + "华法林" * 100 + "可以吗"
        ctx = self.stage.execute_on_text(long_q)
        self.assertIn("warfarin", ctx.normalized_drugs)

    def test_partial_match_no_false_positive(self):
        """部分匹配不应产生假阳性。"""
        # "华法"不应匹配"华法林"
        ctx = self.stage.execute_on_text("华法可以吗")
        self.assertEqual(ctx.normalized_drugs, [])

    # ─── LLM 口语药品抽取 ────────────────────────────────────

    def test_llm_drug_class_kept_ambiguous(self):
        """头孢等类别词不应硬映射为具体药物。"""
        original_flag = drug_recognition.LLM_ENABLE_EXTRACTION
        try:
            drug_recognition.LLM_ENABLE_EXTRACTION = True
            stage = DrugRecognitionStage(self.records)
            stage.llm_client = FakeExtractionLLM(
                {
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
            )

            ctx = stage.execute_on_text("我吃了头孢，可以再吃布洛芬吗")
        finally:
            drug_recognition.LLM_ENABLE_EXTRACTION = original_flag

        self.assertIn("ibuprofen", ctx.normalized_drugs)
        self.assertNotIn("cephalosporin", ctx.normalized_drugs)
        self.assertEqual(ctx.ambiguous_entities[0]["mention"], "头孢")
        self.assertEqual(ctx.ambiguous_entities[0]["entity_type"], "drug_class")

    def test_llm_compound_product_kept_ambiguous(self):
        """感冒灵应作为复方药提示，不参与具体相互作用计算。"""
        original_flag = drug_recognition.LLM_ENABLE_EXTRACTION
        try:
            drug_recognition.LLM_ENABLE_EXTRACTION = True
            stage = DrugRecognitionStage(self.records)
            stage.llm_client = FakeExtractionLLM(
                {
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
            )

            ctx = stage.execute_on_text("感冒灵能不能和布洛芬一起吃")
        finally:
            drug_recognition.LLM_ENABLE_EXTRACTION = original_flag

        self.assertIn("ibuprofen", ctx.normalized_drugs)
        self.assertEqual(ctx.ambiguous_entities[0]["mention"], "感冒灵")
        self.assertEqual(ctx.ambiguous_entities[0]["entity_type"], "compound_product")
        self.assertIn("possible_ingredients", ctx.ambiguous_entities[0])


if __name__ == "__main__":
    unittest.main()
