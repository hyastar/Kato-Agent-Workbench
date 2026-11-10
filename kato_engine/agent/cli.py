"""ZCode Browser 任务 CLI（V6.1）。

ZCode Agent 与 Python 的协作方式：

    python -m kato_engine.agent.cli session-start --add-xhs 113
    python -m kato_engine.agent.cli next-batch --run <run_id> --size 4
      → 得到 task.json（查询、搜索 URL、脚本、目标候选）
    [ZCode 用内置浏览器执行 workflow_js，写出 batch.json]
    python -m kato_engine.agent.cli submit-batch --run <run_id> --task <task.json> --file <batch.json>
      → 入库、更新候选状态、返回剩余量

Python 不启动浏览器、不连接 CDP、不假设拥有任何浏览器对象。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from kato_engine.agent.contracts import BatchResult, BatchTask
from kato_engine.agent.ingest import ingest_batch
from kato_engine.agent.planner import BatchPlan, describe_plan, plan_batch, remaining_for
from kato_engine.config.settings import load_settings
from kato_engine.core.lifecycle import ArticleService
from kato_engine.discovery.keyword_planner import load_keyword_library
from kato_engine.observability.logging import configure_logging, get_logger
from kato_engine.storage.repository import EngineRepository

_LOGGER = get_logger("kato.agent")


def _print(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _run_dir(settings, run_id: str) -> Path:
    return settings.runs_dir / run_id


def _next_task_path(settings, run_id: str) -> Path:
    directory = _run_dir(settings, run_id) / "tasks"
    directory.mkdir(parents=True, exist_ok=True)
    existing = sorted(directory.glob("task-*.json"))
    return directory / f"task-{len(existing) + 1:03d}.json"


def _engine_targets(repo, engine_run_id: str) -> tuple[int, int]:
    row = repo.get_engine_run(engine_run_id)
    if row is None:
        raise SystemExit(f"engine_run 不存在：{engine_run_id}")
    return int(row["target_xiaohongshu"]), int(row["target_zhihu"])


def cmd_session_start(args: argparse.Namespace) -> int:
    settings = load_settings()
    library = load_keyword_library(settings.keyword_library_path)
    campaign_id = args.campaign or library.campaign
    repo, schema = EngineRepository.open(settings)
    try:
        campaign = repo.ensure_campaign(campaign_id)
        current = repo.campaign_article_counts(campaign_id)
        targets = {
            "xiaohongshu": current.get("xiaohongshu", 0) + args.add_xhs,
            "zhihu": current.get("zhihu", 0) + args.add_zhihu,
        }
        run_id = repo.start_engine_run(
            campaign_id,
            target_xiaohongshu=targets["xiaohongshu"],
            target_zhihu=targets["zhihu"],
            profile_dir="zcode-builtin-browser",
            notes="V6.1 ZCode Browser Use",
        )
        remaining = remaining_for(repo, campaign_id, targets["xiaohongshu"], targets["zhihu"])
        payload = {
            "run_id": run_id,
            "campaign_id": campaign_id,
            "campaign_target_total": int(campaign["target_total"]),
            "current": current,
            "targets": targets,
            "remaining": remaining,
            "schema_version": schema.to_version,
            "batch_contract": {
                "task": "由 next-batch 生成",
                "batch": "ZCode 执行 workflow_js 后写入同一 run 目录",
            },
        }
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_next_batch(args: argparse.Namespace) -> int:
    settings = load_settings()
    library = load_keyword_library(settings.keyword_library_path)
    repo, _ = EngineRepository.open(settings)
    try:
        run = repo.get_engine_run(args.run)
        if run is None:
            _print({"error": f"engine_run 不存在：{args.run}"})
            return 2
        campaign_id = str(run["campaign_id"])
        target_xhs, target_zhihu = _engine_targets(repo, args.run)
        reset = repo.reset_processing(campaign_id)
        if reset:
            _LOGGER.warning("回收上一批遗留的 processing 候选 %s 条", reset)
        plan: BatchPlan = plan_batch(
            repo,
            library,
            campaign_id,
            run_id=args.run,
            target_xiaohongshu=target_xhs,
            target_zhihu=target_zhihu,
            platform=args.platform,
            size=args.size,
            dimension=args.dimension,
        )
        if plan.task is None:
            payload = {
                "run_id": args.run,
                "action": "stop",
                "reason": plan.reason,
                "remaining": plan.remaining,
            }
            _print(payload)
            return 0

        # 认领本批目标，避免重复打开同一篇
        claimed = []
        for target in plan.task.targets:
            if not target.candidate_id:
                continue
            state = repo.claim_candidate(
                target.candidate_id, attempts_max=settings.max_attempts
            )
            if state == "processing":
                claimed.append(target.candidate_id)
            else:
                target.candidate_id = None
        plan.task.targets = [
            target
            for target in plan.task.targets
            if target.candidate_id or not target.canonical_url
        ]

        task_path = plan.task.write(_next_task_path(settings, args.run))
        payload = {
            "run_id": args.run,
            "action": "batch",
            "desc": describe_plan(plan),
            "claimed": len(claimed),
            "task": plan.task.to_dict(),
            "task_path": str(task_path),
            "remaining": plan.remaining,
        }
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_submit_batch(args: argparse.Namespace) -> int:
    settings = load_settings()
    repo, _ = EngineRepository.open(settings)
    try:
        task_payload = json.loads(Path(args.task).read_text(encoding="utf-8"))
        task = BatchTask(
            run_id=str(task_payload.get("run_id") or args.run),
            campaign_id=str(task_payload["campaign_id"]),
            platform=str(task_payload["platform"]),
            query=str(task_payload["query"]),
            dimension=str(task_payload.get("dimension") or "unknown"),
            keyword=str(task_payload.get("keyword") or ""),
            combined_query=str(task_payload.get("combined_query") or task_payload["query"]),
            search_url=str(task_payload.get("search_url") or ""),
            size=int(task_payload.get("size") or 0),
            targets=[],
        )
        result = BatchResult.load(
            args.file,
            platform=task.platform,
            run_id=args.run,
            query=task.query,
        )
        service = ArticleService(repo)
        summary = ingest_batch(
            repo,
            service,
            result,
            task,
            engine_run_id=args.run,
            comment_limit=settings.comment_limit,
            relevance_threshold=args.relevance_threshold,
        )
        if summary.blocked:
            _LOGGER.error(
                "平台 %s 需要人工登录/验证，本批已停止；请在 ZCode 内置浏览器完成后再继续",
                task.platform,
            )
        target_xhs, target_zhihu = _engine_targets(repo, args.run)
        payload = {
            "run_id": args.run,
            "action": "ingested",
            "summary": summary.to_dict(),
            "remaining": remaining_for(
                repo, task.campaign_id, target_xhs, target_zhihu
            ),
            "campaign": repo.campaign_article_counts(task.campaign_id),
            "queue": repo.candidate_state_counts(
                campaign_id=task.campaign_id, platform=task.platform
            ),
        }
    finally:
        repo.close()
    _print(payload)
    return 0 if not summary.blocked else 3


def cmd_dynamic_scan(args: argparse.Namespace) -> int:
    """从最近文章标题/摘要中提取动态关键词候选（不自动进入查询队列）。"""
    from kato_engine.agent.dynamic_keywords import extract_candidates

    settings = load_settings()
    library = load_keyword_library(settings.keyword_library_path)
    repo, _ = EngineRepository.open(settings)
    try:
        campaign_id = args.campaign or library.campaign
        rows = repo.conn.execute(
            "SELECT item_id, title, summary FROM research_items "
            "WHERE campaign_id = ? AND platform = ? ORDER BY collected_at DESC LIMIT ?",
            (campaign_id, args.platform, args.scan_items),
        ).fetchall()
        texts = [
            (str(row["item_id"]), str(row["title"] or "") + " " + str(row["summary"] or ""))
            for row in rows
        ]
        existing = {kw for dim in library.dimensions for kw in dim.keywords}
        existing.update(repo.executed_queries(args.platform))
        candidates = extract_candidates(texts, existing=existing, limit=args.limit)
        now = __import__("scripts.db", fromlist=["db"]).utc_now()
        with repo.conn:
            for item in candidates:
                repo.conn.execute(
                    "INSERT INTO engine_dynamic_keywords (keyword, dimension, source_platform, "
                    "occurrences, status, sample_item_id, first_seen_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'candidate', ?, ?, ?) "
                    "ON CONFLICT(keyword, source_platform) DO UPDATE SET "
                    "occurrences = excluded.occurrences, sample_item_id = excluded.sample_item_id, "
                    "updated_at = excluded.updated_at",
                    (
                        item.keyword,
                        args.dimension,
                        args.platform,
                        item.occurrences,
                        item.sample_item_id,
                        now,
                        now,
                    ),
                )
        payload = {
            "campaign_id": campaign_id,
            "platform": args.platform,
            "scanned_items": len(rows),
            "candidates": [
                {"keyword": item.keyword, "occurrences": item.occurrences} for item in candidates
            ],
            "note": "候选不会自动进入查询队列，需 dynamic-approve 批准",
        }
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_dynamic_list(args: argparse.Namespace) -> int:
    settings = load_settings()
    repo, _ = EngineRepository.open(settings)
    try:
        rows = repo.conn.execute(
            "SELECT keyword, dimension, source_platform, occurrences, status, updated_at "
            "FROM engine_dynamic_keywords WHERE status = ? ORDER BY occurrences DESC LIMIT ?",
            (args.status, args.limit),
        ).fetchall()
        payload = {"status": args.status, "items": [dict(row) for row in rows]}
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_dynamic_set_status(args: argparse.Namespace) -> int:
    settings = load_settings()
    repo, _ = EngineRepository.open(settings)
    try:
        with repo.conn:
            cursor = repo.conn.execute(
                "UPDATE engine_dynamic_keywords SET status = ?, updated_at = ? WHERE keyword = ?",
                (args.status, __import__("scripts.db", fromlist=["db"]).utc_now(), args.keyword),
            )
        payload = {"keyword": args.keyword, "status": args.status, "updated": cursor.rowcount}
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    settings = load_settings()
    repo, _ = EngineRepository.open(settings)
    try:
        run = repo.get_engine_run(args.run)
        if run is None:
            _print({"error": f"engine_run 不存在：{args.run}"})
            return 2
        campaign_id = str(run["campaign_id"])
        counts = repo.campaign_article_counts(campaign_id)
        accepted = int(
            repo.conn.execute(
                "SELECT COUNT(*) FROM engine_candidates WHERE engine_run_id = ? "
                "AND state IN ('accepted', 'completed')",
                (args.run,),
            ).fetchone()[0]
        )
        started_at = str(run["started_at"] or "")
        comments_added = int(
            repo.conn.execute(
                "SELECT COUNT(*) FROM research_comments WHERE collected_at >= ?",
                (started_at,),
            ).fetchone()[0]
        )
        repo.finish_engine_run(
            args.run,
            stop_reason=args.reason,
            articles_added=accepted,
            comments_added=comments_added,
        )
        payload = {
            "run_id": args.run,
            "stop_reason": args.reason,
            "campaign": counts,
            "total": sum(counts.values()),
        }
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = load_settings()
    repo, _ = EngineRepository.open(settings)
    try:
        run = repo.get_engine_run(args.run) if args.run else None
        campaign_id = (
            str(run["campaign_id"])
            if run is not None
            else (args.campaign or load_keyword_library(settings.keyword_library_path).campaign)
        )
        counts = repo.campaign_article_counts(campaign_id)
        payload = {
            "run_id": args.run,
            "campaign_id": campaign_id,
            "articles": counts,
            "total": sum(counts.values()),
            "queue": repo.candidate_state_counts(campaign_id=campaign_id),
            "recent_queries": [
                dict(row)
                for row in repo.conn.execute(
                    "SELECT platform, combined_query, candidates_found, accepted, failure_reason, executed_at "
                    "FROM engine_query_runs WHERE campaign_id = ? ORDER BY executed_at DESC LIMIT 8",
                    (campaign_id,),
                ).fetchall()
            ],
        }
        if run is not None:
            payload["targets"] = {
                "xiaohongshu": int(run["target_xiaohongshu"]),
                "zhihu": int(run["target_zhihu"]),
            }
            payload["remaining"] = remaining_for(
                repo, campaign_id, int(run["target_xiaohongshu"]), int(run["target_zhihu"])
            )
    finally:
        repo.close()
    _print(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kato-agent", description="V6.1 ZCode Browser 任务接口")
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("session-start", help="创建引擎运行并确定目标")
    start.add_argument("--campaign")
    start.add_argument("--add-xhs", type=int, default=0)
    start.add_argument("--add-zhihu", type=int, default=0)
    start.set_defaults(func=cmd_session_start)

    nxt = sub.add_parser("next-batch", help="生成下一批浏览器任务")
    nxt.add_argument("--run", required=True)
    nxt.add_argument("--platform", choices=("xiaohongshu", "zhihu"))
    nxt.add_argument("--size", type=int, default=4)
    nxt.add_argument("--dimension", help="只在该主题内选词（验证用）")
    nxt.set_defaults(func=cmd_next_batch)

    submit = sub.add_parser("submit-batch", help="提交浏览器结果并入库")
    submit.add_argument("--run", required=True)
    submit.add_argument("--task", required=True)
    submit.add_argument("--file", required=True)
    submit.add_argument("--relevance-threshold", type=int, default=2)
    submit.set_defaults(func=cmd_submit_batch)

    finish = sub.add_parser("finish", help="结束本次引擎运行")
    finish.add_argument("--run", required=True)
    finish.add_argument("--reason", default="completed")
    finish.add_argument("--baseline", type=int, default=0)
    finish.set_defaults(func=cmd_finish)

    dyn_scan = sub.add_parser("dynamic-scan", help="从真实文章提取动态关键词候选")
    dyn_scan.add_argument("--campaign")
    dyn_scan.add_argument("--platform", required=True, choices=("xiaohongshu", "zhihu"))
    dyn_scan.add_argument("--scan-items", type=int, default=200)
    dyn_scan.add_argument("--limit", type=int, default=40)
    dyn_scan.add_argument("--dimension", default="job_search")
    dyn_scan.set_defaults(func=cmd_dynamic_scan)

    dyn_list = sub.add_parser("dynamic-list", help="查看动态关键词候选")
    dyn_list.add_argument("--status", default="candidate", choices=("candidate", "approved", "rejected"))
    dyn_list.add_argument("--limit", type=int, default=50)
    dyn_list.set_defaults(func=cmd_dynamic_list)

    dyn_approve = sub.add_parser("dynamic-approve", help="批准动态关键词进入查询队列")
    dyn_approve.add_argument("--keyword", required=True)
    dyn_approve.set_defaults(func=cmd_dynamic_set_status, status="approved")

    dyn_reject = sub.add_parser("dynamic-reject", help="拒绝动态关键词")
    dyn_reject.add_argument("--keyword", required=True)
    dyn_reject.set_defaults(func=cmd_dynamic_set_status, status="rejected")

    status = sub.add_parser("status", help="查看进度与队列")
    status.add_argument("--run")
    status.add_argument("--campaign")
    status.set_defaults(func=cmd_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
