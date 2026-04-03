def _fn(args: str, state: dict) -> str:
    state["messages"].clear()
    state["input_tokens"] = 0
    state["output_tokens"] = 0
    return "对话已清空。"


ClearCommand = {
    "name": "clear",
    "aliases": [],
    "description": "清空当前对话历史",
    "fn": _fn,
}
