"""
工作流阶段包：统一导出药物识别、RAG 检索、风险评估和报告生成阶段。
"""

from app.services.stages.base import BaseStage, StageContext
from app.services.stages.drug_recognition import DrugRecognitionStage
from app.services.stages.rag_retrieval import RAGRetrievalStage
from app.services.stages.risk_assessment import RiskAssessmentStage
from app.services.stages.report_generation import ReportGenerationStage

__all__ = [
    "BaseStage",
    "StageContext",
    "DrugRecognitionStage",
    "RAGRetrievalStage",
    "RiskAssessmentStage",
    "ReportGenerationStage",
]
