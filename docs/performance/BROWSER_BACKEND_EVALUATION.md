# 浏览器执行后端对比与选择（V5 阶段 3）

> 依据执行时的官方 README / 文档；未安装或未实测的项目明确标注。评分用于本项目的取舍，不是通用排名。

## 1. 候选

| 代号 | 方案 | 本机状态 |
|---|---|---|
| A | 现有 Playwright MCP 0.0.84 逐步操作 | 已安装、已实测（阶段 2 基线） |
| B | 保持 Playwright MCP 会话，合并确定性步骤为一次浏览器执行单元 | 基于现有 MCP 的 `browser_evaluate`，无需新依赖 |
| C | Tencent BrowserSkill（`bsk` CLI + daemon + Chrome/Edge 扩展） | **未安装、未实测**（`where bsk` 未找到） |
| D | vercel-labs agent-browser（Rust CLI + daemon） | **未安装、未实测**（`where agent-browser` 未找到） |
| E | Browser4 | 仅架构调查；安装与运行成本高，未安装 |

## 2. 官方资料要点

### A/B：Playwright MCP

- 现有配置：`@playwright/mcp@0.0.84`、`--browser=chrome`、仓库外持久化 Profile。
- 工具 25 个；`browser_evaluate` 可在页面上下文执行一个 async 函数，因此可以在一次调用内完成“滚动/展开/提取”的确定性动作。
- 支持 `--snapshot-mode`、`--isolated`、`--extension`、`--user-data-dir` 等参数。
- `browser_run_code_unsafe` 可执行任意代码，**本轮不使用**；官方也说明 MCP 不是安全边界。
- 限制：逐步调用时 Agent ↔ 浏览器往返多；baseline 实测 12.67 次工具调用/篇。

### C：BrowserSkill

- 官方说明：`bsk` CLI 自带后台 daemon，需要 Chrome/Edge 扩展；Windows x64 支持；使用已有登录状态，任务在独立 Agent Window 中运行。
- 安装需要：CLI、daemon、浏览器扩展（Chrome Web Store / Edge 加载项）以及用户手动连接。
- 代价：新增扩展与常驻 daemon；同一标签页不能同时由 MCP 与 BrowserSkill 控制；需要重新验证 ZCode 集成与评论流程。
- 本机未安装，未做端到端测试；不把 README 宣称当作本项目实测。

### D：agent-browser

- 官方说明：Rust CLI、npm 安装、后台 daemon、CDP 控制；`snapshot` 返回带 `@e1` ref 的紧凑文本；支持 `--cdp` / `--auto-connect` 连接已运行 Chrome。
- 代价：默认 Chrome for Testing；需要自己的 daemon/session；与 Playwright 共享同一标签页存在所有权冲突；评论展开工作流未验证。
- 本机未安装，未测试。

### E：Browser4

- 重量级方案，htmlsnapshot/批量 DOM 能力未在本项目验证；安装与运维成本高于当前需求。仅作为远期备选，不进入本轮。

## 3. 评分（1–5，越高越好）

| 维度 | A MCP 基线 | B MCP 批量 | C BrowserSkill | D agent-browser |
|---|---:|---:|---:|---:|
| ZCode 真正可接入 | 5 | 5 | 2（未验证） | 2（未验证） |
| Windows 安装维护成本 | 4 | 5 | 3 | 4 |
| 登录/会话复用 | 5 | 5 | 4（需扩展连接） | 3（需 CDP/独立会话） |
| 批量动作与 DOM 提取 | 4 | 5 | 4（未实测） | 3 |
| 评论/楼中楼可覆盖 | 5 | 5 | 2（未实测） | 2（未实测） |
| 工具往返/Token 成本 | 2 | 4 | 3 | 3 |
| 页面变化可诊断 | 4 | 4 | 3 | 3 |
| 对现有项目侵入 | 5 | 5 | 2 | 2 |
| 失败/检查点/取消 | 3 | 4 | 3 | 3 |
| 安全与浏览器共享风险 | 4 | 4 | 3（扩展权限） | 3（共享标签风险） |
| **合计** | **41** | **46** | **29** | **28** |

## 4. 决策

- **本轮采用 B：Playwright MCP 会话内批量执行**。
  - 不新增依赖、不改变登录 Profile、不引入 daemon/扩展；
  - 把已确定的“滚动 → 展开 → 提取”合并为一次 `browser_evaluate`；
  - 正常路径返回紧凑 JSON，详细快照只在探索/错误诊断时使用。
- A 作为回退方案；若批量执行出现页面结构不兼容，退回逐步操作。
- C/D 本轮不采用：未安装、未实测，且会引入浏览器所有权/扩展/daemon 成本；保留为后续可选实验，不在生产中与 MCP 同时控制同一标签页。
- E 不采用：成本与验证范围不匹配。

## 5. 验证边界

- 本阶段未安装任何新工具，未修改系统环境。
- 未对 BrowserSkill/agent-browser 做功能或性能声明；表中“未实测”即未验证。
- 采用 B 后仍需阶段 ⑤ 同质量 A/B 证明速度与覆盖不退化，未达门槛则回退 A。
