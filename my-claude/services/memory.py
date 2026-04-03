"""
用户级别的记忆管理（对应原版 src/utils/memory/ + src/commands/memory/）

原版支持两层记忆：
  1. 项目级：./CLAUDE.md（已在 context.py 中处理）
  2. 用户级：~/.claude/CLAUDE.md（跨项目的个人偏好和常用指令）

这里管理用户级别的 ~/.claude/CLAUDE.md。
"""

import os

MEMORY_FILE = os.path.expanduser("~/.claude/CLAUDE.md")


def read_memory() -> str | None:
    if not os.path.isfile(MEMORY_FILE):
        return None
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def write_memory(content: str) -> None:
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def append_memory(content: str) -> None:
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        if not content.startswith("\n"):
            f.write("\n")
        f.write(content)
        if not content.endswith("\n"):
            f.write("\n")


def get_memory_path() -> str:
    return MEMORY_FILE
