"""
终端 UI 输出（对应原版 src/screens/REPL.tsx + src/components/）

原版用 React/Ink 渲染，这里用 rich 库提供格式化输出：
  - Claude 回复：渲染 Markdown
  - 工具调用：显示工具名和参数摘要
  - 错误：红色提示
"""


def _get_console():
    try:
        from rich.console import Console
        return Console()
    except ImportError:
        return None


def print_welcome(model: str) -> None:
    console = _get_console()
    if console:
        console.print(f"\n[bold cyan]Claude Code (Python)[/bold cyan] — model: [green]{model}[/green]")
        console.print("输入 [bold]exit[/bold] 或 Ctrl+C 退出\n")
    else:
        print(f"\nClaude Code (Python) — model: {model}")
        print("输入 'exit' 或 Ctrl+C 退出\n")


def print_assistant_message(text: str) -> None:
    """渲染 Claude 的文本回复（支持 Markdown）"""
    console = _get_console()
    if console:
        from rich.markdown import Markdown
        from rich.panel import Panel
        md = Markdown(text)
        console.print(Panel(md, title="[bold green]Claude[/bold green]", border_style="green"))
    else:
        print(f"\nClaude: {text}\n")


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
