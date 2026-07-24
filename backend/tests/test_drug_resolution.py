"""
药物标准化测试：验证短名、盐酸前缀、省略剂型和候选扩展逻辑。
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.schemas.analysis import DrugCandidateGroup, Evidence, ExtractedContext
from app.services.consultation_service import MedicationConsultationService
from app.services.drug_resolution import (
    DrugNameResolver,
    build_resolution_index,
    derive_base_name,
    strip_salt_prefix,
)
from app.services.stages.risk_assessment import RiskAssessmentStage


def sample_records():
    return [
        {"drug": "感冒灵片", "aliases": [], "sections": []},
        {"drug": "感冒灵颗粒", "aliases": [], "sections": []},
        {"drug": "复方感冒灵片", "aliases": [], "sections": []},
        {"drug": "复方感冒灵颗粒", "aliases": [], "sections": []},
        {"drug": "布洛芬片", "aliases": [], "sections": []},
        {"drug": "布洛芬胶囊", "aliases": [], "sections": []},
        {"drug": "布洛芬凝胶", "aliases": [], "sections": []},
        {"drug": "华法林钠片", "aliases": [], "sections": []},
    ]


class TestDrugResolutionIndex(unittest.TestCase):
    def test_derive_base_name_only_removes_formulation_suffix(self):
        self.assertEqual(derive_base_name("感冒灵颗粒"), "感冒灵")
        self.assertEqual(derive_base_name("复方感冒灵片"), "复方感冒灵")
        self.assertEqual(derive_base_name("复方感冒灵片(双层片)"), "复方感冒灵")

    def test_salt_prefix_short_names_are_generated(self):
        records = [
            {"drug": "盐酸二甲双胍片", "aliases": [], "sections": []},
            {"drug": "盐酸二甲双胍缓释片", "aliases": [], "sections": []},
        ]

        index = build_resolution_index(records)
        resolver = DrugNameResolver(records)
        drugs, groups = resolver.resolve("长期吃二甲双胍片")
        _, family_groups = resolver.resolve("长期吃二甲双胍")

        self.assertEqual(strip_salt_prefix("盐酸二甲双胍片"), "二甲双胍片")
        self.assertEqual(index["aliases"]["二甲双胍片"], ["盐酸二甲双胍片"])
        self.assertEqual(drugs, ["盐酸二甲双胍片"])
        self.assertEqual(groups, [])
        self.assertEqual(family_groups[0]["normalized"], "二甲双胍")
        self.assertEqual(
            family_groups[0]["candidates"],
            ["盐酸二甲双胍片", "盐酸二甲双胍缓释片"],
        )

    def test_generated_index_keeps_regular_and_compound_families_separate(self):
        index = build_resolution_index(sample_records())

        self.assertEqual(index["base_names"]["感冒灵"], ["感冒灵片", "感冒灵颗粒"])
        self.assertEqual(
            index["base_names"]["复方感冒灵"],
            ["复方感冒灵片", "复方感冒灵颗粒"],
        )

    def test_resolver_uses_longest_exact_match(self):
        resolver = DrugNameResolver(sample_records())

        drugs, groups = resolver.resolve("复方感冒灵片和布洛芬片能一起吃吗")

        self.assertEqual(set(drugs), {"复方感冒灵片", "布洛芬片"})
        self.assertEqual(groups, [])
        self.assertNotIn("感冒灵片", drugs)

    def test_oral_context_excludes_topical_candidates(self):
        resolver = DrugNameResolver(sample_records())

        _, groups = resolver.resolve("布洛芬能吃吗")

        self.assertEqual(groups[0]["candidates"], ["布洛芬片", "布洛芬胶囊"])

    def test_manual_alias_is_loaded_from_generated_index(self):
        records = sample_records()
        index = build_resolution_index(
            records,
            [
                {
                    "alias": "华法林",
                    "targets": ["华法林钠片"],
                    "source": "manual_review",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "drug_resolution_index.json"
            index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
            resolver = DrugNameResolver(records, index_path)

            drugs, groups = resolver.resolve("布洛芬和华法林能一起吃吗")

        self.assertIn("华法林钠片", drugs)
        self.assertEqual(groups[0]["normalized"], "布洛芬")


class TestCandidateConsensus(unittest.TestCase):
    def _service(self, second_candidate_has_evidence: bool = True):
        interaction_section = {
            "title": "药物相互作用",
            "content": "与抗凝药合用可能增加出血风险。",
        }
        records = [
            {"drug": "甲药片", "aliases": [], "sections": [interaction_section], "interactions": []},
            {
                "drug": "甲药颗粒",
                "aliases": [],
                "sections": [interaction_section] if second_candidate_has_evidence else [],
                "interactions": [],
            },
            {"drug": "乙药片", "aliases": [], "sections": [interaction_section], "interactions": []},
        ]
        service = MedicationConsultationService.__new__(MedicationConsultationService)
        service.records = records
        service.risk_engine = RiskAssessmentStage(records)
        return service

    def test_consistent_candidate_group_can_be_assessed_as_one_drug_concept(self):
        service = self._service()
        group = DrugCandidateGroup(
            mention="甲药",
            normalized="甲药",
            candidates=["甲药片", "甲药颗粒"],
            source="derived_base_name",
        )
        extracted = ExtractedContext(
            drugs=["乙药片"],
            normalized_drugs=["乙药片"],
            population=[],
            conditions=[],
            risk_factors=[],
            candidate_drug_groups=[group],
        )
        evidence = [
            Evidence(
                source="unit",
                drug="甲药片",
                section="药物相互作用",
                snippet="与抗凝药合用可能增加出血风险。",
                score=1.0,
            )
        ]

        risk_level, _, _ = service._assess(
            ["乙药片", "甲药片", "甲药颗粒"],
            evidence,
            extracted=extracted,
            drug_concept_count=2,
            candidate_groups=[group],
        )

        self.assertEqual(risk_level, "Medium")

    def test_partial_family_evidence_can_still_drive_risk(self):
        service = self._service(second_candidate_has_evidence=False)
        group = DrugCandidateGroup(
            mention="甲药",
            normalized="甲药",
            candidates=["甲药片", "甲药颗粒"],
            source="derived_base_name",
        )

        risk_level, mechanism, _ = service._assess(
            ["乙药片", "甲药片", "甲药颗粒"],
            [
                Evidence(
                    source="unit",
                    drug="甲药片",
                    section="药物相互作用",
                    snippet="与抗凝药合用可能增加出血风险。",
                    score=1.0,
                )
            ],
            drug_concept_count=2,
            candidate_groups=[group],
        )

        self.assertEqual(risk_level, "Medium")
        self.assertIn("监测", mechanism)


if __name__ == "__main__":
    unittest.main()
