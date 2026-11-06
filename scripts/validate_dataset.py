"""离线校验已下载数据集的目录结构（COCO / YOLO）。

只做结构一致性检查，不做图像内容、标签质量或许可合规判断。
不需要网络，也不会修改被检查的文件。

用法：
    python -m scripts.validate_dataset data/raw/roboflow/example/v1
    python -m scripts.validate_dataset path/to/annotations.json --format coco
    python -m scripts.validate_dataset data/raw/... --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts import db

MAX_ERRORS = 50
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
QUALITY_DISCLAIMER = "结构检查通过（不代表数据质量合格）"


@dataclass
class ValidationResult:
    path: str
    format: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _add_error(result: ValidationResult, message: str) -> None:
    if len(result.errors) < MAX_ERRORS:
        result.errors.append(message)
    elif len(result.errors) == MAX_ERRORS:
        result.errors.append(f"错误过多，其余错误已省略（上限 {MAX_ERRORS} 条）。")


def _add_warning(result: ValidationResult, message: str) -> None:
    if len(result.warnings) < MAX_ERRORS:
        result.warnings.append(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def resolve_input(target: str | Path) -> Path:
    path = Path(target).expanduser()
    if not path.is_absolute():
        path = db.REPO_ROOT / path
    return path


def _coco_candidates(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix.lower() == ".json" else []
    candidates: list[Path] = []
    seen: set[Path] = set()
    for pattern in ("*.json", "annotations/*.json", "*/annotations/*.json"):
        for candidate in sorted(target.glob(pattern)):
            if not candidate.is_file() or candidate in seen:
                continue
            seen.add(candidate)
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(data, dict) and {"images", "annotations", "categories"} <= data.keys():
                candidates.append(candidate)
    return candidates


def detect_format(target: Path) -> str:
    if target.is_file():
        return "coco" if target.suffix.lower() == ".json" else "unknown"
    if (target / "images").is_dir() and (target / "labels").is_dir():
        return "yolo"
    if _coco_candidates(target):
        return "coco"
    return "unknown"


def validate_coco(target: Path) -> ValidationResult:
    result = ValidationResult(str(target), "coco")
    candidates = _coco_candidates(target)
    if not candidates:
        _add_error(
            result,
            "未找到 COCO 标注 JSON（需为对象且包含 images、annotations、categories）",
        )
        return result
    if len(candidates) > 1:
        _add_warning(
            result,
            f"发现 {len(candidates)} 个候选 COCO JSON，仅校验第一个：{candidates[0].name}",
        )

    annotation_file = candidates[0]
    try:
        data = json.loads(annotation_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        _add_error(result, f"无法读取 {annotation_file.name}：{exc}")
        return result
    if not isinstance(data, dict):
        _add_error(result, f"{annotation_file.name} 顶层必须是 JSON 对象")
        return result

    images = data.get("images")
    annotations = data.get("annotations")
    categories = data.get("categories")

    image_ids: set[int] = set()
    if not isinstance(images, list) or not images:
        _add_error(result, "images 必须是非空数组")
    else:
        missing_files = 0
        for index, item in enumerate(images):
            if not isinstance(item, dict):
                _add_error(result, f"images[{index}] 不是对象")
                continue
            image_id = item.get("id")
            if not _is_int(image_id):
                _add_error(result, f"images[{index}].id 必须是整数")
            elif image_id in image_ids:
                _add_error(result, f"images 中 id 重复：{image_id}")
            else:
                image_ids.add(image_id)
            file_name = item.get("file_name")
            if not isinstance(file_name, str) or not file_name.strip():
                _add_error(result, f"images[{index}].file_name 必须是非空字符串")
            elif target.is_dir() and not (target / file_name).is_file():
                missing_files += 1
        if missing_files:
            _add_warning(result, f"images 列表中有 {missing_files} 个 file_name 在目录中不存在")

    category_ids: set[int] = set()
    if not isinstance(categories, list) or not categories:
        _add_error(result, "categories 必须是非空数组")
    else:
        for index, item in enumerate(categories):
            if not isinstance(item, dict):
                _add_error(result, f"categories[{index}] 不是对象")
                continue
            category_id = item.get("id")
            if not _is_int(category_id):
                _add_error(result, f"categories[{index}].id 必须是整数")
            elif category_id in category_ids:
                _add_error(result, f"categories 中 id 重复：{category_id}")
            else:
                category_ids.add(category_id)
            if not isinstance(item.get("name"), str) or not item.get("name", "").strip():
                _add_error(result, f"categories[{index}].name 必须是非空字符串")

    annotation_ids: set[int] = set()
    if not isinstance(annotations, list):
        _add_error(result, "annotations 必须是数组")
    else:
        if not annotations:
            _add_warning(result, "annotations 为空")
        for index, item in enumerate(annotations):
            if not isinstance(item, dict):
                _add_error(result, f"annotations[{index}] 不是对象")
                continue
            annotation_id = item.get("id")
            if annotation_id is not None:
                if not _is_int(annotation_id):
                    _add_error(result, f"annotations[{index}].id 必须是整数")
                elif annotation_id in annotation_ids:
                    _add_error(result, f"annotations 中 id 重复：{annotation_id}")
                else:
                    annotation_ids.add(annotation_id)

            image_id = item.get("image_id")
            if not _is_int(image_id):
                _add_error(result, f"annotations[{index}].image_id 必须是整数")
            elif image_ids and image_id not in image_ids:
                _add_error(result, f"annotations[{index}].image_id 引用了不存在的图片：{image_id}")

            category_id = item.get("category_id")
            if not _is_int(category_id):
                _add_error(result, f"annotations[{index}].category_id 必须是整数")
            elif category_ids and category_id not in category_ids:
                _add_error(
                    result,
                    f"annotations[{index}].category_id 引用了不存在的类别：{category_id}",
                )

            bbox = item.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                _add_error(result, f"annotations[{index}].bbox 必须是长度为 4 的数组")
            elif not all(_is_number(value) for value in bbox):
                _add_error(result, f"annotations[{index}].bbox 必须全部是数字")
            elif bbox[2] <= 0 or bbox[3] <= 0:
                _add_error(result, f"annotations[{index}].bbox 的宽和高必须为正数")

            if "area" in item and not _is_number(item["area"]):
                _add_error(result, f"annotations[{index}].area 必须是数字")

    result.stats = {
        "annotation_file": db.to_repo_relative(annotation_file),
        "images": len(images) if isinstance(images, list) else 0,
        "annotations": len(annotations) if isinstance(annotations, list) else 0,
        "categories": len(categories) if isinstance(categories, list) else 0,
    }
    return result


def _collect_files(directory: Path, suffixes: set[str]) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    )


def validate_yolo(target: Path) -> ValidationResult:
    result = ValidationResult(str(target), "yolo")
    if not target.is_dir():
        _add_error(result, "YOLO 校验需要一个目录（包含 images/ 与 labels/）")
        return result

    images_dir = target / "images"
    labels_dir = target / "labels"
    if not images_dir.is_dir():
        _add_error(result, "缺少 images/ 目录")
    if not labels_dir.is_dir():
        _add_error(result, "缺少 labels/ 目录")
    if result.errors:
        return result

    image_files = _collect_files(images_dir, IMAGE_SUFFIXES)
    label_files = _collect_files(labels_dir, {".txt"})
    if not image_files:
        _add_error(result, "images/ 中没有图片文件")
    if not label_files:
        _add_warning(result, "labels/ 中没有标签文件")

    label_stems = {
        (label.relative_to(labels_dir).with_suffix("").as_posix()) for label in label_files
    }
    class_ids: set[int] = set()
    invalid_lines = 0

    for label in label_files:
        try:
            lines = label.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            _add_error(result, f"无法读取 {label.name}：{exc}")
            continue

        content = [line.strip() for line in lines if line.strip()]
        if not content:
            _add_warning(result, f"{label.relative_to(target).as_posix()} 是空标签文件")
            continue

        for line_number, line in enumerate(content, start=1):
            parts = line.split()
            if len(parts) != 5:
                _add_error(
                    result,
                    f"{label.relative_to(target).as_posix()}:{line_number} 应为 5 列，实际 {len(parts)} 列",
                )
                invalid_lines += 1
                continue
            try:
                class_id = int(parts[0])
                coordinates = [float(value) for value in parts[1:]]
            except ValueError:
                _add_error(
                    result,
                    f"{label.relative_to(target).as_posix()}:{line_number} 含非数字字段",
                )
                invalid_lines += 1
                continue
            if class_id < 0:
                _add_error(
                    result,
                    f"{label.relative_to(target).as_posix()}:{line_number} 类别 ID 不能为负",
                )
                invalid_lines += 1
                continue
            class_ids.add(class_id)
            if any(not math.isfinite(value) or value < 0 or value > 1 for value in coordinates):
                _add_error(
                    result,
                    f"{label.relative_to(target).as_posix()}:{line_number} 坐标必须位于 [0, 1]",
                )
                invalid_lines += 1
            elif coordinates[2] <= 0 or coordinates[3] <= 0:
                _add_error(
                    result,
                    f"{label.relative_to(target).as_posix()}:{line_number} 宽和高必须为正数",
                )
                invalid_lines += 1

    image_stems = {
        image.relative_to(images_dir).with_suffix("").as_posix() for image in image_files
    }
    missing_labels = len(image_stems - label_stems)
    orphan_labels = len(label_stems - image_stems)
    if missing_labels:
        _add_warning(result, f"{missing_labels} 张图片没有对应标签文件（可能是背景图）")
    if orphan_labels:
        _add_warning(result, f"{orphan_labels} 个标签文件没有对应图片")

    data_yaml = target / "data.yaml"
    if data_yaml.is_file():
        try:
            text = data_yaml.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _add_warning(result, f"无法读取 data.yaml：{exc}")
        else:
            if "names" not in text and "nc" not in text:
                _add_warning(result, "data.yaml 中未发现 names/nc 字段")
            _add_warning(result, "仅对 data.yaml 做文本级检查，未完整解析 YAML")

    result.stats = {
        "images": len(image_files),
        "labels": len(label_files),
        "class_ids": sorted(class_ids),
        "invalid_label_lines": invalid_lines,
        "missing_labels": missing_labels,
        "orphan_labels": orphan_labels,
    }
    return result


def validate_dataset(target: str | Path, format: str = "auto") -> ValidationResult:
    path = resolve_input(target)
    if format not in {"auto", "coco", "yolo"}:
        raise ValueError(f"不支持的格式：{format}")

    if not path.exists():
        return ValidationResult(str(path), format, errors=[f"路径不存在：{path}"])

    resolved_format = detect_format(path) if format == "auto" else format
    if resolved_format == "unknown":
        return ValidationResult(
            str(path),
            "unknown",
            errors=["未实现此格式的校验（当前仅支持 COCO 与 YOLO，可用 --format 显式指定）"],
        )
    if resolved_format == "coco":
        return validate_coco(path)
    return validate_yolo(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线校验数据集目录结构（COCO / YOLO）")
    parser.add_argument("path", help="数据集目录或 COCO 标注 JSON 路径")
    parser.add_argument("--format", choices=("auto", "coco", "yolo"), default="auto")
    parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")
    args = parser.parse_args(argv)

    try:
        result = validate_dataset(args.path, args.format)
    except (OSError, ValueError) as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(
            json.dumps(
                {
                    "path": db.to_repo_relative(result.path),
                    "format": result.format,
                    "ok": result.ok,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "stats": result.stats,
                    "note": QUALITY_DISCLAIMER if result.ok else "结构检查未通过",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"路径：{db.to_repo_relative(result.path)}")
        print(f"格式：{result.format}")
        print(f"结论：{QUALITY_DISCLAIMER if result.ok else f'结构检查未通过（{len(result.errors)} 个错误）'}")
        if result.stats:
            stats = ", ".join(f"{key}={value}" for key, value in sorted(result.stats.items()))
            print(f"统计：{stats}")
        if result.errors:
            print("错误：")
            for message in result.errors:
                print(f"  - {message}")
        if result.warnings:
            print("警告：")
            for message in result.warnings:
                print(f"  - {message}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
