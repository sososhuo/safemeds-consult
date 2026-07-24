"""
配置模块：集中读取环境变量和路径，供 RAG、LLM、数据库与服务启动使用。
"""

import os
from pathlib import Path


def _load_root_env() -> None:
    """Load project-root .env without adding a runtime dependency."""
    root = Path(__file__).resolve().parents[3]
    env_path = root / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


_load_root_env()

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if not raw:
        return default
    path = Path(raw)
    if path.is_absolute():
        return path

    candidates = [PROJECT_ROOT / path, BACKEND_ROOT / path]
    if path.parts and path.parts[0] == "backend":
        candidates.insert(0, BACKEND_ROOT.joinpath(*path.parts[1:]))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


DATA_PATH = _path_from_env("SAFEMEDS_DATA_PATH", BACKEND_ROOT / "data" / "processed" / "drug_knowledge_zh.json")
DRUG_RESOLUTION_INDEX_PATH = _path_from_env(
    "DRUG_RESOLUTION_INDEX_PATH",
    BACKEND_ROOT / "data" / "processed" / "drug_resolution_index.json",
)
DRUG_ALIAS_OVERRIDES_PATH = _path_from_env(
    "DRUG_ALIAS_OVERRIDES_PATH",
    BACKEND_ROOT / "data" / "raw" / "drug_alias_overrides.json",
)
STORAGE_DIR = _path_from_env("SAFEMEDS_STORAGE_DIR", BACKEND_ROOT / "storage")
DATABASE_PATH = _path_from_env("SAFEMEDS_SQLITE_PATH", STORAGE_DIR / "safemeds_history.sqlite3")

ALLOWED_ORIGINS = _split_csv(
    os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
)

# LLM API configuration. The current runtime is offline unless the feature
# switches below are enabled in .env and the integration code is wired in.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai-compatible")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4.1-mini")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
LLM_ENABLE_EXTRACTION = os.getenv("LLM_ENABLE_EXTRACTION", "false").lower() == "true"
LLM_ENABLE_RESPONSE_GENERATION = os.getenv("LLM_ENABLE_RESPONSE_GENERATION", "false").lower() == "true"

# Retrieval backend configuration.
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "chroma")
CHROMA_PERSIST_DIR = _path_from_env("CHROMA_PERSIST_DIR", STORAGE_DIR / "chroma")
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "sentence_transformers")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "lastmass/Qwen3-Embedding-Medical-0.6B")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))
EMBEDDING_NORMALIZE = os.getenv("EMBEDDING_NORMALIZE", "true").lower() == "true"

# Neo4j knowledge graph configuration. SafeMeds treats Neo4j as the formal
# KG backend for medication interaction and special-scenario risk relations.
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "safemeds-password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
