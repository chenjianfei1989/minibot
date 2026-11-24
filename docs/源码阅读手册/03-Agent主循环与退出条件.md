# 第 03 讲 Agent主循环与退出条件

区分一次用户轮次、一次模型响应和一次工具执行。

## 一轮用户请求横跨多少次模型调用

把「读一下 README 并告诉我如何启动」交给 Agent。第一次模型请求可能只得到工具调用，它告诉 MiniBot 该执行什么。MiniBot 完成读取并把结果追加回消息，第二次模型请求才有机会根据文件内容回答。如果模型接着要求另读一个配置文件，循环还会继续。整个往返属于同一轮用户请求。

```text
用户输入 → 模型响应
             ├─ finish_reason 为 tool_calls → 执行工具 → 回填消息 → 再请求模型
             └─ 其他结束原因 → 保存助手消息 → 返回消息列表
```

## 外层负责运行，内层负责迭代

`run_loop()` 是外层入口，负责正常运行和持久化运行的衔接。`_run_segment()` 管理一次执行片段的预算、权限等上下文。`_run_loop()` 才有真正的 `while True`。沿着响应提取代码找到 `is_tool_batch`，便能把上图的两个分支对到实现。响应缺少结束标记时有回退值，所以读分支时要关注 MiniBot 实际使用的归一化 `finish_reason`。

`assistant_end` 是一次助手响应结束的事件。在工具分支，发出它后，还会执行工具并回到循环顶部。整轮的返回位置要看 `return messages` 或异常边界。把断点放在这三处，能分辨「模型发完这一条」「Agent 继续执行工具」「整轮已交还调用方」。

**思考与答案**　怎样知道终端只输出一次最终正文的过程中是否调用过工具？检查结构化工具事件，或在消息历史找助手工具请求和对应的 `role="tool"` 记录。

## 源码索引

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
