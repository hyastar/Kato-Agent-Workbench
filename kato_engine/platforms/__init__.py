"""平台适配器注册表。"""

from __future__ import annotations

from kato_engine.platforms.base import (
    ArticleData,
    CommentBundle,
    CommentNode,
    PlatformAdapter,
    SearchHit,
    SearchOutcome,
)
from kato_engine.platforms.xiaohongshu import XiaohongshuAdapter
from kato_engine.platforms.zhihu import ZhihuAdapter

ADAPTERS: dict[str, PlatformAdapter] = {
    "xiaohongshu": XiaohongshuAdapter(),
    "zhihu": ZhihuAdapter(),
}


def get_adapter(platform: str) -> PlatformAdapter:
    try:
        return ADAPTERS[platform]
    except KeyError as exc:
        raise KeyError(f"不支持的平台：{platform}（可选：{', '.join(ADAPTERS)}）") from exc


__all__ = [
    "ADAPTERS",
    "ArticleData",
    "CommentBundle",
    "CommentNode",
    "PlatformAdapter",
    "SearchHit",
    "SearchOutcome",
    "get_adapter",
]
