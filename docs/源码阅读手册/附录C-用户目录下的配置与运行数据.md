# 附录 C 用户目录下的配置与运行数据

在 Windows 上首次运行 MiniBot 后，可能会发现用户目录多了一个 `.minibot` 文件夹。这里是 MiniBot 的**应用主目录**，源码中叫 `app_home`。CLI 和 WebUI 都会用它保存配置和运行数据。把仓库克隆到其他目录，通常仍会使用同一个应用主目录，因此不同克隆可能共享本地设置和会话。

## MiniBot 如何找到应用主目录

`resolve_app_home()` 按以下顺序查找：

| 顺序 | 条件 | 使用目录 |
| --- | --- | --- |
| 1 | 当前进程的 `MINIBOT_HOME` 非空 | 该变量指定的目录 |
| 2 | `MINIBOT_HOME` 未指定，`XDG_CONFIG_HOME` 非空 | `<XDG_CONFIG_HOME>/minibot` |
| 3 | 两项均未指定 | `Path.home() / ".minibot"`，Windows 上通常显示为 `C:\Users\<用户名>\.minibot` |

`workdir` 是 Agent 操作文件的工作目录。`project_root` 是用来定位项目根目录和初始化模板的路径。`app_home` 决定全局配置及默认运行数据写到哪。SDK 也可通过 `Config(app_home=...)` 为具体实例提供应用主目录。

[目录解析源码](../../src/minibot/utils/path.py) · [主配置模型](../../src/minibot/config/schema.py)

## 首次启动会写入哪些配置

配置加载器检查 `<app_home>/config/`。在可信本地模式下，缺失的 `default.yaml`、`hooks.yaml`、`mcp_servers.yaml` 优先从项目的 `config/` 复制，没有对应文件时使用内置模板。已存在的全局配置会保留。在普通本地路径下，如果应用主目录的 `.env` 缺失且项目中有 `.env.example`，加载器会尝试用示例创建它。受限 Docker 模式使用独立的初始化路径，应用配置必须位于受限工作区之外。

| 写入位置 | 作用 |
| --- | --- |
| `<app_home>/.env` | 供配置解析使用的模型环境变量默认值，可包含 API Key |
| `<app_home>/config/default.yaml` | 模型、工作区、工具权限、会话和其他全局配置 |
| `<app_home>/config/hooks.yaml` | 钩子的开关、事件、处理器和超时 |
| `<app_home>/config/mcp_servers.yaml` | MCP 服务定义和连接方式 |

因此，仓库里的 `config/default.yaml` 适合用来了解模板。排查已经运行的实例时，先打开该实例的 `<app_home>/config/default.yaml`。例如 `llm.model: ${MODEL_ID:gpt-4.1-mini}` 会尝试读取当前进程的 `MODEL_ID`，再找应用主目录的 `.env`，最后使用占位符默认值。若 YAML 里直接给出非空模型名，模型解析器优先使用这个值。WebUI 若给 Bot 绑定了模型，还应检查 Bot 的模型选择。

[配置加载与首次初始化](../../src/minibot/config/settings.py) · [配置加载流程](09-配置加载写回与系统提示词.md)

## 为什么还有其他文件夹

以下是常见的默认位置。实际是否创建取决于使用的入口和已启用的功能，你可以从对应的配置字段确认是否重定向。

| 位置 | 何时使用 |
| --- | --- |
| `sessions/` | 会话持久化启用时，保存会话消息及运行时状态 |
| `memory/`、`state/` | 启用记忆时保存记忆及其迁移状态。默认 SQLite 记忆库位于记忆目录 |
| `history/` | CLI 输入历史，使用的文件取决于终端交互模式 |
| `skills/` | 默认用户技能位置，通常在安装或新建用户技能时写入 |
| `bots/`、`dashboard.json`、`platforms.json` | WebUI 的 Bot、控制台和平台连接数据 |
| `runs/` | 启用持久化执行后使用的运行日志目录 |
| `artifacts/`、`file-checkpoints/` | 相关功能使用的工具产物和文件检查点存储 |

这些内容可能包含真实凭证、会话正文或工具结果。仓库只保留可分享的模板 `.env.example`。如果把 `MINIBOT_HOME` 特意设在 Git 仓库内，提交前也应检查整个运行数据目录是否受到忽略规则保护。

## 在 PowerShell 确认实际路径

在仓库根目录运行下面的命令。它们显示应用主目录和已有条目名称，不读取 `.env` 内容。

```powershell
$appHome = uv run python -c "from minibot.utils.path import resolve_app_home; print(resolve_app_home())"
$appHome
if (Test-Path -LiteralPath $appHome -PathType Container) {
    Get-ChildItem -LiteralPath $appHome -Force | Select-Object Name, Mode
}
```

如果想隔离当前学习实例，可以在**新的 PowerShell 窗口**先将 `MINIBOT_HOME` 设置到单独的目录，再运行 `uv run minibot` 或 `uv run minibot-web`。例如设置为 `$env:MINIBOT_HOME = Join-Path $env:LOCALAPPDATA 'MiniBot-源码学习'`。已有的 `.minibot` 数据不会随变量切换迁移。该窗口启动的进程会使用新位置，关闭窗口后该设置不会影响其他窗口。

想验证首次创建和环境变量的行为，可以运行现有测试。测试使用临时应用主目录，不修改你的真实配置。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_config_loading.py::test_bootstrap_global_config_writes_templates tests/test_config_loading.py::test_load_config_env_precedence_process_over_global
```

[返回全书目录](00-阅读总纲.md) · [配置字典](附录A-配置字典.md)
