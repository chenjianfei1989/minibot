# 第 20 讲 Agent团队

理解团队里的任务、消息、成员状态和共享工作区协调。

## 源码导读

从 TeamCreate 到 TeamRuntime 启动队友，读任务分派、消息路由、事件等待和退出。跟踪 TeamStore 如何记住成员、任务、消息及锁，并核对谁能发起操作。

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
