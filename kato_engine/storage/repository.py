"""V6 引擎的 SQLite 仓储。

分工：
- 候选、查询、运行、指标：V6 新表，本文件直接管理；
- 文章、评论、Campaign/Batch、Markdown 产物：复用已验证的
  `scripts.employment.repository`，避免出现第二套 50 条规则与评论层级实现。

所有写操作参数化并使用事务；`state` 变化必须合法（见 core.state_machine）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from scripts import db
from scripts.employment import repository as legacy

from kato_engine.core.state_machine import assert_transition
from kato_engine.storage.migrations import ensure_schema
from kato_engine.config.settings import Settings, load_settings


def candidate_id_for(platform: str, canonical_url: str) -> str:
    basis = f"{platform}\n{canonical_url}".encode("utf-8")
    return "cd_" + hashlib.sha256(basis).hexdigest()[:16]


def query_run_id_for(platform: str, combined_query: str) -> str:
    basis = f"{platform}\n{combined_query}".encode("utf-8")
    return "qr_" + hashlib.sha256(basis).hexdigest()[:16]


def iso_after(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    moment = datetime.now(timezone.utc) + timedelta(seconds=int(seconds))
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class EnqueueResult:
    inserted: int
    duplicates: int
    skipped_existing: int

    def to_dict(self) -> dict[str, int]:
        return {
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "skipped_existing": self.skipped_existing,
        }


class EngineRepository:
    """引擎仓储。一个进程一个连接，单线程使用。"""

    def __init__(self, conn: sqlite3.Connection, settings: Settings) -> None:
        self.conn = conn
        self.settings = settings
        self.conn.row_factory = sqlite3.Row

    # -- 生命周期 ---------------------------------------------------------
    @classmethod
    def open(cls, settings: Settings | None = None) -> tuple["EngineRepository", Any]:
        settings = settings or load_settings()
        conn, report = ensure_schema(settings)
        return cls(conn, settings), report

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    # -- Campaign ---------------------------------------------------------
    def get_campaign(self, campaign_id: str) -> sqlite3.Row | None:
        return legacy.get_campaign(self.conn, campaign_id)

    def ensure_campaign(self, campaign_id: str) -> sqlite3.Row:
        row = self.get_campaign(campaign_id)
        if row is None:
            raise KeyError(f"Campaign 不存在：{campaign_id}")
        return row

    def campaign_article_counts(self, campaign_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT platform, COUNT(*) AS n FROM research_items "
            "WHERE campaign_id = ? GROUP BY platform",
            (campaign_id,),
        ).fetchall()
        return {str(row["platform"]): int(row["n"]) for row in rows}

    def dimension_article_counts(self, campaign_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT COALESCE(employment_topic, 'unclassified') AS dimension, COUNT(*) AS n "
            "FROM research_items WHERE campaign_id = ? GROUP BY 1",
            (campaign_id,),
        ).fetchall()
        return {str(row["dimension"]): int(row["n"]) for row in rows}

    def refresh_campaign_total(self, campaign_id: str) -> int:
        total = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM research_items WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()[0]
        )
        with self.conn:
            self.conn.execute(
                "UPDATE research_campaigns SET actual_total = ? WHERE campaign_id = ?",
                (total, campaign_id),
            )
        return total

    # -- 引擎运行 ---------------------------------------------------------
    def start_engine_run(
        self,
        campaign_id: str,
        *,
        target_xiaohongshu: int = 0,
        target_zhihu: int = 0,
        profile_dir: str | None = None,
        notes: str | None = None,
    ) -> str:
        engine_run_id = "er_" + hashlib.sha256(
            f"{campaign_id}\n{db.utc_now()}".encode("utf-8")
        ).hexdigest()[:16]
        with self.conn:
            self.conn.execute(
                "INSERT INTO engine_runs (engine_run_id, campaign_id, started_at, "
                "target_xiaohongshu, target_zhihu, profile_dir, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    engine_run_id,
                    campaign_id,
                    db.utc_now(),
                    target_xiaohongshu,
                    target_zhihu,
                    profile_dir,
                    notes,
                ),
            )
        return engine_run_id

    def finish_engine_run(
        self,
        engine_run_id: str,
        *,
        stop_reason: str,
        articles_added: int,
        comments_added: int,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE engine_runs SET finished_at = ?, stop_reason = ?, "
                "articles_added = ?, comments_added = ? WHERE engine_run_id = ?",
                (db.utc_now(), stop_reason, articles_added, comments_added, engine_run_id),
            )

    def get_engine_run(self, engine_run_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM engine_runs WHERE engine_run_id = ?", (engine_run_id,)
        ).fetchone()

    def record_metric(
        self,
        *,
        phase: str,
        duration_ms: int,
        engine_run_id: str | None = None,
        candidate_id: str | None = None,
        platform: str | None = None,
        article_phase: str | None = None,
        outcome: str | None = None,
        error_type: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO engine_metrics (engine_run_id, candidate_id, platform, "
                "article_phase, phase, duration_ms, outcome, error_type, detail, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    engine_run_id,
                    candidate_id,
                    platform,
                    article_phase,
                    phase,
                    int(duration_ms),
                    outcome,
                    error_type,
                    json.dumps(detail, ensure_ascii=False) if detail else None,
                    db.utc_now(),
                ),
            )

    # -- 候选队列 ---------------------------------------------------------
    def existing_urls(self, platform: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT canonical_url FROM research_items WHERE platform = ?", (platform,)
        ).fetchall()
        return {str(row[0]) for row in rows}

    def enqueue_candidates(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        engine_run_id: str | None = None,
    ) -> EnqueueResult:
        """幂等入队。已采集的 URL 记为 skipped，重复候选计为 duplicate。"""
        materialized = list(rows)
        inserted = duplicates = skipped = 0
        now = db.utc_now()
        collected = {
            platform: self.existing_urls(platform)
            for platform in self._platforms(materialized)
        }
        with self.conn:
            for row in materialized:
                platform = str(row["platform"])
                url = str(row["canonical_url"])
                candidate_id = candidate_id_for(platform, url)
                state = "queued"
                error_type = None
                if url in collected.get(platform, set()):
                    state = "skipped"
                    error_type = "already_collected"
                cursor = self.conn.execute(
                    "INSERT OR IGNORE INTO engine_candidates "
                    "(candidate_id, engine_run_id, campaign_id, platform, canonical_url, "
                    "title_hint, dimension, keyword, combined_query, state, error_type, "
                    "discovered_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        candidate_id,
                        engine_run_id,
                        str(row["campaign_id"]),
                        platform,
                        url,
                        row.get("title_hint"),
                        str(row["dimension"]),
                        row.get("keyword"),
                        row.get("combined_query"),
                        state,
                        error_type,
                        now,
                        now,
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                    if state == "skipped":
                        skipped += 1
                else:
                    duplicates += 1
        return EnqueueResult(inserted, duplicates, skipped)

    @staticmethod
    def _platforms(rows: Iterable[dict[str, Any]]) -> Sequence[str]:
        return sorted({str(row["platform"]) for row in rows})

    def claim_next(
        self,
        campaign_id: str,
        platform: str,
        *,
        owner: str,
        lease_seconds: int,
        max_attempts: int,
        engine_run_id: str | None = None,
    ) -> sqlite3.Row | None:
        """领取下一条候选并加租约。优先 queued，其次 retryable_failed。"""
        now = db.utc_now()
        lease_until = iso_after(lease_seconds)
        row = self.conn.execute(
            "SELECT * FROM engine_candidates WHERE campaign_id = ? AND platform = ? "
            "AND state IN ('queued', 'retryable_failed') AND attempts < ? "
            "AND (lease_until IS NULL OR lease_until < ?) "
            # 新入队优先：刚搜索到的卡片仍在当前结果页，命中率最高；
            # 旧候选退回队列后排在后面，避免反复重试过期结果。
            "ORDER BY CASE state WHEN 'queued' THEN 0 ELSE 1 END, discovered_at DESC, candidate_id "
            "LIMIT 1",
            (campaign_id, platform, max_attempts, now),
        ).fetchone()
        if row is None:
            return None
        with self.conn:
            self.conn.execute(
                "UPDATE engine_candidates SET state = 'processing', lease_owner = ?, "
                "lease_until = ?, attempts = attempts + 1, "
                "engine_run_id = COALESCE(?, engine_run_id), updated_at = ? "
                "WHERE candidate_id = ? AND state = ?",
                (
                    owner,
                    lease_until,
                    engine_run_id,
                    now,
                    row["candidate_id"],
                    row["state"],
                ),
            )
        assert_transition(str(row["state"]), "processing")
        return self.conn.execute(
            "SELECT * FROM engine_candidates WHERE candidate_id = ?", (row["candidate_id"],)
        ).fetchone()

    def _transition(
        self,
        candidate_id: str,
        target: str,
        *,
        item_id: str | None = None,
        error: str | None = None,
        error_type: str | None = None,
        clear_lease: bool = True,
    ) -> None:
        current = self.conn.execute(
            "SELECT state FROM engine_candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        if current is None:
            raise KeyError(f"候选不存在：{candidate_id}")
        assert_transition(str(current["state"]), target)
        with self.conn:
            self.conn.execute(
                "UPDATE engine_candidates SET state = ?, item_id = COALESCE(?, item_id), "
                "last_error = COALESCE(?, last_error), error_type = COALESCE(?, error_type), "
                "lease_owner = CASE WHEN ? THEN NULL ELSE lease_owner END, "
                "lease_until = CASE WHEN ? THEN NULL ELSE lease_until END, updated_at = ? "
                "WHERE candidate_id = ?",
                (target, item_id, error, error_type, 1 if clear_lease else 0,
                 1 if clear_lease else 0, db.utc_now(), candidate_id),
            )

    def candidate_state(self, candidate_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT state FROM engine_candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        return str(row["state"]) if row else None

    def mark_accepted(self, candidate_id: str, item_id: str) -> None:
        self._transition(candidate_id, "accepted", item_id=item_id)

    def mark_completed(self, candidate_id: str, item_id: str | None = None) -> None:
        self._transition(candidate_id, "completed", item_id=item_id)

    def mark_rejected(self, candidate_id: str, *, error_type: str, reason: str) -> None:
        self._transition(candidate_id, "rejected", error=reason, error_type=error_type)

    def mark_blocked(self, candidate_id: str, *, error_type: str, reason: str) -> None:
        self._transition(candidate_id, "blocked", error=reason, error_type=error_type)

    def mark_retryable(
        self,
        candidate_id: str,
        *,
        error_type: str,
        reason: str,
        requeue: bool = False,
    ) -> None:
        self._transition(candidate_id, "retryable_failed", error=reason, error_type=error_type)
        if requeue:
            self._transition(candidate_id, "queued", error=reason, error_type=error_type)

    def recover_expired_leases(self, campaign_id: str | None = None) -> int:
        """把租约过期仍停在 processing 的候选退回 queued。"""
        now = db.utc_now()
        clauses = ["state = 'processing'", "lease_until IS NOT NULL", "lease_until < ?"]
        params: list[Any] = [now]
        if campaign_id:
            clauses.append("campaign_id = ?")
            params.append(campaign_id)
        rows = self.conn.execute(
            f"SELECT candidate_id FROM engine_candidates WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()
        if not rows:
            return 0
        with self.conn:
            for row in rows:
                self.conn.execute(
                    "UPDATE engine_candidates SET state = 'queued', lease_owner = NULL, "
                    "lease_until = NULL, error_type = COALESCE(error_type, 'lease_expired'), "
                    "updated_at = ? WHERE candidate_id = ?",
                    (now, row["candidate_id"]),
                )
        return len(rows)

    def requeue_blocked(self, platform: str, *, campaign_id: str) -> int:
        """用户完成人工验证后，把 blocked 候选放回队列。"""
        rows = self.conn.execute(
            "SELECT candidate_id FROM engine_candidates "
            "WHERE platform = ? AND campaign_id = ? AND state = 'blocked'",
            (platform, campaign_id),
        ).fetchall()
        with self.conn:
            for row in rows:
                self.conn.execute(
                    "UPDATE engine_candidates SET state = 'queued', lease_owner = NULL, "
                    "lease_until = NULL, updated_at = ? WHERE candidate_id = ?",
                    (db.utc_now(), row["candidate_id"]),
                )
        return len(rows)

    def candidate_state_counts(
        self, *, campaign_id: str, platform: str | None = None
    ) -> dict[str, int]:
        if platform:
            rows = self.conn.execute(
                "SELECT state, COUNT(*) AS n FROM engine_candidates "
                "WHERE campaign_id = ? AND platform = ? GROUP BY state",
                (campaign_id, platform),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT state, COUNT(*) AS n FROM engine_candidates "
                "WHERE campaign_id = ? GROUP BY state",
                (campaign_id,),
            ).fetchall()
        return {str(row["state"]): int(row["n"]) for row in rows}

    def run_articles_accepted(self, engine_run_id: str, platform: str) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM engine_candidates WHERE engine_run_id = ? "
                "AND platform = ? AND state IN ('accepted', 'completed')",
                (engine_run_id, platform),
            ).fetchone()[0]
        )

    # -- 查询调度 ---------------------------------------------------------
    def executed_queries(self, platform: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT combined_query FROM engine_query_runs WHERE platform = ?", (platform,)
        ).fetchall()
        executed = {str(row[0]) for row in rows}
        # V5 的旧查询记录同样视为"已执行"，避免重复消耗。
        legacy_rows = self.conn.execute(
            "SELECT keyword FROM research_search_queries WHERE platform = ?", (platform,)
        ).fetchall()
        executed.update(str(row[0]) for row in legacy_rows)
        return executed

    def record_query_run(
        self,
        *,
        campaign_id: str,
        platform: str,
        dimension: str,
        keyword: str,
        combined_query: str,
        candidates_found: int,
        duplicates: int,
        opened_details: int,
        accepted: int,
        duration_ms: int,
        failure_reason: str | None = None,
        engine_run_id: str | None = None,
    ) -> str:
        query_run_id = query_run_id_for(platform, combined_query)
        with self.conn:
            self.conn.execute(
                "INSERT INTO engine_query_runs (query_run_id, engine_run_id, campaign_id, "
                "platform, dimension, keyword, combined_query, candidates_found, duplicates, "
                "opened_details, accepted, failure_reason, duration_ms, executed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(query_run_id) DO UPDATE SET candidates_found = excluded.candidates_found, "
                "duplicates = excluded.duplicates, opened_details = excluded.opened_details, "
                "accepted = excluded.accepted, failure_reason = excluded.failure_reason, "
                "duration_ms = excluded.duration_ms, executed_at = excluded.executed_at",
                (
                    query_run_id,
                    engine_run_id,
                    campaign_id,
                    platform,
                    dimension,
                    keyword,
                    combined_query,
                    candidates_found,
                    duplicates,
                    opened_details,
                    accepted,
                    failure_reason,
                    duration_ms,
                    db.utc_now(),
                ),
            )
        return query_run_id

    def dimension_query_stats(
        self, campaign_id: str, platform: str
    ) -> dict[str, dict[str, int]]:
        rows = self.conn.execute(
            "SELECT dimension, COUNT(*) AS queries, COALESCE(SUM(candidates_found), 0) AS found, "
            "COALESCE(SUM(accepted), 0) AS accepted FROM engine_query_runs "
            "WHERE campaign_id = ? AND platform = ? GROUP BY dimension",
            (campaign_id, platform),
        ).fetchall()
        return {
            str(row["dimension"]): {
                "queries": int(row["queries"]),
                "found": int(row["found"]),
                "accepted": int(row["accepted"]),
            }
            for row in rows
        }

    # -- 文章 / 评论（复用 V4 仓储） --------------------------------------
    def save_article(self, payload: dict[str, Any]) -> tuple[str, bool]:
        return legacy.save_article(self.conn, payload)

    def attach_article(
        self,
        item_id: str,
        *,
        campaign_id: str | None = None,
        batch_id: str | None = None,
    ) -> None:
        legacy.attach_article(self.conn, item_id, campaign_id=campaign_id, batch_id=batch_id)

    def import_comments(
        self, item_id: str, nodes: Iterable[dict[str, Any]]
    ) -> dict[str, int]:
        return legacy.import_comment_thread(self.conn, item_id, nodes)

    def update_stats(self, item_id: str, stats: dict[str, Any]) -> dict[str, Any]:
        return legacy.update_article_stats(self.conn, item_id, stats)

    def set_classification(self, item_id: str, **fields: Any) -> None:
        legacy.set_article_classification(self.conn, item_id, **fields)

    def set_markdown_paths(
        self, item_id: str, *, post_path: str | None, comments_path: str | None
    ) -> None:
        legacy.set_article_markdown_paths(
            self.conn, item_id, post_path=post_path, comments_path=comments_path
        )

    def upsert_artifact(
        self, *, item_id: str | None, artifact_type: str, relative_path: str, sha256: str
    ) -> str:
        return legacy.upsert_artifact(
            self.conn,
            item_id=item_id,
            artifact_type=artifact_type,
            relative_path=relative_path,
            sha256=sha256,
        )

    def existing_artifact_hash(self, relative_path: str) -> str | None:
        row = self.conn.execute(
            "SELECT sha256 FROM research_artifacts WHERE relative_path = ?", (relative_path,)
        ).fetchone()
        return str(row[0]) if row else None

    def list_items(self, campaign_id: str, limit: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM research_items WHERE campaign_id = ? ORDER BY collected_at"
        params: list[Any] = [campaign_id]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return self.conn.execute(sql, params).fetchall()

    def get_item(self, item_id: str) -> sqlite3.Row | None:
        return legacy.get_article(self.conn, item_id)

    def find_item(self, platform: str, canonical_url: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM research_items WHERE platform = ? AND canonical_url = ?",
            (platform, canonical_url),
        ).fetchone()

    def item_comments(self, item_id: str) -> list[sqlite3.Row]:
        return legacy.list_comments(self.conn, item_id)
