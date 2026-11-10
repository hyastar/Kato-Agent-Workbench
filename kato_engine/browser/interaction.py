"""页面交互：真实点击、展开、滚动。

原则：
- 只点页面上正常可见的元素；
- 点击失败不静默：记录原因，由适配器决定降级为 partial；
- 每轮展开有上限，避免无限循环。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

from kato_engine.browser.errors import PageLostError, SelectorMissingError
from kato_engine.browser.navigation import StabilityTracker, count, scroll_until_stable
from kato_engine.observability.logging import get_logger

_LOGGER = get_logger("kato.interaction")


@dataclass
class ClickResult:
    selector: str
    clicked: int
    failed: int
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "clicked": self.clicked,
            "failed": self.failed,
            "errors": self.errors[:5],
        }


def _is_page_lost(exc: Exception) -> bool:
    message = str(exc)
    return "has been closed" in message or "Target page" in message or "crash" in message.lower()


def click_first_visible(
    page: Page,
    selectors: Sequence[str],
    *,
    timeout_ms: int = 8_000,
) -> str:
    """点击第一个可见的候选选择器，返回实际使用的选择器。"""
    for selector in selectors:
        try:
            locator = page.locator(selector)
            total = locator.count()
        except PlaywrightError as exc:
            if _is_page_lost(exc):
                raise PageLostError(str(exc)) from exc
            continue
        for index in range(min(total, 5)):
            candidate = locator.nth(index)
            try:
                if not candidate.is_visible(timeout=1_000):
                    continue
                candidate.scroll_into_view_if_needed(timeout=timeout_ms)
                candidate.click(timeout=timeout_ms)
                return selector
            except PlaywrightError as exc:
                if _is_page_lost(exc):
                    raise PageLostError(str(exc)) from exc
                continue
    raise SelectorMissingError(
        "没有可点击的可见元素", detail={"selectors": list(selectors), "url": page.url}
    )


def click_all_visible(
    page: Page,
    selector: str,
    *,
    max_clicks: int = 60,
    timeout_ms: int = 5_000,
) -> ClickResult:
    """点击所有当前可见的匹配元素（元素可能点击后消失，故每轮重查）。"""
    clicked = 0
    failed = 0
    errors: list[str] = []
    for _ in range(max_clicks):
        locator: Locator = page.locator(selector)
        target = None
        try:
            total = locator.count()
        except PlaywrightError as exc:
            if _is_page_lost(exc):
                raise PageLostError(str(exc)) from exc
            break
        for index in range(total):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    target = candidate
                    break
            except PlaywrightError:
                continue
        if target is None:
            break
        try:
            target.scroll_into_view_if_needed(timeout=timeout_ms)
            target.click(timeout=timeout_ms)
            clicked += 1
            page.wait_for_timeout(350)
        except PlaywrightError as exc:
            if _is_page_lost(exc):
                raise PageLostError(str(exc)) from exc
            failed += 1
            errors.append(str(exc).splitlines()[0])
            break
    return ClickResult(selector=selector, clicked=clicked, failed=failed, errors=errors)


def expand_until_stable(
    page: Page,
    *,
    triggers: Sequence[str],
    count_selector: str,
    container_selector: str | None = None,
    max_rounds: int = 8,
    stable_rounds: int = 3,
    max_clicks_per_round: int = 40,
    pause_ms: int = 800,
) -> dict[str, Any]:
    """反复点击"展开更多"类入口，直到内容数量连续多轮不再增长。"""
    tracker = StabilityTracker(stable_rounds=stable_rounds)
    total_clicked = 0
    rounds = 0
    last = 0
    while rounds < max_rounds:
        rounds += 1
        for selector in triggers:
            if count(page, selector) == 0:
                continue
            result = click_all_visible(page, selector, max_clicks=max_clicks_per_round)
            total_clicked += result.clicked
        if container_selector:
            try:
                scroll_until_stable(
                    page,
                    container_selector=container_selector,
                    count_selector=count_selector,
                    max_rounds=4,
                    stable_rounds=2,
                    pause_ms=pause_ms,
                )
            except PlaywrightError as exc:
                _LOGGER.warning("展开过程中滚动失败：%s", exc)
        else:
            page.mouse.wheel(0, 2_400)
        page.wait_for_timeout(pause_ms)
        last = count(page, count_selector)
        if tracker.observe(last):
            break
    return {
        "rounds": rounds,
        "clicks": total_clicked,
        "item_count": last,
        "stable": tracker._same_count >= stable_rounds,  # noqa: SLF001
    }
