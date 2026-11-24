"""验证终端日志中的完整回复、工具结果和异常堆栈。"""

from types import SimpleNamespace

import pytest

from src.minibot import main
from src.minibot.agent import Agent
from src.minibot.config.schema import Config, LLMConfig, SessionConfig
from src.minibot.utils.cli_logging import cli_file_logging, log_cli_event, logger


@pytest.mark.parametrize("stream_enabled", [False, True])
def test_cli_persists_each_completed_reply_and_exception(
    tmp_path, monkeypatch, capsys, stream_enabled,
):
    api_key = "fixture-key-to-redact"
    config = Config(
        workdir=tmp_path,
        app_home=tmp_path / "app",
        llm=LLMConfig(api_key=api_key, stream_enabled=stream_enabled),
        session=SessionConfig(enabled=False),
    )
    prompts = iter(["请求一", "请求二", "故障请求", "exit"])

    class FakeModel:
        model = "test-model"

        @staticmethod
        def reply(messages):
            """构造中文回复，或用可识别的异常模拟请求失败。"""
            prompt = messages[-1]["content"]
            if prompt == "故障请求":
                raise RuntimeError(f"示例故障 {api_key}")
            return f"完成{prompt[-1]} 🚀"

        async def create_message_async(self, *, messages, **kwargs):
            """返回一条非流式回复。"""
            message = SimpleNamespace(content=self.reply(messages), tool_calls=[])
            return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])

        async def create_message_stream_async(self, *, messages, **kwargs):
            """将回复拆成两个分片，模拟同一条流式消息。"""
            answer = self.reply(messages)

            async def chunks():
                """依次发出文本与结束分片。"""
                for content, reason in ((answer[:2], None), (answer[2:], "stop")):
                    delta = SimpleNamespace(content=content, tool_calls=[])
                    yield SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=reason)])

            return chunks()

        async def close(self):
            """模拟关闭客户端。"""

    def make_agent(config, **kwargs):
        """保留真实 Agent 和终端入口，只替换外部模型。"""
        assert any(getattr(handler, "encoding", None) == "utf-8" for handler in logger.handlers)
        return Agent(config, model_client=FakeModel(), **kwargs)

    monkeypatch.setenv("MINIBOT_RICH", "0")
    monkeypatch.setattr(main, "resolve_app_home", lambda: config.app_home)
    monkeypatch.setattr(main, "load_config", lambda **kwargs: config)
    monkeypatch.setattr(main, "_setup_readline", lambda path: None)
    monkeypatch.setattr(main, "prompt_toolkit_enabled", lambda: False)
    monkeypatch.setattr(main, "prompt_input", lambda label: next(prompts))
    monkeypatch.setattr(main, "Agent", make_agent)

    main.main()

    [log_path] = (config.app_home / "logs").glob("minibot-*.log")
    contents = log_path.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert log_path.name in output
    for reply in ("完成一 🚀", "完成二 🚀"):
        assert reply in output
        assert contents.count(reply) == 1
    assert "Traceback (most recent call last)" in contents
    assert "RuntimeError: 示例故障 [已隐藏]" in contents
    assert api_key not in contents


def test_cli_records_successful_tool_result(tmp_path):
    config = Config(workdir=tmp_path, app_home=tmp_path / "app")
    with cli_file_logging(config) as log_path:
        log_cli_event({
            "type": "tool_result",
            "session_id": "session-1",
            "tool_name": "示例工具",
            "tool_status": "success",
            "tool_output": "工具正常完成",
        })

    assert log_path is not None
    contents = log_path.read_text(encoding="utf-8")
    assert "INFO 会话 session-1 工具 示例工具 [success]" in contents
    assert "工具正常完成" in contents
