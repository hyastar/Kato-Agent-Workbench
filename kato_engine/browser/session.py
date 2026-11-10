"""浏览器会话：持有 Playwright → BrowserContext → Page 的唯一引用。

健康检查是真实探测（evaluate + 页面计数 + URL），不是标志位：
没有实际连接浏览器时，管理器拒绝放行采集循环。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import BrowserContext, Page, Playwright

from kato_engine.browser.errors import BrowserNotReadyError, PageLostError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class HealthReport:
    ok: bool
    checked_at: str
    page_count: int = 0
    current_url: str = ""
    user_agent: str = ""
    evaluate_result: int | None = None
    browser_version: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_at": self.checked_at,
            "page_count": self.page_count,
            "current_url": self.current_url,
            "user_agent": self.user_agent,
            "evaluate_result": self.evaluate_result,
            "browser_version": self.browser_version,
            "error": self.error,
        }


@dataclass
class BrowserSession:
    """一次成功的持久化浏览器连接。"""

    playwright: Playwright
    context: BrowserContext
    channel: str
    profile_dir: str
    started_at: str = field(default_factory=utc_now)
    _primary: Page | None = field(default=None, repr=False)
    _closed: bool = field(default=False, repr=False)

    # -- 页面 -------------------------------------------------------------
    @property
    def context_pages(self) -> list[Page]:
        return list(self.context.pages)

    def page(self) -> Page:
        """返回主页面；主页面失效时在同一次会话内重建。"""
        if self._closed:
            raise PageLostError("浏览器会话已关闭")
        if self._primary is not None and not self._primary.is_closed():
            return self._primary
        pages = [p for p in self.context.pages if not p.is_closed()]
        self._primary = pages[0] if pages else self.context.new_page()
        return self._primary

    def new_page(self, url: str | None = None) -> Page:
        page = self.context.new_page()
        if url:
            page.goto(url, wait_until="domcontentloaded")
        return page

    # -- 健康检查 ---------------------------------------------------------
    def health_check(self, retries: int = 2, retry_delay_s: float = 0.5) -> HealthReport:
        last_error: str | None = None
        for attempt in range(retries + 1):
            try:
                pages = self.context_pages
                page = self.page()
                evaluate_result = page.evaluate("() => 1 + 1")
                user_agent = str(page.evaluate("() => navigator.userAgent") or "")
                version = ""
                marker = "Chrome/"
                if marker in user_agent:
                    version = user_agent.split(marker, 1)[1].split()[0].split(".")[0]
                ok = evaluate_result == 2 and len(pages) >= 1
                return HealthReport(
                    ok=ok,
                    checked_at=utc_now(),
                    page_count=len(pages),
                    current_url=page.url,
                    user_agent=user_agent,
                    evaluate_result=evaluate_result if isinstance(evaluate_result, int) else None,
                    browser_version=version,
                    error=None if ok else "evaluate 或页面数量异常",
                )
            except Exception as exc:  # noqa: BLE001 - 需要把任何异常转成健康结论
                last_error = f"{type(exc).__name__}: {exc}"
                self._primary = None
                if attempt < retries:
                    time.sleep(retry_delay_s)
        return HealthReport(
            ok=False,
            checked_at=utc_now(),
            error=last_error or "未知错误",
        )

    def require_healthy(self) -> HealthReport:
        report = self.health_check()
        if not report.ok:
            raise BrowserNotReadyError(
                f"浏览器健康检查失败：{report.error}", detail=report.to_dict()
            )
        return report

    # -- 生命周期 ---------------------------------------------------------
    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for closer in (self.context.close, self.playwright.stop):
            try:
                closer()
            except Exception:  # noqa: BLE001 - 关闭阶段不允许再抛错掩盖原异常
                pass

    def describe(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "profile_dir": self.profile_dir,
            "started_at": self.started_at,
            "closed": self._closed,
            "page_count": len(self.context_pages) if not self._closed else 0,
        }
