"""
对话循环（对应原版 src/query.ts + src/QueryEngine.ts）

核心流程：
  用户输入
    → 斜杠命令？→ 分发给 commands/
    → 通过 provider 发送给 Claude（携带工具定义 + 系统上下文）
    → 流式输出文本 + 累积 tool_use 块
    → 如果有 tool_use：权限检查 → 执行工具 → 返回 tool_result → 继续循环
    → 更新 token 用量，检查是否需要自动压缩
    → 自动保存会话
"""

import config
import permissions
from commands import dispatch as dispatch_command
from context import build_system_prompt
from providers import get_provider
from providers.base import ContentBlock, StreamResult
from services.compact import should_compact, compact_messages_via_provider
from services.session import save_session, new_session_id
from tools import TOOL_REGISTRY, get_api_tools
from ui import repl
from ui.diff_view import print_diff


def run_conversation():
    provider = get_provider()

    state = {
        "messages": [],
        "provider": provider,
        "input_tokens": 0,
        "output_tokens": 0,
        "session_id": new_session_id(),
    }
    messages = state["messages"]

    repl.print_welcome(config.DEFAULT_MODEL)
    repl.print_provider(provider.name)

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
                result = _stream_response(provider, system_prompt, messages, state)
            except Exception as e:
                repl.print_error(str(e))
                break

            # 把 ContentBlock dataclass 转回 messages 需要的格式
            messages.append({
                "role": "assistant",
                "content": _blocks_to_api_format(result.content),
            })

            tool_use_blocks = [b for b in result.content if b.type == "tool_use"]

            if not tool_use_blocks:
                break

            tool_results = []
            for tool_use in tool_use_blocks:
                tool_name = tool_use.name
                tool_input = tool_use.input

                repl.print_tool_call(tool_name, tool_input)

                if not permissions.check_permission(tool_name, tool_input):
                    result_str = "[permission denied by user]"
                    repl.print_tool_result(result_str)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result_str,
                    })
                    continue

                fn = TOOL_REGISTRY.get(tool_name)
                if fn is None:
                    result_str = f"[error] Unknown tool: {tool_name}"
                else:
                    result_str = _run_tool(fn, tool_name, tool_input)

                repl.print_tool_result(result_str)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_str,
                })

            messages.append({"role": "user", "content": tool_results})

        _check_auto_compact(state)
        _autosave(state)


def _blocks_to_api_format(blocks: list[ContentBlock]) -> list[dict]:
    """把统一 ContentBlock 转回 API messages 格式"""
    result = []
    for b in blocks:
        if b.type == "text":
            result.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            result.append({
                "type": "tool_use",
                "id": b.id,
                "name": b.name,
                "input": b.input,
            })
    return result


def _stream_response(
    provider,
    system_prompt: str,
    messages: list,
    state: dict,
) -> StreamResult:
    """
    使用 provider 的流式 API 调用 Claude，逐 token 打印文本。
    返回统一的 StreamResult。
    """
    collected_text = ""
    has_text = False

    gen = provider.stream(
        model=config.DEFAULT_MODEL,
        max_tokens=config.MAX_TOKENS,
        system=system_prompt,
        tools=get_api_tools(),
        messages=messages,
    )

    try:
        while True:
            event = next(gen)
            if event.type == "text_delta" and event.text:
                if not has_text:
                    repl.start_assistant_stream()
                    has_text = True
                repl.stream_text(event.text)
                collected_text += event.text
    except StopIteration as e:
        result = e.value

    if has_text:
        repl.finish_assistant_stream(collected_text)

    state["input_tokens"] += result.usage.input_tokens
    state["output_tokens"] += result.usage.output_tokens

    return result


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


def _check_auto_compact(state: dict) -> None:
    if should_compact(state["input_tokens"], config.DEFAULT_MODEL):
        messages = state["messages"]
        provider = state["provider"]
        print(f"\n[auto-compact] token 用量达到阈值 ({state['input_tokens']:,})，正在压缩...")
        try:
            new_messages = compact_messages_via_provider(provider, messages)
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
