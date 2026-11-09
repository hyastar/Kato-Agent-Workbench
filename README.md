# Kato-Agent-Workbench

一个由**现有编码 Agent（Codex / Zcode 等）驱动**的个人 AI 研究与数据采集工作台。

仓库本身不是 AI Agent，也不是后台服务：理解任务、规划步骤、操作浏览器由宿主 Agent 完成；本仓库提供规范（`AGENTS.md`）、任务定义（`tasks/`）、确定性 Python 工具（`scripts/`）、SQLite 元信息库与执行记录（`runs/`）。

## 不是什么

- 不是独立的 Agent 引擎，不包含 LangChain / CrewAI / AutoGen 等框架；
- 不是 Web 服务或前端应用，没有 FastAPI / React；
- 不是数据仓库：`data/raw/` 存原始文件，数据库只存元信息与索引；
- 不会自动开始采集：只有你明确说“执行当前任务”才会执行。

## 目录结构

```text
Kato-Agent-Workbench/
├── README.md               # 本文件
├── AGENTS.md               # Agent 常驻行为规范（核心）
├── environment.yml         # Conda 环境声明
├── .codex/config.toml      # Codex 项目级 Playwright MCP 配置
├── tasks/
│   ├── CURRENT_TASK.md     # 当前任务（由你反复编辑）
│   ├── TEMPLATE.md         # 任务模板
│   └── archive/            # 历史任务快照
├── docs/                   # 架构、流程、数据库、MCP、安全文档
├── db/migrations/          # SQLite 迁移（001_init.sql）
├── scripts/                # 确定性 Python 工具
├── data/
│   ├── raw/                # 原始下载文件（不覆盖）
│   ├── processed/          # 处理后数据
│   ├── metadata/           # JSON 侧车文件/清单
│   └── catalog/workbench.sqlite3  # 本地数据库（不入 Git）
├── workspace/              # 临时文件（可清空）
├── runs/<run-id>/          # 每次执行的快照、进度、结果、报告
└── tests/                  # 离线单元测试
```

## 依赖

| 组件 | 要求 | 说明 |
|---|---|---|
| Miniconda / Conda | 已安装 | 环境名必须为 `Kato-Agent-Workbench` |
| Python | **3.12** | 由 `environment.yml` 固定 |
| Node.js | LTS | 优先 26 LTS；不兼容时用 24 LTS |
| npx | 随 Node 提供 | 用于启动 Playwright MCP，无需 `package.json` |
| 浏览器 | Chrome / Edge / Chromium | 供 Playwright MCP 使用 |
| 编码 Agent | Codex 或其他支持 MCP 的客户端 | 任务执行者 |

本仓库不使用 pnpm，不创建前端工程；Python 只依赖标准库。

## 快速开始

在仓库根目录执行：

```bash
# 1. 创建 Conda 环境（名称固定为 Kato-Agent-Workbench）
conda env create -f environment.yml

# 2. 激活
conda activate Kato-Agent-Workbench

# 3. 初始化目录与 SQLite（可重复执行）
python -m scripts.init_db

# 4. 环境自检（不联网）
python -m scripts.doctor
```

`doctor` 输出 `PASS / WARN / FAIL`。WARN 表示可继续但建议处理，FAIL 会返回非零退出码。首次在未初始化前运行 `doctor`，数据库项会显示 WARN，这是预期行为。

### 更新已存在的环境

```bash
conda env update -f environment.yml --prune
```

如果已存在同名环境，先检查再决定，不要直接覆盖：

```bash
conda env list
conda run -n Kato-Agent-Workbench python --version
```

只有 Python 3.12 且环境可用时才建议复用；否则请用户确认后再重建。

## 日常使用

### 1. 编辑任务

修改 `tasks/CURRENT_TASK.md`，写清：

- 任务名称、背景与目标；
- 目标网站与允许范围（白名单）；
- 搜索关键词与筛选条件；
- 执行步骤；
- 人工确认与禁止事项；
- 输出要求与验收标准。

章节格式参考 `tasks/TEMPLATE.md`。`CURRENT_TASK.md` 只描述需求，不记录进度。

### 2. 让 Agent 执行

对 Codex / Zcode 说：

```text
执行当前任务
```

Agent 会读取 `AGENTS.md` 与任务文档，做环境检查，生成 `run-id`，保存快照，然后按阶段执行。批量下载前会先请你确认。

### 3. 查看结果

- 人类可读报告：`runs/<run-id>/report.md`
- 机器可读结果：`runs/<run-id>/results.json`
- 执行过程与检查点：`runs/<run-id>/progress.md`
- 原始文件：`data/raw/<source>/<dataset>/<version>/`
- 元信息：`data/catalog/workbench.sqlite3`

`runs/` 与 `data/` 的内容默认不入 Git，避免把数据与运行日志提交到远程仓库；需要归档时由你明确决定。

## 数据集目录工具

```bash
# 查看全部
python -m scripts.catalog list

# 过滤
python -m scripts.catalog list --status candidate
python -m scripts.catalog list --source roboflow --json

# 登记或更新（按 source + source_url + version 去重）
python -m scripts.catalog add \
  --name "示例数据集" \
  --source roboflow \
  --source-url "https://example.invalid/dataset" \
  --version v1 \
  --format coco \
  --license-name "CC BY 4.0" \
  --license-url "https://example.invalid/license" \
  --image-count 1200

# 从 JSON 文件登记（CLI 参数优先）
python -m scripts.catalog add --json-file dataset.json
```

状态取值：`candidate`、`approved`、`downloaded`、`validated`、`failed`。

`catalog` 使用的数据库若尚不存在（例如用 `--db` 指向新路径），会先自动执行一次迁移再写入，不需要手动 `init_db`。`init_db` 仍然负责创建 `data/` 各子目录。

## 数据校验

```bash
# 自动识别 COCO / YOLO
python -m scripts.validate_dataset data/raw/roboflow/example/v1

# 显式指定格式
python -m scripts.validate_dataset path/to/annotations.json --format coco
python -m scripts.validate_dataset data/raw/yolo/example --format yolo

# JSON 输出
python -m scripts.validate_dataset data/raw/... --json
```

只做**结构检查**：COCO 的必填字段、ID 引用与 bbox 尺寸；YOLO 的 `images/` + `labels/` 布局、五列格式与归一化坐标。通过不代表数据质量、标签准确率或许可合规。未支持的格式会明确提示“未实现此格式的校验”。

## 就业情报研究工作流

除数据集调研外，工作台支持具名任务 `tasks/EMPLOYMENT_2026_2027.md` 的就业情报研究：由宿主 Agent 通过 Playwright MCP 操作真实 Chrome，读取页面可见信息，再用确定性 CLI 入库并生成报告。

### 1. 任务入口

`tasks/CURRENT_TASK.md` 仍是默认入口。用户在指令中明确点名 `tasks/EMPLOYMENT_2026_2027.md`（或其他具名任务）时，该文件即是本轮任务定义，并作为 `runs/<run-id>/task_snapshot.md` 的快照来源。

### 2. 浏览器采集

- 登录、验证码、设备确认由用户在可见浏览器窗口亲自完成；Agent 不接触密码或 Cookie。
- 使用页面正常可见的搜索框、结果链接、滚动与详情页；每平台条目上限与关键词以任务文档为准。
- 不调用隐藏/逆向接口，不抓取登录态私有数据，不进行点赞、评论、私信、发帖等互动。
- 遇到 403、限流、验证码循环或权限提示时停止该平台，记录 `blocked` / `partial`，不绕过访问控制。
- 小红书笔记详情需要从搜索结果点击进入（URL 会自动附带 `xsec_token`）；直接拼 `/explore/<id>` 会返回 404。入库只保存不带 token 的规范链接。

### 3. 入库与查询

```bash
python -m scripts.research_catalog add --json-file records.json --run-id <run-id>
python -m scripts.research_catalog list --cohort 2027
python -m scripts.research_catalog list --platform zhihu --topic recruitment
python -m scripts.research_catalog list --verification unverified --json
python -m scripts.research_catalog export --format json
```

`add` 接受 JSON 对象或对象数组，按 `(platform, canonical_url)` 幂等去重；同一链接跨平台不会合并。

### 4. 核验规则

- `source_type` 区分 `official` / `reported` / `ugc` / `search_lead`；UGC 只能作为经验或线索。
- `verification_status=verified` 必须同时提供 `verification_url` 与 `verified_at`，否则 CLI 拒绝写入。
- 岗位是否开放、截止日期、薪资数字等客观事实需官方渠道核验；无法确认时写 `unverified` 或“未核实”。

### 5. 运行产物

`runs/<run-id>/` 下保存 `task_snapshot.md`、`progress.md`、`results.json`、`report.md`；本地数据库、运行目录与浏览器 Profile 均不提交 Git。脱敏阶段摘要写入 `docs/acceptance/EMPLOYMENT_PHASES.md`。

### 6. 1000 篇 Campaign（V4）

- Campaign：`employment-2026-2027-1000-20261109`；目标 1000 篇（小红书 800、知乎 200；2026 届 400、2027 届 600）。
- 每篇最多 50 条一级评论；超过 50 时高赞前 30 + 最新前 20，去重补足；无排序控件时按可见顺序并记录限制。
- 所选一级评论下的楼中楼尽可能全部展开，不计入 50 条；评论作者身份字段不入库。
- 产物：`data/employment/<platform>/{posts,comments,indexes}/`、`data/employment/reports/`、SQLite 的 Campaign/Batch/Artifact 表。
- **当前实测：20/1000**（小红书 16、知乎 4；2026 届 8、2027 届 12；评论 365 条）。Campaign 状态为 `partial`，未声称完成 1000 篇。
- 恢复：先查 SQLite 的 `research_campaigns` / `research_batches` 与 `runs/<run-id>/checkpoints/`，再继续新批次。

## 浏览器 MCP 与首次登录

Codex 的项目级配置在 `.codex/config.toml`：

```toml
[mcp_servers.playwright]
command = "npx"
args = [
  "-y",
  "@playwright/mcp@0.0.84",
  "--browser=chrome",
  "--user-data-dir=../.kato-playwright-profile",
]
```

1. 在项目目录启动 Codex，按提示信任该项目（项目级配置通常需要信任后生效）。
2. 确认 Playwright MCP 出现在工具列表中。
3. 首次需要登录的站点，由你**亲自**在弹出的浏览器中登录。
4. 该版本未指定 `--user-data-dir` 时会使用临时目录；本项目显式使用仓库上一级的持久化目录 `../.kato-playwright-profile`，登录状态可保留且不在版本库内。
5. 详细配置、扩展模式与排障见 `docs/MCP_SETUP.md`。

浏览器 MCP 连通不等于拥有站点授权；登录、验证码、付费与批量下载仍需人工处理。

## 安全与 Git 策略

- `.gitignore` 已排除真实 `.env`、SQLite 及 `-wal` / `-shm`、`data/` 下的数据文件、`runs/` 运行记录、`workspace/`、Python 缓存与常见浏览器会话文件。
- 不提交 Cookie、Token、浏览器 Profile、个人数据或含隐私的页面内容。
- 删除 `data/`、数据库或历史 `runs/` 前必须明确确认。
- 完整边界见 `docs/SAFETY.md` 与 `AGENTS.md`。

## 测试

```bash
conda activate Kato-Agent-Workbench
python -m unittest discover -v
```

测试全部离线，使用临时目录与小型 fixture，不访问网络。

## 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| `Author identity unknown` | Git 未配置提交身份 | `git config --local user.name "..."` 与 `user.email` |
| `doctor` 报告 Python 版本 FAIL | 使用了 base / 系统 Python | `conda activate Kato-Agent-Workbench` |
| 数据库项 WARN | 尚未初始化 | `python -m scripts.init_db` |
| `npx` 找不到 | Node 未安装或 PATH 缺失 | 安装 Node LTS 并重开终端 |
| MCP 工具不出现 | 项目未信任 / 配置语法错误 | 重启 Codex，检查 `.codex/config.toml` |
| 浏览器启动失败 | 浏览器未安装 / Profile 被占用 | 关闭占用进程，或改用 `--browser=msedge` |
| 下载后校验失败 | 结构不完整或格式不支持 | 查看具体错误；不要当作“已可用数据” |
| `conda env create` 很慢/失败 | 网络或镜像问题 | 检查网络；必要时配置镜像后重试 |

## 环境说明（本机实施记录）

本机为 Windows，实施日期 2026-11-07。以下是**实际执行并观察到的结果**，未验证项单独标注。

| 项目 | 实测状态 |
|---|---|
| Conda | conda 26.9.4（`C:\ProgramData\miniconda3`） |
| 环境 | `Kato-Agent-Workbench` 已创建，Python **3.12.16**，路径 `C:\ProgramData\miniconda3\envs\Kato-Agent-Workbench` |
| Node.js | **v22.22.2**（PATH 中的 WorkBuddy 内置版本）/ 系统 Node **v22.23.4**。**没有 24 或 26 LTS**，因此 `doctor` 报 Node WARN；这是本机真实状态，未做升级 |
| npx | 10.9.7 |
| 浏览器 | Google Chrome 与 Microsoft Edge 均已安装 |
| Codex CLI | **已安装 0.167.0**（用户级 npm 前缀 `C:\Users\hyastar\AppData\Roaming\npm`）。`codex doctor` 显示**未登录**（无凭据），且 OpenAI 端点不可达，因此 Codex 无法驱动任务 |

已真实验证：

- `python -m scripts.init_db` 首次执行 `user_version 0 -> 1`，重复执行输出“已是最新版本”，数据不丢；
- `python -m scripts.doctor` 结果 `PASS=8 WARN=1 FAIL=0`，唯一 WARN 是 Node 版本；
- `python -m unittest discover` 全部通过（73 个测试）；
- `npx -y @playwright/mcp@0.0.84 --help` 可正常启动，且确认该版本提供 `--browser`、`--user-data-dir`、`--extension` 参数；
- 在 `~/.codex/config.toml` 写入 `[projects."<仓库路径>"] trust_level = "trusted"` 后，`codex mcp list` **能列出项目级 `playwright` 服务器**（`enabled`），说明 `.codex/config.toml` 可被 Codex 正确解析；
- **真实浏览器 E2E**：用标准 MCP stdio 协议直连 `@playwright/mcp@0.0.84`（`--browser=chrome --user-data-dir=../.kato-playwright-profile`），列出 25 个 browser 工具，成功启动 Chrome 并访问 `https://universe.roboflow.com/`，采集到 5 个数据集页面；
- **Profile 持久化**：关闭会话后 Profile 位于 `D:\Github\Code\.kato-playwright-profile`（仓库之外），`Default/Network/Cookies` 含 `cf_clearance` 等 4 条 Cookie；重启全新会话后再次访问 Roboflow **未再出现 403 验证页**，直接进入首页。

**重要边界**：Roboflow 使用 Cloudflare 人机验证。首次访问返回 HTTP 403 与“正在进行安全验证”页，必须由**用户本人**在可见的 Chrome 窗口中完成验证；自动化不得绕过。本项目的验收流程即是如此处理的。

**仍未验证**：

- Codex 会话内实际调用 Playwright 工具（受“未登录”阻塞，`codex login` 后才能测）；
- 需要账号的动作：登录、导出格式确认、数据集下载。

Node 22 与 Playwright MCP 的兼容性已验证到“真实浏览器会话可运行”，但项目建议版本仍是 24 / 26 LTS。

### 就业情报工作流实测（2026-11-09）

- SQLite 从 V1 升级到 V2（新增 `research_items` / `run_research_items`），原有 5 条 Roboflow 数据集与 1 条运行记录保留，迁移前自动生成可读备份。
- 离线测试 43 个全部通过（新增 V1→V2 迁移、去重、核验约束与 CLI 测试）。

### V4 模块化与试采集（2026-11-09）

- 新增 `scripts/employment/` 模块（模型、标准化、去重、校验、Repository、产物、Markdown 导出、统计、Campaign 报告）。
- SQLite 升级到 V3：新增评论层级、Campaign、Batch、Artifact 表；历史 5 条数据集与 12 条就业记录保留，迁移前自动备份。
- 真实浏览器试采集 20 篇（小红书 16、知乎 4），一级评论 211 条、楼中楼 154 条；文章/评论 Markdown 各 20 份。
- 评论覆盖：完整 9、部分 8、无可用评论 3；Campaign 实际 20/1000，状态 `partial`。
- 离线测试 73 个全部通过。
- Playwright MCP 驱动真实 Chrome；知乎与小红书均由用户在浏览器中手动完成登录。
- 知乎搜索 `2026届 秋招` / `2027届 秋招` / `2027届 校招`，采集 6 条；小红书搜索 `2026届 秋招` / `2027届 秋招`，采集 6 条。
- 12 条写入 `research_items` 并关联运行 `run_research_items`；2026 届 5 条、2027 届 7 条；全部为 `unverified` UGC。
- 运行状态为 `partial`：采集完成，但未做官方公告交叉核验。
- 小红书直接拼 `/explore/<id>` 返回 404，从搜索结果真实点击进入正常；入库链接已去掉 `xsec_token`。

## 文档索引

- `AGENTS.md`：Agent 行为规范（执行前必读）
- `docs/ARCHITECTURE.md`：组件边界与设计取舍
- `docs/WORKFLOW.md`：执行、失败与恢复流程
- `docs/DATABASE.md`：表结构与迁移约定
- `docs/MCP_SETUP.md`：浏览器 MCP 配置与排障
- `docs/ARCHITECTURE_EMPLOYMENT.md`：就业情报模块化架构、SQLite V3 与 Campaign 规则
- `docs/platforms/ZHIHU.md`：知乎搜索、详情与评论操作手册
- `docs/platforms/XIAOHONGSHU.md`：小红书搜索、点击进入与评论操作手册
- `docs/RECRUITMENT_RESEARCH.md`：就业情报来源、分类、核验与报告规范
- `docs/SAFETY.md`：权限、许可、隐私与人工确认边界
