def _run(input: dict) -> str:
    path = input["path"]
    old_string = input["old_string"]
    new_string = input["new_string"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            return f"[error] old_string not found in {path}"
        if count > 1:
            return f"[error] old_string is ambiguous — found {count} matches in {path}. Provide more context."

        new_content = content.replace(old_string, new_string, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"Edited {path}"
    except FileNotFoundError:
        return f"[error] File not found: {path}"
    except Exception as e:
        return f"[error] {e}"


FileEditTool = {
    "name": "file_edit",
    "description": (
        "Edit a file by replacing an exact string with a new string. "
        "old_string must match exactly once in the file."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit",
            },
            "old_string": {
                "type": "string",
                "description": "The exact string to replace",
            },
            "new_string": {
                "type": "string",
                "description": "The string to replace it with",
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
    "fn": _run,
}
