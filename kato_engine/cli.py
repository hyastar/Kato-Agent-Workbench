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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
