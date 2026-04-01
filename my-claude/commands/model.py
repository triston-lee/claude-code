AVAILABLE_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]


def _fn(args: str, state: dict) -> str:
    import config
    if not args:
        lines = [f"\n当前模型: {config.DEFAULT_MODEL}\n\n可用模型："]
        for m in AVAILABLE_MODELS:
            marker = " ◀ 当前" if m == config.DEFAULT_MODEL else ""
            lines.append(f"  {m}{marker}")
        return "\n".join(lines) + "\n\n用法: /model <model-name>\n"

    model = args.strip()
    if model not in AVAILABLE_MODELS:
        return f"未知模型: {model}\n可用模型: {', '.join(AVAILABLE_MODELS)}"

    config.DEFAULT_MODEL = model
    return f"模型已切换为: {model}"


ModelCommand = {
    "name": "model",
    "aliases": [],
    "description": "查看或切换 Claude 模型",
    "fn": _fn,
}
