"""批次规划：决定"下一批采什么"，不接触浏览器。

优先级：
1. 队列里已有候选（上次搜索留下的）：沿用其 combined_query，避免重复搜索；
2. 队列为空：按十维缺口调用 KeywordPlanner 选下一个未执行查询；
3. 关键词耗尽：返回 exhausted，由上层决定停止或扩充词库。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kato_engine.agent.contracts import BatchTask
from kato_engine.agent.scripts import search_url
from kato_engine.discovery.candidate_queue import CandidateQueue
from kato_engine.discovery.keyword_planner import KeywordPlanner, KeywordLibrary
from kato_engine.observability.logging import get_logger

_LOGGER = get_logger("kato.planner")


@dataclass
class BatchPlan:
    task: BatchTask | None
    reason: str | None
    remaining: dict[str, int]
    queue_candidates: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_dict() if self.task else None,
            "reason": self.reason,
            "remaining": self.remaining,
            "queue_candidates": self.queue_candidates,
        }


def remaining_for(repo, campaign_id: str, target_xhs: int, target_zhihu: int) -> dict[str, int]:
    counts = repo.campaign_article_counts(campaign_id)
    return {
        "xiaohongshu": max(target_xhs - counts.get("xiaohongshu", 0), 0),
        "zhihu": max(target_zhihu - counts.get("zhihu", 0), 0),
    }


def plan_batch(
    repo,
    library: KeywordLibrary,
    campaign_id: str,
    *,
    run_id: str,
    target_xiaohongshu: int,
    target_zhihu: int,
    platform: str | None = None,
    size: int = 4,
) -> BatchPlan:
    settings = repo.settings
    remaining = remaining_for(repo, campaign_id, target_xiaohongshu, target_zhihu)

    if platform is None:
        platform = "xiaohongshu" if remaining["xiaohongshu"] > 0 else "zhihu"
    if remaining.get(platform, 0) <= 0:
        return BatchPlan(None, f"target_reached:{platform}", remaining, 0)

    queue = CandidateQueue(repo)
    collected = set(repo.existing_urls(platform))
    # 已拒绝/已完成的候选也不要再打开：结果页重排会反复返回同一批卡片。
    terminal = repo.conn.execute(
        "SELECT canonical_url FROM engine_candidates WHERE campaign_id = ? AND platform = ? "
        "AND (state IN ('completed', 'rejected') "
        "OR (state = 'retryable_failed' AND attempts >= 2))",
        (campaign_id, platform),
    ).fetchall()
    collected.update(str(row[0]) for row in terminal)

    accepted = repo.dimension_article_counts(campaign_id)
    accepted = repo.dimension_article_counts(campaign_id)
    pipeline = queue.dimension_pipeline(campaign_id=campaign_id)
    planner = KeywordPlanner(
        library,
        executed_queries=repo.executed_queries(platform),
        accepted_by_dimension=accepted,
        pipeline_by_dimension=pipeline,
    )
    plan = planner.next_plan()
    if plan is None:
        return BatchPlan(None, f"keywords_exhausted:{platform}", remaining, 0)

    task = BatchTask(
        run_id=run_id,
        campaign_id=campaign_id,
        platform=platform,
        query=plan.combined_query,
        dimension=plan.dimension,
        keyword=plan.keyword,
        combined_query=plan.combined_query,
        search_url=search_url(platform, plan.combined_query),
        size=size,
        exclude_urls=sorted(collected)[:800],
    )
    return BatchPlan(task, None, remaining, 0)


def describe_plan(plan: BatchPlan) -> str:
    if plan.task is None:
        return f"无任务：{plan.reason}（剩余 {plan.remaining}）"
    return (
        f"{plan.task.platform} / {plan.task.combined_query} / "
        f"目标 {len(plan.task.targets)} 篇 / 剩余 {plan.remaining}"
    )
