"""
对话循环（对应原版 src/query.ts）

核心流程：
  用户输入
    → 发送给 Claude（携带工具定义）
    → Claude 返回文本 或 tool_use 块
    → 如果是 tool_use：执行工具 → 把结果作为 tool_result 发回给 Claude
    → 重复直到 Claude 返回纯文本（stop_reason == "end_turn"）
"""

import anthropic

import config
from tools import TOOL_REGISTRY, get_api_tools


def run_conversation():
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = []

    print(f"Claude Code (Python) — model: {config.DEFAULT_MODEL}")
    print("输入 'exit' 或 Ctrl+C 退出\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break

        if user_input.lower() in ("exit", "quit"):
            print("Bye.")
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # 工具调用循环：一次对话可能包含多轮 tool_use → tool_result
        while True:
            response = client.messages.create(
                model=config.DEFAULT_MODEL,
                max_tokens=config.MAX_TOKENS,
                tools=get_api_tools(),
                messages=messages,
            )

            # 把 Claude 的回复加入消息历史
            messages.append({"role": "assistant", "content": response.content})

            # 检查是否有 tool_use 块
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            if not tool_use_blocks:
                # 没有工具调用，直接输出文本并结束本轮
                for block in response.content:
                    if block.type == "text":
                        print(f"\nClaude: {block.text}\n")
                break

            # 执行所有工具，收集结果
            tool_results = []
            for tool_use in tool_use_blocks:
                tool_name = tool_use.name
                tool_input = tool_use.input

                print(f"  [tool] {tool_name}({_fmt_input(tool_input)})")

                fn = TOOL_REGISTRY.get(tool_name)
                if fn is None:
                    result = f"[error] Unknown tool: {tool_name}"
                else:
                    result = fn(tool_input)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })

            # 把工具结果作为 user 消息发回给 Claude，继续循环
            messages.append({"role": "user", "content": tool_results})


def _fmt_input(input: dict) -> str:
    """把工具参数格式化成单行摘要，方便打印。"""
    parts = []
    for k, v in input.items():
        v_str = str(v)
        if len(v_str) > 60:
            v_str = v_str[:57] + "..."
        parts.append(f"{k}={repr(v_str)}")
    return ", ".join(parts)
