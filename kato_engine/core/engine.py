"""连续 Campaign 执行循环。

流程（与 `docs/v6/V6_ARCHITECTURE.md` 第 4 节一致）：

    读取 Campaign → 检查配额 → 选主题与关键词 → 搜索 → 候选入队
    → 领取候选 → 真实 Chrome 打开详情 → 采集正文与评论
    → 校验入库 → 生成 Markdown → checkpoint → 下一条

关键性质：
- 不按"20 篇一批"停止，20 篇只是一致性核对节点；
- 普通错误记录后继续；登录/验证码/限流立即暂停该平台，等待人工处理；
- 浏览器断开时由 BrowserManager 重建会话，候选状态保存在数据库里，不丢进度。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from kato_engine.browser.errors import (
    AuthRequiredError,
    EngineError,
    IrrelevantContentError,
    RateLimitedError,
    VerificationRequiredError,
)
from kato_engine.browser.manager import BrowserManager
from kato_engine.browser.navigation import strip_query
from kato_engine.collection.article import collect_article
from kato_engine.core.lifecycle import ArticleService
from kato_engine.discovery.candidate_queue import CandidateQueue
from kato_engine.discovery.deduplication import canonical_url
from kato_engine.discovery.keyword_planner import KeywordPlanner, load_keyword_library
from kato_engine.observability.logging import get_logger
from kato_engine.platforms import get_adapter
from kato_engine.platforms.base import SearchHit
from kato_engine.storage.checkpoints import write_checkpoint
from kato_engine.storage.repository import EngineRepository

_LOGGER = get_logger("kato.engine")

PLATFORMS = ("xiaohongshu", "zhihu")
HUMAN_ERRORS = (AuthRequiredError, VerificationRequiredError, RateLimitedError)
CHECKPOINT_EVERY = 20
MAX_EMPTY_SEARCHES = 6


@dataclass
class EngineOptions:
    campaign_id: str
    targets: dict[str, int]
    max_articles: int | None = None
    max_consecutive_failures: int = 15
    search_limit: int = 20
    require_relevance: bool = True
    stop_on_empty: bool = True
    platform_order: tuple[str, ...] = PLATFORMS
    on_progress: Callable[[dict[str, Any]], None] | None = None


@dataclass
class EngineSummary:
    engine_run_id: str
    campaign_id: str
    stop_reason: str
    articles_added: int = 0
    comments_added: int = 0
    per_platform: dict[str, dict[str, Any]] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_path: str | None = None
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_run_id": self.engine_run_id,
            "campaign_id": self.campaign_id,
            "stop_reason": self.stop_reason,
            "articles_added": self.articles_added,
            "comments_added": self.comments_added,
            "per_platform": self.per_platform,
            "failures": self.failures[:30],
            "failure_count": len(self.failures),
            "checkpoint_path": self.checkpoint_path,
            "duration_s": round(self.duration_s, 1),
        }


class CampaignEngine:
    def __init__(
        self,
        settings,
        repo: EngineRepository,
        manager: BrowserManager,
        library=None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.manager = manager
        self.library = library or load_keyword_library(settings.keyword_library_path)
        self.queue = CandidateQueue(repo)
        self.service = ArticleService(repo)
        self._contexts: dict[str, dict[str, Any]] = {}
        self._pages: dict[str, Any] = {}
        self._paused: dict[str, str] = {}
        self._empty_searches: dict[str, int] = {}

    # -- 入口 -------------------------------------------------------------
    def run(self, options: EngineOptions) -> EngineSummary:
        started = time.monotonic()
        engine_run_id = self.repo.start_engine_run(
            options.campaign_id,
            target_xiaohongshu=int(options.targets.get("xiaohongshu", 0)),
            target_zhihu=int(options.targets.get("zhihu", 0)),
            profile_dir=str(self.settings.profile_dir),
        )
        summary = EngineSummary(
            engine_run_id=engine_run_id,
            campaign_id=options.campaign_id,
            stop_reason="running",
        )
        recovered = self.repo.recover_expired_leases(options.campaign_id)
        if recovered:
            _LOGGER.warning("回收过期租约 %s 条", recovered)

        session = self.manager.ensure()
        _LOGGER.info("引擎启动：%s", engine_run_id)
        consecutive_failures = 0

        try:
            while True:
                if options.max_articles is not None and summary.articles_added >= options.max_articles:
                    summary.stop_reason = "max_articles_reached"
                    break
                active = [p for p in options.platform_order if p not in self._paused]
                if not active:
                    summary.stop_reason = "all_platforms_paused"
                    break
                progressed = False
                for platform in active:
                    remaining = self._remaining(platform, options)
                    if remaining <= 0:
                        continue
                    try:
                        outcome = self._process_one(platform, options, summary)
                    except EngineError as exc:
                        _LOGGER.error("平台 %s 处理异常：%s", platform, exc.message)
                        summary.failures.append(
                            {
                                "platform": platform,
                                "error_type": exc.error_type,
                                "message": exc.message[:200],
                            }
                        )
                        if exc.needs_human:
                            self._paused[platform] = exc.error_type
                            outcome = "paused"
                        else:
                            outcome = "failed"
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.exception("平台 %s 未捕获异常", platform)
                        summary.failures.append(
                            {
                                "platform": platform,
                                "error_type": "unclassified",
                                "message": f"{type(exc).__name__}: {exc}"[:200],
                            }
                        )
                        outcome = "failed" 
                    if outcome in {"accepted", "rejected", "failed", "resumed"}:
                        progressed = True
                    if outcome == "accepted" or outcome == "resumed":
                        consecutive_failures = 0
                    elif outcome in {"failed", "rejected"}:
                        consecutive_failures += 1
                    if outcome == "paused":
                        last = summary.failures[-1]["error_type"] if summary.failures else "blocked"
                        self._paused[platform] = last
                    if options.max_articles is not None and summary.articles_added >= options.max_articles:
                        break
                if consecutive_failures >= options.max_consecutive_failures:
                    summary.stop_reason = f"consecutive_failures_{consecutive_failures}"
                    break
                if not progressed:
                    if all(
                        self._remaining(p, options) <= 0 for p in options.platform_order
                    ):
                        summary.stop_reason = "targets_reached"
                    elif options.stop_on_empty:
                        summary.stop_reason = "no_candidates_left"
                    else:
                        summary.stop_reason = "no_progress"
                    break
                if summary.articles_added and summary.articles_added % CHECKPOINT_EVERY == 0:
                    self._write_checkpoint(summary, options)
        except KeyboardInterrupt:
            summary.stop_reason = "interrupted"
        finally:
            summary.duration_s = time.monotonic() - started
            self._write_checkpoint(summary, options)
            self.repo.finish_engine_run(
                engine_run_id,
                stop_reason=summary.stop_reason,
                articles_added=summary.articles_added,
                comments_added=summary.comments_added,
            )
            self.repo.refresh_campaign_total(options.campaign_id)
            _LOGGER.info(
                "引擎结束：%s 新增=%s 原因=%s",
                engine_run_id,
                summary.articles_added,
                summary.stop_reason,
            )
        return summary

    # -- 单步 -------------------------------------------------------------
    def _process_one(
        self, platform: str, options: EngineOptions, summary: EngineSummary
    ) -> str:
        stats = summary.per_platform.setdefault(
            platform, {"searches": 0, "claimed": 0, "accepted": 0, "rejected": 0, "failed": 0}
        )
        row = self.queue.claim(
            campaign_id=options.campaign_id,
            platform=platform,
            engine_run_id=summary.engine_run_id,
        )
        if row is None:
            return self._discover(platform, options, summary, stats)

        stats["claimed"] += 1
        candidate = dict(row)
        started = time.monotonic()
        page_before = self._page(platform)
        collected = None
        try:
            hit = self._resolve_hit(platform, candidate, options)
            collected = collect_article(
                self._page(platform),
                get_adapter(platform),
                hit,
                limit=self.settings.comment_limit,
                require_relevance=options.require_relevance,
            )
            persist_started = time.monotonic()
            result = self.service.persist(
                collected,
                campaign_id=options.campaign_id,
                candidate_id=str(candidate["candidate_id"]),
            )
            persist_ms = int((time.monotonic() - persist_started) * 1000)
            metrics = {**collected.metrics, "persist_ms": persist_ms}
            self._record_metrics(summary.engine_run_id, candidate, platform, metrics, "ok")
            summary.articles_added += 1
            summary.comments_added += result.comments_inserted
            stats["accepted"] += 1
            if options.on_progress:
                options.on_progress(
                    {
                        "platform": platform,
                        "candidate_id": candidate["candidate_id"],
                        "item_id": result.item_id,
                        "title": collected.article.title[:60],
                        "top_level": collected.selection.collected_top_level,
                        "replies": collected.selection.collected_replies,
                        "coverage": collected.selection.coverage_status,
                    }
                )
            time.sleep(self.settings.pause_between_articles_ms / 1000)
            return "accepted"
        except IrrelevantContentError as exc:
            self.repo.mark_rejected(
                str(candidate["candidate_id"]), error_type=exc.error_type, reason=exc.message
            )
            stats["rejected"] += 1
            self._record_failure(summary, candidate, platform, exc)
            return "rejected"
        except EngineError as exc:
            stats["failed"] += 1
            self._record_failure(summary, candidate, platform, exc)
            if exc.needs_human:
                self.repo.mark_blocked(
                    str(candidate["candidate_id"]), error_type=exc.error_type, reason=exc.message
                )
                _LOGGER.error("平台 %s 需要人工处理：%s", platform, exc.message)
                return "paused"
            attempts = int(candidate.get("attempts") or 1)
            if exc.retryable and attempts < self.settings.max_attempts:
                self.repo.mark_retryable(
                    str(candidate["candidate_id"]), error_type=exc.error_type, reason=exc.message
                )
            else:
                self.repo.mark_rejected(
                    str(candidate["candidate_id"]), error_type=exc.error_type, reason=exc.message
                )
            return "failed"
        except Exception as exc:  # noqa: BLE001 - 未分类异常不能拖垮整轮
            stats["failed"] += 1
            self._record_failure(
                summary, candidate, platform, EngineError(f"{type(exc).__name__}: {exc}")
            )
            self.repo.mark_retryable(
                str(candidate["candidate_id"]),
                error_type="unclassified",
                reason=f"{type(exc).__name__}: {exc}",
            )
            return "failed"
        finally:
            # 详情页在新标签页打开时关掉它；同标签页导航后尝试回到搜索结果页，
            # 这样同一查询下的后续候选不必重新搜索（结果集会轮换）。
            try:
                if collected is not None and collected.detail_page is not page_before:
                    collected.detail_page.close()
                elif page_before.url and "search" not in page_before.url:
                    if not self._restore_search_page(platform):
                        self._contexts.pop(platform, None)
            except Exception:  # noqa: BLE001
                self._contexts.pop(platform, None)
            elapsed = int((time.monotonic() - started) * 1000)
            _LOGGER.info(
                "候选处理结束：%s 用时 %sms", candidate["candidate_id"], elapsed
            )

    def _discover(
        self,
        platform: str,
        options: EngineOptions,
        summary: EngineSummary,
        stats: dict[str, int],
    ) -> str:
        """队列为空时按缺口执行一次搜索。返回 resumed/paused/failed。"""
        plan = self._planner(platform, options).next_plan()
        if plan is None:
            _LOGGER.warning("平台 %s 关键词已耗尽", platform)
            return "failed"

        adapter = get_adapter(platform)
        page = self._page(platform)
        started = time.monotonic()
        try:
            outcome = adapter.search(page, plan.combined_query, limit=options.search_limit)
        except EngineError as exc:
            self._record_search_failure(platform, plan, summary, exc)
            if exc.needs_human:
                self._paused[platform] = exc.error_type
                return "paused"
            self._empty_searches[platform] = self._empty_searches.get(platform, 0) + 1
            return "failed"

        added = self.queue.add(
            campaign_id=options.campaign_id,
            platform=platform,
            dimension=plan.dimension,
            keyword=plan.keyword,
            combined_query=plan.combined_query,
            hits=outcome.hits,
            engine_run_id=summary.engine_run_id,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        self._contexts[platform] = {"query": plan.combined_query, "outcome": outcome, "page": page}
        self.repo.record_query_run(
            campaign_id=options.campaign_id,
            platform=platform,
            dimension=plan.dimension,
            keyword=plan.keyword,
            combined_query=plan.combined_query,
            candidates_found=outcome.raw_count,
            duplicates=added["duplicates"],
            opened_details=0,
            accepted=0,
            duration_ms=duration_ms,
            failure_reason=None if outcome.hits else "no_hits",
            engine_run_id=summary.engine_run_id,
        )
        self.repo.record_metric(
            phase="search",
            duration_ms=duration_ms,
            engine_run_id=summary.engine_run_id,
            platform=platform,
            outcome="ok",
            detail={
                "query": plan.combined_query,
                "dimension": plan.dimension,
                "raw": outcome.raw_count,
                **added,
            },
        )
        stats["searches"] += 1
        _LOGGER.info(
            "搜索完成：%s / %s 原始=%s 新入队=%s 重复=%s",
            platform,
            plan.combined_query,
            outcome.raw_count,
            added["inserted"],
            added["duplicates"],
        )
        if added["inserted"] == 0:
            self._empty_searches[platform] = self._empty_searches.get(platform, 0) + 1
            if self._empty_searches[platform] >= MAX_EMPTY_SEARCHES:
                self._paused[platform] = "discovery_exhausted"
                _LOGGER.warning(
                    "平台 %s 连续 %s 次搜索无新候选，暂停该平台",
                    platform,
                    self._empty_searches[platform],
                )
        else:
            self._empty_searches[platform] = 0
        time.sleep(self.settings.pause_between_queries_ms / 1000)
        return "resumed" if added["inserted"] else "failed"

    # -- 辅助 -------------------------------------------------------------
    def _resolve_hit(
        self, platform: str, candidate: dict[str, Any], options: EngineOptions
    ) -> SearchHit:
        """为候选构造可点击入口：必要时重新打开该候选所属的搜索页。"""
        url = str(candidate["canonical_url"])
        query = str(candidate.get("combined_query") or "")
        adapter = get_adapter(platform)
        page = self._page(platform)

        context = self._contexts.get(platform)
        if not context or context.get("query") != query or context["page"].is_closed():
            outcome = adapter.search(page, query, limit=max(options.search_limit * 3, 60))
            context = {"query": query, "outcome": outcome, "page": page}
            self._contexts[platform] = context

        for hit in context["outcome"].hits:
            if hit.canonical_url == url:
                return hit

        if platform == "xiaohongshu":
            # 当前查询结果里没有这条候选：仍可按 note_id 定位卡片；
            # 若这次搜索返回过它的 href，则优先用 href 导航（含一次性 token）。
            note_id = url.rstrip("/").rsplit("/", 1)[-1]
            for hit in context["outcome"].hits:
                if hit.canonical_url == url:
                    return hit
            return SearchHit(
                title=str(candidate.get("title_hint") or ""),
                canonical_url=url,
                extra={"note_id": note_id},
            )
        raise EngineError(
            f"搜索结果中找不到候选：{url}",
            detail={"query": query},
        )

    def _page(self, platform: str):
        """每个平台使用独立标签页：避免两个平台的搜索页互相覆盖。"""
        page = self._pages.get(platform)
        if page is None or page.is_closed():
            page = self.manager.ensure().new_page()
            self._pages[platform] = page
            self._contexts.pop(platform, None)
        return page

    def _restore_search_page(self, platform: str) -> bool:
        """从详情页返回搜索结果页，保留同一查询的候选上下文。"""
        context = self._contexts.get(platform)
        if not context:
            return False
        page = context["page"]
        try:
            page.go_back(wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_timeout(1_500)
            selector = "section.note-item" if platform == "xiaohongshu" else ".SearchResult-Card"
            return page.locator(selector).count() > 0 and "search" in page.url
        except Exception:  # noqa: BLE001
            return False

    def _planner(self, platform: str, options: EngineOptions) -> KeywordPlanner:
        accepted = self.repo.dimension_article_counts(options.campaign_id)
        pipeline = self.queue.dimension_pipeline(campaign_id=options.campaign_id)
        return KeywordPlanner(
            self.library,
            executed_queries=self.repo.executed_queries(platform),
            accepted_by_dimension=accepted,
            pipeline_by_dimension=pipeline,
        )

    def _remaining(self, platform: str, options: EngineOptions) -> int:
        target = int(options.targets.get(platform, 0))
        if target <= 0:
            return 0
        current = self.repo.campaign_article_counts(options.campaign_id).get(platform, 0)
        return target - current

    def _record_failure(
        self,
        summary: EngineSummary,
        candidate: dict[str, Any],
        platform: str,
        exc: EngineError,
    ) -> None:
        summary.failures.append(
            {
                "platform": platform,
                "candidate_id": candidate["candidate_id"],
                "url": candidate["canonical_url"],
                "error_type": exc.error_type,
                "message": exc.message[:200],
            }
        )
        self.repo.record_metric(
            phase="article",
            duration_ms=0,
            engine_run_id=summary.engine_run_id,
            candidate_id=str(candidate["candidate_id"]),
            platform=platform,
            outcome="error",
            error_type=exc.error_type,
            detail={"message": exc.message[:300]},
        )

    def _record_search_failure(
        self, platform: str, plan, summary: EngineSummary, exc: EngineError
    ) -> None:  # noqa: ANN001
        summary.failures.append(
            {
                "platform": platform,
                "query": plan.combined_query,
                "error_type": exc.error_type,
                "message": exc.message[:200],
            }
        )
        self.repo.record_metric(            phase="search",
            duration_ms=0,
            engine_run_id=summary.engine_run_id,
            platform=platform,
            outcome="error",
            error_type=exc.error_type,
            detail={"query": plan.combined_query},
        )
        self.repo.record_query_run(
            campaign_id=summary.campaign_id,
            platform=platform,
            dimension=plan.dimension,
            keyword=plan.keyword,
            combined_query=plan.combined_query,
            candidates_found=0,
            duplicates=0,
            opened_details=0,
            accepted=0,
            duration_ms=0,
            failure_reason=exc.error_type,
            engine_run_id=summary.engine_run_id,
        )

    def _record_metrics(
        self,
        engine_run_id: str,
        candidate: dict[str, Any],
        platform: str,
        metrics: dict[str, int],
        outcome: str,
    ) -> None:
        for phase, duration in metrics.items():
            if phase in {"collected_top_level", "collected_replies"}:
                continue
            self.repo.record_metric(
                phase=phase,
                duration_ms=int(duration),
                engine_run_id=engine_run_id,
                candidate_id=str(candidate["candidate_id"]),
                platform=platform,
                outcome=outcome,
            )

    def _write_checkpoint(self, summary: EngineSummary, options: EngineOptions) -> None:
        state = {
            "stop_reason": summary.stop_reason,
            "articles_added": summary.articles_added,
            "comments_added": summary.comments_added,
            "targets": options.targets,
            "campaign_counts": self.repo.campaign_article_counts(options.campaign_id),
            "queue": self.queue.stats(campaign_id=options.campaign_id),
            "paused": self._paused,
            "per_platform": summary.per_platform,
        }
        try:
            path = write_checkpoint(
                self.settings, summary.engine_run_id, options.campaign_id, state
            )
            summary.checkpoint_path = str(path)
        except OSError as exc:  # noqa: BLE001
            _LOGGER.error("写 checkpoint 失败：%s", exc)
