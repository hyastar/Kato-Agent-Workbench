"""单篇文章的采集编排。

顺序：点击进入详情 → 读正文 → 展开并解析评论 → 50 条规则 → 内容分类。
每一步单独计时，供阶段 9 的吞吐与瓶颈报告使用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from playwright.sync_api import Page

from kato_engine.browser.errors import EmptyContentError, IrrelevantContentError
from kato_engine.collection.classification import Classification, classify
from kato_engine.collection.comments import Selection, select_comment_nodes
from kato_engine.platforms.base import ArticleData, PlatformAdapter, SearchHit

MAX_SUMMARY_CHARS = 160


@dataclass
class Collected:
    article: ArticleData
    canonical_url: str
    selection: Selection
    classification: Classification
    metrics: dict[str, int] = field(default_factory=dict)
    detail_page: Any = None

    def summary_text(self) -> str:
        return build_summary(self.article)


def build_summary(article: ArticleData) -> str:
    text = re.sub(r"\s+", " ", article.body_text or "").strip()
    if not text:
        return ""
    return text[:MAX_SUMMARY_CHARS] + ("…" if len(text) > MAX_SUMMARY_CHARS else "")


def collect_article(
    page: Page,
    adapter: PlatformAdapter,
    hit: SearchHit,
    *,
    limit: int = 50,
    require_relevance: bool = True,
    relevance_threshold: int = 2,
) -> Collected:
    metrics: dict[str, int] = {}

    started = perf_counter()
    detail_page, canonical = adapter.open_detail(page, hit)
    metrics["open_detail_ms"] = int((perf_counter() - started) * 1000)

    started = perf_counter()
    article = adapter.read_article(detail_page)
    metrics["read_article_ms"] = int((perf_counter() - started) * 1000)
    if not article.title.strip():
        raise EmptyContentError("标题为空")
    if article.body_length < 20:
        raise EmptyContentError(f"正文过短：{article.body_length} 字")

    started = perf_counter()
    bundle = adapter.collect_comments(detail_page, limit=limit)
    metrics["collect_comments_ms"] = int((perf_counter() - started) * 1000)

    selection = select_comment_nodes(bundle, limit=limit)
    metrics["collected_top_level"] = selection.collected_top_level
    metrics["collected_replies"] = selection.collected_replies

    classification = classify(article.title, article.body_text)
    top_score = max(classification.scores.values()) if classification.scores else 0
    if require_relevance and top_score < relevance_threshold:
        raise IrrelevantContentError(
            f"内容与就业生态无关（最高分 {top_score}）",
            detail={"title": article.title[:80], "scores": classification.scores},
        )

    return Collected(
        article=article,
        canonical_url=canonical,
        selection=selection,
        classification=classification,
        metrics=metrics,
        detail_page=detail_page,
    )
