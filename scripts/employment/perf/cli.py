"""性能事件汇总与 A/B 比较 CLI。"""

from __future__ import annotations

import argparse
import json

from scripts.employment.perf.aggregate import summarize_file
from scripts.employment.perf.compare import adoption_gate, compare_summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="就业采集性能汇总与 A/B 比较")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary_parser = subparsers.add_parser("summary", help="汇总一个事件 JSONL")
    summary_parser.add_argument("--events", required=True, help="events.jsonl 路径")
    summary_parser.add_argument("--output", help="写入 JSON 文件（默认打印）")

    compare_parser = subparsers.add_parser("compare", help="比较基线与优化事件")
    compare_parser.add_argument("--baseline", required=True)
    compare_parser.add_argument("--optimized", required=True)
    compare_parser.add_argument("--required-speedup", type=float, default=1.3)

    args = parser.parse_args(argv)
    if args.command == "summary":
        payload = summarize_file(args.events)
    else:
        baseline = summarize_file(args.baseline)
        optimized = summarize_file(args.optimized)
        payload = {
            "comparison": compare_summaries(baseline, optimized),
            "gate": adoption_gate(
                baseline, optimized, required_speedup=args.required_speedup
            ),
        }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if getattr(args, "output", None):
        from pathlib import Path

        Path(args.output).write_text(text, encoding="utf-8", newline="")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
