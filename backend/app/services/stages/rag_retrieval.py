"""
Stage 2：RAG 检索 Stage
=========================
将用户问题送入 RAG 服务，召回相关证据片段。
"""

from __future__ import annotations

from typing import Dict, List

from app.services.rag_service import SimpleRagIndex
from app.services.stages.base import BaseStage, StageContext


class RAGRetrievalStage(BaseStage):
    """RAG 检索阶段：切分/向量化/召回/规则重排。"""

    def __init__(self, records: List[Dict]):
        self.records = records
        self.index = SimpleRagIndex(records)

    @property
    def name(self) -> str:
        return "RAG 检索 Stage"

    def execute(self, ctx: StageContext) -> StageContext:
        drugs = ctx.extracted.normalized_drugs if ctx.extracted else []
        ctx.evidence = self.index.retrieve(ctx.question, drugs, top_k=8)
        ctx.add_trace(
            agent=self.name,
            status="完成",
            detail=f"完成切分、向量召回与规则重排，返回 {len(ctx.evidence)} 条证据",
        )
        return ctx
