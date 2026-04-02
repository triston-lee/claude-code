import os


ANTHROPIC_API_KEY = os.environ.get(
    "ANTHROPIC_API_KEY",
    "8T9e3yaX270e3XeM0z3tPXk1btIzwT0XaIiY20HDMYHO4zwR",
)
ANTHROPIC_BASE_URL = os.environ.get(
    "ANTHROPIC_BASE_URL",
    "https://api.aipaibox.com",
)
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-6")
MAX_TOKENS = 8096
