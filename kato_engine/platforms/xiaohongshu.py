"""小红书适配器（真实页面，2026-11-10 实测结构）。

实测要点：
- 搜索页卡片：`section.note-item`，带 `data-note-id`；
  卡片内第一个 `<a>` 是隐藏的 `/explore/<id>`，可见入口是 `a.title`
  （`/search_result/<id>?xsec_token=...`）。必须点击可见入口，不能拼 URL。
- 详情页：`#detail-title`、`.note-content`、评论总数 `"共 N 条评论"`。
- 评论层级：`.parent-comment` 包含直属 `.comment-item` 与兄弟 `.reply-container`，
  楼中楼是 `.reply-container` 里的 `.comment-item`，可继续嵌套。
- 展开入口：`.show-more`（展开更多回复/更多评论）。
"""

from __future__ import annotations

import re
from urllib.parse import quote

from playwright.sync_api import Page

from kato_engine.browser.errors import (
    AuthRequiredError,
    ContentNotLoadedError,
    IrrelevantContentError,
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

_LOGGER = get_logger("kato.xhs")

CARD_SELECTOR = "section.note-item"
TITLE_LINK_SELECTOR = "a.title"
COMMENT_TOTAL_RE = re.compile(r"(\d+)\s*条评论")
DATE_TOKEN_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?"
    r"|\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?"
    r"|昨天(?:\s*\d{1,2}:\d{2})?"
    r"|前天(?:\s*\d{1,2}:\d{2})?"
    r"|\d+\s*(?:秒|分钟|小时|天|周|个月|年)前)"
)


def clean_date_text(text: object) -> str | None:
    """只保留时间片段，丢弃页面附带的 IP 归属地等信息。"""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    raw = re.sub(r"^\s*(编辑于|发布于|修改于)\s*", "", raw)
    match = DATE_TOKEN_RE.match(raw)
    return match.group(1).strip() if match else None

_SEARCH_EXTRACT = """
(cards) => cards.map((card, index) => {
  const titleEl = card.querySelector('a.title, .title');
  const noteId = card.getAttribute('data-note-id') || '';
  return {
    index,
    note_id: noteId,
    title: (titleEl?.innerText || '').trim().slice(0, 120),
    href: titleEl?.getAttribute('href') || '',
  };
})
"""

_COMMENTS_EXTRACT = """
(root) => {
  const parseItem = (el, level) => {
    if (!el) return null;
    const id = (el.id || '').replace(/^comment-/, '') || null;
    const contentEl = el.querySelector(':scope > .content, :scope .content');
    const likeEl = el.querySelector(':scope > .interactions .like .count, :scope .like .count');
    const dateEl = el.querySelector(':scope > .info .date, :scope .date');
    const replyCountEl = el.querySelector(':scope .reply .count, :scope .count');
    const content = (contentEl?.innerText || '').trim();
    if (!content && !id) return null;
    const node = {
      id,
      content: content.slice(0, 4000),
      like_text: (likeEl?.innerText || '').trim().slice(0, 20),
      date_text: (dateEl?.innerText || '').trim().slice(0, 40),
      reply_text: (replyCountEl?.innerText || '').trim().slice(0, 20),
      level,
      children: [],
    };
    // 楼中楼：reply-container 内可继续嵌套
    const containers = el.querySelectorAll(':scope > .reply-container, :scope .reply-container');
    const seen = new Set();
    containers.forEach(container => {
      const nested = container.querySelectorAll(':scope > .comment-item');
      nested.forEach(child => {
        if (seen.has(child)) return;
        seen.add(child);
        const parsed = parseItem(child, level + 1);
        if (parsed) node.children.push(parsed);
      });
    });
    return node;
  };

  const scope = root || document;
  const parents = Array.from(scope.querySelectorAll('.parent-comment'));
  const items = [];
  if (parents.length) {
    parents.forEach(parent => {
      const own = parent.querySelector(':scope > .comment-item');
      const parsed = parseItem(own, 1);
      if (!parsed) return;
      // 保证 reply-container 里未被 parseItem 覆盖的层级也被采集
      const replies = Array.from(parent.querySelectorAll(':scope > .reply-container .comment-item'));
      const known = new Set(parsed.children.map(c => c.id));
      replies.forEach(reply => {
        const id = (reply.id || '').replace(/^comment-/, '');
        if (id && known.has(id)) return;
        const extra = parseItem(reply, 2);
        if (extra) parsed.children.push(extra);
      });
      items.push(parsed);
    });
  }
  return items;
}
"""


def _parse_int(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"(\d+)", str(value).replace(",", ""))
    return int(match.group(1)) if match else None


class XiaohongshuAdapter:
    name = "xiaohongshu"
    home_url = "https://www.xiaohongshu.com"

    def search_url(self, query: str) -> str:
        return (
            "https://www.xiaohongshu.com/search_result?"
            f"keyword={quote(query)}&source=web_explore_feed"
        )

    # -- 搜索 -------------------------------------------------------------
    def search(self, page: Page, query: str, *, limit: int) -> SearchOutcome:
        url = self.search_url(query)
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2_500)
        self._raise_if_blocked(page, context="搜索页")

        try:
            page.wait_for_selector(CARD_SELECTOR, timeout=15_000)
        except Exception as exc:  # noqa: BLE001
            guards = detect_guards(page)
            if guards:
                self._raise_for_guards(guards, context="搜索页")
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
        for record in records[: max(limit, 1) * 3]:
            note_id = str(record.get("note_id") or "").strip()
            title = str(record.get("title") or "").strip()
            if not note_id:
                continue
            try:
                canonical = canonical_url(self.name, f"{self.home_url}/explore/{note_id}")
            except ValueError:
                continue
            hits.append(
                SearchHit(
                    title=title,
                    canonical_url=canonical,
                    raw_index=int(record.get("index") or 0),
                    extra={"note_id": note_id},
                )
            )
        if not hits:
            notes.append("所有卡片都缺少 data-note-id")
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
        note_id = hit.extra.get("note_id", "")
        if not note_id:
            raise SelectorMissingError("候选缺少 note_id，无法从搜索页点击进入")
        card = page.locator(f'{CARD_SELECTOR}[data-note-id="{note_id}"]')
        if card.count() == 0:
            raise SelectorMissingError(
                "搜索页上找不到该笔记卡片，可能已翻页或结果被重排",
                detail={"note_id": note_id},
            )
        link = card.first.locator(TITLE_LINK_SELECTOR)
        try:
            link.scroll_into_view_if_needed(timeout=8_000)
            link.click(timeout=10_000)
        except Exception as exc:  # noqa: BLE001
            raise SelectorMissingError(
                f"点击笔记入口失败：{type(exc).__name__}", detail={"note_id": note_id}
            ) from exc

        page.wait_for_timeout(2_500)
        self._raise_if_blocked(page, context="详情页")
        try:
            page.wait_for_selector("#detail-title, .note-content", timeout=15_000)
        except Exception as exc:  # noqa: BLE001
            raise ContentNotLoadedError(
                "笔记详情未加载", detail={"note_id": note_id, "url": strip_query(page.url)}
            ) from exc

        final_url = strip_query(page.url)
        if note_id not in final_url:
            raise IrrelevantContentError(
                f"详情页与候选不匹配：{final_url}", detail={"note_id": note_id}
            )
        return page, canonical_url(self.name, final_url)

    def read_article(self, page: Page) -> ArticleData:
        title = (page.locator("#detail-title").first.inner_text(timeout=5_000) or "").strip()
        body = (page.locator(".note-content").first.inner_text(timeout=8_000) or "").strip()
        published = None
        for selector in (".bottom-container .date", ".note-content .date", ".publish-date"):
            locator = page.locator(selector)
            if locator.count():
                text = (locator.first.inner_text(timeout=2_000) or "").strip()
                if text:
                    published = text
                    break
        if not title:
            raise ContentNotLoadedError("笔记标题为空")
        return ArticleData(
            platform=self.name,
            canonical_url=canonical_url(self.name, strip_query(page.url)),
            title=title,
            body_text=body,
            published_text=clean_date_text(published),
        )

    # -- 评论 -------------------------------------------------------------
    def displayed_comments_total(self, page: Page) -> int | None:
        for selector in (".comments-container .total", ".comments-el .total"):
            locator = page.locator(selector)
            if locator.count():
                text = (locator.first.inner_text(timeout=2_000) or "").strip()
                match = COMMENT_TOTAL_RE.search(text)
                if match:
                    return int(match.group(1))
        return None

    def collect_comments(self, page: Page, *, limit: int) -> CommentBundle:
        notes: list[str] = []
        displayed_total = self.displayed_comments_total(page)

        try:
            page.wait_for_selector(".comment-item", timeout=12_000)
        except Exception as exc:  # noqa: BLE001
            guards = detect_guards(page)
            if guards:
                self._raise_for_guards(guards, context="评论区")
            return CommentBundle(
                nodes=[],
                displayed_total=displayed_total,
                sort_basis="visible_order",
                notes=[f"评论区未加载：{type(exc).__name__}"],
            )

        # 滚动评论区并展开楼中楼
        rounds = 0
        prev_count = -1
        stable = 0
        while rounds < 12:
            rounds += 1
            for selector in (".show-more", ".comment-item .reply .show-more"):
                buttons = page.locator(selector)
                for index in range(min(buttons.count(), 8)):
                    try:
                        button = buttons.nth(index)
                        if button.is_visible():
                            button.click(timeout=2_500)
                            page.wait_for_timeout(350)
                    except Exception:  # noqa: BLE001
                        continue
            try:
                page.evaluate(
                    """() => {
                        const el = document.querySelector('.note-scroller') || document.scrollingElement;
                        if (el) el.scrollTop = el.scrollHeight;
                        const comments = document.querySelector('.comments-container');
                        if (comments) comments.scrollTop = comments.scrollHeight;
                    }"""
                )
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(700)
            current = page.locator(".comment-item").count()
            if current == prev_count:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
                prev_count = current

        raw_nodes = page.evaluate(_COMMENTS_EXTRACT, None)
        nodes = [self._to_node(item, 1) for item in raw_nodes or []]
        nodes = [node for node in nodes if node is not None]
        if not nodes:
            notes.append("评论选择器命中但解析为空")
        if displayed_total is not None and len(nodes) < displayed_total:
            notes.append(
                f"页面显示 {displayed_total} 条，实际解析到 {len(nodes)} 条一级评论"
            )
        bundle = CommentBundle(
            nodes=nodes,
            displayed_total=displayed_total,
            displayed_top_level=None,
            sort_basis="visible_order",
            notes=notes,
        )
        _LOGGER.debug(
            "小红书评论解析：一级 %s，楼中楼 %s，页面总数 %s",
            bundle.top_level,
            bundle.replies,
            displayed_total,
        )
        return bundle

    # -- 内部 -------------------------------------------------------------
    def _to_node(self, item: dict, level: int) -> CommentNode | None:
        content = str(item.get("content") or "").strip()
        if not content:
            content = "[无文字内容]"
        children = [
            node
            for child in item.get("children") or []
            if (node := self._to_node(child, level + 1)) is not None
        ]
        return CommentNode(
            content=content,
            platform_comment_id=(str(item.get("id")) if item.get("id") else None),
            like_count=_parse_int(item.get("like_text")),
            published_time_displayed=clean_date_text(item.get("date_text")),
            reply_count_displayed=_parse_int(item.get("reply_text")),
            level=level,
            children=children,
        )

    def _raise_if_blocked(self, page: Page, *, context: str) -> None:
        guards = detect_guards(page)
        if guards:
            self._raise_for_guards(guards, context=context)

    @staticmethod
    def _raise_for_guards(guards: list[dict[str, str]], *, context: str) -> None:
        kinds = {guard["kind"] for guard in guards}
        markers = ", ".join(sorted({guard["marker"] for guard in guards}))
        if "verification_required" in kinds:
            raise VerificationRequiredError(f"{context}出现安全验证：{markers}")
        if "rate_limited" in kinds:
            raise RateLimitedError(f"{context}出现限流/拒绝：{markers}")
        if "auth_required" in kinds:
            raise AuthRequiredError(f"{context}要求登录：{markers}")
