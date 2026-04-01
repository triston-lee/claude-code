"""
/memory 命令（对应原版 src/commands/memory/）

用法:
  /memory           显示当前记忆内容
  /memory add <内容> 追加内容到记忆
  /memory edit      打开记忆文件路径提示
"""

from services.memory import read_memory, append_memory, get_memory_path


def _fn(args: str, state: dict) -> str:
    if not args:
        return _show()

    parts = args.split(None, 1)
    sub = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if sub == "add":
        if not rest:
            return "用法: /memory add <要记住的内容>"
        append_memory(rest)
        return f"已添加到记忆: {rest}"
    elif sub == "edit":
        return f"记忆文件路径: {get_memory_path()}\n用编辑器直接修改该文件即可。"
    else:
        append_memory(args)
        return f"已添加到记忆: {args}"


def _show() -> str:
    content = read_memory()
    if not content:
        return f"记忆文件为空或不存在。\n路径: {get_memory_path()}"
    return f"当前记忆内容 ({get_memory_path()}):\n\n{content}"


MemoryCommand = {
    "name": "memory",
    "aliases": ["mem"],
    "description": "查看或更新用户级记忆（~/.claude/CLAUDE.md）",
    "fn": _fn,
}
