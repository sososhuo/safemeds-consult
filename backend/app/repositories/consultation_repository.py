from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import DATABASE_PATH
from app.schemas.analysis import Evidence, ExtractedContext, RiskLevel
from app.schemas.consultation import (
    ConsultationResponse,
    KnowledgeRelation,
    MemoryUpdate,
    SafetyFlag,
    SessionDetail,
    SessionSnapshot,
    SessionSummary,
)


@dataclass
class StoredSession:
    id: int
    user_id: str
    title: str
    snapshot: SessionSnapshot


class ConsultationRepository:
    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consultation_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL DEFAULT 'Unknown',
                    conclusion TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consultation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES consultation_sessions(id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_consult_sessions_updated ON consultation_sessions(updated_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_consult_messages_session ON consultation_messages(session_id, created_at)")

    def get_or_create_session(self, user_id: str, session_id: Optional[int], title: str) -> StoredSession:
        if session_id is not None:
            existing = self._get_session(session_id, user_id)
            if existing is not None:
                return existing

        now = datetime.now(timezone.utc).isoformat()
        snapshot = SessionSnapshot()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO consultation_sessions (user_id, title, snapshot_json, risk_level, conclusion, created_at, updated_at)
                VALUES (?, ?, ?, 'Unknown', '', ?, ?)
                """,
                (user_id, title or "新的用药咨询", snapshot.model_dump_json(), now, now),
            )
            new_id = int(cursor.lastrowid)
        return StoredSession(id=new_id, user_id=user_id, title=title or "新的用药咨询", snapshot=snapshot)

    def _get_session(self, session_id: int, user_id: str | None = None) -> StoredSession | None:
        where = "WHERE id = ?"
        params: tuple = (session_id,)
        if user_id is not None:
            where += " AND user_id = ?"
            params = (session_id, user_id)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT id, user_id, title, snapshot_json FROM consultation_sessions {where}",
                params,
            ).fetchone()
        if row is None:
            return None
        return StoredSession(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            snapshot=SessionSnapshot.model_validate(json.loads(row["snapshot_json"])),
        )

    def save_message(
        self,
        session_id: int,
        user_id: str,
        message: str,
        answer: str,
        conclusion: str,
        risk_level: RiskLevel,
        mechanism: str,
        recommendation: str,
        confidence: float,
        extracted: ExtractedContext,
        snapshot: SessionSnapshot,
        kg_relations: list[KnowledgeRelation],
        evidence: list[Evidence],
        safety_flags: list[SafetyFlag],
        memory_updates: list[MemoryUpdate],
        safety_notice: str,
        workflow_trace: list[dict] | None = None,
    ) -> ConsultationResponse:
        now = datetime.now(timezone.utc).isoformat()
        pending = ConsultationResponse(
            id=0,
            session_id=session_id,
            user_id=user_id,
            message=message,
            answer=answer,
            conclusion=conclusion,
            risk_level=risk_level,
            mechanism=mechanism,
            recommendation=recommendation,
            confidence=confidence,
            extracted_context=extracted,
            session_snapshot=snapshot,
            kg_relations=kg_relations,
            evidence=evidence,
            safety_flags=safety_flags,
            memory_updates=memory_updates,
            workflow_trace=workflow_trace or [],
            safety_notice=safety_notice,
            created_at=datetime.fromisoformat(now),
        )
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO consultation_messages (session_id, user_id, message, response_json, risk_level, conclusion, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, user_id, message, pending.model_dump_json(), risk_level, conclusion, now),
            )
            message_id = int(cursor.lastrowid)
            conn.execute(
                """
                UPDATE consultation_sessions
                SET snapshot_json = ?, risk_level = ?, conclusion = ?, updated_at = ?
                WHERE id = ?
                """,
                (snapshot.model_dump_json(), risk_level, conclusion, now, session_id),
            )

        return pending.model_copy(update={"id": message_id})

    def list_sessions(self, user_id: str, limit: int = 30) -> list[SessionSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, title, risk_level, conclusion, updated_at
                FROM consultation_sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [
            SessionSummary(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                risk_level=row["risk_level"],
                conclusion=row["conclusion"] or "新的用药咨询",
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def get_session_detail(self, session_id: int, user_id: str) -> SessionDetail | None:
        with self._connect() as conn:
            session = conn.execute(
                """
                SELECT id, user_id, title, snapshot_json, risk_level, conclusion, updated_at
                FROM consultation_sessions
                WHERE id = ? AND user_id = ?
                """,
                (session_id, user_id),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT id, response_json
                FROM consultation_messages
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
        if session is None:
            return None
        messages = []
        for row in rows:
            payload = json.loads(row["response_json"])
            payload["id"] = row["id"]
            messages.append(ConsultationResponse.model_validate(payload))
        return SessionDetail(
            id=session["id"],
            user_id=session["user_id"],
            title=session["title"],
            risk_level=session["risk_level"],
            conclusion=session["conclusion"] or "新的用药咨询",
            updated_at=datetime.fromisoformat(session["updated_at"]),
            snapshot=SessionSnapshot.model_validate(json.loads(session["snapshot_json"])),
            messages=messages,
        )

    def delete_session(self, session_id: int, user_id: str) -> bool:
        with self._connect() as conn:
            session = conn.execute(
                "SELECT id FROM consultation_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            if session is None:
                return False
            conn.execute("DELETE FROM consultation_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM consultation_sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
        return True
