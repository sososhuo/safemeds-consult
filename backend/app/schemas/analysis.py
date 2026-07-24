"""
分析结果 Schema：定义药物相互作用分析、证据和风险等级的数据结构。
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


RiskLevel = Literal["High", "Medium", "Low", "Unknown"]


class AnalyzeRequest(BaseModel):
    question: str = Field(..., min_length=2, description="用户输入的中文用药问题")


class DrugCandidateGroup(BaseModel):
    mention: str
    normalized: str
    candidates: List[str]
    source: str


class ExtractedContext(BaseModel):
    drugs: List[str]
    normalized_drugs: List[str]
    population: List[str]
    conditions: List[str]
    risk_factors: List[str]
    ambiguous_entities: List[dict] = Field(default_factory=list)
    candidate_drug_groups: List[DrugCandidateGroup] = Field(default_factory=list)


class Evidence(BaseModel):
    source: str
    drug: str
    section: str
    snippet: str
    score: float


class AgentTrace(BaseModel):
    agent: str
    status: str
    detail: str


class AnalysisReport(BaseModel):
    conclusion: str
    risk_level: RiskLevel
    mechanism: str
    recommendation: str
    confidence: float
    extracted_context: ExtractedContext
    evidence: List[Evidence]
    limitations: List[str]
    safety_notice: str
    agent_trace: List[AgentTrace]


class DrugOption(BaseModel):
    name: str
    aliases: List[str]


class HealthResponse(BaseModel):
    status: str
    indexed_documents: int
    available_drugs: List[DrugOption]


class HistoryItem(BaseModel):
    id: int
    question: str
    risk_level: RiskLevel
    conclusion: str
    created_at: datetime


class HistoryDetail(HistoryItem):
    report: AnalysisReport
