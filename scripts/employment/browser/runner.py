"""浏览器执行结果规范化 CLI 与 checkpoint。

浏览器动作由宿主 Agent 通过 Playwright MCP 完成；本模块只处理已返回的
payload（规范化、50 条规则、覆盖、checkpoint），不发起任何网络请求。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts import db
from scripts.employment.browser.contracts import ArticleTask
from scripts.employment.browser.discovery import build_queue
from scripts.employment.browser.extraction import normalize_payload


def task_from_dict(payload: dict[str, Any]) -> ArticleTask:
    return ArticleTask(
        case_id=str(payload["case_id"]),
        platform=str(payload["platform"]),
        cohort=str(payload.get("cohort") or "unknown"),
        recruitment_stage=str(payload.get("recruitment_stage") or "unknown"),
        topic=str(payload.get("topic") or "other"),
        company=payload.get("company"),
        url=payload.get("url"),
        keyword=payload.get("keyword"),
        title_fragment=payload.get("title_fragment"),
        comment_limit=int(payload.get("comment_limit", 50)),
    )


def result_to_dict(result: Any) -> dict[str, Any]:
    return {
        **result.summary(),
        "reason": result.reason,
        "comments": [asdict(node) for node in result.comments],
        "metrics": result.metrics,
    }


def write_checkpoint(
    path: str | Path,
    task: ArticleTask,
    result: Any,
) -> dict[str, Any]:
    checkpoint = {
        "case_id": task.case_id,
        "platform": task.platform,
        "backend": result.backend,
        "status": result.status,
        "coverage_status": result.coverage_status,
        "collected_top_level": result.collected_top_level,
        "collected_replies": result.collected_replies,
        "updated_at": db.utc_now(),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8", newline=""
    )
    return checkpoint


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="规范化浏览器执行结果（不联网）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize_parser = subparsers.add_parser("normalize", help="规范化一个 payload")
    normalize_parser.add_argument("--task", required=True, help="任务 JSON")
    normalize_parser.add_argument("--payload", required=True, help="浏览器返回 JSON")
    normalize_parser.add_argument("--output", help="结果 JSON")
    normalize_parser.add_argument("--checkpoint", help="checkpoint JSON")
    normalize_parser.add_argument("--latest-verified", action="store_true")

    status_parser = subparsers.add_parser("status", help="读取 checkpoint")
    status_parser.add_argument("--checkpoint", required=True)

    queue_parser = subparsers.add_parser("queue", help="规范化搜索结果并入队")
    queue_parser.add_argument("--platform", required=True, choices=("xiaohongshu", "zhihu"))
    queue_parser.add_argument("--keyword", default="")
    queue_parser.add_argument("--payload", required=True, help="搜索结果 JSON（含 items）")
    queue_parser.add_argument("--known-json", help="已知 canonical_url 数组 JSON")
    queue_parser.add_argument("--db", help="从 SQLite 读取已知 URL（可选）")
    queue_parser.add_argument("--output", help="队列 JSON 输出路径")

    args = parser.parse_args(argv)
    if args.command == "status":
        print(Path(args.checkpoint).read_text(encoding="utf-8"))
        return 0
    if args.command == "queue":
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        known: set[str] = set()
        if args.known_json:
            known.update(json.loads(Path(args.known_json).read_text(encoding="utf-8")))
        if args.db:
            conn = db.connect_ready(args.db)
            try:
                known.update(
                    row["canonical_url"]
                    for row in conn.execute(
                        "SELECT canonical_url FROM research_items WHERE platform = ?",
                        (args.platform,),
                    ).fetchall()
                )
            finally:
                conn.close()
        queue = build_queue(args.platform, args.keyword, payload.get("items") or [], known)
        text = json.dumps(queue, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8", newline="")
        else:
            print(text)
        return 0

    task = task_from_dict(json.loads(Path(args.task).read_text(encoding="utf-8")))
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    result = normalize_payload(payload, task, latest_verified=args.latest_verified)
    output = result_to_dict(result)
    text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8", newline="")
    else:
        print(text)
    if args.checkpoint:
        write_checkpoint(args.checkpoint, task, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
