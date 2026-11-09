"""浏览器执行契约、动作片段与规范化（V5）。"""

from scripts.employment.browser.contracts import (
    ArticleResult,
    ArticleTask,
    BrowserExecutionError,
    CommentNode,
)
from scripts.employment.browser.extraction import normalize_payload

__all__ = [
    "ArticleResult",
    "ArticleTask",
    "BrowserExecutionError",
    "CommentNode",
    "normalize_payload",
]
