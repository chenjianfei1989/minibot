# 附录 B 跟踪一次完整的工具往返

这次练习跟踪一轮带工具调用的会话，验证模型正文分片、工具参数合并、一次 Python 工具执行和模型最终回复之间的关系。使用仓库现有的假模型测试，无需 API Key、真实模型或 Docker。

## 先运行测试

在仓库根目录执行：

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_agent_streaming.py::test_stream_tool_call_arguments_are_merged
```

打开[测试文件](../../tests/test_agent_streaming.py)，搜索方法名。测试中的 `ToolCallClient` 已规定两次响应。第一次分段返回 `working `、工具名、参数和 `finish_reason="tool_calls"`。第二次返回 `done`，以 `"stop"` 结束。测试替换了工具执行入口，因此关注的是 Agent 分发到工具层的参数，不依赖实际文件操作。

## 记录四个观察点

| 步骤 | 观察点 | 应看到的数据 |
| --- | --- | --- |
| 第一次模型响应 | 找到 `ToolCallClient` 返回的第一组分片 | 调用 ID 为 `call-1`，工具名为 `echo`，参数分两段到达 |
| 合并后 | 在 `Agent._merge_stream_tool_call_delta()` 与分发入口间定位 | 两段字符串组成完整 JSON，解析后是 `{"text": "hello"}` |
| 工具结果 | 查测试替身和 Agent 返回的消息列表 | 测试替身收到 `echo` 和对应参数。结果消息的角色为 `tool`，调用 ID 仍是 `call-1` |
| 第二次模型响应 | 查循环结束条件和最终断言 | 最后一条助手消息是 `done`。响应结束原因为 `stop` |

把 `_dispatch_tool_batch()` 里的结果写入位置与 `_run_loop()` 顶部对照。第 1 章说明 SDK 最终从这套消息里如何取得助手文本。第 4 章的独立示例可以补查 `echo` 工具定义如何产生。测试中的执行替身代表分发边界，不代表 SDK 自动注册了这个测试工具。

## 加深练习

1. **手绘时序。** 只画 SDK 或测试入口、Agent、模型和工具四列。在箭头上写明传的是事件、请求、工具参数还是消息。
2. **追踪一次错误。** 对照 [参数解析测试](../../tests/test_tool_args.py)，解释非法 JSON 如何被处理。再读第 [06 章](06-工具结果权限与钩子.md)，找出权限拒绝和参数拒绝为何出现在不同位置。
3. **追踪一次等待或恢复。** 阅读 [运行预算测试](../../tests/test_runtime_budget.py)中的等待用户用例，或 [持久化执行测试](../../tests/test_durable_execution.py)中暂停后恢复的用例。描述会话 ID、运行 ID、问题 ID 和工具调用 ID 分别用于哪一步。
4. **迁移到真实界面。** 在自己的测试配置中用 WebUI 发起一次对话。把网络面板里的 SSE 事件和第 [22 章](22-FastAPI与SSE及WebUI.md)的处理点进行对照。

完成后，应该能独立解释「一次前端请求、两次模型响应、一次工具调用」怎样同时成立，也能定位解析、权限、预算、网络或持久化失败分别应查哪一层。

[返回全书目录](00-阅读总纲.md)
