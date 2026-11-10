"""数据库迁移与完整性检查。

V6 只做增量迁移：
1. 迁移前在线备份（`data/catalog/backups/`）；
2. `PRAGMA integrity_check` 必须为 ok；
3. 迁移后再检查一次完整性、外键与关键计数；
4. 计数与迁移前不一致就中止，不删除旧库。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts import db

from kato_engine.config.settings import Settings, load_settings
from kato_engine.observability.logging import get_logger

_LOGGER = get_logger("kato.storage")


@dataclass
class SchemaReport:
    db_path: Path
    from_version: int
    to_version: int
    applied: tuple[int, ...]
    backup_path: Path | None
    integrity_ok: bool
    foreign_key_violations: int
    counts_before: dict[str, int] = field(default_factory=dict)
    counts_after: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "from_version": self.from_version,
            "to_version": self.to_version,
            "applied": list(self.applied),
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "integrity_ok": self.integrity_ok,
            "foreign_key_violations": self.foreign_key_violations,
            "counts_before": self.counts_before,
            "counts_after": self.counts_after,
        }


_PRESERVE_TABLES = (
    "research_items",
    "research_comments",
    "research_campaigns",
    "research_batches",
    "research_artifacts",
    "research_search_queries",
)


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    result: dict[str, int] = {}
    for table in _PRESERVE_TABLES:
        try:
            result[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.OperationalError:
            result[table] = -1
    return result


def _integrity(conn: sqlite3.Connection) -> tuple[bool, int]:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    return integrity == "ok", violations


def ensure_schema(settings: Settings | None = None) -> tuple[sqlite3.Connection, SchemaReport]:
    """打开（必要时迁移）数据库，返回连接与迁移报告。"""
    settings = settings or load_settings()
    path = settings.db_path
    existed = path.exists() and path.stat().st_size > 0

    conn = db.connect(path)
    version_before = int(conn.execute("PRAGMA user_version").fetchone()[0])
    counts_before = _counts(conn)
    backup_path: Path | None = None

    pending = db.pending_migration_versions(conn)
    if pending and existed:
        backup_path = db.backup_database(conn, path)
        _LOGGER.info("迁移前备份完成：%s", backup_path)

    result = db.apply_migrations(conn) if pending else db.MigrationResult(version_before, version_before, ())
    integrity_ok, violations = _integrity(conn)
    counts_after = _counts(conn)

    report = SchemaReport(
        db_path=path,
        from_version=version_before,
        to_version=result.to_version,
        applied=result.applied,
        backup_path=backup_path,
        integrity_ok=integrity_ok,
        foreign_key_violations=violations,
        counts_before=counts_before,
        counts_after=counts_after,
    )

    if not integrity_ok or violations:
        conn.close()
        raise RuntimeError(
            f"迁移后完整性检查失败：integrity_ok={integrity_ok}, fk_violations={violations}"
        )
    # 历史表只允许新增，不允许因为迁移丢失行。
    for table, before in counts_before.items():
        after = counts_after.get(table, -1)
        if before >= 0 and after < before:
            conn.close()
            raise RuntimeError(f"迁移导致 {table} 行数减少：{before} -> {after}")

    remaining = db.missing_tables(conn)
    if remaining:
        conn.close()
        raise RuntimeError(f"迁移后仍缺少表：{', '.join(remaining)}")

    return conn, report
