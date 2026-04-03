"""
单轮查询函数（对应原版 src/query.ts 的核心流程）

用 core/client.py 替代 anthropic SDK，实现：
  1. 流式输出（文字实时打印）
  2. 工具调用提取
  3. 返回组装好的 messages（与原版 conversation.py 接口兼容）

未来扩展点（对应原版）：
  - 并发工具执行（StreamingToolExecutor）
  - 权限 pre-check
  - hook 生命周期
  - 自动压缩触发
"""

from __future__ import annotations

from core.client import AnthropicClient
from core.streaming import StreamedResponse, TextBlock, ToolUseBlock


def query_once(
    client: AnthropicClient,
    model: str,
    messages: list[dict],
    system: str,
    tools: list[dict],
    max_tokens: int,
    *,
    text_callback=None,
    tool_start_callback=None,
) -> StreamedResponse:
    """
    发一轮请求，流式打印文字，返回 StreamedResponse。

    参数
    ----
    client: AnthropicClient 实例（core/client.py）
    text_callback: 文字 delta 回调，用于实时渲染
    tool_start_callback: 工具块开始回调，用于显示 "正在调用 xxx..."

    返回
    ----
    StreamedResponse，包含：
      .content      — TextBlock / ToolUseBlock 列表
      .stop_reason  — "end_turn" | "tool_use" | ...
      .input_tokens — 本轮输入 token
      .output_tokens— 本轮输出 token
    """
    return client.stream(
        model=model,
        messages=messages,
        system=system,
        tools=tools,
        max_tokens=max_tokens,
        text_callback=text_callback,
        tool_start_callback=tool_start_callback,
    )


def response_to_api_message(response: StreamedResponse) -> dict:
    """
    把 StreamedResponse 转为 messages API 格式的 assistant 消息。

    原版：messages.append({"role": "assistant", "content": response.content})
    这里做等价转换，让 conversation.py 可以直接 append。
    """
    content = []
    for block in response.content:
        if isinstance(block, TextBlock):
            content.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolUseBlock):
            content.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return {"role": "assistant", "content": content}


def extract_tool_uses(response: StreamedResponse) -> list[ToolUseBlock]:
    """从响应中提取所有 tool_use 块。"""
    return [b for b in response.content if isinstance(b, ToolUseBlock)]


def build_tool_result_message(
    tool_use: ToolUseBlock,
    result: str,
    is_error: bool = False,
) -> dict:
    """
    构建单个工具结果的 API 格式。

    返回格式（符合 Anthropic tool_result 规范）：
      {
        "type": "tool_result",
        "tool_use_id": "toolu_xxx",
        "content": "...",
        "is_error": False,
      }
    """
    return {
        "type": "tool_result",
        "tool_use_id": tool_use.id,
        "content": result,
        "is_error": is_error,
    }
