# my-claude 2.0 深度研究计划

基于对原版 claude-code 源码的逐文件研究。每个模块包含：原版关键代码片段、架构决策分析、Python 实现方案。

---

## 模块一：工具系统架构

### 原版文件
- src/Tool.ts（793行）— 接口定义与 buildTool 工厂
- src/tools.ts — 工具注册表
- src/tools/BashTool/BashTool.tsx — 典型复杂工具

### 核心数据结构（直接来自 Tool.ts）

Tool 接口有 30+ 个方法，但通过 buildTool() 工厂大多有默认值：



设计哲学：所有默认值都偏向保守（fail-closed）。
新工具不显式声明并发安全 → 串行执行，避免竞态。

### Tool 接口关键方法分类

| 类别 | 方法 | 说明 |
|------|------|------|
| 核心执行 | call(args, context, canUseTool, parentMsg, onProgress?) | 实际执行，返回 ToolResult<T> |
| 输入定义 | inputSchema: Zod.ZodType | Zod v4 schema，同时用于 API 和验证 |
| 权限 | checkPermissions(input, ctx) | 工具级权限逻辑（通用权限系统外的补充）|
| 权限 | validateInput(input, ctx) | 前置验证，失败直接报错不触发权限弹窗 |
| 权限 | preparePermissionMatcher(input) | 预编译权限规则匹配器（性能优化）|
| 分类 | isConcurrencySafe(input) | 是否可与其他工具并行 |
| 分类 | isReadOnly(input) | 是否只读（影响 bypassPermissions 模式）|
| 分类 | isDestructive(input) | 是否不可逆（删除/覆写/发送）|
| 分类 | isSearchOrReadCommand(input) | UI 折叠展示依据 |
| UI | renderToolUseMessage(input, opts) | 工具调用时的展示（流式，input 可能不完整）|
| UI | renderToolResultMessage(output, progress, opts) | 结果展示 |
| UI | renderToolUseProgressMessage(progress, opts) | 执行中进度展示 |
| UI | getActivityDescription(input) | Spinner 文字（如 "Reading src/foo.ts"）|
| UI | getToolUseSummary(input) | 紧凑视图摘要 |
| API | mapToolResultToToolResultBlockParam(content, toolUseID) | 序列化给 Anthropic API |
| 优化 | maxResultSizeChars | 超过此大小写磁盘，API 收到文件路径 |
| 优化 | backfillObservableInput(input) | 注入兼容字段（不修改 API 缓存的原始 input）|
| 搜索 | searchHint | 3-10 词描述，供 ToolSearch 关键词匹配 |
| 搜索 | shouldDefer | 是否延迟加载（需 ToolSearch 先调用）|

### ToolResult 类型



注意：contextModifier 只对 isConcurrencySafe=false 的工具有效。
并发工具的 contextModifier 被忽略，因为多个工具并行修改 context 会冲突。

### Python 实现目标



---

## 模块二：流式响应 + 并发工具执行

### 原版文件
- src/services/tools/StreamingToolExecutor.ts（530行）
- src/services/tools/toolOrchestration.ts
- src/query.ts（1732行）

### SSE 事件流格式（直接来自 Anthropic API）

原版使用 @anthropic-ai/sdk 的 Stream<BetaRawMessageStreamEvent>，
但其底层就是标准 SSE。事件类型：

```
message_start       → 消息开始，含 input_tokens
content_block_start → 块开始（type: "text" 或 "tool_use"）
content_block_delta → 增量（text_delta 或 input_json_delta）
content_block_stop  → 块结束
message_delta       → stop_reason + output_tokens
message_stop        → 消息结束
ping                → 心跳（忽略）
```

### StreamingToolExecutor 并发模型

核心思想：工具在 Claude 还在流式输出时就开始执行。

```
Claude 流式输出：  text... text... [tool_use_start] ... [tool_use_stop] text...
工具执行：                           ↑立即开始执行，不等流结束
结果输出：                                                  ↑流结束时工具可能已完成
```

工具状态机（TrackedTool.status）：
  queued → executing → completed → yielded

并发控制规则：
- isConcurrencySafe=true  的工具：可与其他 safe 工具并行
- isConcurrencySafe=false 的工具：独占执行，等所有其他工具完成后才开始

```typescript
type TrackedTool = {
  id: string
  block: ToolUseBlock
  status: 'queued' | 'executing' | 'completed' | 'yielded'
  isConcurrencySafe: boolean
  promise?: Promise<void>
  results?: Message[]
  pendingProgress: Message[]     // 进度消息立即 yield，不等工具完成
  contextModifiers?: Array<(ctx: ToolUseContext) => ToolUseContext>
}
```

siblingAbortController：BashTool 出错时，取消所有兄弟进程。
不取消父 abortController（query.ts 继续运行这一轮）。

### Python 实现目标（asyncio 版）

```python
# core/tool_orchestrator.py
import asyncio

async def stream_and_execute(stream, tools: dict, context: dict):
    tasks = {}          # index -> asyncio.Task
    tool_inputs = {}    # index -> accumulated json string
    
    async for event in stream:
        if event.type == "content_block_start" and event.block_type == "tool_use":
            tool_inputs[event.index] = ""
            # 立即开始执行（输入稍后通过 json_delta 填充）
            # 注意：实际执行需等 content_block_stop 后才有完整 input
            
        elif event.type == "text_delta":
            print(event.text, end="", flush=True)
            
        elif event.type == "input_json_delta":
            tool_inputs[event.index] = tool_inputs.get(event.index, "") + event.partial_json
            
        elif event.type == "content_block_stop":
            if event.index in tool_inputs:
                # 现在有完整 input，启动工具
                import json
                # 需要从之前记录的 block_start 信息中拿 tool name/id
                tasks[event.index] = asyncio.create_task(
                    execute_tool(tools, tool_inputs[event.index], context)
                )
    
    results = await asyncio.gather(*tasks.values())
    return results
```

### 已实现状态

Phase A 已完成（2026-04-03 提交 889577f）：
- core/streaming.py: SSE 事件类型 + ResponseAssembler
- core/client.py: 同步/异步 httpx 客户端
- core/query.py: 单轮查询函数
- providers/httpx_provider.py: Provider 适配器

待实现：asyncio 并发工具执行（core/tool_orchestrator.py）

---

## 模块三：Context Window 管理

### 原版文件
- src/services/compact/autoCompact.ts
- src/services/compact/compact.ts
- src/services/compact/microCompact.ts
- src/services/compact/snipCompact.ts（⚠️ 此版本为 STUB）
- src/services/compact/reactiveCompact.ts（⚠️ feature flag 关闭）

### 关键常量（来自 autoCompact.ts）

```typescript
const MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000   // 压缩输出预留
const AUTOCOMPACT_BUFFER_TOKENS = 13_000        // 安全缓冲
const WARNING_THRESHOLD_BUFFER_TOKENS = 20_000
const ERROR_THRESHOLD_BUFFER_TOKENS = 20_000
const MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3  // 熔断器
```

触发阈值计算：
```
effectiveContextWindow = contextWindow(model) - min(maxOutputTokens, 20000)
autocompactThreshold = effectiveContextWindow - 13000

// Claude Opus 4.6 (200k 上下文):
// effectiveContextWindow = 200000 - 20000 = 180000
// autocompactThreshold = 180000 - 13000 = 167000 tokens
```

环境变量覆盖：
- CLAUDE_CODE_AUTO_COMPACT_WINDOW: 限制上下文窗口大小
- CLAUDE_AUTOCOMPACT_PCT_OVERRIDE: 按百分比设置阈值（调试用）

### microCompact 压缩逻辑

只压缩特定工具的 tool_result，保留对话结构：

```typescript
const COMPACTABLE_TOOLS = new Set([
  'file_read', 'bash', 'computer', 'grep', 'glob',
  'web_search', 'web_fetch', 'file_edit', 'file_write'
])
const TIME_BASED_MC_CLEARED_MESSAGE = '[Old tool result content cleared]'
const IMAGE_MAX_TOKEN_SIZE = 2000  // 图片超过此大小也被清除
```

压缩策略：将"旧"的 tool_result 内容替换为占位符字符串。
"旧"的定义由 TimeBasedMCConfig 决定（基于时间的配置）。

### snipCompact 状态

⚠️ 重要发现：在这个反编译版本中，snipCompact 是自动生成的 STUB：
```typescript
// snipCompact.ts - AUTO-GENERATED STUB
export const snipCompactIfNeeded = (messages) => ({
  messages,
  executed: false,  // 永远不执行！
  tokensFreed: 0,
})
export const isSnipRuntimeEnabled = () => false
```

### Python 实现目标

```python
# services/compact_v2.py

MODEL_CONTEXT_WINDOWS = {
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5": 200_000,
}
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
AUTOCOMPACT_BUFFER_TOKENS = 13_000
MAX_CONSECUTIVE_FAILURES = 3

def get_autocompact_threshold(model: str) -> int:
    context_window = MODEL_CONTEXT_WINDOWS.get(model, 200_000)
    effective = context_window - MAX_OUTPUT_TOKENS_FOR_SUMMARY
    return effective - AUTOCOMPACT_BUFFER_TOKENS

COMPACTABLE_TOOLS = {
    "file_read", "bash", "grep", "glob",
    "web_search", "web_fetch", "file_edit", "file_write"
}
MC_CLEARED_MESSAGE = "[Old tool result content cleared]"

def micro_compact(messages: list, max_age_turns: int = 10) -> list:
    """
    压缩旧 tool_result：保留最近 max_age_turns 轮的完整结果，
    将更早的 tool_result 替换为占位符。
    """
    result = []
    turn = 0
    for msg in messages:
        if msg["role"] == "user" and isinstance(msg["content"], list):
            compacted_content = []
            for block in msg["content"]:
                if (block.get("type") == "tool_result"
                        and turn < len(messages) // 2 - max_age_turns):
                    compacted_content.append({
                        **block,
                        "content": MC_CLEARED_MESSAGE,
                    })
                else:
                    compacted_content.append(block)
            result.append({**msg, "content": compacted_content})
        else:
            result.append(msg)
        if msg["role"] == "assistant":
            turn += 1
    return result
```

---

## 模块四：Hook 系统（AOP 设计）

### 原版文件
- src/utils/hooks.ts（1700+ 行）
- src/schemas/hooks.ts — Zod schema 定义
- src/entrypoints/sdk/coreTypes.ts — HOOK_EVENTS 常量

### 完整 Hook 事件列表（来自 coreTypes.ts）

```typescript
export const HOOK_EVENTS = [
  'PreToolUse',        // 工具执行前（可阻止）
  'PostToolUse',       // 工具成功后
  'PostToolUseFailure',// 工具失败后
  'Notification',      // 通知事件
  'UserPromptSubmit',  // 用户提交输入
  'SessionStart',      // 会话开始
  'SessionEnd',        // 会话结束
  'Stop',              // Claude 停止响应
  'StopFailure',       // 停止时出错
  'SubagentStart',     // 子 Agent 启动
  'SubagentStop',      // 子 Agent 结束
  'PreCompact',        // 压缩前
  'PostCompact',       // 压缩后
  'PermissionRequest', // 权限请求
  'PermissionDenied',  // 权限拒绝
  'Setup',             // 初始化
  'TeammateIdle',      // 队友空闲
  'TaskCreated',       // 任务创建
  'TaskCompleted',     // 任务完成
  'Elicitation',       // 引导
  'ElicitationResult', // 引导结果
  'ConfigChange',      // 配置变更
  'WorktreeCreate',    // git worktree 创建
  'WorktreeRemove',    // git worktree 移除
  'InstructionsLoaded',// CLAUDE.md 加载
  'CwdChanged',        // 工作目录变更
  'FileChanged',       // 文件变更
] as const  // 共 27 种
```

### Hook 类型（来自 schemas/hooks.ts）

4 种 Hook 实现类型，通过 discriminated union：

```typescript
// 1. Shell 命令 hook（最常用）
type BashCommandHook = {
  type: 'command'
  command: string        // shell 命令
  if?: string            // 权限规则语法的前置条件（如 "Bash(git *)"）
  shell?: 'bash'|'powershell'
  timeout?: number       // 秒数
  statusMessage?: string // spinner 显示文字
  once?: boolean         // 执行一次后删除
  async?: boolean        // 后台运行，不阻塞
  asyncRewake?: boolean  // 后台运行，exit code 2 唤醒模型（implies async）
}

// 2. LLM Prompt hook
type PromptHook = {
  type: 'prompt'
  prompt: string   // 给 LLM 的 prompt（用 $ARGUMENTS 引用 hook input JSON）
  if?: string
  timeout?: number
  model?: string   // 默认用小模型（Haiku）
  statusMessage?: string
  once?: boolean
}

// 3. HTTP hook
type HttpHook = {
  type: 'http'
  url: string
  if?: string
  headers?: Record<string, string>
  allowedEnvVars?: string[]  // 允许在 headers 中插值的环境变量
  timeout?: number
  statusMessage?: string
  once?: boolean
}

// 4. Agent hook（验证器）
type AgentHook = {
  type: 'agent'
  prompt: string   // 验证 prompt（如 "Verify that tests passed"）
  if?: string
  timeout?: number // 默认 60 秒
  model?: string   // 默认 Haiku
  statusMessage?: string
  once?: boolean
}
```

### settings.json 配置格式

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "echo '[hook] About to run: $CLAUDE_TOOL_INPUT'"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "file_edit",
        "hooks": [
          { "type": "command", "command": "git add -A" },
          {
            "type": "agent",
            "prompt": "Verify the edit didn't break any imports"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "notify-send 'Claude done'", "async": true }
        ]
      }
    ]
  }
}
```

### 关键超时常量（hooks.ts）

```typescript
const TOOL_HOOK_EXECUTION_TIMEOUT_MS = 10 * 60 * 1000  // 10 分钟（工具 hook）
const SESSION_END_HOOK_TIMEOUT_MS_DEFAULT = 1500        // 1.5 秒（会话结束 hook！）
// 可通过 CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS 环境变量覆盖
```

SessionEnd hook 只有 1.5 秒是有意设计的——用户关闭终端时不能等待太长。

### asyncRewake 机制

exit code 2 有特殊语义：
- code 0: 成功
- code 1: 失败（记录但不阻塞）
- code 2: "需要模型注意"——将 stderr/stdout 作为系统消息注入对话，唤醒模型

这让 hook 可以异步监控然后"打断"Claude：
```bash
# 在 PostToolUse 中监控测试
type: asyncRewake
command: |
  sleep 5 && pytest && exit 0 || exit 2
```

### Python 实现目标

```python
# services/hooks.py
import subprocess
import json
import os
from dataclasses import dataclass

TOOL_HOOK_TIMEOUT = 600  # 10 分钟
SESSION_END_HOOK_TIMEOUT = 1.5  # 1.5 秒

@dataclass
class HookCommand:
    type: str           # 'command' | 'prompt' | 'http' | 'agent'
    # command hook
    command: str = ""
    shell: str = "bash"
    timeout: float | None = None
    status_message: str = ""
    once: bool = False
    async_: bool = False
    async_rewake: bool = False
    if_condition: str = ""  # 'if' 字段
    # prompt/agent hook
    prompt: str = ""
    model: str = ""
    # http hook
    url: str = ""
    headers: dict = None
    allowed_env_vars: list = None

@dataclass
class HookMatcher:
    matcher: str        # 工具名匹配模式（如 "Bash", "file_*"）
    hooks: list[HookCommand]

class HookExecutor:
    def __init__(self, settings: dict):
        self._config = settings.get("hooks", {})

    def run_pre_tool(self, tool_name: str, tool_input: dict) -> bool:
        """返回 False 表示阻止工具执行（exit code 2 或 hook deny）"""
        return self._run_event("PreToolUse", tool_name, tool_input)

    def run_post_tool(self, tool_name: str, tool_input: dict, result: str) -> None:
        self._run_event("PostToolUse", tool_name, tool_input, result)

    def run_stop(self) -> None:
        self._run_event("Stop", "", {})

    def run_session_start(self) -> None:
        self._run_event("SessionStart", "", {})

    def run_session_end(self) -> None:
        """超时只有 1.5 秒！"""
        self._run_event("SessionEnd", "", {}, timeout_override=SESSION_END_HOOK_TIMEOUT)

    def _run_event(self, event: str, tool_name: str,
                   tool_input: dict, result: str = "", timeout_override=None) -> bool:
        matchers = self._config.get(event, [])
        for matcher_config in matchers:
            matcher = matcher_config.get("matcher", "")
            if matcher and not self._matches(matcher, tool_name, tool_input):
                continue
            for hook in matcher_config.get("hooks", []):
                ok = self._exec_hook(hook, tool_name, tool_input, result,
                                     timeout_override or TOOL_HOOK_TIMEOUT)
                if not ok:
                    return False
        return True

    def _matches(self, matcher: str, tool_name: str, tool_input: dict) -> bool:
        """用权限规则语法匹配 tool_name（如 'Bash(git *)'）"""
        from permissions.rule_engine import match_tool_pattern
        return match_tool_pattern(matcher, tool_name, tool_input)

    def _exec_hook(self, hook: dict, tool_name: str,
                   tool_input: dict, result: str, timeout: float) -> bool:
        hook_type = hook.get("type", "command")
        env = {**os.environ, "CLAUDE_TOOL_NAME": tool_name,
               "CLAUDE_TOOL_INPUT": json.dumps(tool_input),
               "CLAUDE_TOOL_RESULT": result}

        if hook_type == "command":
            try:
                proc = subprocess.run(
                    hook["command"], shell=True, env=env,
                    capture_output=True, text=True, timeout=timeout
                )
                if proc.returncode == 2:
                    print(f"[hook] blocking: {proc.stderr or proc.stdout}")
                    return False
            except subprocess.TimeoutExpired:
                pass  # 超时忽略
        return True
```

---

## 模块七：权限规则引擎

### 原版文件
- src/types/permissions.ts — 类型定义（248行）
- src/utils/permissions/shellRuleMatching.ts — Shell 命令匹配算法
- src/utils/permissions/permissionRuleParser.ts
- src/utils/settings/types.ts — PermissionsSchema（Zod）

### 完整类型定义（来自 permissions.ts）

```typescript
// 5 种用户可见模式 + 2 种内部模式
type PermissionMode =
  | 'acceptEdits'       // 自动接受文件编辑，其他需询问
  | 'bypassPermissions' // 绕过所有权限检查（危险！）
  | 'default'           // 默认：每次询问
  | 'dontAsk'           // 不询问（自动接受所有）
  | 'plan'              // 只读模式，不允许写操作
  | 'auto'              // 内部：AI 分类器决定（feature flag 控制）
  | 'bubble'            // 内部：冒泡到父 agent

// 8 种规则来源（优先级从高到低）
type PermissionRuleSource =
  | 'cliArg'           // CLI 参数（最高优先级）
  | 'session'          // 本次会话动态添加
  | 'localSettings'    // .claude/settings.local.json
  | 'projectSettings'  // .claude/settings.json
  | 'userSettings'     // ~/.claude/settings.json
  | 'flagSettings'     // feature flag 配置
  | 'policySettings'   // 策略配置
  | 'command'          // 斜杠命令添加

// 权限规则
type PermissionRule = {
  source: PermissionRuleSource
  ruleBehavior: 'allow' | 'deny' | 'ask'
  ruleValue: {
    toolName: string      // 如 "Bash", "file_edit"
    ruleContent?: string  // 如 "git *"（bash 命令模式）
  }
}
```

### settings.json 权限配置

```json
{
  "permissions": {
    "allow": ["Bash(git *)", "file_read", "glob"],
    "deny":  ["Bash(rm -rf *)"],
    "ask":   ["Bash(curl *)"],
    "defaultMode": "default",
    "additionalDirectories": ["/tmp/work"]
  }
}
```

规则字符串格式：`toolName` 或 `toolName(content)`
- `"file_read"` → 允许所有文件读取
- `"Bash(git *)"` → 允许以 git 开头的 bash 命令
- `"Bash(npm run *)"` → 允许 npm run 命令

### Shell 规则匹配算法（shellRuleMatching.ts 核心）

3 种规则类型：
1. **exact** — 精确匹配（如 `"git status"`）
2. **prefix** — 旧语法 `"git:*"` → 匹配 "git" 开头的命令
3. **wildcard** — 含未转义 * 的模式（如 `"git *"`）

matchWildcardPattern 完整算法：
```typescript
function matchWildcardPattern(pattern: string, command: string): boolean {
  // 1. 处理转义序列
  //    \* → ESCAPED_STAR_PLACEHOLDER（字面量 *）
  //    \\ → ESCAPED_BACKSLASH_PLACEHOLDER（字面量 \）

  // 2. 转义 regex 特殊字符（. + ? ^ $ { } ( ) | [ ] \ '）

  // 3. 将未转义的 * 替换为 .*

  // 4. 还原占位符（ESCAPED_STAR → \*，ESCAPED_BACKSLASH → \\）

  // 5. 特例：末尾 ' .*'（单个通配符+前置空格）→ '( .*)?'
  //    使 "git *" 既匹配 "git add" 也匹配裸 "git"
  if (regexPattern.endsWith(' .*') && unescapedStarCount === 1) {
    regexPattern = regexPattern.slice(0, -3) + '( .*)?'
  }

  // 6. 用 /^pattern$/s 匹配（dotAll：. 可匹配换行符）
  return new RegExp(`^${regexPattern}$`, 's').test(command)
}
```

示例：
- `"git *"` → regex `^git( .*)?$`
  - ✅ 匹配 "git", "git add", "git commit -m 'foo'"
  - ❌ 不匹配 "gitk"（没有空格分隔）
- `"npm * --save"` → regex `^npm .* --save$`
  - ✅ 匹配 "npm install lodash --save"

### PermissionResult 类型（三种结果）

```typescript
type PermissionResult =
  | {
      behavior: 'allow'
      updatedInput?: Record<string, unknown>  // 可修改输入（如规范化路径）
      userModified?: boolean
      decisionReason?: string
      toolUseID?: string
      acceptFeedback?: string
    }
  | {
      behavior: 'ask'
      message: string                    // 询问用户的说明
      updatedInput?: Record<string, unknown>
      suggestions?: PermissionUpdate[]  // 建议添加的规则
      blockedPath?: string              // 被阻止的路径
      pendingClassifierCheck?: {        // 异步分类器检查
        command: string
        cwd: string
        descriptions: string[]
      }
    }
  | {
      behavior: 'deny'
      message: string
      decisionReason: string
    }
```

### Python 实现目标

```python
# permissions/rule_engine.py
import fnmatch
import re
from dataclasses import dataclass
from enum import Enum

class PermissionMode(str, Enum):
    ACCEPT_EDITS = "acceptEdits"
    BYPASS = "bypassPermissions"
    DEFAULT = "default"
    DONT_ASK = "dontAsk"
    PLAN = "plan"

RULE_SOURCE_PRIORITY = [
    "cliArg", "session", "localSettings",
    "projectSettings", "userSettings",
    "flagSettings", "policySettings", "command"
]

@dataclass
class PermissionRule:
    source: str          # 来源
    behavior: str        # 'allow' | 'deny' | 'ask'
    tool_name: str       # 工具名
    rule_content: str    # 命令模式（可选）

@dataclass
class PermissionResult:
    behavior: str        # 'allow' | 'ask' | 'deny'
    message: str = ""
    updated_input: dict | None = None
    suggestions: list = None

def match_wildcard_pattern(pattern: str, command: str) -> bool:
    """对应 shellRuleMatching.ts 的 matchWildcardPattern"""
    p = pattern.strip()
    # 处理转义（简化版）
    p = p.replace("\\*", "\x00STAR\x00")
    p = p.replace("\\\\", "\x00BS\x00")
    # 转义 regex 特殊字符（除 *）
    p = re.escape(p).replace("\\*", "*")
    # * → .*
    p = p.replace("*", ".*")
    # 还原占位符
    p = p.replace("\x00STAR\x00", "\\*")
    p = p.replace("\x00BS\x00", "\\\\")
    # 特例：末尾 ' .*'（单个通配符）→ 可选尾部参数
    if p.endswith(" .*") and pattern.count("*") == 1:
        p = p[:-3] + "( .*)?"
    return bool(re.match(f"^{p}$", command, re.DOTALL))

def match_tool_pattern(pattern: str, tool_name: str, tool_input: dict) -> bool:
    """
    解析 'ToolName(content)' 格式并匹配。
    - 'Bash' → 匹配所有 bash 调用
    - 'Bash(git *)' → 只匹配以 git 开头的 bash 命令
    """
    if '(' in pattern and pattern.endswith(')'):
        paren_pos = pattern.index('(')
        pname = pattern[:paren_pos]
        pcontent = pattern[paren_pos+1:-1]
    else:
        pname = pattern
        pcontent = ""

    # 工具名不匹配
    if pname.lower() != tool_name.lower():
        return False

    # 无内容约束 → 匹配所有
    if not pcontent:
        return True

    # bash 类工具：匹配命令
    command = tool_input.get("command", "")
    return match_wildcard_pattern(pcontent, command)

class RuleEngine:
    def __init__(self):
        self._rules: list[PermissionRule] = []
        self._mode: PermissionMode = PermissionMode.DEFAULT

    def add_rule(self, source: str, behavior: str,
                 tool_name: str, rule_content: str = "") -> None:
        self._rules.append(PermissionRule(source, behavior, tool_name, rule_content))

    def load_from_settings(self, settings: dict) -> None:
        perms = settings.get("permissions", {})
        for rule_str in perms.get("allow", []):
            name, content = _parse_rule_string(rule_str)
            self.add_rule("projectSettings", "allow", name, content)
        for rule_str in perms.get("deny", []):
            name, content = _parse_rule_string(rule_str)
            self.add_rule("projectSettings", "deny", name, content)
        for rule_str in perms.get("ask", []):
            name, content = _parse_rule_string(rule_str)
            self.add_rule("projectSettings", "ask", name, content)
        if "defaultMode" in perms:
            self._mode = PermissionMode(perms["defaultMode"])

    def check(self, tool_name: str, tool_input: dict) -> PermissionResult:
        # 按优先级排序规则（高优先级先检查）
        sorted_rules = sorted(self._rules,
            key=lambda r: RULE_SOURCE_PRIORITY.index(r.source)
            if r.source in RULE_SOURCE_PRIORITY else 99)

        for rule in sorted_rules:
            if match_tool_pattern(
                rule.tool_name + (f'({rule.rule_content})' if rule.rule_content else ''),
                tool_name, tool_input
            ):
                return PermissionResult(behavior=rule.behavior)

        # 无匹配规则 → 根据模式决定
        if self._mode == PermissionMode.BYPASS:
            return PermissionResult(behavior="allow")
        if self._mode == PermissionMode.DONT_ASK:
            return PermissionResult(behavior="allow")
        return PermissionResult(behavior="ask",
                                message=f"Allow {tool_name}?")

def _parse_rule_string(rule: str) -> tuple[str, str]:
    """'Bash(git *)' → ('Bash', 'git *')"""
    if '(' in rule and rule.endswith(')'):
        pos = rule.index('(')
        return rule[:pos], rule[pos+1:-1]
    return rule, ""
```

---

## 模块九：Buddy 虚拟伴侣系统

### 原版文件
- src/buddy/types.ts — 数据定义
- src/buddy/companion.ts — 确定性生成算法
- src/buddy/sprites.ts — ASCII 精灵图
- src/buddy/prompt.ts — Claude 上下文注入
- src/buddy/useBuddyNotification.tsx — 气泡通知

### 完整物种 + 属性数据（来自 types.ts）

```typescript
// 18 种物种
export const SPECIES = [
  'duck', 'goose', 'blob', 'cat', 'dragon', 'octopus', 'owl',
  'penguin', 'turtle', 'snail', 'ghost', 'axolotl', 'capybara',
  'cactus', 'robot', 'rabbit', 'mushroom', 'chonk'
] as const

// 6 种眼睛
export const EYES = ['·', '✦', '×', '◉', '@', '°'] as const

// 8 种帽子（common 永远是 'none'）
export const HATS = [
  'none', 'crown', 'tophat', 'propeller',
  'halo', 'wizard', 'beanie', 'tinyduck'
] as const

// 5 种属性
export const STAT_NAMES = ['DEBUGGING', 'PATIENCE', 'CHAOS', 'WISDOM', 'SNARK'] as const

// 稀有度权重
export const RARITY_WEIGHTS = {
  common: 60, uncommon: 25, rare: 10, epic: 4, legendary: 1
}

// 属性底限（稀有度越高，属性越强）
const RARITY_FLOOR = {
  common: 5, uncommon: 15, rare: 25, epic: 35, legendary: 50
}

// 星级展示
export const RARITY_STARS = {
  common: '★', uncommon: '★★', rare: '★★★', epic: '★★★★', legendary: '★★★★★'
}
```

### 核心算法（来自 companion.ts）

**Mulberry32 PRNG**（确定性随机数生成器）：
```typescript
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return function () {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
```

**FNV-1a Hash**（非 Bun 环境 fallback）：
```typescript
function hashString(s: string): number {
  if (typeof Bun !== 'undefined') {
    return Number(BigInt(Bun.hash(s)) & 0xffffffffn)  // Bun 原生 hash
  }
  let h = 2166136261  // FNV offset basis
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)  // FNV prime
  }
  return h >>> 0
}
```

**SALT 设计**：
```typescript
const SALT = 'friend-2026-401'
// 用途：key = userId + SALT → hash → seed
// 防止用户通过 userId 预测或枚举自己的外观
```

**rollStats 属性分配**：
```
peak  stat: floor + 50 + random(0-29)  → 55-79（common）到 100（legendary）
dump  stat: max(1, floor-10 + random(0-14))  → 有可能很低
其余 stats: floor + random(0-39)
shiny: rng() < 0.01（1% 概率）
```

**存储策略**（关键设计决策）：
```typescript
// 只存灵魂，不存外观
type StoredCompanion = {
  name: string           // Claude 生成
  personality: string    // Claude 生成
  hatchedAt: number      // 时间戳
}
// 外观每次从 hash(userId) 重新生成
// 好处：用户无法编辑 config 来刷稀有度
```

### Companion 介绍文本（注入给 Claude 的 system prompt）

```typescript
// prompt.ts
export function companionIntroText(name: string, species: string): string {
  return `# Companion

A small ${species} named ${name} sits beside the user's input box and occasionally
comments in a speech bubble. You're not ${name} — it's a separate watcher.

When the user addresses ${name} directly (by name), its bubble will answer. Your job
in that moment is to stay out of the way: respond in ONE line or less, or just answer
any part of the message meant for you. Don't explain that you're not ${name} — they know.
Don't narrate what ${name} might say — the bubble handles that.`
}
```

### Sprites 格式（来自 sprites.ts）

```
每个精灵：5 行 × 12 列
{E} 占位符 → 眼睛字符（渲染时替换）
多帧动画（通常 3 帧，用于 idle 闲置动画）
Line 0 = 帽子槽（frames 0-1 为空，frame 2 可能有帽子）

示例（duck，frame 0）：
'            '
'    __      '
'  <({E} )___  '
'   (  ._>   '
'    `--´    '
```

### Python 实现目标

```python
# buddy/companion.py
import ctypes

SPECIES = [
    'duck', 'goose', 'blob', 'cat', 'dragon', 'octopus', 'owl',
    'penguin', 'turtle', 'snail', 'ghost', 'axolotl', 'capybara',
    'cactus', 'robot', 'rabbit', 'mushroom', 'chonk'
]
EYES = ['·', '✦', '×', '◉', '@', '°']
HATS = ['none', 'crown', 'tophat', 'propeller', 'halo', 'wizard', 'beanie', 'tinyduck']
STAT_NAMES = ['DEBUGGING', 'PATIENCE', 'CHAOS', 'WISDOM', 'SNARK']
RARITIES = ['common', 'uncommon', 'rare', 'epic', 'legendary']
RARITY_WEIGHTS = {'common': 60, 'uncommon': 25, 'rare': 10, 'epic': 4, 'legendary': 1}
RARITY_FLOOR = {'common': 5, 'uncommon': 15, 'rare': 25, 'epic': 35, 'legendary': 50}
RARITY_STARS = {'common': '★', 'uncommon': '★★', 'rare': '★★★', 'epic': '★★★★', 'legendary': '★★★★★'}
SALT = 'friend-2026-401'

def mulberry32(seed: int):
    """确定性 PRNG，完全对应原版 TypeScript 实现"""
    a = seed & 0xFFFFFFFF
    def rng() -> float:
        nonlocal a
        a = (a + 0x6d2b79f5) & 0xFFFFFFFF
        t = ctypes.c_int32(a ^ (a >> 15)).value
        t = ctypes.c_int32(t * (1 | a)).value
        t = ctypes.c_int32(t + ctypes.c_int32(
            ctypes.c_int32(t ^ (t >> 7)).value * (61 | t)
        ).value).value ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rng

def hash_string(s: str) -> int:
    """FNV-1a hash，对应原版 hashString()"""
    h = 2166136261  # FNV offset basis
    for c in s:
        h ^= ord(c)
        h = ctypes.c_uint32(h * 16777619).value
    return h

def roll_rarity(rng) -> str:
    total = sum(RARITY_WEIGHTS.values())
    r = rng() * total
    for rarity in RARITIES:
        r -= RARITY_WEIGHTS[rarity]
        if r < 0:
            return rarity
    return 'common'

def roll_stats(rng, rarity: str) -> dict:
    floor = RARITY_FLOOR[rarity]
    peak = STAT_NAMES[int(rng() * len(STAT_NAMES))]
    dump = peak
    while dump == peak:
        dump = STAT_NAMES[int(rng() * len(STAT_NAMES))]
    stats = {}
    for name in STAT_NAMES:
        if name == peak:
            stats[name] = min(100, floor + 50 + int(rng() * 30))
        elif name == dump:
            stats[name] = max(1, floor - 10 + int(rng() * 15))
        else:
            stats[name] = floor + int(rng() * 40)
    return stats

def roll(user_id: str) -> dict:
    """从 userId 确定性生成 companion bones"""
    key = user_id + SALT
    seed = hash_string(key)
    rng = mulberry32(seed)
    rarity = roll_rarity(rng)
    return {
        'rarity': rarity,
        'species': SPECIES[int(rng() * len(SPECIES))],
        'eye': EYES[int(rng() * len(EYES))],
        'hat': 'none' if rarity == 'common' else HATS[int(rng() * len(HATS))],
        'shiny': rng() < 0.01,
        'stats': roll_stats(rng, rarity),
        'inspiration_seed': int(rng() * 1e9),
    }

# buddy/soul.py
HATCH_PROMPT = """
You are generating a companion character for a software developer.

Species: {species}
Rarity: {rarity} ({stars})
Stats: {stats}

Generate:
1. A SHORT name (1-2 words, fits the species personality)
2. A personality description (2-3 sentences, based on the stats)

Respond in JSON: {{"name": "...", "personality": "..."}}
"""

# buddy/sprites.py
DUCK_SPRITES = [
    ['            ', '    __      ', '  <({E} )___  ', '   (  ._>   ', "    `--'    "],
    ['            ', '    __      ', '  <({E} )___  ', '   (  ._>   ', "    `--'~   "],
    ['            ', '    __      ', '  <({E} )___  ', '   (  .__>  ', "    `--'    "],
]

def render_sprite(bones: dict, frame: int = 0) -> str:
    """将 sprite 渲染为字符串，替换 {E} 为眼睛字符"""
    from buddy.sprites import BODIES, HATS_OVERLAY
    species = bones['species']
    eye = bones['eye']
    frames = BODIES.get(species, DUCK_SPRITES)
    sprite_frame = frames[frame % len(frames)]
    lines = [line.replace('{E}', eye) for line in sprite_frame]
    return '\n'.join(lines)
```

---

## 模块五：MCP（Model Context Protocol）

### 原版文件
- src/services/mcp/ 目录（12,242 LOC）
- src/tools/MCPTool/ 目录

### 协议分层

```
Claude API
    ↓ tool_use 块
工具调用系统
    ↓
MCPTool（统一适配器，将 MCP 工具包装成内部 Tool 接口）
    ↓
MCPClient（连接池管理，每个 server 一个连接）
    ↓
transport 层
    ├── stdio: 子进程通信（本地工具，如 github-mcp-server）
    └── HTTP:  SSE 或 WebSocket（远程工具）
```

### settings.json MCP 配置格式

```json
{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" }
    },
    "remote-db": {
      "type": "sse",
      "url": "https://my-mcp-server.com/sse",
      "headers": { "Authorization": "Bearer ${DB_TOKEN}" }
    }
  }
}
```

### 工具发现流程

```
startup
  → for each mcpServer in config:
      client = MCPClient(server_config)
      client.connect()          # 启动子进程 / 建立 HTTP 连接
      tools = client.list_tools()  # MCP initialize → tools/list
      for tool in tools:
          register(MCPTool(tool, client))  # 包装成内部 Tool
  → 所有 MCP 工具与内置工具合并到 tools 列表
```

### Python 实现目标（基于官方 mcp Python SDK）

```python
# services/mcp/client.py
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPServerClient:
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self._session: ClientSession | None = None

    async def connect(self):
        if self.config['type'] == 'stdio':
            params = StdioServerParameters(
                command=self.config['command'],
                args=self.config.get('args', []),
                env=self.config.get('env', {}),
            )
            self._read, self._write = await stdio_client(params).__aenter__()
            self._session = await ClientSession(self._read, self._write).__aenter__()
            await self._session.initialize()

    async def list_tools(self) -> list[dict]:
        result = await self._session.list_tools()
        return [
            {
                'name': f'mcp__{self.name}__{t.name}',
                'description': t.description,
                'input_schema': t.inputSchema,
                'mcp_server': self.name,
                'mcp_tool': t.name,
            }
            for t in result.tools
        ]

    async def call_tool(self, tool_name: str, tool_input: dict) -> str:
        result = await self._session.call_tool(tool_name, tool_input)
        return '\n'.join(
            c.text for c in result.content if hasattr(c, 'text')
        )
```

---

## 模块六：多 Agent 协调系统

### 原版文件
- src/tools/AgentTool/AgentTool.tsx（最复杂的工具）
- src/utils/forkedAgent.ts
- src/coordinator/

### 四种 fork 模式

| 模式 | 说明 | Python 实现 |
|------|------|-------------|
| subagent | 同步子任务，等待结果 | 函数调用 + await |
| background | 异步，不等结果 | asyncio.create_task |
| worktree | 独立 git worktree | subprocess + git worktree |
| remote | 远程环境 | HTTP 调用（暂不实现）|

### worktree 模式原理

```
主 Agent 工作在 main branch
  → fork worktree("fix-auth-bug")
      创建 git worktree /tmp/work-fix-auth-bug
      子 Agent 在独立分支工作
      互不干扰
  → 主 Agent 继续
  → 子 Agent 完成 → cherry-pick 到 main
```

这让 Claude 可以并行尝试多种方案，每个方案在独立分支，互不干扰。

### Python 实现目标

```python
# tools/agent_tool.py
import subprocess
import tempfile
import os

async def fork_subagent(task: str, context: dict) -> str:
    """同步子 Agent：完整的独立对话"""
    from conversation import run_single_task
    return await run_single_task(task, context)

def fork_worktree(task: str, branch_name: str, base_dir: str) -> str:
    """在独立 git worktree 中运行子 Agent"""
    worktree_path = tempfile.mkdtemp(prefix=f'claude-worktree-{branch_name}-')
    try:
        # 创建 worktree
        subprocess.run(
            ['git', 'worktree', 'add', '-b', branch_name, worktree_path],
            cwd=base_dir, check=True
        )
        # 在 worktree 中运行任务
        from conversation import run_single_task
        result = run_single_task(task, {'cwd': worktree_path})
        return result
    finally:
        # 清理 worktree
        subprocess.run(['git', 'worktree', 'remove', '--force', worktree_path],
                      cwd=base_dir)
```

---

## 模块八：Textual TUI 架构

### 对应原版
- src/screens/REPL.tsx（巨型组件）
- src/ink/（自定义 Ink 框架 fork）
- src/components/（组件库）

### 原版架构（React/Ink）

```
用户输入（键盘）
    ↓
PromptInput 组件（useInput hook）
    ↓
query.ts / QueryEngine.ts（API 调用）
    ↓ SSE 流式事件
REPL.tsx 状态更新（messages state）
    ↓
React 重渲染
    ↓
Ink reconciler（将 React 树映射到 ANSI 输出）
    ↓
Terminal output（ANSI 转义码）
```

虚拟滚动（useVirtualScroll）：消息列表可能几千条，只渲染可见区域。
流式更新：每个 SSE delta 触发最小化 re-render，不重绘整个界面。

### Python 对应（Textual）

```python
# ui/app.py（未来实现）
from textual.app import App, ComposeResult
from textual.widgets import Input, RichLog, Static
from textual.reactive import reactive

class MessageList(RichLog):
    """对应 Messages.tsx + 虚拟滚动"""
    pass

class ToolCallPanel(Static):
    """对应工具调用状态展示"""
    tool_name: reactive[str] = reactive("")
    pass

class PromptInput(Input):
    """对应 PromptInput/ 组件"""
    pass

class ClaudeApp(App):
    CSS = """
    MessageList { height: 1fr; }
    ToolCallPanel { height: auto; }
    PromptInput { dock: bottom; }
    """

    def compose(self) -> ComposeResult:
        yield MessageList()
        yield ToolCallPanel()
        yield PromptInput(placeholder="Message Claude...")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value
        event.input.clear()
        # 触发对话循环
        await self.run_conversation_turn(user_input)
```

---

## 实施路线图（已更新）

| 阶段 | 模块 | 状态 | 关键文件 |
|------|------|------|---------|
| A | 流式输出（SSE + httpx） | ✅ 完成 | core/streaming.py, core/client.py |
| B | Hook 系统 | 待实现 | services/hooks.py |
| C | 权限规则引擎 | 待实现 | permissions/rule_engine.py |
| D | 工具基类重构 | 待实现 | tools/base.py |
| E | 压缩策略扩展 | 待实现 | services/compact_v2.py |
| F | Buddy 系统 | 待实现 | buddy/ |
| G | asyncio 并发工具执行 | 待实现 | core/tool_orchestrator.py |
| H | MCP 协议 | 待实现 | services/mcp/ |
| I | 多 Agent 协调 | 待实现 | tools/agent_tool.py |
| J | Textual TUI | 可选 | ui/app.py |

## 各模块原版文件速查表

| Python 文件 | 原版 TypeScript 文件 | 行数 |
|-------------|---------------------|------|
| tools/base.py | src/Tool.ts | 793 |
| core/streaming.py | src/services/api/claude.ts (部分) | ~300 |
| core/client.py | src/services/api/claude.ts (部分) | ~500 |
| core/tool_orchestrator.py | src/services/tools/StreamingToolExecutor.ts | 530 |
| services/compact_v2.py | src/services/compact/*.ts | ~600 |
| services/hooks.py | src/utils/hooks.ts | 1700+ |
| permissions/rule_engine.py | src/utils/permissions/*.ts | ~900 |
| services/mcp/client.py | src/services/mcp/*.ts | ~800 |
| tools/agent_tool.py | src/tools/AgentTool/*.tsx + forkedAgent.ts | ~1200 |
| buddy/companion.py | src/buddy/companion.ts | 134 |
| buddy/sprites.py | src/buddy/sprites.ts | ~500 |
| buddy/soul.py | src/buddy/prompt.ts | 37 |
| ui/app.py | src/screens/REPL.tsx + src/ink/ | ~4000+ |

---

## 补充模块：配置系统（Config System）

### 原版文件
- src/utils/config.ts（GlobalConfig + ProjectConfig，800+ 行）
- src/utils/settings/settings.ts（Settings 文件读写）
- src/utils/settings/constants.ts（SettingSource 定义）
- src/bootstrap/state.ts（会话级全局单例）

### 关键区分：GlobalConfig vs Settings

⚠️ 原版有两套独立的配置概念，很容易混淆：

| | GlobalConfig | Settings |
|-|-------------|---------|
| 文件 | ~/.claude/config.json | ~/.claude/settings.json 等 |
| 用途 | 用户身份 + 持久偏好 | 行为配置（hooks/permissions/mcpServers）|
| 结构 | 单一 JSON 文件 | 多层合并（5 个来源）|
| 写入 | saveGlobalConfig() | updateSettingsForSource() |
| 典型内容 | userID, oauthAccount, companion, theme | hooks, permissions, env, mcpServers |

### Settings 文件层次结构（5 个来源）

```typescript
// constants.ts
export const SETTING_SOURCES = [
  'userSettings',    // ~/.claude/settings.json（用户级，共享）
  'projectSettings', // .claude/settings.json（项目级，提交到 git）
  'localSettings',   // .claude/settings.local.json（本地覆盖，gitignore）
  'flagSettings',    // --settings /path/to/settings.json（CLI 参数）
  'policySettings',  // managed-settings.json（企业管理员下发）
] as const
```

优先级：**policySettings > flagSettings > localSettings > projectSettings > userSettings**

后加载的来源覆盖前面的值（高优先级赢）。

文件路径映射：
```
userSettings    → ~/.claude/settings.json
projectSettings → {cwd}/.claude/settings.json
localSettings   → {cwd}/.claude/settings.local.json
flagSettings    → 由 --settings 指定的路径
policySettings  → {os_managed_path}/managed-settings.json
```

注：localSettings 是给 .gitignore 的本地覆盖，不应提交到版本控制。

### GlobalConfig 关键字段

```typescript
type GlobalConfig = {
  userID?: string               // 用于 Buddy 生成的种子
  oauthAccount?: AccountInfo    // OAuth 账号信息
  companion?: StoredCompanion   // Buddy 灵魂（name + personality）
  autoCompactEnabled: boolean   // 是否启用自动压缩
  theme: ThemeSetting           // UI 主题
  primaryApiKey?: string        // OAuth 授权后的 API key
  env: Record<string, string>   // 环境变量（@deprecated，用 settings.env）
  mcpServers?: Record<string, McpServerConfig>  // 用户级 MCP 服务器
  numStartups: number           // 启动次数（用于首次体验引导）
  verbose: boolean              // 详细日志
  editorMode?: 'emacs' | 'vim' // 编辑器模式
  bypassPermissionsModeAccepted?: boolean
  showTurnDuration: boolean     // 是否显示每轮耗时
  diffTool?: 'terminal' | 'vscode'
}
```

### bootstrap/state.ts — 会话全局单例

```typescript
// 注释：DO NOT ADD MORE STATE HERE - BE JUDICIOUS WITH GLOBAL STATE
type State = {
  sessionId: SessionId      // UUID，每次启动生成
  originalCwd: string       // 启动时的工作目录（永不改变）
  projectRoot: string       // 项目根目录（worktree 时保持主项目路径）
  cwd: string               // 当前工作目录（worktree 时会变化）
  totalCostUSD: number      // 本次会话累计花费
  modelUsage: {...}         // 各模型 token 用量
  isInteractive: boolean    // 是否交互模式（vs pipe 模式）
  startTime: number         // 会话开始时间戳
  lastInteractionTime: number
  totalLinesAdded: number   // 代码变更统计
  totalLinesRemoved: number
}
```

originalCwd vs cwd vs projectRoot 的区别：
- `originalCwd`：启动时固定，用于解析 settings.json 路径
- `projectRoot`：项目标识，用于历史/会话关联（worktree 时仍指向主仓库）
- `cwd`：当前操作目录，EnterWorktreeTool 后会更新

### Python 实现目标

```python
# config_system/global_config.py
import json
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict

def get_claude_config_dir() -> Path:
    """对应 getClaudeConfigHomeDir()"""
    return Path(os.environ.get('CLAUDE_CONFIG_DIR',
                               Path.home() / '.claude'))

def get_config_file() -> Path:
    return get_claude_config_dir() / 'config.json'

@dataclass
class GlobalConfig:
    user_id: str | None = None
    oauth_account: dict | None = None
    companion: dict | None = None      # StoredCompanion
    auto_compact_enabled: bool = True
    theme: str = 'dark'
    primary_api_key: str | None = None
    num_startups: int = 0
    verbose: bool = False
    show_turn_duration: bool = False

def load_global_config() -> GlobalConfig:
    path = get_config_file()
    if not path.exists():
        return GlobalConfig()
    data = json.loads(path.read_text())
    return GlobalConfig(
        user_id=data.get('userID'),
        oauth_account=data.get('oauthAccount'),
        companion=data.get('companion'),
        auto_compact_enabled=data.get('autoCompactEnabled', True),
        theme=data.get('theme', 'dark'),
        primary_api_key=data.get('primaryApiKey'),
        num_startups=data.get('numStartups', 0),
        verbose=data.get('verbose', False),
        show_turn_duration=data.get('showTurnDuration', False),
    )

def save_global_config(config: GlobalConfig) -> None:
    path = get_config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in asdict(config).items() if v is not None}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

# config_system/settings.py
SETTING_SOURCES = ['userSettings', 'projectSettings', 'localSettings',
                   'flagSettings', 'policySettings']

def get_settings_path(source: str, cwd: str = None) -> Path | None:
    cwd = Path(cwd or os.getcwd())
    match source:
        case 'userSettings':
            return get_claude_config_dir() / 'settings.json'
        case 'projectSettings':
            return cwd / '.claude' / 'settings.json'
        case 'localSettings':
            return cwd / '.claude' / 'settings.local.json'
        case _:
            return None

def load_merged_settings(cwd: str = None) -> dict:
    """按优先级合并所有 settings（低优先级先加载，高优先级覆盖）"""
    merged = {}
    for source in SETTING_SOURCES:
        path = get_settings_path(source, cwd)
        if path and path.exists():
            try:
                data = json.loads(path.read_text())
                deep_merge(merged, data)
            except json.JSONDecodeError:
                pass
    return merged

def deep_merge(base: dict, override: dict) -> dict:
    """深度合并，override 优先"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base
```

---

## 补充模块：State 管理

### 原版两层状态

**层 1：bootstrap/state.ts（模块级单例）**
- 会话粒度的全局变量
- 进程启动时初始化，整个会话共享
- 用 getter/setter 函数访问（非响应式）
- 内容：sessionId, originalCwd, totalCostUSD, modelUsage

**层 2：AppState + Zustand store（React 响应式状态）**
- UI 粒度的响应式状态
- 内容：messages, tools, permissionContext, mcpClients
- 每次更新触发 React re-render
- 子 Agent 有独立的 AppState 副本（或 no-op setter）

```typescript
// AppState 核心字段（src/state/AppState.tsx）
type AppState = {
  messages: Message[]
  tools: Tools
  toolPermissionContext: ToolPermissionContext
  mcpClients: MCPServerConnection[]
  verbose: boolean
  isLoading: boolean
  inProgressToolUseIDs: Set<string>
  hasInterruptibleToolInProgress: boolean
  // ... 更多 UI 状态
}
```

**设计决策**：两层分离的原因：
- bootstrap 状态需要在工具执行、hook、API 调用等非 React 上下文中访问
- AppState 只在 React 组件树中流通，保持 UI 更新的精确性
- 如果把会话统计放进 React state，每次 token 增加都会触发全局重渲染

### Python 对应

```python
# bootstrap/state.py — 模块级单例（对应 bootstrap/state.ts）
import uuid
import time
from dataclasses import dataclass, field

@dataclass
class SessionState:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    original_cwd: str = field(default_factory=lambda: os.getcwd())
    project_root: str = field(default_factory=lambda: os.getcwd())
    cwd: str = field(default_factory=lambda: os.getcwd())
    start_time: float = field(default_factory=time.time)
    total_cost_usd: float = 0.0
    total_lines_added: int = 0
    total_lines_removed: int = 0
    is_interactive: bool = True
    model_usage: dict = field(default_factory=dict)  # model -> {input, output, cost}

# 模块级单例（整个进程共享）
_session: SessionState | None = None

def get_session() -> SessionState:
    global _session
    if _session is None:
        _session = SessionState()
    return _session

def reset_session() -> SessionState:
    global _session
    _session = SessionState()
    return _session
```

---

## 补充模块：Context 构建（System Prompt 组装）

### 原版文件
- src/context.ts（189 行核心，另有大量辅助）

### 系统提示的组成

Claude 收到的 system prompt 由多个部分拼装：

```
1. [固定前缀] CLI sysprompt prefix（版本号、基础指令）
2. [内存文件] ~/.claude/CLAUDE.md（用户全局记忆）
3. [项目文件] 从 cwd 向上遍历的 CLAUDE.md 文件
4. [Git 状态] 当前分支、最近提交、文件变更
5. [时间] 今天的日期
6. [工具列表] 可用工具的描述（通过 prompt() 方法）
7. [Buddy] Companion 介绍文本（如果启用）
```

CLAUDE.md 文件发现规则：
- 从 cwd 开始，向上遍历目录树
- 遇到 .git 目录停止
- 支持 @path/to/other.md 语法引用其他文件（安全验证后内联）
- 路径必须在项目根目录内（防路径遍历）

### Python 实现现状

```python
# my-claude/context.py — 当前实现（已完成基础版）
def build_system_prompt() -> str:
    parts = []
    parts.append(f"Today's date: {datetime.now().strftime('%Y-%m-%d')}")
    parts.append(f"Working directory: {os.getcwd()}")
    
    # CLAUDE.md 文件（已实现）
    claude_md = _find_claude_md_files()
    for path, content in claude_md:
        parts.append(f"# Instructions from {path}\n{content}")
    
    # Git 状态（已实现）
    git_info = _get_git_info()
    if git_info:
        parts.append(git_info)
    
    return "\n\n".join(parts)
```

待补充：
- `@import` 语法支持（内联引用其他 markdown 文件）
- 安全验证（防止引用项目外文件）
- 内存文件（~/.claude/CLAUDE.md）

---

## 实施路线图（最终版）

| 阶段 | 模块 | 状态 | 关键文件 | 原版参考 |
|------|------|------|---------|---------|
| A | SSE 流式输出 + httpx 客户端 | ✅ 已完成 | core/ | claude.ts |
| B | Hook 系统（27事件/4类型）| 待实现 | services/hooks.py | hooks.ts |
| C | 权限规则引擎 | 待实现 | permissions/rule_engine.py | permissions/*.ts |
| D | 工具基类重构 | 待实现 | tools/base.py | Tool.ts |
| E | 压缩策略扩展（micro+降级链）| 待实现 | services/compact_v2.py | compact/*.ts |
| F | 配置系统（GlobalConfig+Settings）| 待实现 | config_system/ | config.ts + settings/ |
| G | Bootstrap State 单例 | 待实现 | bootstrap/state.py | bootstrap/state.ts |
| H | Buddy 系统 | 待实现 | buddy/ | buddy/ |
| I | asyncio 并发工具执行 | 待实现 | core/tool_orchestrator.py | StreamingToolExecutor.ts |
| J | MCP 协议 | 待实现 | services/mcp/ | services/mcp/ |
| K | 多 Agent 协调 | 待实现 | tools/agent_tool.py | AgentTool/ |
| L | Textual TUI（可选）| 可选 | ui/app.py | REPL.tsx + ink/ |
