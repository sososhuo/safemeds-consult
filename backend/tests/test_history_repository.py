"""
模块用途：验证 SQLite 历史记录仓储的增删查改能力。
历史记录 Repository 单元测试
=============================
测试 SQLite 数据访问层的 CRUD 操作。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.repositories.history_repository import HistoryRepository
from app.schemas.analysis import AnalysisReport, ExtractedContext, Evidence


def _make_sample_report() -> AnalysisReport:
    return AnalysisReport(
        conclusion="华法林与布洛芬存在 High 级用药风险。",
        risk_level="High",
        mechanism="出血风险显著增加。",
        recommendation="避免无医嘱合用。",
        confidence=0.86,
        extracted_context=ExtractedContext(
            drugs=["warfarin", "ibuprofen"],
            normalized_drugs=["warfarin", "ibuprofen"],
            population=["老年人"],
            conditions=[],
            risk_factors=[],
        ),
        evidence=[
            Evidence(
                source="测试知识库",
                drug="warfarin",
                section="药物相互作用",
                snippet="阿司匹林与华法林合用可显著增加出血风险。",
                score=0.85,
            )
        ],
        limitations=[],
        safety_notice="本系统仅用于面试 Demo 展示。",
        agent_trace=[],
    )


class TestHistoryRepository(unittest.TestCase):
    """SQLite 历史记录 CRUD 测试。"""

    def setUp(self):
        # 使用临时数据库
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_safemeds.sqlite3"
        self.repo = HistoryRepository(db_path=self.db_path)

    def tearDown(self):
        for f in [self.db_path]:
            if f.exists():
                f.unlink()
        os.rmdir(self.tmpdir)

    def test_create_and_list(self):
        """创建记录后可列表查询。"""
        report = _make_sample_report()
        detail = self.repo.create("华法林和布洛芬", report)
        self.assertIsNotNone(detail.id)
        self.assertEqual(detail.risk_level, "High")
        items = self.repo.list(limit=10)
        self.assertEqual(len(items), 1)

    def test_create_multiple_and_list_order(self):
        """多条记录应逆序返回（最新在前）。"""
        for i in range(3):
            r = _make_sample_report()
            r.risk_level = ["Low", "Medium", "High"][i]
            self.repo.create(f"问题 {i}", r)
        items = self.repo.list(limit=3)
        self.assertEqual(len(items), 3)
        # 最新创建的排第一
        self.assertEqual(items[0].risk_level, "High")

    def test_get_by_id(self):
        """按 ID 查询应返回完整详情。"""
        report = _make_sample_report()
        detail = self.repo.create("测试问题", report)
        fetched = self.repo.get(detail.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.question, "测试问题")
        self.assertEqual(fetched.report.risk_level, "High")

    def test_get_nonexistent(self):
        """查询不存在的 ID 应返回 None。"""
        result = self.repo.get(99999)
        self.assertIsNone(result)

    def test_delete(self):
        """删除应成功。"""
        detail = self.repo.create("待删除", _make_sample_report())
        deleted = self.repo.delete(detail.id)
        self.assertTrue(deleted)
        self.assertIsNone(self.repo.get(detail.id))

    def test_delete_nonexistent(self):
        """删除不存在的记录应返回 False。"""
        result = self.repo.delete(99999)
        self.assertFalse(result)

    def test_list_limit(self):
        """limit 参数应生效。"""
        for i in range(10):
            self.repo.create(f"问题 {i}", _make_sample_report())
        items_5 = self.repo.list(limit=5)
        self.assertLessEqual(len(items_5), 5)
        items_20 = self.repo.list(limit=20)
        self.assertEqual(len(items_20), 10)

    def test_report_roundtrip(self):
        """Report JSON 序列化/反序列化应完整保留字段。"""
        report = _make_sample_report()
        detail = self.repo.create("华法林和布洛芬", report)
        fetched = self.repo.get(detail.id)
        self.assertEqual(fetched.report.conclusion, report.conclusion)
        self.assertEqual(fetched.report.risk_level, report.risk_level)
        self.assertEqual(fetched.report.recommendation, report.recommendation)
        self.assertEqual(fetched.report.confidence, report.confidence)
        self.assertEqual(len(fetched.report.evidence), len(report.evidence))


if __name__ == "__main__":
    unittest.main()
