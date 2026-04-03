"""
上下文构建（对应原版 src/context.ts + src/utils/claudemd.ts）

原版做了两件事：
  1. getGitStatus() - 获取当前分支、git status --short、最近 5 条 commit
  2. getClaudeMds()  - 从当前目录往上找所有 CLAUDE.md，注入到系统提示

这里照样实现，在对话开始时构建一次系统提示。
"""

import os
import subprocess
from datetime import date

MAX_STATUS_CHARS = 2000


def get_git_status() -> str | None:
    """获取 git 状态摘要，对应原版 getGitStatus()"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return None

        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True
        ).stdout.strip()

        default_branch = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True
        ).stdout.strip().replace("refs/remotes/origin/", "") or "main"

        status = subprocess.run(
            ["git", "--no-optional-locks", "status", "--short"],
            capture_output=True, text=True
        ).stdout.strip()

        log = subprocess.run(
            ["git", "--no-optional-locks", "log", "--oneline", "-n", "5"],
            capture_output=True, text=True
        ).stdout.strip()

        username = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True
        ).stdout.strip()

        if len(status) > MAX_STATUS_CHARS:
            status = status[:MAX_STATUS_CHARS] + \
                '\n... (truncated. Run "git status" via bash tool for full output)'

        parts = [
            "This is the git status at the start of the conversation. "
            "Note that this status is a snapshot in time and will not update during the conversation.",
            f"Current branch: {branch}",
            f"Main branch: {default_branch}",
        ]
        if username:
            parts.append(f"Git user: {username}")
        parts.append(f"Status:\n{status or '(clean)'}")
        parts.append(f"Recent commits:\n{log or '(none)'}")

        return "\n\n".join(parts)

    except FileNotFoundError:
        return None
    except Exception:
        return None


def find_claude_mds(start_dir: str | None = None) -> list[tuple[str, str]]:
    """
    从 start_dir 往上查找所有 CLAUDE.md 文件，返回 [(path, content), ...]
    对应原版 getClaudeMds()
    """
    if start_dir is None:
        start_dir = os.getcwd()

    results = []
    current = os.path.abspath(start_dir)

    while True:
        candidate = os.path.join(current, "CLAUDE.md")
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    results.append((candidate, content))
            except Exception:
                pass

        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return results


def build_system_prompt() -> str:
    """
    构建系统提示，在对话开始时调用一次。
    对应原版 getSystemContext() + getUserContext()
    """
    parts = []

    parts.append(
        f"You are Claude Code, an AI assistant for software engineering tasks.\n"
        f"Today's date is {date.today().isoformat()}.\n"
        f"Current working directory: {os.getcwd()}"
    )

    claude_mds = find_claude_mds()
    if claude_mds:
        md_parts = []
        for path, content in claude_mds:
            md_parts.append(f'<claude_md path="{path}">\n{content}\n</claude_md>')
        parts.append("# Project Instructions (from CLAUDE.md files)\n\n" + "\n\n".join(md_parts))

    git_status = get_git_status()
    if git_status:
        parts.append("# Git Status\n\n" + git_status)

    return "\n\n---\n\n".join(parts)
