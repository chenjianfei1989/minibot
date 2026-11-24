# 第 23 讲 Bot与外部平台

理解 Bot 配置、平台绑定和外部消息如何映射到本地会话。

## Bot、平台连接和会话的关系

Bot 有自己的角色配置与能力装配。平台连接保存外部接入的配置并绑定到 Bot。外部会话再映射到这个 Bot 处理的本地会话。三类标识各有职责，所以修改平台绑定时不能简单复用旧会话映射。先读 `BotStore` 和 `AgentManager` 的配置构建，再顺着平台配置与运行时进入消息事件。

## 从飞书文本到 MiniBot 回复

读飞书运行时接收事件的入口，找到消息类型检查及去重逻辑。再跟踪如何取得当前绑定 Bot、解析本地会话、执行聊天和送回回复。打开平台配置相关测试看看重新绑定时怎样清理旧映射。对凭证的阅读限于字段、加载位置和校验路径，实际接入使用自己的测试应用并妥善保存密钥。

练习时优先使用伪造的测试事件，分别送入首次消息与重复消息，观察消息是否重复进入 Agent。只有需要检查真实平台连接时，才开启项目配置中的平台服务。

**思考与答案**　平台连接在 WebUI 可见，是否说明飞书消息一定能收到回复？要分别验证事件是否送达、Bot 是否绑定有效模型、会话是否正确路由，以及最终发送是否成功。

## 源码索引

[server/app.py](../../src/minibot/server/app.py) · [server/bots.py](../../src/minibot/server/bots.py) · [server/dashboard_store.py](../../src/minibot/server/dashboard_store.py) · [server/manager.py](../../src/minibot/server/manager.py) · [server/platforms.py](../../src/minibot/server/platforms.py) · [server/platform_runtime.py](../../src/minibot/server/platform_runtime.py) · [server/plugins.py](../../src/minibot/server/plugins.py)

## 配置核对

核对平台是否启用、绑定目标 Bot、App ID 与 App Secret 等配置，并追踪改绑时旧映射的清理。凭证只在运行环境配置。

## 使用与验证

在 WebUI 查看 Config 和 Platforms 的入口。用假飞书事件验证路由与去重，需要实连时再按项目说明配置自有测试应用。

在仓库根目录运行本讲的定向测试。测试可在未配置真实模型凭证的环境中执行。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_server_platforms.py::test_feishu_runtime_routes_messages_and_deduplicates
```

## 阅读验收

能解释飞书用户消息如何找到 Bot 与本地会话，以及删除或改绑 Bot 后映射如何变化。

[阅读总纲](00-阅读总纲.md) · [上一讲](22-FastAPI与SSE及WebUI.md) · [下一讲](24-构建打包与发布.md)
