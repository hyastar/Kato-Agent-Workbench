"""COCO / YOLO 结构校验的离线测试，全部使用临时 fixture。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts import validate_dataset


class CocoValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "coco-dataset"
        self.root.mkdir()

    def _write(self, payload: Any, images: tuple[str, ...] = ("img1.jpg",)) -> Path:
        for name in images:
            (self.root / name).write_bytes(b"")
        (self.root / "annotations.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return self.root

    def _valid_payload(self) -> dict[str, Any]:
        return {
            "images": [{"id": 1, "file_name": "img1.jpg", "width": 640, "height": 480}],
            "annotations": [
                {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 20, 30, 40], "area": 1200}
            ],
            "categories": [{"id": 1, "name": "person"}],
        }

    def test_valid_coco_passes(self) -> None:
        result = validate_dataset.validate_dataset(self._write(self._valid_payload()))
        self.assertEqual(result.format, "coco")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.stats["images"], 1)
        self.assertEqual(result.stats["annotations"], 1)

    def test_coco_with_broken_references_fails(self) -> None:
        payload = self._valid_payload()
        payload["annotations"] = [
            {"id": 1, "image_id": 999, "category_id": 999, "bbox": [10, 20]}
        ]
        result = validate_dataset.validate_dataset(self._write(payload))
        self.assertFalse(result.ok)
        joined = "\n".join(result.errors)
        self.assertIn("image_id", joined)
        self.assertIn("category_id", joined)
        self.assertIn("bbox", joined)

    def test_coco_with_missing_image_file_warns(self) -> None:
        result = validate_dataset.validate_dataset(
            self._write(self._valid_payload(), images=())
        )
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(any("不存在" in warning for warning in result.warnings))

    def test_coco_duplicate_ids_fail(self) -> None:
        payload = self._valid_payload()
        payload["images"].append({"id": 1, "file_name": "img1.jpg"})
        result = validate_dataset.validate_dataset(self._write(payload))
        self.assertFalse(result.ok)
        self.assertIn("重复", "\n".join(result.errors))

    def test_missing_path_fails(self) -> None:
        result = validate_dataset.validate_dataset(self.root / "does-not-exist")
        self.assertFalse(result.ok)
        self.assertIn("不存在", result.errors[0])


class YoloValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "yolo-dataset"
        (self.root / "images").mkdir(parents=True)
        (self.root / "labels").mkdir(parents=True)

    def _write(self, label_text: str, image_name: str = "a.jpg") -> Path:
        (self.root / "images" / image_name).write_bytes(b"")
        stem = Path(image_name).stem
        (self.root / "labels" / f"{stem}.txt").write_text(label_text, encoding="utf-8")
        return self.root

    def test_valid_yolo_passes(self) -> None:
        result = validate_dataset.validate_dataset(self._write("0 0.5 0.5 0.2 0.2\n1 0.1 0.1 0.05 0.05\n"))
        self.assertEqual(result.format, "yolo")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.stats["images"], 1)
        self.assertEqual(result.stats["labels"], 1)
        self.assertEqual(result.stats["class_ids"], [0, 1])

    def test_out_of_range_coordinates_fail(self) -> None:
        result = validate_dataset.validate_dataset(self._write("0 1.2 0.5 0.2 0.2\n"))
        self.assertFalse(result.ok)
        self.assertIn("[0, 1]", "\n".join(result.errors))

    def test_wrong_column_count_fails(self) -> None:
        result = validate_dataset.validate_dataset(self._write("0 0.5 0.5 0.2\n"))
        self.assertFalse(result.ok)
        self.assertIn("5 列", "\n".join(result.errors))

    def test_missing_label_warns(self) -> None:
        (self.root / "images" / "b.jpg").write_bytes(b"")
        result = validate_dataset.validate_dataset(self._write("0 0.5 0.5 0.2 0.2\n"))
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(any("没有对应标签" in warning for warning in result.warnings))


class FormatDetectionTests(unittest.TestCase):
    def test_unknown_layout_reports_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate_dataset.validate_dataset(directory)
        self.assertFalse(result.ok)
        self.assertEqual(result.format, "unknown")
        self.assertIn("未实现此格式的校验", "\n".join(result.errors))

    def test_explicit_format_is_respected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate_dataset.validate_dataset(directory, format="yolo")
        self.assertEqual(result.format, "yolo")
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
