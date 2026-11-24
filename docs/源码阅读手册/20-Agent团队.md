# 第 20 讲 Agent团队

理解团队里的任务、消息、成员状态和共享工作区协调。

## 一次委派和持续团队协作有何不同

假设需要两个 Agent 分头阅读源码，并通过任务板共享结果。团队机制会管理多个成员以及通信、任务、事件和文件锁。先从 `TeamCreate` 追到底层 `TeamRuntime`，观察成员如何启动，再通过一次 `TeamMessage` 对照消息的发送者、接收者与队友生成所读取的内容。

只执行一个子任务时，入口与结果主要由父 Agent 的一次工具调用关联。团队场景中，成员需要明确谁能创建、分派或认领任务，负责人需要知道何时等待，文件写入也要避免队友相互覆盖。`TeamStore` 持有任务与协调状态，工具入口会根据执行上下文判断角色与成员。

## 从一条共享任务读团队状态

在测试里观察任务创建与领取，分别定位工具名称、操作方 ID 和状态字段。再读 `TeamWait` 的返回值，找出哪些状态变化形成运行事件。关闭团队时，沿运行时清理队友任务与资源，理解为什么只把工具从注册表移除还不足以结束运行中的队友。

**思考与答案**　两个队友都想写同一个文件时，谁负责协调？底层团队工作区的锁参与协调。需要从具体文件工具进入团队上下文与锁判断来确认当前调用的行为。

## 源码索引

[teams/runtime.py](../../src/minibot/teams/runtime.py) · [teams/store.py](../../src/minibot/teams/store.py) · [teams/models.py](../../src/minibot/teams/models.py) · [teams/context.py](../../src/minibot/teams/context.py) · [tools/meta/team.py](../../src/minibot/tools/meta/team.py)

## 配置核对

核对 teams.enabled、成员上限与默认数量、等待超时、日志目录、静默与调试输出，以及 allow_team_tools。

## 使用与验证

用假队友运行并行消息测试，记录发送者、接收者及负责人看到事件的顺序。对照 /team 的命令处理。

在仓库根目录运行本讲的定向测试。测试可在未配置真实模型凭证的环境中执行。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_team_runtime.py::test_parallel_message_workers_and_wait
```

## 阅读验收

能解释团队成员如何通信和协调写入，以及 Agent 团队与一次 Task 委派的适用场景。

[阅读总纲](00-阅读总纲.md) · [上一讲](19-子Agent与任务委派.md) · [下一讲](21-CLI与终端交互.md)
