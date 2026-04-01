import os


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-6")
MAX_TOKENS = 8096
