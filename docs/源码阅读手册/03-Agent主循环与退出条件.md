# 第 03 讲 Agent主循环与退出条件

区分一次用户轮次、一次模型响应和一次工具执行。

## 源码导读

从 run_loop() 找到 _run_segment() 与真正的 while 循环 _run_loop()。读 finish_reason 的提取与回退，找到 is_tool_batch。工具批次走 _dispatch_tool_batch() 并继续下一次模型调用，其他结束原因进入 return messages。预算和中断走异常处理。

[agent.py](../../src/minibot/agent.py) · [core/run_store.py](../../src/minibot/core/run_store.py)

## 配置核对

durable_execution 决定外层是否接入运行日志。llm.stream_enabled 影响读取响应的方式。runtime_budget 则限制整个执行片段。

## 使用与验证

分别用「你好」和一次文件查询画流程图，标出模型交接给 Python 执行的时点。

在仓库根目录运行本讲的定向测试。测试可在未配置真实模型凭证的环境中执行。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_agent_streaming.py::test_run_loop_streaming_happy_path
```

## 阅读验收

能定位退出条件，并解释 assistant_end 为什么还可能伴随下一次工具执行。

[阅读总纲](00-阅读总纲.md) · [上一讲](02-模型请求组装.md) · [下一讲](04-工具注册与定义.md)
