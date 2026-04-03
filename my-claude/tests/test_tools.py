"""
工具测试（file_read, file_write, file_edit, glob, grep, bash）
"""

import os
import sys
import tempfile
import unittest

# 添加 my-claude 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.file_read import FileReadTool
from tools.file_write import FileWriteTool
from tools.file_edit import FileEditTool
from tools.glob_tool import GlobTool
from tools.grep_tool import GrepTool
from tools.bash import BashTool


class TestFileReadTool(unittest.TestCase):
    def test_read_existing_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path = f.name
        try:
            result = FileReadTool["fn"]({"path": path})
            self.assertEqual(result, "hello world")
        finally:
            os.unlink(path)

    def test_read_nonexistent_file(self):
        result = FileReadTool["fn"]({"path": "/tmp/nonexistent_file_xyz.txt"})
        self.assertIn("[error]", result)
        self.assertIn("not found", result.lower())


class TestFileWriteTool(unittest.TestCase):
    def test_write_new_file(self):
        path = os.path.join(tempfile.gettempdir(), "test_write_tool.txt")
        try:
            result = FileWriteTool["fn"]({"path": path, "content": "new content"})
            self.assertNotIn("[error]", result)
            with open(path) as f:
                self.assertEqual(f.read(), "new content")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_overwrite_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("old content")
            path = f.name
        try:
            result = FileWriteTool["fn"]({"path": path, "content": "replaced"})
            self.assertNotIn("[error]", result)
            with open(path) as f:
                self.assertEqual(f.read(), "replaced")
        finally:
            os.unlink(path)


class TestFileEditTool(unittest.TestCase):
    def test_edit_replaces_string(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path = f.name
        try:
            result = FileEditTool["fn"]({
                "path": path,
                "old_string": "world",
                "new_string": "Python",
            })
            self.assertNotIn("[error]", result)
            with open(path) as f:
                self.assertEqual(f.read(), "hello Python")
        finally:
            os.unlink(path)

    def test_edit_not_found(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path = f.name
        try:
            result = FileEditTool["fn"]({
                "path": path,
                "old_string": "xyz",
                "new_string": "abc",
            })
            self.assertIn("[error]", result)
            self.assertIn("not found", result.lower())
        finally:
            os.unlink(path)

    def test_edit_ambiguous(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("aaa bbb aaa")
            path = f.name
        try:
            result = FileEditTool["fn"]({
                "path": path,
                "old_string": "aaa",
                "new_string": "ccc",
            })
            self.assertIn("[error]", result)
            self.assertIn("ambiguous", result.lower())
        finally:
            os.unlink(path)


class TestGlobTool(unittest.TestCase):
    def test_glob_finds_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试文件
            open(os.path.join(tmpdir, "a.py"), "w").close()
            open(os.path.join(tmpdir, "b.py"), "w").close()
            open(os.path.join(tmpdir, "c.txt"), "w").close()

            result = GlobTool["fn"]({"pattern": "*.py", "path": tmpdir})
            self.assertIn("a.py", result)
            self.assertIn("b.py", result)
            self.assertNotIn("c.txt", result)

    def test_glob_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = GlobTool["fn"]({"pattern": "*.xyz", "path": tmpdir})
            self.assertIn("No files found", result)


class TestGrepTool(unittest.TestCase):
    def test_grep_finds_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.py")
            with open(filepath, "w") as f:
                f.write("def hello():\n    pass\ndef world():\n    pass\n")

            result = GrepTool["fn"]({"pattern": "def hello", "path": tmpdir})
            self.assertIn("def hello", result)
            self.assertIn(":1:", result)

    def test_grep_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.py")
            with open(filepath, "w") as f:
                f.write("nothing here\n")

            result = GrepTool["fn"]({"pattern": "zzzzz", "path": tmpdir})
            self.assertIn("No matches", result)

    def test_grep_invalid_regex(self):
        result = GrepTool["fn"]({"pattern": "[invalid", "path": "/tmp"})
        self.assertIn("[error]", result)


class TestBashTool(unittest.TestCase):
    def test_echo(self):
        result = BashTool["fn"]({"command": "echo hello"})
        self.assertEqual(result.strip(), "hello")

    def test_timeout(self):
        result = BashTool["fn"]({"command": "sleep 10", "timeout": 1})
        self.assertIn("timed out", result.lower())

    def test_stderr(self):
        result = BashTool["fn"]({"command": "echo err >&2"})
        self.assertIn("[stderr]", result)
        self.assertIn("err", result)


if __name__ == "__main__":
    unittest.main()
