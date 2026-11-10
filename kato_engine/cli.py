"""V6 引擎命令行入口。

用法：
    python -m kato_engine.cli browser-check
    python -m kato_engine.cli browser-check --headless
    python -m kato_engine.cli browser-open --url https://example.com --seconds 15
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from kato_engine import __version__
from kato_engine.browser.errors import EngineError
from kato_engine.browser.manager import BrowserManager, verify_dom_roundtrip
from kato_engine.browser.navigation import strip_query
from kato_engine.config.settings import load_settings
from kato_engine.observability.logging import configure_logging

_DOM_PROBE_HTML = """
<!doctype html>
<html lang="zh-CN">
  <body>
    <h1 class="probe-title">V6 页面提取自检</h1>
    <div class="comment-item" id="comment-1">
      <span class="content">一级评论 A</span>
      <div class="reply-container">
        <div class="comment-item" id="comment-1-1"><span class="content">楼中楼 A-1</span></div>
        <div class="comment-item" id="comment-1-2"><span class="content">楼中楼 A-2</span></div>
      </div>
    </div>
    <div class="comment-item" id="comment-2"><span class="content">一级评论 B</span></div>
  </body>
</html>
"""


def _print(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def cmd_browser_check(args: argparse.Namespace) -> int:
    settings = load_settings()
    if args.profile:
        from dataclasses import replace

        settings = replace(settings, profile_dir=Path(args.profile).expanduser())
    manager = BrowserManager(settings)
    report: dict[str, Any] = {"engine_version": __version__, "ok": False, "steps": {}}
    code = 2
    try:
        report["steps"]["preflight"] = manager.preflight()
        session = manager.start(headless=args.headless)
        health = manager.health()
        report["steps"]["health"] = health.to_dict()
        if not health.ok:
            report["error"] = f"健康检查失败：{health.error}"
            return 2
        dom = verify_dom_roundtrip(
            session.page(),
            _DOM_PROBE_HTML,
            [
                ".probe-title",
                "body > .comment-item",
                ".comment-item",
                ".comment-item .content",
                ".reply-container .comment-item",
            ],
        )
        report["steps"]["dom"] = dom
        nested = dom["selectors"][".reply-container .comment-item"]["count"]
        top_level = dom["selectors"]["body > .comment-item"]["count"]
        report["steps"]["canonical_url_probe"] = strip_query(
            "https://www.xiaohongshu.com/explore/abc?xsec_token=SECRET#frag"
        )
        ok = (
            health.ok
            and dom["selectors"][".probe-title"]["text"] == "V6 页面提取自检"
            and top_level == 2
            and nested == 2
        )
        report["ok"] = ok
        report["steps"]["manager"] = manager.describe()
        code = 0 if ok else 2
    except EngineError as exc:
        report["error"] = exc.to_dict()
    finally:
        manager.stop()
        report["steps"]["stopped"] = manager.describe()
    _print(report)
    return code


def cmd_browser_open(args: argparse.Namespace) -> int:
    """打开一个真实页面并保持 N 秒，用于人工观察登录态与页面结构。"""
    settings = load_settings()
    if args.profile:
        from dataclasses import replace

        settings = replace(settings, profile_dir=Path(args.profile).expanduser())
    manager = BrowserManager(settings)
    payload: dict[str, Any] = {"ok": False, "url": args.url}
    try:
        session = manager.start(headless=False)
        page = session.page()
        status = 0
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
            status = 0
        except EngineError:
            raise
        except Exception as exc:  # noqa: BLE001
            payload["error"] = f"{type(exc).__name__}: {exc}"
        payload.update(
            {
                "ok": True,
                "status": status,
                "final_url": page.url,
                "title": page.title(),
                "health": manager.health().to_dict(),
                "seconds": args.seconds,
            }
        )
        if args.seconds > 0:
            page.wait_for_timeout(args.seconds * 1000)
    except EngineError as exc:
        payload["error"] = exc.to_dict()
    finally:
        manager.stop()
    _print(payload)
    return 0 if payload.get("ok") else 2


def cmd_plan(args: argparse.Namespace) -> int:
    """展示关键词调度器下一步会执行哪些查询（只读，不联网）。"""
    from kato_engine.discovery.candidate_queue import CandidateQueue
    from kato_engine.discovery.keyword_planner import KeywordPlanner, load_keyword_library
    from kato_engine.storage.repository import EngineRepository

    settings = load_settings()
    library = load_keyword_library(settings.keyword_library_path)
    campaign_id = args.campaign or library.campaign
    repo, report = EngineRepository.open(settings)
    try:
        accepted = repo.dimension_article_counts(campaign_id)
        pipeline = CandidateQueue(repo).dimension_pipeline(campaign_id=campaign_id)
        executed = repo.executed_queries(args.platform)
        planner = KeywordPlanner(
            library,
            executed_queries=executed,
            accepted_by_dimension=accepted,
            pipeline_by_dimension=pipeline,
        )
        plans = []
        for _ in range(max(args.limit, 0)):
            plan = planner.next_plan()
            if plan is None:
                break
            plans.append(plan.to_dict())
            executed.add(plan.combined_query)
            planner.executed.add(plan.combined_query)
        payload = {
            "campaign_id": campaign_id,
            "platform": args.platform,
            "schema_version": report.to_version,
            "library_dimensions": len(library.dimensions),
            "library_keywords": sum(len(d.keywords) for d in library.dimensions),
            "accepted_by_dimension": accepted,
            "pipeline_by_dimension": pipeline,
            "executed_queries": len(executed),
            "plans": plans,
            "exhausted_dimensions": planner.exhausted_dimensions(),
        }
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_queue_stats(args: argparse.Namespace) -> int:
    from kato_engine.discovery.candidate_queue import CandidateQueue
    from kato_engine.discovery.keyword_planner import load_keyword_library
    from kato_engine.storage.repository import EngineRepository

    settings = load_settings()
    library = load_keyword_library(settings.keyword_library_path)
    campaign_id = args.campaign or library.campaign
    repo, report = EngineRepository.open(settings)
    try:
        queue = CandidateQueue(repo)
        payload = {
            "campaign_id": campaign_id,
            "schema_version": report.to_version,
            "states": queue.stats(campaign_id=campaign_id, platform=args.platform),
            "campaign_articles": repo.campaign_article_counts(campaign_id),
            "dimensions": repo.dimension_article_counts(campaign_id),
        }
    finally:
        repo.close()
    _print(payload)
    return 0


def cmd_dom_probe(args: argparse.Namespace) -> int:
    """打开一个页面并输出结构摘要（调试选择器用；不保存页面内容到仓库）。"""
    from kato_engine.browser.navigation import detect_guards, strip_query

    settings = load_settings()
    payload: dict[str, Any] = {"url": strip_query(args.url), "ok": False}
    manager = BrowserManager(settings)
    try:
        session = manager.start(headless=args.headless)
        page = session.page()
        response_status = 0
        try:
            response = page.goto(args.url, wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
            response_status = response.status if response else 0
        except Exception as exc:  # noqa: BLE001
            payload["navigation_error"] = f"{type(exc).__name__}: {exc}"
        page.wait_for_timeout(args.wait_ms)
        selectors = [item for item in (args.selectors or "").split(",") if item.strip()]
        counts = {}
        for selector in selectors:
            try:
                counts[selector] = page.locator(selector).count()
            except Exception:  # noqa: BLE001
                counts[selector] = -1
        anchors: list[str] = []
        try:
            hrefs = page.eval_on_selector_all(
                "a[href]", "els => els.slice(0, 80).map(e => e.getAttribute('href'))"
            )
        except Exception:  # noqa: BLE001
            hrefs = []
        for href in hrefs or []:
            if not href:
                continue
            absolute = href if str(href).startswith("http") else f"https://{page.url.split('/')[2]}{href}"
            anchors.append(strip_query(absolute))
        payload.update(
            {
                "ok": True,
                "status": response_status,
                "final_url": strip_query(page.url),
                "title": page.title(),
                "guards": detect_guards(page),
                "selector_counts": counts,
                "anchors": anchors[:40],
                "body_text_sample": (page.evaluate("() => document.body ? document.body.innerText.slice(0, 300) : ''") or ""),
            }
        )
    except EngineError as exc:
        payload["error"] = exc.to_dict()
    finally:
        manager.stop()
    _print(payload)
    return 0 if payload.get("ok") else 2


def cmd_campaign_run(args: argparse.Namespace) -> int:
    """连续采集：从关键词到文章与评论档案，自动推进下一条候选。"""
    from kato_engine.core.engine import CampaignEngine, EngineOptions
    from kato_engine.discovery.keyword_planner import load_keyword_library
    from kato_engine.storage.repository import EngineRepository

    settings = load_settings()
    library = load_keyword_library(settings.keyword_library_path)
    campaign_id = args.campaign or library.campaign
    repo, schema = EngineRepository.open(settings)
    manager = BrowserManager(settings)
    summary: dict[str, Any] = {"campaign_id": campaign_id, "ok": False}
    try:
        campaign = repo.ensure_campaign(campaign_id)
        current = repo.campaign_article_counts(campaign_id)
        targets = {
            "xiaohongshu": current.get("xiaohongshu", 0) + args.add_xhs,
            "zhihu": current.get("zhihu", 0) + args.add_zhihu,
        }
        summary.update(
            {
                "schema_version": schema.to_version,
                "campaign_target_total": int(campaign["target_total"]),
                "before": current,
                "targets": targets,
                "add_xhs": args.add_xhs,
                "add_zhihu": args.add_zhihu,
            }
        )
        if args.dry_run:
            summary.update({"ok": True, "dry_run": True})
            _print(summary)
            return 0

        manager.start(headless=args.headless)
        engine = CampaignEngine(settings, repo, manager, library)
        order = tuple(
            item.strip() for item in (args.order or "xiaohongshu,zhihu").split(",") if item.strip()
        )
        result = engine.run(
            EngineOptions(
                campaign_id=campaign_id,
                targets=targets,
                max_articles=args.max_articles,
                max_consecutive_failures=args.max_failures,
                require_relevance=not args.no_relevance,
                platform_order=order,
                on_progress=_progress_printer(),
            )
        )
        after = repo.campaign_article_counts(campaign_id)
        summary.update(
            {
                "ok": result.articles_added > 0 or result.stop_reason == "targets_reached",
                "result": result.to_dict(),
                "after": after,
            }
        )
    except EngineError as exc:
        summary["error"] = exc.to_dict()
    finally:
        manager.stop()
        repo.close()
    _print(summary)
    return 0 if summary.get("ok") else 2


def _progress_printer():  # noqa: ANN202
    def _print_progress(payload: dict[str, Any]) -> None:
        sys.stderr.write(
            "[采集] {platform} {item_id} 一级={top_level} 楼中楼={replies} 覆盖={coverage} {title}\n".format(
                **payload
            )
        )
        sys.stderr.flush()

    return _print_progress


def cmd_requeue(args: argparse.Namespace) -> int:
    from kato_engine.discovery.keyword_planner import load_keyword_library
    from kato_engine.storage.repository import EngineRepository

    settings = load_settings()
    library = load_keyword_library(settings.keyword_library_path)
    campaign_id = args.campaign or library.campaign
    repo, _ = EngineRepository.open(settings)
    try:
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
    from kato_engine.discovery.keyword_planner import load_keyword_library
    from kato_engine.storage.markdown import verify_artifacts
    from kato_engine.storage.repository import EngineRepository

    settings = load_settings()
    library = load_keyword_library(settings.keyword_library_path)
    campaign_id = args.campaign or library.campaign
    repo, _ = EngineRepository.open(settings)
    try:
        report = verify_artifacts(settings, repo)
        report.update(
            {
                "campaign_id": campaign_id,
                "campaign_articles": repo.campaign_article_counts(campaign_id),
                "queue": repo.candidate_state_counts(campaign_id=campaign_id),
            }
        )
    finally:
        repo.close()
    _print(report)
    return 0 if report["missing_count"] == 0 and report["mismatched_count"] == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kato-engine", description=f"Kato Collection Engine V6 {__version__}"
    )
    parser.add_argument("--log-level", default="INFO", help="日志级别（默认 INFO）")
    parser.add_argument("--json", action="store_true", help="保留参数位，输出始终为 JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("browser-check", help="启动真实 Chrome 并验证导航/DOM/关闭链路")
    check.add_argument("--headless", action="store_true", help="无头运行（默认可见）")
    check.add_argument("--profile", help="覆盖持久化 Profile 路径")
    check.set_defaults(func=cmd_browser_check)

    open_cmd = sub.add_parser("browser-open", help="打开页面并保持窗口，供人工观察")
    open_cmd.add_argument("--url", required=True)
    open_cmd.add_argument("--seconds", type=int, default=20)
    open_cmd.add_argument("--profile")
    open_cmd.set_defaults(func=cmd_browser_open)

    plan_cmd = sub.add_parser("plan", help="展示关键词调度的下一步查询")
    plan_cmd.add_argument("--platform", required=True, choices=("xiaohongshu", "zhihu"))
    plan_cmd.add_argument("--campaign")
    plan_cmd.add_argument("--limit", type=int, default=3)
    plan_cmd.set_defaults(func=cmd_plan)

    stats_cmd = sub.add_parser("queue-stats", help="查看候选队列与文章分布")
    stats_cmd.add_argument("--platform", choices=("xiaohongshu", "zhihu"))
    stats_cmd.add_argument("--campaign")
    stats_cmd.set_defaults(func=cmd_queue_stats)

    probe_cmd = sub.add_parser("dom-probe", help="打开页面并输出选择器/链接结构（调试）")
    probe_cmd.add_argument("--url", required=True)
    probe_cmd.add_argument("--selectors", default="", help="逗号分隔的选择器列表")
    probe_cmd.add_argument("--wait-ms", type=int, default=3_000)
    probe_cmd.add_argument("--headless", action="store_true")
    probe_cmd.set_defaults(func=cmd_dom_probe)

    run_cmd = sub.add_parser("campaign-run", help="连续采集（真实浏览器）")
    run_cmd.add_argument("--campaign")
    run_cmd.add_argument("--add-xhs", type=int, default=0, help="本轮新增小红书篇数")
    run_cmd.add_argument("--add-zhihu", type=int, default=0, help="本轮新增知乎篇数")
    run_cmd.add_argument("--max-articles", type=int, default=None, help="本轮最多新增篇数（验收用）")
    run_cmd.add_argument("--max-failures", type=int, default=15, help="连续失败上限，达到即停止")
    run_cmd.add_argument("--order", default="xiaohongshu,zhihu")
    run_cmd.add_argument("--no-relevance", action="store_true", help="关闭相关性过滤（不推荐）")
    run_cmd.add_argument("--dry-run", action="store_true")
    run_cmd.add_argument("--headless", action="store_true")
    run_cmd.set_defaults(func=cmd_campaign_run)

    requeue_cmd = sub.add_parser("requeue", help="人工处理完成后把 blocked 候选放回队列")
    requeue_cmd.add_argument("--platform", required=True, choices=("xiaohongshu", "zhihu"))
    requeue_cmd.add_argument("--campaign")
    requeue_cmd.set_defaults(func=cmd_requeue)

    verify_cmd = sub.add_parser("verify-artifacts", help="核对 Markdown 档案哈希")
    verify_cmd.add_argument("--campaign")
    verify_cmd.set_defaults(func=cmd_verify_artifacts)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
