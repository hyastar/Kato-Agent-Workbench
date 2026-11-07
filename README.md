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
| Codex CLI | **未安装**（`codex` 不在 PATH，也无 `~/.codex`），因此 `codex mcp list` 与“信任项目后配置生效”**无法在本机验证** |

已真实验证：

- `python -m scripts.init_db` 首次执行 `user_version 0 -> 1`，重复执行输出“已是最新版本”，数据不丢；
- `python -m scripts.doctor` 结果 `PASS=8 WARN=1 FAIL=0`，唯一 WARN 是 Node 版本；
- `python -m unittest discover` 全部通过（26 个测试）；
- `npx -y @playwright/mcp@0.0.84 --help` 可正常启动，且确认该版本提供 `--browser`、`--user-data-dir`、`--extension` 参数，`.codex/config.toml` 中的参数写法有效。

**未验证**：MCP 客户端侧连接（未装 Codex）、浏览器实际启动与页面操作、`--user-data-dir` 持久化 Profile 的登录保持。这些需在装好 Codex 后由人工确认，不要在未验证前视为已通过。

Node 22 与 Playwright MCP 的兼容性只验证到“包能启动并打印帮助”，未做真实浏览器会话。若希望消除 WARN 并贴近任务书建议，可安装 Node 24 LTS 后在 Codex 中复测。

## 文档索引

- `AGENTS.md`：Agent 行为规范（执行前必读）
- `docs/ARCHITECTURE.md`：组件边界与设计取舍
- `docs/WORKFLOW.md`：执行、失败与恢复流程
- `docs/DATABASE.md`：表结构与迁移约定
- `docs/MCP_SETUP.md`：浏览器 MCP 配置与排障
- `docs/SAFETY.md`：权限、许可、隐私与人工确认边界
