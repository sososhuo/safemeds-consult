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
        graph.add_edge("extract_entities", "query_kg")
        graph.add_edge("query_kg", "retrieve_evidence")
        graph.add_edge("retrieve_evidence", "assess_risk")
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
        has_current_medication_signal = bool(extracted.normalized_drugs or extracted.ambiguous_entities)
        query_drugs = extracted.normalized_drugs if has_current_medication_signal else snapshot.drugs
        kg_entities = list(dict.fromkeys(query_drugs))
        return {
            **state,
            "extracted": extracted,
            "snapshot": snapshot,
            "query_drugs": query_drugs,
            "kg_entities": kg_entities,
            "workflow_trace": self._trace(
                state,
                "extract_entities",
                f"识别药物 {len(extracted.normalized_drugs)} 个，上下文药物 {len(snapshot.drugs)} 个。",
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
            state.get("kg_relations", []),
            state.get("query_drugs", []),
        )
        evidence = self.service.vector_index.retrieve(
            evidence_query,
            state.get("query_drugs", []),
            top_k=8,
        )
        query_drugs = set(state.get("query_drugs", []))
        if query_drugs:
            scoped_evidence = [item for item in evidence if item.drug in query_drugs]
            if scoped_evidence:
                evidence = scoped_evidence
        return {
            **state,
            "evidence_query": evidence_query,
            "retrieval_backend": self.service.retrieval_backend,
            "evidence": evidence,
            "workflow_trace": self._trace(
                state,
                "retrieve_evidence",
                f"{self.service.retrieval_backend} 返回证据 {len(evidence)} 条。",
            ),
        }

    def _assess_risk(self, state: MedicationRagState) -> MedicationRagState:
        risk_level, mechanism, pair_hit = self.service._assess(
            state.get("query_drugs", []),
            state.get("evidence", []),
            state.get("extracted"),
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
