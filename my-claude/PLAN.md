# my-claude 开发计划

用 Python 重写 Claude Code CLI 的学习型项目。对应原仓库：`src/` 目录。

## 总体原则

- 按「能跑起来 → 能用 → 好用」三个阶段推进，每个阶段结束都有可运行的版本
- 不要试图一次性重写全部，每个模块先看原版对应文件，搞清楚做了什么，再用 Python 实现
- 不依赖官方 Python SDK 以外的抽象，后续可替换为裸 HTTP（`httpx` + SSE）

---

## 阶段一：最小可用版本（MVP） ✅

**目标**：能和 Claude 对话、能执行工具的命令行程序。

**对应原版**：`src/query.ts`、`src/entrypoints/cli.tsx`、`src/tools/`

```
my-claude/
├── main.py              # 入口，处理命令行参数
├── config.py            # 读取 API Key、模型配置
├── conversation.py      # 对话循环（对应 query.ts）
└── tools/
    ├── __init__.py      # 工具注册表
    ├── bash.py          # BashTool
    ├── file_read.py     # FileReadTool
    ├── file_write.py    # FileWriteTool
    └── file_edit.py     # FileEditTool（字符串替换）
```

**学习重点**：工具调用循环

```
用户输入
  → Claude API（带工具定义）
  → 有 tool_use？
      是 → 执行工具 → 结果作为 tool_result 发回 → 继续循环
      否 → 打印文本，等待下一轮用户输入
```

**运行方式**：
```bash
pip install anthropic
export ANTHROPIC_API_KEY=your_key
python main.py
```

---

## 阶段二：工程化

**目标**：加入权限确认、更多工具、基本终端 UI。

**对应原版**：`src/permissions/`、`src/tools/`、`src/screens/REPL.tsx`

```
my-claude/
├── main.py
├── config.py
├── conversation.py
├── permissions.py       # 权限检查（对应 src/permissions/ 目录）
├── context.py           # 读取 CLAUDE.md、git status 构建上下文
├── ui/
│   ├── repl.py          # 主 REPL 界面（用 rich 库）
│   └── diff_view.py     # 文件修改的 diff 展示
└── tools/
    ├── ...（阶段一的工具）
    ├── glob_tool.py     # GlobTool
    ├── grep_tool.py     # GrepTool
    └── web_fetch.py     # WebFetchTool
```

**学习重点**：
- 权限系统：plan / auto / manual 三种模式
- 上下文构建：CLAUDE.md 读取、git status 注入系统提示
- 终端 UI：用 `rich` 渲染 Markdown、diff

---

## 阶段三：服务层

**目标**：加入会话管理、对话压缩、斜杠命令。

**对应原版**：`src/services/compact/`、`src/commands/`、`src/services/mcp/`

```
my-claude/
├── ...（前两阶段的所有文件）
├── services/
│   ├── compact.py       # 对话压缩（上下文太长时自动压缩，对应 autoCompact.ts）
│   ├── session.py       # 会话保存/恢复（对应 /resume 命令）
│   └── memory.py        # CLAUDE.md 读写
└── commands/            # 斜杠命令（/help /clear /cost 等）
    ├── __init__.py
    ├── help.py
    ├── clear.py
    ├── cost.py
    └── model.py
```

**学习重点**：
- 对话压缩：当 token 超限时，如何摘要历史消息
- 斜杠命令路由：识别 `/xxx` 输入并分发
- 会话持久化：JSON 序列化消息历史

---

## 阶段四：完善

**目标**：稳定性、测试、多 API 提供商支持。

**对应原版**：`src/services/api/client.ts`（多 provider）、`src/services/api/claude.ts`

```
my-claude/
├── ...
├── providers/           # 多 API 提供商（对应 src/services/api/）
│   ├── base.py          # 抽象基类
│   ├── anthropic.py     # 默认（当前用 SDK，可替换为裸 HTTP）
│   ├── bedrock.py       # AWS Bedrock
│   └── vertex.py        # Google Vertex
└── tests/
    ├── test_tools.py
    ├── test_conversation.py
    └── test_permissions.py
```

**可选升级**：将 `providers/anthropic.py` 从 Python SDK 替换为 `httpx` + SSE 手动解析，深入了解底层协议。

---

## 各模块对应原版文件

| Python 文件 | 原版 TypeScript 文件 |
|-------------|---------------------|
| `conversation.py` | `src/query.ts` |
| `main.py` | `src/entrypoints/cli.tsx` + `src/main.tsx` |
| `config.py` | `src/utils/config.ts` |
| `tools/bash.py` | `src/tools/BashTool/` |
| `tools/file_read.py` | `src/tools/FileReadTool/` |
| `tools/file_write.py` | `src/tools/FileWriteTool/` |
| `tools/file_edit.py` | `src/tools/FileEditTool/` |
| `permissions.py` | `src/permissions/` |
| `context.py` | `src/context.ts` + `src/utils/claudemd.ts` |
| `services/compact.py` | `src/services/compact/autoCompact.ts` |
| `services/session.py` | `src/screens/ResumeConversation.tsx` |
| `providers/anthropic.py` | `src/services/api/claude.ts` + `client.ts` |
