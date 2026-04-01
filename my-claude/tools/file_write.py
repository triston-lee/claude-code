import os


def _run(input: dict) -> str:
    path = input["path"]
    content = input["content"]
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written to {path}"
    except Exception as e:
        return f"[error] {e}"


FileWriteTool = {
    "name": "file_write",
    "description": "Write content to a file, creating it if it doesn't exist.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write",
            },
            "content": {
                "type": "string",
                "description": "Content to write into the file",
            },
        },
        "required": ["path", "content"],
    },
    "fn": _run,
}
