"""
文件编辑 diff 展示（对应原版 src/components/ 中的文件 diff 渲染）
"""

import difflib


def make_diff(old_content: str, new_content: str, filepath: str) -> str:
    """生成统一格式的 diff 字符串"""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
        lineterm="",
    )
    return "".join(diff)


def print_diff(old_content: str, new_content: str, filepath: str) -> None:
    """打印带颜色的 diff（使用 rich 如果可用，否则纯文本）"""
    diff = make_diff(old_content, new_content, filepath)
    if not diff:
        print("(no changes)")
        return

    try:
        from rich.syntax import Syntax
        from rich.console import Console
        console = Console()
        syntax = Syntax(diff, "diff", theme="monokai", line_numbers=False)
        console.print(syntax)
    except ImportError:
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("++"):
                print(f"\033[32m{line}\033[0m")
            elif line.startswith("-") and not line.startswith("--"):
                print(f"\033[31m{line}\033[0m")
            elif line.startswith("@@"):
                print(f"\033[36m{line}\033[0m")
            else:
                print(line)
