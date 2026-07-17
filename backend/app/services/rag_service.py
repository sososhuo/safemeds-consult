import hashlib
import logging
import math
import os
import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Tuple

from app.core.config import (
    CHROMA_PERSIST_DIR,
    EMBEDDING_BACKEND,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DEVICE,
    EMBEDDING_MODEL_NAME,
    EMBEDDING_NORMALIZE,
)
from app.schemas.analysis import Evidence


IMPORTANT_SECTIONS = {"药物相互作用", "禁忌", "警告与注意事项", "特殊人群", "儿童用药", "老年用药", "孕妇及哺乳期妇女用药"}
HIGH_RISK_TERMS = {
    "禁忌",
    "避免",
    "不得",
    "严重",
    "出血",
    "低血压",
    "横纹肌溶解",
    "乳酸酸中毒",
}


def tokenize(text: str) -> List[str]:
    text = text.lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]+|[\u4e00-\u9fff]{2,}", text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    return words + chinese_chars


def build_documents(records: List[Dict]) -> list[Dict]:
    documents: list[Dict] = []
    chunker = SimpleRagIndex([])
    for record in records:
        documents.extend(_build_record_documents(record, chunker))
    return documents


def _build_record_documents(record: Dict, chunker: "SimpleRagIndex") -> list[Dict]:
    documents: list[Dict] = []
    for section_index, section in enumerate(record.get("sections", [])):
        title = section.get("title", "")
        structured_chunks = section.get("chunks") or []
        if structured_chunks:
            for idx, chunk in enumerate(structured_chunks):
                text = re.sub(r"\s+", " ", str(chunk.get("text", ""))).strip()
                if not text:
                    continue
                documents.append(
                    {
                        "source": record.get("source", ""),
                        "drug": record.get("drug", ""),
                        "section": title,
                        "text": text,
                        "chunk_id": f"{record.get('drug', '')}::{section_index}::{title}::structured::{idx}",
                        "chunk_type": chunk.get("chunk_type", "section"),
                        "population_tags": chunk.get("population_tags", []),
                        "condition_tags": chunk.get("condition_tags", []),
                        "risk_terms": chunk.get("risk_terms", []),
                    }
                )
            continue

        for idx, chunk in enumerate(chunker._chunk(section.get("content", ""))):
            documents.append(
                {
                    "source": record.get("source", ""),
                    "drug": record.get("drug", ""),
                    "section": title,
                    "text": chunk,
                    "chunk_id": f"{record.get('drug', '')}::{section_index}::{title}::window::{idx}",
                    "chunk_type": "window",
                    "population_tags": [],
                    "condition_tags": [],
                    "risk_terms": [],
                }
            )
    return documents


class SimpleRagIndex:
    def __init__(self, records: List[Dict]):
        self.documents: List[Dict] = []
        for record in records:
            self.documents.extend(_build_record_documents(record, self))

        self.doc_tokens = [tokenize(doc["text"]) for doc in self.documents]
        self.doc_tf = [Counter(tokens) for tokens in self.doc_tokens]
        self.idf = self._build_idf(self.doc_tokens)
        self.doc_vectors = [self._tfidf(tf) for tf in self.doc_tf]
        self.doc_norms = [self._norm(vec) for vec in self.doc_vectors]

    def _chunk(self, text: str, size: int = 160, overlap: int = 35) -> Iterable[str]:
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= size:
            yield text
            return
        start = 0
        while start < len(text):
            yield text[start : start + size]
            start += size - overlap

    def _build_idf(self, docs: List[List[str]]) -> Dict[str, float]:
        df = defaultdict(int)
        for tokens in docs:
            for token in set(tokens):
                df[token] += 1
        total = len(docs) or 1
        return {token: math.log((total + 1) / (count + 1)) + 1 for token, count in df.items()}

    def _tfidf(self, tf: Counter) -> Dict[str, float]:
        return {token: count * self.idf.get(token, 1.0) for token, count in tf.items()}

    def _norm(self, vec: Dict[str, float]) -> float:
        return math.sqrt(sum(value * value for value in vec.values())) or 1.0

    def _cosine(self, left: Dict[str, float], right: Dict[str, float], right_norm: float) -> float:
        score = sum(value * right.get(token, 0.0) for token, value in left.items())
        return score / ((self._norm(left) * right_norm) or 1.0)

    def retrieve(self, query: str, drugs: List[str], top_k: int = 8) -> List[Evidence]:
        query_tokens = tokenize(query)
        if not query_tokens and not drugs:
            return []
        query_vec = self._tfidf(Counter(query_tokens))
        drug_set = set(drugs)
        scored: List[Tuple[float, Dict]] = []
        for doc, doc_vec, doc_norm in zip(self.documents, self.doc_vectors, self.doc_norms):
            base = self._cosine(query_vec, doc_vec, doc_norm)
            section_boost = 0.2 if doc["section"] in IMPORTANT_SECTIONS else 0.0
            drug_boost = 0.25 if doc["drug"] in drug_set else 0.0
            structured_boost = 0.08 if doc.get("chunk_type") in {"section", "clause", "section_part"} else 0.0
            score = base + section_boost + drug_boost + structured_boost
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            Evidence(
                source=doc["source"],
                drug=doc["drug"],
                section=doc["section"],
                snippet=doc["text"],
                score=round(score, 4),
            )
            for score, doc in scored[:top_k]
        ]


class LocalHashEmbeddingFunction:
    """Small deterministic embedding function for local Chroma retrieval.

    This keeps the vector store fully offline. It is intentionally simple and can
    later be replaced with a medical embedding model without changing callers.
    """

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def name(self) -> str:
        return "safemeds_local_hash"

    def __call__(self, input):  # Chroma expects the parameter name to be `input`.
        return [self._embed(text) for text in input]

    def embed_query(self, input):
        return self(input)

    def embed_documents(self, input):
        return self(input)

    def _embed(self, text: str) -> list[float]:
        tokens = tokenize(text)
        vector = [0.0] * self.dimensions
        for token in tokens:
            idx = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.dimensions
            vector[idx] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class SentenceTransformerEmbeddingFunction:
    """Chroma embedding function backed by a real local embedding model."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL_NAME,
        device: str = EMBEDDING_DEVICE,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        normalize_embeddings: bool = EMBEDDING_NORMALIZE,
    ):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        self._model = None

    def name(self) -> str:
        safe_model_name = re.sub(r"[^a-zA-Z0-9_]+", "_", self.model_name).strip("_")
        return f"safemeds_sentence_transformers_{safe_model_name}"

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "EMBEDDING_BACKEND=sentence_transformers requires sentence-transformers. "
                    "Install backend requirements first."
                ) from exc
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def __call__(self, input):  # Chroma expects the parameter name to be `input`.
        return self._encode(input)

    def embed_query(self, input):
        return self._encode(input)

    def embed_documents(self, input):
        return self._encode(input)

    def _encode(self, input):
        model = self._load_model()
        vectors = model.encode(
            list(input),
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
        )
        return vectors.tolist()


class ChromaRagIndex:
    """Local Chroma vector index for medication evidence retrieval."""

    collection_prefix = "safemeds_drug_knowledge"

    def __init__(self, records: List[Dict]):
        try:
            os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
            logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
            import chromadb
            from chromadb.config import Settings
        except ImportError as exc:
            raise RuntimeError(
                "VECTOR_BACKEND=chroma requires chromadb. Install backend requirements first."
            ) from exc

        self.documents = self._build_documents(records)
        self.embedding_function = self._build_embedding_function()
        self.collection_name = self._collection_name()
        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(CHROMA_PERSIST_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        metadata = {
            "hnsw:space": "cosine",
            "embedding_backend": EMBEDDING_BACKEND,
            "embedding_model": EMBEDDING_MODEL_NAME,
        }
        try:
            return self.client.get_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
            )
        except Exception:
            try:
                return self.client.create_collection(
                    name=self.collection_name,
                    embedding_function=self.embedding_function,
                    metadata=metadata,
                )
            except Exception:
                return self.client.get_collection(
                    name=self.collection_name,
                    embedding_function=self.embedding_function,
                )

    def _build_embedding_function(self):
        if EMBEDDING_BACKEND == "sentence_transformers":
            return SentenceTransformerEmbeddingFunction()
        return LocalHashEmbeddingFunction()

    def _collection_name(self) -> str:
        model_part = re.sub(r"[^a-zA-Z0-9_]+", "_", EMBEDDING_MODEL_NAME.lower()).strip("_")
        backend_part = re.sub(r"[^a-zA-Z0-9_]+", "_", EMBEDDING_BACKEND.lower()).strip("_")
        name = f"{self.collection_prefix}_{backend_part}_{model_part}"[:63].strip("_")
        return name if len(name) >= 3 else "safemeds_embeddings"

    def _build_documents(self, records: List[Dict]) -> list[Dict]:
        return build_documents(records)

    def _populate(self) -> None:
        if not self.documents:
            return
        batch_size = 5000
        for start in range(0, len(self.documents), batch_size):
            batch = self.documents[start : start + batch_size]
            self.collection.add(
                ids=[doc["chunk_id"] for doc in batch],
                documents=[doc["text"] for doc in batch],
                metadatas=[
                    {
                        "source": doc["source"],
                        "drug": doc["drug"],
                        "section": doc["section"],
                    }
                    for doc in batch
                ],
            )

    def _ensure_populated(self) -> None:
        if self.collection.count() != len(self.documents):
            existing = self.collection.get(include=[])
            ids = existing.get("ids", [])
            if ids:
                self.collection.delete(ids=ids)
            self._populate()

    def retrieve(self, query: str, drugs: List[str], top_k: int = 8) -> List[Evidence]:
        query_tokens = tokenize(query)
        if not query_tokens and not drugs:
            return []

        self._ensure_populated()
        result = self.collection.query(
            query_texts=[query],
            n_results=min(max(top_k * 3, top_k), max(len(self.documents), 1)),
            include=["documents", "metadatas", "distances"],
        )
        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        drug_set = set(drugs)
        scored: list[tuple[float, Evidence]] = []
        for text, metadata, distance in zip(docs, metadatas, distances):
            base = 1.0 / (1.0 + float(distance or 0.0))
            section_boost = 0.12 if metadata.get("section") in IMPORTANT_SECTIONS else 0.0
            drug_boost = 0.18 if metadata.get("drug") in drug_set else 0.0
            score = round(base + section_boost + drug_boost, 4)
            scored.append(
                (
                    score,
                    Evidence(
                        source=metadata.get("source", ""),
                        drug=metadata.get("drug", ""),
                        section=metadata.get("section", ""),
                        snippet=text,
                        score=score,
                    ),
                )
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[:top_k]]


class BM25RagIndex:
    """Keyword retrieval for exact medication and risk-term matching."""

    def __init__(self, records: List[Dict], documents: list[Dict] | None = None):
        self.documents = documents if documents is not None else build_documents(records)
        self.doc_tokens = [tokenize(self._doc_text(doc)) for doc in self.documents]
        self.doc_tf = [Counter(tokens) for tokens in self.doc_tokens]
        self.doc_len = [len(tokens) or 1 for tokens in self.doc_tokens]
        self.avg_doc_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 1.0
        self.idf = self._build_idf(self.doc_tokens)

    def _doc_text(self, doc: Dict) -> str:
        return f"{doc['drug']} {doc['section']} {doc['text']}"

    def _build_idf(self, docs: List[List[str]]) -> Dict[str, float]:
        df = defaultdict(int)
        for tokens in docs:
            for token in set(tokens):
                df[token] += 1
        total = len(docs) or 1
        return {
            token: math.log(1 + (total - count + 0.5) / (count + 0.5))
            for token, count in df.items()
        }

    def retrieve(self, query: str, drugs: List[str], top_k: int = 8) -> List[Evidence]:
        query_tokens = tokenize(" ".join([query, *drugs]))
        if not query_tokens and not drugs:
            return []

        k1 = 1.5
        b = 0.75
        drug_set = set(drugs)
        scored: list[tuple[float, Dict]] = []
        for doc, tf, length in zip(self.documents, self.doc_tf, self.doc_len):
            score = 0.0
            for token in query_tokens:
                freq = tf.get(token, 0)
                if freq <= 0:
                    continue
                denom = freq + k1 * (1 - b + b * length / self.avg_doc_len)
                score += self.idf.get(token, 0.0) * ((freq * (k1 + 1)) / denom)
            if doc["section"] in IMPORTANT_SECTIONS:
                score += 0.35
            if doc["drug"] in drug_set:
                score += 0.45
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            Evidence(
                source=doc["source"],
                drug=doc["drug"],
                section=doc["section"],
                snippet=doc["text"],
                score=round(score, 4),
            )
            for score, doc in scored[:top_k]
        ]


class HybridRagIndex:
    """BM25 + dense retrieval with RRF fusion and medical reranking."""

    def __init__(self, records: List[Dict], dense_index=None):
        self.documents = build_documents(records)
        self.bm25 = BM25RagIndex(records, documents=self.documents)
        self.dense = dense_index if dense_index is not None else ChromaRagIndex(records)

    def retrieve(self, query: str, drugs: List[str], top_k: int = 8) -> List[Evidence]:
        if not tokenize(query) and not drugs:
            return []

        candidate_k = max(top_k * 4, 16)
        bm25_results = self.bm25.retrieve(query, drugs, top_k=candidate_k)
        dense_results = self.dense.retrieve(query, drugs, top_k=candidate_k)
        fused = self._rrf_fuse(
            {"bm25": bm25_results, "dense": dense_results},
            drugs=drugs,
        )
        reranked = self._rerank(fused, drugs)
        return reranked[:top_k]

    def _key(self, evidence: Evidence) -> tuple[str, str, str, str]:
        return (evidence.source, evidence.drug, evidence.section, evidence.snippet)

    def _rrf_fuse(self, ranked_lists: dict[str, list[Evidence]], drugs: list[str]) -> list[Evidence]:
        k = 60
        by_key: dict[tuple[str, str, str, str], Evidence] = {}
        scores: dict[tuple[str, str, str, str], float] = defaultdict(float)
        source_hits: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)

        for source_name, results in ranked_lists.items():
            for rank, evidence in enumerate(results, start=1):
                key = self._key(evidence)
                by_key[key] = evidence
                scores[key] += 1.0 / (k + rank)
                source_hits[key].add(source_name)

        drug_set = set(drugs)
        fused: list[Evidence] = []
        for key, evidence in by_key.items():
            score = scores[key]
            if len(source_hits[key]) > 1:
                score += 0.02
            if evidence.drug in drug_set:
                score += 0.03
            fused.append(evidence.model_copy(update={"score": round(score, 4)}))

        fused.sort(key=lambda item: item.score, reverse=True)
        return fused

    def _rerank(self, evidence: list[Evidence], drugs: list[str]) -> list[Evidence]:
        drug_set = set(drugs)

        def score(item: Evidence) -> float:
            value = item.score
            if item.section in IMPORTANT_SECTIONS:
                value += 0.08
            if item.drug in drug_set:
                value += 0.08
            if any(term in item.snippet for term in HIGH_RISK_TERMS):
                value += 0.05
            return value

        reranked = [
            item.model_copy(update={"score": round(score(item), 4)})
            for item in evidence
        ]
        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked
