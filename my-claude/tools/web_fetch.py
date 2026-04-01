import urllib.request
import urllib.error

MAX_CHARS = 20_000


def _run(input: dict) -> str:
    url = input["url"]
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "my-claude/0.1 (learning project)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()

            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            try:
                text = raw.decode(charset)
            except (UnicodeDecodeError, LookupError):
                text = raw.decode("utf-8", errors="replace")

            if len(text) > MAX_CHARS:
                text = text[:MAX_CHARS] + f"\n\n...(truncated at {MAX_CHARS} chars)"
            return text
    except urllib.error.HTTPError as e:
        return f"[error] HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"[error] URL error: {e.reason}"
    except Exception as e:
        return f"[error] {e}"


WebFetchTool = {
    "name": "web_fetch",
    "description": "Fetch the content of a URL and return it as text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
        },
        "required": ["url"],
    },
    "fn": _run,
}
