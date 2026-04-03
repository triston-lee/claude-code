"""
权限系统测试
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import permissions


class TestPermissions(unittest.TestCase):
    def setUp(self):
        # 每个测试前重置状态
        permissions.set_mode("default")
        # 重置 READ_ONLY_TOOLS 到默认值
        permissions.READ_ONLY_TOOLS.clear()
        permissions.READ_ONLY_TOOLS.update({"file_read", "glob", "grep", "web_fetch"})

    def test_set_mode_valid(self):
        permissions.set_mode("bypass")
        self.assertEqual(permissions.get_mode(), "bypass")
        permissions.set_mode("plan")
        self.assertEqual(permissions.get_mode(), "plan")
        permissions.set_mode("default")
        self.assertEqual(permissions.get_mode(), "default")

    def test_set_mode_invalid(self):
        with self.assertRaises(ValueError):
            permissions.set_mode("invalid")

    def test_bypass_mode_allows_all(self):
        permissions.set_mode("bypass")
        self.assertTrue(permissions.check_permission("bash", {"command": "rm -rf /"}))
        self.assertTrue(permissions.check_permission("file_write", {"path": "/etc/passwd"}))

    def test_default_mode_allows_readonly(self):
        permissions.set_mode("default")
        self.assertTrue(permissions.check_permission("file_read", {"path": "foo.txt"}))
        self.assertTrue(permissions.check_permission("glob", {"pattern": "*.py"}))
        self.assertTrue(permissions.check_permission("grep", {"pattern": "hello"}))
        self.assertTrue(permissions.check_permission("web_fetch", {"url": "http://example.com"}))

    @patch("builtins.input", return_value="y")
    def test_default_mode_asks_for_bash(self, mock_input):
        permissions.set_mode("default")
        result = permissions.check_permission("bash", {"command": "ls"})
        self.assertTrue(result)
        mock_input.assert_called_once()

    @patch("builtins.input", return_value="n")
    def test_default_mode_denies_on_n(self, mock_input):
        permissions.set_mode("default")
        result = permissions.check_permission("bash", {"command": "ls"})
        self.assertFalse(result)

    @patch("builtins.input", return_value="y!")
    def test_allow_all_for_session(self, mock_input):
        permissions.set_mode("default")
        result = permissions.check_permission("bash", {"command": "ls"})
        self.assertTrue(result)
        # 之后不再询问
        result2 = permissions.check_permission("bash", {"command": "echo hi"})
        self.assertTrue(result2)

    @patch("builtins.input", return_value="y")
    def test_plan_mode_asks_for_readonly(self, mock_input):
        permissions.set_mode("plan")
        result = permissions.check_permission("file_read", {"path": "foo.txt"})
        self.assertTrue(result)
        mock_input.assert_called_once()


if __name__ == "__main__":
    unittest.main()
