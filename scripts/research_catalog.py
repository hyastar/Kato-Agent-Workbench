"""就业/行业情报条目的导入、查询与导出 CLI。

用法：
    python -m scripts.research_catalog add --json-file record.json
    python -m scripts.research_catalog add --json-file records.json --run-id <run-id>
    python -m scripts.research_catalog list --cohort 2027
    python -m scripts.research_catalog list --platform zhihu --topic recruitment
    python -m scripts.research_catalog list --verification unverified --json
    python -m scripts.research_catalog export --format json

只读写本地 SQLite；不联网、不抓取网页。网页内容由宿主 Agent 在授权范围内
观察并组织成 JSON 后交给本 CLI 入库。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts import db

ALLOWED_FIELDS: tuple[str, ...] = (
    "platform",
    "canonical_url",
    "title",
    "summary",
    "source_type",
    "topic",
    "cohort",
    "recruitment_stage",
    "company",
    "city",
    "published_at",
    "collected_at",
    "verification_status",
    "verification_url",
    "verified_at",
)
REQUIRED_FIELDS: tuple[str, ...] = (
    "platform",
    "canonical_url",
    "title",
    "source_type",
    "topic",
    "cohort",
    "recruitment_stage",
)


def _add_db_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", help="数据库路径（默认 data/catalog/workbench.sqlite3）")


def _add_filter_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cohort", choices=db.RESEARCH_COHORTS, help="按届别过滤")
    parser.add_argument("--platform", choices=db.RESEARCH_PLATFORMS, help="按平台过滤")
    parser.add_argument("--topic", choices=db.RESEARCH_TOPICS, help="按主题过滤")
    parser.add_argument(
        "--verification", choices=db.VERIFICATION_STATUSES, help="按核验状态过滤"
    )
    parser.add_argument("--limit", type=int, help="最多返回条数")


def _load_records(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        if not raw:
            raise ValueError("JSON 文件中的数组为空")
        if not all(isinstance(item, dict) for item in raw):
            raise ValueError("JSON 数组的每一项都必须是对象")
        return raw
    raise ValueError("--json-file 必须是 JSON 对象或对象数组")


def _build_payload(record: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(record) - set(ALLOWED_FIELDS))
    if unknown:
        raise ValueError(f"包含未知字段：{', '.join(unknown)}")
    missing = [
        field for field in REQUIRED_FIELDS if not str(record.get(field) or "").strip()
    ]
    if missing:
        raise ValueError(f"缺少必填字段：{', '.join(missing)}")

    payload: dict[str, Any] = {}
    for field in ALLOWED_FIELDS:
        value = record.get(field)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                value = None
        payload[field] = value

    # 规范化 URL 在 db.upsert_research_item 中完成；这里仅做可读性预检。
    db.normalize_url(str(payload["canonical_url"]))
    return payload


def _print_table(rows: list[Any]) -> None:
    if not rows:
        print("（无记录）")
        return
    headers = ("item_id", "platform", "cohort", "topic", "stage", "verification", "title")
    widths = (18, 12, 8, 12, 10, 12, 40)
    print("  ".join(header.ljust(width) for header, width in zip(headers, widths)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        values = (
            row["item_id"],
            row["platform"],
            row["cohort"],
            row["topic"],
            row["recruitment_stage"],
            row["verification_status"],
            row["title"],
        )
        print(
            "  ".join(
                str(value)[:width].ljust(width)
                for value, width in zip(values, widths)
            )
        )


def _command_add(args: argparse.Namespace) -> int:
    try:
        records = _load_records(args.json_file)
        payloads = [_build_payload(record) for record in records]
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        return 2

    conn = db.connect_ready(args.db)
    try:
        results = []
        for payload in payloads:
            item_id, created = db.upsert_research_item(conn, **payload)
            if args.run_id:
                db.link_run_research_item(conn, args.run_id, item_id, args.action)
            results.append({"item_id": item_id, "created": created})
    except ValueError as exc:
        print(f"登记失败：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - 外键/数据库错误需要可读报告
        print(f"登记失败：{exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False))
    else:
        for result in results:
            action = "新建" if result["created"] else "更新"
            print(f"{action}研究条目：{result['item_id']}")
    return 0


def _query(args: argparse.Namespace) -> list[Any]:
    conn = db.connect_ready(args.db)
    try:
        return db.list_research_items(
            conn,
            cohort=args.cohort,
            platform=args.platform,
            topic=args.topic,
            verification=args.verification,
            limit=args.limit,
        )
    finally:
        conn.close()


def _command_list(args: argparse.Namespace) -> int:
    rows = _query(args)
    if args.as_json:
        print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
    else:
        _print_table(rows)
        print(f"\n共 {len(rows)} 条记录。")
    return 0


def _command_export(args: argparse.Namespace) -> int:
    rows = _query(args)
    payload = json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
        print(f"已导出 {len(rows)} 条记录：{target}")
    else:
        print(payload)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导入、查询或导出就业情报研究条目")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="从 JSON 文件导入记录")
    _add_db_argument(add_parser)
    add_parser.add_argument("--json-file", type=Path, required=True, help="JSON 对象或对象数组")
    add_parser.add_argument("--run-id", help="关联到某次执行（写入 run_research_items）")
    add_parser.add_argument(
        "--action",
        choices=db.RESEARCH_ACTIONS,
        default="imported",
        help="关联动作（默认 imported）",
    )
    add_parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")
    add_parser.set_defaults(handler=_command_add)

    list_parser = subparsers.add_parser("list", help="查询研究条目")
    _add_db_argument(list_parser)
    _add_filter_arguments(list_parser)
    list_parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")
    list_parser.set_defaults(handler=_command_list)

    export_parser = subparsers.add_parser("export", help="导出研究条目")
    _add_db_argument(export_parser)
    _add_filter_arguments(export_parser)
    export_parser.add_argument("--format", choices=("json",), default="json", help="导出格式")
    export_parser.add_argument("--output", help="写入文件（默认输出到 stdout）")
    export_parser.set_defaults(handler=_command_export)

    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:  # noqa: BLE001 - CLI 边界需要统一报告
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
