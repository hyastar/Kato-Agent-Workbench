"""搜索结果发现、候选 URL 规范化与入队（不访问网络）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from scripts.employment.normalize import normalize_text

XHS_ID_RE = re.compile(r"/(?:explore|search_result)/([0-9a-f]{24})", re.IGNORECASE)
ZHIHU_PATH_RE = re.compile(r"^/(question|p)/[A-Za-z0-9]+(?:/answer/[A-Za-z0-9]+)?$")


def canonicalize_candidate(platform: str, href: str) -> str | None:
    """把搜索结果链接规范化为可入库的文章 URL。

    小红书：/search_result/<id>?xsec_token=... -> /explore/<id>
    知乎：去掉 query 与 fragment，保留问题/回答/专栏路径。
    """
    if not href:
        return None
    parts = urlsplit(href.strip())
    host = parts.netloc.lower()
    if platform == "xiaohongshu":
        if "xiaohongshu.com" not in host:
            return None
        match = XHS_ID_RE.search(parts.path)
        if not match:
            return None
        return f"https://www.xiaohongshu.com/explore/{match.group(1).lower()}"
    if platform == "zhihu":
        if host not in {"www.zhihu.com", "zhuanlan.zhihu.com"}:
            return None
        if not ZHIHU_PATH_RE.match(parts.path):
            return None
        return urlunsplit((parts.scheme or "https", host, parts.path, "", ""))
    return None


def normalize_candidates(platform: str, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """规范化并去除同页重复候选，保留首次出现的顺序。"""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in raw:
        href = item.get("href") or item.get("url") or ""
        canonical = canonicalize_candidate(platform, str(href))
        if canonical is None or canonical in seen:
            continue
        seen.add(canonical)
        text = normalize_text(str(item.get("text") or item.get("title") or ""))[:160]
        result.append({"canonical_url": canonical, "text": text})
    return result


def filter_known(
    candidates: list[dict[str, Any]],
    known_urls: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按 (platform, canonical_url) 的 URL 集合拆分新候选与重复候选。"""
    new: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for candidate in candidates:
        (duplicates if candidate["canonical_url"] in known_urls else new).append(candidate)
    return new, duplicates


def build_queue(
    platform: str,
    keyword: str,
    raw: list[dict[str, Any]],
    known_urls: set[str],
) -> dict[str, Any]:
    candidates = normalize_candidates(platform, raw)
    new, duplicates = filter_known(candidates, known_urls)
    return {
        "platform": platform,
        "keyword": keyword,
        "raw_count": len(raw),
        "unique_count": len(candidates),
        "new_count": len(new),
        "duplicate_count": len(duplicates),
        "queue": new,
        "duplicates": duplicates,
    }
