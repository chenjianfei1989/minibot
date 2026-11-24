"""管理本地和 Docker 命令的启动、输出采集、超时和清理。"""

import asyncio
import codecs
import csv
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import dataclass, field
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory, gettempdir
import uuid
from typing import Protocol

from ...config.schema import BashConfig, WorkspaceConfig
from ...config.workspace import require_outside_root
from ...core.workspace import DockerContainer, restricted_root_key

_OUTPUT_LIMIT = 50000
_ADMIN_TIMEOUT = 10.0
_DURABLE_LABEL = "io.minibot.durable-container"


class ExecutionCleanupCancelledError(asyncio.CancelledError):
    """取消已完成，并附带明确的资源清理诊断信息。"""


@dataclass(frozen=True)
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    output_exceeded: bool = False
    incomplete_output: bool = False


@dataclass(frozen=True)
class _DrainedOutput:
    data: bytes
    exceeded: bool
    incomplete: bool


async def _settle(task: asyncio.Task):
    """等待清理任务结束，并记录等待期间收到的取消信号。"""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    try:
        result = task.result()
    except Exception as exc:
        if cancelled:
            raise ExecutionCleanupCancelledError(str(exc)) from exc
        raise
    if cancelled:
        raise asyncio.CancelledError
    return result


async def _drain(reader: asyncio.StreamReader, limit: int) -> _DrainedOutput:
    """持续读取流，限制保留的字节数并记录输出是否被截断。"""
    output = bytearray()
    exceeded = False
    try:
        while chunk := await reader.read(65536):
            spare = limit - len(output)
            if len(chunk) > spare:
                exceeded = True
            output.extend(chunk[:spare])
    except asyncio.CancelledError:
        # 只有拥有读取任务的管理器才会在限时读取结束后取消这些任务。
        return _DrainedOutput(bytes(output), exceeded, True)
    return _DrainedOutput(bytes(output), exceeded, False)


def _windows_output_encodings() -> tuple[str, ...]:
    """读取 Windows 控制台输出代码页，并为本机程序保留系统编码。"""
    from ctypes import WinDLL

    page = WinDLL("kernel32").GetConsoleOutputCP()
    return (f"cp{page}", "oem", "mbcs") if page else ("oem", "mbcs")


def _decode_process_output(
    data: bytes, fallback_encodings: tuple[str, ...], *, truncated: bool = False,
) -> str:
    """优先使用 UTF-8 解码，再尝试 Windows 本机命令的输出编码。"""
    for encoding in ("utf-8", *fallback_encodings):
        try:
            decoder = codecs.getincrementaldecoder(encoding)()
            # 达到字节上限时，最后一个多字节字符可能没有收完整。
            return decoder.decode(data, final=not truncated)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """按操作系统结束受管的进程树。"""
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif proc.returncode is None:
        killer = None
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(proc.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            async with asyncio.timeout(_ADMIN_TIMEOUT):
                _, error = await killer.communicate()
            if killer.returncode and proc.returncode is None:
                raise RuntimeError(_decode_process_output(error, _windows_output_encodings()))
        except (OSError, TimeoutError, RuntimeError) as exc:
            if killer is not None and killer.returncode is None:
                killer.kill()
                await killer.wait()
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise RuntimeError(f"taskkill could not confirm tree cleanup: {exc}") from exc
    while proc.returncode is None:
        await asyncio.sleep(0.01)
    await proc.wait()


async def _feed_stdin(writer: asyncio.StreamWriter, data: bytes) -> None:
    """把请求数据写入子进程的标准输入并关闭写端。"""
    try:
        with suppress(BrokenPipeError, ConnectionResetError):
            for start in range(0, len(data), 65536):
                writer.write(data[start:start + 65536])
                await writer.drain()
    finally:
        writer.close()


async def _process(
    *args: str, cwd: Path, env: dict[str, str] | None = None, output_limit: int | None = None,
    stdin: bytes | None = None, fallback_encodings: tuple[str, ...] = (),
) -> ExecutionResult:
    """启动受管进程，采集标准输出和错误，并在取消或超时时等待清理。"""
    per_stream_limit = _OUTPUT_LIMIT if output_limit is None else output_limit
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *args, cwd=cwd, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        start_new_session=os.name == "posix",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    ))
    proc = None
    readers = []
    writer = None
    try:
        proc = await asyncio.shield(spawn)
        readers = [
            asyncio.create_task(_drain(proc.stdout, per_stream_limit)),
            asyncio.create_task(_drain(proc.stderr, per_stream_limit)),
        ]
        if stdin is not None:
            writer = asyncio.create_task(_feed_stdin(proc.stdin, stdin))
        # Shell 退出后，Process.wait 仍可能等待子进程继承的管道。
        while proc.returncode is None:
            await asyncio.sleep(0.01)
    finally:
        interrupted = isinstance(sys.exception(), asyncio.CancelledError)

        async def finalize():
            """收尾子进程，处理尚未完成的启动和输出读取任务。"""
            nonlocal proc, readers
            if proc is None:
                proc = await spawn
            if not readers:
                readers = [
                    asyncio.create_task(_drain(proc.stdout, per_stream_limit)),
                    asyncio.create_task(_drain(proc.stderr, per_stream_limit)),
                ]
            if writer is not None:
                writer.cancel()
            if proc.stdin is not None:
                proc.stdin.close()
            await _kill_tree(proc)
            if writer is not None:
                await asyncio.gather(writer, return_exceptions=True)
            # 分离的会话不受本地管理器管控，可能仍持有管道。
            done, pending = await asyncio.wait(readers, timeout=1)
            for reader in pending:
                reader.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            # asyncio Process 没有公开的关闭管道方法。脱离控制的会话可能仍持有文件描述符，
            # 因此限时读取结束后关闭本进程的传输对象。
            proc._transport.close()
        try:
            await _settle(asyncio.create_task(finalize()))
        except Exception as exc:
            if interrupted:
                diagnostic = f"Process cleanup failed during cancellation: {exc}"
                logging.getLogger(__name__).error(diagnostic)
                raise ExecutionCleanupCancelledError(diagnostic) from exc
            raise
    stdout, stderr = [
        reader.result() if not reader.cancelled() else _DrainedOutput(b"", False, True)
        for reader in readers
    ]
    exceeded = output_limit is not None and (
        stdout.exceeded or stderr.exceeded or len(stdout.data) + len(stderr.data) > output_limit
    )
    return ExecutionResult(
        _decode_process_output(stdout.data, fallback_encodings, truncated=stdout.exceeded or stdout.incomplete),
        _decode_process_output(stderr.data, fallback_encodings, truncated=stderr.exceeded or stderr.incomplete),
        proc.returncode, output_exceeded=exceeded, incomplete_output=stdout.incomplete or stderr.incomplete,
    )


@dataclass(frozen=True)
class LocalCommand:
    workdir: Path

    async def run(
        self, command: str, *, timeout: float, output_limit: int | None = None,
    ) -> ExecutionResult:
        """在给定超时和输出限制下执行本地命令。"""
        async with asyncio.timeout(timeout):
            if os.name == "nt":
                return await _process(
                    os.environ.get("COMSPEC", "cmd.exe"), "/c", command,
                    cwd=self.workdir, output_limit=output_limit,
                    fallback_encodings=_windows_output_encodings(),
                )
            return await _process("/bin/sh", "-c", command, cwd=self.workdir, output_limit=output_limit)


def _trusted_docker_cli(workdir: Path, env: dict[str, str]) -> str:
    """从受信任的搜索目录确定 Docker CLI 的可执行路径。"""
    search_dirs = []
    for entry in env.get("PATH", os.defpath).split(os.pathsep):
        directory = Path(entry)
        if not directory.is_absolute():
            continue
        try:
            require_outside_root(workdir, directory, "Docker CLI search directory")
        except ValueError:
            continue
        search_dirs.append(str(directory))
    env["PATH"] = os.pathsep.join(search_dirs)
    executable = shutil.which("docker", path=env["PATH"]) if search_dirs else None
    if executable is None:
        raise RuntimeError("Docker CLI was not found on a trusted absolute PATH")
    executable_path = Path(executable)
    require_outside_root(workdir, executable_path, "Docker CLI")
    config_dir = Path(env.get("DOCKER_CONFIG") or Path.home() / ".docker").expanduser().absolute()
    require_outside_root(workdir, config_dir, "Docker CLI configuration")
    env["DOCKER_CONFIG"] = str(config_dir)
    return str(executable_path)


@dataclass(frozen=True)
class DockerEngine:
    endpoint: str
    engine_id: str


class DockerLease(Protocol):
    @property
    def engine(self) -> DockerEngine:
        """返回容器租约绑定的 Docker 守护进程标识。"""
        ...
    def pending(self) -> DockerContainer | None:
        """读取目前仍需处理的容器租约记录。"""
        ...
    def reserve(self, name: str) -> None:
        """登记即将创建的容器名。"""
        ...
    def confirm(self, name: str, container_id: str) -> None:
        """确认租约中指定容器的完整 ID。"""
        ...
    def release(self, name: str) -> None:
        """释放指定容器的租约记录。"""
        ...


@dataclass(frozen=True)
class _DockerClient:
    executable: str
    cwd: Path
    env: dict[str, str]

    async def cli(self, *args: str) -> ExecutionResult:
        """在管理操作的时限内发起 Docker CLI 调用。"""
        async with asyncio.timeout(_ADMIN_TIMEOUT):
            return await _process(self.executable, *args, cwd=self.cwd, env=self.env)

    async def checked(self, *args: str) -> str:
        """执行 Docker 管理命令，失败时将诊断转换为异常。"""
        result = await self.cli(*args)
        if result.exit_code or result.incomplete_output:
            raise RuntimeError(f"Docker {' '.join(args[:2])} failed: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout

    async def image_id(self, image: str) -> str:
        """查询镜像信息，验证配置并返回本地镜像 ID。"""
        details = json.loads(await self.checked("image", "inspect", image))[0]
        if details.get("Config", {}).get("Volumes"):
            raise RuntimeError("Docker Bash rejects image-declared volumes")
        return details["Id"]

    async def engine(self) -> DockerEngine:
        """读取 Docker 守护进程标识及连接端点。"""
        engine_id = (await self.checked("info", "--format", "{{.ID}}")).strip()
        if not engine_id:
            raise RuntimeError("Docker did not report a daemon ID")
        return DockerEngine(self.env["DOCKER_HOST"], engine_id)

    async def reconcile(self, record: DockerContainer) -> None:
        # 如果容器创建响应未送达 MiniBot，可用准确的容器名
        # 查证创建是否已提交。已知容器 ID 也能处理此前已删除容器的情况。
        """根据租约查找仍存在的容器，完成删除并核验清理结果。"""
        async def matches() -> list[str]:
            """查找租约可能关联的 Docker 容器标识。"""
            result = await self.checked(
                "ps", "--all", "--no-trunc", "--filter", f"name=^/{record.name}$",
                "--format", "{{.ID}}",
            )
            return result.split()

        found = await matches()
        if not found:
            if record.container_id is None:
                raise RuntimeError("Docker create may still be in flight")
            # 通过 ID 查找已改名的容器。稍后启动容器时也会使用这个 ID。
            found = (await self.checked(
                "ps", "--all", "--no-trunc", "--filter", f"id={record.container_id}", "--format", "{{.ID}}",
            )).split()
            if not found:
                return
        if len(found) != 1 or (record.container_id is not None and found != [record.container_id]):
            raise RuntimeError("Docker container identity changed")
        container_id = found[0]
        labels = json.loads(await self.checked("inspect", "--format", "{{json .Config.Labels}}", container_id))
        if not isinstance(labels, dict) or labels.get(_DURABLE_LABEL) != record.name:
            raise RuntimeError("Docker container is not owned by this execution")
        await self.checked("rm", "-f", "--volumes", container_id)
        remaining = await self.checked(
            "ps", "--all", "--no-trunc", "--filter", f"id={container_id}", "--format", "{{.ID}}",
        )
        if remaining.strip():
            raise RuntimeError("Docker container removal could not be confirmed")


@dataclass(frozen=True)
class DockerCommand:
    workdir: Path
    config: BashConfig | WorkspaceConfig
    lease: DockerLease | None = None
    _root_key: tuple[int, int] | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        """根据配置初始化工作区根目录和执行配置。"""
        if isinstance(self.config, WorkspaceConfig):
            object.__setattr__(self, "_root_key", restricted_root_key(self.workdir))
        elif self.lease is not None:
            raise ValueError("A durable Docker lease requires a restricted workspace")

    def bind_root(self) -> Path:
        """绑定并校验当前工作区根目录标识。"""
        if self._root_key is None:
            return self.workdir.resolve()
        if restricted_root_key(self.workdir) != self._root_key:
            raise ValueError("The restricted Docker workspace directory was replaced.")
        return self.workdir

    async def run(
        self, command: str, *, timeout: float, output_limit: int | None = None,
    ) -> ExecutionResult:
        """在 Docker 工作区运行一条 Shell 命令。"""
        return await self.execute("/bin/sh", "-c", command, timeout=timeout, output_limit=output_limit)

    @asynccontextmanager
    async def _client(self):
        """构造执行配置所允许的 Docker CLI 客户端。"""
        restricted = isinstance(self.config, WorkspaceConfig)
        env = dict(os.environ)
        executable = _trusted_docker_cli(self.bind_root(), env) if restricted else "docker"
        client = _DockerClient(executable, Path(self.workdir.anchor) if restricted else self.workdir, env)
        endpoint = env.get("DOCKER_HOST") if not env.get("DOCKER_CONTEXT") else None
        if not endpoint:
            context = env.get("DOCKER_CONTEXT") or (await client.checked("context", "show")).strip()
            contexts = json.loads(await client.checked("context", "inspect", context))
            endpoint = contexts[0]["Endpoints"]["docker"]["Host"]
        if not endpoint.startswith(("unix://", "npipe://")):
            raise RuntimeError("Docker Bash requires a local Unix socket or Windows named pipe endpoint")
        env.pop("DOCKER_CONTEXT", None)
        env["DOCKER_HOST"] = endpoint
        if not restricted:
            yield client
            return
        # 原有 Docker CLI 配置可能自动注入代理设置。
        temp_parent = Path(gettempdir())
        require_outside_root(self.workdir, temp_parent, "Docker CLI temporary directory")
        with TemporaryDirectory(prefix="minibot-docker-", dir=temp_parent) as cli_config:
            env["DOCKER_CONFIG"] = cli_config
            if self.lease is not None and await client.engine() != self.lease.engine:
                raise RuntimeError("Docker daemon identity changed")
            yield client

    async def probe(self) -> tuple[DockerEngine, str]:
        """查询当前 Docker 守护进程和配置镜像的标识。"""
        async with self._client() as client:
            return await client.engine(), await client.image_id(self.config.image)

    async def reconcile(self) -> None:
        """核对租约并清理之前未结案的容器。"""
        if self.lease is None:
            return
        async with self._client() as client:
            if (record := self.lease.pending()) is not None:
                await client.reconcile(record)
                self.lease.release(record.name)

    async def execute(
        self, program: str, *arguments: str, timeout: float, output_limit: int | None = None,
        stdin: bytes | None = None,
    ) -> ExecutionResult:
        """管理 Docker 命令所需资源，在作用域内执行指定程序。"""
        async with AsyncExitStack() as resources:
            return await self._execute(
                resources, program, *arguments, timeout=timeout, output_limit=output_limit, stdin=stdin,
            )

    async def _execute(
        self, resources: AsyncExitStack, program: str, *arguments: str, timeout: float, output_limit: int | None,
        stdin: bytes | None,
    ) -> ExecutionResult:
        """校验执行环境，创建容器并收集程序输出，退出时进行清理。"""
        restricted = isinstance(self.config, WorkspaceConfig)
        label = "workspace" if restricted else "bash"
        name = f"minibot-{label}-{uuid.uuid4().hex}"
        create_task = None
        may_exist = False
        lease = self.lease
        if lease is not None and lease.pending() is not None:
            raise RuntimeError("Docker cleanup is still pending for this child")

        async def cleanup():
            """等待容器创建操作稳定后，核对容器状态并清理。"""
            create_uncertain = False
            create_failed = False
            if create_task is not None:
                try:
                    await create_task
                except TimeoutError:
                    create_uncertain = True
                except Exception:
                    create_failed = True
            if lease is not None:
                record = lease.pending()
                if record is None or record.name != name:
                    raise RuntimeError("Docker container lease changed")
                await client.reconcile(record)
                lease.release(name)
                return
            removal = await client.cli("rm", "-f", "--volumes", name)
            remaining = await client.checked("ps", "--all", "--filter", f"name=^{name}$", "--format", "{{.ID}}")
            if create_uncertain:
                raise RuntimeError("create exceeded its administrative deadline; daemon completion cannot be proved")
            if remaining.strip() or (removal.exit_code and not create_failed):
                raise RuntimeError(f"Docker removal failed: {removal.stderr.strip()}")

        try:
            async with asyncio.timeout(timeout):
                client = await resources.enter_async_context(self._client())
                image_id = await client.image_id(self.config.image)
                mount = io.StringIO(newline="")
                mount_options = ["type=bind", f"src={self.bind_root()}", "dst=/workspace"]
                if restricted:
                    mount_options.append("bind-recursive=disabled")
                csv.writer(mount, lineterminator="").writerow(mount_options)
                args = [
                    "create", "--name", name, "--pull", "never", "--init",
                    "--network", self.config.network if restricted else "none", "--read-only", "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges", "--memory", f"{self.config.memory_mb}m",
                    "--cpus", str(self.config.cpus), "--pids-limit", str(self.config.pids_limit),
                    "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=64m", "--mount", mount.getvalue(),
                    "--workdir", "/workspace",
                ]
                if os.name == "posix":
                    args += ["--user", f"{os.getuid()}:{os.getgid()}"]
                if stdin is not None:
                    args.append("--interactive")
                if lease is not None:
                    args += ["--label", f"{_DURABLE_LABEL}={name}"]
                args += ["--entrypoint", program, image_id, *arguments]

                async def create() -> str:
                    """创建容器，并在使用租约时登记 Docker 返回的完整容器 ID。"""
                    container_id = (await client.checked(*args)).strip()
                    if lease is None:
                        return name
                    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
                        raise RuntimeError("Docker did not return a full container ID")
                    lease.confirm(name, container_id)
                    return container_id

                if lease is not None:
                    lease.reserve(name)
                may_exist = True
                create_task = asyncio.create_task(create())
                attached_id = await asyncio.shield(create_task)
                if restricted:
                    self.bind_root()
                attach = [client.executable, "start", "--attach"]
                input_options = {}
                if stdin is not None:
                    attach.append("--interactive")
                    input_options["stdin"] = stdin
                result = await _process(
                    *attach, attached_id, cwd=client.cwd, env=client.env, output_limit=output_limit, **input_options,
                )
                state = json.loads(await client.checked("inspect", "--format", "{{json .State}}", attached_id))
                if state["Running"] or state.get("Error"):
                    raise RuntimeError(f"Docker command did not finish: {state.get('Error') or 'still running'}")
                if result.exit_code != state["ExitCode"]:
                    raise RuntimeError(f"Docker attach failed: {result.stderr.strip()}")
                return result
        finally:
            interrupted = isinstance(sys.exception(), asyncio.CancelledError)
            if may_exist:
                try:
                    await _settle(asyncio.create_task(cleanup()))
                except (Exception, ExecutionCleanupCancelledError) as exc:
                    diagnostic = f"Docker cleanup uncertain for {name}: {exc}"
                    if interrupted or isinstance(exc, asyncio.CancelledError):
                        logging.getLogger(__name__).error(diagnostic)
                        raise ExecutionCleanupCancelledError(diagnostic) from exc
                    raise RuntimeError(diagnostic) from exc
