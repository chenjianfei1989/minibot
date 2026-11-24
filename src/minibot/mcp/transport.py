"""MCP 传输方式实现。"""

import asyncio
import json
import ntpath
import os
from pathlib import Path
import shutil
from abc import ABC, abstractmethod
from typing import Any

import httpx


class MCPTransport(ABC):
    """MCP 传输方式的抽象基类。"""

    @abstractmethod
    async def connect(self) -> None:
        """建立连接。"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """关闭连接。"""
        pass

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """发送消息并等待响应。"""
        pass

    @abstractmethod
    async def notify(self, message: dict[str, Any]) -> None:
        """发送无需等待响应的 JSON-RPC 通知。"""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """检查传输连接是否已建立。"""
        pass


class StdioTransport(MCPTransport):
    """用于 stdio MCP 服务的传输方式。"""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ):
        """保存 stdio 服务的启动命令、环境和待处理请求状态。"""
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd

        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._read_task: asyncio.Task | None = None

    def _resolve_command(self) -> str:
        """将命令解析为当前操作系统可用的可执行文件路径。"""
        command = (self.command or "").strip()
        if not command:
            raise FileNotFoundError("MCP stdio command is not configured")

        if os.name != "nt":
            return command

        if ntpath.isabs(command) or "\\" in command or "/" in command:
            return command

        for suffix in (".cmd", ".exe", ".bat", ".ps1"):
            resolved = shutil.which(f"{command}{suffix}")
            if resolved:
                return resolved

        resolved = shutil.which(command)
        if resolved:
            return resolved

        return command

    @property
    def is_connected(self) -> bool:
        """判断 stdio 服务进程是否仍处于运行状态。"""
        return self._process is not None and self._process.returncode is None

    async def connect(self) -> None:
        """启动 MCP 服务进程。"""
        env = dict(os.environ)
        env.update(self.env)
        executable = self._resolve_command()

        self._process = await asyncio.create_subprocess_exec(
            executable,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self.cwd,
        )

        # 开始读取响应。
        self._read_task = asyncio.create_task(self._read_loop())

    async def disconnect(self) -> None:
        """停止 MCP 服务进程。"""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()

    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON-RPC 消息并等待响应。"""
        if not self.is_connected:
            raise RuntimeError("Transport not connected")

        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            **message,
        }

        # 为响应创建 Future。
        future: asyncio.Future = asyncio.Future()
        self._pending[request_id] = future

        # 发送请求。
        data = json.dumps(request) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

        # 等待响应。
        try:
            return await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise

    async def notify(self, message: dict[str, Any]) -> None:
        """发送无需等待响应的 JSON-RPC 通知。"""
        if not self.is_connected:
            raise RuntimeError("Transport not connected")

        notification = {
            "jsonrpc": "2.0",
            **message,
        }
        data = json.dumps(notification) + "\n"
        self._process.stdin.write(data.encode())
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        """读取服务端响应。"""
        while self.is_connected:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                data = json.loads(line.decode())
                request_id = data.get("id")

                if request_id and request_id in self._pending:
                    future = self._pending.pop(request_id)
                    if "error" in data:
                        future.set_exception(
                            RuntimeError(data["error"].get("message", "Unknown error"))
                        )
                    else:
                        future.set_result(data.get("result", {}))

            except json.JSONDecodeError:
                continue
            except Exception:
                break


class SSETransport(MCPTransport):
    """用于 SSE MCP 服务的传输方式。"""

    def __init__(self, url: str, headers: dict[str, str] | None = None):
        """保存 SSE 端点并初始化连接及请求状态。"""
        self.url = url
        self.headers = headers or {}
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """判断 SSE 传输当前是否已连接。"""
        return self._connected and self._client is not None

    async def connect(self) -> None:
        """建立 HTTP 连接。"""
        self._client = httpx.AsyncClient(
            base_url=self.url,
            headers=self.headers,
            timeout=30.0,
        )
        self._connected = True

    async def disconnect(self) -> None:
        """关闭 HTTP 连接。"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """通过 HTTP POST 发送请求。"""
        if not self.is_connected:
            raise RuntimeError("Transport not connected")

        response = await self._client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                **message,
            },
        )
        response.raise_for_status()

        data = response.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "Unknown error"))

        return data.get("result", {})

    async def notify(self, message: dict[str, Any]) -> None:
        """通过 HTTP POST 发送 JSON-RPC 通知。"""
        if not self.is_connected:
            raise RuntimeError("Transport not connected")

        response = await self._client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                **message,
            },
        )
        response.raise_for_status()
