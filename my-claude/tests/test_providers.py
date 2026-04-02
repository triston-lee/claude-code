"""
Provider 抽象层测试
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from providers.base import ContentBlock, StreamEvent, StreamResult, Usage, Provider
from providers.registry import detect_provider_name, list_providers


class TestContentBlock(unittest.TestCase):
    def test_text_block(self):
        b = ContentBlock(type="text", text="hello")
        self.assertEqual(b.type, "text")
        self.assertEqual(b.text, "hello")

    def test_tool_use_block(self):
        b = ContentBlock(type="tool_use", id="123", name="bash", input={"command": "ls"})
        self.assertEqual(b.type, "tool_use")
        self.assertEqual(b.name, "bash")
        self.assertEqual(b.input, {"command": "ls"})


class TestStreamResult(unittest.TestCase):
    def test_defaults(self):
        r = StreamResult()
        self.assertEqual(r.content, [])
        self.assertEqual(r.usage.input_tokens, 0)
        self.assertEqual(r.stop_reason, "")

    def test_with_content(self):
        blocks = [ContentBlock(type="text", text="hi")]
        r = StreamResult(
            content=blocks,
            usage=Usage(input_tokens=100, output_tokens=50),
            stop_reason="end_turn",
        )
        self.assertEqual(len(r.content), 1)
        self.assertEqual(r.usage.input_tokens, 100)
        self.assertEqual(r.stop_reason, "end_turn")


class TestStreamEvent(unittest.TestCase):
    def test_text_delta(self):
        e = StreamEvent(type="text_delta", text="hello")
        self.assertEqual(e.type, "text_delta")
        self.assertEqual(e.text, "hello")

    def test_tool_use_start(self):
        e = StreamEvent(type="tool_use_start", tool_name="bash", tool_id="abc")
        self.assertEqual(e.tool_name, "bash")


class TestRegistry(unittest.TestCase):
    def test_list_providers(self):
        providers = list_providers()
        self.assertIn("anthropic", providers)
        self.assertIn("bedrock", providers)
        self.assertIn("vertex", providers)

    def test_detect_default_anthropic(self):
        # 清除可能影响检测的环境变量
        env_backup = {}
        for key in ["CLAUDE_PROVIDER", "ANTHROPIC_BEDROCK", "AWS_PROFILE", "ANTHROPIC_VERTEX"]:
            if key in os.environ:
                env_backup[key] = os.environ.pop(key)
        try:
            name = detect_provider_name()
            self.assertEqual(name, "anthropic")
        finally:
            os.environ.update(env_backup)

    def test_detect_explicit_provider(self):
        old = os.environ.get("CLAUDE_PROVIDER")
        try:
            os.environ["CLAUDE_PROVIDER"] = "bedrock"
            self.assertEqual(detect_provider_name(), "bedrock")
            os.environ["CLAUDE_PROVIDER"] = "vertex"
            self.assertEqual(detect_provider_name(), "vertex")
        finally:
            if old is None:
                os.environ.pop("CLAUDE_PROVIDER", None)
            else:
                os.environ["CLAUDE_PROVIDER"] = old


class TestProviderABC(unittest.TestCase):
    def test_cannot_instantiate_abstract(self):
        with self.assertRaises(TypeError):
            Provider()


if __name__ == "__main__":
    unittest.main()
