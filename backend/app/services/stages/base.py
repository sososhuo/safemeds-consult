"""Pipeline 阶段：基础抽象与上下文"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.schemas.analysis import (
    AnalysisReport,
    AgentTrace,
    Evidence,
    ExtractedContext,
    RiskLevel,
)


@dataclass
class StageContext:
    """在 Pipeline 各阶段之间传递的上下文。"""

    question: str
    extracted: ExtractedContext | None = None
    evidence: list[Evidence] = field(default_factory=list)
    risk_level: RiskLevel = "Unknown"
    mechanism: str = ""
    pair_hit: dict[str, Any] = field(default_factory=dict)
    report: AnalysisReport | None = None
    traces: list[AgentTrace] = field(default_factory=list)

    def add_trace(self, agent: str, status: str, detail: str) -> None:
        self.traces.append(AgentTrace(agent=agent, status=status, detail=detail))


class BaseStage(ABC):
    """Pipeline 中一个可独立执行、可独立测试的阶段。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """阶段名称，用于 Trace 显示。"""
        ...

    @abstractmethod
    def execute(self, ctx: StageContext) -> StageContext:
        """执行本阶段逻辑，修改上下文后返回。"""
        ...
