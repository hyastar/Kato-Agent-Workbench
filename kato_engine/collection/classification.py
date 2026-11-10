"""按正文内容做就业生态分类。

原则：
- 分类依据是文章内容，不是搜索关键词；
- 规则是确定性关键词打分，输出可复现；
- 匹配不到时保留 `None`（数据库字段可空），不猜造标签。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 维度关键词：命中即计分（标题权重 3，正文权重 1）。
DIMENSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "salary": (
        "工资", "薪资", "月薪", "到手", "年包", "薪水", "税前", "税后", "存款", "收入",
        "补贴", "年终奖", "涨薪", "调薪", "5k", "6k", "8k", "9k", "10k",
    ),
    "job_search": (
        "找工作", "求职", "简历", "投递", "面试", "招聘", "boss直聘", "智联", "猎聘",
        "岗位", "内推", "hr", "offer", "没回复", "面试官",
    ),
    "probation": (
        "试用期", "转正", "入职", "新人期", "考核期", "试用", "实习转正",
    ),
    "layoff": (
        "裁员", "被裁", "辞退", "劝退", "优化", "失业", "毁约", "解约", "失业金",
        "经济补偿", "n+1", "毕业即失业",
    ),
    "home_idle": (
        "回老家", "回家", "老家", "躺平", "待业", "啃老", "全职儿女", "不上班",
        "县城", "gap", "空窗期", "啃老族",
    ),
    "factory": (
        "进厂", "工厂", "流水线", "电子厂", "倒班", "普工", "车间", "蓝领", "打螺丝",
        "两班倒", "计件",
    ),
    "machinery": (
        "机械", "制造业", "自动化", "工艺", "设备", "模具", "材料", "焊接", "数控",
        "工程机械", "机电",
    ),
    "it": (
        "计算机", "互联网", "程序员", "开发", "算法", "前端", "后端", "测试", "运维",
        "产品经理", "大厂", "ai", "人工智能", "码农", "it行业", "软件",
    ),
    "campus": (
        "秋招", "春招", "校招", "补录", "提前批", "宣讲会", "双选会", "应届", "毕业季",
        "offer", "三方", "签约", "海投",
    ),
    "worklife": (
        "加班", "996", "007", "单休", "双休", "房租", "通勤", "生活成本", "内卷",
        "大小周", "工时", "加班费", "租房",
    ),
}

# 维度 → 旧 topic 枚举（research_items.topic 有 CHECK 约束）。
LEGACY_TOPIC: dict[str, str] = {
    "salary": "salary",
    "job_search": "experience",
    "probation": "experience",
    "layoff": "warning",
    "home_idle": "experience",
    "factory": "experience",
    "machinery": "experience",
    "it": "industry",
    "campus": "recruitment",
    "worklife": "experience",
}

STAGE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("提前批", "early"),
    ("秋招", "autumn"),
    ("春招", "spring"),
    ("补录", "makeup"),
    ("实习", "internship"),
)

STATUS_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("试用期", "probation"),
    ("已入职", "employed"),
    ("在职", "employed"),
    ("裸辞", "left"),
    ("离职", "left"),
    ("辞职", "left"),
    ("被裁", "unemployed"),
    ("失业", "unemployed"),
    ("待业", "unemployed"),
    ("没工作", "unemployed"),
    ("求职", "job_seeking"),
    ("找工作", "job_seeking"),
    ("投简历", "job_seeking"),
    ("躺平", "waiting"),
    ("在家", "waiting"),
)

INDUSTRY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("互联网", "互联网"),
    ("大厂", "互联网"),
    ("制造业", "制造业"),
    ("机械", "制造业"),
    ("工厂", "制造业"),
    ("金融", "金融"),
    ("银行", "金融"),
    ("券商", "金融"),
    ("国企", "国企"),
    ("央企", "国企"),
    ("教师", "教育"),
    ("医院", "医疗"),
    ("护士", "医疗"),
    ("电网", "能源"),
    ("建筑", "建筑"),
    ("土木", "建筑"),
)

SALARY_PATTERN = re.compile(r"(?<![0-9A-Za-z])([0-9]{1,2}(?:\.[0-9])?)\s*[kK千万](?![0-9])")
SALARY_PREFIX_PATTERN = re.compile(r"(工资|薪资|月薪|到手|年包|收入)")

COHORT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("27届", "2027"),
    ("2027届", "2027"),
    ("2027", "2027"),
    ("26届", "2026"),
    ("2026届", "2026"),
    ("2026", "2026"),
    ("25届", "other"),
    ("2025", "other"),
)

RECRUITMENT_AD_MARKERS = ("招聘", "内推", "岗位职责", "任职要求", "简历投递", "扫码", "薪资面议")
SECONDHAND_MARKERS = ("我朋友", "我表姐", "我同学说", "听说", "转述", "网友说", "我室友")


@dataclass
class Classification:
    employment_topic: str | None
    employment_status: str | None
    industry: str | None
    graduation_cohort: str | None
    event_year: int | None
    salary_reported: bool | None
    experience_type: str | None
    legacy_topic: str
    cohort: str
    recruitment_stage: str
    scores: dict[str, int] = field(default_factory=dict)
    matched_topic: bool = False

    def to_db_fields(self) -> dict[str, object]:
        return {
            "employment_topic": self.employment_topic,
            "employment_status": self.employment_status,
            "industry": self.industry,
            "graduation_cohort": self.graduation_cohort,
            "event_year": self.event_year,
            "salary_reported": self.salary_reported,
            "experience_type": self.experience_type,
        }


def _score(text: str, keywords: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(lowered.count(keyword.lower()) for keyword in keywords)


def classify(title: str, body: str) -> Classification:
    title_text = title or ""
    body_text = (body or "")[:20_000]
    scores: dict[str, int] = {}
    for dimension, keywords in DIMENSION_KEYWORDS.items():
        score = _score(title_text, keywords) * 3 + _score(body_text, keywords)
        if score:
            scores[dimension] = score
    topic = max(scores, key=lambda key: scores[key]) if scores else None
    matched = topic is not None and scores.get(topic, 0) > 0

    cohort = "unknown"
    for marker, value in COHORT_PATTERNS:
        if marker in title_text or marker in body_text:
            cohort = value
            break

    stage = "unknown"
    combined = f"{title_text}\n{body_text}"
    for marker, value in STAGE_KEYWORDS:
        if marker in combined:
            stage = value
            break

    status = None
    for marker, value in STATUS_KEYWORDS:
        if marker in combined:
            status = value
            break

    industry = None
    for marker, value in INDUSTRY_KEYWORDS:
        if marker in combined:
            industry = value
            break

    salary_reported = None
    if topic is not None:
        salary_reported = bool(
            SALARY_PATTERN.search(combined) or SALARY_PREFIX_PATTERN.search(combined)
        )

    experience_type = "personal"
    if sum(marker in combined for marker in RECRUITMENT_AD_MARKERS) >= 2:
        experience_type = "recruitment_ad"
    elif any(marker in combined for marker in SECONDHAND_MARKERS):
        experience_type = "secondhand"

    event_year = int(cohort) if cohort in {"2026", "2027"} else None

    return Classification(
        employment_topic=topic,
        employment_status=status,
        industry=industry,
        graduation_cohort=cohort if cohort != "unknown" else None,
        event_year=event_year,
        salary_reported=salary_reported,
        experience_type=experience_type,
        legacy_topic=LEGACY_TOPIC.get(topic or "", "other"),
        cohort=cohort,
        recruitment_stage=stage,
        scores=scores,
        matched_topic=matched,
    )
