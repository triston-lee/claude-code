#!/usr/bin/env python3
import argparse
import os
import sys

import config
import permissions
from conversation import run_conversation


def main():
    parser = argparse.ArgumentParser(description="Claude Code (Python)")
    parser.add_argument("--model", default=config.DEFAULT_MODEL, help="Claude model to use")
    parser.add_argument(
        "--mode",
        default="default",
        choices=["default", "plan", "bypass"],
        help="Permission mode: default (ask for bash), plan (ask for all), bypass (ask for none)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "bedrock", "vertex"],
        help="API provider (default: auto-detect from env)",
    )
    parser.add_argument("--version", action="version", version="my-claude 0.3.0")
    args = parser.parse_args()

    if not config.ANTHROPIC_API_KEY and (args.provider is None or args.provider == "anthropic"):
        print("Error: ANTHROPIC_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    config.DEFAULT_MODEL = args.model
    permissions.set_mode(args.mode)

    # 设置 provider 环境变量供 registry 检测
    if args.provider:
        os.environ["CLAUDE_PROVIDER"] = args.provider

    run_conversation()


if __name__ == "__main__":
    main()
