# 第 22 讲 FastAPI与SSE及WebUI

把一次浏览器发送消息的流程追到服务端和模型，再追回复。

## 从发送按钮到一次 SSE 响应

在浏览器里发一条消息，先找 `ChatView` 的发送动作和前端 API 代码。请求携带当前 Bot 和会话所需标识。服务端路由校验请求后，利用 `AgentManager` 取得相应 SDK 实例，再消费它的流式事件。事件以 SSE 送回浏览器，前端按类型更新助手正文、工具状态和其它界面信息。网络面板中看到多条 SSE 数据，对应的仍可能是同一轮用户请求。

## 为什么删除和重新生成按轮次判断

重新生成针对最近的助手轮次。删除则需要找到匹配的用户消息，以及之后属于同轮的助手和工具消息。读这两条路由时对照 `message_id` 与 `parent_user_message_id`。工具审批和用户提问各有交互入口，和普通正文增量应分开跟踪。

从浏览器发起一次对话，记录网络请求与一个结构化事件，然后用服务端测试找到相同类型的事件。继续看静态资源选择逻辑，区分后端提供构建后的 WebUI 与前后端分离的开发方式。

**思考与答案**　页面增量显示异常，怎样判断是 Agent 没发事件，还是前端没处理？对照 SDK 事件、网络 SSE 帧和页面状态三处，逐段确定数据在哪一步停止或被忽略。

## 源码索引

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
