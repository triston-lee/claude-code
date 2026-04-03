"""
/resume 命令（对应原版 src/commands/resume/）

用法:
  /resume           列出最近 10 条会话
  /resume <id>      按 session_id 恢复
  /resume <keyword> 按关键词搜索并恢复
"""

from services.session import list_sessions, load_session


def _fn(args: str, state: dict) -> str:
    if not args:
        return _list(state)
    return _load(args.strip(), state)


def _list(state: dict) -> str:
    sessions = list_sessions()
    if not sessions:
        return "没有保存的会话。"

    lines = ["\n最近会话（最多显示 10 条）：\n"]
    for s in sessions[:10]:
        saved_at = s["saved_at"][:16].replace("T", " ")
        lines.append(
            f"  {s['session_id']}\n"
            f"    时间: {saved_at}  消息数: {s['message_count']}\n"
            f"    目录: {s['cwd']}\n"
            f"    预览: {s['preview']}\n"
        )
    lines.append("用法: /resume <session_id 或关键词>\n")
    return "\n".join(lines)


def _load(query: str, state: dict) -> str:
    messages = load_session(query)
    if messages is None:
        return f"未找到匹配的会话: {query}"

    state["messages"][:] = messages
    state["input_tokens"] = 0
    state["output_tokens"] = 0
    return f"已恢复会话，共 {len(messages)} 条消息。继续对话吧。"


ResumeCommand = {
    "name": "resume",
    "aliases": ["continue"],
    "description": "恢复之前的对话会话",
    "fn": _fn,
}
