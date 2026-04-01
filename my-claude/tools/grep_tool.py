import os
import re
import glob as glob_module


MAX_RESULTS = 100
MAX_LINE_LEN = 500


def _run(input: dict) -> str:
    pattern = input["pattern"]
    path = input.get("path", os.getcwd())
    file_glob = input.get("include", "*")

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"[error] Invalid regex: {e}"

    if os.path.isfile(path):
        files = [path]
    else:
        full_glob = os.path.join(path, "**", file_glob)
        files = sorted(glob_module.glob(full_glob, recursive=True))
        files = [f for f in files if os.path.isfile(f)]

    results = []
    cwd = os.getcwd()

    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    if regex.search(line):
                        rel = filepath
                        try:
                            rel = os.path.relpath(filepath, cwd)
                        except ValueError:
                            pass
                        line_display = line.rstrip()
                        if len(line_display) > MAX_LINE_LEN:
                            line_display = line_display[:MAX_LINE_LEN] + "..."
                        results.append(f"{rel}:{lineno}:{line_display}")
                        if len(results) >= MAX_RESULTS:
                            break
        except Exception:
            continue
        if len(results) >= MAX_RESULTS:
            break

    if not results:
        return "No matches found"

    output = "\n".join(results)
    if len(results) >= MAX_RESULTS:
        output += f"\n(Results truncated at {MAX_RESULTS} matches)"
    return output


GrepTool = {
    "name": "grep",
    "description": (
        "Search for a regex pattern in file contents. "
        "Returns matching lines with file path and line number. "
        "Use the 'include' parameter to filter by file type (e.g. '*.py')."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The regex pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search. Defaults to current working directory.",
            },
            "include": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g. '*.py'). Defaults to all files.",
            },
        },
        "required": ["pattern"],
    },
    "fn": _run,
}
