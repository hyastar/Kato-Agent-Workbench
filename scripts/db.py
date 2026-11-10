"""SQLite 连接、迁移与少量 CRUD 工具（仅使用 Python 标准库）。

设计原则：
- 数据库只存元信息、状态、仓库相对路径、URL、许可与哈希。
- 所有写操作使用事务与参数化查询。
- 时间统一为 UTC ISO-8601 文本。

Agent 可直接在 Python 中复用这些函数，例如：

    from scripts import db
    conn = db.connect()
    task_id = db.ensure_task(conn, name="...", source_path="tasks/CURRENT_TASK.md",
                             content_sha256=db.sha256_file(path))
    run_id = db.start_run(conn, task_id)
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "catalog" / "workbench.sqlite3"
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

RUN_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "completed",
    "partial",
    "failed",
    "blocked",
)
DATASET_STATUSES: tuple[str, ...] = (
    "candidate",
    "approved",
    "downloaded",
    "validated",
    "failed",
)
RUN_DATASET_ACTIONS: tuple[str, ...] = (
    "discovered",
    "approved",
    "downloaded",
    "validated",
    "failed",
)
RESEARCH_PLATFORMS: tuple[str, ...] = (
    "zhihu",
    "xiaohongshu",
    "official",
    "media",
    "other",
)
RESEARCH_SOURCE_TYPES: tuple[str, ...] = ("official", "reported", "ugc", "search_lead")
RESEARCH_TOPICS: tuple[str, ...] = (
    "recruitment",
    "experience",
    "policy",
    "industry",
    "salary",
    "warning",
    "other",
)
RESEARCH_COHORTS: tuple[str, ...] = ("2026", "2027", "unknown")
RECRUITMENT_STAGES: tuple[str, ...] = (
    "autumn",
    "spring",
    "makeup",
    "early",
    "internship",
    "other",
    "unknown",
)
VERIFICATION_STATUSES: tuple[str, ...] = (
    "unverified",
    "partially_verified",
    "verified",
    "contradicted",
    "expired",
)
RESEARCH_ACTIONS: tuple[str, ...] = ("discovered", "imported", "verified", "updated")
COMMENT_SORT_BASES: tuple[str, ...] = (
    "high_likes",
    "latest",
    "high_likes_then_latest",
    "visible_order",
)
COMMENT_COVERAGE_STATUSES: tuple[str, ...] = (
    "complete",
    "partial",
    "blocked",
    "not_available",
)
CAMPAIGN_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "partial",
    "completed",
    "blocked",
    "failed",
)
ARTIFACT_TYPES: tuple[str, ...] = (
    "post_markdown",
    "comments_markdown",
    "index",
    "report",
)
EMPLOYMENT_TOPICS: tuple[str, ...] = (
    "salary", "job_search", "probation", "layoff", "home_idle",
    "factory", "computer", "machinery", "campus", "work_life", "other",
)
EMPLOYMENT_STATUSES: tuple[str, ...] = (
    "job_seeking", "employed", "probation", "left", "unemployed",
    "waiting", "career_change", "other", "unknown",
)
EXPERIENCE_TYPES: tuple[str, ...] = (
    "personal", "secondhand", "recruitment_ad", "opinion", "unknown",
)
REQUIRED_TABLES: tuple[str, ...] = (
    "tasks",
    "runs",
    "datasets",
    "run_datasets",
    "research_items",
    "run_research_items",
    "research_comments",
    "research_campaigns",
    "research_batches",
    "research_artifacts",
    "research_search_queries",
    "research_keyword_candidates",
)


def utc_now() -> str:
    """返回毫秒精度 UTC 时间，例如 2026-11-06T08:25:00.123Z。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """解析数据库路径：显式参数 > KATO_DB_PATH > 默认 data/catalog/workbench.sqlite3。"""
    candidate: str | Path | None = db_path
    if candidate is None:
        env_value = os.environ.get("KATO_DB_PATH")
        candidate = env_value if env_value else DEFAULT_DB_PATH
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def to_repo_relative(path: str | Path) -> str:
    """尽量转为仓库相对路径；路径在仓库外时原样返回，并在文档中视为特例。"""
    candidate = Path(path).expanduser()
    resolved = candidate.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(candidate)


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """打开数据库连接并启用外键、WAL 与忙等待。"""
    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@dataclass(frozen=True)
class MigrationResult:
    from_version: int
    to_version: int
    applied: tuple[int, ...]


def migration_files(migrations_dir: str | Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    """返回按版本号升序排列的迁移文件。文件名必须形如 001_init.sql。"""
    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"迁移目录不存在：{directory}")

    migrations: list[tuple[int, Path]] = []
    seen: dict[int, Path] = {}
    for path in sorted(directory.glob("*.sql")):
        prefix = path.name.split("_", 1)[0]
        if not prefix.isdigit():
            raise ValueError(f"迁移文件名必须以数字版本开头：{path.name}")
        version = int(prefix)
        if version in seen:
            raise ValueError(f"迁移版本重复：{version}（{seen[version].name} 与 {path.name}）")
        seen[version] = path
        migrations.append((version, path))
    return migrations


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: str | Path = MIGRATIONS_DIR,
) -> MigrationResult:
    """执行所有高于 PRAGMA user_version 的迁移；重复调用不删除数据。"""
    start_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    current = start_version
    applied: list[int] = []

    for version, path in migration_files(migrations_dir):
        if version <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        # 迁移可能重建被外键引用的表；在事务外临时关闭外键，迁移后统一检查。
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.executescript(
                "BEGIN;\n" + sql + f"\nPRAGMA user_version = {version};\nCOMMIT;"
            )
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            conn.execute("PRAGMA foreign_keys = ON")
            raise
        conn.execute("PRAGMA foreign_keys = ON")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"迁移 {version:03d} 后存在外键违规：{len(violations)} 条"
            )
        current = version
        applied.append(version)

    return MigrationResult(start_version, current, tuple(applied))


def missing_tables(conn: sqlite3.Connection) -> list[str]:
    """返回当前连接中缺失的必要表。"""
    existing = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    return [table for table in REQUIRED_TABLES if table not in existing]


def pending_migration_versions(
    conn: sqlite3.Connection,
    migrations_dir: str | Path = MIGRATIONS_DIR,
) -> list[int]:
    """返回高于当前 PRAGMA user_version 的迁移版本号（升序）。

    迁移是否待执行应以版本号为准，而不是“必要表是否缺失”：V1 -> V2 这类只新增
    表的升级不能被“基础表已存在”的旧判断跳过。
    """
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    return [version for version, _ in migration_files(migrations_dir) if version > current]


def backup_database(
    conn: sqlite3.Connection,
    db_path: str | Path,
    *,
    backup_dir: str | Path | None = None,
) -> Path:
    """用 SQLite 在线备份 API 复制数据库，并验证备份可读。

    默认写入数据库所在目录的 `backups/` 子目录；该目录位于被 Git 忽略的
    data/catalog 下（或测试临时目录），不会进入版本库。
    """
    source_path = Path(db_path)
    target_dir = Path(backup_dir) if backup_dir is not None else source_path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = target_dir / f"{source_path.name}.{stamp}.bak"

    destination = sqlite3.connect(str(target))
    try:
        conn.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"备份完整性检查失败：{integrity}")
        destination.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    finally:
        destination.close()
    return target


def connect_ready(
    db_path: str | Path | None = None,
    migrations_dir: str | Path = MIGRATIONS_DIR,
    *,
    backup: bool = True,
) -> sqlite3.Connection:
    """打开连接并应用所有待执行迁移（按 PRAGMA user_version 判断）。

    - 全新路径：直接迁移到最新版本；
    - 旧版本库（例如 V1）：先做一次在线备份，再应用 002 等增量迁移；
    - 已是最新版本：不迁移、不备份，保持幂等。

    供 CLI 工具使用：新建或空的数据库文件不会因为未先运行 init_db 而报
    “no such table”；迁移失败时关闭连接并抛出异常。
    """
    path = resolve_db_path(db_path)
    existed = path.exists() and path.stat().st_size > 0
    conn = connect(path)
    try:
        if pending_migration_versions(conn, migrations_dir):
            if existed and backup:
                backup_database(conn, path)
            apply_migrations(conn, migrations_dir)
        remaining = missing_tables(conn)
        if remaining:
            raise RuntimeError(f"迁移后仍缺少表：{', '.join(remaining)}")
    except Exception:
        conn.close()
        raise
    return conn


def ensure_task(
    conn: sqlite3.Connection,
    *,
    name: str,
    source_path: str,
    content_sha256: str,
    task_id: str | None = None,
) -> str:
    """登记任务定义快照；相同内容重复调用复用同一 task_id。"""
    if task_id is None:
        task_id = "task_" + hashlib.sha256(
            f"{source_path}\n{content_sha256}".encode("utf-8")
        ).hexdigest()[:16]

    existing = conn.execute(
        "SELECT task_id FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    if existing is None:
        with conn:
            conn.execute(
                "INSERT INTO tasks (task_id, name, source_path, content_sha256, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, name, source_path, content_sha256, utc_now()),
            )
    return task_id


def start_run(conn: sqlite3.Connection, task_id: str, run_id: str | None = None) -> str:
    """创建一次执行记录；run_id 默认由 UTC 时间戳与随机后缀组成。"""
    if run_id is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{stamp}-{secrets.token_hex(2)}"

    with conn:
        conn.execute(
            "INSERT INTO runs (run_id, task_id, status, started_at) VALUES (?, ?, 'pending', ?)",
            (run_id, task_id, utc_now()),
        )
    return run_id


def set_run_status(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    *,
    report_path: str | None = None,
    error_message: str | None = None,
) -> None:
    """更新执行状态；终态写入结束时间。"""
    if status not in RUN_STATUSES:
        raise ValueError(f"不支持的运行状态：{status}")

    finished_at = utc_now() if status in {"completed", "partial", "failed", "blocked"} else None
    with conn:
        cursor = conn.execute(
            "UPDATE runs SET status = ?, finished_at = COALESCE(?, finished_at), "
            "report_path = COALESCE(?, report_path), "
            "error_message = COALESCE(?, error_message) WHERE run_id = ?",
            (status, finished_at, report_path, error_message, run_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"运行不存在：{run_id}")


def get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()


def dataset_identity(source: str, source_url: str, version: str | None) -> tuple[str, str, str]:
    """归一化数据集身份：version 的空字符串统一成 None，返回 (id, url, version)。"""
    normalized_version = version or None
    dataset_id = "ds_" + hashlib.sha256(
        f"{source}\n{source_url}\n{normalized_version or ''}".encode("utf-8")
    ).hexdigest()[:16]
    return dataset_id, source_url, normalized_version


DATASET_UPDATE_FIELDS: tuple[str, ...] = (
    "name",
    "license_name",
    "license_url",
    "format",
    "image_count",
    "status",
    "raw_path",
    "processed_path",
    "sha256",
)


def upsert_dataset(
    conn: sqlite3.Connection,
    *,
    name: str,
    source: str,
    source_url: str,
    version: str | None = None,
    license_name: str | None = None,
    license_url: str | None = None,
    format: str | None = None,
    image_count: int | None = None,
    status: str = "candidate",
    raw_path: str | None = None,
    processed_path: str | None = None,
    sha256: str | None = None,
) -> tuple[str, bool]:
    """按 (source, source_url, version) 幂等登记数据集；返回 (dataset_id, 是否新建)。"""
    if not name.strip():
        raise ValueError("name 不能为空")
    if not source.strip():
        raise ValueError("source 不能为空")
    if not source_url.strip():
        raise ValueError("source_url 不能为空")
    if status not in DATASET_STATUSES:
        raise ValueError(f"不支持的数据集状态：{status}")
    if image_count is not None and image_count < 0:
        raise ValueError("image_count 不能为负数")

    dataset_id, normalized_url, normalized_version = dataset_identity(
        source, source_url, version
    )
    now = utc_now()
    existing = conn.execute(
        "SELECT dataset_id FROM datasets "
        "WHERE source = ? AND source_url = ? AND COALESCE(version, '') = ?",
        (source, normalized_url, normalized_version or ""),
    ).fetchone()

    values = {
        "name": name,
        "license_name": license_name,
        "license_url": license_url,
        "format": format,
        "image_count": image_count,
        "status": status,
        "raw_path": raw_path,
        "processed_path": processed_path,
        "sha256": sha256,
    }

    with conn:
        if existing is None:
            conn.execute(
                "INSERT INTO datasets (dataset_id, name, source, source_url, version, "
                "license_name, license_url, format, image_count, status, raw_path, "
                "processed_path, sha256, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dataset_id,
                    name,
                    source,
                    normalized_url,
                    normalized_version,
                    license_name,
                    license_url,
                    format,
                    image_count,
                    status,
                    raw_path,
                    processed_path,
                    sha256,
                    now,
                    now,
                ),
            )
            return dataset_id, True

        present = {key: value for key, value in values.items() if value is not None}
        assignments = ", ".join(f"{field} = ?" for field in present)
        conn.execute(
            f"UPDATE datasets SET {assignments}, updated_at = ? WHERE dataset_id = ?",
            (*present.values(), now, existing["dataset_id"]),
        )
        return str(existing["dataset_id"]), False


def link_run_dataset(
    conn: sqlite3.Connection,
    run_id: str,
    dataset_id: str,
    action: str,
) -> None:
    """建立执行与数据集的关联；重复关联是幂等的。"""
    if action not in RUN_DATASET_ACTIONS:
        raise ValueError(f"不支持的关联动作：{action}")
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO run_datasets (run_id, dataset_id, action, created_at) "
            "VALUES (?, ?, ?, ?)",
            (run_id, dataset_id, action, utc_now()),
        )


def list_datasets(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source)

    sql = "SELECT * FROM datasets"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, name ASC"
    if limit is not None:
        if limit < 0:
            raise ValueError("limit 不能为负数")
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params))


def get_dataset(conn: sqlite3.Connection, dataset_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,)).fetchone()


def dataset_links(conn: sqlite3.Connection, dataset_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM run_datasets WHERE dataset_id = ? ORDER BY created_at",
            (dataset_id,),
        )
    )


# ---------------------------------------------------------------------------
# 研究条目（research_items / run_research_items）
# ---------------------------------------------------------------------------


def normalize_url(url: str) -> str:
    """规范化 URL：小写 scheme/host、去掉 fragment，保留路径与查询参数。

    不删除可能影响身份识别的路径或参数，只做最小的稳定化处理。
    """
    candidate = (url or "").strip()
    if not candidate:
        raise ValueError("canonical_url 不能为空")
    parts = urlsplit(candidate)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("canonical_url 必须是 http(s) URL")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


def research_item_identity(platform: str, canonical_url: str) -> str:
    """由 (platform, 规范化 URL) 稳定派生 item_id。"""
    normalized = normalize_url(canonical_url)
    return "ri_" + hashlib.sha256(
        f"{platform}\n{normalized}".encode("utf-8")
    ).hexdigest()[:16]


def _normalize_iso8601(value: str | None, field: str) -> str | None:
    """校验并保留 ISO-8601 文本；空值返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} 必须是 ISO-8601 日期或时间：{text}") from exc
    return text


def upsert_research_item(
    conn: sqlite3.Connection,
    *,
    platform: str,
    canonical_url: str,
    title: str,
    source_type: str,
    topic: str,
    cohort: str,
    recruitment_stage: str,
    summary: str | None = None,
    company: str | None = None,
    city: str | None = None,
    published_at: str | None = None,
    collected_at: str | None = None,
    verification_status: str | None = None,
    verification_url: str | None = None,
    verified_at: str | None = None,
) -> tuple[str, bool]:
    """按 (platform, canonical_url) 幂等登记研究条目；返回 (item_id, 是否新建)。

    `verification_status="verified"` 时必须同时提供 `verification_url` 与
    `verified_at`，否则拒绝写入——不能用猜测或模型记忆充当核验证据。
    """
    if platform not in RESEARCH_PLATFORMS:
        raise ValueError(f"不支持的 platform：{platform}（可选：{', '.join(RESEARCH_PLATFORMS)}）")
    if source_type not in RESEARCH_SOURCE_TYPES:
        raise ValueError(
            f"不支持的 source_type：{source_type}（可选：{', '.join(RESEARCH_SOURCE_TYPES)}）"
        )
    if topic not in RESEARCH_TOPICS:
        raise ValueError(f"不支持的 topic：{topic}（可选：{', '.join(RESEARCH_TOPICS)}）")
    if cohort not in RESEARCH_COHORTS:
        raise ValueError(f"不支持的 cohort：{cohort}（可选：{', '.join(RESEARCH_COHORTS)}）")
    if recruitment_stage not in RECRUITMENT_STAGES:
        raise ValueError(
            f"不支持的 recruitment_stage：{recruitment_stage}"
            f"（可选：{', '.join(RECRUITMENT_STAGES)}）"
        )
    if verification_status is not None and verification_status not in VERIFICATION_STATUSES:
        raise ValueError(
            f"不支持的 verification_status：{verification_status}"
            f"（可选：{', '.join(VERIFICATION_STATUSES)}）"
        )
    if not str(title or "").strip():
        raise ValueError("title 不能为空")

    normalized_url = normalize_url(canonical_url)
    item_id = research_item_identity(platform, normalized_url)
    status = verification_status or "unverified"
    verification_url = (verification_url or "").strip() or None
    verified_at = _normalize_iso8601(verified_at, "verified_at")
    if status == "verified" and (verification_url is None or verified_at is None):
        raise ValueError(
            "verification_status=verified 时必须提供 verification_url 与 verified_at"
        )

    published_at = _normalize_iso8601(published_at, "published_at")
    collected_at = _normalize_iso8601(collected_at, "collected_at") or utc_now()

    values: dict[str, Any] = {
        "title": str(title).strip(),
        "summary": summary,
        "source_type": source_type,
        "topic": topic,
        "cohort": cohort,
        "recruitment_stage": recruitment_stage,
        "company": company,
        "city": city,
        "published_at": published_at,
        "verification_status": verification_status,
        "verification_url": verification_url,
        "verified_at": verified_at,
    }
    now = utc_now()
    existing = conn.execute(
        "SELECT item_id FROM research_items WHERE platform = ? AND canonical_url = ?",
        (platform, normalized_url),
    ).fetchone()

    with conn:
        if existing is None:
            conn.execute(
                "INSERT INTO research_items (item_id, platform, canonical_url, title, summary, "
                "source_type, topic, cohort, recruitment_stage, company, city, published_at, "
                "collected_at, verification_status, verification_url, verified_at, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    platform,
                    normalized_url,
                    values["title"],
                    summary,
                    source_type,
                    topic,
                    cohort,
                    recruitment_stage,
                    company,
                    city,
                    published_at,
                    collected_at,
                    status,
                    verification_url,
                    verified_at,
                    now,
                    now,
                ),
            )
            return item_id, True

        present = {key: value for key, value in values.items() if value is not None}
        assignments = ", ".join(f"{field} = ?" for field in present)
        conn.execute(
            f"UPDATE research_items SET {assignments}, collected_at = ?, updated_at = ? "
            "WHERE item_id = ?",
            (*present.values(), collected_at, now, existing["item_id"]),
        )
        return str(existing["item_id"]), False


def link_run_research_item(
    conn: sqlite3.Connection,
    run_id: str,
    item_id: str,
    action: str = "imported",
) -> None:
    """建立执行与研究条目的关联；重复关联是幂等的。"""
    if action not in RESEARCH_ACTIONS:
        raise ValueError(f"不支持的关联动作：{action}（可选：{', '.join(RESEARCH_ACTIONS)}）")
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO run_research_items (run_id, item_id, action, created_at) "
            "VALUES (?, ?, ?, ?)",
            (run_id, item_id, action, utc_now()),
        )


def list_research_items(
    conn: sqlite3.Connection,
    *,
    cohort: str | None = None,
    platform: str | None = None,
    topic: str | None = None,
    verification: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[Any] = []
    if cohort:
        clauses.append("cohort = ?")
        params.append(cohort)
    if platform:
        clauses.append("platform = ?")
        params.append(platform)
    if topic:
        clauses.append("topic = ?")
        params.append(topic)
    if verification:
        clauses.append("verification_status = ?")
        params.append(verification)

    sql = "SELECT * FROM research_items"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY collected_at DESC, item_id ASC"
    if limit is not None:
        if limit < 0:
            raise ValueError("limit 不能为负数")
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params))


def get_research_item(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM research_items WHERE item_id = ?", (item_id,)
    ).fetchone()


def research_item_links(conn: sqlite3.Connection, item_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM run_research_items WHERE item_id = ? ORDER BY created_at",
            (item_id,),
        )
    )
