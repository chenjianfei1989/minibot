# 配置 Bash 隔离

Bash 默认在宿主机运行。要在 Docker 中运行内置 Bash 工具，请准备可信的本地镜像，将 MiniBot 应用主目录下全局 `config/default.yaml` 中的 `tools.bash.backend` 设为 `docker`，然后重启 MiniBot。

```sh
docker pull debian:bookworm
```

```yaml
tools:
  timeout: 60
  bash:
    backend: docker
    image: debian:bookworm
    memory_mb: 512
    cpus: 1.0
    pids_limit: 128
```

选择 `local` 可继续在宿主机执行，选择 `disabled` 可停用内置 Bash。已有的 `BashTool(workdir, timeout)` 调用仍在本地执行。SDK 调用方也可以设置同样的策略。

```python
from pathlib import Path
from minibot import Minibot
from minibot.config import BashConfig, Config, ToolsConfig

bot = Minibot(config=Config(
    workdir=Path.cwd(),
    tools=ToolsConfig(bash=BashConfig(backend="docker")),
))
```

用 `image` 指定另一个已加载且提供 `/bin/sh` 的镜像，所需程序应在准备镜像时安装。MiniBot 在执行期间不会拉取镜像，Docker 失败时也不会回退到宿主机执行。声明了卷的镜像会被拒绝。每次运行都固定使用检查过的镜像 ID。

## 执行行为

每条命令在一个新容器内执行。解析后的工作区以可读写方式挂载为 `/workspace`，Shell 从该目录启动。POSIX 上容器使用宿主用户的 UID 和 GID。根文件系统只读，`/tmp` 提供 64 MiB 临时文件系统。容器禁用网络、Linux capabilities 和权限提升，遵守配置的内存、CPU 和 PID 限制。

MiniBot 不会转发宿主环境变量，也不会挂载用户主目录或 Docker 套接字。镜像定义的环境变量仍可用。Docker 客户端使用宿主环境连接本地 Unix 套接字或 Windows 命名管道，拒绝远程端点。`DOCKER_CONTEXT` 优先于 `DOCKER_HOST`。

成功时沿用原有输出格式。失败时在输出之前附上退出码。输出采集使用有界缓冲区，按 UTF-8 解码并替换无效字节。危险命令检查和队友工作区锁仍适用。

`tools.timeout` 覆盖镜像检查、容器创建、运行和结果检查。超时或取消会触发容器删除，并检查容器已不存在。清理阶段每次管理调用最多可额外延长 10 秒。删除前会等待容器创建操作结束。管理调用超时时，MiniBot 会报告清理状态无法确认，并附上唯一容器名。取消期间，清理失败保留取消状态，并通过日志和 Agent 系统事件报告。

## 隔离范围

要将 Bash 和文件工具都放入 Docker，请[配置 Docker 工作区](工作区后端.md)。

此策略仅隔离内置 Bash 工具。文件工具、Python 工具、Hooks、MCP 工具和自定义 SDK 工具仍保留原有访问权限。工作区内已有的文件和凭证可被命令读取、更改或删除。请使用可信的 Docker 守护进程和镜像。容器无法防御已遭入侵的守护进程或内核。

本地模式直接在宿主机运行。POSIX 上，执行完成、超时或取消时，MiniBot 会终止并回收其 Shell 进程，并停止同进程组的普通子进程。另建会话的进程可脱离此进程组。Windows 通过 `taskkill /T /F` 尽力终止进程树。这项变更当时未验证 Windows 的运行时行为。

## 运行验证

常规测试使用真实本地子进程和确定性的 Docker 控制同步点。真实 Docker 测试需要本地守护进程已启动，并预先加载 `debian:bookworm` 镜像。

```sh
MINIBOT_TEST_DOCKER=1 uv run --with pytest --with pytest-asyncio pytest tests/test_bash_docker_integration.py -q
```

主动启用的 Docker 测试在守护进程或镜像不可用时会失败。测试覆盖工作区访问、退出状态、固定容器策略、宿主环境和文件隔离、超时、取消、启动失败及容器确已清除。测试固定使用 `debian:bookworm`，独立于全局配置。
