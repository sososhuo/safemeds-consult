"""
指标服务模块：汇总咨询量、风险等级、药物命中和最近活动统计。
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Any


@dataclass
class ConsultationMetric:
    latency_ms: float
    risk_level: str
    evidence_count: int
    kg_relation_count: int
    fallback_used: bool
    downgraded: bool
    created_at: str


class SystemMetrics:
    def __init__(self, max_events: int = 300):
        self.events: deque[ConsultationMetric] = deque(maxlen=max_events)

    def record_chat(
        self,
        *,
        latency_ms: float,
        risk_level: str,
        evidence_count: int,
        kg_relation_count: int,
        fallback_used: bool,
        downgraded: bool,
    ) -> None:
        self.events.append(
            ConsultationMetric(
                latency_ms=round(latency_ms, 2),
                risk_level=risk_level,
                evidence_count=evidence_count,
                kg_relation_count=kg_relation_count,
                fallback_used=fallback_used,
                downgraded=downgraded,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )

    def snapshot(self) -> dict[str, Any]:
        events = list(self.events)
        if not events:
            return {
                "chat_count": 0,
                "avg_latency_ms": 0,
                "p95_latency_ms": 0,
                "avg_evidence_count": 0,
                "avg_kg_relation_count": 0,
                "fallback_rate": 0,
                "downgrade_rate": 0,
                "risk_distribution": {},
                "recent": [],
            }

        latencies = sorted(event.latency_ms for event in events)
        p95_index = min(len(latencies) - 1, int(len(latencies) * 0.95))
        risk_distribution = Counter(event.risk_level for event in events)
        return {
            "chat_count": len(events),
            "avg_latency_ms": round(mean(event.latency_ms for event in events), 2),
            "p95_latency_ms": round(latencies[p95_index], 2),
            "avg_evidence_count": round(mean(event.evidence_count for event in events), 2),
            "avg_kg_relation_count": round(mean(event.kg_relation_count for event in events), 2),
            "fallback_rate": round(sum(event.fallback_used for event in events) / len(events), 4),
            "downgrade_rate": round(sum(event.downgraded for event in events) / len(events), 4),
            "risk_distribution": dict(risk_distribution),
            "recent": [event.__dict__ for event in events[-10:]][::-1],
        }


system_metrics = SystemMetrics()
