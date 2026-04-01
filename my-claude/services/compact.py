"""
对话压缩（对应原版 src/services/compact/compact.ts + prompt.ts）

原版的压缩流程：
  1. 把当前所有消息序列化成文本
  2. 调用 Claude API，让它生成一份详细的结构化摘要
  3. 剥离 <analysis> 标签（草稿思考），保留 <summary>
  4. 用一条包含摘要的 user 消息替换全部历史消息
  5. 继续对话

触发时机：
  - 手动：用户输入 /compact
  - 自动：response.usage.input_tokens 超过阈值（原版约为上下文窗口的 95%）
"""

import re
import anthropic

import config

COMPACT_SYSTEM_PROMPT = """CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.
Your entire response must be plain text: an <analysis> block followed by a <summary> block.
"""

COMPACT_USER_PROMPT = """Your task is to create a detailed summary of the conversation so far.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions.

Before providing your final summary, wrap your analysis in <analysis> tags.

Your summary should include:
1. Primary Request and Intent: All of the user's explicit requests in detail
2. Key Technical Concepts: Technologies, frameworks, and patterns discussed
3. Files and Code Sections: Files examined/modified/created, with key code snippets
4. Errors and fixes: Errors encountered and how they were fixed
5. Problem Solving: Problems solved and ongoing troubleshooting
6. All user messages: List ALL user messages (not tool results)
7. Pending Tasks: Tasks explicitly asked but not yet completed
8. Current Work: What was being worked on immediately before this summary
9. Optional Next Step: The next step directly in line with the most recent work

Format:
<analysis>
[Your thought process]
</analysis>

<summary>
[Structured summary following the sections above]
</summary>

REMINDER: Do NOT call any tools. Respond with plain text only.
"""

AUTO_COMPACT_THRESHOLD = 0.80

CONTEXT_WINDOWS = {
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5": 200_000,
}

DEFAULT_CONTEXT_WINDOW = 200_000


def should_compact(input_tokens: int, model: str) -> bool:
    window = CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)
    return input_tokens >= window * AUTO_COMPACT_THRESHOLD


def compact_messages(client: anthropic.Anthropic, messages: list) -> list:
    """
    调用 Claude 压缩对话历史，返回新的 messages 列表（只含摘要）。
    对应原版 compactConversation()
    """
    conversation_text = _messages_to_text(messages)

    response = client.messages.create(
        model=config.DEFAULT_MODEL,
        max_tokens=8096,
        system=COMPACT_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"{COMPACT_USER_PROMPT}\n\n<conversation>\n{conversation_text}\n</conversation>",
            }
        ],
    )

    raw_summary = ""
    for block in response.content:
        if block.type == "text":
            raw_summary = block.text
            break

    formatted = _format_summary(raw_summary)

    summary_message = (
        "This session is being continued from a previous conversation that ran out of context. "
        "The summary below covers the earlier portion of the conversation.\n\n"
        + formatted
    )

    return [{"role": "user", "content": summary_message}]


def _format_summary(raw: str) -> str:
    """
    剥离 <analysis> 标签，提取 <summary> 内容。
    对应原版 formatCompactSummary()
    """
    text = re.sub(r"<analysis>[\s\S]*?</analysis>", "", raw)

    match = re.search(r"<summary>([\s\S]*?)</summary>", text)
    if match:
        content = match.group(1).strip()
        text = re.sub(r"<summary>[\s\S]*?</summary>", f"Summary:\n{content}", text)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _messages_to_text(messages: list) -> str:
    lines = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")

        if isinstance(content, str):
            lines.append(f"[{role}]: {content}")
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append(block.get("text", ""))
                    elif btype == "tool_use":
                        parts.append(f"<tool_use name={block.get('name')}>{block.get('input')}</tool_use>")
                    elif btype == "tool_result":
                        result_content = block.get("content", "")
                        parts.append(f"<tool_result>{str(result_content)[:500]}</tool_result>")
                elif hasattr(block, "type"):
                    if block.type == "text":
                        parts.append(block.text)
                    elif block.type == "tool_use":
                        parts.append(f"<tool_use name={block.name}>{block.input}</tool_use>")
            lines.append(f"[{role}]: " + "\n".join(parts))

    return "\n\n".join(lines)
