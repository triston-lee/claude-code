"""
Provider 抽象基类（对应原版 src/services/api/client.ts）

所有 provider 必须实现：
  - stream()    : 流式调用，yield StreamEvent
  - create()    : 非流式调用（用于 compact 等场景）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generator


@dataclass
class StreamEvent:
    """流式事件，统一各 provider 的事件格式"""
    type: str                      # "text_delta" | "tool_use_start" | "tool_input_delta" | "content_block_stop" | "message_done"
    text: str = ""                 # text_delta 时的文本片段
    tool_name: str = ""            # tool_use_start 时的工具名
    tool_id: str = ""              # tool_use_start 时的 tool_use id
    index: int = 0                 # content block 的索引


@dataclass
class Usage:
    """token 用量"""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ContentBlock:
    """统一的 content block"""
    type: str              # "text" | "tool_use"
    text: str = ""         # type == "text" 时
    id: str = ""           # type == "tool_use" 时
    name: str = ""         # type == "tool_use" 时
    input: dict = field(default_factory=dict)  # type == "tool_use" 时


@dataclass
class StreamResult:
    """流式调用完成后的完整结果"""
    content: list[ContentBlock] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = ""


class Provider(ABC):
    """Provider 抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名称，如 'anthropic', 'bedrock', 'vertex'"""
        ...

    @abstractmethod
    def stream(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        tools: list[dict],
        messages: list[dict],
    ) -> Generator[StreamEvent, None, StreamResult]:
        """
        流式调用 API。
        yield StreamEvent，最终 return StreamResult。

        调用方式：
            gen = provider.stream(...)
            try:
                while True:
                    event = next(gen)
                    # 处理 event
            except StopIteration as e:
                result = e.value  # StreamResult
        """
        ...

    @abstractmethod
    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> StreamResult:
        """非流式调用，返回完整结果。用于 compact 等不需要流式的场景。"""
        ...
