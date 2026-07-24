"""
历史记录仓储模块：用 SQLite 保存和查询用户咨询历史。
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.core.config import DATABASE_PATH
from app.schemas.analysis import AnalysisReport, HistoryDetail, HistoryItem


class HistoryRepository:
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
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_created_at ON analysis_history(created_at DESC)")

    def create(self, question: str, report: AnalysisReport) -> HistoryDetail:
        created_at = datetime.now(timezone.utc).isoformat()
        payload = report.model_dump_json()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO analysis_history (question, risk_level, conclusion, report_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (question, report.risk_level, report.conclusion, payload, created_at),
            )
            history_id = int(cursor.lastrowid)
        return HistoryDetail(
            id=history_id,
            question=question,
            risk_level=report.risk_level,
            conclusion=report.conclusion,
            report=report,
            created_at=datetime.fromisoformat(created_at),
        )

    def list(self, limit: int = 30) -> List[HistoryItem]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, question, risk_level, conclusion, created_at
                FROM analysis_history
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            HistoryItem(
                id=row["id"],
                question=row["question"],
                risk_level=row["risk_level"],
                conclusion=row["conclusion"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def get(self, history_id: int) -> Optional[HistoryDetail]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, question, risk_level, conclusion, report_json, created_at
                FROM analysis_history
                WHERE id = ?
                """,
                (history_id,),
            ).fetchone()
        if row is None:
            return None
        report = AnalysisReport.model_validate(json.loads(row["report_json"]))
        return HistoryDetail(
            id=row["id"],
            question=row["question"],
            risk_level=row["risk_level"],
            conclusion=row["conclusion"],
            report=report,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def delete(self, history_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM analysis_history WHERE id = ?", (history_id,))
            return cursor.rowcount > 0
