"""动态关键词发现：从真实文章标题/摘要中发现候选就业词组。

原则：
- 只生成**候选**（`engine_dynamic_keywords.status='candidate'`），不自动进入查询队列；
- 必须人工批准后才由 `KeywordPlanner` 读取（来源与基础词库分开记录）；
- 提取是确定性的：锚点词 + 相邻中文片段，频次排序，不与现有词库重复。

不做语义模型推断，也不从评论里抓个人信息。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

ANCHOR_WORDS: tuple[str, ...] = (
    "工资", "月薪", "年包", "薪资", "到手", "社保", "公积金", "五险", "试用期", "转正",
    "实习", "外包", "派遣", "裁员", "辞退", "赔偿", "仲裁", "欠薪", "进厂", "流水线",
    "倒班", "房租", "房租水电", "攒钱", "存款", "求职", "面试", "简历", "招聘", "学历",
    "本科", "大专", "研究生", "硕士", "转行", "离职", "待业", "失业", "躺平", "回老家",
    "县城", "房租占工资", "加班", "大小周", "单休", "offer", "就业", "秋招", "春招",
)

CHINESE_SEGMENT = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9+#]{2,16}")
MIN_OCCURRENCES = 3

# 平台 UI 标签、运营话术、纯话题标签，不作为关键词候选
STOPWORDS: tuple[str, ...] = (
    "招聘线索", "分享求职经历", "秋招有路子", "猜你想搜", "相关推荐", "点击查看",
    "查看更多", "展开全文", "点赞收藏", "关注我", "评论区", "个人观点",
)
MAX_KEYWORD_LEN = 14


@dataclass
class DynamicKeyword:
    keyword: str
    occurrences: int
    sample_item_id: str | None = None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_candidates(
    texts: Iterable[tuple[str, str]],
    *,
    existing: Iterable[str] = (),
    limit: int = 40,
    min_occurrences: int = MIN_OCCURRENCES,
) -> list[DynamicKeyword]:
    """texts: [(item_id, text)] → 候选词组（按出现次数降序）。"""
    known = {item.strip() for item in existing}

    def is_known(segment: str) -> bool:
        """已有词、包含已有词（近似重复）、或被已有词包含，都视为已覆盖。"""
        if segment in known:
            return True
        for item in known:
            if len(item) >= 4 and item in segment:
                return True
            if len(segment) >= 4 and segment in item:
                return True
        return False
    counter: Counter[str] = Counter()
    samples: dict[str, str] = {}

    for item_id, raw in texts:
        text = _normalize(raw)
        if not text:
            continue
        for match in CHINESE_SEGMENT.finditer(text):
            segment = match.group(0).lstrip("#＃").strip()
            if not any(anchor in segment for anchor in ANCHOR_WORDS):
                continue
            if len(segment) > MAX_KEYWORD_LEN:
                continue
            if is_known(segment) or segment in STOPWORDS:
                continue
            # 去掉纯锚点词本身（信息量低）
            if segment in ANCHOR_WORDS:
                continue
            counter[segment] += 1
            samples.setdefault(segment, item_id)

    results = [
        DynamicKeyword(keyword=keyword, occurrences=count, sample_item_id=samples.get(keyword))
        for keyword, count in counter.most_common(limit)
        if count >= min_occurrences
    ]
    return results
