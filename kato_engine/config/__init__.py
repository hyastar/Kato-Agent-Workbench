"""配置层：路径、浏览器、限速与配额。"""

from __future__ import annotations

from .settings import Settings, load_settings

__all__ = ["Settings", "load_settings"]
