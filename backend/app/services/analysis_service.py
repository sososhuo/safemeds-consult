"""
药物分析服务模块：面向药物对的相互作用分析和历史记录封装。
"""

from typing import Dict, List

from app.repositories.history_repository import HistoryRepository
from app.schemas.analysis import AnalysisReport, HistoryDetail
from app.services.agent_service import SafeMedsPipeline


class AnalysisService:
    def __init__(self, records: List[Dict], history_repository: HistoryRepository):
        self.pipeline = SafeMedsPipeline(records)
        self.history_repository = history_repository

    def analyze_and_save(self, question: str) -> HistoryDetail:
        report: AnalysisReport = self.pipeline.analyze(question)
        return self.history_repository.create(question=question, report=report)
