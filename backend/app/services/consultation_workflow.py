"""
LangGraph 工作流模块：按阶段串联咨询上下文抽取、检索、校验和报告生成。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from langgraph.graph import END, StateGraph

from app.schemas.analysis import Evidence, ExtractedContext, RiskLevel
from app.schemas.consultation import KnowledgeRelation, SafetyFlag, SessionSnapshot

if TYPE_CHECKING:
    from app.services.consultation_service import MedicationConsultationService


class MedicationRagState(TypedDict, total=False):
    message: str
    previous_snapshot: SessionSnapshot
    extracted: ExtractedContext
    snapshot: SessionSnapshot
    query_drugs: list[str]
    drug_concept_count: int
    kg_entities: list[str]
    kg_relations: list[KnowledgeRelation]
    evidence_query: str
    retrieval_backend: str
    evidence: list[Evidence]
    risk_level: RiskLevel
    mechanism: str
    pair_hit: dict[str, Any]
    recommendation: str
    confidence: float
    conclusion: str
    safety_flags: list[SafetyFlag]
    answer: str
    llm_fallback_used: bool
    workflow_trace: list[dict[str, Any]]


class MedicationRagWorkflow:
    """LangGraph workflow for the medication consultation RAG path."""

    def __init__(self, service: MedicationConsultationService):
        self.service = service
        self.graph = self._build_graph()

    def run(self, message: str, previous_snapshot: SessionSnapshot) -> MedicationRagState:
        initial: MedicationRagState = {
            "message": message,
            "previous_snapshot": previous_snapshot,
            "workflow_trace": [],
        }
        return self.graph.invoke(initial)

    def _build_graph(self):
        graph = StateGraph(MedicationRagState)
        graph.add_node("extract_entities", self._extract_entities)
        graph.add_node("query_kg", self._query_kg)
        graph.add_node("retrieve_evidence", self._retrieve_evidence)
        graph.add_node("assess_risk", self._assess_risk)
        graph.add_node("prepare_answer", self._prepare_answer)

        graph.set_entry_point("extract_entities")
        graph.add_edge("extract_entities", "retrieve_evidence")
        graph.add_edge("retrieve_evidence", "query_kg")
        graph.add_edge("query_kg", "assess_risk")
        graph.add_edge("assess_risk", "prepare_answer")
        graph.add_edge("prepare_answer", END)
        return graph.compile()

    def _trace(self, state: MedicationRagState, node: str, detail: str) -> list[dict[str, Any]]:
        return [
            *state.get("workflow_trace", []),
            {"node": node, "status": "completed", "detail": detail},
        ]

    def _extract_entities(self, state: MedicationRagState) -> MedicationRagState:
        message = state["message"]
        previous_snapshot = state["previous_snapshot"]
        extracted = self.service.extractor.execute_on_text(message)
        snapshot = self.service._merge_snapshot(previous_snapshot, extracted, message)
        candidate_drugs = [
            candidate
            for group in extracted.candidate_drug_groups
            for candidate in group.candidates
        ]
        has_current_medication_signal = bool(
            extracted.normalized_drugs
            or extracted.candidate_drug_groups
            or extracted.ambiguous_entities
        )
        query_drugs = (
            list(dict.fromkeys([*extracted.normalized_drugs, *candidate_drugs]))
            if has_current_medication_signal
            else snapshot.drugs
        )
        drug_concept_count = (
            len(extracted.normalized_drugs) + len(extracted.candidate_drug_groups)
            if has_current_medication_signal
            else len(snapshot.drugs)
        )
        kg_entities = list(dict.fromkeys(query_drugs))
        return {
            **state,
            "extracted": extracted,
            "snapshot": snapshot,
            "query_drugs": query_drugs,
            "drug_concept_count": drug_concept_count,
            "kg_entities": kg_entities,
            "workflow_trace": self._trace(
                state,
                "extract_entities",
                f"识别明确药物 {len(extracted.normalized_drugs)} 个、候选药品组 {len(extracted.candidate_drug_groups)} 个。",
            ),
        }

    def _query_kg(self, state: MedicationRagState) -> MedicationRagState:
        query_drugs = state.get("query_drugs", [])
        extracted = state.get("extracted")
        if extracted and extracted.ambiguous_entities and len(query_drugs) < 2:
            return {
                **state,
                "kg_relations": [],
                "workflow_trace": self._trace(
                    state,
                    "query_kg",
                    "本轮包含模糊药品表达，跳过单药扩展图谱关系。",
                ),
            }
        raw_relations = self.service.kg.query(
            state.get("kg_entities", []),
            depth=2 if len(query_drugs) >= 2 else 1,
        )
        drug_set = set(query_drugs)
        if len(drug_set) >= 2:
            kg_relations = [
                item for item in raw_relations
                if item.subject in drug_set and item.object in drug_set
            ]
        else:
            kg_relations = [
                item for item in raw_relations
                if item.subject in drug_set or item.object in drug_set
            ]
        return {
            **state,
            "kg_relations": kg_relations,
            "workflow_trace": self._trace(
                state,
                "query_kg",
                f"Neo4j 返回图谱关系 {len(kg_relations)} 条。",
            ),
        }

    def _retrieve_evidence(self, state: MedicationRagState) -> MedicationRagState:
        evidence_query = self.service._build_evidence_query(
            state["message"],
            [],
            state.get("query_drugs", []),
            state.get("extracted"),
            state.get("snapshot"),
        )
        top_k = min(max(8, len(state.get("query_drugs", [])) * 2), 24)
        evidence = self.service.vector_index.retrieve(
            evidence_query,
            state.get("query_drugs", []),
            top_k=top_k,
        )
        query_drugs = set(state.get("query_drugs", []))
        if query_drugs:
            scoped_evidence = [item for item in evidence if item.drug in query_drugs]
            if scoped_evidence:
                evidence = scoped_evidence
        population = self.service._combined_population(
            state.get("extracted"),
            state.get("snapshot"),
        )
        population_evidence = self.service._retrieve_population_evidence(
            state["message"],
            state.get("query_drugs", []),
            state.get("extracted"),
            state.get("snapshot"),
            state.get("extracted").candidate_drug_groups if state.get("extracted") else [],
        )
        evidence = self.service._merge_and_prioritize_evidence(
            evidence,
            population_evidence,
            population,
            state.get("extracted").candidate_drug_groups if state.get("extracted") else [],
        )
        return {
            **state,
            "evidence_query": evidence_query,
            "retrieval_backend": self.service.retrieval_backend,
            "evidence": evidence,
            "workflow_trace": self._trace(
                state,
                "retrieve_evidence",
                f"{self.service.retrieval_backend} 返回证据 {len(evidence)} 条，其中特殊人群证据 {len(population_evidence)} 条。",
            ),
        }

    def _assess_risk(self, state: MedicationRagState) -> MedicationRagState:
        risk_level, mechanism, pair_hit = self.service._assess(
            state.get("query_drugs", []),
            state.get("evidence", []),
            state.get("extracted"),
            state.get("snapshot"),
            state.get("kg_relations", []),
            state.get("drug_concept_count"),
            state.get("extracted").candidate_drug_groups if state.get("extracted") else [],
        )
        recommendation = self.service._recommendation(
            risk_level,
            pair_hit,
            state.get("evidence", []),
            state["snapshot"],
        )
        confidence = self.service._confidence(
            risk_level,
            state.get("evidence", []),
            pair_hit,
            state.get("kg_relations", []),
        )
        conclusion = self.service._conclusion(risk_level, pair_hit)
        safety_flags = self.service._safety_flags(
            risk_level,
            state.get("evidence", []),
            state["snapshot"],
            state.get("extracted"),
        )
        return {
            **state,
            "risk_level": risk_level,
            "mechanism": mechanism,
            "pair_hit": pair_hit,
            "recommendation": recommendation,
            "confidence": confidence,
            "conclusion": conclusion,
            "safety_flags": safety_flags,
            "workflow_trace": self._trace(
                state,
                "assess_risk",
                f"风险等级 {risk_level}，安全标记 {len(safety_flags)} 个。",
            ),
        }

    def _prepare_answer(self, state: MedicationRagState) -> MedicationRagState:
        answer = self.service._compose_answer(
            conclusion=state["conclusion"],
            risk_level=state["risk_level"],
            mechanism=state["mechanism"],
            recommendation=state["recommendation"],
            flags=state.get("safety_flags", []),
            evidence=state.get("evidence", []),
            kg_relations=state.get("kg_relations", []),
            current_population=state["snapshot"].population,
        )
        return {
            **state,
            "answer": answer,
            "llm_fallback_used": self.service._last_response_fallback_used,
            "workflow_trace": self._trace(
                state,
                "prepare_answer",
                "完成 grounded answer 生成。",
            ),
        }
