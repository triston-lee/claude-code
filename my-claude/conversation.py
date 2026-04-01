"""
对话循环（对应原版 src/query.ts）

核心流程：
  用户输入
    → 发送给 Claude（携带工具定义 + 系统上下文）
    → Claude 返回文本 或 tool_use 块
    → 如果是 tool_use：权限检查 → 执行工具 → 把结果作为 tool_result 发回给 Claude
    → 重复直到 Claude 返回纯文本（stop_reason == "end_turn"）
"""

import anthropic

import config
import permissions
from context import build_system_prompt
from tools import TOOL_REGISTRY, get_api_tools
from ui import repl
from ui.diff_view import print_diff


def run_conversation():
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = []

    repl.print_welcome(config.DEFAULT_MODEL)

    # 对话开始时构建一次系统上下文（CLAUDE.md + git status）
    system_prompt = build_system_prompt()

    while True:
        user_input = repl.get_user_input()

        if user_input is None:
            print("\nBye.")
            break
        if user_input.lower() in ("exit", "quit"):
            print("Bye.")
            break
        if not user_input:
            continue

        # 处理斜杠命令（阶段三会独立为 commands/ 模块）
        if user_input.startswith("/"):
            _handle_slash_command(user_input)
            continue

        messages.append({"role": "user", "content": user_input})

        # 工具调用循环：一次对话可能包含多轮 tool_use → tool_result
        while True:
            try:
                response = client.messages.create(
                    model=config.DEFAULT_MODEL,
                    max_tokens=config.MAX_TOKENS,
                    system=system_prompt,
                    tools=get_api_tools(),
                    messages=messages,
                )
            except anthropic.APIStatusError as e:
                repl.print_error(str(e))
                break
            except anthropic.APIConnectionError as e:
                repl.print_error(f"Connection error: {e}")
                break

            messages.append({"role": "assistant", "content": response.content})

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            if not tool_use_blocks:
                for block in response.content:
                    if block.type == "text" and block.text:
                        repl.print_assistant_message(block.text)
                break

            tool_results = []
            for tool_use in tool_use_blocks:
                tool_name = tool_use.name
                tool_input = tool_use.input

                repl.print_tool_call(tool_name, tool_input)

                if not permissions.check_permission(tool_name, tool_input):
                    result = "[permission denied by user]"
                    repl.print_tool_result(result)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result,
                    })
                    continue

                fn = TOOL_REGISTRY.get(tool_name)
                if fn is None:
                    result = f"[error] Unknown tool: {tool_name}"
                else:
                    if tool_name == "file_edit":
                        result = _run_file_edit_with_diff(fn, tool_input)
                    else:
                        result = fn(tool_input)

                repl.print_tool_result(result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})


def _run_file_edit_with_diff(fn, tool_input: dict) -> str:
    """执行 file_edit 并在执行后展示 diff"""
    import os
    path = tool_input.get("path", "")
    old_string = tool_input.get("old_string", "")
    new_string = tool_input.get("new_string", "")

    old_content = None
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                old_content = f.read()
        except Exception:
            pass

    result = fn(tool_input)

    if old_content is not None and not result.startswith("[error]"):
        new_content = old_content.replace(old_string, new_string, 1)
        print_diff(old_content, new_content, path)

    return result


def _handle_slash_command(command: str) -> None:
    """简易斜杠命令处理（阶段三会扩展为完整的 commands/ 模块）"""
    cmd = command.strip().lower()
    if cmd in ("/help", "/?"):
        print("\n可用命令：")
        print("  /help        显示此帮助")
        print("  /mode        查看当前权限模式")
        print("  /mode plan   切换到 plan 模式（所有工具都询问）")
        print("  /mode bypass 切换到 bypass 模式（跳过所有询问）")
        print("  /mode default 切换到默认模式")
        print("  exit / quit  退出\n")
    elif cmd == "/mode":
        print(f"当前权限模式：{permissions.get_mode()}")
    elif cmd.startswith("/mode "):
        mode = cmd.split(" ", 1)[1].strip()
        try:
            permissions.set_mode(mode)
            print(f"权限模式已切换为：{mode}")
        except ValueError as e:
            repl.print_error(str(e))
    else:
        repl.print_error(f"未知命令：{command}。输入 /help 查看可用命令。")
