"""
SSE 流式响应解析器（对应原版 src/services/api/claude.ts 的流式部分）

Anthropic API 的 SSE 格式：
  event: message_start
  data: {"type":"message_start","message":{...}}

  event: content_block_start
  data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

  event: content_block_delta
  data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}

  event: content_block_delta
  data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"cmd\\""}}

  event: content_block_stop
  data: {"type":"content_block_stop","index":0}

  event: message_delta
  data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":42}}

  event: message_stop
  data: {"type":"message_stop"}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterator, Literal


# ---------------------------------------------------------------------------
# 事件数据类
# ---------------------------------------------------------------------------

@dataclass
class MessageStartEvent:
    type: Literal["message_start"] = "message_start"
    message_id: str = ""
    model: str = ""
    input_tokens: int = 0


@dataclass
class ContentBlockStartEvent:
    type: Literal["content_block_start"] = "content_block_start"
    index: int = 0
    block_type: str = ""   # "text" | "tool_use"
    tool_id: str = ""
    tool_name: str = ""


@dataclass
class TextDeltaEvent:
    type: Literal["text_delta"] = "text_delta"
    index: int = 0
    text: str = ""


@dataclass
class InputJsonDeltaEvent:
    type: Literal["input_json_delta"] = "input_json_delta"
    index: int = 0
    partial_json: str = ""


@dataclass
class ContentBlockStopEvent:
    type: Literal["content_block_stop"] = "content_block_stop"
    index: int = 0


@dataclass
class MessageDeltaEvent:
    type: Literal["message_delta"] = "message_delta"
    stop_reason: str = ""
    output_tokens: int = 0


@dataclass
class MessageStopEvent:
    type: Literal["message_stop"] = "message_stop"


@dataclass
class PingEvent:
    type: Literal["ping"] = "ping"


StreamEvent = (
    MessageStartEvent
    | ContentBlockStartEvent
    | TextDeltaEvent
    | InputJsonDeltaEvent
    | ContentBlockStopEvent
    | MessageDeltaEvent
    | MessageStopEvent
    | PingEvent
)


# ---------------------------------------------------------------------------
# 已组装的响应块（流结束后构建）
# ---------------------------------------------------------------------------

@dataclass
class TextBlock:
    type: Literal["text"] = "text"
    text: str = ""


@dataclass
class ToolUseBlock:
    type: Literal["tool_use"] = "tool_use"
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class StreamedResponse:
    """流式响应的最终组装结果"""
    content: list[TextBlock | ToolUseBlock] = field(default_factory=list)
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# SSE 行解析
# ---------------------------------------------------------------------------

def parse_sse_data(line: str) -> dict | None:
    """从 'data: {...}' 行提取 JSON，返回 None 表示跳过。"""
    if not line.startswith("data: "):
        return None
    payload = line[6:].strip()
    if payload in ("", "[DONE]"):
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def parse_event(data: dict) -> StreamEvent | None:
    """把 SSE data dict 转为对应的事件对象。"""
    etype = data.get("type", "")

    if etype == "message_start":
        msg = data.get("message", {})
        usage = msg.get("usage", {})
        return MessageStartEvent(
            message_id=msg.get("id", ""),
            model=msg.get("model", ""),
            input_tokens=usage.get("input_tokens", 0),
        )

    if etype == "content_block_start":
        block = data.get("content_block", {})
        return ContentBlockStartEvent(
            index=data.get("index", 0),
            block_type=block.get("type", ""),
            tool_id=block.get("id", ""),
            tool_name=block.get("name", ""),
        )

    if etype == "content_block_delta":
        index = data.get("index", 0)
        delta = data.get("delta", {})
        dtype = delta.get("type", "")
        if dtype == "text_delta":
            return TextDeltaEvent(index=index, text=delta.get("text", ""))
        if dtype == "input_json_delta":
            return InputJsonDeltaEvent(index=index, partial_json=delta.get("partial_json", ""))
        return None

    if etype == "content_block_stop":
        return ContentBlockStopEvent(index=data.get("index", 0))

    if etype == "message_delta":
        delta = data.get("delta", {})
        usage = data.get("usage", {})
        return MessageDeltaEvent(
            stop_reason=delta.get("stop_reason", ""),
            output_tokens=usage.get("output_tokens", 0),
        )

    if etype == "message_stop":
        return MessageStopEvent()

    if etype == "ping":
        return PingEvent()

    return None


# ---------------------------------------------------------------------------
# 同步迭代器（用于 httpx 同步客户端）
# ---------------------------------------------------------------------------

def iter_sse_events(lines: Iterator[str]) -> Iterator[StreamEvent]:
    """从行迭代器中解析 SSE 事件（同步版）。"""
    for line in lines:
        data = parse_sse_data(line)
        if data is None:
            continue
        event = parse_event(data)
        if event is not None:
            yield event


# ---------------------------------------------------------------------------
# 异步迭代器（用于 httpx 异步客户端）
# ---------------------------------------------------------------------------

async def aiter_sse_events(lines: AsyncIterator[str]) -> AsyncIterator[StreamEvent]:
    """从异步行迭代器中解析 SSE 事件。"""
    async for line in lines:
        data = parse_sse_data(line)
        if data is None:
            continue
        event = parse_event(data)
        if event is not None:
            yield event


# ---------------------------------------------------------------------------
# 流组装器：从事件流 → StreamedResponse
# ---------------------------------------------------------------------------

class ResponseAssembler:
    """
    消费 StreamEvent 序列，组装出完整的 StreamedResponse。

    用法（同步）：
        assembler = ResponseAssembler()
        for event in iter_sse_events(lines):
            assembler.feed(event)
        response = assembler.result()

    用法（流式打印）：
        assembler = ResponseAssembler(text_callback=lambda t: print(t, end="", flush=True))
        ...
    """

    def __init__(self, text_callback=None, tool_start_callback=None):
        """
        text_callback: 每收到文字 delta 时调用，参数为 str
        tool_start_callback: 收到 tool_use block 开始时调用，参数为 (name, id)
        """
        self._text_callback = text_callback
        self._tool_start_callback = tool_start_callback

        # index → 当前块状态
        self._blocks: dict[int, dict] = {}
        self._stop_reason: str = "end_turn"
        self._input_tokens: int = 0
        self._output_tokens: int = 0

    def feed(self, event: StreamEvent) -> None:
        if isinstance(event, MessageStartEvent):
            self._input_tokens = event.input_tokens

        elif isinstance(event, ContentBlockStartEvent):
            self._blocks[event.index] = {
                "type": event.block_type,
                "text": "",
                "tool_id": event.tool_id,
                "tool_name": event.tool_name,
                "json_parts": [],
            }
            if event.block_type == "tool_use" and self._tool_start_callback:
                self._tool_start_callback(event.tool_name, event.tool_id)

        elif isinstance(event, TextDeltaEvent):
            block = self._blocks.get(event.index)
            if block:
                block["text"] += event.text
                if self._text_callback:
                    self._text_callback(event.text)

        elif isinstance(event, InputJsonDeltaEvent):
            block = self._blocks.get(event.index)
            if block:
                block["json_parts"].append(event.partial_json)

        elif isinstance(event, MessageDeltaEvent):
            self._stop_reason = event.stop_reason or self._stop_reason
            self._output_tokens = event.output_tokens

    def result(self) -> StreamedResponse:
        content: list[TextBlock | ToolUseBlock] = []
        for idx in sorted(self._blocks):
            block = self._blocks[idx]
            if block["type"] == "text":
                if block["text"]:
                    content.append(TextBlock(text=block["text"]))
            elif block["type"] == "tool_use":
                raw_json = "".join(block["json_parts"])
                try:
                    parsed_input = json.loads(raw_json) if raw_json else {}
                except json.JSONDecodeError:
                    parsed_input = {}
                content.append(ToolUseBlock(
                    id=block["tool_id"],
                    name=block["tool_name"],
                    input=parsed_input,
                ))
        return StreamedResponse(
            content=content,
            stop_reason=self._stop_reason,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )
