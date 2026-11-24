"""为终端会话写入 UTF-8 运行日志。"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sys

from ..config.schema import Config
from ..config.workspace import require_outside_workspace
from ..events import StreamEvent


logger = logging.getLogger("minibot.cli")
logger.addHandler(logging.NullHandler())
logger.propagate = False


class _CliLogFormatter(logging.Formatter):
    """格式化输出并隐藏当前配置中的 API 密钥和数据库连接串。"""

    def __init__(self, config: Config) -> None:
        """保留配置引用，以便在终端切换模型后使用最新密钥。"""
        super().__init__("%(asctime)s %(levelname)s %(message)s")
        self._config = config

    def format(self, record: logging.LogRecord) -> str:
        """清理日志正文和异常堆栈里的已知凭证。"""
        message = super().format(record)
        for value in (self._config.memory.database_url, self._config.llm.api_key):
            if value:
                message = message.replace(value, "[已隐藏]")
        return message


@contextmanager
def cli_file_logging(config: Config) -> Iterator[Path | None]:
    """为本次启动打开日志文件，离开终端入口时释放文件句柄。"""
    directory = config.app_home / "logs"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"minibot-{stamp}-{os.getpid()}.log"
    try:
        require_outside_workspace(config, directory, "CLI log directory")
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8", errors="backslashreplace")
    except (OSError, ValueError) as exc:
        print(f"无法写入 MiniBot 日志 {path}: {exc}", file=sys.stderr)
        yield None
        return

    handler.setFormatter(_CliLogFormatter(config))
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield path
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.close()


def log_cli_event(event: StreamEvent) -> None:
    """记录完整回复、工具结果和运行状态，跳过流式增量和内部推理。"""
    event_type = event.get("type")
    session_id = event.get("session_id", "")
    if event_type == "assistant_end" and event.get("content"):
        logger.info("会话 %s 助手回复\n%s", session_id, event["content"])
    elif event_type == "tool_result":
        level = logging.WARNING if event.get("is_error") else logging.INFO
        logger.log(
            level, "会话 %s 工具 %s [%s]\n%s",
            session_id, event.get("tool_name", ""), event.get("tool_status", ""), event.get("tool_output", ""),
        )
    elif event_type == "system" and event.get("message"):
        error = event.get("data", {}).get("error")
        if error:
            logger.warning("会话 %s %s\n%s", session_id, event["message"], error)
        else:
            logger.info("会话 %s %s", session_id, event["message"])
