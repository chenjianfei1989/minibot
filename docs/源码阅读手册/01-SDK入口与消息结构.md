# 第 01 讲 SDK入口与消息结构

追踪一次普通问答，知道调用方何时收到结果。

## 源码导读

先从公开导出的 Minibot 找到 chat()。沿 _run_once() 看用户消息进入 messages，再沿 _run_existing_messages_once() 看 Agent.run_loop() 如何修改消息。回到 chat()，定位 _last_assistant_text() 与 ChatResult 的组装。

[sdk/minibot.py](../../src/minibot/sdk/minibot.py) · [sdk/types.py](../../src/minibot/sdk/types.py) · [__init__.py](../../src/minibot/__init__.py)

## 配置核对

session_id 决定使用哪个会话，reasoning_effort 随请求传入。对照 Config.session 判断是否加载和写入历史。SDK 的 chat() 会临时关闭流式输出并在退出时恢复原设置。

## 使用与验证

配置可用模型后，在同步环境调用 Minibot().chat_sync('你好')，读取 result.assistant_text。异步环境用 await bot.chat('你好')。

```python
from minibot import Minibot

bot = Minibot()
result = bot.chat_sync("你好")
print(result.assistant_text)
```

在仓库根目录运行本讲的定向测试。测试可在未配置真实模型凭证的环境中执行。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_function_tool.py::test_minibot_chat_persists_session_and_usage
```

## 阅读验收

说明 prompt、完整消息列表与 assistant_text 的关系，并解释一次 chat() 为什么可能包含多次模型请求。

[阅读总纲](00-阅读总纲.md) · [下一讲](02-模型请求组装.md)
