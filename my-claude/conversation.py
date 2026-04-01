"""
对话循环（对应原版 src/query.ts + src/QueryEngine.ts）

核心流程：
  用户输入
    → 斜杠命令？→ 分发给 commands/
    → 发送给 Claude（携带工具定义 + 系统上下文）
    → Claude 返回文本 或 tool_use 块
    → 如果是 tool_use：权限检查 → 执行工具 → 返回 tool_result → 继续循环
    → 更新 token 用量，检查是否需要自动压缩
    → 自动保存会话
"""

import anthropic

import config
import permissions
from commands import dispatch as dispatch_command
from context import build_system_prompt
from services.compact import should_compact, compact_messages
from services.session import save_session, new_session_id
from tools import TOOL_REGISTRY, get_api_tools
from ui import repl
from ui.diff_view import print_diff


def run_conversation():
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    state = {
        "messages": [],
        "client": client,
        "input_tokens": 0,
        "output_tokens": 0,
        "session_id": new_session_id(),
    }
    messages = state["messages"]

    repl.print_welcome(config.DEFAULT_MODEL)

    system_prompt = build_system_prompt()

    while True:
        user_input = repl.get_user_input()

        if user_input is None:
            _autosave(state)
            print("\nBye.")
            break
        if user_input.lower() in ("exit", "quit"):
            _autosave(state)
            print("Bye.")
            break
        if not user_input:
            continue

        if user_input.startswith("/"):
            handled = dispatch_command(user_input, state)
            if not handled:
                repl.print_error(f"未知命令: {user_input}。输入 /help 查看可用命令。")
            continue

        messages.append({"role": "user", "content": user_input})

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

            state["input_tokens"] += response.usage.input_tokens
            state["output_tokens"] += response.usage.output_tokens

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
                    result = _run_tool(fn, tool_name, tool_input)

                repl.print_tool_result(result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        _check_auto_compact(state, client)
        _autosave(state)


def _run_tool(fn, tool_name: str, tool_input: dict) -> str:
    if tool_name == "file_edit":
        return _run_file_edit_with_diff(fn, tool_input)
    return fn(tool_input)


def _run_file_edit_with_diff(fn, tool_input: dict) -> str:
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


def _check_auto_compact(state: dict, client: anthropic.Anthropic) -> None:
    """
    检查 token 用量，超阈值时自动压缩。
    对应原版 isAutoCompactEnabled() + compactConversation()
    """
    if should_compact(state["input_tokens"], config.DEFAULT_MODEL):
        messages = state["messages"]
        print(f"\n[auto-compact] token 用量达到阈值 ({state['input_tokens']:,})，正在压缩...")
        try:
            new_messages = compact_messages(client, messages)
            state["messages"][:] = new_messages
            state["input_tokens"] = 0
            state["output_tokens"] = 0
            print(f"[auto-compact] 压缩完成，消息从 {len(messages)} 条 → {len(new_messages)} 条")
        except Exception as e:
            print(f"[auto-compact] 压缩失败: {e}")


def _autosave(state: dict) -> None:
    if not state["messages"]:
        return
    try:
        save_session(state["messages"], state["session_id"])
    except Exception:
        pass
