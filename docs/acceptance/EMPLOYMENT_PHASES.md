# 就业情报工作流 — 阶段验收摘要

> 本文件只记录**脱敏**的阶段状态、测试结果与统计数字。
> 不写入平台正文、账号信息、Cookie、Profile 路径细节、完整采集内容或私密地址。
> 每个阶段完成后**追加**记录，不改写历史条目。

## 阶段总览

| 阶段 | 内容 | 状态 | 提交标题 |
|---|---|---|---|
| ① | 规则与任务入口 | 完成 | 文档：新增就业情报任务与浏览器协作规范 |
| ② | SQLite 与工具 | 完成 | 功能：新增就业情报数据库与去重查询工具 |
| ③ | 浏览器与端到端联调 | 未开始 | 测试：完成就业平台浏览器联调与权限核查 |
| ④ | 小规模真实调研 | 未开始 | 验证：完成应届生就业信息实测与入库核验 |
| ⑤ | 文档与最终回归 | 未开始 | 文档：完善就业情报工作流使用与验收说明 |

## 阶段 ① — 规则与任务入口

- 日期：2026-11-09
- 变更：
  - `AGENTS.md` 增补具名任务入口、社交平台安全规则、分阶段 Git 交付规则；
  - 新增 `tasks/EMPLOYMENT_2026_2027.md` 具名任务；
  - 新增 `tasks/presets/EMPLOYMENT_2026_2027.md` 预设；
  - 通用化 `tasks/TEMPLATE.md`；
  - 新增 `docs/RECRUITMENT_RESEARCH.md` 研究规范；
  - 新增本验收文件。
- 测试：文档变更，无代码执行；`git diff --check` 通过（提交前核对）。
- 真实执行：否（本阶段不访问外部站点）。
- 访问方式：无。
- 可披露统计：0 条采集记录。
- 阻塞：无。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 ⑤ 交付表。

## 阶段 ② — SQLite 与工具

- 日期：2026-11-09
- 变更：
  - 新增 `db/migrations/002_research_items.sql`（`research_items`、`run_research_items`，未修改 001）；
  - `scripts/db.py`：按 `PRAGMA user_version` 判断待执行迁移，修复“基础表已存在则跳过 002”的升级陷阱；新增在线备份、URL 规范化与研究条目 CRUD；
  - `scripts/init_db.py`：迁移前自动创建可读备份并输出路径；
  - 新增 `scripts/research_catalog.py`（add / list / export，不联网）；
  - 新增 `tests/test_research_db.py`、`tests/test_research_catalog.py`；更新 `tests/test_db.py` 的版本断言。
- 测试：`python -m unittest discover -v` → **43 个测试全部通过**（其中新增 17 个）。
- 真实数据库升级：`user_version 1 -> 2`；升级前备份生成于本地忽略目录；升级后 `datasets=5`、`runs=1` 保持不变，`research_items=0`，`integrity_check=ok`。
- 真实执行：否（本阶段不访问外部站点）。
- 访问方式：无。
- 可披露统计：research_items 0 条。
- 阻塞：无。
- 提交：中文提交并推送 `origin/main`；SHA 记录于阶段 ⑤ 交付表。

## 阶段 ③ — 浏览器与端到端联调

（待本阶段完成后追加）

## 阶段 ④ — 小规模真实调研

（待本阶段完成后追加）

## 阶段 ⑤ — 文档与最终回归

（待本阶段完成后追加）
