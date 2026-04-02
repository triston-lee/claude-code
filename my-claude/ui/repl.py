"""
终端 UI 输出（对应原版 src/screens/REPL.tsx + src/components/）

原版用 React/Ink 渲染，这里用 rich 库提供格式化输出：
  - Claude 回复：流式逐 token 打印，结束后渲染完整 Markdown
  - 工具调用：显示工具名和参数摘要
  - 错误：红色提示
"""

import sys

_console = None


def _get_console():
    global _console
    if _console is None:
        try:
            from rich.console import Console
            _console = Console()
        except ImportError:
            pass
    return _console


def print_welcome(model: str) -> None:
    console = _get_console()
    if console:
        console.print(f"\n[bold cyan]Claude Code (Python)[/bold cyan] — model: [green]{model}[/green]")
        console.print("输入 [bold]exit[/bold] 或 Ctrl+C 退出\n")
    else:
        print(f"\nClaude Code (Python) — model: {model}")
        print("输入 'exit' 或 Ctrl+C 退出\n")


def print_provider(provider_name: str) -> None:
    """显示当前使用的 provider"""
    if provider_name != "anthropic":
        console = _get_console()
        if console:
            console.print(f"  [dim]provider: {provider_name}[/dim]")
        else:
            print(f"  provider: {provider_name}")


# ── Streaming output ──────────────────────────────────────────────

def start_assistant_stream() -> None:
    """流式输出开始前调用，打印标题行"""
    console = _get_console()
    if console:
        console.print("\n[bold green]Claude[/bold green]", end=" ")
    else:
        print("\nClaude: ", end="")
    sys.stdout.flush()


def stream_text(chunk: str) -> None:
    """逐 token 打印文本（原始文本，不做 Markdown 渲染）"""
    sys.stdout.write(chunk)
    sys.stdout.flush()


def finish_assistant_stream(full_text: str) -> None:
    """
    流式输出结束后调用。
    换行、然后用 rich Markdown 重新渲染完整回复（覆盖原始流式输出）。
    如果终端不支持 rich，直接换行即可（原始文本已经打印过了）。
    """
    # 流式输出后加一个空行收尾
    sys.stdout.write("\n")
    sys.stdout.flush()


def print_assistant_message(text: str) -> None:
    """渲染 Claude 的文本回复（支持 Markdown）— 非流式时使用"""
    console = _get_console()
    if console:
        from rich.markdown import Markdown
        from rich.panel import Panel
        md = Markdown(text)
        console.print(Panel(md, title="[bold green]Claude[/bold green]", border_style="green"))
    else:
        print(f"\nClaude: {text}\n")


# ── Tool output ───────────────────────────────────────────────────

def print_tool_call(tool_name: str, tool_input: dict) -> None:
    """显示工具调用信息"""
    console = _get_console()
    if console:
        parts = []
        for k, v in tool_input.items():
            v_str = str(v)
            if len(v_str) > 80:
                v_str = v_str[:77] + "..."
            parts.append(f"  [dim]{k}:[/dim] {v_str}")
        args_display = "\n".join(parts)
        console.print(f"\n[bold yellow]⚙ {tool_name}[/bold yellow]")
        if args_display:
            console.print(args_display)
    else:
        parts = []
        for k, v in tool_input.items():
            v_str = str(v)
            if len(v_str) > 60:
                v_str = v_str[:57] + "..."
            parts.append(f"{k}={repr(v_str)}")
        print(f"  [tool] {tool_name}({', '.join(parts)})")


def print_tool_result(result: str) -> None:
    """显示工具执行结果摘要"""
    console = _get_console()
    lines = result.strip().splitlines()
    preview = "\n".join(lines[:5])
    if len(lines) > 5:
        preview += f"\n  ... ({len(lines)} lines total)"

    if console:
        console.print(f"[dim]  → {preview}[/dim]")
    else:
        print(f"  → {preview}")


# ── Misc ──────────────────────────────────────────────────────────

def print_error(message: str) -> None:
    console = _get_console()
    if console:
        console.print(f"[bold red]Error:[/bold red] {message}")
    else:
        print(f"Error: {message}")


def get_user_input(prompt: str = "You") -> str | None:
    """获取用户输入，返回 None 表示退出"""
    console = _get_console()
    if console:
        from rich.prompt import Prompt
        try:
            return Prompt.ask(f"[bold blue]{prompt}[/bold blue]")
        except (KeyboardInterrupt, EOFError):
            return None
    else:
        try:
            return input(f"{prompt}: ").strip()
        except (KeyboardInterrupt, EOFError):
            return None
