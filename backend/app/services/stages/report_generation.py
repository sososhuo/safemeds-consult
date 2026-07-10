"""
Stage 4：报告生成 Stage
=========================
将前面三个阶段的结果组装为结构化的 AnalysisReport。
"""

from __future__ import annotations

import re

from app.schemas.analysis import AnalysisReport, RiskLevel
from app.services.stages.base import BaseStage, StageContext

CONFIDENCE_HIGH = 0.86
CONFIDENCE_MEDIUM = 0.62
CONFIDENCE_LOW = 0.35


class ReportGenerationStage(BaseStage):
    """报告生成阶段：组装最终结构化报告。"""

    @property
    def name(self) -> str:
        return "报告生成 Stage"

    def execute(self, ctx: StageContext) -> StageContext:
        ctx.add_trace(agent=self.name, status="完成", detail="生成结构化 JSON 报告并附带安全边界")
        ctx.report = self._compose(ctx)
        return ctx

    def _compose(self, ctx: StageContext) -> AnalysisReport:
        question = ctx.question
        extracted = ctx.extracted
        evidence = ctx.evidence
        risk_level = ctx.risk_level
        mechanism = ctx.mechanism
        pair_hit = ctx.pair_hit

        if risk_level == "Unknown":
            conclusion = "未找到足够可靠证据，系统不做安全性结论。"
            recommendation = "建议补充完整药物名称、剂量、疾病和特殊人群信息，并咨询医生或药师。"
            confidence = CONFIDENCE_LOW
        elif pair_hit:
            conclusion = f"{pair_hit['left']} 与 {pair_hit['right']} 存在 {risk_level} 级用药风险。"
            recommendation = pair_hit.get(
                "recommendation",
                "建议由医生或药师评估是否调整治疗方案，并进行必要监测。",
            )
            confidence = CONFIDENCE_HIGH
        else:
            conclusion = f"基于当前知识库证据，综合风险等级为 {risk_level}。"
            recommendation = "建议结合患者病史、剂量、肝肾功能和正在使用的其他药物，由专业人员确认。"
            confidence = CONFIDENCE_MEDIUM if evidence else CONFIDENCE_LOW

        limitations = self._build_limitations(extracted, evidence, question)
        return AnalysisReport(
            conclusion=conclusion,
            risk_level=risk_level,
            mechanism=mechanism,
            recommendation=recommendation,
            confidence=confidence,
            extracted_context=extracted,
            evidence=evidence,
            limitations=limitations,
            safety_notice="本系统仅用于面试 Demo 和用药风险信息检索展示，不提供诊断、处方或替代医生/药师的医疗建议。",
            agent_trace=ctx.traces,
        )

    def _build_limitations(self, extracted, evidence, question: str) -> list[str]:
        limitations = []
        if extracted and len(extracted.normalized_drugs) < 2:
            limitations.append("输入中少于两个可识别药物，药物相互作用判断可能不完整。")
        if not evidence:
            limitations.append("当前本地知识库未召回相关说明书片段。")
        if not re.search(r"\d+\s*(mg|毫克|片|粒)", question, flags=re.I):
            limitations.append("输入缺少剂量信息，无法评估剂量相关风险。")
        return limitations
