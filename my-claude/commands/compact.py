"""
/compact 命令（对应原版 src/commands/compact/）
"""


def _fn(args: str, state: dict) -> str:
    from services.compact import compact_messages

    messages = state.get("messages", [])
    if len(messages) < 2:
        return "消息太少，无需压缩。"

    print("正在压缩对话历史...")
    try:
        new_messages = compact_messages(state["client"], messages)
        state["messages"][:] = new_messages
        state["input_tokens"] = 0
        state["output_tokens"] = 0
        return f"压缩完成。历史消息从 {len(messages)} 条压缩为 {len(new_messages)} 条。"
    except Exception as e:
        return f"压缩失败: {e}"


CompactCommand = {
    "name": "compact",
    "aliases": [],
    "description": "将当前对话历史压缩成摘要（释放 context window）",
    "fn": _fn,
}
