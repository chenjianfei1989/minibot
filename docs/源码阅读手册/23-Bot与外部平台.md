# 第 23 讲 Bot与外部平台

理解 Bot 配置、平台绑定和外部消息如何映射到本地会话。

## 源码导读

先读 BotStore 和配置构建，区分 Bot、模型提供方和会话。再跟 FeishuPlatformRuntime 的消息入口、去重、会话映射及回复发送。补读服务端插件和 Bot 工具装配。

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
