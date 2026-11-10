"""导航与页面级工具：跳转、滚动稳定检测、可见文本提取、风控信号识别。

只使用页面正常可见的 DOM 与交互；不调用隐藏接口。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from kato_engine.browser.errors import (
    ContentNotLoadedError,
    NavigationTimeout,
    PageLostError,
    SelectorMissingError,
)
from kato_engine.observability.logging import get_logger

_LOGGER = get_logger("kato.nav")

# 页面出现这些信号说明需要人工介入，不能继续自动操作。
GUARD_TEXT_MARKERS: dict[str, tuple[str, ...]] = {
    "verification_required": (
        "请完成安全验证",
        "拖动滑块",
        "请按住滑块",
        "访问验证",
        "人机验证",
        "captcha",
    ),
    "rate_limited": (
        "访问过于频繁",
        "操作频繁",
        "当前请求异常",
        "请求被拒绝",
        "403 forbidden",
    ),
    "auth_required": (
        "扫码登录",
        "请先登录",
        "登录后查看",
        "手机号登录",
        "密码登录",
        "登录后继续",
    ),
}


@dataclass
class StabilityTracker:
    """连续 N 轮观察值不变即判定稳定（用于滚动/展开终止）。"""

    stable_rounds: int = 3
    _last: Any = field(default=None, repr=False)
    _same_count: int = field(default=0, repr=False)
    observations: int = field(default=0, repr=False)

    def observe(self, value: Any) -> bool:
        self.observations += 1
        if self._last is not None and value == self._last:
            self._same_count += 1
        else:
            self._same_count = 0
            self._last = value
        return self._same_count >= self.stable_rounds


def strip_query(url: str) -> str:
    """去掉查询串与 fragment，保留 scheme/host/path（用于规范化入库 URL）。"""
    parts = urlsplit((url or "").strip())
    if not parts.scheme or not parts.netloc:
        return (url or "").strip()
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", "", ""))


def goto(
    page: Page,
    url: str,
    *,
    timeout_ms: int = 30_000,
    wait_until: str = "domcontentloaded",
    retries: int = 1,
) -> int:
    """打开页面；返回 HTTP 状态码（不可得时为 0）。超时/断页转分类异常。"""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            return response.status if response is not None else 0
        except PlaywrightTimeoutError as exc:
            last_error = exc
            _LOGGER.warning("导航超时（第 %s 次）：%s", attempt + 1, url)
        except PlaywrightError as exc:
            message = str(exc)
            if "has been closed" in message or "Target page" in message:
                raise PageLostError(f"页面已关闭：{message}", detail={"url": url}) from exc
            last_error = exc
            _LOGGER.warning("导航失败（第 %s 次）：%s", attempt + 1, message)
    raise NavigationTimeout(
        f"导航失败：{url}", detail={"url": url, "error": str(last_error)}
    )


def wait_for_any(
    page: Page,
    selectors: Sequence[str],
    *,
    timeout_ms: int = 15_000,
    poll_ms: int = 250,
) -> str:
    """轮询等待任一选择器出现，返回命中的选择器。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for selector in selectors:
            try:
                if page.locator(selector).count() > 0:
                    return selector
            except PlaywrightError:
                continue
        page.wait_for_timeout(poll_ms)
    raise SelectorMissingError(
        "等待内容超时，未匹配任何选择器",
        detail={"selectors": list(selectors), "url": page.url},
    )


def require_selector(page: Page, selectors: Sequence[str], *, what: str = "内容") -> str:
    for selector in selectors:
        try:
            if page.locator(selector).count() > 0:
                return selector
        except PlaywrightError:
            continue
    raise ContentNotLoadedError(
        f"{what}未加载", detail={"selectors": list(selectors), "url": page.url}
    )


def count(page: Page, selector: str) -> int:
    try:
        return page.locator(selector).count()
    except PlaywrightError:
        return 0


def first_text(page: Page, selectors: Iterable[str]) -> str | None:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                text = locator.first.inner_text(timeout=2_000).strip()
                if text:
                    return text
        except PlaywrightError:
            continue
    return None


def scroll_until_stable(
    page: Page,
    *,
    container_selector: str | None = None,
    count_selector: str | None = None,
    max_rounds: int = 12,
    stable_rounds: int = 3,
    pause_ms: int = 800,
) -> dict[str, Any]:
    """滚动容器直到内容不再增长。

    返回观察记录，供平台适配器判断"是否加载完"；不做任何伪造计数。
    """
    tracker = StabilityTracker(stable_rounds=stable_rounds)
    rounds = 0
    last_count = 0
    last_scroll = 0
    for _ in range(max_rounds):
        rounds += 1
        try:
            metrics = page.evaluate(
                """(selector) => {
                    const el = selector ? document.querySelector(selector) : null;
                    const target = el || document.scrollingElement || document.documentElement;
                    if (!target) return {scrollTop: 0, scrollHeight: 0};
                    target.scrollTop = target.scrollHeight;
                    return {scrollTop: target.scrollTop, scrollHeight: target.scrollHeight};
                }""",
                container_selector,
            )
        except PlaywrightError as exc:
            if "has been closed" in str(exc):
                raise PageLostError(f"滚动时页面已关闭：{exc}") from exc
            raise
        last_scroll = int(metrics.get("scrollTop") or 0)
        last_count = count(page, count_selector) if count_selector else int(metrics.get("scrollHeight") or 0)
        if tracker.observe((last_count, last_scroll)):
            break
        page.wait_for_timeout(pause_ms)
    return {
        "rounds": rounds,
        "observations": tracker.observations,
        "stable": tracker._same_count >= stable_rounds,  # noqa: SLF001 - 结果用于诊断
        "item_count": last_count,
        "scroll_top": last_scroll,
        "container": container_selector,
    }


def detect_guards(page: Page, *, max_chars: int = 4_000) -> list[dict[str, str]]:
    """在页面可见文本里查找风控/登录信号，返回命中项（不抛异常）。"""
    try:
        body_text = page.evaluate(
            """(limit) => (document.body ? document.body.innerText.slice(0, limit) : "")""",
            max_chars,
        ) or ""
    except PlaywrightError:
        return []
    lowered = str(body_text).lower()
    hits: list[dict[str, str]] = []
    for kind, markers in GUARD_TEXT_MARKERS.items():
        for marker in markers:
            if marker.lower() in lowered:
                hits.append({"kind": kind, "marker": marker, "url": page.url})
                break
    return hits


def visible_text(page: Page, selector: str, *, limit: int = 20_000) -> str:
    text = first_text(page, [selector]) or ""
    return text[:limit]
