"""结构化日志。

约束：
- 不记录 Cookie、Token、storage state、评论作者身份信息；
- 默认写 stderr，可选同时写 `runs/<engine-run>/engine.log`；
- 时间统一 UTC ISO-8601，便于与 SQLite 对齐。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_CONFIGURED = False


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "context", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    level: str = "INFO",
    *,
    log_file: str | Path | None = None,
    quiet: bool = False,
) -> None:
    """初始化根 logger。重复调用只追加文件 handler 一次。"""
    global _CONFIGURED
    root = logging.getLogger("kato")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not _CONFIGURED and not quiet:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(JsonLineFormatter())
        root.addHandler(handler)

    if log_file is not None:
        target = Path(log_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved = str(target.resolve())
        existing = {
            getattr(h, "baseFilename", None) for h in root.handlers if isinstance(h, logging.FileHandler)
        }
        if resolved not in existing:
            file_handler = logging.FileHandler(target, encoding="utf-8")
            file_handler.setFormatter(JsonLineFormatter())
            root.addHandler(file_handler)

    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("kato") else f"kato.{name}")
