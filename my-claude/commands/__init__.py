"""
斜杠命令注册表（对应原版 src/commands/）

每个命令是一个 dict：
  name        命令名（不含 /）
  aliases     别名列表
  description 简短描述
  fn          handler(args: str, state: dict) -> str | None

state 是对话状态 dict，包含：
  messages        当前消息列表
  client          anthropic.Anthropic 实例
  input_tokens    累计输入 token
  output_tokens   累计输出 token
  session_id      当前会话 ID
"""

from commands.help import HelpCommand
from commands.clear import ClearCommand
from commands.cost import CostCommand
from commands.model import ModelCommand
from commands.compact import CompactCommand
from commands.resume import ResumeCommand
from commands.memory import MemoryCommand

ALL_COMMANDS = [
    HelpCommand,
    ClearCommand,
    CostCommand,
    ModelCommand,
    CompactCommand,
    ResumeCommand,
    MemoryCommand,
]

_REGISTRY: dict = {}
for cmd in ALL_COMMANDS:
    _REGISTRY[cmd["name"]] = cmd
    for alias in cmd.get("aliases", []):
        _REGISTRY[alias] = cmd


def dispatch(raw_input: str, state: dict) -> bool:
    """
    解析并分发斜杠命令。
    返回 True 表示已处理，False 表示未识别。
    """
    stripped = raw_input.lstrip("/").strip()
    parts = stripped.split(None, 1)
    name = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""

    cmd = _REGISTRY.get(name)
    if cmd is None:
        return False

    result = cmd["fn"](args, state)
    if result:
        print(result)
    return True


def get_all_commands() -> list[dict]:
    return ALL_COMMANDS
