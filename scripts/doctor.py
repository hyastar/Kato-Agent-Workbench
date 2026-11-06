"""本地环境与项目健康检查；不访问任何外部网站。

用法：
    python -m scripts.doctor
    python -m scripts.doctor --json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts import db

ENV_NAME = "Kato-Agent-Workbench"
NODE_MIN_MAJOR = 24
DISK_WARN_BYTES = 2 * 1024**3


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""


def _version_line(command: list[str]) -> str | None:
    executable = shutil.which(command[0])
    if executable is None:
        return None
    argv = [executable, *command[1:]]
    # Windows 上 npx 是 .CMD 包装脚本，CreateProcess 不能直接执行。
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        argv = ["cmd", "/c", *argv]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    output = (completed.stdout or completed.stderr).strip()
    return output.splitlines()[0] if output else None


def check_python() -> Check:
    version = platform.python_version()
    if sys.version_info[:2] == (3, 12):
        return Check("Python 3.12", "PASS", f"{version}（{sys.executable}）")
    return Check(
        "Python 3.12",
        "FAIL",
        f"当前为 {version}（{sys.executable}），项目要求 3.12",
        "conda activate Kato-Agent-Workbench 后重新运行",
    )


def check_conda_env() -> Check:
    active = os.environ.get("CONDA_DEFAULT_ENV", "")
    prefix_name = Path(sys.prefix).name
    detail = f"CONDA_DEFAULT_ENV={active or '未设置'}；sys.prefix={sys.prefix}"
    if active == ENV_NAME or prefix_name.lower() == ENV_NAME.lower():
        return Check("Conda 环境", "PASS", detail)
    return Check(
        "Conda 环境",
        "WARN",
        detail + f"；预期环境名为 {ENV_NAME}",
        f"conda env create -f environment.yml 或 conda activate {ENV_NAME}",
    )


def check_node() -> list[Check]:
    checks: list[Check] = []
    node_path = shutil.which("node")
    if not node_path:
        checks.append(
            Check("Node.js", "WARN", "未找到 node", "安装 Node.js LTS（优先 26，回退 24）")
        )
    else:
        version = _version_line(["node", "--version"])
        if version is None:
            checks.append(Check("Node.js", "WARN", f"无法执行：{node_path}", "检查 Node.js 安装"))
        else:
            match = re.match(r"v?(\d+)", version)
            major = int(match.group(1)) if match else 0
            if major >= NODE_MIN_MAJOR:
                checks.append(Check("Node.js", "PASS", f"{version}（{node_path}）"))
            else:
                checks.append(
                    Check(
                        "Node.js",
                        "WARN",
                        f"{version} 过旧，Playwright MCP 需要较新的 LTS",
                        "升级到 Node.js 24 或 26 LTS",
                    )
                )

    npx_path = shutil.which("npx")
    if not npx_path:
        checks.append(Check("npx", "WARN", "未找到 npx", "安装 Node.js 后随附；检查 PATH"))
    else:
        version = _version_line(["npx", "--version"])
        checks.append(
            Check("npx", "PASS" if version else "WARN", f"{version or '已找到'}（{npx_path}）")
        )
    return checks


def check_mcp_config() -> Check:
    config_path = db.REPO_ROOT / ".codex" / "config.toml"
    if not config_path.is_file():
        return Check(
            "Playwright MCP 配置",
            "WARN",
            f"未找到 {config_path}",
            "创建 .codex/config.toml 并配置 mcp_servers.playwright",
        )
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return Check("Playwright MCP 配置", "FAIL", f"无法解析：{exc}", "修正 TOML 语法")

    server = data.get("mcp_servers", {}).get("playwright")
    if not isinstance(server, dict) or not server.get("command"):
        return Check(
            "Playwright MCP 配置",
            "WARN",
            "配置文件中缺少 mcp_servers.playwright.command",
            "参考 docs/MCP_SETUP.md",
        )

    command = str(server["command"])
    args = [str(item) for item in server.get("args", [])]
    return Check(
        "Playwright MCP 配置",
        "PASS",
        f"{command} {' '.join(args)}（配置存在；未建立实际 MCP 连接验证）",
    )


def check_database(db_path: str | None) -> Check:
    path = db.resolve_db_path(db_path)
    if not path.is_file():
        return Check(
            "SQLite 数据库",
            "WARN",
            f"尚未初始化：{path}",
            "python -m scripts.init_db",
        )
    try:
        conn = db.connect(path)
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            missing = [table for table in db.REQUIRED_TABLES if table not in tables]
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        return Check("SQLite 数据库", "FAIL", f"无法打开或检查：{exc}", "重新运行 scripts.init_db")

    if missing:
        return Check(
            "SQLite 数据库",
            "FAIL",
            f"缺少表：{', '.join(missing)}（user_version={version}）",
            "python -m scripts.init_db",
        )
    if integrity != "ok" or version < 1:
        return Check(
            "SQLite 数据库",
            "FAIL",
            f"integrity_check={integrity}，user_version={version}",
            "备份后重建数据库；检查磁盘错误",
        )
    return Check(
        "SQLite 数据库",
        "PASS",
        f"{path}（user_version={version}，表齐全，integrity=ok）",
    )


def _is_writable(directory: Path) -> bool:
    try:
        handle, name = tempfile.mkstemp(dir=directory, prefix=".doctor-")
        os.close(handle)
        os.unlink(name)
        return True
    except OSError:
        return False


def check_directories() -> Check:
    required = ("data/raw", "data/processed", "data/metadata", "data/catalog", "workspace", "runs")
    missing = [name for name in required if not (db.REPO_ROOT / name).is_dir()]
    unwritable = [
        name
        for name in required
        if (db.REPO_ROOT / name).is_dir() and not _is_writable(db.REPO_ROOT / name)
    ]
    if unwritable:
        return Check(
            "项目目录",
            "FAIL",
            f"不可写：{', '.join(unwritable)}",
            "检查磁盘权限或只读挂载",
        )
    if missing:
        return Check(
            "项目目录",
            "WARN",
            f"缺少目录：{', '.join(missing)}",
            "python -m scripts.init_db",
        )
    return Check("项目目录", "PASS", "数据、工作区、运行目录齐全且可写")


def check_gitignore() -> Check:
    path = db.REPO_ROOT / ".gitignore"
    if not path.is_file():
        return Check(".gitignore", "WARN", "未找到 .gitignore", "恢复仓库中的 .gitignore")
    text = path.read_text(encoding="utf-8")
    required_patterns = ("data/catalog/*.sqlite3", ".env")
    missing = [pattern for pattern in required_patterns if pattern not in text]
    if missing:
        return Check(
            ".gitignore",
            "WARN",
            f"缺少忽略规则：{', '.join(missing)}",
            "补充 .gitignore，避免提交数据库与密钥",
        )
    return Check(".gitignore", "PASS", "已忽略数据库、数据文件与 .env")


def check_disk() -> Check:
    try:
        free = shutil.disk_usage(db.REPO_ROOT).free
    except OSError as exc:
        return Check("磁盘空间", "WARN", f"无法读取：{exc}")
    free_gib = free / 1024**3
    if free < DISK_WARN_BYTES:
        return Check("磁盘空间", "WARN", f"剩余 {free_gib:.1f} GiB", "清理空间后再下载数据集")
    return Check("磁盘空间", "PASS", f"剩余 {free_gib:.1f} GiB")


def run_checks(db_path: str | None = None) -> list[Check]:
    checks = [
        check_python(),
        check_conda_env(),
        *check_node(),
        check_mcp_config(),
        check_database(db_path),
        check_directories(),
        check_gitignore(),
        check_disk(),
    ]
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 Kato-Agent-Workbench 本地环境（不联网）")
    parser.add_argument("--db", help="数据库路径（默认 data/catalog/workbench.sqlite3）")
    parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")
    args = parser.parse_args(argv)

    checks = run_checks(args.db)
    counts = {status: sum(1 for check in checks if check.status == status) for status in ("PASS", "WARN", "FAIL")}

    if args.as_json:
        print(
            json.dumps(
                {
                    "repository": str(db.REPO_ROOT),
                    "checks": [asdict(check) for check in checks],
                    "summary": counts,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"Kato-Agent-Workbench doctor\n仓库：{db.REPO_ROOT}\n")
        for check in checks:
            print(f"[{check.status}] {check.name}: {check.detail}")
            if check.hint:
                print(f"       建议：{check.hint}")
        print(f"\n汇总：PASS={counts['PASS']}  WARN={counts['WARN']}  FAIL={counts['FAIL']}")

    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
