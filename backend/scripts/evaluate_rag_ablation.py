"""
RAG 消融评估脚本：对比不同检索配置下的召回和回答效果。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.data_store import load_knowledge
from app.repositories.consultation_repository import ConsultationRepository
from app.schemas.analysis import Evidence
from app.schemas.consultation import SessionSnapshot
from app.services.consultation_service import MedicationConsultationService
from app.services.rag_service import BM25RagIndex, ChromaRagIndex, HybridRagIndex


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    group: str
    question: str
    expected_risk: str
    expected_terms: tuple[str, ...]


class EmptyKnowledgeGraph:
    def query(self, entities, depth=1, limit=16):
        return []

    def health(self):
        return {
            "kg_status": "disabled",
            "kg_backend": "none",
            "kg_nodes": 0,
            "kg_relations": 0,
            "neo4j_uri": "",
            "neo4j_database": "",
        }


class SuccessfulLLM:
    configured = True

    def chat(self, prompt: str) -> str:
        return "mocked successful grounded answer"


class DenseBm25NoRerankIndex(HybridRagIndex):
    """Chroma + BM25 with RRF fusion, intentionally without medical reranking."""

    def retrieve(self, query: str, drugs: list[str], top_k: int = 8) -> list[Evidence]:
        candidate_k = max(top_k * 4, 16)
        bm25_results = self.bm25.retrieve(query, drugs, top_k=candidate_k)
        dense_results = self.dense.retrieve(query, drugs, top_k=candidate_k)
        fused = self._rrf_fuse({"bm25": bm25_results, "dense": dense_results}, drugs=drugs)
        return fused[:top_k]


def build_cases() -> list[EvalCase]:
    return [
        # 儿童
        EvalCase("child_01", "儿童", "我7岁，发烧了，可以吃左氧氟沙星片吗？", "High", ("18岁以下", "儿童", "禁用", "关节")),
        EvalCase("child_02", "儿童", "我3岁，家里只有对乙酰氨基酚片，能直接吃吗？", "High", ("3岁以下", "儿童", "避免", "肝")),
        EvalCase("child_03", "儿童", "我12岁感冒发热，可以吃阿司匹林肠溶片退烧吗？", "High", ("儿童", "青少年", "Reye", "病毒")),
        EvalCase("child_04", "儿童", "我8岁，能用奥美拉唑肠溶胶囊治胃痛吗？", "High", ("儿童", "婴幼儿", "禁用", "经验")),
        EvalCase("child_05", "儿童", "我15岁，能同时吃阿司匹林肠溶片和布洛芬胶囊止痛吗？", "High", ("出血", "胃肠道", "不宜", "同用")),
        EvalCase("child_06", "儿童", "我6岁咳嗽，能吃利巴韦林颗粒吗？", "High", ("儿童", "缺乏", "资料", "慎")),
        EvalCase("child_07", "儿童", "我10岁，有癫痫，能吃卡马西平片吗？", "High", ("儿童", "血", "肝功能", "检查")),
        EvalCase("child_08", "儿童", "我9岁，能用地高辛片吗？", "High", ("儿童", "新生儿", "敏感", "剂量")),
        # 成人
        EvalCase("adult_01", "成人", "我35岁，正在吃华法林钠片，能加阿司匹林肠溶片吗？", "High", ("华法林", "阿司匹林", "抗凝", "出血")),
        EvalCase("adult_02", "成人", "我40岁，吃华法林钠片期间能吃布洛芬胶囊止痛吗？", "High", ("华法林", "布洛芬", "出血", "抗凝")),
        EvalCase("adult_03", "成人", "我45岁，辛伐他汀片和克拉霉素片能一起吃吗？", "High", ("辛伐他汀", "克拉霉素", "横纹肌溶解", "危险")),
        EvalCase("adult_04", "成人", "我50岁，硫酸氢氯吡格雷片和奥美拉唑肠溶胶囊能同服吗？", "High", ("氯吡格雷", "奥美拉唑", "避免", "相互作用")),
        EvalCase("adult_05", "成人", "我38岁，甲氨蝶呤片治疗期间可以吃布洛芬胶囊吗？", "High", ("甲氨蝶呤", "布洛芬", "血药浓度", "毒性")),
        EvalCase("adult_06", "成人", "我30岁，卡马西平片和克拉霉素片可以一起吃吗？", "High", ("卡马西平", "克拉霉素", "血药浓度", "监测")),
        EvalCase("adult_07", "成人", "我42岁，地高辛片和奥美拉唑肠溶胶囊可以同服吗？", "High", ("地高辛", "奥美拉唑", "避免", "相互作用")),
        EvalCase("adult_08", "成人", "我36岁，螺内酯片和布洛芬胶囊能一起吃吗？", "High", ("螺内酯", "非甾体", "肾毒性", "高钾")),
        # 孕妇
        EvalCase("pregnant_01", "孕妇", "我怀孕8周，能吃华法林钠片吗？", "High", ("妊娠", "禁用", "致畸", "胎儿")),
        EvalCase("pregnant_02", "孕妇", "我孕中期感冒，能吃利巴韦林颗粒吗？", "High", ("孕妇", "禁用", "致畸", "胚胎毒性")),
        EvalCase("pregnant_03", "孕妇", "我怀孕了，能继续吃辛伐他汀片吗？", "High", ("妊娠", "孕妇", "禁用", "胎儿")),
        EvalCase("pregnant_04", "孕妇", "我备孕期间长痘，能吃异维A酸软胶囊吗？", "High", ("孕妇", "禁用", "避孕", "妊娠")),
        EvalCase("pregnant_05", "孕妇", "我怀孕期间牙疼，可以吃布洛芬胶囊吗？", "High", ("孕妇", "哺乳期", "禁用", "慎用")),
        EvalCase("pregnant_06", "孕妇", "我怀孕期间感染，可以吃左氧氟沙星片吗？", "High", ("孕妇", "禁用", "关节", "喹诺酮")),
        EvalCase("pregnant_07", "孕妇", "我怀孕期间胃痛，可以吃奥美拉唑肠溶胶囊吗？", "High", ("孕妇", "一般不用", "慎用", "哺乳")),
        EvalCase("pregnant_08", "孕妇", "我怀孕期间能吃甲氨蝶呤片吗？", "High", ("致畸", "禁怀孕", "哺乳", "孕")),
        # 老年人
        EvalCase("elderly_01", "老年人", "我70岁，正在吃华法林钠片，能加阿司匹林肠溶片吗？", "High", ("老年", "华法林", "阿司匹林", "出血")),
        EvalCase("elderly_02", "老年人", "我78岁糖尿病，能吃盐酸二甲双胍片吗？", "High", ("65岁", "80岁", "肾功能", "不推荐")),
        EvalCase("elderly_03", "老年人", "我72岁，地高辛片和螺内酯片能一起用吗？", "High", ("老年", "地高辛", "螺内酯", "血药浓度")),
        EvalCase("elderly_04", "老年人", "我68岁，吃辛伐他汀片期间能用克拉霉素片吗？", "High", ("老年", "辛伐他汀", "克拉霉素", "横纹肌溶解")),
        EvalCase("elderly_05", "老年人", "我80岁肾功能不好，可以吃左氧氟沙星片吗？", "High", ("老年", "肾功能", "减量", "慎用")),
        EvalCase("elderly_06", "老年人", "我75岁，能用螺内酯片治疗水肿吗？", "High", ("老年", "高钾血症", "利尿过度", "禁用")),
        EvalCase("elderly_07", "老年人", "我73岁，吃卡马西平片安全吗？", "High", ("老年", "敏感", "认知", "房室传导")),
        EvalCase("elderly_08", "老年人", "我76岁，能吃对乙酰氨基酚片止痛吗？", "High", ("老年", "肝", "肾", "减量")),
    ]


def has_evidence_hit(evidence: list[Evidence], case: EvalCase, drugs: list[str]) -> bool:
    if not evidence:
        return False
    text = " ".join(f"{item.drug} {item.section} {item.snippet}" for item in evidence)
    term_hit = any(term in text for term in case.expected_terms)
    if not drugs:
        return term_hit
    drug_hit = any(item.drug in set(drugs) for item in evidence)
    return term_hit and drug_hit


def run_variant(
    service: MedicationConsultationService,
    cases: list[EvalCase],
    *,
    name: str,
    index,
    use_kg: bool,
    use_current_rules: bool,
) -> dict[str, Any]:
    original_index = service.vector_index
    original_kg = service.kg
    service.vector_index = index
    if not use_kg:
        service.kg = EmptyKnowledgeGraph()
    rows: list[dict[str, Any]] = []
    started = perf_counter()

    for case in cases:
        state: dict[str, Any] = {
            "message": case.question,
            "previous_snapshot": SessionSnapshot(),
            "workflow_trace": [],
        }
        for step in [
            service.workflow._extract_entities,
            service.workflow._retrieve_evidence,
            service.workflow._query_kg,
            service.workflow._assess_risk,
        ]:
            state = step(state)

        if not use_current_rules:
            # Baselines should reflect retrieval differences only. Remove the
            # current system's extra direct population evidence and reprioritize
            # from the raw retrieval result.
            extracted = state["extracted"]
            query = service._build_evidence_query(
                case.question,
                [],
                state.get("query_drugs", []),
                extracted,
                state.get("snapshot"),
            )
            evidence = index.retrieve(query, state.get("query_drugs", []), top_k=8)
            risk_level, mechanism, pair_hit = service._assess(
                state.get("query_drugs", []),
                evidence,
                extracted,
                state.get("snapshot"),
            )
            state = {
                **state,
                "kg_relations": [],
                "evidence": evidence,
                "risk_level": risk_level,
                "mechanism": mechanism,
                "pair_hit": pair_hit,
            }

        state = service.workflow._prepare_answer(state)
        drugs = state.get("query_drugs", [])
        evidence = state.get("evidence", [])
        rows.append(
            {
                "case_id": case.case_id,
                "group": case.group,
                "question": case.question,
                "expected_risk": case.expected_risk,
                "predicted_risk": state.get("risk_level"),
                "high_risk_correct": state.get("risk_level") == case.expected_risk,
                "evidence_hit": has_evidence_hit(evidence, case, drugs),
                "evidence_count": len(evidence),
                "kg_relation_count": len(state.get("kg_relations", [])),
                "fallback_used": bool(state.get("llm_fallback_used", False)),
                "drugs": drugs,
                "top_evidence": [
                    {
                        "drug": item.drug,
                        "section": item.section,
                        "score": item.score,
                        "snippet": item.snippet[:120],
                    }
                    for item in evidence[:3]
                ],
            }
        )

    service.vector_index = original_index
    service.kg = original_kg

    total = len(rows)
    return {
        "name": name,
        "total_cases": total,
        "elapsed_seconds": round(perf_counter() - started, 2),
        "high_risk_accuracy": round(sum(row["high_risk_correct"] for row in rows) / total, 4),
        "evidence_recall_hit_rate": round(sum(row["evidence_hit"] for row in rows) / total, 4),
        "unknown_rate": round(sum(row["predicted_risk"] == "Unknown" for row in rows) / total, 4),
        "fallback_rate": round(sum(row["fallback_used"] for row in rows) / total, 4),
        "risk_distribution": dict(Counter(row["predicted_risk"] for row in rows)),
        "by_group": summarize_by_group(rows),
        "cases": rows,
    }


def summarize_by_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["group"], []).append(row)
    summary = {}
    for group, items in grouped.items():
        total = len(items)
        summary[group] = {
            "total_cases": total,
            "high_risk_accuracy": round(sum(item["high_risk_correct"] for item in items) / total, 4),
            "evidence_recall_hit_rate": round(sum(item["evidence_hit"] for item in items) / total, 4),
            "unknown_rate": round(sum(item["predicted_risk"] == "Unknown" for item in items) / total, 4),
        }
    return summary


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# SafeMeds RAG Ablation Evaluation",
        "",
        f"- Test cases: {report['case_count']} ({', '.join(f'{k} {v}' for k, v in report['case_groups'].items())})",
        "- Metrics: high-risk accuracy, evidence recall hit rate, Unknown rate, fallback rate",
        "- Note: LLM answer generation is mocked as successful to isolate retrieval and risk workflow differences.",
        "",
        "| Variant | High-risk accuracy | Evidence recall hit rate | Unknown rate | Fallback rate | Risk distribution |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for variant in report["variants"]:
        lines.append(
            "| {name} | {acc:.1%} | {recall:.1%} | {unknown:.1%} | {fallback:.1%} | {dist} |".format(
                name=variant["name"],
                acc=variant["high_risk_accuracy"],
                recall=variant["evidence_recall_hit_rate"],
                unknown=variant["unknown_rate"],
                fallback=variant["fallback_rate"],
                dist=", ".join(f"{k}: {v}" for k, v in variant["risk_distribution"].items()),
            )
        )
    lines.extend(["", "## Group Breakdown", ""])
    for variant in report["variants"]:
        lines.extend([
            f"### {variant['name']}",
            "",
            "| Group | High-risk accuracy | Evidence recall hit rate | Unknown rate |",
            "| --- | ---: | ---: | ---: |",
        ])
        for group, item in variant["by_group"].items():
            lines.append(
                f"| {group} | {item['high_risk_accuracy']:.1%} | {item['evidence_recall_hit_rate']:.1%} | {item['unknown_rate']:.1%} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    output_dir = BACKEND / "data" / "processed" / "eval"
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = build_cases()
    records = load_knowledge()
    repository = ConsultationRepository(db_path=output_dir / "ablation_tmp.sqlite3")
    service = MedicationConsultationService(records, repository=repository)
    service.llm_client = SuccessfulLLM()

    dense = ChromaRagIndex(records)
    bm25_dense = DenseBm25NoRerankIndex(records, dense_index=dense)
    current = HybridRagIndex(records, dense_index=dense)

    variants = [
        run_variant(
            service,
            cases,
            name="Baseline A: Chroma only",
            index=dense,
            use_kg=False,
            use_current_rules=False,
        ),
        run_variant(
            service,
            cases,
            name="Baseline B: Chroma + BM25",
            index=bm25_dense,
            use_kg=False,
            use_current_rules=False,
        ),
        run_variant(
            service,
            cases,
            name="Current: Chroma + BM25 + rules + KG",
            index=current,
            use_kg=True,
            use_current_rules=True,
        ),
    ]

    report = {
        "case_count": len(cases),
        "case_groups": dict(Counter(case.group for case in cases)),
        "variants": variants,
    }
    json_path = output_dir / "rag_ablation_eval.json"
    md_path = output_dir / "rag_ablation_eval.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, md_path)

    print(json.dumps(
        {
            "json": str(json_path),
            "markdown": str(md_path),
            "summary": [
                {
                    "name": item["name"],
                    "high_risk_accuracy": item["high_risk_accuracy"],
                    "evidence_recall_hit_rate": item["evidence_recall_hit_rate"],
                    "unknown_rate": item["unknown_rate"],
                    "fallback_rate": item["fallback_rate"],
                    "risk_distribution": item["risk_distribution"],
                }
                for item in variants
            ],
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
