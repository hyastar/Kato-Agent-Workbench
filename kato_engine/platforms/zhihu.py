"""知乎适配器（真实页面，2026-11-10 实测结构）。

实测要点：
- 搜索页结果卡片：`.SearchResult-Card`，链接形如
  `/question/<qid>/answer/<aid>` 或 `/p/<id>`；点击可能打开新标签页。
- 详情页标题：`.QuestionHeader-title`（问题页）或 `.Post-Title`（专栏）。
- 正文：专栏 `.Post-RichText`；问题页 `.QuestionRichText` 为问题描述。
- 评论区：`.CommentContent` 列表，DOM 里没有稳定评论 ID；
  层级用缩进判断（实测一级 ≈ 342px、楼中楼 ≈ 376px，差 34px），
  因此不能按文本全局去重。
- 问题页可能同时显示多个回答，必须把解析范围限定在单个 `.ContentItem` 内，
  否则会把不同回答的评论混在一起。
"""

from __future__ import annotations

import re
from urllib.parse import quote

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from kato_engine.browser.errors import (
    AuthRequiredError,
    ContentNotLoadedError,
    RateLimitedError,
    SelectorMissingError,
    VerificationRequiredError,
)
from kato_engine.browser.navigation import detect_guards, strip_query
from kato_engine.discovery.deduplication import canonical_url
from kato_engine.observability.logging import get_logger
from kato_engine.platforms.base import (
    ArticleData,
    CommentBundle,
    CommentNode,
    SearchHit,
    SearchOutcome,
)

_LOGGER = get_logger("kato.zhihu")

CARD_SELECTOR = ".SearchResult-Card"
COMMENT_TOTAL_RE = re.compile(r"(\d+)\s*条评论")
INDENT_THRESHOLD_PX = 15

_SEARCH_EXTRACT = """
(cards) => cards.map((card, index) => {
  const anchors = Array.from(card.querySelectorAll('a[href]'))
    .map(a => a.getAttribute('href'))
    .filter(href => href && (href.includes('/answer/') || href.startsWith('/p/') || href.startsWith('/question/')));
  const titleEl = card.querySelector('h2, .ContentItem-title, a');
  return {
    index,
    href: anchors[0] || '',
    title: (titleEl?.innerText || '').trim().slice(0, 120),
  };
})
"""

_COMMENTS_EXTRACT = """
(root) => {
  const scope = root || document;
  const nodes = Array.from(scope.querySelectorAll('.CommentContent'));
  return nodes.map((el, index) => {
    const rect = el.getBoundingClientRect();
    const container = el.closest('.CommentItem, .CommentItemV2, .CommentContentParent, div');
    const meta = container ? container.innerText : '';
    const timeMatch = meta.match(/(\\d{2}-\\d{2}\\s*[·・]?\\s*[^\\n]{0,12})|(\\d{4}-\\d{2}-\\d{2}\\s*\\d{2}:\\d{2})|(\\d+\\s*(?:小时|分钟|天)前)/);
    return {
      index,
      left: Math.round(rect.left),
      top: Math.round(rect.top),
      text: (el.innerText || '').trim().slice(0, 4000),
      time_text: timeMatch ? timeMatch[0].trim().slice(0, 30) : '',
    };
  });
}
"""

_ACTIONS_TEXT = """
(root) => {
  const scope = root || document;
  const nodes = Array.from(scope.querySelectorAll('.ContentItem-actions, .Post-Actions, .Comments-container, button'));
  for (const el of nodes) {
    const text = (el.innerText || '').replace(/\\s+/g, ' ');
    if (text.includes('条评论')) return text.slice(0, 200);
  }
  return '';
}
"""

PUBLISHED_DATETIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")
PUBLISHED_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def clean_published_text(text: str | None) -> str | None:
    """去掉"发布于"前缀与 IP 归属地；不保留位置信息。"""
    if not text:
        return None
    cleaned = re.sub(r"[・·].*$", "", str(text), flags=re.S)
    cleaned = re.sub(r"^\s*(发布于|编辑于|修改于)\s*", "", cleaned).strip()
    return cleaned or None


def published_iso(text: str | None) -> str | None:
    """仅当页面给出完整日期时才转 ISO；相对时间不推算。"""
    if not text:
        return None
    match = PUBLISHED_DATETIME_RE.search(text)
    if match:
        return f"{match.group(1)}T{match.group(2)}:00"
    match = PUBLISHED_DATE_RE.search(text)
    if match:
        return match.group(1)
    return None


class ZhihuAdapter:
    name = "zhihu"
    home_url = "https://www.zhihu.com"

    def search_url(self, query: str) -> str:
        return f"https://www.zhihu.com/search?type=content&q={quote(query)}"

    # -- 搜索 -------------------------------------------------------------
    def search(self, page: Page, query: str, *, limit: int) -> SearchOutcome:
        page.goto(self.search_url(query), wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2_500)
        self._raise_if_blocked(page, context="搜索页")

        try:
            page.wait_for_selector(CARD_SELECTOR, timeout=15_000)
        except Exception as exc:  # noqa: BLE001
            guards = detect_guards(page)
            if guards:
                self._raise_for_guards(guards)
            return SearchOutcome(
                platform=self.name,
                query=query,
                page_title=page.title(),
                raw_count=0,
                hits=[],
                notes=[f"搜索结果未出现卡片：{type(exc).__name__}"],
            )

        cards = page.locator(CARD_SELECTOR)
        raw_count = cards.count()
        records = page.eval_on_selector_all(CARD_SELECTOR, _SEARCH_EXTRACT)
        hits: list[SearchHit] = []
        notes: list[str] = []
        for record in records:
            href = str(record.get("href") or "").strip()
            if not href:
                continue
            absolute = href if href.startswith("http") else f"{self.home_url}{href}"
            try:
                canonical = canonical_url(self.name, absolute)
            except ValueError:
                continue
            title = str(record.get("title") or "").strip()
            if not title:
                notes.append("部分结果缺少标题")
            hits.append(
                SearchHit(
                    title=title,
                    canonical_url=canonical,
                    raw_index=int(record.get("index") or 0),
                    extra={"href": href},
                )
            )
        return SearchOutcome(
            platform=self.name,
            query=query,
            page_title=page.title(),
            raw_count=raw_count,
            hits=hits[:limit],
            notes=notes,
        )

    # -- 详情 -------------------------------------------------------------
    def open_detail(self, page: Page, hit: SearchHit) -> tuple[Page, str]:
        href = hit.extra.get("href", "")
        if not href:
            raise SelectorMissingError("候选缺少详情链接")
        anchor = page.locator(f'a[href="{href}"]')
        if anchor.count() == 0:
            anchor = page.locator(f'a[href*="{href.split("?")[0]}"]')
        if anchor.count() == 0:
            raise SelectorMissingError("搜索页上找不到该结果链接", detail={"href": href})

        target_page = page
        try:
            with page.context.expect_page(timeout=6_000) as new_page_info:
                anchor.first.click(timeout=10_000)
            target_page = new_page_info.value
            target_page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except PlaywrightTimeoutError:
            target_page = page
        except PlaywrightError as exc:
            raise SelectorMissingError(
                f"点击知乎结果失败：{type(exc).__name__}", detail={"href": href}
            ) from exc

        target_page.wait_for_timeout(2_500)
        self._raise_if_blocked(target_page, context="详情页")
        final_url = strip_query(target_page.url)
        if "/search" in final_url or final_url.rstrip("/") == self.home_url:
            raise ContentNotLoadedError("知乎详情没有打开（仍停留在搜索页）", detail={"url": final_url})
        try:
            target_page.wait_for_selector(
                ".QuestionHeader-title, .Post-Title, .RichText", timeout=15_000
            )
        except Exception as exc:  # noqa: BLE001
            raise ContentNotLoadedError("知乎详情未加载", detail={"url": final_url}) from exc
        return target_page, canonical_url(self.name, final_url)

    def read_article(self, page: Page) -> ArticleData:
        title = ""
        for selector in (".QuestionHeader-title", ".Post-Title"):
            locator = page.locator(selector)
            if locator.count():
                title = (locator.first.inner_text(timeout=5_000) or "").strip()
                if title:
                    break
        if not title:
            title = (page.title() or "").split(" - ")[0].strip()

        body = ""
        post_rich = page.locator(".Post-RichText")
        if post_rich.count():
            body = (post_rich.first.inner_text(timeout=8_000) or "").strip()
        if not body:
            parts: list[str] = []
            question_rich = page.locator(".QuestionRichText")
            if question_rich.count():
                parts.append((question_rich.first.inner_text(timeout=5_000) or "").strip())
            rich_texts = page.locator(".RichText")
            for index in range(min(rich_texts.count(), 2)):
                text = (rich_texts.nth(index).inner_text(timeout=5_000) or "").strip()
                if text and text not in parts:
                    parts.append(text)
            body = "\n".join(part for part in parts if part)[:6_000]

        published_raw = None
        for selector in (".ContentItem-time", ".Post-Time", ".QuestionHeader-detail"):
            locator = page.locator(selector)
            if locator.count():
                text = (locator.first.inner_text(timeout=2_000) or "").strip()
                if text:
                    published_raw = text
                    break
        published = clean_published_text(published_raw)

        if not title:
            raise ContentNotLoadedError("知乎标题为空")
        return ArticleData(
            platform=self.name,
            canonical_url=canonical_url(self.name, strip_query(page.url)),
            title=title,
            body_text=body,
            published_text=published,
            published_at=published_iso(published),
        )

    # -- 评论 -------------------------------------------------------------
    def _scope(self, page: Page):
        """返回包含评论区的单个回答容器；专栏页退化为整页。"""
        items = page.locator(".ContentItem")
        count = items.count()
        for index in range(min(count, 5)):
            item = items.nth(index)
            try:
                if item.locator(".CommentContent").count() > 0:
                    return item.element_handle()
            except PlaywrightError:
                continue
        return None

    def displayed_comments_total(self, page: Page) -> int | None:
        handle = self._scope(page)
        try:
            text = page.evaluate(_ACTIONS_TEXT, handle)
        except PlaywrightError:
            text = ""
        match = COMMENT_TOTAL_RE.search(text or "")
        return int(match.group(1)) if match else None

    def collect_comments(self, page: Page, *, limit: int) -> CommentBundle:
        notes: list[str] = []
        item = page.locator(".ContentItem").first
        if item.count():
            buttons = item.locator("button:has-text('评论')")
            for index in range(min(buttons.count(), 3)):
                try:
                    button = buttons.nth(index)
                    if button.is_visible():
                        button.click(timeout=3_000)
                        page.wait_for_timeout(1_500)
                        break
                except PlaywrightError:
                    continue

        try:
            page.wait_for_selector(".CommentContent", timeout=12_000)
        except Exception as exc:  # noqa: BLE001
            guards = detect_guards(page)
            if guards:
                self._raise_for_guards(guards)
            return CommentBundle(
                nodes=[],
                sort_basis="visible_order",
                notes=[f"评论区未加载：{type(exc).__name__}"],
            )

        # 展开楼中楼并滚动
        for _ in range(4):
            for selector in ("button:has-text('展开')", "button:has-text('查看更多')"):
                buttons = item.locator(selector) if item.count() else page.locator(selector)
                for index in range(min(buttons.count(), 6)):
                    try:
                        button = buttons.nth(index)
                        if button.is_visible():
                            button.click(timeout=2_000)
                            page.wait_for_timeout(300)
                    except PlaywrightError:
                        continue
            page.mouse.wheel(0, 1_500)
            page.wait_for_timeout(600)

        scope = self._scope(page)
        raw_nodes = page.evaluate(_COMMENTS_EXTRACT, scope) or []
        displayed_total = self.displayed_comments_total(page)
        nodes = self._build_tree(raw_nodes)
        if not nodes:
            notes.append("评论选择器命中但解析为空")
        if displayed_total is not None and len(nodes) < displayed_total:
            notes.append(f"页面显示 {displayed_total} 条，实际解析到 {len(nodes)} 条一级评论")
        bundle = CommentBundle(
            nodes=nodes,
            displayed_total=displayed_total,
            displayed_top_level=len(nodes),
            sort_basis="visible_order",
            notes=notes,
        )
        _LOGGER.debug(
            "知乎评论解析：一级 %s，楼中楼 %s，页面总数 %s",
            bundle.top_level,
            bundle.replies,
            displayed_total,
        )
        return bundle

    def _build_tree(self, raw_nodes: list[dict]) -> list[CommentNode]:
        """按缩进恢复父子关系；缩进差 ≤ 阈值视为同一层。"""
        prepared: list[tuple[int, CommentNode]] = []
        for raw in raw_nodes:
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            prepared.append(
                (
                    int(raw.get("left") or 0),
                    CommentNode(
                        content=text,
                        platform_comment_id=None,
                        like_count=None,
                        published_time_displayed=(str(raw.get("time_text") or "").strip() or None),
                    ),
                )
            )
        roots: list[CommentNode] = []
        stack: list[tuple[int, CommentNode]] = []
        for left, node in prepared:
            while stack and left <= stack[-1][0] + INDENT_THRESHOLD_PX:
                stack.pop()
            if stack:
                parent = stack[-1][1]
                node.level = parent.level + 1
                parent.children.append(node)
            else:
                node.level = 1
                roots.append(node)
            stack.append((left, node))
        return roots

    # -- 内部 -------------------------------------------------------------
    def _raise_if_blocked(self, page: Page, *, context: str) -> None:
        guards = detect_guards(page)
        if guards:
            self._raise_for_guards(guards, context=context)

    @staticmethod
    def _raise_for_guards(guards: list[dict[str, str]], *, context: str = "页面") -> None:
        kinds = {guard["kind"] for guard in guards}
        markers = ", ".join(sorted({guard["marker"] for guard in guards}))
        if "verification_required" in kinds:
            raise VerificationRequiredError(f"{context}出现安全验证：{markers}")
        if "rate_limited" in kinds:
            raise RateLimitedError(f"{context}出现限流/拒绝：{markers}")
        if "auth_required" in kinds:
            raise AuthRequiredError(f"{context}要求登录：{markers}")
