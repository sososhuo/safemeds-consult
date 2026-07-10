from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from app.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_SECONDS
from app.schemas.analysis import Evidence, RiskLevel
from app.schemas.consultation import KnowledgeRelation, SafetyFlag

logger = logging.getLogger(__name__)


class LLMClient:
    """Minimal OpenAI-compatible chat client."""

    def __init__(
        self,
        api_key: str = LLM_API_KEY,
        base_url: str = LLM_BASE_URL,
        model: str = LLM_MODEL,
        timeout: float = LLM_TIMEOUT_SECONDS,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        if not self.configured:
            raise RuntimeError("LLM client is not configured")

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload["choices"][0]["message"]["content"].strip()

    def extract_medication_entities(self, message: str) -> dict[str, Any]:
        content = self.chat(build_entity_extraction_prompt(message), temperature=0.0)
        return _parse_json_object(content)


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("LLM entity extraction did not return a JSON object")
    return payload


def build_entity_extraction_prompt(message: str) -> list[dict[str, str]]:
    system = """
你是中文用药咨询系统中的医学实体抽取器，只负责从患者口语问题中抽取药物相关实体。
必须输出严格 JSON，不要输出 Markdown。

抽取原则：
1. specific_drugs 只放明确具体药品或通用名，例如“布洛芬”“华法林”“阿莫西林”。
2. ambiguous_entities 放不够具体、不能代表单一药品的表达，例如“头孢”“降压药”“消炎药”“安眠药”“胃药”“退烧药”“止疼药”。
3. compound_products 放复方或商品化口语表达，例如“感冒灵”“999感冒灵”“白加黑”“泰诺”等。复方药不能直接当作单一具体药物。
4. 不要臆测厂家、剂量或具体成分；如果只是可能成分，要写 possible_ingredients，并提醒以包装或说明书为准。
5. 不要把疾病、症状或检查当药物。
""".strip()
    user = f"""
请抽取下面问题中的用药实体，并输出严格 JSON：

问题：{message}

JSON schema：
{{
  "specific_drugs": [
    {{"mention": "原文提及", "normalized": "标准药品名或通用名", "confidence": 0.0}}
  ],
  "ambiguous_entities": [
    {{
      "mention": "原文提及",
      "entity_type": "drug_class|drug_intent|unclear_drug",
      "normalized": "类别或意图名称",
      "reason": "为什么不够具体",
      "user_message": "请补充具体药品名称"
    }}
  ],
  "compound_products": [
    {{
      "mention": "原文提及",
      "normalized": "复方感冒药等类别",
      "possible_ingredients": ["可能成分1", "可能成分2"],
      "reason": "为什么不能当作单一药品",
      "user_message": "不同厂家成分可能不同，实际以包装或说明书为准"
    }}
  ]
}}
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_consultation_prompt(
    *,
    conclusion: str,
    risk_level: RiskLevel,
    mechanism: str,
    recommendation: str,
    flags: list[SafetyFlag],
    evidence: list[Evidence],
    kg_relations: list[KnowledgeRelation],
    safety_notice: str,
) -> list[dict[str, str]]:
    evidence_text = "\n".join(
        f"- [{idx + 1}] {item.drug}/{item.section}: {item.snippet} (source: {item.source})"
        for idx, item in enumerate(evidence[:5])
    ) or "无可用证据。"
    kg_text = "\n".join(
        f"- {item.subject} --{item.relation}--> {item.object}"
        for item in kg_relations[:8]
    ) or "无结构化图谱关系。"
    flag_text = "\n".join(f"- {item.level}: {item.message}" for item in flags) or "无额外安全标记。"

    system = (
        "你是一个中文用药安全咨询助手。"
        "你只能基于提供的风险等级、机制、证据、知识图谱关系和安全标记生成回答。"
        "不得新增处方、诊断或未经证据支持的确定性结论。"
        "如果证据不足，要明确说明不确定性。"
    )
    user = f"""
请生成一段面向普通用户的中文用药咨询回复。

固定结论：
- 风险等级：{risk_level}
- 结论：{conclusion}
- 机制：{mechanism}
- 建议：{recommendation}

知识图谱关系：
{kg_text}

证据片段：
{evidence_text}

安全标记：
{flag_text}

必须包含安全声明：
{safety_notice}

输出要求：
1. 先给结论，再解释原因。
2. 不要使用“绝对安全”“一定可以”等表达。
3. 不要建议用户自行调整处方药。
4. 保持简洁，分 3-5 小段。
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
