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


---

## 附录：全仓库能力模块覆盖审计

> 本节基于对原始 TypeScript 代码库的系统性行数审计，补充 PLAN_V2_DEEP.md 尚未覆盖的所有能力模块。

### 覆盖矩阵总览

| 模块目录 | 行数 | 计划覆盖状态 | 优先级 |
|---------|------|------------|-------|
| utils/ | ~181,000 | 部分覆盖（permissions、settings、config 已覆盖）| 高 |
| components/ | ~82,000 | 未覆盖（TUI 阶段 L 简化处理）| 中 |
| tools/ | ~51,000 | 已覆盖（56 个工具，阶段 D）| 高 |
| bridge/ | ~12,622 | **未覆盖**（IDE 集成）| 中 |
| utils/bash/ | ~12,310 | **未覆盖**（Bash AST 安全分析）| 高 |
| screens/ | ~9,000 | 未覆盖（TUI 屏幕层）| 中 |
| utils/swarm/ | ~7,548 | **未覆盖**（Swarm 多 Agent 协调）| 高 |
| services/ | ~6,000+ | 部分覆盖（MCP、compact 已覆盖）| 高 |
| cli/ | ~5,604 | **未覆盖**（SDK/print 模式）| 中 |
| utils/messages.ts | ~5,556 | **未覆盖**（消息格式化核心）| 高 |
| utils/sessionStorage.ts | ~5,106 | **未覆盖**（会话持久化）| 高 |
| skills/ | ~4,080 | **未覆盖**（技能系统）| 高 |
| utils/attachments.ts | ~3,999 | **未覆盖**（附件系统）| 中 |
| tasks/ | ~3,317 | **未覆盖**（7 种后台任务类型）| 高 |
| keybindings/ | ~3,168 | **未覆盖**（按键绑定系统）| 低 |
| services/oauth/ | ~1,077 | **未覆盖**（OAuth 2.0 认证）| 中 |
| services/SessionMemory/ | ~1,026 | **未覆盖**（会话记忆）| 高 |
| coordinator/ | ~373 | **未覆盖**（协调器模式）| 低 |

---

## 补充模块 S1：Bash AST 安全分析系统

**原始路径**：（~12,310 行）

### 核心组成

| 文件 | 功能 |
|------|------|
|  | tree-sitter AST 解析，提取安全相关结构 |
|  | Bash 命令解析器主入口 |
|  | AST 节点类型定义 |
|  | 低层解析原语 |
|  | 命令识别与分类 |
|  | Shell 补全分析 |
|  /  | 引号处理和转义 |
|  | heredoc 语法解析 |
|  /  | 命令前缀分析 |
|  | 命令注册表 |
|  | 核心安全分析 |

### TreeSitterAnalysis 数据结构

{ is a shell keyword

### Python 实现设计

', fully_unquoted):
        compound.has_subshell = True
    if re.search(r'\{[^}]+\}', fully_unquoted):
        compound.has_command_group = True
    
    # Dangerous patterns
    dangerous = DangerousPatterns()
    if re.search(r'\$\(|]+

**实施阶段**：Phase D（工具基类重构）时配套实现，BashTool 的安全验证依赖此模块。


---

## 补充模块 S1：Bash AST 安全分析系统

**原始路径**：`src/utils/bash/`（~12,310 行）

### 核心组成

| 文件 | 功能 |
|------|------|
| `treeSitterAnalysis.ts` | tree-sitter AST 解析，提取安全相关结构 |
| `bashParser.ts` | Bash 命令解析器主入口 |
| `ast.ts` | AST 节点类型定义 |
| `commands.ts` | 命令识别与分类 |
| `shellQuote.ts` / `shellQuoting.ts` | 引号处理和转义 |
| `heredoc.ts` | heredoc 语法解析 |
| `registry.ts` | 命令注册表 |

### 关键数据结构

原版使用 tree-sitter NAPI 原生模块解析 Bash AST，提取三类信息：

1. **QuoteContext**：去除引号内容后的命令文本（三种变体），用于判断命令是否处于安全引号上下文中
2. **CompoundStructure**：复合命令结构（&&、||、;、管道、子shell、命令组）
3. **DangerousPatterns**：危险模式检测（命令替换 `$()`、进程替换 `<()`、参数展开 `${}`、heredoc、注释）

### Python 实现计划

```python
# my-claude/utils/bash_analysis.py
# 纯 Python 正则实现（原版用 tree-sitter NAPI，精度更高）

from dataclasses import dataclass, field

@dataclass
class QuoteContext:
    with_double_quotes: str      # 去除单引号内容
    fully_unquoted: str          # 去除所有引号内容
    unquoted_keep_quote_chars: str

@dataclass
class CompoundStructure:
    has_compound_operators: bool = False  # &&, ||, ;
    has_pipeline: bool = False
    has_subshell: bool = False            # $() 或反引号
    has_command_group: bool = False       # {...}
    operators: list = field(default_factory=list)
    segments: list = field(default_factory=list)

@dataclass
class DangerousPatterns:
    has_command_substitution: bool = False  # $() 或反引号
    has_process_substitution: bool = False  # <() 或 >()
    has_parameter_expansion: bool = False   # ${...}
    has_heredoc: bool = False
    has_comment: bool = False

@dataclass
class BashAnalysis:
    quote_context: QuoteContext
    compound_structure: CompoundStructure
    dangerous_patterns: DangerousPatterns

def analyze_bash_command(cmd: str) -> BashAnalysis:
    """近似实现，用于安全验证。"""
    import re
    uq = re.sub(r"'[^']*'|"[^"]*"", '', cmd)
    quote_ctx = QuoteContext(
        with_double_quotes=re.sub(r"'[^']*'", '', cmd),
        fully_unquoted=uq,
        unquoted_keep_quote_chars=re.sub(r"'[^']*'|"[^"]*"", '""', cmd),
    )
    compound = CompoundStructure(
        has_compound_operators=bool(re.search(r'&&|[|][|]|;', uq)),
        has_pipeline=bool(re.search(r'[|]', uq)),
        has_subshell=bool(re.search(r'[$][(]|`', uq)),
        has_command_group=bool(re.search(r'[{][^}]+[}]', uq)),
    )
    dangerous = DangerousPatterns(
        has_command_substitution=bool(re.search(r'[$][(]|`[^`]+`', uq)),
        has_process_substitution=bool(re.search(r'[<>][(]', uq)),
        has_parameter_expansion=bool(re.search(r'[$][{]', uq)),
        has_heredoc=bool(re.search(r'<<', uq)),
        has_comment=bool(re.search(r'#', uq)),
    )
    return BashAnalysis(quote_ctx, compound, dangerous)
```

**实施阶段**：Phase D（工具基类）时配套实现，供 BashTool 安全验证使用。


---

## 补充模块 S2：Tasks 后台任务系统

**原始路径**：`src/tasks/`（~3,317 行）

### 7 种任务类型

| 类型 | 文件 | 用途 |
|------|------|------|
| `LocalShellTask` | `LocalShellTask/` | 本地 shell 命令后台执行 |
| `LocalAgentTask` | `LocalAgentTask/` | 本地 Claude agent 子任务 |
| `RemoteAgentTask` | `RemoteAgentTask/` | 远程（Bridge）agent 任务 |
| `InProcessTeammateTask` | `InProcessTeammateTask/` | 进程内队友任务（Swarm）|
| `LocalWorkflowTask` | `LocalWorkflowTask/` | 本地工作流任务 |
| `MonitorMcpTask` | `MonitorMcpTask/` | 监控 MCP 服务器任务 |
| `DreamTask` | `DreamTask/` | Dream 模式任务（feature flag 关闭）|

### 任务状态机

```typescript
// 原版 types.ts
type TaskState =
  | LocalShellTaskState
  | LocalAgentTaskState
  | RemoteAgentTaskState
  | InProcessTeammateTaskState
  | LocalWorkflowTaskState
  | MonitorMcpTaskState
  | DreamTaskState

// 后台任务判断条件：
// 1. status === 'running' 或 'pending'
// 2. isBackgrounded !== false
function isBackgroundTask(task: TaskState): boolean
```

### Python 实现设计

```python
# my-claude/tasks/types.py
from enum import Enum
from dataclasses import dataclass
from typing import Literal, Union

class TaskStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    DONE = 'done'
    ERROR = 'error'
    CANCELLED = 'cancelled'

@dataclass
class BaseTaskState:
    task_id: str
    status: TaskStatus
    is_backgrounded: bool = True
    created_at: float = 0.0

@dataclass
class LocalShellTaskState(BaseTaskState):
    type: Literal['local_shell'] = 'local_shell'
    command: str = ''
    pid: int | None = None
    output: str = ''
    exit_code: int | None = None

@dataclass
class LocalAgentTaskState(BaseTaskState):
    type: Literal['local_agent'] = 'local_agent'
    prompt: str = ''
    session_id: str = ''
    messages: list = None

TaskState = Union[
    LocalShellTaskState,
    LocalAgentTaskState,
    # ... 其他类型
]

def is_background_task(task: BaseTaskState) -> bool:
    if task.status not in (TaskStatus.RUNNING, TaskStatus.PENDING):
        return False
    if hasattr(task, 'is_backgrounded') and task.is_backgrounded is False:
        return False
    return True
```

**实施阶段**：Phase K（多 Agent 协调）时实现基础任务类型，Swarm 阶段扩展 InProcessTeammateTask。

---

## 补充模块 S3：Skills 技能系统

**原始路径**：`src/skills/`（~4,080 行）

### 核心概念

Skills（技能）是用户自定义的斜杠命令（slash commands），以 Markdown 文件形式存储：

- **存储位置**：
  - `~/.claude/skills/` — 用户全局技能
  - `<project>/.claude/skills/` — 项目级技能
  - Plugin 提供的技能
  - MCP 服务器注册的技能
  - 内置（bundled）技能

- **文件格式**：Markdown 文件，支持 frontmatter：

```markdown
---
description: 执行 git commit 并推送
allowed-tools: Bash
argument-hint: <message>
model: claude-opus-4-5
effort: high
---
执行以下操作：
1. git add -A
2. git commit -m "$ARGUMENTS"  
3. git push
```

### Frontmatter 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | string | 命令描述 |
| `allowed-tools` | string/list | 允许使用的工具列表 |
| `argument-hint` | string | 参数提示（显示在补全中）|
| `model` | string | 覆盖默认模型 |
| `effort` | low/medium/high | 努力等级（影响 token budget）|
| `shell` | string | 执行 shell（bash/zsh 等）|

### LoadedFrom 来源标识

```typescript
type LoadedFrom =
  | 'commands_DEPRECATED'  // 旧版 commands/ 目录
  | 'skills'               // 新版 skills/ 目录
  | 'plugin'               // 插件提供
  | 'managed'              // 管理员策略
  | 'bundled'              // 内置技能
  | 'mcp'                  // MCP 服务器注册
```

### Python 实现设计

```python
# my-claude/skills/loader.py
from pathlib import Path
from dataclasses import dataclass
import yaml, re

@dataclass
class SkillFrontmatter:
    description: str = ''
    allowed_tools: list[str] = None
    argument_hint: str = ''
    model: str | None = None
    effort: str = 'medium'  # low/medium/high
    shell: str = 'bash'

@dataclass
class LoadedSkill:
    name: str           # 斜杠命令名（文件名去掉 .md）
    content: str        # Markdown 主体内容
    frontmatter: SkillFrontmatter
    loaded_from: str    # 'skills'/'bundled'/'plugin'/'mcp'
    source_path: Path

def load_skills_dir(directory: Path, loaded_from: str = 'skills') -> list[LoadedSkill]:
    skills = []
    for md_file in sorted(directory.glob('**/*.md')):
        name = md_file.stem
        text = md_file.read_text(encoding='utf-8')
        fm, body = parse_frontmatter(text)
        skills.append(LoadedSkill(
            name=name,
            content=body,
            frontmatter=fm,
            loaded_from=loaded_from,
            source_path=md_file,
        ))
    return skills

def get_skills_paths() -> list[tuple[Path, str]]:
    """返回所有技能目录及其来源标识。"""
    import os
    home = Path.home()
    cwd = Path.cwd()
    paths = []
    # 用户全局
    paths.append((home / '.claude' / 'skills', 'skills'))
    # 项目级（从 cwd 到 home）
    for d in [cwd] + list(cwd.parents):
        p = d / '.claude' / 'skills'
        if p.exists():
            paths.append((p, 'skills'))
        if d == home:
            break
    return paths
```

**实施阶段**：Phase F（配置系统）时实现基础加载，Phase L（TUI）时集成到斜杠命令补全。


---

## 补充模块 S4：Session Memory 会话记忆

**原始路径**：`src/services/SessionMemory/`（~1,026 行）

### 功能概述

Session Memory 是一个持久化的会话笔记系统：
- 在会话结束时，由模型自动更新会话摘要文件
- 文件路径：`~/.claude/session_memory/<session_id>.md`
- 在新会话开始时，将摘要注入到系统提示中，实现跨会话记忆

### 关键常量

```typescript
// src/services/SessionMemory/sessionMemory.ts
const MAX_SECTION_LENGTH = 2000        // 每个 section 最大 token 数
const MAX_TOTAL_SESSION_MEMORY_TOKENS = 12000  // 总会话记忆最大 token 数
```

### 会话记忆模板

原版有 10 个固定 section（不可增删）：

1. **Session Title** — 5-10 词的描述性标题
2. **Current State** — 当前正在做什么，待完成的任务
3. **Task specification** — 用户要求构建什么
4. **Files and Functions** — 重要文件及其作用
5. **Workflow** — 常用 bash 命令及执行顺序
6. **Errors & Corrections** — 遇到的错误及修复方法
7. **Codebase and System Documentation** — 系统组件说明
8. **Learnings** — 什么有效，什么无效
9. **Key results** — 用户要求的具体输出结果
10. **Worklog** — 逐步操作记录（简洁）

### 更新机制

```typescript
// 会话结束时，发送一条特殊消息给模型：
// "Based on the user conversation above, update the session notes file."
// 模型调用 Edit 工具更新笔记文件，然后停止
// 更新规则：
// - 只更新每个 section 的内容，不修改 header 和斜体描述行
// - section 接近 MAX_SECTION_LENGTH 时，精简旧内容
// - 并行调用多个 Edit 工具更新多个 section
```

### Python 实现设计

```python
# my-claude/services/session_memory.py
from pathlib import Path
from dataclasses import dataclass

MAX_SECTION_LENGTH = 2000
MAX_TOTAL_SESSION_MEMORY_TOKENS = 12000

SESSION_MEMORY_TEMPLATE = """# Session Title
_A short and distinctive 5-10 word descriptive title_

# Current State
_What is actively being worked on right now?_

# Task specification
_What did the user ask to build?_

# Files and Functions
_What are the important files and why are they relevant?_

# Workflow
_What bash commands are usually run and in what order?_

# Errors & Corrections
_Errors encountered and how they were fixed._

# Codebase and System Documentation
_What are the important system components?_

# Learnings
_What has worked well? What has not?_

# Key results
_Exact output the user requested._

# Worklog
_Step by step, what was attempted, done?_
"""

def get_session_memory_path(session_id: str) -> Path:
    home = Path.home()
    return home / '.claude' / 'session_memory' / f'{session_id}.md'

def load_session_memory(session_id: str) -> str | None:
    path = get_session_memory_path(session_id)
    if path.exists():
        return path.read_text(encoding='utf-8')
    return None

def init_session_memory(session_id: str) -> Path:
    path = get_session_memory_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(SESSION_MEMORY_TEMPLATE, encoding='utf-8')
    return path

def build_memory_update_prompt(notes_path: Path, current_notes: str) -> str:
    return (
        f"Based on the conversation above, update the session notes file.\n"
        f"File: {notes_path}\n"
        f"Current contents:\n{current_notes}\n\n"
        f"Use the Edit tool to update relevant sections. "
        f"Preserve all section headers and italic description lines exactly. "
        f"Only update content below each italic description."
    )
```

**实施阶段**：Phase G（Bootstrap State）完成后实现，作为跨会话记忆的核心基础设施。

---

## 补充模块 S5：Session Storage 会话持久化

**原始路径**：`src/utils/sessionStorage.ts`（~5,106 行）

### 功能概述

会话持久化系统负责将完整的对话历史序列化到磁盘，支持会话恢复：

- **存储路径**：`~/.claude/sessions/<session_id>.json`（或 `.jsonl`）
- **格式**：每行一个 JSON 对象（JSONL 格式），流式追加写入
- **内容**：完整消息历史 + 元数据（token 用量、成本、工具调用结果）

### 关键功能

```typescript
// 核心 API（原版 sessionStorage.ts）
async function saveSessionMessage(sessionId: string, message: Message): Promise<void>
async function loadSession(sessionId: string): Promise<Message[]>
async function listSessions(): Promise<SessionSummary[]>
async function deleteSession(sessionId: string): Promise<void>
async function getSessionPath(sessionId: string): string
```

### Python 实现设计

```python
# my-claude/utils/session_storage.py
import json
from pathlib import Path
from datetime import datetime

def get_sessions_dir() -> Path:
    return Path.home() / '.claude' / 'sessions'

def get_session_path(session_id: str) -> Path:
    return get_sessions_dir() / f'{session_id}.jsonl'

def save_message(session_id: str, message: dict) -> None:
    path = get_session_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(message, ensure_ascii=False) + '\n')

def load_session(session_id: str) -> list[dict]:
    path = get_session_path(session_id)
    if not path.exists():
        return []
    messages = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(json.loads(line))
    return messages

def list_sessions() -> list[dict]:
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        return []
    result = []
    for p in sorted(sessions_dir.glob('*.jsonl'), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = p.stat()
        result.append({
            'session_id': p.stem,
            'path': str(p),
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return result
```

**实施阶段**：Phase G（Bootstrap State）时同步实现，用于支持 `--resume` 会话恢复功能。


---

## 补充模块 S6：Swarm 多 Agent 协调系统

**原始路径**：`src/utils/swarm/`（~7,548 行）

### 核心概念

Swarm 是基于 tmux 的多 Claude 实例协调系统，允许一个 team-lead 实例控制多个 teammate 实例并行工作：

- **team-lead**：协调者，分配任务给各 teammate
- **teammate**：工作者，各自在独立 tmux pane 中运行
- **通信**：通过 tmux 的 send-keys 机制传递消息

### 关键常量

```typescript
// src/utils/swarm/constants.ts
const TEAM_LEAD_NAME = 'team-lead'
const SWARM_SESSION_NAME = 'claude-swarm'
const SWARM_VIEW_WINDOW_NAME = 'swarm-view'
const TMUX_COMMAND = 'tmux'
const HIDDEN_SESSION_NAME = 'claude-hidden'

// 环境变量
const TEAMMATE_COMMAND_ENV_VAR = 'CLAUDE_CODE_TEAMMATE_COMMAND'
const TEAMMATE_COLOR_ENV_VAR = 'CLAUDE_CODE_AGENT_COLOR'
const PLAN_MODE_REQUIRED_ENV_VAR = 'CLAUDE_CODE_PLAN_MODE_REQUIRED'

function getSwarmSocketName(): string {
  return `claude-swarm-${process.pid}`  // 每个进程独立 socket
}
```

### 模块组成

| 文件 | 功能 |
|------|------|
| `constants.ts` | Swarm 常量和环境变量 |
| `backends/` | 后端实现（local tmux、remote 等）|
| `inProcessRunner.ts` | 进程内运行器（InProcessTeammateTask）|
| `leaderPermissionBridge.ts` | team-lead 权限桥接 |
| `permissionSync.ts` | 权限同步机制 |
| `reconnection.ts` | 断线重连逻辑 |
| `spawnInProcess.ts` | 进程内 spawn |
| `spawnUtils.ts` | spawn 工具函数 |
| `teamHelpers.ts` | 团队辅助函数 |
| `teammateInit.ts` | teammate 初始化 |
| `teammateLayoutManager.ts` | tmux 布局管理 |
| `teammateModel.ts` | teammate 状态模型 |
| `teammatePromptAddendum.ts` | teammate 提示词附录 |
| `It2SetupPrompt.tsx` | iTerm2 配置提示 |

### Python 实现设计（简化版）

```python
# my-claude/utils/swarm/manager.py
import subprocess
import os
from dataclasses import dataclass

TEAM_LEAD_NAME = 'team-lead'
SWARM_SESSION_NAME = 'claude-swarm'
TEAMMATE_COLOR_ENV_VAR = 'CLAUDE_CODE_AGENT_COLOR'
PLAN_MODE_REQUIRED_ENV_VAR = 'CLAUDE_CODE_PLAN_MODE_REQUIRED'

# 预设颜色（每个 teammate 一种）
TEAMMATE_COLORS = ['blue', 'green', 'yellow', 'magenta', 'cyan', 'red']

@dataclass
class TeammateConfig:
    name: str
    color: str
    plan_mode_required: bool = False
    prompt: str = ''
    worktree: str | None = None

class SwarmManager:
    """
    基于 tmux 的 Swarm 协调器（简化实现）。
    完整实现需要 tmux 进程管理 + send-keys 通信。
    """
    def __init__(self, session_name: str = SWARM_SESSION_NAME):
        self.session_name = session_name
        self.teammates: dict[str, TeammateConfig] = {}
    
    def _tmux(self, *args: str) -> str:
        result = subprocess.run(
            ['tmux', *args],
            capture_output=True, text=True
        )
        return result.stdout.strip()
    
    def create_session(self) -> None:
        self._tmux('new-session', '-d', '-s', self.session_name)
    
    def spawn_teammate(self, config: TeammateConfig) -> None:
        env = {**os.environ, TEAMMATE_COLOR_ENV_VAR: config.color}
        if config.plan_mode_required:
            env[PLAN_MODE_REQUIRED_ENV_VAR] = 'true'
        # 创建新 pane 并启动 Claude
        self._tmux('split-window', '-t', self.session_name, '-h')
        self.teammates[config.name] = config
    
    def send_to_teammate(self, name: str, message: str) -> None:
        # 通过 tmux send-keys 发送消息
        self._tmux('send-keys', '-t', f'{self.session_name}:{name}', message, 'Enter')
    
    def is_swarm_available(self) -> bool:
        try:
            subprocess.run(['tmux', '-V'], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
```

**实施阶段**：Phase K（多 Agent 协调）的扩展部分，依赖 InProcessTeammateTask 先完成。注意：原版 Swarm 使用 tmux，Python 版本可以基于 asyncio 子进程实现更简洁的替代方案。

---

## 补充模块 S7：Bridge IDE 集成

**原始路径**：`src/bridge/`（~12,622 行）

### 功能概述

Bridge 是 Claude Code 与 IDE（VSCode、JetBrains）的通信层，支持：
- 远程会话管理（通过 Bridge API）
- JWT token 刷新调度
- 会话 spawn/kill/poll
- 可信设备认证
- 容量感知唤醒（capacityWake）

### 关键模块

| 文件 | 功能 |
|------|------|
| `bridgeMain.ts` | Bridge 主循环，会话生命周期管理 |
| `bridgeApi.ts` | Bridge API 客户端（HTTP）|
| `bridgeUI.ts` | Bridge 日志/UI 适配器 |
| `bridgeStatusUtil.ts` | 状态格式化工具 |
| `capacityWake.ts` | 容量感知唤醒（server busy 时重试）|
| `debugUtils.ts` | 调试工具（Axios 错误描述）|
| `jwtUtils.ts` | JWT token 刷新调度器 |
| `pollConfig.ts` | 轮询间隔配置 |
| `sessionIdCompat.ts` | 会话 ID 格式兼容性转换 |
| `sessionRunner.ts` | 会话 spawn 实现 |
| `trustedDevice.ts` | 可信设备 token 管理 |
| `types.ts` | Bridge 类型定义 |

### Python 实现优先级

Bridge 是 IDE 集成功能，纯 CLI 版本的 Python 重写可以**跳过**此模块。如需实现 VSCode 扩展集成，参考原版 API 协议即可。

**实施阶段**：可选 Phase M（IDE 集成），不影响核心功能。


---

## 补充模块 S8：OAuth 2.0 认证

**原始路径**：`src/services/oauth/`（~1,077 行）

### 功能概述

OAuth 2.0 认证流程，用于通过浏览器登录 Anthropic 账户：

### 关键文件

| 文件 | 功能 |
|------|------|
| `index.ts` | OAuth 主入口，发起授权流程 |
| `client.ts` | OAuth HTTP 客户端 |
| `auth-code-listener.ts` | 本地 HTTP 服务器，监听授权码回调 |
| `crypto.ts` | PKCE 加密工具（code_verifier/challenge）|
| `types.ts` | OAuth 类型定义 |
| `getOauthProfile.ts` | 获取用户 profile 信息 |

### PKCE 流程

```
1. 生成 code_verifier (随机 32 字节 base64url)
2. 计算 code_challenge = SHA256(code_verifier) base64url
3. 启动本地 HTTP server 监听 redirect_uri（如 http://localhost:8080/callback）
4. 打开浏览器：{auth_url}?response_type=code&client_id=...&code_challenge=...
5. 用户授权后，浏览器回调到本地 server，携带 authorization_code
6. 用 code + code_verifier 换取 access_token + refresh_token
7. 保存 token 到 ~/.claude/credentials.json
```

### Python 实现设计

```python
# my-claude/services/oauth.py
import hashlib, secrets, base64, json
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, parse_qs, urlparse

CREDENTIALS_PATH = Path.home() / '.claude' / 'credentials.json'

def generate_pkce() -> tuple[str, str]:
    """返回 (code_verifier, code_challenge)。"""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b'=').decode()
    return verifier, challenge

def save_credentials(token_data: dict) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(token_data, indent=2))
    CREDENTIALS_PATH.chmod(0o600)

def load_credentials() -> dict | None:
    if CREDENTIALS_PATH.exists():
        return json.loads(CREDENTIALS_PATH.read_text())
    return None
```

**实施阶段**：Phase F（配置系统）时实现凭证加载，完整 OAuth 流程可作为可选 Phase M 实现。

---

## 补充模块 S9：消息格式化核心

**原始路径**：`src/utils/messages.ts`（~5,556 行）

### 功能概述

消息格式化是 Claude Code 的核心基础设施，处理所有消息类型的序列化、转换和展示：

### 主要功能

1. **API 消息构造**：将内部消息格式转换为 Anthropic API 格式
2. **消息规范化**：处理 tool_use、tool_result、text 等内容块
3. **Token 估算**：`roughTokenCountEstimation(text: string): number` — 用 `text.length / 4` 粗估 token 数
4. **消息截断**：超出上下文窗口时截断旧消息
5. **内容块合并**：将连续的相同类型内容块合并

### 关键函数

```typescript
// 原版核心函数（messages.ts）
function getTokenCountFromMessages(messages: Message[]): number
function truncateMessages(messages: Message[], maxTokens: number): Message[]
function normalizeMessages(messages: Message[]): Message[]  
function roughTokenCountEstimation(text: string): number
  // 实现：return Math.ceil(text.length / 4)

// 消息类型转换
function userMessageToApiFormat(msg: UserMessage): APIUserMessage
function assistantMessageToApiFormat(msg: AssistantMessage): APIAssistantMessage
```

### Python 实现设计

```python
# my-claude/utils/messages.py
import math
from typing import Any

def rough_token_count(text: str) -> int:
    """粗略估算 token 数，使用 length/4 近似。"""
    return math.ceil(len(text) / 4)

def normalize_messages(messages: list[dict]) -> list[dict]:
    """规范化消息列表，合并连续相同角色的消息。"""
    if not messages:
        return []
    result = []
    for msg in messages:
        if result and result[-1]['role'] == msg['role']:
            # 合并内容
            prev = result[-1]
            if isinstance(prev['content'], str):
                prev['content'] = [{'type': 'text', 'text': prev['content']}]
            if isinstance(msg['content'], str):
                extra = [{'type': 'text', 'text': msg['content']}]
            else:
                extra = msg['content']
            prev['content'].extend(extra)
        else:
            result.append(dict(msg))
    return result

def get_message_token_count(messages: list[dict]) -> int:
    """估算消息列表总 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get('content', '')
        if isinstance(content, str):
            total += rough_token_count(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += rough_token_count(str(block.get('text', '') or block.get('input', '')))
    return total

def truncate_messages(messages: list[dict], max_tokens: int) -> list[dict]:
    """从最旧的消息开始删除，直到总 token 数在限制内。"""
    while messages and get_message_token_count(messages) > max_tokens:
        messages = messages[1:]  # 删除最旧消息
    return messages
```

**实施阶段**：Phase A 完成后即可实现（已在 core/query.py 中有基础版本），Phase E（压缩策略）时需要完整版本。

---

## 补充模块 S10：附件系统

**原始路径**：`src/utils/attachments.ts`（~3,999 行）

### 功能概述

附件系统处理用户粘贴或拖拽的文件内容，支持：
- **图片**：base64 编码后作为 image content block 发送
- **文本文件**：直接嵌入为 text content block
- **PDF**：base64 编码（API 支持直接处理 PDF）

### Python 实现设计

```python
# my-claude/utils/attachments.py
import base64, mimetypes
from pathlib import Path

SUPPORTED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
SUPPORTED_DOC_TYPES = {'application/pdf'}

def file_to_content_block(path: Path) -> dict:
    """将文件转换为 Anthropic API content block。"""
    mime, _ = mimetypes.guess_type(str(path))
    data = path.read_bytes()
    
    if mime in SUPPORTED_IMAGE_TYPES:
        return {
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': mime,
                'data': base64.standard_b64encode(data).decode(),
            }
        }
    elif mime in SUPPORTED_DOC_TYPES:
        return {
            'type': 'document',
            'source': {
                'type': 'base64',
                'media_type': mime,
                'data': base64.standard_b64encode(data).decode(),
            }
        }
    else:
        # 文本文件
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = data.decode('latin-1')
        return {'type': 'text', 'text': f'<file path="{path.name}">\n{text}\n</file>'}
```

**实施阶段**：Phase L（TUI）时实现，用于支持文件拖拽和粘贴功能。


---

## 补充模块 S11：消息格式化与打印模式

**原始路径**：`src/cli/print.ts`（~5,604 行）

### 功能概述

`print.ts` 是非交互式（SDK/pipe）模式的输出处理器，与 REPL 的 React/Ink 组件平行：

- **pipe 模式**（`echo "..." | claude -p`）：流式输出到 stdout
- **SDK 模式**：程序化调用时的输出格式
- **JSON 输出**（`--output-format json`）：结构化 JSON 输出
- **stream-JSON 输出**：每个事件一行 JSON

### 输出格式

```bash
# text 格式（默认）
$ echo "hello" | claude -p
Hello! How can I help you?

# json 格式
$ echo "hello" | claude -p --output-format json
{"type":"result","subtype":"success","result":"Hello!","session_id":"...","cost_usd":0.001}

# stream-json 格式
$ echo "hello" | claude -p --output-format stream-json
{"type":"assistant","message":{"role":"assistant","content":[...]}}
{"type":"result","subtype":"success","result":"..."}
```

### Python 实现设计

```python
# my-claude/cli/print_mode.py
import json, sys
from dataclasses import dataclass
from typing import Literal

OutputFormat = Literal['text', 'json', 'stream-json']

@dataclass
class PrintModeConfig:
    output_format: OutputFormat = 'text'
    verbose: bool = False
    max_turns: int = 10

class PrintModeOutput:
    def __init__(self, config: PrintModeConfig):
        self.config = config
        self._text_buffer = []
    
    def on_text_delta(self, text: str) -> None:
        if self.config.output_format == 'text':
            sys.stdout.write(text)
            sys.stdout.flush()
        elif self.config.output_format == 'stream-json':
            print(json.dumps({'type': 'text_delta', 'text': text}))
    
    def on_turn_complete(self, message: dict) -> None:
        if self.config.output_format == 'stream-json':
            print(json.dumps({'type': 'assistant', 'message': message}))
    
    def on_done(self, result_text: str, session_id: str, cost_usd: float) -> None:
        if self.config.output_format == 'text':
            pass  # 已经流式输出
        elif self.config.output_format == 'json':
            print(json.dumps({
                'type': 'result',
                'subtype': 'success',
                'result': result_text,
                'session_id': session_id,
                'cost_usd': cost_usd,
            }))
        elif self.config.output_format == 'stream-json':
            print(json.dumps({
                'type': 'result',
                'subtype': 'success',
                'result': result_text,
                'session_id': session_id,
                'cost_usd': cost_usd,
            }))
```

**实施阶段**：Phase A 完成后可立即实现，是 pipe 模式的核心输出层。

---

## 补充模块 S12：更新后的实施路线图

在原有 A-L 12 个阶段基础上，补充以下阶段：

### 完整路线图（修订版）

| 阶段 | 模块 | 状态 | 关键文件 | 原版参考 | 优先级 |
|------|------|------|---------|---------|--------|
| A | SSE 流式输出 + httpx 客户端 | ✅ 已完成 | core/ | claude.ts | 核心 |
| B | Hook 系统（27事件/4类型）| 待实现 | services/hooks.py | hooks.ts | 高 |
| C | 权限规则引擎 | 待实现 | permissions/rule_engine.py | permissions/*.ts | 高 |
| D | 工具基类重构 + Bash AST | 待实现 | tools/base.py, utils/bash_analysis.py | Tool.ts, utils/bash/ | 高 |
| E | 压缩策略扩展（micro+降级链）| 待实现 | services/compact_v2.py | compact/*.ts | 高 |
| F | 配置系统（GlobalConfig+Settings+Skills）| 待实现 | config_system/, skills/ | config.ts + settings/ + skills/ | 高 |
| G | Bootstrap State + Session Storage + Session Memory | 待实现 | bootstrap/state.py, session_storage.py, session_memory.py | bootstrap/state.ts | 高 |
| H | Buddy 系统 | 待实现 | buddy/ | buddy/ | 低 |
| I | asyncio 并发工具执行 | 待实现 | core/tool_orchestrator.py | StreamingToolExecutor.ts | 高 |
| J | MCP 协议 | 待实现 | services/mcp/ | services/mcp/ | 中 |
| K | 多 Agent 协调 + Tasks | 待实现 | tools/agent_tool.py, tasks/ | AgentTool/, tasks/ | 中 |
| L | Textual TUI + 附件 + 打印模式 | 可选 | ui/app.py, cli/print_mode.py | REPL.tsx + cli/print.ts | 中 |
| M | 消息格式化核心（messages.py）| 待实现 | utils/messages.py | utils/messages.ts | 高 |
| N | Swarm 多 Agent 协调 | 可选 | utils/swarm/ | utils/swarm/ | 低 |
| O | OAuth 认证 | 可选 | services/oauth.py | services/oauth/ | 低 |
| P | IDE Bridge 集成 | 可选 | bridge/ | bridge/ | 低 |

### 实际最小可行版本（MVP）所需阶段

按优先级排序，实现完整 CLI 功能最少需要：

1. **A**（已完成）→ **M**（消息格式化）→ **G**（状态+存储）→ **F**（配置）
2. → **C**（权限）→ **D**（工具基类+Bash AST）→ **B**（Hook）
3. → **I**（并发执行）→ **E**（压缩）→ **L**（TUI 或 print 模式）

其余阶段（H/J/K/N/O/P）为可选增强功能。

---

## 模块覆盖完成度总结

| 类别 | 原版代码量 | 本计划覆盖 | 完成度 |
|------|-----------|-----------|--------|
| 核心 API + 流式 | ~3,000 行 | A 阶段 | ✅ 100% |
| 工具系统（56个工具）| ~51,000 行 | D 阶段 | 规划完整 |
| Hook 系统 | ~5,121 行 | B 阶段 | 规划完整 |
| 权限系统 | ~3,000 行 | C 阶段 | 规划完整 |
| 压缩系统 | ~8,000 行 | E 阶段 | 规划完整（snip为stub）|
| 配置+Settings | ~10,000 行 | F 阶段 | 规划完整 |
| Bootstrap State | ~2,000 行 | G 阶段 | 规划完整 |
| Session Storage | ~5,106 行 | G/S5 阶段 | 规划完整 |
| Session Memory | ~1,026 行 | G/S4 阶段 | 规划完整 |
| Bash AST 安全分析 | ~12,310 行 | D/S1 阶段 | 规划完整 |
| Skills 技能系统 | ~4,080 行 | F/S3 阶段 | 规划完整 |
| Tasks 任务系统 | ~3,317 行 | K/S2 阶段 | 规划完整 |
| MCP 协议 | ~6,000 行 | J 阶段 | 规划完整 |
| 多 Agent/AgentTool | ~8,000 行 | K 阶段 | 规划完整 |
| Swarm 协调 | ~7,548 行 | N/S6 阶段 | 规划（可选）|
| Bridge IDE 集成 | ~12,622 行 | P/S7 阶段 | 规划（可选）|
| Buddy 系统 | ~3,000 行 | H 阶段 | 规划完整 |
| TUI/UI 层 | ~82,000 行 | L 阶段 | 规划（简化）|
| 消息格式化 | ~5,556 行 | M/S9 阶段 | 规划完整 |
| OAuth 认证 | ~1,077 行 | O/S8 阶段 | 规划（可选）|
| 附件系统 | ~3,999 行 | L/S10 阶段 | 规划完整 |
| CLI/打印模式 | ~5,604 行 | L/S11 阶段 | 规划完整 |
| **总计** | **~150,000 行** | **全部覆盖** | **规划完成** |

