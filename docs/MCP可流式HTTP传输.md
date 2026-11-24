# 连接 Streamable HTTP MCP 服务

在 MiniBot 应用主目录的 `config/mcp_servers.yaml` 中添加服务条目，`url` 填写 MCP 端点的完整路径。

```yaml
servers:
  - name: remote
    transport: streamable_http
    url: https://mcp.example.com/api/mcp
    headers:
      Authorization: "${MINIBOT_REMOTE_MCP_AUTHORIZATION}"
    enabled: true
```

接受匿名请求的端点可以省略 `headers`。此示例需在进程环境或应用主目录的 `.env` 中设置 `MINIBOT_REMOTE_MCP_AUTHORIZATION`，值包含完整的请求头内容及所需的 `Bearer` 前缀。请求头在 YAML 中配置。WebUI 显示端点 URL 和连接状态，并支持编辑 URL。

编辑 YAML 后启动或重启 MiniBot。启动时，它会连接已启用的服务，并把这些服务的工具注册到 Agent。

## 连接行为

MiniBot 在初始化请求中提供协议版本 `2025-11-25`，也接受协商得到的 `2025-06-18` 或 `2025-03-26`。后续请求携带协商后的版本和已分配的会话 ID。每个请求可收到 JSON 响应，也可通过该 POST 打开的 SSE 流收到响应。已使用 `stdio` 或 `sse` 的服务可以沿用原有配置。

已分配的会话收到 HTTP 404 时会标记为过期。发送新请求前，在 `/mcp list` 或 WebUI 中选择服务重新连接。MiniBot 会报告失败的操作且不重发。断开连接时，会尝试用 HTTP DELETE 关闭已分配的会话。

当前客户端的 SSE 流以单个请求为范围。此连接方式不支持独立 GET 监听、SSE 恢复或 OAuth 发现。要求使用无状态 `2026-07-28` 方言的服务需要单独支持。

[MCP 2025-11-25 传输规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
