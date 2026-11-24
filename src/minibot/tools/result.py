"""独立于服务商消息格式的内部工具执行结果。"""

from dataclasses import dataclass
from typing import Any, Literal

ToolStatus = Literal["success", "refused", "timeout", "error", "unknown_tool", "invalid_arguments"]


@dataclass(frozen=True)
class ToolOutcome:
    """提供给模型的文本和明确的执行状态。钩子诊断信息单独记录。"""

    text: str
    status: ToolStatus = "success"
    exit_code: int | None = None
    hook_error: str | None = None
    hook_phase: Literal["pre", "post"] | None = None
    artifact_id: str | None = None
    artifact_eligible: bool = True

    @property
    def is_error(self) -> bool:
        """根据工具状态和钩子错误判断该结果是否应标记为错误。"""
        return self.status != "success" or self.hook_error is not None

    def metadata(self) -> dict[str, Any]:
        """生成工具结果的结构化状态和可用诊断字段。"""
        data: dict[str, Any] = {"tool_status": self.status, "is_error": self.is_error}
        if self.exit_code is not None:
            data["tool_exit_code"] = self.exit_code
        if self.hook_error is not None:
            data["tool_hook_error"] = self.hook_error
            data["tool_hook_phase"] = self.hook_phase
        if self.artifact_id is not None and self.artifact_eligible:
            data["tool_artifact_id"] = self.artifact_id
        return data
