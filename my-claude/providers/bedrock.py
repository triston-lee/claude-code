"""
AWS Bedrock provider

对应原版 src/utils/model/providers.ts 中的 Bedrock 逻辑。
使用 anthropic SDK 的 AnthropicBedrock client。

需要配置环境变量：
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION (默认 us-east-1)
"""

from __future__ import annotations

import os
from typing import Generator

from providers.base import (
    ContentBlock,
    Provider,
    StreamEvent,
    StreamResult,
    Usage,
)

# Bedrock 模型名映射：短名 -> ARN 前缀
BEDROCK_MODEL_MAP = {
    "claude-opus-4-6": "us.anthropic.claude-opus-4-6-20250515-v1:0",
    "claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6-20250514-v1:0",
    "claude-haiku-4-5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}


class BedrockProvider(Provider):
    def __init__(self):
        try:
            import anthropic
            self._client = anthropic.AnthropicBedrock(
                aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize Bedrock client. "
                f"Ensure AWS credentials are configured: {e}"
            )

    @property
    def name(self) -> str:
        return "bedrock"

    def _resolve_model(self, model: str) -> str:
        return BEDROCK_MODEL_MAP.get(model, model)

    def stream(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        tools: list[dict],
        messages: list[dict],
    ) -> Generator[StreamEvent, None, StreamResult]:
        resolved = self._resolve_model(model)
        with self._client.messages.stream(
            model=resolved,
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
        resolved = self._resolve_model(model)
        kwargs: dict = {
            "model": resolved,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        response = self._client.messages.create(**kwargs)
        return _message_to_result(response)


def _message_to_result(msg) -> StreamResult:
    blocks = []
    for cb in msg.content:
        if cb.type == "text":
            blocks.append(ContentBlock(type="text", text=cb.text))
        elif cb.type == "tool_use":
            blocks.append(ContentBlock(
                type="tool_use", id=cb.id, name=cb.name, input=cb.input,
            ))
    return StreamResult(
        content=blocks,
        usage=Usage(
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        ),
        stop_reason=msg.stop_reason,
    )
