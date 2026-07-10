from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


SECTION_KEYWORDS: list[tuple[str, list[str]]] = [
    ("药物相互作用", ["药物相互作用", "相互作用", "drug interaction", "合用", "联合用药", "配伍"]),
    ("禁忌", ["禁忌", "contraindication", "禁忌症", "禁忌证"]),
    ("警告与注意事项", ["警告", "注意事项", "warning", "precaution", "慎用"]),
    ("不良反应", ["不良反应", "副作用", "adverse", "side effect"]),
    ("用法用量", ["用法用量", "用法", "用量", "dosage", "剂量"]),
    ("特殊人群", ["特殊人群", "老年", "儿童", "妊娠", "哺乳", "肝功能", "肾功能"]),
]


@dataclass
class SourceDocument:
    source_id: str
    source_path: str
    source_type: str
    title: str
    text: str
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentChunk:
    chunk_id: str
    source_id: str
    source_path: str
    source_type: str
    title: str
    section: str
    text: str
    drug: str
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "source_path": self.source_path,
            "source_type": self.source_type,
            "title": self.title,
            "section": self.section,
            "text": self.text,
            "drug": self.drug,
            "page": self.page,
            "metadata": self.metadata,
        }


@dataclass
class IngestionReport:
    source_count: int = 0
    chunk_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    failures: list[dict[str, str]] = field(default_factory=list)
    output_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": self.source_count,
            "chunk_count": self.chunk_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "by_type": self.by_type,
            "failures": self.failures,
            "output_path": self.output_path,
        }


class DocumentIngestionService:
    supported_suffixes = {".pdf", ".json", ".csv", ".txt"}

    def ingest_path(self, input_path: Path) -> tuple[list[DocumentChunk], IngestionReport]:
        files = self._collect_files(input_path)
        report = IngestionReport(source_count=len(files))
        chunks: list[DocumentChunk] = []

        for file_path in files:
            suffix = file_path.suffix.lower()
            if suffix not in self.supported_suffixes:
                report.skipped_count += 1
                continue
            try:
                docs = list(self._load_file(file_path))
                report.by_type[suffix.lstrip(".")] = report.by_type.get(suffix.lstrip("."), 0) + 1
                for doc in docs:
                    chunks.extend(self._chunk_document(doc))
            except Exception as exc:
                report.failed_count += 1
                report.failures.append({"path": str(file_path), "error": str(exc)})

        report.chunk_count = len(chunks)
        return chunks, report

    def export_chunks(self, chunks: list[DocumentChunk], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [chunk.to_dict() for chunk in chunks]
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def export_knowledge_records(self, chunks: list[DocumentChunk], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        records: dict[str, dict[str, Any]] = {}
        for chunk in chunks:
            drug = chunk.drug or self._drug_from_title(chunk.title)
            if not drug:
                continue
            record = records.setdefault(
                drug,
                {
                    "drug": drug,
                    "aliases": [drug],
                    "source": chunk.source_path,
                    "sections": [],
                    "interactions": [],
                },
            )
            if chunk.source_path not in record["source"]:
                record["source"] = f"{record['source']} + {chunk.source_path}"
            record["sections"].append({"title": chunk.section, "content": chunk.text})
        output_path.write_text(
            json.dumps(list(records.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _collect_files(self, input_path: Path) -> list[Path]:
        if input_path.is_file():
            return [input_path]
        if not input_path.exists():
            raise FileNotFoundError(f"输入路径不存在: {input_path}")
        return sorted(path for path in input_path.rglob("*") if path.is_file())

    def _load_file(self, file_path: Path) -> Iterable[SourceDocument]:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            yield from self._load_pdf(file_path)
        elif suffix == ".json":
            yield from self._load_json(file_path)
        elif suffix == ".csv":
            yield from self._load_csv(file_path)
        elif suffix == ".txt":
            yield self._load_txt(file_path)
        else:
            return

    def _load_pdf(self, file_path: Path) -> Iterable[SourceDocument]:
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("读取 PDF 需要安装 pymupdf") from exc

        doc = fitz.open(str(file_path))
        try:
            for index, page in enumerate(doc, start=1):
                text = clean_text(page.get_text("text"))
                if not text:
                    continue
                yield SourceDocument(
                    source_id=f"{file_path.name}::page::{index}",
                    source_path=str(file_path),
                    source_type="pdf",
                    title=file_path.stem,
                    text=text,
                    page=index,
                    metadata={"filename": file_path.name},
                )
        finally:
            doc.close()

    def _load_json(self, file_path: Path) -> Iterable[SourceDocument]:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        items = payload if isinstance(payload, list) else [payload]
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("drug") or file_path.stem)
            sections = item.get("sections")
            if isinstance(sections, list):
                for section_index, section in enumerate(sections):
                    if not isinstance(section, dict):
                        continue
                    text = clean_text(str(section.get("content", "")))
                    if not text:
                        continue
                    yield SourceDocument(
                        source_id=f"{file_path.name}::json::{index}::{section_index}",
                        source_path=str(file_path),
                        source_type="json",
                        title=title,
                        text=text,
                        metadata={
                            "drug": item.get("drug", ""),
                            "section": section.get("title", ""),
                            "aliases": item.get("aliases", []),
                        },
                    )
            else:
                text = clean_text(str(item.get("text") or item.get("content") or ""))
                if text:
                    yield SourceDocument(
                        source_id=f"{file_path.name}::json::{index}",
                        source_path=str(file_path),
                        source_type="json",
                        title=title,
                        text=text,
                        metadata={"drug": item.get("drug", "")},
                    )

    def _load_csv(self, file_path: Path) -> Iterable[SourceDocument]:
        with file_path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            for index, row in enumerate(reader):
                title = row.get("title") or row.get("drug") or file_path.stem
                text = clean_text(row.get("text") or row.get("content") or row.get("section_content") or "")
                if not text:
                    continue
                yield SourceDocument(
                    source_id=f"{file_path.name}::csv::{index}",
                    source_path=str(file_path),
                    source_type="csv",
                    title=title,
                    text=text,
                    metadata={
                        "drug": row.get("drug", ""),
                        "section": row.get("section") or row.get("section_title") or "",
                    },
                )

    def _load_txt(self, file_path: Path) -> SourceDocument:
        return SourceDocument(
            source_id=f"{file_path.name}::txt::0",
            source_path=str(file_path),
            source_type="txt",
            title=file_path.stem,
            text=clean_text(file_path.read_text(encoding="utf-8")),
            metadata={},
        )

    def _chunk_document(self, doc: SourceDocument) -> list[DocumentChunk]:
        section = doc.metadata.get("section") or classify_section(doc.text) or "正文"
        drug = doc.metadata.get("drug") or self._drug_from_title(doc.title)
        chunks = list(split_text(doc.text))
        result = []
        for index, text in enumerate(chunks):
            result.append(
                DocumentChunk(
                    chunk_id=f"{doc.source_id}::chunk::{index}",
                    source_id=doc.source_id,
                    source_path=doc.source_path,
                    source_type=doc.source_type,
                    title=doc.title,
                    section=section,
                    text=text,
                    drug=drug,
                    page=doc.page,
                    metadata=doc.metadata,
                )
            )
        return result

    def _drug_from_title(self, title: str) -> str:
        name = re.sub(r"(说明书|指南|共识|手册|临床|用药|_|-).*$", "", title).strip()
        return name if len(name) >= 2 else title.strip()


def classify_section(text: str) -> str | None:
    text_lower = text.lower()
    for section_name, keywords in SECTION_KEYWORDS:
        if any(keyword.lower() in text_lower for keyword in keywords):
            return section_name
    return None


def clean_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n\s*-?\s*\d+\s*-?\s*\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text: str, size: int = 700, overlap: int = 100) -> Iterable[str]:
    text = clean_text(text)
    if not text:
        return
    if len(text) <= size:
        yield text
        return
    start = 0
    step = max(size - overlap, 1)
    while start < len(text):
        chunk = text[start : start + size].strip()
        if chunk:
            yield chunk
        start += step
