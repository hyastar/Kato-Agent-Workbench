"""平台适配器契约。

适配器只负责"在真实页面上做什么"，不负责入库与导出：
- 搜索 → 候选链接
- 点击进入详情
- 读取正文与元信息
- 展开并解析一级评论与楼中楼

作者昵称、头像、用户 ID、主页、位置一律在抽取阶段丢弃，不进入内存模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from playwright.sync_api import Page


@dataclass
class SearchHit:
    """搜索结果条目。`canonical_url` 已去跟踪参数；`extra` 保存点击所需信息。"""

    title: str
    canonical_url: str
    raw_index: int = 0
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class SearchOutcome:
    platform: str
    query: str
    page_title: str
    raw_count: int
    hits: list[SearchHit]
    notes: list[str] = field(default_factory=list)


@dataclass
class CommentNode:
    content: str
    platform_comment_id: str | None = None
    like_count: int | None = None
    published_time_displayed: str | None = None
    reply_count_displayed: int | None = None
    level: int = 1
    children: list["CommentNode"] = field(default_factory=list)

    def total(self) -> int:
        return 1 + sum(child.total() for child in self.children)

    def to_payload(self, sort_basis: str = "visible_order") -> dict[str, Any]:
        return {
            "platform_comment_id": self.platform_comment_id,
            "content": self.content,
            "like_count": self.like_count,
            "published_time_displayed": self.published_time_displayed,
            "reply_count_displayed": self.reply_count_displayed,
            "sort_basis": sort_basis,
            "children": [child.to_payload(sort_basis) for child in self.children],
        }


@dataclass
class CommentBundle:
    nodes: list[CommentNode]
    displayed_total: int | None = None
    displayed_top_level: int | None = None
    displayed_replies: int | None = None
    sort_basis: str = "visible_order"
    notes: list[str] = field(default_factory=list)

    @property
    def top_level(self) -> int:
        return len(self.nodes)

    @property
    def replies(self) -> int:
        return sum(node.total() - 1 for node in self.nodes)


@dataclass
class ArticleData:
    platform: str
    canonical_url: str
    title: str
    body_text: str = ""
    published_text: str | None = None
    published_at: str | None = None
    city: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def body_length(self) -> int:
        return len(self.body_text)


class PlatformAdapter(Protocol):
    """浏览器操作契约。所有方法都直接作用于传入的 Page。"""

    name: str
    home_url: str

    def search_url(self, query: str) -> str: ...

    def search(self, page: Page, query: str, *, limit: int) -> SearchOutcome: ...

    def open_detail(self, page: Page, hit: SearchHit) -> tuple[Page, str]: ...

    def read_article(self, page: Page) -> ArticleData: ...

    def collect_comments(self, page: Page, *, limit: int) -> CommentBundle: ...

    def displayed_comments_total(self, page: Page) -> int | None: ...
