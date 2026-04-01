#!/usr/bin/env python3
import argparse
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
    parser.add_argument("--version", action="version", version="my-claude 0.2.0")
    args = parser.parse_args()

    if not config.ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    config.DEFAULT_MODEL = args.model
    permissions.set_mode(args.mode)
    run_conversation()


if __name__ == "__main__":
    main()
