# 第 01 讲 SDK入口与消息结构

追踪一次普通问答，知道调用方何时收到结果。

## 一次调用到底返回什么

假设你在终端输入「你好」，模型直接回复「你好，有什么可以帮你？」。调用 SDK 时，这两个字符串分别处在不同层：传入 `chat()` 的是本轮用户输入，`ChatResult.assistant_text` 是 SDK 从执行完成后的消息中取出的助手正文。想查看工具返回了什么、消息怎样关联，应该看 `ChatResult.messages`。只想把答案打印到界面上时，读取 `assistant_text` 就够了。

普通非持久化路径上，`_run_once()` 先构造带 `role="user"` 和 `message_id` 的消息，将它加入会话；启用会话存储时也会追加写盘。接着 `_run_existing_messages_once()` 把消息列表交给 `Agent.run_loop()`。Agent 可以在列表末尾追加助手消息、工具结果和后续回复。SDK 在返回前整理新增消息和用量。持久化模式通过运行日志播种和发布消息，外部仍得到同类结果，第 14 章会展开。

## 顺着一条消息读代码

| 观察点 | 此时应看到什么 |
| --- | --- |
| `chat()` 入口 | 当前会话、用户输入字符串和可选的推理强度 |
| `_run_once()` 写入后 | 一条新用户消息及其 ID，前面可能已有多轮历史 |
| `Agent.run_loop()` 返回后 | 用户消息与执行产生的助手、工具消息 |
| 构造 `ChatResult` 时 | 从最近有效助手消息中取出的正文，以及会话 ID 和用量 |

把 `chat_sync()` 看成上述协程的同步入口。它在当前线程有运行中的事件循环时会报错。在异步应用里直接 `await chat()`，让已有事件循环调度即可。同样，`chat()` 一次性返回结果属于调用接口的形态，模型可能在同一轮内被请求多次。

**思考与答案**　两条消息的 `role` 相同，能不能只用角色来定位用户正在重生成的那轮？不能。角色说明是谁发的，具体关联依靠 `message_id` 和 `parent_user_message_id` 等字段。

## 源码索引

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
