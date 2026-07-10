"""
药物交互分析 Pipeline
========================
编排一组 Stage 依次执行：药物识别 -> RAG 检索 -> 风险评估 -> 报告生成。
每个 Stage 是独立的可替换模块，可在不修改编排逻辑的前提下替换为 LLM Agent。
"""

from __future__ import annotations

from typing import Dict, List

from app.schemas.analysis import AnalysisReport
from app.services.stages import (
    DrugRecognitionStage,
    RAGRetrievalStage,
    ReportGenerationStage,
    RiskAssessmentStage,
    StageContext,
)


class SafeMedsPipeline:
    """多阶段管线：编排 4 个独立 Stage 完成一次用药分析。"""

    def __init__(self, records: List[Dict]):
        self.records = records
        # ── 将 4 个 Stage 声明为实例属性，每个均可独立测试 ──
        self.drug_recognition = DrugRecognitionStage(records)
        self.rag_retrieval = RAGRetrievalStage(records)
        self.risk_assessment = RiskAssessmentStage(records)
        self.report_generation = ReportGenerationStage()

    def analyze(self, question: str) -> AnalysisReport:
        """顺序执行全部 Stage，返回最终报告。"""
        ctx = StageContext(question=question)

        # Stage 1：药物识别
        ctx = self.drug_recognition.execute(ctx)

        # Stage 2：RAG 检索
        ctx = self.rag_retrieval.execute(ctx)

        # Stage 3：风险评估
        ctx = self.risk_assessment.execute(ctx)

        # Stage 4：报告生成
        ctx = self.report_generation.execute(ctx)

        # ctx.report 由 ReportGenerationStage 填充
        assert ctx.report is not None, "ReportGenerationStage 必须生成报告"
        return ctx.report
