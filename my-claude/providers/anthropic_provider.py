"""
Anthropic 直连 provider（默认）

对应原版 src/services/api/claude.ts
使用官方 anthropic Python SDK。
"""

from __future__ import annotations

from typing import Generator

import anthropic

from providers.base import (
    ContentBlock,
    Provider,
    StreamEvent,
    StreamResult,
    Usage,
)


class AnthropicProvider(Provider):
    def __init__(self, api_key: str, base_url: str | None = None):
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)

    @property
    def name(self) -> str:
        return "anthropic"

    def stream(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        tools: list[dict],
        messages: list[dict],
    ) -> Generator[StreamEvent, None, StreamResult]:
        with self._client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        ) as s:
            for event in s:
                if event.type == "content_block_start":
                    cb = event.content_block
                    if hasattr(cb, "name") and cb.type == "tool_use":
                        yield StreamEvent(
                            type="tool_use_start",
                            tool_name=cb.name,
                            tool_id=cb.id,
                            index=event.index,
                        )
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        yield StreamEvent(type="text_delta", text=delta.text)
                    elif hasattr(delta, "partial_json") and delta.partial_json:
                        yield StreamEvent(
                            type="tool_input_delta",
                            text=delta.partial_json,
                        )
                elif event.type == "content_block_stop":
                    yield StreamEvent(type="content_block_stop", index=event.index)

            final = s.get_final_message()

        return _message_to_result(final)

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> StreamResult:
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = self._client.messages.create(**kwargs)
        return _message_to_result(response)


def _message_to_result(msg) -> StreamResult:
    """把 SDK Message 对象转成统一的 StreamResult"""
    blocks = []
    for cb in msg.content:
        if cb.type == "text":
            blocks.append(ContentBlock(type="text", text=cb.text))
        elif cb.type == "tool_use":
            blocks.append(ContentBlock(
                type="tool_use",
                id=cb.id,
                name=cb.name,
                input=cb.input,
            ))
    return StreamResult(
        content=blocks,
        usage=Usage(
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        ),
        stop_reason=msg.stop_reason,
    )
