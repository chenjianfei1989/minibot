# 第 21 讲 CLI与终端交互

从键盘输入追到普通对话或斜杠命令。

## 键盘输入怎样走进 Python

在仓库根目录启动 CLI，试输 `/help`、`/session list` 和一条普通消息。从项目脚本定位 `main()`，接着读 `repl()` 里的输入循环。命令前缀把一部分输入送入独立的处理器，普通输入则被加入用户消息，再交给 Agent。这条入口直接使用 Agent 的地方可以与第 1 章的 SDK 路径对照。

## 一次命令涉及的用户状态

以 `/session load` 为例，命令处理器负责解析子命令和目标，REPL 随后更新当前对话状态。配置命令还可能写回模型服务信息。遇到终端渲染问题时，从交互循环回到输出工具，区分输入补全、正文输出、状态和按键中断。终端的输出配置影响呈现，执行本身仍遵循 Agent 的工具与预算控制。

先用不依赖模型的命令检查本地配置与会话切换，之后再发普通消息。遇到启动失败时，在初始化、模型配置和实际请求几个节点审查错误，避免把命令无法解析误认成模型异常。

**思考与答案**　终端的状态行和 WebUI 消耗的事件是不是同一个输出接口？它们都可能由同一 Agent 行为触发，但终端侧走渲染组件，WebUI 通过 SDK 和服务端接收结构化事件。

## 源码索引

[main.py](../../src/minibot/main.py) · [ui/](../../src/minibot/ui/) · [utils/prompt_toolkit.py](../../src/minibot/utils/prompt_toolkit.py) · [utils/output.py](../../src/minibot/utils/output.py) · [utils/terminal.py](../../src/minibot/utils/terminal.py) · [utils/esc_interrupt.py](../../src/minibot/utils/esc_interrupt.py)

## 配置核对

核对 `MINIBOT_RICH` 的渲染分支，以及 `llm.stream_enabled` 和 `/stream` 命令对流式行为的影响。示例中还有 `MINIBOT_STREAM`，当前运行路径以配置和命令开关为准。

## 使用与验证

用 uv run minibot 启动，先试 /help、/info 和 /session list，再配置模型并发送一条消息。

在仓库根目录运行本讲的定向测试。测试可在未配置真实模型凭证的环境中执行。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_cli_session.py::test_session_load_by_id
```

## 阅读验收

能够按输入类型定位 CLI 分支，说明终端输出和 SDK 事件分别由哪些组件处理。

[阅读总纲](00-阅读总纲.md) · [上一讲](20-Agent团队.md) · [下一讲](22-FastAPI与SSE及WebUI.md)
