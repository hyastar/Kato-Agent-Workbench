"""批次入库：把 ZCode 内置浏览器返回的结构化结果写入 SQLite 与 Markdown。

流程：
1. 记录关键词执行（原始数、去重数、实际打开数、采纳数、耗时）；
2. 搜索结果全部入队（保留未处理候选，供下一批继续）；
3. 逐篇：认领候选 → 校验相关性 → 分类 → 入库 → 评论树 → Markdown → 候选 completed；
4. 失败按错误类型落到 retryable_failed / rejected / blocked，并注明原因。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from kato_engine.agent.contracts import ArticleExtraction, BatchResult, BatchTask
from kato_engine.collection.article import Collected, build_summary, ensure_relevant
from kato_engine.collection.classification import classify
from kato_engine.collection.comments import select_comment_nodes
from kato_engine.collection.models import ArticleData, CommentBundle
from kato_engine.collection.thread_tree import (
    clean_date_text,
    nodes_from_indentation,
    nodes_from_nested,
)
from kato_engine.core.lifecycle import ArticleService
from kato_engine.observability.logging import get_logger
from kato_engine.storage.repository import EngineRepository, candidate_id_for

_LOGGER = get_logger("kato.ingest")

PUBLISHED_DATETIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")
PUBLISHED_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

NON_RETRYABLE_ERRORS = {"empty_content", "irrelevant", "invalid_url"}


@dataclass
class IngestSummary:
    platform: str
    query: str
    search_raw: int = 0
    new_candidates: int = 0
    duplicates: int = 0
    opened: int = 0
    accepted: int = 0
    rejected: int = 0
    failed: int = 0
    blocked: bool = False
    items: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "query": self.query,
            "search_raw": self.search_raw,
            "new_candidates": self.new_candidates,
            "duplicates": self.duplicates,
            "opened": self.opened,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "failed": self.failed,
            "blocked": self.blocked,
            "items": self.items,
            "notes": self.notes,
        }


def published_iso(text: str | None) -> str | None:
    if not text:
        return None
    match = PUBLISHED_DATETIME_RE.search(text)
    if match:
        return f"{match.group(1)}T{match.group(2)}:00"
    match = PUBLISHED_DATE_RE.search(text)
    return match.group(1) if match else None


def build_collected(platform: str, extraction: ArticleExtraction, *, limit: int = 50) -> Collected:
    assert extraction.canonical_url
    nodes = (
        nodes_from_nested(extraction.comments_nested)
        if platform == "xiaohongshu"
        else nodes_from_indentation(extraction.comments_flat)
    )
    bundle = CommentBundle(nodes=nodes, displayed_total=extraction.displayed_total)
    selection = select_comment_nodes(bundle, limit=limit)
    published_text = clean_date_text(extraction.published_text)
    article = ArticleData(
        platform=platform,
        canonical_url=extraction.canonical_url,
        title=extraction.title,
        body_text=extraction.body,
        published_text=published_text,
        published_at=published_iso(published_text),
    )
    classification = classify(extraction.title, extraction.body)
    return Collected(
        article=article,
        canonical_url=extraction.canonical_url,
        selection=selection,
        classification=classification,
        metrics={},
    )


def ingest_batch(
    repo: EngineRepository,
    service: ArticleService,
    result: BatchResult,
    task: BatchTask,
    *,
    engine_run_id: str,
    comment_limit: int = 50,
    relevance_threshold: int = 2,
) -> IngestSummary:
    summary = IngestSummary(platform=result.platform, query=result.query)
    summary.search_raw = int(result.search.get("raw") or 0)
    summary.notes.extend(result.notes)

    # 1) 搜索结果整体入队（未处理的候选留待下一批）
    hits = result.search_hits()
    rows = [
        {
            "campaign_id": task.campaign_id,
            "platform": result.platform,
            "canonical_url": canonical,
            "title_hint": title,
            "dimension": task.dimension,
            "keyword": task.keyword,
            "combined_query": task.combined_query,
        }
        for title, canonical, _index in hits
    ]
    enqueued = repo.enqueue_candidates(rows, engine_run_id=engine_run_id)
    summary.new_candidates = enqueued.inserted
    summary.duplicates = enqueued.duplicates

    # 2) 逐篇入库
    for extraction in result.articles:
        item = {"url": extraction.canonical_url, "ok": False}
        candidate_id: str | None = None
        try:
            if not extraction.ok or not extraction.canonical_url:
                item.update(
                    {
                        "error_type": extraction.error_type or "extraction_failed",
                        "message": extraction.message,
                    }
                )
                summary.failed += 1
                if extraction.error_type == "login_required":
                    summary.blocked = True
                summary.items.append(item)
                continue

            candidate_id = candidate_id_for(result.platform, extraction.canonical_url)
            state = repo.claim_candidate(candidate_id, attempts_max=repo.settings.max_attempts)
            if state == "completed":
                item.update({"skipped": "already_completed"})
                summary.items.append(item)
                continue

            collected = build_collected(
                result.platform, extraction, limit=comment_limit
            )
            relevant, score = ensure_relevant(
                collected.classification, threshold=relevance_threshold
            )
            if not relevant:
                repo.mark_rejected(
                    candidate_id,
                    error_type="irrelevant",
                    reason=f"内容与就业生态无关（最高分 {score}）",
                )
                summary.rejected += 1
                item.update({"rejected": "irrelevant", "score": score})
                summary.items.append(item)
                continue
            if collected.article.body_length < 20:
                repo.mark_rejected(
                    candidate_id,
                    error_type="empty_content",
                    reason=f"正文过短：{collected.article.body_length} 字",
                )
                summary.rejected += 1
                item.update({"rejected": "empty_content"})
                summary.items.append(item)
                continue

            persisted = service.persist(
                collected, campaign_id=task.campaign_id, candidate_id=candidate_id
            )
            summary.accepted += 1
            item.update(
                {
                    "ok": True,
                    "item_id": persisted.item_id,
                    "title": extraction.title[:60],
                    "top_level": collected.selection.collected_top_level,
                    "replies": collected.selection.collected_replies,
                    "coverage": collected.selection.coverage_status,
                    "topic": collected.classification.employment_topic,
                    "new": persisted.created,
                }
            )
        except Exception as exc:  # noqa: BLE001 - 单篇异常不影响整批
            summary.failed += 1
            item.update({"error_type": "ingest_error", "message": f"{type(exc).__name__}: {exc}"[:200]})
            _LOGGER.exception("入库失败：%s", extraction.canonical_url)
            if candidate_id:
                try:
                    repo.mark_retryable(
                        candidate_id,
                        error_type="ingest_error",
                        reason=f"{type(exc).__name__}: {exc}"[:300],
                    )
                except Exception:  # noqa: BLE001
                    pass
        summary.items.append(item)

    summary.opened = len(result.articles)

    # 3) 记录关键词执行
    repo.record_query_run(
        campaign_id=task.campaign_id,
        platform=result.platform,
        dimension=task.dimension,
        keyword=task.keyword,
        combined_query=task.combined_query,
        candidates_found=summary.search_raw or len(hits),
        duplicates=summary.duplicates,
        opened_details=summary.opened,
        accepted=summary.accepted,
        duration_ms=0,
        failure_reason=(
            "login_required" if summary.blocked else (None if summary.accepted else "no_accept")
        ),
        engine_run_id=engine_run_id,
    )
    return summary
