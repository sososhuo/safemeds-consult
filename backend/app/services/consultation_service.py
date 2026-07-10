from __future__ import annotations

from time import perf_counter
from typing import Dict, List

from app.core.config import LLM_ENABLE_RESPONSE_GENERATION, VECTOR_BACKEND
from app.repositories.consultation_repository import ConsultationRepository
from app.schemas.analysis import Evidence, ExtractedContext, RiskLevel
from app.schemas.consultation import (
    ConsultationResponse,
    KnowledgeRelation,
    MemoryUpdate,
    SafetyFlag,
    SessionSnapshot,
)
from app.services.kg_service import MedicationKnowledgeGraph
from app.services.llm_service import LLMClient, build_consultation_prompt
from app.services.consultation_workflow import MedicationRagWorkflow
from app.services.metrics_service import system_metrics
from app.services.rag_service import ChromaRagIndex, HybridRagIndex, SimpleRagIndex
from app.services.stages.drug_recognition import DrugRecognitionStage
from app.services.stages.risk_assessment import RiskAssessmentStage


SAFETY_NOTICE = "本系统用于用药风险信息检索与咨询辅助，不提供诊断、处方或替代医生/药师的医疗建议。"


class MedicationConsultationService:
    """智能用药咨询服务：上下文记忆 + KG + 向量检索 + 安全评估。"""

    def __init__(self, records: List[Dict], repository: ConsultationRepository):
        self.records = records
        self.repository = repository
        self.extractor = DrugRecognitionStage(records)
        self.vector_backend = VECTOR_BACKEND
        self.retrieval_backend = "hybrid_bm25_dense" if VECTOR_BACKEND == "chroma" else "keyword_tfidf"
        self.vector_index = self._build_vector_index(records)
        self.kg = MedicationKnowledgeGraph(records)
        self.risk_engine = RiskAssessmentStage(records)
        self.llm_client = LLMClient()
        self._last_response_fallback_used = False
        self.workflow = MedicationRagWorkflow(self)

    def _build_vector_index(self, records: List[Dict]):
        if VECTOR_BACKEND == "chroma":
            return HybridRagIndex(records, dense_index=ChromaRagIndex(records))
        return SimpleRagIndex(records)

    def health(self) -> dict:
        kg_health = self.kg.health()
        return {
            "status": "ok",
            "vector_backend": self.vector_backend,
            "retrieval_backend": self.retrieval_backend,
            "workflow_backend": "langgraph",
            "workflow_nodes": [
                "extract_entities",
                "query_kg",
                "retrieve_evidence",
                "assess_risk",
                "prepare_answer",
            ],
            "indexed_documents": len(self.vector_index.documents),
            "kg_backend": kg_health["kg_backend"],
            "kg_status": kg_health["kg_status"],
            "kg_nodes": kg_health["kg_nodes"],
            "kg_relations": kg_health["kg_relations"],
            "neo4j_uri": kg_health["neo4j_uri"],
            "neo4j_database": kg_health["neo4j_database"],
            **({"kg_error": kg_health["kg_error"]} if "kg_error" in kg_health else {}),
            "available_drugs": [
                {"name": item["drug"], "aliases": item.get("aliases", [])}
                for item in self.records
            ],
        }

    def chat(self, message: str, user_id: str = "demo_user", session_id: int | None = None) -> ConsultationResponse:
        started = perf_counter()
        session = self.repository.get_or_create_session(user_id=user_id, session_id=session_id, title=message[:32])
        previous_snapshot = session.snapshot
        state = self.workflow.run(message=message, previous_snapshot=previous_snapshot)
        memory_updates = self._memory_updates(previous_snapshot, state["snapshot"])
        latency_ms = (perf_counter() - started) * 1000
        system_metrics.record_chat(
            latency_ms=latency_ms,
            risk_level=state["risk_level"],
            evidence_count=len(state.get("evidence", [])),
            kg_relation_count=len(state.get("kg_relations", [])),
            fallback_used=state.get("llm_fallback_used", False),
            downgraded=state["risk_level"] == "Unknown" or any(
                flag.level == "warning" for flag in state.get("safety_flags", [])
            ),
        )

        return self.repository.save_message(
            session_id=session.id,
            user_id=user_id,
            message=message,
            answer=state["answer"],
            conclusion=state["conclusion"],
            risk_level=state["risk_level"],
            mechanism=state["mechanism"],
            recommendation=state["recommendation"],
            confidence=state["confidence"],
            extracted=state["extracted"],
            snapshot=state["snapshot"],
            kg_relations=state.get("kg_relations", []),
            evidence=state.get("evidence", []),
            safety_flags=state.get("safety_flags", []),
            memory_updates=memory_updates,
            safety_notice=SAFETY_NOTICE,
            workflow_trace=state.get("workflow_trace", []),
        )

    def _merge_snapshot(self, snapshot: SessionSnapshot, extracted: ExtractedContext, message: str) -> SessionSnapshot:
        return SessionSnapshot(
            drugs=sorted(set(snapshot.drugs + extracted.normalized_drugs)),
            population=sorted(set(snapshot.population + extracted.population)),
            conditions=sorted(set(snapshot.conditions + extracted.conditions)),
            risk_factors=sorted(set(snapshot.risk_factors + extracted.risk_factors)),
            last_question=message,
        )

    def _build_evidence_query(self, message: str, kg_relations: list[KnowledgeRelation], drugs: list[str] | None = None) -> str:
        drug_set = set(drugs or [])
        scoped_relations = [
            item for item in kg_relations
            if not drug_set or (item.subject in drug_set and item.object in drug_set)
        ]
        relation_terms = " ".join(
            f"{item.subject} {item.object}" for item in scoped_relations[:6]
        )
        return f"{message} {relation_terms}".strip()

    def _assess(self, drugs: list[str], evidence: list[Evidence], extracted: ExtractedContext | None = None) -> tuple[RiskLevel, str, dict]:
        if extracted and extracted.ambiguous_entities:
            return "Unknown", "当前问题包含口语化、类别或复方药品表达，无法作为具体药品组合进行精确相互作用判断。", {}
        if len(drugs) < 2:
            return "Unknown", "当前问题中少于两个明确药物，无法对药物相互作用做确定性判断。", {}
        pair_hit = self.risk_engine._match_pair(drugs)
        risk_level, mechanism = self.risk_engine._assess(drugs, evidence, pair_hit)
        if not evidence and not pair_hit:
            return "Unknown", "当前本地知识库和向量检索未找到足够证据，不能做确定性判断。", pair_hit
        return risk_level, mechanism, pair_hit

    def _recommendation(
        self,
        risk_level: RiskLevel,
        pair_hit: dict,
        evidence: list[Evidence],
        snapshot: SessionSnapshot,
    ) -> str:
        if pair_hit:
            return pair_hit.get("recommendation", "建议由医生或药师确认是否需要调整治疗方案。")
        if risk_level == "High":
            return "不建议自行合用或调整剂量，请尽快咨询医生或药师，并留意出血、低血压、过敏等异常表现。"
        if risk_level == "Medium":
            return "可以作为风险线索处理，但需结合剂量、频次、肝肾功能和其他用药，由专业人员确认。"
        if risk_level == "Low":
            return "当前证据未提示明确严重相互作用，但仍建议按说明书和医嘱使用。"
        if snapshot.drugs:
            return "目前存在未明确的药品名称，建议先补充具体药品名称后再判断。"
        return "建议补充具体药品名称后再判断，必要时咨询医生或药师。"

    def _confidence(self, risk_level: RiskLevel, evidence: list[Evidence], pair_hit: dict, kg: list[KnowledgeRelation]) -> float:
        if pair_hit:
            return 0.88
        if risk_level == "Unknown":
            return 0.32
        score = 0.48 + min(len(evidence), 5) * 0.06 + min(len(kg), 5) * 0.03
        return round(min(score, 0.82), 2)

    def _conclusion(self, risk_level: RiskLevel, pair_hit: dict) -> str:
        if pair_hit:
            return f"{pair_hit['left']} 与 {pair_hit['right']} 存在 {risk_level} 级用药风险。"
        if risk_level == "Unknown":
            return "证据不足，暂不能给出确定性用药安全结论。"
        return f"基于当前上下文、知识图谱关系和检索证据，综合风险等级为 {risk_level}。"

    def _safety_flags(self, risk_level: RiskLevel, evidence: list[Evidence], snapshot: SessionSnapshot, extracted: ExtractedContext | None = None) -> list[SafetyFlag]:
        flags: list[SafetyFlag] = []
        if extracted and extracted.ambiguous_entities:
            names = "、".join(item.get("mention", "") for item in extracted.ambiguous_entities if item.get("mention"))
            flags.append(SafetyFlag(level="warning", message=f"{names or '部分药品'}不是明确的具体药品名称，请补充具体名称后再判断。"))
        if risk_level == "High":
            flags.append(SafetyFlag(level="danger", message="存在高风险或禁忌线索，不建议自行合用。"))
        if not evidence:
            flags.append(SafetyFlag(level="warning", message="未召回足够说明书/指南证据，结论已降级处理。"))
        if len(snapshot.drugs) < 2:
            flags.append(SafetyFlag(level="info", message="当前上下文少于两个明确药物，无法完整评估相互作用。"))
        return flags

    def _memory_updates(self, previous: SessionSnapshot, current: SessionSnapshot) -> list[MemoryUpdate]:
        updates: list[MemoryUpdate] = []
        for drug in sorted(set(current.drugs) - set(previous.drugs)):
            updates.append(MemoryUpdate(event_type="medication_mentioned", detail=f"记录本会话提到药物：{drug}"))
        for condition in sorted(set(current.conditions) - set(previous.conditions)):
            updates.append(MemoryUpdate(event_type="condition_mentioned", detail=f"记录本会话疾病/场景：{condition}"))
        return updates

    def _compose_answer(
        self,
        *,
        conclusion: str,
        risk_level: RiskLevel,
        mechanism: str,
        recommendation: str,
        flags: list[SafetyFlag],
        evidence: list[Evidence],
        kg_relations: list[KnowledgeRelation],
    ) -> str:
        self._last_response_fallback_used = False
        if LLM_ENABLE_RESPONSE_GENERATION and self.llm_client.configured:
            try:
                return self.llm_client.chat(
                    build_consultation_prompt(
                        conclusion=conclusion,
                        risk_level=risk_level,
                        mechanism=mechanism,
                        recommendation=recommendation,
                        flags=flags,
                        evidence=evidence,
                        kg_relations=kg_relations,
                        safety_notice=SAFETY_NOTICE,
                    )
                )
            except Exception as exc:
                # Medical safety should not depend on the model provider being up.
                # Fall back to deterministic output if the API fails.
                import logging

                logging.getLogger(__name__).warning("llm_response_generation_failed: %s", exc)

        self._last_response_fallback_used = True
        parts = [conclusion, f"原因：{mechanism}", f"建议：{recommendation}"]
        if kg_relations:
            rel = kg_relations[0]
            parts.append(f"图谱关系：{rel.subject} - {rel.relation} - {rel.object}。")
        if evidence:
            ev = evidence[0]
            parts.append(f"主要证据：{ev.drug}/{ev.section} 提到“{ev.snippet[:90]}”。")
        if flags:
            parts.append("安全提示：" + "；".join(flag.message for flag in flags))
        parts.append(SAFETY_NOTICE)
        return "\n\n".join(parts)
