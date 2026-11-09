"""URL、时间、文本与联系方式的标准化。"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
WECHAT_RE = re.compile(r"(?:微信|wechat|vx|VX)\s*[:：]?\s*([A-Za-z][A-Za-z0-9_-]{5,19})")
QQ_RE = re.compile(r"(?:QQ|qq)\s*[:：]?\s*(\d{5,12})")


def normalize_url(url: str) -> str:
    """小写 scheme/host、去掉 fragment、保留路径与查询参数。"""
    candidate = (url or "").strip()
    if not candidate:
        raise ValueError("canonical_url 不能为空")
    parts = urlsplit(candidate)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("canonical_url 必须是 http(s) URL")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


def normalize_text(text: str) -> str:
    """压缩空白并去掉首尾空格，不改变语义。"""
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_enum(value: str | None, allowed: tuple[str, ...], field: str) -> str:
    if value is None or not str(value).strip():
        raise ValueError(f"{field} 不能为空")
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        raise ValueError(f"不支持的 {field}：{value}（可选：{', '.join(allowed)}）")
    return normalized


def ensure_iso8601(value: str | None, field: str) -> str | None:
    """校验 ISO-8601；空值返回 None。绝不把相对时间推算成绝对时间。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} 必须是 ISO-8601 日期或时间：{text}") from exc
    return text


def redact_contacts(text: str) -> tuple[str, bool]:
    """脱敏手机号、邮箱、微信/QQ 号；返回 (文本, 是否发生脱敏)。"""
    changed = False

    def replace(pattern: re.Pattern[str], replacement: str, source: str) -> str:
        nonlocal changed
        result, count = pattern.subn(replacement, source)
        if count:
            changed = True
        return result

    result = replace(EMAIL_RE, "[邮箱已脱敏]", text or "")
    result = replace(MOBILE_RE, "[手机号已脱敏]", result)
    result = replace(WECHAT_RE, "微信：[已脱敏]", result)
    result = replace(QQ_RE, "QQ：[已脱敏]", result)
    return result, changed


def relative_time_displayed(value: str | None) -> str | None:
    """保留页面相对时间原文；不转换为绝对时间。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
