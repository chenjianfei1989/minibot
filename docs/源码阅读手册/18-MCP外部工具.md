# 第 18 讲 MCP外部工具

跟踪一个外部工具从服务发现到返回结果。

## 源码导读

从 MCPManager.connect_all() 到单服务初始化和工具发现，再读 register_tools() 与适配器。比较 stdio、SSE 和 Streamable HTTP 的传输路径，定位一次工具请求与响应如何配对。

[mcp/manager.py](../../src/minibot/mcp/manager.py) · [mcp/client.py](../../src/minibot/mcp/client.py) · [mcp/protocol.py](../../src/minibot/mcp/protocol.py) · [mcp/tool_adapter.py](../../src/minibot/mcp/tool_adapter.py) · [mcp/transport.py](../../src/minibot/mcp/transport.py) · [mcp/streamable_http.py](../../src/minibot/mcp/streamable_http.py)

## 配置核对

对照 config/mcp_servers.yaml 的 enabled、transport、command、args、env、url 与 headers。不同传输需要不同字段。查看断连、远端会话过期和显式重连时的状态。

[相关配置与使用指南](../MCP可流式HTTP传输.md)

## 使用与验证

使用现有假服务测试观察 JSON 和 SSE 响应。配置自己有权使用的服务后，可通过 /mcp list 或 WebUI 查看连接状态。

在仓库根目录运行本讲的定向测试。测试可在未配置真实模型凭证的环境中执行。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_mcp_streamable_http.py::test_configured_server_discovers_and_calls_tools_via_json_and_sse
```

## 阅读验收

能画出外部工具与本地工具汇合到同一注册表的路径，并指出连接故障与工具错误在哪一层处理。

[阅读总纲](00-阅读总纲.md) · [上一讲](17-Skills加载与使用.md) · [下一讲](19-子Agent与任务委派.md)
