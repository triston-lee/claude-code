"""
会话保存/恢复（对应原版 src/commands/resume/）

会话以 JSON 保存在 ~/.claude/sessions/<session_id>.json，
包含完整的 messages 列表，支持按 ID 或关键词恢复。
"""

import json
import os
import uuid
from datetime import datetime


SESSIONS_DIR = os.path.expanduser("~/.claude/sessions")


def _ensure_dir():
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def save_session(messages: list, session_id: str, cwd: str | None = None) -> str:
    """保存对话到文件，返回 session_id"""
    _ensure_dir()
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")

    serialized = _serialize_messages(messages)

    data = {
        "session_id": session_id,
        "saved_at": datetime.now().isoformat(),
        "cwd": cwd or os.getcwd(),
        "message_count": len(messages),
        "preview": _get_preview(messages),
        "messages": serialized,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return session_id


def list_sessions() -> list[dict]:
    """列出所有保存的会话，按时间倒序"""
    _ensure_dir()
    sessions = []
    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(SESSIONS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions.append({
                "session_id": data.get("session_id", fname[:-5]),
                "saved_at": data.get("saved_at", ""),
                "cwd": data.get("cwd", ""),
                "preview": data.get("preview", ""),
                "message_count": data.get("message_count", 0),
            })
        except Exception:
            continue
    sessions.sort(key=lambda x: x["saved_at"], reverse=True)
    return sessions


def load_session(session_id_or_search: str) -> list | None:
    """
    按 session_id 或关键词恢复会话，返回 messages 列表。
    对应原版 /resume 命令的搜索逻辑。
    """
    _ensure_dir()

    exact_path = os.path.join(SESSIONS_DIR, f"{session_id_or_search}.json")
    if os.path.isfile(exact_path):
        return _load_file(exact_path)

    keyword = session_id_or_search.lower()
    sessions = list_sessions()
    for s in sessions:
        if (keyword in s["session_id"].lower() or
                keyword in s["preview"].lower() or
                keyword in s["cwd"].lower()):
            path = os.path.join(SESSIONS_DIR, f"{s['session_id']}.json")
            return _load_file(path)

    return None


def _load_file(path: str) -> list | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("messages", [])
    except Exception:
        return None


def _get_preview(messages: list) -> str:
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()[:80]
    return "(no preview)"


def _serialize_messages(messages: list) -> list:
    """把 SDK ContentBlock 对象转成可 JSON 序列化的 dict"""
    result = []
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, list):
                serialized_content = []
                for block in content:
                    if hasattr(block, "model_dump"):
                        serialized_content.append(block.model_dump())
                    elif hasattr(block, "__dict__"):
                        serialized_content.append(vars(block))
                    else:
                        serialized_content.append(block)
                result.append({**msg, "content": serialized_content})
            else:
                result.append(msg)
        else:
            result.append(msg)
    return result
