"""
Stage 3：风险评估 Stage
=========================
根据 RAG 检索到的证据进行风险等级判定，使用关键词 + 规则引擎。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from app.schemas.analysis import Evidence, RiskLevel
from app.services.stages.base import BaseStage, StageContext

HIGH_PATTERNS = [
    "禁忌", "严重", "不得", "避免合用", "显著增加", "危及生命",
    "横纹肌溶解", "严重低血压", "禁止", "危险", "致死", "避免与",
]
MEDIUM_PATTERNS = [
    "监测", "谨慎", "调整剂量", "增加风险", "可能", "注意",
    "肾功能", "出血", "减量", "慎用",
]


class RiskAssessmentStage(BaseStage):
    """风险评估阶段：综合药物对匹配 + 证据关键词判定风险等级。"""

    def __init__(self, records: List[Dict]):
        self.drug_pairs = self._build_pairs(records)

    @staticmethod
    def _build_pairs(records: List[Dict]) -> Dict[Tuple[str, str], Dict]:
        pairs = {}
        for item in records:
            for rule in item.get("interactions", []):
                pair = tuple(sorted([item["drug"], rule["with"]]))
                pairs[pair] = rule
        return pairs

    @property
    def name(self) -> str:
        return "风险评估 Stage"

    def execute(self, ctx: StageContext) -> StageContext:
        drugs = ctx.extracted.normalized_drugs if ctx.extracted else []
        evidence = ctx.evidence
        pair_hit = self._match_pair(drugs)
        risk_level, mechanism = self._assess(drugs, evidence, pair_hit)

        ctx.risk_level = risk_level
        ctx.mechanism = mechanism
        ctx.pair_hit = pair_hit
        ctx.add_trace(agent=self.name, status="完成", detail=f"风险等级判定为 {risk_level}")
        return ctx

    def _match_pair(self, drugs: List[str]) -> Dict:
        """精确匹配知识库中预定义的药物相互作用对。"""
        for i, left in enumerate(drugs):
            for right in drugs[i + 1:]:
                pair = tuple(sorted([left, right]))
                if pair in self.drug_pairs:
                    rule = self.drug_pairs[pair]
                    return {"left": left, "right": right, **rule}
        return {}

    def _assess(self, drugs: List[str], evidence: List[Evidence], pair_hit: Dict) -> Tuple[RiskLevel, str]:
        """综合药物对匹配和证据关键词判定风险等级。"""
        if not drugs:
            return "Unknown", "当前问题中未识别到明确药物，无法进行个体化用药风险判断。"

        # 优先级 1：命中预定义药物交互对
        if pair_hit:
            level = pair_hit.get("risk_level", "Medium")
            mechanism = pair_hit.get("mechanism", "存在已知药物相互作用。")
            recommendation = pair_hit.get("recommendation")
            if recommendation and recommendation not in mechanism:
                mechanism = f"{mechanism} {recommendation}"
            return level, mechanism

        # 优先级 2：证据不足
        if not evidence:
            return "Unknown", "当前知识库未检索到足够证据，不能做确定性判断。"

        # 优先级 3：从证据内容中关键词判定
        joined = " ".join(item.snippet for item in evidence)
        if any(p in joined for p in HIGH_PATTERNS):
            return "High", "检索证据包含禁忌、严重不良反应或明确避免合用信息。"
        if any(p in joined for p in MEDIUM_PATTERNS):
            return "Medium", "检索证据提示可能需要监测、谨慎使用或调整剂量。"
        return "Low", "当前证据未提示明确严重相互作用，但仍需结合患者情况判断。"
