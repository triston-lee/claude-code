"""
/cost 命令（对应原版 src/commands/cost/cost.ts）
"""

PRICING = {
    "claude-opus-4-6":    {"input": 15.0,  "output": 75.0},
    "claude-sonnet-4-6":  {"input": 3.0,   "output": 15.0},
    "claude-haiku-4-5":   {"input": 0.8,   "output": 4.0},
}

DEFAULT_PRICING = {"input": 3.0, "output": 15.0}


def _fn(args: str, state: dict) -> str:
    import config
    input_tokens = state.get("input_tokens", 0)
    output_tokens = state.get("output_tokens", 0)

    pricing = PRICING.get(config.DEFAULT_MODEL, DEFAULT_PRICING)
    input_cost = input_tokens / 1_000_000 * pricing["input"]
    output_cost = output_tokens / 1_000_000 * pricing["output"]
    total_cost = input_cost + output_cost

    return (
        f"\n本次会话 Token 用量：\n"
        f"  输入: {input_tokens:,} tokens  (${input_cost:.4f})\n"
        f"  输出: {output_tokens:,} tokens  (${output_cost:.4f})\n"
        f"  合计: ${total_cost:.4f}\n"
        f"  模型: {config.DEFAULT_MODEL}\n"
    )


CostCommand = {
    "name": "cost",
    "aliases": ["usage"],
    "description": "显示当前会话的 token 用量和费用估算",
    "fn": _fn,
}
