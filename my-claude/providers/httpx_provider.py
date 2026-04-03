"""
基于 httpx 的 Anthropic Provider（对应 core/client.py）

不依赖官方 SDK，直接调用 REST API + 解析 SSE 流。
这是"透明版"，你能看到每一层：HTTP 请求、SSE 格式、事件流。

与 AnthropicProvider 的对比：
  AnthropicProvider  → 使用 @anthropic-ai/sdk（黑盒）
  HttpxProvider      → 使用 httpx + 自研 SSE 解析器（透明）

激活方式：在 providers/registry.py 中指定 provider="httpx"，
或设置环境变量 CLAUDE_PROVIDER=httpx。
"""

from __future__ import annotations

from typing import Generator

from core.client import AnthropicClient
from core.streaming import (
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    InputJsonDeltaEvent,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    PingEvent,
    StreamedResponse,
    TextDeltaEvent,
    ToolUseBlock,
    TextBlock,
)
from providers.base import (
    ContentBlock,
    Provider,
    StreamEvent,
    StreamResult,
    Usage,
)


class HttpxProvider(Provider):
    """
    使用 core/client.py (httpx) 直连 Anthropic API 的 Provider。

    流式实现：
      1. AnthropicClient.stream() 调用 POST /v1/messages（stream=true）
      2. SSE 事件通过 ResponseAssembler 实时回调 + 最终组装
      3. 将 core/ 的类型转换为 providers/base.py 的统一接口
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        import os
        from core.client import ANTHROPIC_API_BASE
        self._client = AnthropicClient(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
            base_url=base_url or ANTHROPIC_API_BASE,
        )

    @property
    def name(self) -> str:
        return "anthropic-httpx"

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
        流式调用。在 text_callback 里 yield 文字事件，在 tool_start_callback 里 yield 工具事件。

        注意：因为 AnthropicClient.stream() 是同步阻塞的，
        我们通过 callback 把中间事件桥接出来。
        """
        events_buffer: list[StreamEvent] = []

        def text_cb(text: str) -> None:
            events_buffer.append(StreamEvent(type="text_delta", text=text))

        def tool_cb(name: str, tool_id: str) -> None:
            events_buffer.append(StreamEvent(type="tool_use_start", tool_name=name, tool_id=tool_id))

        # 由于 httpx.stream() 是边接收边处理，callback 在调用期间触发
        # 我们需要一个"边 yield 边消费 buffer"的机制
        # 解决方法：用生成器 + 手动 pump 模式

        # 实际上 AnthropicClient.stream() 目前是一次性消费整个流再返回
        # （text_callback 在中途被调用，但控制权无法 yield 给外部）
        # 因此这里采用更简单的"后处理"模式：先收集所有事件，再逐一 yield
        # 真正的并发流式需要 asyncio 版本（AsyncAnthropicClient）

        result = self._client.stream(
            model=model,
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            text_callback=text_cb,
            tool_start_callback=tool_cb,
        )

        # 按顺序 yield 已缓冲的事件
        for event in events_buffer:
            yield event

        # 转换 StreamedResponse → StreamResult
        return _streamed_to_result(result)

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> StreamResult:
        resp_dict = self._client.create(
            model=model,
            messages=messages,
            system=system,
            tools=tools or [],
            max_tokens=max_tokens,
        )
        return _dict_to_result(resp_dict)


# ---------------------------------------------------------------------------
# 格式转换
# ---------------------------------------------------------------------------

def _streamed_to_result(resp: StreamedResponse) -> StreamResult:
    """StreamedResponse (core/) → StreamResult (providers/base/)"""
    blocks: list[ContentBlock] = []
    for block in resp.content:
        if isinstance(block, TextBlock):
            blocks.append(ContentBlock(type="text", text=block.text))
        elif isinstance(block, ToolUseBlock):
            blocks.append(ContentBlock(
                type="tool_use",
                id=block.id,
                name=block.name,
                input=block.input,
            ))
    return StreamResult(
        content=blocks,
        usage=Usage(input_tokens=resp.input_tokens, output_tokens=resp.output_tokens),
        stop_reason=resp.stop_reason,
    )


def _dict_to_result(resp: dict) -> StreamResult:
    """非流式 API 响应 dict → StreamResult"""
    blocks: list[ContentBlock] = []
    for cb in resp.get("content", []):
        ctype = cb.get("type", "")
        if ctype == "text":
            blocks.append(ContentBlock(type="text", text=cb.get("text", "")))
        elif ctype == "tool_use":
            blocks.append(ContentBlock(
                type="tool_use",
                id=cb.get("id", ""),
                name=cb.get("name", ""),
                input=cb.get("input", {}),
            ))
    usage = resp.get("usage", {})
    return StreamResult(
        content=blocks,
        usage=Usage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        ),
        stop_reason=resp.get("stop_reason", "end_turn"),
    )
