# 浏览器 MCP 配置

## 目标

让宿主 Agent 通过 **Playwright MCP** 操作真实浏览器：

- 默认使用**独立、持久化的浏览器 Profile**，用户手动登录一次，后续复用会话；
- Profile 与 Cookie 不进入仓库；
- 登录、CAPTCHA、二次验证始终由用户人工完成。

## 前置依赖

| 组件 | 要求 | 本机检查命令 |
|---|---|---|
| Node.js | 当前 LTS（优先 26，若 MCP 不兼容用 24） | `node --version` |
| npx | 随 Node 提供 | `npx --version` |
| 浏览器 | Chrome / Edge / Chromium 任一 | 打开浏览器确认可用 |
| Codex CLI | 支持 MCP 的版本 | `codex --version` |

MCP 通过 `npx -y @playwright/mcp@<version>` 启动，不需要在仓库里创建 `package.json`。首次运行会下载 npm 包和浏览器驱动；网络受限时可能失败，需先解决网络或预装。

## Codex

项目级配置已放在 `.codex/config.toml`：

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

使用步骤：

1. 在项目根目录启动 Codex。
2. 如 Codex 提示“是否信任该项目”，按提示信任；项目级配置通常需要信任后才生效。
3. 用 `codex mcp list`（或当前版本的等价命令）确认 `playwright` 出现在 MCP 列表中。若未出现，通常是项目尚未被信任或需要重启客户端；本机实测（Codex CLI 0.162.1、项目未信任时）该命令确实未列出 `playwright`，这一点尚未在本项目中完成验证。
4. 第一次需要登录的站点，由用户在弹出的浏览器窗口中手动登录；不向 Agent 提供密码。

说明与注意事项：

- 版本固定为 `@playwright/mcp@0.0.84`：本机已验证该包可通过 `npx` 启动并打印帮助信息；**浏览器实际连接与页面操作尚未验证**。如需升级，先在 Codex 中实测再改版本号。
- 不同 Codex 版本的配置字段可能变化；以官方文档为准：<https://developers.openai.com/zh-Hans/docs/config-file/config-basic>。
- 本文件不包含任何账号、Cookie 或密钥。

## 其他 Agent（Zcode / 其他 IDE）

**不要假定不同客户端共享同一种 MCP 配置格式。** 每个客户端有各自的配置文件位置与字段，需要按其官方文档单独添加：

- 服务器启动命令通常是 `npx`，参数为 `-y @playwright/mcp@<version> --browser=chrome`；
- 若客户端支持环境变量，可用 `KATO_BROWSER_CHANNEL` 选择浏览器；
- 配置完成后在该客户端的 MCP / 工具面板中确认能看到 Playwright 工具，再让 Agent 调用。

本仓库只对 Codex 提供了可直接复制的项目级示例；其他客户端的配置写在客户端一侧，不放进本仓库。

## Profile 与会话

### 默认：独立持久化 Profile（推荐）

`@playwright/mcp@0.0.84` 在**未指定** `--user-data-dir` 时会创建一个临时目录，关闭后不保留登录状态。因此本项目在 `.codex/config.toml` 中显式指定：

```text
--user-data-dir=../.kato-playwright-profile
```

该路径相对于仓库根目录，位于仓库的**上一级**，因此不在版本库内。启动 Codex 时的项目根目录应为仓库根目录；登录状态会保留到下次启动。

也可以改用仓库之外的绝对路径（本机专属路径不要提交到 Git）：

```toml
args = ["-y", "@playwright/mcp@0.0.84", "--browser=chrome",
        "--user-data-dir=C:\\Users\\<you>\\AppData\\Local\\kato-playwright-profile"]
```

Profile 路径必须在仓库之外；不要提交 Profile、Cookie、`storage-state.json`。

### 可选：接管已登录的日常浏览器（扩展模式）

如果用户希望复用日常 Chrome/Edge 的登录状态，可以显式使用官方的 **Playwright 浏览器扩展**模式（`--extension`），而不是让 MCP 启动独立浏览器。

代价与风险：

- 扩展拥有对所连接标签页的读取与操作权限；
- 可能接触到已登录网站中的个人数据；
- 需要用户在浏览器中安装扩展并手动连接。

因此该模式**不是默认**，只在用户明确要求时启用。参考：

- Playwright MCP：<https://github.com/microsoft/playwright-mcp>
- Playwright 浏览器扩展：<https://github.com/microsoft/playwright/tree/main/packages/extension>

## 授权边界

浏览器 MCP 连接成功**不等于**获得站点授权：

- 只能访问当前任务明确列出的站点；
- 遇到 CAPTCHA、短信/邮箱验证、付费墙，暂停并交回用户；
- 批量下载、上传、发布、删除前必须人工确认（见 `docs/SAFETY.md`）；
- 不通过自动化手段规避访问控制或反自动化机制。

## 排障

按顺序检查：

1. **命令不存在**：`node --version`、`npx --version` 是否正常；必要时重装 Node LTS。
2. **包下载失败**：`npx -y @playwright/mcp@0.0.84 --help` 手动执行，确认网络或 npm 镜像可用。
3. **浏览器启动失败**：确认 Chrome/Edge 已安装；改用 `--browser=msedge` 或 `msedge` 通道；检查是否有残留 Profile 锁（关闭所有使用该 Profile 的浏览器进程）。
4. **MCP 未出现在工具列表**：确认项目已被 Codex 信任；重启 Codex；检查 `.codex/config.toml` 的 TOML 语法。
5. **能启动但页面空白/超时**：检查代理、DNS、站点可达性；先访问 `https://example.com` 验证基本浏览。
6. **需要登录**：让用户在弹出的浏览器中手动完成，Agent 不接触凭据。

排障时仍然遵守：不访问任务范围外的站点，不下载数据，不修改 `data/`。
