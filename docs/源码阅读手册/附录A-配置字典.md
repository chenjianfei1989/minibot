# 附录 A 配置字典

遇到行为与预期不一致时，从完整键名开始检查。以下默认值按项目配置模型或随附模板列出。模板显式指定的值优先查看实际载入的文件，模型连接信息和路径还可能经过环境变量解析。第 [09 章](09-配置加载写回与系统提示词.md)讲解如何追踪实际生效值。

## 模型、上下文和存储

| 字段 | 常见默认值 | 所在环节 |
| --- | --- | --- |
| `llm.base_url`、`llm.api_key` | 从对应环境变量取得，配置模型允许为空 | 客户端连接地址与凭证 |
| `llm.model` | `gpt-4.1-mini` | 模型标识，可通过模板占位符从环境变量获得 |
| `llm.max_tokens` | 8000 | 单次模型请求的输出额度，还受上下文与运行预算约束 |
| `llm.max_context_tokens` | 100000 | MiniBot 构造请求时使用的上下文窗口估算上限 |
| `llm.max_tool_output_chars` | 16000 | 模型可见的工具结果字符上限 |
| `llm.stream_enabled` | `true` | Agent 默认流式设置，SDK 入口可在调用期间切换 |
| `context_offloading.enabled` | `true` | 大工具输出是否可卸载为本地产物 |
| `context_offloading.threshold_chars` | `null` | 产物卸载的字符阈值。无显式值时核对模型工具输出上限的使用 |
| `context_offloading.max_artifact_bytes` | 8388608 | 单个产物的字节上限 |
| `session.enabled`、`session.sessions_dir` | `true`、`sessions` | 会话持久化开关及目录，目录默认相对于应用主目录 |
| `trace_dir` | `null` | 追踪记录目录，未设置时关闭这一文件输出 |
| `file_checkpoints`、`durable_execution` | 均为 `false` | 文件检查点及运行日志，各有独立的恢复用途 |

来源：[默认模板](../../config/default.yaml) · [配置模型](../../src/minibot/config/schema.py) · [上下文请求构造](../../src/minibot/core/model_context.py)

## 工作区、工具和运行控制

| 字段 | 默认值或可选项 | 所在环节 |
| --- | --- | --- |
| `workspace.backend` | `local` 或 `docker`，默认 `local` | 文件与命令的整体执行后端 |
| `workspace.image`、`memory_mb`、`cpus`、`pids_limit` | `python:3.12-slim`、512、1.0、128 | Docker 镜像与资源限制 |
| `workspace.network`、`workspace.timeout` | `none`、`null` | 容器网络与工作区操作时限，时限为空时检查工具配置 |
| `durable_child_workspace` | 使用 Docker 和禁网配置 | 持久化委派子运行的工作区，字段与 `workspace` 同结构 |
| `tools.enabled`、`tools.disabled` | `["*"]`、`[]` | 参与默认工具注册筛选 |
| `tools.timeout` | 60 秒 | 工具操作超时 |
| `tools.bash.backend` | `disabled`、`local` 或 `docker`，默认 `local` | 本地工作区的 Bash 执行方式 |
| `tools.bash.image`、`memory_mb`、`cpus`、`pids_limit` | `debian:bookworm`、512、1.0、128 | Bash Docker 模式的镜像与资源限制 |
| `runtime_budget.max_llm_calls`、`max_tool_calls` | 30、100 | 执行片段的模型及工具尝试次数预算 |
| `runtime_budget.max_wall_time` | 600 秒 | 执行片段的时间预算 |
| `runtime_budget.max_input_tokens`、`max_output_tokens` | 200000、50000 | 执行片段的累计输入和输出预算 |
| `tool_permissions.mode` | `off`、`manual` 或 `auto_review`，默认 `off` | 工具审批模式 |
| `tool_permissions.default`、`rules` | `ask`、空映射 | 默认判定及按工具名覆盖 |
| `tool_permissions.auto_review_paths`、`timeout` | 空列表、120 秒 | 模型审核允许的相对路径及审批等待时间 |

来源：[工具权限指南](../工具权限与审批.md) · [工作区配置指南](../工作区后端.md) · [运行预算实现](../../src/minibot/core/runtime_budget.py)

## 记忆、技能与协作

| 字段 | 默认值或说明 |
| --- | --- |
| `memory.enabled`、`memory.memory_dir`、`memory.backend` | `true`、`memory`、`sqlite`。后端可选 `sqlite`、`postgres`、`mysql`。受限工作区另有能力限制 |
| `memory.database_url`、`memory.active_namespace` | 默认空。使用 `postgres` 或 `mysql` 时需要数据库连接地址，通常引用 `MEMORY_DATABASE_URL`。`active_namespace` 指定当前命名空间 |
| `memory.long_term_max_lines`、`memory.daily_lookback_days` | 200 行、1 天，用于加载文件型长期与每日记忆 |
| `skills_dir` | 模板为 `../skills`，由配置目录解析 |
| `teams.enabled`、`max_members`、`default_members` | `true`、6、3 |
| `teams.log_dir`、`wait_timeout_sec` | `.minibot/teams`、30 秒，供团队日志与等待使用 |
| `teams.quiet_teammates`、`debug_teammate_output` | `true`、`false`，控制队友输出 |
| `subagents.<类型>.description`、`prompt`、`tools` | 类型描述、提示词和允许工具的覆盖项 |
| `subagents.<类型>.enabled`、`skills_enabled` | 单个覆盖配置模型默认 `true`、`false` |

## 独立配置文件与环境变量

- [钩子配置](../../config/hooks.yaml)中的 `enabled` 是总开关，`hooks_dir` 是脚本目录，`hooks` 每项包含 `event`、`handler`、`timeout`、`enabled`。处理器支持脚本路径或 `module:function` 引用。
- [MCP 配置](../../config/mcp_servers.yaml)中的 `enabled` 和 `servers[].enabled` 分别控制总开关及服务开关。`servers[].name` 标识服务。`transport` 选择传输方式。`command`、`args` 和 `env` 用于 stdio，`url` 和 `headers` 用于相应的网络服务。
- [.env 示例](../../.env.example)列出 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_ID`、`MINIBOT_RICH`、`MINIBOT_STREAM`。前 3 项用于模型连接。`MINIBOT_RICH` 控制富文本渲染。示例保留了 `MINIBOT_STREAM`，当前实现直接使用 `llm.stream_enabled` 及对应的运行时开关。对照[加载器](../../src/minibot/config/settings.py)、[Rich 工具](../../src/minibot/utils/rich_utils.py)和 [CLI](../../src/minibot/main.py)区分实际读值位置。
- `MINIBOT_HOME` 用于定位应用主目录。SDK 可以直接传入配置和工作目录，还可用 `session_id`、`sessions_dir`、`skills_dir`、`system_prompt` 等参数调整实例。浏览器内的模型和 Bot 配置入口见第 [22 章](22-FastAPI与SSE及WebUI.md)和第 [23 章](23-Bot与外部平台.md)。

[返回全书目录](00-阅读总纲.md)
