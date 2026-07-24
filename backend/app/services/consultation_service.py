"""
咨询编排服务模块：整合药物识别、RAG、知识图谱和风险规则生成安全结论。
"""

from __future__ import annotations

import re
from time import perf_counter
from typing import Dict, List

from app.core.config import LLM_ENABLE_RESPONSE_GENERATION, VECTOR_BACKEND
from app.repositories.consultation_repository import ConsultationRepository
from app.schemas.analysis import DrugCandidateGroup, Evidence, ExtractedContext, RiskLevel
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

POPULATION_QUERY_TERMS = {
    "老年人": ["老年", "老人", "老年患者", "高龄", "65岁", "65 岁", "特殊人群", "风险增高", "风险更高", "剂量选择", "清除率", "AUC", "小剂量"],
    "儿童": ["儿童", "小儿", "婴幼儿", "18岁以下", "18 岁以下", "儿科", "特殊人群", "禁用", "慎用"],
    "妊娠/备孕": ["妊娠", "孕妇", "孕期", "备孕", "胎儿", "特殊人群", "禁用", "慎用"],
    "哺乳期": ["哺乳", "乳汁", "婴儿", "特殊人群", "禁用", "慎用"],
    "肾功能相关": ["肾功能", "肾功能不全", "eGFR", "透析", "剂量调整", "特殊人群"],
    "肝功能相关": ["肝功能", "肝功能不全", "转氨酶", "减量", "特殊人群"],
    "心力衰竭": ["心力衰竭", "心衰", "水肿", "慎用", "禁用"],
}

POPULATION_MATCH_TERMS = {
    "老年人": ["老年", "老人", "老年患者", "高龄", "65岁", "65 岁"],
    "儿童": ["儿童", "小儿", "婴幼儿", "18岁以下", "18 岁以下", "儿科"],
    "妊娠/备孕": ["妊娠", "孕妇", "孕期", "备孕", "胎儿"],
    "哺乳期": ["哺乳", "乳汁", "婴儿"],
    "肾功能相关": ["肾功能", "肾功能不全", "eGFR", "透析"],
    "肝功能相关": ["肝功能", "肝功能不全", "转氨酶"],
    "心力衰竭": ["心力衰竭", "心衰"],
}

POPULATION_HIGH_TERMS = [
    "禁用",
    "禁止",
    "禁忌",
    "不得",
    "避免",
    "原则上禁用",
    "致畸",
    "不应使用",
    "胎儿死亡",
    "胎儿危害",
    "胎儿损伤",
]
POPULATION_MEDIUM_TERMS = [
    "慎用",
    "风险增高",
    "风险更高",
    "应监测",
    "监测",
    "减量",
    "调整剂量",
    "起始剂量",
    "不宜",
    "医师指导",
    "医生指导",
    "药师指导",
    "专业医师指导",
    "遵医嘱",
    "成人监护",
    "剂量选择",
    "低剂量",
    "小剂量",
    "清除率",
    "AUC",
    "肝功能",
    "肾功能",
    "心功能",
    "合用其他药物",
]
POPULATION_SECTION_TITLES = {
    "老年人": ["老年用药", "特殊人群", "警告与注意事项"],
    "儿童": ["儿童用药", "特殊人群", "警告与注意事项"],
    "妊娠/备孕": ["孕妇及哺乳期妇女用药", "妊娠", "特殊人群", "警告与注意事项"],
    "哺乳期": ["孕妇及哺乳期妇女用药", "哺乳", "特殊人群", "警告与注意事项"],
    "肾功能相关": ["肾功能", "特殊人群", "警告与注意事项", "用法用量"],
    "肝功能相关": ["肝功能", "特殊人群", "警告与注意事项", "用法用量"],
    "心力衰竭": ["心力衰竭", "心衰", "警告与注意事项", "禁忌"],
}
CONDITION_MATCH_TERMS = {
    "高血压": ["高血压", "血压"],
    "糖尿病": ["糖尿病", "血糖"],
    "肾功能不全": ["肾功能不全", "肾功能", "肾病", "eGFR"],
    "肝功能不全": ["肝功能不全", "肝功能", "肝病", "转氨酶"],
    "心力衰竭": ["心力衰竭", "心衰", "心功能不全"],
    "冠心病": ["冠心病", "心脏病"],
}
CONDITION_HIGH_TERMS = ["禁用", "禁止", "禁忌", "不得", "避免", "不应使用", "严重"]
CONDITION_MEDIUM_TERMS = [
    "慎用",
    "医师指导",
    "医生指导",
    "药师指导",
    "监测",
    "评估",
    "调整剂量",
    "剂量调整",
    "风险",
    "不宜",
]
RISK_ORDER = {"Unknown": 0, "Low": 1, "Medium": 2, "High": 3}
KG_HIGH_RELATIONS = {"禁忌合用", "禁用于", "CONTRAINDICATED_WITH", "CONTRAINDICATED_FOR"}
KG_MEDIUM_RELATIONS = {"慎用于", "检查注意", "USE_WITH_CAUTION_IN", "CAUTION_FOR", "EXAM_CAUTION"}


class MedicationConsultationService:
    """智能用药咨询服务：上下文记忆 + KG + 向量检索 + 安全评估。"""

    def __init__(
        self,
        records: List[Dict],
        repository: ConsultationRepository,
        vector_index=None,
    ):
        self.records = records
        self.repository = repository
        self.extractor = DrugRecognitionStage(records)
        self.vector_backend = VECTOR_BACKEND
        self.retrieval_backend = "hybrid_bm25_dense" if VECTOR_BACKEND == "chroma" else "keyword_tfidf"
        self.vector_index = vector_index or self._build_vector_index(records)
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
                "retrieve_evidence",
                "query_kg",
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
            population=self._merge_population(extracted.population, snapshot.population),
            conditions=sorted(set(snapshot.conditions + extracted.conditions)),
            risk_factors=sorted(set(snapshot.risk_factors + extracted.risk_factors)),
            last_question=message,
        )

    def _build_evidence_query(
        self,
        message: str,
        kg_relations: list[KnowledgeRelation],
        drugs: list[str] | None = None,
        extracted: ExtractedContext | None = None,
        snapshot: SessionSnapshot | None = None,
    ) -> str:
        drug_set = set(drugs or [])
        scoped_relations = [
            item for item in kg_relations
            if not drug_set or (item.subject in drug_set and item.object in drug_set)
        ]
        relation_terms = " ".join(
            f"{item.subject} {item.object}" for item in scoped_relations[:6]
        )
        population = self._combined_population(extracted, snapshot)
        conditions = sorted(set((extracted.conditions if extracted else []) + (snapshot.conditions if snapshot else [])))
        risk_factors = sorted(set((extracted.risk_factors if extracted else []) + (snapshot.risk_factors if snapshot else [])))
        context_terms = " ".join(
            [
                *self._population_query_terms(population),
                *conditions,
                *risk_factors,
            ]
        )
        return f"{message} {relation_terms} {context_terms}".strip()

    def _retrieve_population_evidence(
        self,
        message: str,
        drugs: list[str],
        extracted: ExtractedContext | None = None,
        snapshot: SessionSnapshot | None = None,
        candidate_groups: list[DrugCandidateGroup] | None = None,
        top_k: int = 12,
    ) -> list[Evidence]:
        population = self._combined_population(extracted, snapshot)
        if not population or not drugs:
            return []

        population_query = self._build_population_evidence_query(message, drugs, population)
        vector_hits = self.vector_index.retrieve(population_query, drugs, top_k=top_k)
        vector_hits = [
            item for item in vector_hits
            if item.drug in set(drugs) and self._is_population_evidence(item, population)
        ]
        direct_hits = self._direct_population_evidence(drugs, population)
        prioritized = self._prioritize_population_evidence(
            self._dedupe_evidence([*direct_hits, *vector_hits]),
            population,
        )
        return self._diversify_evidence_by_concept(prioritized, candidate_groups or [], top_k)

    def _build_population_evidence_query(self, message: str, drugs: list[str], population: list[str]) -> str:
        section_terms: list[str] = []
        for group in population:
            section_terms.extend(POPULATION_SECTION_TITLES.get(group, []))
        terms = [
            message,
            *drugs,
            *self._population_query_terms(population),
            *section_terms,
            "特殊人群",
            "用药前确认",
            "禁忌",
            "注意事项",
            "用法用量",
        ]
        return " ".join(dict.fromkeys(term for term in terms if term)).strip()

    def _direct_population_evidence(self, drugs: list[str], population: list[str]) -> list[Evidence]:
        drug_set = set(drugs)
        hits: list[Evidence] = []
        for record in self.records:
            if record.get("drug") not in drug_set:
                continue
            for section in record.get("sections", []):
                title = section.get("title", "")
                content = section.get("content", "")
                evidence = Evidence(
                    source=record.get("source", ""),
                    drug=record.get("drug", ""),
                    section=title,
                    snippet=content[:320],
                    score=1.0,
                )
                if self._is_population_evidence(evidence, population):
                    hits.append(evidence)
        return hits

    def _combined_population(
        self,
        extracted: ExtractedContext | None = None,
        snapshot: SessionSnapshot | None = None,
    ) -> list[str]:
        return self._merge_population(
            extracted.population if extracted else [],
            snapshot.population if snapshot else [],
        )

    def _combined_conditions(
        self,
        extracted: ExtractedContext | None = None,
        snapshot: SessionSnapshot | None = None,
    ) -> list[str]:
        return sorted(
            set((extracted.conditions if extracted else []) + (snapshot.conditions if snapshot else []))
        )

    def _merge_population(self, current: list[str], previous: list[str]) -> list[str]:
        merged = set(previous)
        current_set = set(current)
        if "儿童" in current_set and "老年人" not in current_set:
            merged.discard("老年人")
        if "老年人" in current_set and "儿童" not in current_set:
            merged.discard("儿童")
        merged.update(current_set)
        return sorted(merged)

    def _is_population_evidence(self, item: Evidence, population: list[str]) -> bool:
        text = f"{item.section} {item.snippet}"
        for group in population:
            match_terms = POPULATION_MATCH_TERMS.get(group, [group])
            section_terms = POPULATION_SECTION_TITLES.get(group, [])
            if any(term in text for term in match_terms + section_terms):
                return True
        return False

    def _merge_and_prioritize_evidence(
        self,
        evidence: list[Evidence],
        population_evidence: list[Evidence],
        population: list[str],
        candidate_groups: list[DrugCandidateGroup] | None = None,
        limit: int = 12,
    ) -> list[Evidence]:
        merged = self._dedupe_evidence([*population_evidence, *evidence])
        if population:
            merged = self._prioritize_population_evidence(merged, population)
        return self._diversify_evidence_by_concept(merged, candidate_groups or [], limit)

    def _diversify_evidence_by_concept(
        self,
        evidence: list[Evidence],
        candidate_groups: list[DrugCandidateGroup],
        limit: int,
    ) -> list[Evidence]:
        if not evidence:
            return []

        candidate_to_concept = {
            candidate: group.normalized or group.mention
            for group in candidate_groups
            for candidate in group.candidates
        }
        concept_order: list[str] = []
        by_concept: dict[str, list[Evidence]] = {}
        for item in evidence:
            concept = candidate_to_concept.get(item.drug, item.drug)
            if concept not in by_concept:
                by_concept[concept] = []
                concept_order.append(concept)
            by_concept[concept].append(item)

        if len(concept_order) <= 1:
            return evidence[:limit]

        per_concept = max(2, limit // len(concept_order))
        selected: list[Evidence] = []
        selected_keys: set[tuple[str, str, str, str]] = set()
        for concept in concept_order:
            for item in by_concept[concept][:per_concept]:
                selected.append(item)
                selected_keys.add((item.source, item.drug, item.section, item.snippet))

        if len(selected) < limit:
            for item in evidence:
                key = (item.source, item.drug, item.section, item.snippet)
                if key in selected_keys:
                    continue
                selected.append(item)
                selected_keys.add(key)
                if len(selected) >= limit:
                    break

        return selected[:limit]

    def _dedupe_evidence(self, evidence: list[Evidence]) -> list[Evidence]:
        seen: set[tuple[str, str, str, str]] = set()
        unique: list[Evidence] = []
        for item in evidence:
            normalized_snippet = re.sub(r"^\s*\d+[.、)]\s*", "", item.snippet).strip()
            key = (item.source, item.drug, item.section, normalized_snippet)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _prioritize_population_evidence(self, evidence: list[Evidence], population: list[str]) -> list[Evidence]:
        def score(item: Evidence) -> float:
            value = item.score
            if self._is_population_evidence(item, population):
                value += 2.0
            if any(item.section == title for group in population for title in POPULATION_SECTION_TITLES.get(group, [])):
                value += 0.8
            if any(term in item.snippet for term in POPULATION_HIGH_TERMS):
                value += 0.4
            if any(term in item.snippet for term in POPULATION_MEDIUM_TERMS):
                value += 0.3
            return value

        return sorted(
            [item.model_copy(update={"score": round(score(item), 4)}) for item in evidence],
            key=lambda item: item.score,
            reverse=True,
        )

    def _assess(
        self,
        drugs: list[str],
        evidence: list[Evidence],
        extracted: ExtractedContext | None = None,
        snapshot: SessionSnapshot | None = None,
        kg_relations: list[KnowledgeRelation] | None = None,
        drug_concept_count: int | None = None,
        candidate_groups: list[DrugCandidateGroup] | None = None,
    ) -> tuple[RiskLevel, str, dict]:
        concept_count = drug_concept_count if drug_concept_count is not None else len(drugs)
        if extracted and extracted.ambiguous_entities and concept_count < 2:
            return "Unknown", "当前问题包含口语化、类别或复方药品表达，无法作为具体药品组合进行精确相互作用判断。", {}
        population = self._combined_population(extracted, snapshot)
        population_signal = self._population_evidence_signal(
            evidence,
            population,
        )
        condition_signal = self._condition_evidence_signal(
            evidence,
            self._combined_conditions(extracted, snapshot),
        )
        if concept_count < 2:
            if drugs and population_signal:
                level, mechanism = population_signal
                return level, mechanism, {}
            if drugs and condition_signal:
                level, mechanism = condition_signal
                return level, mechanism, {}
            return "Unknown", "当前问题中少于两个明确药物，无法对药物相互作用做确定性判断。", {}
        pair_hit = self._match_pair_across_concepts(drugs, candidate_groups or [])
        risk_level, mechanism = self.risk_engine._assess(drugs, evidence, pair_hit)
        if population_signal:
            population_level, population_mechanism = population_signal
            if RISK_ORDER[population_level] > RISK_ORDER[risk_level]:
                risk_level = population_level
            if population_mechanism not in mechanism:
                mechanism = f"{mechanism} 同时，{population_mechanism}"
        if condition_signal:
            condition_level, condition_mechanism = condition_signal
            if RISK_ORDER[condition_level] > RISK_ORDER[risk_level]:
                risk_level = condition_level
            if condition_mechanism not in mechanism:
                mechanism = f"{mechanism} 同时，{condition_mechanism}"
        kg_signal = self._kg_risk_signal(kg_relations or [], drugs)
        if kg_signal:
            kg_level, kg_mechanism = kg_signal
            if RISK_ORDER[kg_level] > RISK_ORDER[risk_level]:
                risk_level = kg_level
            if kg_mechanism not in mechanism:
                mechanism = f"{mechanism} 同时，{kg_mechanism}"
        if not evidence and not pair_hit and not kg_signal:
            return "Unknown", "当前本地知识库和向量检索未找到足够证据，不能做确定性判断。", pair_hit
        return risk_level, mechanism, pair_hit

    def _match_pair_across_concepts(
        self,
        drugs: list[str],
        candidate_groups: list[DrugCandidateGroup],
    ) -> dict:
        grouped_candidates = {
            candidate
            for group in candidate_groups
            for candidate in group.candidates
        }
        concepts = [{drug} for drug in drugs if drug not in grouped_candidates]
        concepts.extend(set(group.candidates) for group in candidate_groups)
        for index, left_group in enumerate(concepts):
            for right_group in concepts[index + 1:]:
                for left in left_group:
                    for right in right_group:
                        pair = tuple(sorted([left, right]))
                        if pair in self.risk_engine.drug_pairs:
                            return {
                                "left": left,
                                "right": right,
                                **self.risk_engine.drug_pairs[pair],
                            }
        return {}

    def _candidate_consensus_error(self, groups: list[DrugCandidateGroup]) -> str | None:
        if not groups:
            return None
        records_by_drug = {record.get("drug"): record for record in self.records}
        for group in groups:
            levels: set[RiskLevel] = set()
            missing: list[str] = []
            for candidate in group.candidates:
                record = records_by_drug.get(candidate)
                evidence = [
                    Evidence(
                        source=record.get("source", ""),
                        drug=candidate,
                        section=section.get("title", ""),
                        snippet=section.get("content", "")[:2000],
                        score=1.0,
                    )
                    for section in (record or {}).get("sections", [])
                    if section.get("title") == "药物相互作用" and section.get("content")
                ]
                if not evidence:
                    missing.append(candidate)
                    continue
                level, _ = self.risk_engine._assess([candidate], evidence, {})
                levels.add(level)
            if missing or len(levels) != 1:
                return (
                    f"“{group.mention}”对应的候选制剂在当前知识库中的相互作用证据不完整或不一致，"
                    "暂不能合并为同一结论。"
                )
        return None

    def _kg_risk_signal(
        self,
        kg_relations: list[KnowledgeRelation],
        drugs: list[str],
    ) -> tuple[RiskLevel, str] | None:
        if not kg_relations:
            return None

        drug_set = set(drugs)
        scoped = [
            item for item in kg_relations
            if not drug_set or item.subject in drug_set or item.object in drug_set
        ]
        if not scoped:
            return None

        def relation_level(item: KnowledgeRelation) -> RiskLevel | None:
            if item.risk_level in RISK_ORDER:
                return item.risk_level
            if item.relation in KG_HIGH_RELATIONS:
                return "High"
            if item.relation == "风险" and item.object == "High":
                return "High"
            if item.relation in KG_MEDIUM_RELATIONS:
                return "Medium"
            if item.relation == "风险" and item.object == "Medium":
                return "Medium"
            return None

        best_relation: KnowledgeRelation | None = None
        best_level: RiskLevel | None = None
        for item in scoped:
            level = relation_level(item)
            if level is None:
                continue
            if best_level is None or RISK_ORDER[level] > RISK_ORDER[best_level]:
                best_level = level
                best_relation = item

        if best_relation is None or best_level is None:
            return None

        mechanism = (
            best_relation.mechanism
            or f"知识图谱校验命中结构化关系：{best_relation.subject} - {best_relation.relation} - {best_relation.object}。"
        )
        if best_relation.recommendation and best_relation.recommendation not in mechanism:
            mechanism = f"{mechanism} {best_relation.recommendation}"
        return best_level, mechanism

    def _population_query_terms(self, population: list[str]) -> list[str]:
        terms: list[str] = []
        for item in population:
            terms.extend(POPULATION_QUERY_TERMS.get(item, [item]))
        return list(dict.fromkeys(terms))

    def _population_evidence_signal(self, evidence: list[Evidence], population: list[str]) -> tuple[RiskLevel, str] | None:
        if not evidence or not population:
            return None

        matched: list[tuple[str, Evidence]] = []
        for group in population:
            match_terms = POPULATION_MATCH_TERMS.get(group, [group])
            for item in evidence:
                text = f"{item.section} {item.snippet}"
                if item.section == "特殊人群" or any(term in text for term in match_terms):
                    if any(term in text for term in match_terms):
                        matched.append((group, item))

        if not matched:
            return None

        joined = " ".join(item.snippet for _, item in matched)
        groups = "、".join(sorted({group for group, _ in matched}))
        if any(term in joined for term in POPULATION_HIGH_TERMS):
            return "High", f"检索证据提示该药在{groups}相关场景中存在禁用、禁忌或应避免使用等限制。"
        if any(term in joined for term in POPULATION_MEDIUM_TERMS):
            return "Medium", f"检索证据提示{groups}用药时风险可能增高，需谨慎使用、监测或由医生药师确认。"
        return None

    @staticmethod
    def _has_near_terms(text: str, anchors: list[str], signals: list[str], window: int = 48) -> bool:
        for anchor in anchors:
            start = text.find(anchor)
            while start >= 0:
                left = max(0, start - window)
                right = min(len(text), start + len(anchor) + window)
                scope = text[left:right]
                if any(signal in scope for signal in signals):
                    return True
                start = text.find(anchor, start + 1)
        return False

    def _condition_evidence_signal(self, evidence: list[Evidence], conditions: list[str]) -> tuple[RiskLevel, str] | None:
        if not evidence or not conditions:
            return None

        matched: list[tuple[str, Evidence]] = []
        high_match = False
        medium_match = False
        for condition in conditions:
            match_terms = CONDITION_MATCH_TERMS.get(condition)
            if not match_terms:
                continue
            for item in evidence:
                text = f"{item.section} {item.snippet}"
                if any(term in text for term in match_terms):
                    matched.append((condition, item))
                    if self._has_near_terms(text, match_terms, CONDITION_HIGH_TERMS):
                        high_match = True
                    if self._has_near_terms(text, match_terms, CONDITION_MEDIUM_TERMS):
                        medium_match = True

        if not matched:
            return None

        conditions_text = "、".join(sorted({condition for condition, _ in matched}))
        if high_match or medium_match:
            return "Medium", f"检索证据提示合并{conditions_text}时需谨慎使用、监测或由医生药师确认。"
        return None

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
            concept_count = len(extracted.normalized_drugs) + len(extracted.candidate_drug_groups)
            if concept_count >= 2 and risk_level != "Unknown":
                message = f"{names or '部分药品表达'}未识别为明确药品，未纳入本次相互作用计算。"
            else:
                message = f"{names or '部分药品'}不是明确的具体药品名称，请补充具体名称后再判断。"
            flags.append(SafetyFlag(level="warning", message=message))
        if extracted:
            for group in extracted.candidate_drug_groups:
                evidence_count = len({item.drug for item in evidence if item.drug in set(group.candidates)})
                message = (
                    f"“{group.mention}”已按药物家族展开为 {len(group.candidates)} 个相关制剂，"
                    f"本次基于其中 {evidence_count} 个制剂召回到的说明书证据进行综合判断。"
                )
                flags.append(
                    SafetyFlag(
                        level="info",
                        message=message,
                    )
                )
        if risk_level == "High":
            flags.append(SafetyFlag(level="danger", message="存在高风险或禁忌线索，不建议自行合用。"))
        if not evidence:
            flags.append(SafetyFlag(level="warning", message="未召回足够说明书/指南证据，结论已降级处理。"))
        current_concept_count = (
            len(extracted.normalized_drugs) + len(extracted.candidate_drug_groups)
            if extracted
            else len(snapshot.drugs)
        )
        if current_concept_count < 2:
            flags.append(SafetyFlag(level="info", message="当前上下文少于两个明确药物，无法完整评估相互作用。"))
        population_signal = self._population_evidence_signal(evidence, snapshot.population)
        if population_signal:
            level, message = population_signal
            flag_level = "danger" if level == "High" else "warning"
            flags.append(SafetyFlag(level=flag_level, message=message))
        condition_signal = self._condition_evidence_signal(evidence, snapshot.conditions)
        if condition_signal:
            level, message = condition_signal
            flag_level = "danger" if level == "High" else "warning"
            flags.append(SafetyFlag(level=flag_level, message=message))
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
        current_population: list[str] | None = None,
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
                        current_population=current_population,
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
