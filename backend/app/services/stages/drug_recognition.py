"""
Stage 1：药物实体识别
========================
从用户输入中抽取药物实体、特殊人群、疾病和风险因素。
改进点：
  1. 支持否定语境（不吃、没吃、未服用）
  2. 补全 interaction 中被引用的药物别名
  3. 处理组合提及（"华法林和布洛芬一起吃"）
  4. 多策略匹配：别名匹配 + 词典辅助 + 字符级匹配
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from app.core.config import LLM_ENABLE_EXTRACTION
from app.schemas.analysis import ExtractedContext
from app.services.llm_service import LLMClient
from app.services.stages.base import BaseStage, StageContext

# ---------- 中文否定模式 ----------
NEGATION_PATTERNS: List[Tuple[str, int]] = [
    # (正则, 前视窗口字符数)
    (r"(?:没有|没|不|未|拒绝)\s*(?:在\s*)?(?:服用|使用|吃[了]?|用[了]?|打|注射|口服)", 6),
    (r"(?:不能|不可|禁止)\s*(?:同时\s*)?(?:服用|使用|吃|用|合用)", 6),
    (r"(?:停[了]?|停止|暂停)\s*(?:服用|使用|吃|用)", 5),
    (r"(?:停[了]?|停止|暂停)", 6),
    (r"(?:不\s*(?:需要|建议|推荐|应该)\s*(?:服用|使用|吃|用))", 6),
]

# ---------- 组合提及模式 ----------
COMBINATION_PATTERN = re.compile(
    r"([一-鿿\w]+)\s*(?:和|与|及|、|,|，|\+)\s*([一-鿿\w]+)"
)

# ---------- 特殊人群关键词 ----------
POPULATION_PATTERNS: List[Tuple[str, str]] = [
    ("老年", "老年人"),
    ("老人", "老年人"),
    ("高龄", "老年人"),
    ("孕", "妊娠/备孕"),
    ("哺乳", "哺乳期"),
    ("儿童", "儿童"),
    ("婴幼儿", "儿童"),
    ("小儿", "儿童"),
    ("肾", "肾功能相关"),
    ("肝", "肝功能相关"),
    ("透析", "肾功能相关"),
    ("心衰", "心力衰竭"),
]

AGE_PATTERN = re.compile(
    r"(?<![\d.])(?P<age>\d{1,3}|[零〇一二两三四五六七八九十百]{1,8})\s*(?:岁|周岁|岁半|周岁半)"
)
CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

# ---------- 疾病关键词 ----------
CONDITION_KEYWORDS = [
    "高血压", "糖尿病", "房颤", "心房颤动", "感染", "感冒",
    "冠心病", "冠脉", "肾功能不全", "肝功能不全", "心衰",
    "心力衰竭", "高血脂", "高脂血症", "哮喘", "痛风",
    "肠胃炎", "胃肠炎", "胃炎", "肠炎", "消化道溃疡",
]

# ---------- 风险因素关键词 ----------
RISK_FACTOR_KEYWORDS = [
    "出血", "抗凝", "低血压", "高钾", "低钾", "肾功能",
    "肝功能", "肌痛", "肌无力", "横纹肌", "过敏",
    "胃肠道", "消化道", "胃痛", "腹痛",
]


def parse_age_token(value: str) -> int | None:
    """Parse Arabic or common Chinese age numerals into an integer age."""
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        age = int(value)
        return age if 0 <= age <= 130 else None
    if any(char not in CHINESE_DIGITS and char not in {"十", "百"} for char in value):
        return None

    if "百" in value:
        left, _, right = value.partition("百")
        hundreds = CHINESE_DIGITS.get(left, 1 if not left else None)
        if hundreds is None:
            return None
        rest = parse_age_token(right) if right else 0
        if rest is None:
            return None
        age = hundreds * 100 + rest
        return age if 0 <= age <= 130 else None

    if "十" in value:
        left, _, right = value.partition("十")
        tens = CHINESE_DIGITS.get(left, 1 if not left else None)
        ones = CHINESE_DIGITS.get(right, 0 if not right else None)
        if tens is None or ones is None:
            return None
        age = tens * 10 + ones
        return age if 0 <= age <= 130 else None

    if len(value) == 1:
        return CHINESE_DIGITS.get(value)
    return None


def population_from_age(age: int) -> str | None:
    """Map age to medication-safety populations.

    Uses common international cutoffs: pediatric patients are under 18 years;
    older adults are 65 years and above.
    """
    if age < 18:
        return "儿童"
    if age >= 65:
        return "老年人"
    return None


def build_drug_dictionary(records: list[Dict]) -> Dict[str, Dict]:
    """
    从知识库构建完整的药物字典，包含别名、英文名、中文名。
    同时补全 interaction 中被引用但无独立条目的药物。
    """
    drug_dict: Dict[str, Dict] = {}
    canonical_names = {item["drug"].lower(): item["drug"] for item in records}

    # 补充高频交互对象（防止只出现在 interaction 中而无法被识别）
    SUPPLEMENTARY_DRUGS: Dict[str, List[str]] = {
        "methotrexate": ["甲氨蝶呤", "氨甲蝶呤", "mtx", "methotrexate"],
        "cyclosporine": ["环孢素", "环孢菌素", "环孢霉素", "新山地明", "cyclosporine", "ciclosporin"],
        "lithium": ["锂剂", "碳酸锂", "锂盐", "lithium"],
        "verapamil": ["维拉帕米", "异搏定", "verapamil"],
        "ketoconazole": ["酮康唑", "ketoconazole"],
        "theophylline": ["茶碱", "theophylline"],
        "tamoxifen": ["他莫昔芬", "三苯氧胺", "tamoxifen"],
        "amiodarone": ["胺碘酮", "可达龙", "amiodarone"],
        "hydrochlorothiazide": ["氢氯噻嗪", "双氢克尿噻", "hydrochlorothiazide", "hctz"],
        "gemfibrozil": ["吉非贝齐", "gemfibrozil"],
        "oral_contraceptives": ["口服避孕药", "避孕药", "oral contraceptives"],
        "calcium_carbonate": ["碳酸钙", "钙片", "calcium carbonate"],
        "prednisone": ["泼尼松", "强的松", "prednisone"],
        "contrast_media": ["造影剂", "对比剂", "contrast media"],
        "fentanyl": ["芬太尼", "芬太尼贴", "芬太尼透皮贴", "fentanyl"],
    }

    # 从知识库记录中提取，真实药名优先，避免脏别名覆盖独立药品。
    for item in records:
        drug = item["drug"]
        for variant in drug_name_variants(drug):
            drug_dict[variant.lower()] = {"canonical": drug, "source": "knowledge_base"}

    for item in records:
        drug = item["drug"]
        for name in item.get("aliases", []):
            lower_name = name.lower()
            if lower_name in canonical_names and canonical_names[lower_name] != drug:
                continue
            if lower_name in drug_dict and drug_dict[lower_name]["canonical"] != drug:
                continue
            for variant in drug_name_variants(name):
                variant_key = variant.lower()
                if variant_key in canonical_names and canonical_names[variant_key] != drug:
                    continue
                if variant_key in drug_dict and drug_dict[variant_key]["canonical"] != drug:
                    continue
                drug_dict[variant_key] = {"canonical": drug, "source": "knowledge_base_alias"}

    # 补充高频交互对象
    for canonical, aliases in SUPPLEMENTARY_DRUGS.items():
        for name in [canonical] + aliases:
            lower_name = name.lower()
            if lower_name not in drug_dict:
                drug_dict[lower_name] = {"canonical": canonical, "source": "interaction_ref"}

    return drug_dict


def drug_name_variants(name: str) -> set[str]:
    variants = {name}
    if "阿司匹林" in name:
        variants.add(name.replace("阿司匹林", "阿斯匹林"))
    if "阿斯匹林" in name:
        variants.add(name.replace("阿斯匹林", "阿司匹林"))
    return variants


class DrugRecognitionStage(BaseStage):
    """药物实体识别阶段。"""

    def __init__(self, records: List[Dict]):
        self.records = records
        # 别名 -> 标准名映射
        self.alias_map: Dict[str, str] = {}
        canonical_names = {item["drug"].lower(): item["drug"] for item in records}
        for item in records:
            for variant in drug_name_variants(item["drug"]):
                self.alias_map[variant.lower()] = item["drug"]
        for item in records:
            for alias in item.get("aliases", []):
                alias_key = alias.lower()
                for variant in drug_name_variants(alias):
                    variant_key = variant.lower()
                    if variant_key in canonical_names and canonical_names[variant_key] != item["drug"]:
                        continue
                    if variant_key in self.alias_map and self.alias_map[variant_key] != item["drug"]:
                        continue
                    self.alias_map[variant_key] = item["drug"]
        # 完整的药物词典（含补充药物）
        self.drug_dict = build_drug_dictionary(records)
        # 知识库中的已知药物集合
        self.known_drugs = set(item["drug"] for item in records)
        self.llm_client = LLMClient()

    @property
    def name(self) -> str:
        return "药物识别 Stage"

    def execute_on_text(self, question: str) -> ExtractedContext:
        """便捷方法：直接对文本运行实体识别，返回 ExtractedContext（用于测试）。"""
        return self._extract(question)

    def execute(self, ctx: StageContext) -> StageContext:
        question = ctx.question
        extracted = self._extract(question)
        ctx.extracted = extracted
        detail = (
            f"识别到 {len(extracted.normalized_drugs)} 个标准药物实体"
            f"{', 含 ' + str(len(extracted.population)) + ' 个人群标签' if extracted.population else ''}"
        )
        ctx.add_trace(agent=self.name, status="完成", detail=detail)
        return ctx

    def _extract(self, question: str) -> ExtractedContext:
        drugs = self._extract_drugs(question)
        ambiguous_entities = self._extract_llm_entities(question, drugs)
        drugs = self._filter_negated(question, drugs)
        normalized = sorted(set(drugs))

        population = self._extract_population(question)
        conditions = self._extract_conditions(question)
        risk_factors = self._extract_risk_factors(question)

        return ExtractedContext(
            drugs=normalized,
            normalized_drugs=normalized,
            population=sorted(set(population)),
            conditions=conditions,
            risk_factors=risk_factors,
            ambiguous_entities=ambiguous_entities,
        )

    def _extract_llm_entities(self, question: str, found_drugs: List[str]) -> List[dict]:
        if not LLM_ENABLE_EXTRACTION or not self.llm_client.configured:
            return []

        try:
            payload = self.llm_client.extract_medication_entities(question)
        except Exception:
            return []

        ambiguous: List[dict] = []
        seen_drugs = set(found_drugs)

        for item in payload.get("specific_drugs", []) or []:
            mention = str(item.get("mention", "")).strip()
            normalized = str(item.get("normalized", "")).strip()
            mention_canonical = self._canonical_from_llm_value(mention)
            normalized_canonical = self._canonical_from_llm_value(normalized)
            canonical = mention_canonical or normalized_canonical
            if canonical and canonical in self.known_drugs:
                if mention and not mention_canonical:
                    ambiguous.append(
                        {
                            "mention": mention,
                            "entity_type": "uncertain_specific_drug",
                            "normalized": normalized or mention,
                            "reason": "原文提及未能直接匹配到知识库药品，暂不使用 LLM 归一化结果进行精确计算。",
                            "user_message": "请补充或确认完整药品名称。",
                        }
                    )
                    continue
                if canonical not in seen_drugs:
                    found_drugs.append(canonical)
                    seen_drugs.add(canonical)
            elif mention or normalized:
                ambiguous.append(
                    {
                        "mention": mention or normalized,
                        "entity_type": "unknown_specific_drug",
                        "normalized": normalized or mention,
                        "reason": "LLM 识别到可能的具体药品，但当前知识库未收录，不能纳入精确相互作用计算。",
                        "user_message": "请补充或确认具体药品名称。",
                    }
                )

        for item in payload.get("ambiguous_entities", []) or []:
            mention = str(item.get("mention", "")).strip()
            if not mention:
                continue
            ambiguous.append(
                {
                    "mention": mention,
                    "entity_type": item.get("entity_type") or "unclear_drug",
                    "normalized": item.get("normalized") or mention,
                    "reason": item.get("reason") or "该表达不是明确的单一药品名称。",
                    "user_message": item.get("user_message") or "请补充具体药品名称。",
                }
            )

        for item in payload.get("compound_products", []) or []:
            mention = str(item.get("mention", "")).strip()
            if not mention:
                continue
            ambiguous.append(
                {
                    "mention": mention,
                    "entity_type": "compound_product",
                    "normalized": item.get("normalized") or "复方药品",
                    "possible_ingredients": item.get("possible_ingredients") or [],
                    "reason": item.get("reason") or "复方药品不同厂家成分可能不同，不能当作单一药品计算相互作用。",
                    "user_message": item.get("user_message") or "不同厂家成分可能不同，实际以包装或说明书为准。",
                }
            )

        return self._dedupe_ambiguous(ambiguous)

    def _canonical_from_llm_value(self, value: str) -> str | None:
        key = value.lower().strip()
        if not key:
            return None
        if key in self.alias_map:
            return self.alias_map[key]
        if key in self.drug_dict:
            return self.drug_dict[key]["canonical"]
        return None

    def _dedupe_ambiguous(self, items: List[dict]) -> List[dict]:
        result = []
        seen = set()
        for item in items:
            key = (item.get("mention"), item.get("entity_type"), item.get("normalized"))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def _extract_drugs(self, question: str) -> List[str]:
        """多策略药物实体抽取。"""
        lower = question.lower()
        found: List[str] = []

        # 策略 1：精确别名匹配
        for alias, canonical in self.alias_map.items():
            if len(alias) >= 2 and alias in lower:
                found.append(canonical)

        # 策略 2：从 drug_dict 匹配（覆盖补充药物）
        for name, info in self.drug_dict.items():
            if len(name) >= 2 and name in lower:
                canonical = info["canonical"]
                if canonical not in found:
                    found.append(canonical)

        # 策略 3：组合提及拆分——"华法林和布洛芬"
        for m in COMBINATION_PATTERN.finditer(question):
            for group in (m.group(1), m.group(2)):
                g_lower = group.lower().strip()
                if g_lower in self.alias_map:
                    c = self.alias_map[g_lower]
                    if c not in found:
                        found.append(c)
                elif g_lower in self.drug_dict:
                    c = self.drug_dict[g_lower]["canonical"]
                    if c not in found:
                        found.append(c)

        # 策略 4：跳过被否定的药物
        found = self._filter_negated(question, found)

        return found

    def _filter_negated(self, question: str, drugs: List[str]) -> List[str]:
        """过滤被否定语境排除的药物。"""
        negated_drugs: List[str] = []

        # 对每个否定模式，查找否定词后的药物名
        for neg_re, lookback in NEGATION_PATTERNS:
            for m in re.finditer(neg_re, question):
                neg_end = m.end()
                # 从否定词后开始搜索，看接下来提到什么药
                tail = question[neg_end : neg_end + lookback].lower()
                for name, info in self.drug_dict.items():
                    if len(name) >= 2 and name in tail:
                        negated_drugs.append(info["canonical"])

        return [d for d in drugs if d not in set(negated_drugs)]

    def _extract_population(self, question: str) -> List[str]:
        result = []
        for match in AGE_PATTERN.finditer(question):
            age = parse_age_token(match.group("age"))
            if age is None:
                continue
            label = population_from_age(age)
            if label:
                result.append(label)
        for pattern, label in POPULATION_PATTERNS:
            if pattern in question:
                result.append(label)
        return result

    def _extract_conditions(self, question: str) -> List[str]:
        matched = [kw for kw in CONDITION_KEYWORDS if kw in question]
        result: list[str] = []
        for item in sorted(matched, key=len, reverse=True):
            if any(item != kept and item in kept for kept in result):
                continue
            result.append(item)
        return sorted(result)

    def _extract_risk_factors(self, question: str) -> List[str]:
        return [kw for kw in RISK_FACTOR_KEYWORDS if kw in question]
