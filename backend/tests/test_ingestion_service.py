"""
模块用途：验证多格式文档摄入、切片和知识库导出逻辑。
混合文档摄入测试
================
覆盖 PDF/JSON/CSV/TXT 解析、chunk 输出和知识库兼容导出。
"""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.services.ingestion_service import DocumentIngestionService


class TestDocumentIngestionService(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.service = DocumentIngestionService()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_ingest_json_csv_txt_and_export_records(self):
        (self.root / "warfarin.json").write_text(
            json.dumps(
                [
                    {
                        "drug": "warfarin",
                        "aliases": ["华法林"],
                        "sections": [
                            {
                                "title": "药物相互作用",
                                "content": "华法林与布洛芬合用时可能增加出血风险，应监测 INR。",
                            }
                        ],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with (self.root / "metformin.csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["drug", "section", "content"])
            writer.writeheader()
            writer.writerow(
                {
                    "drug": "metformin",
                    "section": "特殊人群",
                    "content": "二甲双胍在肾功能不全和增强 CT 造影场景中需要评估。",
                }
            )
        (self.root / "阿司匹林说明书.txt").write_text(
            "禁忌：活动性消化道出血患者应避免使用阿司匹林。",
            encoding="utf-8",
        )

        chunks, report = self.service.ingest_path(self.root)
        output = self.root / "chunks.json"
        knowledge_output = self.root / "knowledge.json"
        self.service.export_chunks(chunks, output)
        self.service.export_knowledge_records(chunks, knowledge_output)

        self.assertEqual(report.failed_count, 0)
        self.assertGreaterEqual(report.chunk_count, 3)
        self.assertTrue(output.exists())
        records = json.loads(knowledge_output.read_text(encoding="utf-8"))
        self.assertTrue(any(item["drug"] == "warfarin" for item in records))
        self.assertTrue(any(item["drug"] == "metformin" for item in records))

    def test_ingest_pdf(self):
        fitz = __import__("fitz")
        pdf_path = self.root / "布洛芬说明书.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "药物相互作用：布洛芬与华法林合用可能增加出血风险。")
        doc.save(str(pdf_path))
        doc.close()

        chunks, report = self.service.ingest_path(pdf_path)

        self.assertEqual(report.failed_count, 0)
        self.assertEqual(report.source_count, 1)
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(chunks[0].source_type, "pdf")
        self.assertEqual(chunks[0].drug, "布洛芬")


if __name__ == "__main__":
    unittest.main()
