"""Browser Manager：V6 中唯一的浏览器所有者。

职责：
1. 启动真实 Chrome（`channel="chrome"`，持久化 Profile 位于仓库之外）；
2. 启动前检测 Profile 占用，避免与 MCP 浏览器抢锁；
3. 启动后强制健康检查，未通过不允许进入采集循环；
4. 连接断开时重建会话，并把进度留给状态机；
5. 退出时释放浏览器与 Playwright。

不做任何指纹伪装、代理池或验证码绕过。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from kato_engine.browser.errors import (
    BrowserLaunchError,
    BrowserNotReadyError,
    ConfigError,
    ProfileInUseError,
)
from kato_engine.browser.session import BrowserSession, HealthReport
from kato_engine.config.settings import Settings, find_chrome_executable, load_settings
from kato_engine.observability.logging import get_logger

_LOGGER = get_logger("kato.browser")

# Chrome 在 Profile 目录里留下的锁文件（POSIX）；Windows 用进程检测。
_POSIX_LOCK_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")

_LOCK_MESSAGE_MARKERS = (
    "singletonlock",
    "processsingleton",
    "already in use",
    "user data directory is already in use",
    "failed to create a process singleton",
)


def _read_singleton_lock(profile_dir: Path) -> list[int]:
    """从 SingletonLock 符号链接解析占用进程 PID（hostname-pid）。"""
    lock = profile_dir / "SingletonLock"
    try:
        target = os.readlink(lock)
    except OSError:
        return []
    host_pid = target.rsplit("-", 1)[-1]
    return [int(host_pid)] if host_pid.isdigit() else []


def _windows_profile_holders(profile_dir: Path) -> list[int] | None:
    """查询命令行里带该 Profile 的 chrome.exe 进程。

    返回 None 表示检测不可用（例如 PowerShell 受限），调用方应退回到
    "尝试启动并解析错误" 的策略。
    """
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
        "| Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    raw = (completed.stdout or "").strip()
    if not raw:
        return []
    import json

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return None

    wanted = str(profile_dir.resolve()).replace("/", "\\").lower()
    holders: list[int] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        command_line = str(entry.get("CommandLine") or "").replace("/", "\\").lower()
        pid = entry.get("ProcessId")
        # Chrome 的渲染/GPU 子进程同样带 --user-data-dir，只保留浏览器主进程。
        if "--type=" in command_line:
            continue
        if wanted and wanted in command_line and isinstance(pid, int):
            holders.append(pid)
    return holders


def profile_holders(profile_dir: Path) -> list[int] | None:
    """返回占用 Profile 的进程 PID 列表；None 表示无法判定。"""
    if not profile_dir.exists():
        return []
    found = _read_singleton_lock(profile_dir)
    if found:
        return found
    if sys.platform.startswith("win"):
        return _windows_profile_holders(profile_dir)
    return None


class BrowserManager:
    """进程内单例的浏览器所有权对象。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self._session: BrowserSession | None = None
        self._starts = 0
        self._restarts = 0
        self._last_health: HealthReport | None = None

    # -- 启动 -------------------------------------------------------------
    def preflight(self) -> dict[str, Any]:
        """启动前的静态检查：Chrome 是否存在、Profile 是否被占用。"""
        chrome = find_chrome_executable() if self.settings.browser_channel == "chrome" else None
        if self.settings.browser_channel == "chrome" and chrome is None:
            raise ConfigError(
                "未找到本机 Chrome。请安装 Chrome，或用 KATO_BROWSER_CHANNEL 指定可用的 channel。"
            )
        holders = profile_holders(self.settings.profile_dir)
        if holders:
            raise ProfileInUseError(
                "浏览器 Profile 正被占用，请先关闭 MCP 浏览器或手动启动的 Chrome："
                f"{self.settings.profile_dir}（PID: {', '.join(map(str, holders))}）",
                detail={"profile_dir": str(self.settings.profile_dir), "pids": holders},
            )
        return {
            "chrome": str(chrome) if chrome else None,
            "profile_dir": str(self.settings.profile_dir),
            "profile_exists": self.settings.profile_dir.exists(),
            "profile_holders": holders,
        }

    def start(self, *, headless: bool | None = None) -> BrowserSession:
        """启动浏览器并完成健康检查。任何失败都不会留下半开状态。"""
        from playwright.sync_api import sync_playwright

        self.stop()
        self.settings.ensure_dirs()
        preflight = self.preflight()
        self.settings.profile_dir.mkdir(parents=True, exist_ok=True)
        _LOGGER.info(
            "启动浏览器 channel=%s headless=%s profile=%s",
            self.settings.browser_channel,
            self.settings.headless if headless is None else headless,
            self.settings.profile_dir,
        )

        try:
            playwright = sync_playwright().start()
        except Exception as exc:  # noqa: BLE001
            raise BrowserLaunchError(f"Playwright 启动失败：{exc}") from exc

        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.settings.profile_dir),
                channel=self.settings.browser_channel,
                headless=self.settings.headless if headless is None else headless,
                locale="zh-CN",
                viewport=None,
                accept_downloads=False,
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--disable-features=Translate",
                ],
            )
        except Exception as exc:  # noqa: BLE001
            try:
                playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            message = str(exc)
            lowered = message.lower()
            if any(marker in lowered for marker in _LOCK_MESSAGE_MARKERS):
                raise ProfileInUseError(
                    "浏览器 Profile 已被占用（Chrome 单例锁）："
                    f"{self.settings.profile_dir}。请先关闭 MCP 浏览器或手动 Chrome。",
                    detail={"profile_dir": str(self.settings.profile_dir), "raw": message},
                ) from exc
            raise BrowserLaunchError(
                f"Chrome 启动失败：{message}",
                detail={"channel": self.settings.browser_channel, "preflight": preflight},
            ) from exc

        session = BrowserSession(
            playwright=playwright,
            context=context,
            channel=self.settings.browser_channel,
            profile_dir=str(self.settings.profile_dir),
        )
        try:
            report = session.require_healthy()
        except BrowserNotReadyError:
            session.close()
            raise
        self._session = session
        self._starts += 1
        self._last_health = report
        return session

    # -- 运行期 -----------------------------------------------------------
    @property
    def session(self) -> BrowserSession:
        if self._session is None or self._session.closed:
            raise BrowserNotReadyError("浏览器会话尚未启动")
        return self._session

    def ensure(self, *, headless: bool | None = None) -> BrowserSession:
        """确保有一个健康会话；不健康则重建（保留任务进度由调用方负责）。"""
        if self._session is not None and not self._session.closed:
            report = self._session.health_check()
            self._last_health = report
            if report.ok:
                return self._session
            _LOGGER.warning("健康检查失败，重建会话：%s", report.error)
        self._restarts += 1 if self._session is not None else 0
        return self.start(headless=headless)

    def health(self) -> HealthReport:
        if self._session is None or self._session.closed:
            return HealthReport(ok=False, checked_at="", error="会话未启动")
        self._last_health = self._session.health_check()
        return self._last_health

    def stop(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # -- 生命周期与诊断 ---------------------------------------------------
    def __enter__(self) -> "BrowserManager":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.stop()

    def describe(self) -> dict[str, Any]:
        return {
            "channel": self.settings.browser_channel,
            "headless": self.settings.headless,
            "profile_dir": str(self.settings.profile_dir),
            "starts": self._starts,
            "restarts": self._restarts,
            "running": bool(self._session and not self._session.closed),
            "last_health": self._last_health.to_dict() if self._last_health else None,
        }


def verify_dom_roundtrip(page, html: str, selectors: Sequence[str]) -> dict[str, Any]:  # noqa: ANN001
    """用本地 HTML 验证"导航 → DOM 提取"链路（不联网）。"""
    page.set_content(html, wait_until="domcontentloaded")
    extracted: dict[str, Any] = {"url": page.url, "selectors": {}}
    for selector in selectors:
        locator = page.locator(selector)
        extracted["selectors"][selector] = {
            "count": locator.count(),
            "text": (locator.first.inner_text(timeout=3_000) if locator.count() else None),
        }
    return extracted
