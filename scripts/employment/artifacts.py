"""文件产物路径、写入与 SHA-256。"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EMPLOYMENT_ROOT = REPO_ROOT / "data" / "employment"

KIND_DIRS = {
    "post_markdown": "posts",
    "comments_markdown": "comments",
    "index": "indexes",
    "report": "reports",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_path(
    platform: str,
    item_id: str,
    kind: str,
    *,
    root: str | Path | None = None,
) -> Path:
    """生成产物绝对路径。

    posts/<item_id>.md
    comments/<item_id>.comments.md
    indexes/<name>.md
    reports/<name>.md
    """
    if kind not in KIND_DIRS:
        raise ValueError(f"不支持的产物类型：{kind}")
    base = Path(root) if root is not None else EMPLOYMENT_ROOT
    directory = base / platform / KIND_DIRS[kind]
    if kind == "post_markdown":
        name = f"{item_id}.md"
    elif kind == "comments_markdown":
        name = f"{item_id}.comments.md"
    else:
        name = f"{item_id}.md"
    return directory / name


def write_text_artifact(path: str | Path, content: str) -> dict[str, str | int]:
    """写入文本产物并返回相对路径、SHA-256 与字节数。

    使用 newline="" 保留原始换行，确保 SH-256 与文件字节一致（Windows 下
    默认写入会把 \\n 转成 \\r\\n）。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    try:
        relative = target.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        relative = str(target)
    return {
        "relative_path": relative,
        "sha256": sha256_file(target),
        "size_bytes": target.stat().st_size,
    }
