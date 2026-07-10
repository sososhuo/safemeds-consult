"""
临床指南 PDF 结构化提取管道
===========================
将 backend/data/guidelines/ 目录下的 PDF 文件解析为结构化药物交互数据，
合并到现有知识库中。

支持的 PDF 类型:
  - 药品说明书扫描件/电子版
  - 临床用药指南
  - 药物相互作用专题文献

提取策略:
  1. 按页提取文本
  2. 按标题/章节切分（识别「药物相互作用」「禁忌」「注意事项」等关键章节）
  3. 生成与 drug_knowledge_zh.json 相同格式的记录
  4. 合并到现有知识库

依赖: pip install pymupdf (即 fitz)

运行: python -m scripts.ingest_guidelines
      python -m scripts.ingest_guidelines --dir /path/to/pdfs
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

GUIDELINES_DIR = Path(__file__).resolve().parents[1] / "data" / "guidelines"
KNOWLEDGE_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "drug_knowledge_zh.json"

# 章节标题关键词 —— 用于从 PDF 中识别相关章节
SECTION_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("药物相互作用", ["药物相互作用", "相互作用", "drug interaction", "合用", "联合用药", "配伍"]),
    ("禁忌", ["禁忌", "contraindication", "禁忌症", "禁忌证"]),
    ("警告与注意事项", ["警告", "注意事项", "warning", "precaution", "慎用"]),
    ("不良反应", ["不良反应", "副作用", "adverse", "side effect"]),
    ("用法用量", ["用法用量", "用法", "用量", "dosage", "剂量"]),
    ("特殊人群", ["特殊人群", "老年", "儿童", "妊娠", "哺乳", "肝功能", "肾功能"]),
]

# 药物名称模式 —— 用于从文本中提取药物实体
DRUG_NAME_PATTERNS = [
    # 中文药名（2-6字 + 可选的盐/酸/钠等后缀）
    r"[一-鿿]{2,6}(?:片|胶囊|注射液|滴丸|颗粒|口服液|缓释片)?",
]


def extract_text_from_pdf(pdf_path: Path) -> List[Dict[str, Any]]:
    """从 PDF 中按页提取文本，返回 [{page: int, text: str}]"""
    if fitz is None:
        raise ImportError("需要安装 pymupdf: pip install pymupdf")

    doc = fitz.open(str(pdf_path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            pages.append({"page": i + 1, "text": text.strip()})
    doc.close()
    return pages


def classify_section(text: str) -> Optional[str]:
    """判断文本片段属于哪个标准章节"""
    text_lower = text.lower()
    for section_name, keywords in SECTION_KEYWORDS:
        for kw in keywords:
            if kw.lower() in text_lower:
                return section_name
    return None


def split_into_sections(full_text: str) -> List[Dict[str, str]]:
    """
    将连续文本按章节标题切分。
    查找类似「【药物相互作用】」「7. 药物相互作用」「禁忌症：」这样的标题行。
    """
    # 匹配各种章节标题格式
    heading_pattern = re.compile(
        r"(?:^|\n)\s*"
        r"(?:【([^】]+)】"              # 【标题】
        r"|(\d+[\.\、]\s*[^\n]{2,20})"  # 7. 标题 或 7、标题
        r"|([^\n]{2,15})[：:]\s*$"      # 标题：
        r")",
        re.MULTILINE,
    )

    matches = list(heading_pattern.finditer(full_text))
    if not matches:
        # 无法识别标题，整段作为一个 section
        section_name = classify_section(full_text[:200])
        if section_name:
            return [{"title": section_name, "content": _clean_text(full_text)}]
        return []

    sections = []
    for i, match in enumerate(matches):
        title_raw = match.group(1) or match.group(2) or match.group(3)
        title_raw = re.sub(r"^\d+[\.\、]\s*", "", title_raw).strip()

        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        content = full_text[start:end].strip()

        if not content or len(content) < 10:
            continue

        section_name = classify_section(title_raw)
        if section_name:
            sections.append({
                "title": section_name,
                "content": _clean_text(content),
            })

    return sections


def _clean_text(text: str) -> str:
    """清理 PDF 提取文本中的噪音"""
    # 去除页码行
    text = re.sub(r"\n\s*-?\s*\d+\s*-?\s*\n", "\n", text)
    # 合并被换行打断的句子
    text = re.sub(r"(?<=[，、；。])\n(?=[^\n])", "", text)
    # 合并多余空白
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_drug_name_from_filename(filename: str) -> Optional[str]:
    """从文件名中提取药物名称"""
    name = Path(filename).stem
    # 去除常见后缀
    name = re.sub(r"(说明书|指南|共识|手册|_|-).*$", "", name)
    name = re.sub(r"\s+", "", name)
    if len(name) >= 2:
        return name
    return None


def pdf_to_knowledge_record(pdf_path: Path) -> Optional[Dict[str, Any]]:
    """
    将单个 PDF 文件转换为 drug_knowledge_zh.json 格式的记录。
    """
    print(f"  处理: {pdf_path.name}")

    try:
        pages = extract_text_from_pdf(pdf_path)
    except Exception as e:
        print(f"    读取失败: {e}")
        return None

    if not pages:
        print("    无文本内容，跳过")
        return None

    full_text = "\n\n".join(p["text"] for p in pages)
    sections = split_into_sections(full_text)

    if not sections:
        print("    未识别到有效章节，跳过")
        return None

    drug_name = extract_drug_name_from_filename(pdf_path.name)
    if not drug_name:
        print("    无法从文件名提取药物名称，跳过")
        return None

    # 截断过长内容
    for sec in sections:
        if len(sec["content"]) > 3000:
            sec["content"] = sec["content"][:3000] + "……（内容截断）"

    record = {
        "drug": drug_name,
        "aliases": [drug_name],
        "source": f"临床指南/说明书 PDF: {pdf_path.name}",
        "sections": sections,
        "interactions": [],  # PDF 中的交互关系需要进一步 NLP 提取
    }

    print(f"    提取 {len(sections)} 个章节, 药物: {drug_name}")
    return record


def merge_into_knowledge(existing: List[Dict], new_records: List[Dict]) -> List[Dict]:
    """合并新提取的记录到现有知识库"""
    by_drug: Dict[str, Dict] = {}
    for rec in existing:
        by_drug[rec["drug"]] = rec

    for rec in new_records:
        key = rec["drug"]
        if key in by_drug:
            old = by_drug[key]
            # 合并 sections
            old_sections = {s["title"]: s for s in old.get("sections", [])}
            for sec in rec.get("sections", []):
                if sec["title"] not in old_sections:
                    old_sections[sec["title"]] = sec
                else:
                    # 如果新内容更长，替换
                    if len(sec["content"]) > len(old_sections[sec["title"]]["content"]):
                        old_sections[sec["title"]] = sec
            old["sections"] = list(old_sections.values())
            # 合并 aliases
            all_aliases = list(dict.fromkeys(old.get("aliases", []) + rec.get("aliases", [])))
            old["aliases"] = all_aliases
            # 更新 source
            if rec["source"] not in old.get("source", ""):
                old["source"] = old["source"] + " + " + rec["source"]
        else:
            by_drug[key] = rec

    return list(by_drug.values())


def main():
    parser = argparse.ArgumentParser(description="从临床指南 PDF 中提取药物知识")
    parser.add_argument("--dir", type=str, default=str(GUIDELINES_DIR), help="PDF 文件目录")
    parser.add_argument("--dry-run", action="store_true", help="仅提取不写入")
    args = parser.parse_args()

    pdf_dir = Path(args.dir)
    if not pdf_dir.exists():
        pdf_dir.mkdir(parents=True, exist_ok=True)
        print(f"已创建指南目录: {pdf_dir}")
        print("请将 PDF 文件放入该目录后重新运行。")
        print()
        print("支持的文件命名方式:")
        print("  - 华法林说明书.pdf")
        print("  - 阿司匹林-临床用药指南.pdf")
        print("  - 抗凝药物相互作用指南.pdf")
        return

    pdf_files = list(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"目录 {pdf_dir} 中没有 PDF 文件。")
        print("请将临床指南或药品说明书 PDF 放入该目录。")
        return

    print(f"找到 {len(pdf_files)} 个 PDF 文件")
    print()

    new_records = []
    for pdf_path in sorted(pdf_files):
        record = pdf_to_knowledge_record(pdf_path)
        if record:
            new_records.append(record)

    if not new_records:
        print("\n未能从 PDF 中提取有效记录。")
        return

    print(f"\n成功提取 {len(new_records)} 条药物记录")

    if args.dry_run:
        print("\n[dry-run] 不写入文件")
        for rec in new_records:
            print(f"  {rec['drug']}: {len(rec['sections'])} 个章节")
        return

    # 加载现有知识库并合并
    existing = []
    if KNOWLEDGE_PATH.exists():
        existing = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
        print(f"已加载现有知识库: {len(existing)} 条记录")

    merged = merge_into_knowledge(existing, new_records)
    KNOWLEDGE_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已合并写入: {KNOWLEDGE_PATH} ({len(merged)} 条记录)")


if __name__ == "__main__":
    main()
