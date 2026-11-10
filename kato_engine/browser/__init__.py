"""浏览器层：会话所有权、导航与交互。"""

from __future__ import annotations

from .errors import (
    AuthRequiredError,
    BrowserLaunchError,
    BrowserNotReadyError,
    ConfigError,
    ContentNotLoadedError,
    EmptyContentError,
    EngineError,
    IrrelevantContentError,
    NavigationTimeout,
    PageLostError,
    ProfileInUseError,
    RateLimitedError,
    SelectorMissingError,
    VerificationRequiredError,
)

__all__ = [
    "AuthRequiredError",
    "BrowserLaunchError",
    "BrowserNotReadyError",
    "ConfigError",
    "ContentNotLoadedError",
    "EmptyContentError",
    "EngineError",
    "IrrelevantContentError",
    "NavigationTimeout",
    "PageLostError",
    "ProfileInUseError",
    "RateLimitedError",
    "SelectorMissingError",
    "VerificationRequiredError",
]
