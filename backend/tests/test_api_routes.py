"""
API 路由集成测试
=================
测试 FastAPI 路由层的请求/响应。
"""

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.data_store import load_knowledge
from app.main import app

TEST_DIR = Path(__file__).resolve().parent
DATA_PATH = TEST_DIR.parent / "data" / "processed" / "drug_knowledge_zh.json"


class TestAPIRoutes(unittest.TestCase):
    """FastAPI 路由集成测试。"""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_endpoint(self):
        """健康检查应返回 200 和索引统计。"""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("indexed_documents", data)
        self.assertIn("available_drugs", data)
        self.assertGreater(data["indexed_documents"], 0)
        self.assertGreater(len(data["available_drugs"]), 0)

    def test_analyze_valid(self):
        """有效分析请求应返回 HistoryDetail。"""
        resp = self.client.post("/api/analyze", json={"question": "华法林和布洛芬"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("id", data)
        self.assertIn("report", data)
        self.assertEqual(data["report"]["risk_level"], "High")

    def test_analyze_question_too_short(self):
        """过短问题应返回 422。"""
        resp = self.client.post("/api/analyze", json={"question": "A"})
        self.assertEqual(resp.status_code, 422)

    def test_analyze_missing_field(self):
        """缺少 question 字段应返回 422。"""
        resp = self.client.post("/api/analyze", json={})
        self.assertEqual(resp.status_code, 422)

    def test_history_list_default(self):
        """历史列表默认返回 30 条。"""
        resp = self.client.get("/api/history")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)

    def test_history_list_with_limit(self):
        """指定 limit 参数。"""
        resp = self.client.get("/api/history?limit=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertLessEqual(len(data), 5)

    def test_history_get_nonexistent(self):
        """获取不存在的历史应返回 404。"""
        resp = self.client.get("/api/history/99999")
        self.assertEqual(resp.status_code, 404)

    def test_history_delete_nonexistent(self):
        """删除不存在的历史应返回 404。"""
        resp = self.client.delete("/api/history/99999")
        self.assertEqual(resp.status_code, 404)

    def test_analyze_saves_to_history(self):
        """分析后应能在历史列表中查到。"""
        resp = self.client.post("/api/analyze", json={"question": "测试问题华法林"})
        self.assertEqual(resp.status_code, 200)
        detail = resp.json()

        # 从历史中读取
        hist_resp = self.client.get(f"/api/history/{detail['id']}")
        self.assertEqual(hist_resp.status_code, 200)
        self.assertEqual(hist_resp.json()["question"], "测试问题华法林")

    def test_full_cycle_create_read_delete(self):
        """完整 CRUD 周期。"""
        # CREATE
        resp = self.client.post("/api/analyze", json={"question": "华法林和布洛芬"})
        self.assertEqual(resp.status_code, 200)
        item_id = resp.json()["id"]

        # READ
        resp = self.client.get(f"/api/history/{item_id}")
        self.assertEqual(resp.status_code, 200)

        # DELETE
        resp = self.client.delete(f"/api/history/{item_id}")
        self.assertEqual(resp.status_code, 200)

        # VERIFY DELETED
        resp = self.client.get(f"/api/history/{item_id}")
        self.assertEqual(resp.status_code, 404)

    def test_report_structure(self):
        """分析报告应包含所有预期字段。"""
        resp = self.client.post("/api/analyze", json={"question": "华法林和布洛芬"})
        data = resp.json()["report"]
        expected_fields = [
            "conclusion", "risk_level", "mechanism", "recommendation",
            "confidence", "extracted_context", "evidence", "limitations",
            "safety_notice", "agent_trace",
        ]
        for field in expected_fields:
            self.assertIn(field, data, f"缺少字段: {field}")

        # 检查 structural 子字段
        ctx = data["extracted_context"]
        for f in ["drugs", "normalized_drugs", "population", "conditions", "risk_factors"]:
            self.assertIn(f, ctx)

    def test_agent_trace_in_response(self):
        """响应应包含 4 个 Stage 的 Trace。"""
        resp = self.client.post("/api/analyze", json={"question": "华法林和布洛芬"})
        traces = resp.json()["report"]["agent_trace"]
        self.assertEqual(len(traces), 4)
        expected_names = [
            "药物识别 Stage",
            "RAG 检索 Stage",
            "风险评估 Stage",
            "报告生成 Stage",
        ]
        for i, name in enumerate(expected_names):
            self.assertEqual(traces[i]["agent"], name)
            self.assertEqual(traces[i]["status"], "完成")


if __name__ == "__main__":
    unittest.main()
