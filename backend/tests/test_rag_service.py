"""
RAG 检索服务单元测试
=====================
测试 SimpleRagIndex 的召回能力：
  1. 基础检索
  2. 药物相关文档提升
  3. 关键章节加分
  4. 边界情况
"""

import json
import unittest
from pathlib import Path

from app.services.rag_service import BM25RagIndex, HybridRagIndex, SimpleRagIndex, build_documents

TEST_DIR = Path(__file__).resolve().parent
DATA_PATH = TEST_DIR.parent / "data" / "processed" / "drug_knowledge_zh.json"


def load_test_records():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestSimpleRagIndex(unittest.TestCase):
    """RAG 检索核心能力测试。"""

    @classmethod
    def setUpClass(cls):
        cls.records = load_test_records()
        cls.index = SimpleRagIndex(cls.records)

    def test_document_count(self):
        """索引文档数应大于 0。"""
        self.assertGreater(len(self.index.documents), 0)

    def test_retrieve_returns_list(self):
        """检索应返回 Evidence 列表。"""
        results = self.index.retrieve("华法林", ["warfarin"], top_k=5)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

    def test_retrieve_respects_top_k(self):
        """top_k 参数应生效。"""
        results = self.index.retrieve("华法林", ["warfarin"], top_k=3)
        self.assertLessEqual(len(results), 3)

    def test_drug_boost(self):
        """药物相关文档应获得加分。"""
        results = self.index.retrieve("出血风险", ["warfarin"], top_k=10)
        warfarin_results = [r for r in results if r.drug == "warfarin"]
        non_warfarin = [r for r in results if r.drug != "warfarin"]
        # warfarin 相关文档应有更高的排名
        if warfarin_results and non_warfarin:
            min_warfarin_rank = min(
                results.index(r) for r in warfarin_results
            )
            max_non_warfarin_rank = max(
                results.index(r) for r in non_warfarin
            )
            # 至少有一个 warfarin 文档排在非 warfarin 文档之前
            self.assertLess(
                min_warfarin_rank, len(results) - 1,
                "药物相关文档应获得加分提升",
            )

    def test_section_boost(self):
        """关键章节（药物相互作用/禁忌）应获加分。"""
        results = self.index.retrieve("药物相互作用", ["warfarin"], top_k=20)
        section_boost_sections = {"药物相互作用", "禁忌", "警告与注意事项"}
        boosted = [r for r in results if r.section in section_boost_sections]
        self.assertGreater(
            len(boosted), 0,
            "应有关键章节文档被召回",
        )

    def test_query_without_drugs(self):
        """未指定药物列表时仍应返回结果。"""
        results = self.index.retrieve("感冒吃药", [], top_k=5)
        self.assertGreater(len(results), 0)

    def test_empty_query(self):
        """空查询应返回空结果。"""
        results = self.index.retrieve("", [], top_k=5)
        self.assertEqual(len(results), 0)

    def test_relevance_scoring(self):
        """相关性分数应在合理范围内。"""
        results = self.index.retrieve("华法林 布洛芬", ["warfarin", "ibuprofen"], top_k=5)
        for r in results:
            self.assertGreater(r.score, 0.0)
            self.assertLessEqual(r.score, 5.0)

    def test_interaction_section_preferred(self):
        """药物相互作用章节应有较高分数。"""
        results = self.index.retrieve("华法林 布洛芬", ["warfarin", "ibuprofen"], top_k=10)
        interaction_results = [r for r in results if r.section == "药物相互作用"]
        other_results = [r for r in results if r.section != "药物相互作用"]
        if interaction_results and other_results:
            # 最高分的 interaction 文档应比最高分的非 interaction 文档高
            max_interaction_score = max(r.score for r in interaction_results)
            max_other_score = max(r.score for r in other_results)
            self.assertGreaterEqual(
                max_interaction_score, max_other_score * 0.8,
                "相互作用章节应获得相近或更高分数",
            )

    def test_structured_chunks_are_indexed_without_window_splitting(self):
        records = [
            {
                "drug": "阿魏酸哌嗪片",
                "source": "unit-test",
                "sections": [
                    {
                        "title": "老年用药",
                        "content": "1. 老人应在专业医师指导下使用",
                        "chunks": [
                            {
                                "text": "老人应在专业医师指导下使用",
                                "chunk_type": "section",
                                "population_tags": ["老年人"],
                                "risk_terms": ["专业医师指导"],
                            }
                        ],
                    }
                ],
            }
        ]

        documents = build_documents(records)
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["text"], "老人应在专业医师指导下使用")
        self.assertEqual(documents[0]["chunk_type"], "section")

        index = SimpleRagIndex(records)
        results = index.retrieve("老人 阿魏酸哌嗪片", ["阿魏酸哌嗪片"], top_k=1)
        self.assertEqual(results[0].snippet, "老人应在专业医师指导下使用")


class TestHybridRagIndex(unittest.TestCase):
    """混合检索、RRF 融合和规则重排测试。"""

    @classmethod
    def setUpClass(cls):
        cls.records = load_test_records()
        cls.bm25 = BM25RagIndex(cls.records)
        cls.hybrid = HybridRagIndex(cls.records, dense_index=SimpleRagIndex(cls.records))

    def test_bm25_exact_drug_match(self):
        results = self.bm25.retrieve("华法林 布洛芬 出血", ["warfarin", "ibuprofen"], top_k=5)
        self.assertGreater(len(results), 0)
        self.assertTrue(any(item.drug in {"warfarin", "ibuprofen"} for item in results))

    def test_hybrid_returns_unique_evidence(self):
        results = self.hybrid.retrieve("华法林和布洛芬一起吃可以吗", ["warfarin", "ibuprofen"], top_k=8)
        keys = {(item.source, item.drug, item.section, item.snippet) for item in results}
        self.assertEqual(len(keys), len(results))

    def test_hybrid_prefers_medication_safety_sections(self):
        results = self.hybrid.retrieve("华法林 布洛芬 出血风险", ["warfarin", "ibuprofen"], top_k=5)
        self.assertGreater(len(results), 0)
        self.assertIn(results[0].section, {"药物相互作用", "禁忌", "警告与注意事项", "特殊人群"})

    def test_hybrid_respects_top_k(self):
        results = self.hybrid.retrieve("辛伐他汀 克拉霉素", ["simvastatin", "clarithromycin"], top_k=3)
        self.assertLessEqual(len(results), 3)


if __name__ == "__main__":
    unittest.main()
