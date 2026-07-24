"""
咨询业务 Schema：定义咨询请求、响应、证据、知识图谱关系和安全提示结构。
"""

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.analysis import Evidence, ExtractedContext, RiskLevel


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=2, description="用户本轮用药咨询内容")
    user_id: str = Field(default="demo_user", min_length=1, description="用户标识")
    session_id: Optional[int] = Field(default=None, description="已有会话 ID；为空则创建新会话")


class KnowledgeRelation(BaseModel):
    subject: str
    relation: str
    object: str
    source: str = "local_kg"
    weight: float = 1.0
    risk_level: Optional[RiskLevel] = None
    mechanism: str = ""
    recommendation: str = ""


class SafetyFlag(BaseModel):
    level: Literal["info", "warning", "danger"]
    message: str


class MemoryUpdate(BaseModel):
    event_type: str
    detail: str


class SessionSnapshot(BaseModel):
    drugs: List[str] = Field(default_factory=list)
    population: List[str] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list)
    risk_factors: List[str] = Field(default_factory=list)
    last_question: str = ""


class ConsultationResponse(BaseModel):
    id: int
    session_id: int
    user_id: str
    message: str
    answer: str
    conclusion: str
    risk_level: RiskLevel
    mechanism: str
    recommendation: str
    confidence: float
    extracted_context: ExtractedContext
    session_snapshot: SessionSnapshot
    kg_relations: List[KnowledgeRelation]
    evidence: List[Evidence]
    safety_flags: List[SafetyFlag]
    memory_updates: List[MemoryUpdate]
    workflow_trace: List[dict[str, Any]] = Field(default_factory=list)
    safety_notice: str
    created_at: datetime


class SessionSummary(BaseModel):
    id: int
    user_id: str
    title: str
    risk_level: RiskLevel
    conclusion: str
    updated_at: datetime


class SessionDetail(SessionSummary):
    snapshot: SessionSnapshot
    messages: List[ConsultationResponse]


class UserProfile(BaseModel):
    user_id: str
    allergies: List[str] = Field(default_factory=list)
    chronic_conditions: List[str] = Field(default_factory=list)
    baseline_medications: List[str] = Field(default_factory=list)
    notes: dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[datetime] = None
