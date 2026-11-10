"""持久化候选队列。

候选不是内存列表：全部落在 `engine_candidates`，进程重启后按状态继续。
本模块负责"搜索结果 → 规范化 URL → 幂等入队"和"领取/回写状态"，
状态合法性由 `core.state_machine` 统一校验。
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Any, Iterable

from kato_engine.discovery.deduplication import canonical_url
from kato_engine.discovery.keyword_planner import QueryPlan
from kato_engine.observability.logging import get_logger
from kato_engine.collection.models import SearchHit
from kato_engine.storage.repository import EnqueueResult, EngineRepository

_LOGGER = get_logger("kato.queue")


def default_lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


class CandidateQueue:
    def __init__(self, repository: EngineRepository) -> None:
        self.repo = repository

    def add(
        self,
        *,
        campaign_id: str,
        platform: str,
        dimension: str,
        keyword: str,
        combined_query: str,
        hits: Iterable[SearchHit],
        engine_run_id: str | None = None,
    ) -> dict[str, int]:
        """把一批搜索结果写入队列；同一批内重复也只算一次。"""
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        invalid = 0
        duplicates_in_batch = 0
        hits_list = list(hits)
        for hit in hits_list:
            try:
                url = canonical_url(platform, hit.canonical_url)
            except ValueError as exc:
                invalid += 1
                _LOGGER.debug("跳过无法识别的候选 URL：%s", exc)
                continue
            if url in seen:
                duplicates_in_batch += 1
                continue
            seen.add(url)
            rows.append(
                {
                    "campaign_id": campaign_id,
                    "platform": platform,
                    "canonical_url": url,
                    "title_hint": hit.title,
                    "dimension": dimension,
                    "keyword": keyword,
                    "combined_query": combined_query,
                }
            )

        result: EnqueueResult = self.repo.enqueue_candidates(rows, engine_run_id=engine_run_id)
        return {
            "hits": len(hits_list),
            "invalid": invalid,
            "inserted": result.inserted,
            "duplicates": result.duplicates + duplicates_in_batch,
            "skipped_existing": result.skipped_existing,
        }

    def claim(
        self,
        *,
        campaign_id: str,
        platform: str,
        owner: str | None = None,
        engine_run_id: str | None = None,
    ):
        settings = self.repo.settings
        return self.repo.claim_next(
            campaign_id,
            platform,
            owner=owner or default_lease_owner(),
            lease_seconds=settings.lease_seconds,
            max_attempts=settings.max_attempts,
            engine_run_id=engine_run_id,
        )

    def pending(self, *, campaign_id: str, platform: str) -> int:
        counts = self.repo.candidate_state_counts(campaign_id=campaign_id, platform=platform)
        return counts.get("queued", 0) + counts.get("retryable_failed", 0)

    def stats(self, *, campaign_id: str, platform: str | None = None) -> dict[str, int]:
        return self.repo.candidate_state_counts(campaign_id=campaign_id, platform=platform)

    def dimension_pipeline(self, *, campaign_id: str) -> dict[str, int]:
        """已入队但尚未完成的数量，按维度汇总（用于调度缺口）。"""
        rows = self.repo.conn.execute(
            "SELECT dimension, COUNT(*) AS n FROM engine_candidates "
            "WHERE campaign_id = ? AND state IN ('queued', 'processing', 'retryable_failed') "
            "GROUP BY dimension",
            (campaign_id,),
        ).fetchall()
        return {str(row["dimension"]): int(row["n"]) for row in rows}


def plan_to_row(plan: QueryPlan, campaign_id: str, platform: str) -> dict[str, str]:
    return {
        "campaign_id": campaign_id,
        "platform": platform,
        "dimension": plan.dimension,
        "keyword": plan.keyword,
        "combined_query": plan.combined_query,
    }
