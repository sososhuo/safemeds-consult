"""
API 路由模块：提供用药咨询、历史记录、指标统计和知识库管理接口。
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from app.schemas.analysis import AnalyzeRequest, DrugOption, HealthResponse, HistoryDetail, HistoryItem
from app.schemas.consultation import ChatRequest, ConsultationResponse, SessionDetail, SessionSummary
from app.services.metrics_service import system_metrics

logger = logging.getLogger(__name__)


def create_router(records, analysis_service, history_repository, consultation_service=None, consultation_repository=None) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            indexed_documents=len(analysis_service.pipeline.rag_retrieval.index.documents),
            available_drugs=[DrugOption(name=item["drug"], aliases=item.get("aliases", [])) for item in records],
        )

    @router.get("/system/health")
    def system_health() -> dict:
        if consultation_service is None:
            return {"status": "ok", "mode": "analysis_only"}
        return consultation_service.health()

    @router.get("/system/metrics")
    def system_metric_snapshot() -> dict:
        return system_metrics.snapshot()

    @router.post("/chat", response_model=ConsultationResponse)
    def chat(payload: ChatRequest) -> ConsultationResponse:
        if consultation_service is None:
            raise HTTPException(status_code=503, detail="咨询服务未初始化")
        logger.info("chat_requested user_id=%s session_id=%s message_length=%s", payload.user_id, payload.session_id, len(payload.message))
        return consultation_service.chat(
            message=payload.message,
            user_id=payload.user_id,
            session_id=payload.session_id,
        )

    @router.get("/sessions", response_model=list[SessionSummary])
    def list_sessions(user_id: str = "demo_user", limit: int = Query(default=30, ge=1, le=100)) -> list[SessionSummary]:
        if consultation_repository is None:
            raise HTTPException(status_code=503, detail="咨询存储未初始化")
        return consultation_repository.list_sessions(user_id=user_id, limit=limit)

    @router.get("/sessions/{session_id}", response_model=SessionDetail)
    def get_session(session_id: int, user_id: str = "demo_user") -> SessionDetail:
        if consultation_repository is None:
            raise HTTPException(status_code=503, detail="咨询存储未初始化")
        item = consultation_repository.get_session_detail(session_id=session_id, user_id=user_id)
        if item is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return item

    @router.delete("/sessions/{session_id}")
    def delete_session(session_id: int, user_id: str = "demo_user") -> dict:
        if consultation_repository is None:
            raise HTTPException(status_code=503, detail="咨询存储未初始化")
        deleted = consultation_repository.delete_session(session_id=session_id, user_id=user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"deleted": True}

    @router.post("/analyze", response_model=HistoryDetail)
    def analyze(payload: AnalyzeRequest) -> HistoryDetail:
        logger.info("analysis_requested question_length=%s", len(payload.question))
        return analysis_service.analyze_and_save(payload.question)

    @router.get("/history", response_model=list[HistoryItem])
    def list_history(limit: int = Query(default=30, ge=1, le=100)) -> list[HistoryItem]:
        return history_repository.list(limit=limit)

    @router.get("/history/{history_id}", response_model=HistoryDetail)
    def get_history(history_id: int) -> HistoryDetail:
        item = history_repository.get(history_id)
        if item is None:
            raise HTTPException(status_code=404, detail="历史记录不存在")
        return item

    @router.delete("/history/{history_id}")
    def delete_history(history_id: int) -> dict:
        deleted = history_repository.delete(history_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="历史记录不存在")
        return {"deleted": True}

    return router
