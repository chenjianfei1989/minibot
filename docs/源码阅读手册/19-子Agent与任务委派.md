# 第 19 讲 子Agent与任务委派

理解主 Agent 怎样把一个有明确范围的任务交给子 Agent。

## 源码导读

从 TaskTool 查 agent_type 的解析与注册表选择，再进入 SubagentExecutor。跟踪子 Agent 的提示词、工具允许列表、技能、预算和最终结果，注意哪些资源与父 Agent 共享。

[tools/meta/task.py](../../src/minibot/tools/meta/task.py) · [subagents/registry.py](../../src/minibot/subagents/registry.py) · [subagents/executor.py](../../src/minibot/subagents/executor.py) · [agent.py](../../src/minibot/agent.py)

启用持久化执行且具备可信本地父工作区时，还要读 `subagents/durable.py`。比较 `Task` 和 `TaskBatch` 的调度方式，确认每个子运行有独立 Docker 工作区，并通过 `deliverables` 与 `ReadChildArtifact` 交付文件。

[持久化沙箱子 Agent 指南](../持久化沙箱子Agent.md) · [持久化子 Agent 实现](../../src/minibot/subagents/durable.py)

## 配置核对

对照 subagents 中工具列表、描述、提示词和技能开关，以及 SDK 的 allow_subagent_delegation。核对队友和受限工作区的注册限制。持久化子运行还使用 `durable_child_workspace`，应使用 Docker 后端并保持禁网。

## 使用与验证

用现有测试比较同一子 Agent 在 skills_enabled 开关前后的工具集合，再找一处父运行和子运行的追踪关联。

在仓库根目录运行本讲的定向测试。测试可在未配置真实模型凭证的环境中执行。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_subagent_skills.py::test_get_tools_includes_skill_when_enabled
```

## 阅读验收

能判断子 Agent 可以调用哪些工具，并把子任务完成后的结果追到主 Agent。

[阅读总纲](00-阅读总纲.md) · [上一讲](18-MCP外部工具.md) · [下一讲](20-Agent团队.md)
