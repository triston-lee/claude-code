"""
Anthropic HTTP 客户端（对应原版 src/services/api/claude.ts 的 API 请求部分）

使用 httpx 直接调用 Anthropic REST API，不依赖官方 SDK。
这让我们能清楚看到协议细节：请求体结构、SSE 格式、错误处理。

支持模式：
  - 流式：stream=True，返回 SSE 事件生成器
  - 非流式：stream=False，返回完整响应 dict

对应原版的关键设计：
  - 原版使用 @anthropic-ai/sdk 的 Stream<BetaRawMessageStreamEvent>
  - 原版通过 withRetry() 包装请求，最多重试 3 次
  - 原版在流开始时启动 watchdog timer 检测空闲超时
  本版保留重试和超时，但简化了 watchdog。
"""

from __future__ import annotations

import os
import time
from typing import Iterator, AsyncIterator

import httpx

from core.streaming import (
    ResponseAssembler,
    StreamedResponse,
    aiter_sse_events,
    iter_sse_events,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ANTHROPIC_API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 600.0  # 10 分钟，长任务需要

# 原版支持的 beta 特性（按需开启）
DEFAULT_BETAS = [
    "interleaved-thinking-2025-05-14",
    "prompt-caching-2024-07-31",
]


# ---------------------------------------------------------------------------
# 同步客户端
# ---------------------------------------------------------------------------

class AnthropicClient:
    """
    轻量级 Anthropic API 同步客户端。

    设计目标：透明 —— 你能看到每一个 HTTP 请求的细节。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = ANTHROPIC_API_BASE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }

    def _build_body(
        self,
        model: str,
        messages: list[dict],
        system: str,
        tools: list[dict],
        max_tokens: int,
        stream: bool,
    ) -> dict:
        body: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "stream": stream,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools
        return body

    # ------------------------------------------------------------------
    # 流式请求（主路径）
    # ------------------------------------------------------------------

    def stream(
        self,
        model: str,
        messages: list[dict],
        *,
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 8096,
        text_callback=None,
        tool_start_callback=None,
    ) -> StreamedResponse:
        """
        发送流式请求，实时回调文字增量，返回组装好的响应。

        text_callback(str): 每收到文字 delta 时调用
        tool_start_callback(name, id): 收到 tool_use 块开始时调用
        """
        body = self._build_body(model, messages, system, tools or [], max_tokens, stream=True)
        assembler = ResponseAssembler(
            text_callback=text_callback,
            tool_start_callback=tool_start_callback,
        )

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as http:
                    with http.stream(
                        "POST",
                        f"{self.base_url}/v1/messages",
                        json=body,
                        headers=self._headers(),
                    ) as response:
                        response.raise_for_status()
                        for event in iter_sse_events(response.iter_lines()):
                            assembler.feed(event)
                return assembler.result()

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                # 429 / 529 限速，指数退避
                if status in (429, 529) and attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    time.sleep(wait)
                    last_error = e
                    continue
                # 其他 4xx 直接抛出
                raise APIError(status, str(e)) from e

            except httpx.RequestError as e:
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    last_error = e
                    continue
                raise ConnectionError(f"Connection failed: {e}") from e

        raise last_error or RuntimeError("All retries exhausted")

    # ------------------------------------------------------------------
    # 非流式请求（fallback，用于较短的摘要/工具等）
    # ------------------------------------------------------------------

    def create(
        self,
        model: str,
        messages: list[dict],
        *,
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 8096,
    ) -> dict:
        """发送非流式请求，返回完整响应 dict。"""
        body = self._build_body(model, messages, system, tools or [], max_tokens, stream=False)

        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as http:
                    resp = http.post(
                        f"{self.base_url}/v1/messages",
                        json=body,
                        headers=self._headers(),
                    )
                    resp.raise_for_status()
                    return resp.json()

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status in (429, 529) and attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise APIError(status, str(e)) from e

            except httpx.RequestError as e:
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise ConnectionError(f"Connection failed: {e}") from e

        raise RuntimeError("All retries exhausted")


# ---------------------------------------------------------------------------
# 异步客户端（供将来的 asyncio 架构使用）
# ---------------------------------------------------------------------------

class AsyncAnthropicClient:
    """
    轻量级 Anthropic API 异步客户端。
    适合与 asyncio 并发工具执行（StreamingToolExecutor 风格）配合使用。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = ANTHROPIC_API_BASE,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }

    async def stream(
        self,
        model: str,
        messages: list[dict],
        *,
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 8096,
        text_callback=None,
        tool_start_callback=None,
    ) -> StreamedResponse:
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "stream": True,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools

        assembler = ResponseAssembler(
            text_callback=text_callback,
            tool_start_callback=tool_start_callback,
        )

        async with httpx.AsyncClient(timeout=self.timeout) as http:
            async with http.stream(
                "POST",
                f"{self.base_url}/v1/messages",
                json=body,
                headers=self._headers(),
            ) as response:
                response.raise_for_status()
                async for event in aiter_sse_events(response.aiter_lines()):
                    assembler.feed(event)

        return assembler.result()


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class APIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")
