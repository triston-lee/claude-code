import glob as glob_module
import os


def _run(input: dict) -> str:
    pattern = input["pattern"]
    search_path = input.get("path", os.getcwd())

    try:
        if not os.path.isabs(pattern):
            full_pattern = os.path.join(search_path, "**", pattern)
        else:
            full_pattern = pattern

        matches = glob_module.glob(full_pattern, recursive=True)

        truncated = len(matches) > 100
        matches = matches[:100]

        cwd = os.getcwd()
        rel_matches = []
        for m in sorted(matches):
            try:
                rel_matches.append(os.path.relpath(m, cwd))
            except ValueError:
                rel_matches.append(m)

        if not rel_matches:
            return "No files found"

        result = "\n".join(rel_matches)
        if truncated:
            result += "\n(Results are truncated. Consider using a more specific path or pattern.)"
        return result
    except Exception as e:
        return f"[error] {e}"


GlobTool = {
    "name": "glob",
    "description": (
        "Fast file pattern matching tool. "
        "Supports glob patterns like '**/*.py' or 'src/**/*.ts'. "
        "Returns matching file paths sorted alphabetically."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The glob pattern to match files against",
            },
            "path": {
                "type": "string",
                "description": "The directory to search in. Defaults to current working directory.",
            },
        },
        "required": ["pattern"],
    },
    "fn": _run,
}
