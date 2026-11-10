"""统一异常分类。

每个异常带 `error_type`，直接映射到候选状态机与指标：
- retryable=True  → `retryable_failed`，可重新入队；
- needs_human=True → `blocked`，暂停该平台等待用户处理。
"""

from __future__ import annotations

from typing import Any


class EngineError(RuntimeError):
    """引擎内所有可分类错误的基类。"""

    error_type = "engine_error"
    retryable = False
    needs_human = False

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail: dict[str, Any] = dict(detail or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "retryable": self.retryable,
            "needs_human": self.needs_human,
            "detail": self.detail,
        }


class ConfigError(EngineError):
    error_type = "config_error"


class ProfileInUseError(EngineError):
    """持久化 Profile 被其他 Chrome 占用。"""

    error_type = "profile_in_use"
    needs_human = True


class BrowserLaunchError(EngineError):
    error_type = "browser_launch"


class BrowserNotReadyError(EngineError):
    """健康检查未通过：不允许进入采集循环。"""

    error_type = "browser_not_ready"
    retryable = True


class PageLostError(EngineError):
    """页面被关闭或崩溃。"""

    error_type = "page_lost"
    retryable = True


class NavigationTimeout(EngineError):
    error_type = "timeout"
    retryable = True


class SelectorMissingError(EngineError):
    error_type = "selector_error"
    retryable = True


class ContentNotLoadedError(EngineError):
    error_type = "content_not_loaded"
    retryable = True


class AuthRequiredError(EngineError):
    """需要登录：暂停平台，等待用户手动完成。"""

    error_type = "auth_required"
    needs_human = True


class VerificationRequiredError(EngineError):
    """验证码 / 设备确认 / 安全验证。"""

    error_type = "verification_required"
    needs_human = True


class RateLimitedError(EngineError):
    """403、限流、访问拒绝。"""

    error_type = "rate_limited"
    needs_human = True


class EmptyContentError(EngineError):
    error_type = "empty_content"


class IrrelevantContentError(EngineError):
    error_type = "irrelevant"
