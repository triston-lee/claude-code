from tools.bash import BashTool
from tools.file_read import FileReadTool
from tools.file_write import FileWriteTool
from tools.file_edit import FileEditTool
from tools.glob_tool import GlobTool
from tools.grep_tool import GrepTool
from tools.web_fetch import WebFetchTool

ALL_TOOLS = [BashTool, FileReadTool, FileWriteTool, FileEditTool, GlobTool, GrepTool, WebFetchTool]

# 工具注册表：name -> 执行函数
TOOL_REGISTRY = {tool["name"]: tool["fn"] for tool in ALL_TOOLS}

# 传给 Claude API 的 tools 列表（去掉内部的 fn 字段）
def get_api_tools():
    return [
        {k: v for k, v in tool.items() if k != "fn"}
        for tool in ALL_TOOLS
    ]
