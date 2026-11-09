# 架构说明

## 定位

Kato-Agent-Workbench 是**由现有编码 Agent（Codex / Zcode 等）驱动的个人研究与数据采集工作台**。

它本身不是 AI Agent 运行时，也不在仓库里实现推理、规划或多智能体循环。理解任务、决定下一步、调用浏览器 MCP 和本地命令，全部由宿主 Agent 完成；仓库提供的是规范、任务定义、确定性工具、数据目录和执行记录。

## 明确不引入的东西

第一版不引入 LangChain、CrewAI、AutoGen、Celery、Redis、Docker、FastAPI、React 或 ORM：

- 宿主 Agent 已经负责推理与编排，再写一套 Agent 框架会制造重复且不可控的“第二个大脑”。
- 没有并发任务与远程访问需求，SQLite 足够，且零运维。
- 没有前端需求，Markdown 报告和 CLI 足够；需要更强交互时再讨论。
- 确定性工作（建库、登记、校验、检查）全部用 Python 标准库脚本表达，便于测试与审计。

这些取舍的前提是“单用户、本地、按任务串行执行”。如果将来出现多人并发、远程访问或定时批处理需求，再单独评估升级，而不是提前引入。

## 组件边界

| 目录 | 职责 | 不负责 |
|---|---|---|
| `tasks/` | 用户需求层：任务目标、范围、验收标准 | 运行状态、历史进度 |
| `AGENTS.md` | 行为规则层：Agent 如何执行、何时确认、如何记录 | 某一次具体任务的细节 |
| `docs/` | 项目知识层：稳定架构、流程、数据库、安全说明 | 每次运行的日志 |
| `scripts/` | 确定性工具层：建库、登记、查询、校验、环境检查 | 调用大模型、访问网站 |
| `data/` | 持久化成果层：原始文件、处理文件、元信息、SQLite 索引 | 临时文件 |
| `runs/` | 执行记录层：每次执行一个快照目录 | 持久数据本体 |
| `workspace/` | 可清理的临时层 | 任何需要长期保留的东西 |

硬性边界：

1. `scripts/` 中的程序不做自然语言推理，也不发起未经授权的网络请求。
2. Agent 不把进度写进 `tasks/CURRENT_TASK.md`。
3. 原始下载文件只读：处理产物进入 `data/processed/`，不覆盖 `data/raw/`。
4. 数据库只存元信息与路径，不存图像/视频大二进制。
5. `runs/<run-id>/` 一旦生成不覆盖；重试新建 `run-id` 并在进度中注明来源。

## 数据流

```text
用户编辑 tasks/CURRENT_TASK.md
        │
用户对宿主 Agent 说“执行当前任务”
        │
宿主 Agent ──读取 AGENTS.md / docs/WORKFLOW.md / CURRENT_TASK.md
        │
        ├─ scripts.init_db        （确保数据库就绪）
        ├─ 生成 run-id，写 runs/<run-id>/task_snapshot.md
        ├─ 浏览器 MCP 调研、收集候选、按需人工确认
        ├─ scripts.catalog add/list （登记与查询元信息）
        ├─ scripts.validate_dataset （离线校验下载结果）
        └─ 更新 runs/<run-id>/progress.md、results.json、report.md
                │
             SQLite：tasks / runs / datasets / run_datasets
```

## 为什么用 SQLite

- 单文件、零服务、可备份、可脱离程序用任何 SQLite 客户端查看。
- Python 标准库 `sqlite3` 直接可用，不需要 ORM 或驱动。
- 支持事务、外键、唯一约束和索引，足够表达任务/执行/数据集的关系。
- 数据文件与元信息分离：删掉数据库可以重建索引，但不会重下数据；反过来，元信息不会污染数据目录。

## 为什么浏览器能力交给 Playwright MCP

- MCP 是宿主 Agent 与浏览器之间的标准接口，避免为每个站点重复编写自动化脚本。
- 持久化 Profile 让用户手动登录一次即可复用会话，同时不把 Cookie 放进仓库。
- 登录、CAPTCHA、二次验证始终交回用户；Agent 不实现反检测或绕过逻辑。

## 扩展点

- 就业情报的模块化设计、SQLite V3 表、文件档案与 Campaign/Batch 规则见 `docs/ARCHITECTURE_EMPLOYMENT.md`。
- 新站点：写进任务文档的“目标网站与允许范围”，复用浏览器 MCP。
- 新数据格式：在 `scripts/validate_dataset.py` 增加明确支持的格式分支，并补离线 fixture 测试。
- 新元信息字段：新增迁移文件（例如 `002_add_field.sql`），不要修改已执行的迁移。
- 更多报告形式：仍然落在 `runs/<run-id>/`，不要把报告写回 `tasks/`。
