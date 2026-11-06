"""初始化项目目录与 SQLite 数据库；重复执行不删除已有数据。

用法：
    python -m scripts.init_db
    python -m scripts.init_db --db data/catalog/workbench.sqlite3
"""

from __future__ import annotations

import argparse
import sys

from scripts import db

PROJECT_DIRS: tuple[str, ...] = (
    "data/raw",
    "data/processed",
    "data/metadata",
    "data/catalog",
    "workspace",
    "runs",
    "tasks/archive",
)


def ensure_directories() -> list[str]:
    """创建运行所需目录，返回本次新建的相对路径。"""
    created: list[str] = []
    for relative in PROJECT_DIRS:
        directory = db.REPO_ROOT / relative
        if not directory.is_dir():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(relative)
    return created


def initialize(db_path: str | None = None) -> tuple[str, db.MigrationResult, list[str], list[str]]:
    created = ensure_directories()
    path = db.resolve_db_path(db_path)
    conn = db.connect(path)
    try:
        result = db.apply_migrations(conn)
        tables = sorted(
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        missing = [table for table in db.REQUIRED_TABLES if table not in tables]
        if missing:
            raise RuntimeError(f"迁移后缺少必要的表：{', '.join(missing)}")

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"数据库完整性检查失败：{integrity}")
    finally:
        conn.close()

    return str(path), result, created, tables


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="初始化 Kato-Agent-Workbench 目录与 SQLite 数据库")
    parser.add_argument("--db", help="数据库路径（默认 data/catalog/workbench.sqlite3）")
    parser.add_argument("--quiet", action="store_true", help="只输出最终结果")
    args = parser.parse_args(argv)

    try:
        path, result, created, tables = initialize(args.db)
    except Exception as exc:  # noqa: BLE001 - CLI 边界需要统一报告
        print(f"初始化失败：{exc}", file=sys.stderr)
        return 1

    if created and not args.quiet:
        print("已创建目录：")
        for relative in created:
            print(f"  - {relative}")

    if result.applied:
        versions = ", ".join(f"{version:03d}" for version in result.applied)
        print(f"迁移已应用：user_version {result.from_version} -> {result.to_version}（{versions}）")
    else:
        print(f"数据库已是最新版本：user_version = {result.to_version}，未执行迁移")

    print(f"数据库：{path}")
    print(f"数据表：{', '.join(tables)}")
    print("初始化完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
