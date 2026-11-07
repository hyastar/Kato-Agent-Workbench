"""数据集目录的查询与登记 CLI。

用法：
    python -m scripts.catalog list
    python -m scripts.catalog list --status candidate --json
    python -m scripts.catalog add --name "示例数据集" --source roboflow \
        --source-url "https://example.invalid/ds" --version v1 --format coco
    python -m scripts.catalog add --json-file dataset.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts import db


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", help="数据库路径（默认 data/catalog/workbench.sqlite3）")
    parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")


def _build_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.json_file:
        raw = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("--json-file 必须包含一个 JSON 对象")
        payload.update(raw)

    overrides = {
        "name": args.name,
        "source": args.source,
        "source_url": args.source_url,
        "version": args.version,
        "license_name": args.license_name,
        "license_url": args.license_url,
        "format": args.format,
        "image_count": args.image_count,
        "status": args.status,
        "raw_path": args.raw_path,
        "processed_path": args.processed_path,
        "sha256": args.sha256,
    }
    payload.update({key: value for key, value in overrides.items() if value is not None})

    for required in ("name", "source", "source_url"):
        if not str(payload.get(required) or "").strip():
            raise ValueError(f"缺少必填字段：{required}")

    if payload.get("status") and payload["status"] not in db.DATASET_STATUSES:
        raise ValueError(f"不支持的 status：{payload['status']}（可选：{', '.join(db.DATASET_STATUSES)}）")

    if payload.get("image_count") is not None:
        try:
            payload["image_count"] = int(payload["image_count"])
        except (TypeError, ValueError) as exc:
            raise ValueError("image_count 必须是整数") from exc
        if payload["image_count"] < 0:
            raise ValueError("image_count 不能为负数")

    for key in ("raw_path", "processed_path"):
        if payload.get(key):
            payload[key] = db.to_repo_relative(str(payload[key]))
    return payload


def _print_table(rows: list[Any]) -> None:
    if not rows:
        print("（无记录）")
        return

    headers = ("dataset_id", "name", "source", "version", "status", "format", "images", "license")
    widths = (20, 28, 12, 10, 12, 8, 8, 20)
    print("  ".join(header.ljust(width) for header, width in zip(headers, widths)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        values = (
            row["dataset_id"],
            row["name"],
            row["source"],
            row["version"] or "",
            row["status"],
            row["format"] or "",
            "" if row["image_count"] is None else str(row["image_count"]),
            row["license_name"] or "",
        )
        print("  ".join(str(value)[:width].ljust(width) for value, width in zip(values, widths)))


def _command_list(args: argparse.Namespace) -> int:
    conn = db.connect_ready(args.db)
    try:
        rows = db.list_datasets(conn, status=args.status, source=args.source, limit=args.limit)
    finally:
        conn.close()

    if args.as_json:
        print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
    else:
        _print_table(rows)
        print(f"\n共 {len(rows)} 条记录。")
    return 0


def _command_add(args: argparse.Namespace) -> int:
    try:
        payload = _build_payload(args)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        return 2

    conn = db.connect_ready(args.db)
    try:
        dataset_id, created = db.upsert_dataset(conn, **payload)
    except ValueError as exc:
        print(f"登记失败：{exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    result = {"dataset_id": dataset_id, "created": created}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        action = "新建" if created else "更新"
        print(f"{action}数据集：{dataset_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="查询或登记数据集元信息")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="列出数据集")
    _add_common_arguments(list_parser)
    list_parser.add_argument("--status", choices=db.DATASET_STATUSES, help="按状态过滤")
    list_parser.add_argument("--source", help="按来源过滤")
    list_parser.add_argument("--limit", type=int, help="最多返回条数")
    list_parser.set_defaults(handler=_command_list)

    add_parser = subparsers.add_parser("add", help="登记或更新一条数据集元信息")
    _add_common_arguments(add_parser)
    add_parser.add_argument("--json-file", type=Path, help="从 JSON 文件读取字段（CLI 参数优先）")
    add_parser.add_argument("--name", help="数据集名称")
    add_parser.add_argument("--source", help="来源，如 roboflow")
    add_parser.add_argument("--source-url", dest="source_url", help="来源页面 URL")
    add_parser.add_argument("--version", help="数据集版本")
    add_parser.add_argument("--license-name", dest="license_name", help="许可名称")
    add_parser.add_argument("--license-url", dest="license_url", help="许可链接")
    add_parser.add_argument("--format", help="导出格式，如 coco / yolo")
    add_parser.add_argument("--image-count", dest="image_count", type=int, help="图片数量")
    add_parser.add_argument(
        "--status",
        choices=db.DATASET_STATUSES,
        help="数据集状态（默认 candidate）",
    )
    add_parser.add_argument("--raw-path", dest="raw_path", help="原始文件路径")
    add_parser.add_argument("--processed-path", dest="processed_path", help="处理后路径")
    add_parser.add_argument("--sha256", help="原始包 SHA-256")
    add_parser.set_defaults(handler=_command_add)

    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:  # noqa: BLE001 - CLI 边界需要统一报告
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
