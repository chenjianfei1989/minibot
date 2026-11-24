# 第 21 讲 CLI与终端交互

从键盘输入追到普通对话或斜杠命令。

## 源码导读

从入口 main() 追到 repl()，观察会话启动、MCP 连接和消息持久化。挑选 /session、/model 和 /skills 各一条命令，追到相应处理器。顺 utils 看输入补全、终端渲染与 Esc 中断。

[main.py](../../src/minibot/main.py) · [ui/](../../src/minibot/ui/) · [utils/prompt_toolkit.py](../../src/minibot/utils/prompt_toolkit.py) · [utils/output.py](../../src/minibot/utils/output.py) · [utils/terminal.py](../../src/minibot/utils/terminal.py) · [utils/esc_interrupt.py](../../src/minibot/utils/esc_interrupt.py)

## 配置核对

核对 MINIBOT_RICH、MINIBOT_STREAM 与模型、会话配置。用实际配置加载路径确认环境变量与配置开关组合后的行为。

## 使用与验证

用 uv run minibot 启动，先试 /help、/info 和 /session list，再配置模型并发送一条消息。

在仓库根目录运行本讲的定向测试。测试可在未配置真实模型凭证的环境中执行。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_cli_session.py::test_session_load_by_id
```

## 阅读验收

能够按输入类型定位 CLI 分支，说明终端输出和 SDK 事件分别由哪些组件处理。

[阅读总纲](00-阅读总纲.md) · [上一讲](20-Agent团队.md) · [下一讲](22-FastAPI与SSE及WebUI.md)
