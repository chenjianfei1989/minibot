# 第 19 讲 子Agent与任务委派

理解主 Agent 怎样把一个有明确范围的任务交给子 Agent。

## 把一个可界定的子问题交给子 Agent

主 Agent 处理仓库问题时，可以把「只读源码，找出会话保存入口」委派给子 Agent。跟踪 `TaskTool` 提供的字段以及 `AgentRegistry` 如何选定类型，随后进入 `SubagentExecutor`。类型配置可以限制能用哪些工具、是否能加载技能以及使用哪些提示词。这些约束帮助子任务遵守自己的边界。

## 普通委派和持久化沙箱委派

普通委派沿子执行器运行并返回结果。持久化路径则可用日志关联父步骤和子运行，每个子运行使用独立的 Docker 工作区。`TaskBatch` 适用于多个相互独立的任务，子运行共享父运行的预算，交付通过凭据明确记录。阅读这条链时，把「返回文本」「导出文件」「把文件应用到父工作区」当作三个不同的操作。

先对照技能测试修改子 Agent 的工具配置，观察实际工具清单，再读一个子运行恢复场景，查看父步骤处于等待时如何定位原子运行。实际 Docker 验证需要本地守护进程和已准备好的镜像。

**思考与答案**　两项子任务之间有数据依赖，适合直接一起放到 `TaskBatch` 里吗？这个批次面向独立任务。需要使用前一项结果时，先等其交付并检查，再委派后续工作。

## 源码索引

[tools/meta/task.py](../../src/minibot/tools/meta/task.py) · [subagents/registry.py](../../src/minibot/subagents/registry.py) · [subagents/executor.py](../../src/minibot/subagents/executor.py) · [agent.py](../../src/minibot/agent.py)

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
