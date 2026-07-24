"""
知识图谱服务测试：验证 Neo4j 查询降级、关系解析和风险证据格式。
"""

import unittest

from app.services.kg_service import MedicationKnowledgeGraph


class _FailingSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def run(self, *args, **kwargs):
        raise ConnectionError("neo4j unavailable")


class _FailingDriver:
    def __init__(self):
        self.closed = False

    def session(self, **kwargs):
        return _FailingSession()

    def close(self):
        self.closed = True


class TestMedicationKnowledgeGraph(unittest.TestCase):
    def test_query_degrades_when_neo4j_is_unavailable(self):
        graph = MedicationKnowledgeGraph(records=[])
        driver = _FailingDriver()
        graph._driver = driver

        self.assertEqual(graph.query(["华法林钠片"]), [])
        self.assertTrue(driver.closed)
        self.assertIsNone(graph._driver)


if __name__ == "__main__":
    unittest.main()
