"""URL 规范化与去重判据。

同一篇文章可能来自多个关键词、多个搜索页、带不同查询参数：
- 小红书详情必须从搜索结果点击进入，URL 带 `xsec_token`——入库只保留
  `/explore/<id>`，绝不保存 token；
- 知乎问题/回答/专栏分别用各自的稳定 ID；
- 其余情况退回 `strip_query`。

数据库唯一索引 `(platform, canonical_url)` 是最终判据。
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

def strip_query(url: str) -> str:
    """去掉查询串与 fragment，保留 scheme/host/path。"""
    parts = urlsplit((url or "").strip())
    if not parts.scheme or not parts.netloc:
        return (url or "").strip()
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", "", ""))

_XHS_NOTE_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-fA-F]{16,32})")
_ZHIHU_QUESTION_RE = re.compile(r"/question/(\d+)")
_ZHIHU_ANSWER_RE = re.compile(r"/answer/(\d+)")
_ZHIHU_ARTICLE_RE = re.compile(r"/p/(\d+)")

SUPPORTED_PLATFORMS = ("xiaohongshu", "zhihu")


def canonical_url(platform: str, url: str) -> str:
    """把页面 URL 规范成稳定、无跟踪参数的入库 URL。"""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL 不能为空")
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"不是 http(s) URL：{raw}")

    path = parts.path or "/"

    if platform == "xiaohongshu":
        match = _XHS_NOTE_RE.search(path)
        if not match:
            raise ValueError(f"小红书笔记 URL 无法识别笔记 ID：{raw}")
        return f"https://www.xiaohongshu.com/explore/{match.group(1)}"

    if platform == "zhihu":
        match = _ZHIHU_ANSWER_RE.search(path)
        if match:
            return f"https://www.zhihu.com/answer/{match.group(1)}"
        match = _ZHIHU_QUESTION_RE.search(path)
        if match:
            return f"https://www.zhihu.com/question/{match.group(1)}"
        match = _ZHIHU_ARTICLE_RE.search(path)
        if match:
            return f"https://zhuanlan.zhihu.com/p/{match.group(1)}"
        raise ValueError(f"知乎 URL 无法识别内容 ID：{raw}")

    return strip_query(raw)


def is_supported_platform(platform: str) -> bool:
    return platform in SUPPORTED_PLATFORMS
