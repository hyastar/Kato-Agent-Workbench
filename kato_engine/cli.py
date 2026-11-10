"""V6.1 引擎命令行（离线工具）。

浏览器相关命令已移除：页面动作由 ZCode 内置 Browser Use 完成，
采集任务走 `python -m kato_engine.agent.cli`。

这里只保留确定性的查询、校验、回填与报告。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from kato_engine import __version__
from kato_engine.config.settings import load_settings
from kato_engine.discovery.candidate_queue import CandidateQueue
from kato_engine.discovery.keyword_planner import KeywordPlanner, load_keyword_library
from kato_engine.observability.logging import configure_logging
from kato_engine.storage.repository import EngineRepository


def _print(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _open():
    settings = load_settings()
    library = load_keyword_library(settings.keyword_library_path)
    repo, report = EngineRepository.open(settings)
    return settings, repo, report, library


def cmd_plan(args: argparse.Namespace) -> int:
    settings, repo, report, library = _open()
    try:
        campaign_id = args.campaign or library.campaign
        planner = KeywordPlanner(
            library,
            executed_queries=repo.executed_queries(args.platform),
            accepted_by_dimension=repo.dimension_article_counts(campaign_id),
            pipeline_by_dimension=CandidateQueue(repo).dimension_pipeline(campaign_id=campaign_id),
        )
        plans = []
        for _ in range(max(args.limit, 0)):
            plan = planner.next_plan()
            if plan is None:
                break
            plans.append(plan.to_dict())
            planner.executed.add(plan.combined_query)
        payload = {
            "campaign_id": campaign_id,
            "platform": args.platform,
            "schema_version": report.to_version,
            "dimensions": len(planner.library.dimensions),
            "keywords": sum(len(d.keywords) for d in planner.library.dimensions),
            "accepted_by_dimension": repo.dimension_article_counts(campaign_id),
            "plans": plans,
            "exhausted_dimensions": planner.exhausted_dimensions(),
        }
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_queue_stats(args: argparse.Namespace) -> int:
    settings, repo, report, library = _open()
    try:
        campaign_id = args.campaign or library.campaign
        payload = {
            "campaign_id": campaign_id,
            "schema_version": report.to_version,
            "states": repo.candidate_state_counts(campaign_id=campaign_id, platform=args.platform),
            "campaign_articles": repo.campaign_article_counts(campaign_id),
            "dimensions": repo.dimension_article_counts(campaign_id),
        }
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_requeue(args: argparse.Namespace) -> int:
    _, repo, _, library = _open()
    try:
        campaign_id = args.campaign or library.campaign
        count = repo.requeue_blocked(args.platform, campaign_id=campaign_id)
        payload = {
            "campaign_id": campaign_id,
            "platform": args.platform,
            "requeued": count,
            "queue": repo.candidate_state_counts(campaign_id=campaign_id, platform=args.platform),
        }
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_verify_artifacts(args: argparse.Namespace) -> int:
    from kato_engine.storage.markdown import verify_artifacts

    settings, repo, _, library = _open()
    try:
        campaign_id = args.campaign or library.campaign
        report = verify_artifacts(settings, repo)
        report.update(
            {
                "campaign_id": campaign_id,
                "campaign_articles": repo.campaign_article_counts(campaign_id),
            }
        )
    finally:
        repo.close()
    _print(report)
    return 0 if report["missing_count"] == 0 and report["mismatched_count"] == 0 else 2


def cmd_report(args: argparse.Namespace) -> int:
    from kato_engine.observability.reporting import (
        build_report,
        render_report_markdown,
        write_report,
    )

    settings, repo, _, library = _open()
    try:
        campaign_id = args.campaign or library.campaign
        report = build_report(
            repo, settings, campaign_id, engine_run_id=args.engine_run, verify=not args.no_verify
        )
    finally:
        repo.close()
    if args.out:
        json_path = Path(args.out)
        markdown_path = json_path.with_suffix(".md")
        write_report(report, json_path, markdown_path)
        _print({"ok": True, "json": str(json_path), "markdown": str(markdown_path)})
    elif args.markdown:
        sys.stdout.write(render_report_markdown(report) + "\n")
    else:
        _print(report)
    return 0


def cmd_classify_backfill(args: argparse.Namespace) -> int:
    from kato_engine.collection.classification import classify

    _, repo, _, library = _open()
    campaign_id = args.campaign or library.campaign
    summary: dict[str, Any] = {"campaign_id": campaign_id, "dry_run": args.dry_run}
    try:
        rows = repo.conn.execute(
            "SELECT item_id, platform, title, summary, employment_topic FROM research_items "
            "WHERE campaign_id = ? AND employment_topic IS NULL",
            (campaign_id,),
        ).fetchall()
        updated = skipped = 0
        by_topic: dict[str, int] = {}
        details: list[dict[str, Any]] = []
        for row in rows:
            result = classify(str(row["title"] or ""), str(row["summary"] or ""))
            score = max(result.scores.values()) if result.scores else 0
            if not result.matched_topic or score < args.min_score:
                skipped += 1
                continue
            topic = str(result.employment_topic)
            by_topic[topic] = by_topic.get(topic, 0) + 1
            updated += 1
            details.append(
                {
                    "item_id": row["item_id"],
                    "topic": topic,
                    "cohort": result.graduation_cohort,
                    "score": score,
                }
            )
            if not args.dry_run:
                repo.set_classification(str(row["item_id"]), **result.to_db_fields())
        summary.update(
            {
                "candidates": len(rows),
                "updated": updated,
                "skipped_low_confidence": skipped,
                "min_score": args.min_score,
                "by_topic": by_topic,
                "details": details[:40],
            }
        )
    finally:
        repo.close()
    _print(summary)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kato-engine", description=f"Kato Collection Engine V6.1 {__version__}（离线工具）"
    )
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="查看关键词调度（不联网）")
    plan.add_argument("--platform", required=True, choices=("xiaohongshu", "zhihu"))
    plan.add_argument("--campaign")
    plan.add_argument("--limit", type=int, default=3)
    plan.set_defaults(func=cmd_plan)

    stats = sub.add_parser("queue-stats", help="查看候选队列与文章分布")
    stats.add_argument("--platform", choices=("xiaohongshu", "zhihu"))
    stats.add_argument("--campaign")
    stats.set_defaults(func=cmd_queue_stats)

    requeue = sub.add_parser("requeue", help="人工处理完成后把 blocked 候选放回队列")
    requeue.add_argument("--platform", required=True, choices=("xiaohongshu", "zhihu"))
    requeue.add_argument("--campaign")
    requeue.set_defaults(func=cmd_requeue)

    verify = sub.add_parser("verify-artifacts", help="核对 Markdown 档案哈希")
    verify.add_argument("--campaign")
    verify.set_defaults(func=cmd_verify_artifacts)

    report = sub.add_parser("report", help="汇总数据质量与性能")
    report.add_argument("--campaign")
    report.add_argument("--engine-run")
    report.add_argument("--out")
    report.add_argument("--markdown", action="store_true")
    report.add_argument("--no-verify", action="store_true")
    report.set_defaults(func=cmd_report)

    backfill = sub.add_parser("classify-backfill", help="补齐历史文章分类")
    backfill.add_argument("--campaign")
    backfill.add_argument("--min-score", type=int, default=3)
    backfill.add_argument("--dry-run", action="store_true")
    backfill.set_defaults(func=cmd_classify_backfill)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
