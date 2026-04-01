def _fn(args: str, state: dict) -> str:
    from commands import get_all_commands
    lines = ["\n可用斜杠命令：\n"]
    for cmd in get_all_commands():
        aliases = ", ".join(f"/{a}" for a in cmd.get("aliases", []))
        alias_str = f"  (别名: {aliases})" if aliases else ""
        lines.append(f"  /{cmd['name']:<12} {cmd['description']}{alias_str}")
    lines.append("\n  exit / quit   退出程序\n")
    return "\n".join(lines)


HelpCommand = {
    "name": "help",
    "aliases": ["?"],
    "description": "显示可用命令列表",
    "fn": _fn,
}
