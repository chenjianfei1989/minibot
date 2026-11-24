# 第 22 讲 FastAPI与SSE及WebUI

把一次浏览器发送消息的流程追到服务端和模型，再追回复。

## 源码导读

从 ChatView 的发送操作读 API 请求、服务端路由和 AgentManager 创建或复用 SDK 实例。回读 SSE 事件如何被前端消费，再对照重新生成、整轮删除、审批和等待用户回答的接口。

[server/app.py](../../src/minibot/server/app.py) · [server/manager.py](../../src/minibot/server/manager.py) · [server/models.py](../../src/minibot/server/models.py) · [webui/src/lib/api.ts](../../webui/src/lib/api.ts) · [webui/src/lib/types.ts](../../webui/src/lib/types.ts) · [webui/src/views/ChatView.tsx](../../webui/src/views/ChatView.tsx)

## 配置核对

核对 Bot 的模型选择、会话范围和服务端流式处理。定位服务端启动参数、静态资源来源和 Vite 开发配置。

## 使用与验证

从 uv run minibot-web 启动。需要静态资源时先按项目说明构建 WebUI。浏览器开发者工具可观察一次对话的 SSE 请求。

在仓库根目录运行本讲的定向测试。测试可在未配置真实模型凭证的环境中执行。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_server_webui_bots.py::test_stream_endpoint_forwards_todo_snapshot_events
```

## 阅读验收

能从一个界面事件追到相应 API 路由，并说明页面展示的消息字段来自哪里。

[阅读总纲](00-阅读总纲.md) · [上一讲](21-CLI与终端交互.md) · [下一讲](23-Bot与外部平台.md)
