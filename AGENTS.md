# AGENTS.md

本文件是供在此仓库工作的编码 Agent 使用的长期备忘和入门说明。

## 项目速览

- **PyPI 发行包名**为 `minibotclaw`。
  - **Python 导入包名**仍为 `minibot`。
  - **CLI 命令**为 `minibot` 和 `minibot-web`。
- **自动发布**由 `.github/workflows/publish-pypi.yml` 负责。推送版本标签 `vX.Y.Z` 会发布到 PyPI 并创建 GitHub Release。
  - 重命名或移动 `.github/workflows/publish-pypi.yml` 时，必须同步更新 PyPI Trusted Publisher 配置。
- **WebUI 构建**由 Vite 将 `webui/` 构建到 `webui/dist/`，并在**打包前**同步到 `src/minibot/server/static/`。
  - 使用 `bash scripts/sync_webui_static.sh` 同步。
  - 同步脚本负责清理 `src/minibot/server/static/assets/` 里的旧哈希文件，只保留当前 `index.html` 引用的文件。
  - 归档构建完成后，使用 `python scripts/verify_package_static.py dist/*.whl dist/*.tar.gz` 验证包中包含 WebUI 文件。

## 架构索引

- **核心 Agent**位于 `src/minibot/agent.py`。
  - 事件驱动的 ReAct 循环会发出 `assistant_delta`、`tool_call` 等结构化流式事件。
- **SDK** 位于 `src/minibot/sdk/minibot.py`。
  - 公共入口是 `minibot.Minibot`，由 `src/minibot/__init__.py` 重新导出。
  - 支持传入 `session_id`、自定义 `tools`（原生 Python 可调用对象）、`skills_dir` 和 `extra_system_prompt`。
- **工具**位于 `src/minibot/tools/`，支持将 Python 函数包装为使用 JSON Schema 的工具。
- **技能**由 `src/minibot/skills/loader.py` 从目录加载技能和提示词，SDK 和服务端可以覆盖 `skills_dir`。
- **会话和持久化**位于 `src/minibot/session/`。文件元数据兼容多平台。Linux 没有 `st_birthtime` 时使用回退值。
- **服务端**位于 `src/minibot/server/app.py`。提供 FastAPI 和 SSE 流式端点，并从 `src/minibot/server/static/` 提供静态界面。
- **WebUI** 位于 `webui/`。使用 React、Vite 和 Tailwind，提供聊天和配置标签页并调用 FastAPI API。

## 聊天消息

- 聊天和会话消息采用**结构化对象**，可包含 `{role, content}` 以外的字段。
  - 持久化消息可包含 `message_id`、`parent_user_message_id`、助手的 `reasoning` 和 `usage`。
  - WebUI 聊天操作和 token 显示依赖这些字段。调整消息结构时，同步更新 Agent 事件、服务端响应模型和 `webui/src/lib/types.ts`。
- 当前 WebUI 的消息操作规则如下。
  - `Regenerate`（重新生成）仅适用于**最近一轮助手回复**。
  - `Delete`（删除）移除匹配助手消息的**整轮对话**，包括配对的用户消息及下一条用户消息之前的同轮工具和助手消息。
- `src/minibot/server/static/` 是打包所用的构建产物目录。
  - 使用 `bash scripts/sync_webui_static.sh` 保持 `index.html` 和哈希资源同步，禁止临时手工复制。
  - 每次同步后，`src/minibot/server/static/assets/` 中只能存在当前 `index.html` 引用的文件。

## 本地开发命令

```bash
# Python 依赖
uv sync

# TUI / REPL
uv run minibot

# 后端（提供 API 和已打包的静态界面）
uv run minibot-web --reload

# 前端开发服务（可选）
cd webui
npm install
npm run dev
```

## WebUI 同步流程

构建新的 WebUI 后，使用仓库脚本同步到 `src/minibot/server/static/`。

```bash
cd webui
npm run build
cd ..
bash scripts/sync_webui_static.sh
```

- 同步与清理流程以 `scripts/sync_webui_static.sh` 为准。
- 脚本会验证 `src/minibot/server/static/assets/` 中的文件名与 `src/minibot/server/static/index.html` 引用的哈希资源文件名完全一致。
- 校验构建归档时，运行 `python scripts/verify_package_static.py dist/*.whl dist/*.tar.gz`。

## CI 与发布

- **CI** 由 `.github/workflows/ci.yml` 定义。
  - 向 `main` 推送或提交 PR 会触发 CI，依次构建 WebUI、运行 `bash scripts/sync_webui_static.sh`、运行测试、构建 wheel 和 sdist，最后校验静态资源。
- **一键发布**由 `.github/workflows/publish-pypi.yml` 定义。
  - 推送 `v*` 标签时触发。
  - 标签版本必须与 `pyproject.toml` 中的版本相同。
  - 流程为构建 WebUI → 运行 `bash scripts/sync_webui_static.sh` → 运行测试 → `python -m build` → 运行 `python scripts/verify_package_static.py dist/*.whl dist/*.tar.gz` → 发布到 PyPI（Trusted Publishing，可选 `PYPI_API_TOKEN`）→ 创建 GitHub Release 并上传 `dist/*`。

## 跨平台测试稳定性

- Linux CI 区分文件名大小写，即使本地 macOS 环境可能不区分。测试创建供业务代码读取的文件时，必须使用实现中的确切大小写。例如长期记忆使用 `LONG_TERM.md`，曾有测试写入 `long_term.md`，在 macOS 上通过却在 GitHub Actions 上失败。
- 测试每日文件、会话或记忆时，除非明确冻结时间，否则避免硬编码“今天”的文件名。优先在运行时获取日期，例如 `datetime.now().strftime("%Y-%m-%d")`，或经产品 API 传入显式日期。
- 文件系统测试在本地通过、在 GitHub Actions 失败时，先检查文件名大小写、日期假设及其他与操作系统有关的路径行为，再排查 Agent、提示词和业务逻辑。

## 跨平台文本读写

- 仓库管理的文本一律使用 UTF-8。读写 `SKILL.md`、Markdown、YAML/JSON/TOML 配置、提示词模板、会话及其他项目文本时，始终显式传入 `encoding="utf-8"`。
- 禁止对项目文本使用未指定编码的 `open(...)`、`Path.read_text()` 或 `Path.write_text()`。有意使用平台默认编码时，加一条简短注释说明原因。
- 对任意用户文件和第三方文件，明确选择解码策略。优先尝试 UTF-8，只有产品行为需要时才采用明确的回退方式。
- 涉及技能、配置加载、提示词、会话或聊天和服务端启动路径时，新增或更新至少一个回归测试，使移除显式编码参数后测试失败。
- 审查时，在修改过的 Python 代码中搜索 `open(`、`read_text()` 和 `write_text()`，确认每个文本读写调用都明确选择了编码。
- 问题只在 Windows 上重现时，优先检查文本编码、路径规范化及 CRLF 行为，再排查模型或 API 层。
- 仓库说明和模板中优先使用 ASCII 标点，必要时使用 Unicode。这样未配置 UTF-8 的终端仍能清楚显示日志和诊断信息。

## 会话上下文日志

- 持续记录在 `.claude/tasks/context_session_YYYY-MM-DD.md` 中。
- 开始工作时阅读当天的会话上下文文件。
- 完成后追加变更、决定及后续事项。
