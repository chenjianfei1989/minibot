# 第 18 讲 MCP外部工具

跟踪一个外部工具从服务发现到返回结果。

## 一个外部工具怎样进入同一份工具清单

想让 MiniBot 调用某个远程工具。启动时，`MCPManager` 依据配置建立客户端。客户端完成协议初始化，再向服务发现工具。管理器把外部工具包装成适配器注册到本地工具表。此后模型只看到统一请求中的名称、描述和 Schema。真正执行工具时，适配器才把请求交给相应 MCP 客户端。

跟一次 `stdio` 服务和一次 Streamable HTTP 服务，比较建立连接与发消息的路径。前者使用程序的标准输入输出，HTTP 传输按端点和会话处理请求，可能直接收到 JSON，也可能读取 SSE 事件取得结果。项目另有 SSE 传输实现，应分别定位相应类。

## 连接成功与调用成功

使用脚本化测试端点先验证初始化与工具发现，再验证一次请求返回。若 HTTP 会话过期，读客户端如何处理过期状态以及重连，区分连接失败、服务端工具错误和本地参数错误。真实接入前先确认该传输对应的配置字段，凭证通过环境或受控配置注入。

**思考与答案**　配置了 MCP 服务，为什么模型可能没有发现该服务的工具？先查服务是否启用以及初始化和注册是否完成，再看请求工具定义是否包含它。

## 源码索引

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
