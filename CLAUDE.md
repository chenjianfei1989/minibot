# CLAUDE.md

本文件为使用 Claude Code（claude.ai/code）处理此仓库的开发工作提供说明。

## 项目概览

MiniBot 使用 Python 3.12 编写，是一个模块化的 Claude Code 类工具，包含以下功能。

- **模块化架构**，各模块职责明确。
- **技能系统**，通过 SKILL.md 按需加载领域知识。
- **子 Agent**，执行探索、编码和规划等专门任务。
- **钩子系统**，在工具调用前后、会话开始或结束等事件上执行自定义脚本。
- **MCP 客户端**，连接外部 MCP 服务扩展工具能力。
- **交互式 REPL**，使用 prompt-toolkit 提供输入历史和自动补全。

## 开发命令

```bash
# 安装依赖
uv sync

# 运行应用
uv run python -m minibot

# 也可在安装后使用命令入口
minibot

# 添加依赖
uv add <package-name>
```

## 项目结构

```
minibot/
├── config/                   # 配置文件
│   ├── default.yaml          # 默认设置
│   ├── hooks.yaml            # 钩子配置
│   └── mcp_servers.yaml       # MCP 服务定义
├── hooks/                    # 用户钩子脚本
│   └── examples/              # 钩子示例
├── skills/                   # SKILL.md 文件
├── src/minibot/              # 主包
│   ├── __init__.py
│   ├── main.py               # REPL 入口
│   ├── agent.py              # 主 Agent 类（异步）
│   ├── config/               # 配置管理
│   │   ├── schema.py         # 配置数据类
│   │   └── settings.py       # 加载配置
│   ├── core/                 # 核心组件
│   │   ├── types.py          # 类型定义
│   │   └── client.py         # LLM 客户端封装
│   ├── tools/                # 工具系统
│   │   ├── base.py           # BaseTool 抽象类
│   │   ├── registry.py       # 工具注册表
│   │   ├── builtin/          # 内置工具
│   │   │   ├── bash.py        # 执行 Shell 命令
│   │   │   ├── file.py        # 读取、写入和编辑文件
│   │   │   └── todo.py        # 任务管理
│   │   └── meta/             # 元工具
│   │       ├── skill.py       # 技能加载器
│   │       └── task.py        # 启动子 Agent
│   ├── skills/               # 技能加载器
│   │   └── loader.py
│   ├── subagents/            # 子 Agent 系统
│   │   ├── registry.py       # Agent 类型注册表
│   │   └── executor.py       # 子 Agent 执行引擎
│   ├── hooks/                # 钩子系统
│   │   ├── events.py         # 事件定义
│   │   ├── manager.py        # 钩子管理器
│   │   └── executor.py       # 钩子执行器
│   ├── mcp/                  # MCP 客户端
│   │   ├── protocol.py       # 协议类型
│   │   ├── transport.py      # Stdio/SSE 传输
│   │   ├── client.py         # MCP 客户端
│   │   ├── manager.py        # 多服务管理器
│   │   └── tool_adapter.py   # MCP 到 BaseTool 的适配器
│   └── utils/                # 实用工具
│       ├── output.py         # Rich 输出格式化
│       ├── prompt_toolkit.py # 交互式输入
│       ├── rich_progress.py  # 进度条
│       └── terminal.py       # 终端工具
└── tests/                    # 测试文件
```

## 关键组件

### 工具

| 工具 | 用途 |
|------|------|
| `bash` | 执行 Shell 命令 |
| `read_file` | 读取文件内容 |
| `write_file` | 写入或覆盖文件 |
| `edit_file` | 替换文件中的文本 |
| `TodoWrite` | 管理任务列表 |
| `Skill` | 动态加载技能 |
| `Task` | 启动子 Agent |

### 新增工具

1. 在 `src/minibot/tools/builtin/` 下创建继承 `BaseTool` 的类。
2. 实现 `name`、`description`、`input_schema` 和 `execute()`。
3. 在 `Agent._register_tools()` 中注册。

### 新增技能

在 `skills/` 中创建目录并添加 `SKILL.md`。

```markdown
---
name: my-skill
description: 说明此技能的用途
---

# 我的技能说明
...
```

如果存在 `~/.claude/skills`，MiniBot 也会自动发现其中的技能。

### 新增子 Agent

1. 在 `src/minibot/subagents/` 中创建 Agent 类。
2. 在 `SubagentExecutor.__init__()` 中或通过装饰器注册。
3. 可用类型为 `Explore`、`Plan`、`general-purpose` 和 `code-reviewer`。

### 配置钩子

编辑 `config/hooks.yaml`。

```yaml
hooks:
  - event: pre_tool_call
    handler: hooks/my_hook.py
    timeout: 5
```

### 配置 MCP 服务

编辑 `config/mcp_servers.yaml`。

```yaml
servers:
  - name: my-server
    transport: stdio
    command: npx
    args: ["-y", "@my/mcp-server"]
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `OPENAI_BASE_URL` | LLM API 基础 URL |
| `OPENAI_API_KEY` | API 密钥 |
| `MODEL_ID` | 模型标识符，默认 `gpt-4.1-mini` |

## 协作规则

- 开始任何工作前，必须查看 `.claude/tasks/context_session_[date].md` 以了解完整上下文。
- `context_session_x.md` 应记录主要工作与整体计划，子 Agent 会持续补充上下文。
- 工作结束后，必须更新 `.claude/tasks/context_session_[date].md`。
