"""单篇文章的采集结果模型与摘要生成（与浏览器无关）。

V6.1：页面动作由 ZCode 内置浏览器完成，Python 只处理"已提取的结构化结果"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from kato_engine.collection.classification import Classification
from kato_engine.collection.comments import Selection
from kato_engine.collection.models import ArticleData

MAX_SUMMARY_CHARS = 160


@dataclass
class Collected:
    article: ArticleData
    canonical_url: str
    selection: Selection
    classification: Classification
    metrics: dict[str, int] = field(default_factory=dict)

    def summary_text(self) -> str:
        return build_summary(self.article)


def build_summary(article: ArticleData) -> str:
    """用正文前 160 字做摘录；不生成未经核实的事实。"""
    text = re.sub(r"\s+", " ", article.body_text or "").strip()
    if not text:
        return ""
    return text[:MAX_SUMMARY_CHARS] + ("…" if len(text) > MAX_SUMMARY_CHARS else "")


def ensure_relevant(classification: Classification, *, threshold: int = 2) -> tuple[bool, int]:
    top = max(classification.scores.values()) if classification.scores else 0
    return top >= threshold, top


def collected_metrics(selection: Selection) -> dict[str, int]:
    return {
        "collected_top_level": selection.collected_top_level,
        "collected_replies": selection.collected_replies,
    }


def as_payload(collected: Collected) -> dict[str, Any]:
    """调试/日志用摘要，不含正文全文。"""
    return {
        "url": collected.canonical_url,
        "title": collected.article.title[:80],
        "body_length": collected.article.body_length,
        "displayed_total": collected.selection.displayed_total,
        "top_level": collected.selection.collected_top_level,
        "replies": collected.selection.collected_replies,
        "coverage": collected.selection.coverage_status,
        "topic": collected.classification.employment_topic,
    }
