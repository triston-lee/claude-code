# my-claude 2.0 开发计划

架构师视角的深度研究计划。每个模块分三层：
- **研究**：原版对应文件
- **理解**：核心架构决策
- **实现**：Python 复现

---

## 模块一：工具系统架构（Tool System Design）

**原版文件**
- `src/Tool.ts` — Tool 接口定义
- `src/tools/BashTool/BashTool.ts` — 典型工具实现
- `src/tools/GlobTool/GlobTool.ts` — buildTool() 模式
- `src/tools.ts` — 工具注册表

**核心设计决策**

原版工具不是简单函数，而是一个完整对象，包含：

```typescript
buildTool({
  name, description,
  inputSchema,        // JSON Schema 校验输入
  outputSchema,       // 输出结构定义
  isReadOnly(),       // 是否只读（影响权限）
  isConcurrencySafe(),// 是否支持并发
  isSearchOrReadCommand(), // 分类（影响自动权限）
  checkPermissions(), // 权限检查（与权限系统解耦）
  validateInput(),    // 前置校验（不触发 API 调用）
  call(),             // 实际执行
  renderToolUseMessage(),  // 终端渲染（与逻辑解耦）
  mapToolResultToToolResultBlockParam(), // 序列化给 API
})
```

**架构亮点**：工具是自描述的——它知道自己是否安全、如何渲染、如何验证。
相比 my-claude v1 中工具只是一个带 `fn` 字段的 dict，这是一个完整的 Plugin 架构。

**Python 实现目标**
```
tools/
└── base.py     # 工具基类（dataclass + Protocol）
    # 包含：is_read_only, is_concurrency_safe,
    #       validate_input, check_permissions,
    #       render_result
```

---

## 模块二：流式响应 + 并发工具执行

**原版文件**
- `src/services/tools/StreamingToolExecutor.ts`
- `src/services/tools/toolOrchestration.ts`
- `src/query.ts` — 流式循环主体

**核心设计决策**

原版有两种工具执行模式：

```
普通模式（v1 实现）：
  Claude 输出完整 → 解析 tool_use → 执行 → 返回结果

流式并发模式（StreamingToolExecutor）：
  Claude 开始流式输出
    → 遇到 tool_use block 开始
    → 不等 Claude 输出完，立即开始执行工具
    → Claude 输出完毕时工具可能已经执行完了
    → 极大减少延迟
```

这是一个生产者-消费者模型：
- Claude SSE 流是生产者
- 工具执行是消费者，提前消费

**Python 实现目标**
```python
# 用 asyncio 实现：
async def stream_and_execute(response_stream, tools):
    tasks = {}
    async for event in response_stream:
        if event.type == "content_block_start" and event.content_block.type == "tool_use":
            # 立即开始执行，不等流结束
            tasks[event.index] = asyncio.create_task(execute_tool(...))
        elif event.type == "content_block_delta":
            # 打印文字输出
            print(event.delta.text, end="", flush=True)
    results = await asyncio.gather(*tasks.values())
```

---

## 模块三：Context Window 管理三策略

**原版文件**
- `src/services/compact/autoCompact.ts` — 触发决策
- `src/services/compact/compact.ts` — 标准压缩
- `src/services/compact/microCompact.ts` — 微压缩
- `src/services/compact/reactiveCompact.ts` — 响应式压缩（feature flag）
- `src/services/compact/snipCompact.ts` — 裁剪压缩

**三种策略对比**

| 策略 | 触发时机 | 方式 | 保真度 |
|------|---------|------|--------|
| Auto Compact | 主动，token 达到 95% | 调用 Claude 生成摘要 | 低（有损） |
| Micro Compact | 主动，更细粒度 | 只压缩 tool_result，保留对话结构 | 中 |
| Snip Compact | 主动，最激进 | 直接删除旧消息 | 最低 |
| Reactive Compact | 被动，API 返回 413 | 出错后再压缩 | - |

**架构亮点**：降级策略链。先尝试 micro-compact，失败再 auto-compact，
再失败再 snip，形成一个完整的容错降级链。

**Python 实现目标**
```python
# services/compact.py 扩展
def compact_with_fallback(client, messages, strategy="auto"):
    strategies = [micro_compact, auto_compact, snip_compact]
    for strategy_fn in strategies:
        try:
            return strategy_fn(client, messages)
        except ContextTooLongError:
            continue
    raise RuntimeError("All compaction strategies failed")
```

---

## 模块四：Hook 系统（AOP 设计）

**原版文件**
- `src/utils/hooks.ts` — hook 执行器
- `src/utils/hooks/postSamplingHooks.ts` — 采样后 hook
- `~/.claude/settings.json` — hook 配置

**核心设计决策**

Hook 是 AOP（面向切面编程）的实践：用户通过配置文件注入行为，无需修改核心代码。

```json
// ~/.claude/settings.json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "bash",
      "hooks": [{"type": "command", "command": "echo 'about to run bash'"}]
    }],
    "PostToolUse": [{
      "matcher": "file_edit",
      "hooks": [{"type": "command", "command": "git add -A"}]
    }],
    "Stop": [{
      "hooks": [{"type": "command", "command": "notify-send 'Claude done'"}]
    }]
  }
}
```

Hook 生命周期：
```
PreToolUse  → 工具执行 → PostToolUse
                              ↓
                         PostSampling（每次 Claude 回复后）
                              ↓
                           Stop（对话结束）
```

**Python 实现目标**
```python
# services/hooks.py
class HookExecutor:
    def run_pre_tool(self, tool_name, tool_input) -> bool:  # False = 阻止执行
    def run_post_tool(self, tool_name, tool_input, result)
    def run_post_sampling(self, messages)
    def run_stop(self)
```

---

## 模块五：MCP（Model Context Protocol）

**原版文件**
- `src/services/mcp/` — MCP 连接管理
- `src/tools/MCPTool/` — MCP 工具包装
- `src/utils/mcp.ts`

**核心设计决策**

MCP 是一个标准化协议，让外部服务（数据库、Slack、GitHub 等）以统一接口接入工具系统。

架构分层：
```
Claude API
    ↓
工具调用系统
    ↓
MCPTool（统一适配器）
    ↓
MCP Client（管理连接池）
    ↓
MCP Server（外部进程，stdio/HTTP）
    ↓
实际服务（DB/GitHub/Slack...）
```

**核心挑战**：MCP Server 是独立进程，需要进程生命周期管理、连接重试、超时控制。

**Python 实现目标**
```python
# services/mcp/client.py
class MCPClient:
    def connect(self, server_config: dict)  # stdio / HTTP
    def list_tools(self) -> list[Tool]
    def call_tool(self, name, input) -> str
```

---

## 模块六：多 Agent 协调系统

**原版文件**
- `src/tools/AgentTool/AgentTool.tsx`
- `src/utils/forkedAgent.ts`
- `src/coordinator/` — 协调器模式
- `src/tools/AgentTool/built-in/` — 内置子 Agent

**核心设计决策**

Agent 可以 fork 子 Agent，形成树状结构：

```
主 Agent（用户对话）
  ├── 子 Agent A（并行任务）
  │   └── 工具调用
  ├── 子 Agent B（并行任务）
  │   └── 工具调用
  └── 协调 Agent（汇总结果）
```

四种 fork 模式：
| 模式 | 说明 |
|------|------|
| `subagent` | 同步子任务，等待结果 |
| `background` | 异步，不等结果 |
| `worktree` | 在独立 git worktree 中运行，不污染工作区 |
| `remote` | 在远程环境运行 |

**架构亮点**：worktree 模式极其优雅——Claude 可以并行尝试多种方案，
每个方案在独立分支，互不干扰，最后 cherry-pick 最好的。

**Python 实现目标**
```python
# tools/agent_tool.py
class AgentTool:
    def fork_subagent(self, task, context) -> AgentResult
    def fork_background(self, task, context) -> asyncio.Task
    def fork_worktree(self, task, branch_name) -> AgentResult
```

---

## 模块七：权限规则引擎

**原版文件**
- `src/utils/permissions/permissionRuleParser.ts`
- `src/utils/permissions/shellRuleMatching.ts`
- `src/utils/permissions/filesystem.ts`
- `src/types/permissions.ts`

**核心设计决策**

权限规则是多源、多层次的：

```
规则来源优先级（高 → 低）：
  CLI 参数 > session > localSettings > projectSettings > userSettings > policy

规则类型：
  alwaysAllow: ["bash(git *)", "file_read"]   # glob 模式匹配命令
  alwaysDeny:  ["bash(rm -rf *)"]
  alwaysAsk:   ["bash(curl *)"]
```

Shell 命令匹配（`shellRuleMatching.ts`）：
```
"bash(git *)"  → 只允许以 git 开头的 bash 命令
"file_edit"    → 允许所有文件编辑
"glob(**/*.py)"→ 允许 glob 搜索 .py 文件
```

这是一个完整的策略引擎，支持通配符、命令解析、路径匹配。

**Python 实现目标**
```python
# permissions/rule_engine.py
class RuleEngine:
    def add_rule(self, source, behavior, tool_name, pattern=None)
    def check(self, tool_name, tool_input) -> Literal["allow", "deny", "ask"]
    def _match_bash_rule(self, pattern, command) -> bool  # fnmatch
```

---

## 模块八：React/Ink 终端 UI 架构

**原版文件**
- `src/ink/` — 自定义 Ink 框架（fork）
- `src/screens/REPL.tsx` — 主界面
- `src/components/` — UI 组件库
- `src/ink.ts` — render 入口

**核心设计决策**

用 React reconciler 驱动终端：
```
React 组件树（逻辑层）
      ↓ reconciler
虚拟终端树（Yoga 布局）
      ↓ render
ANSI 转义码输出（物理层）
```

**架构亮点**：
1. **虚拟滚动**（`useVirtualScroll`）：消息列表可能有数千条，只渲染可见区域
2. **流式更新**：每个 SSE delta 触发最小 React re-render，不重绘整个界面
3. **React Compiler**：编译时自动插入 memo，原版组件几乎不需要手写 useMemo

**Python 对应**：`textual`（TUI 框架，同样用组件化模型 + CSS 布局）

**Python 实现目标**
```python
# ui/app.py（用 textual 重写）
class ClaudeApp(App):
    def compose(self) -> ComposeResult:
        yield MessageList()    # 虚拟滚动消息列表
        yield ToolCallPanel()  # 工具调用状态
        yield PromptInput()    # 用户输入框
```

---

## 模块九：Buddy 虚拟伴侣系统 🐾

**原版文件**
- `src/buddy/types.ts` — 物种/稀有度/属性定义
- `src/buddy/companion.ts` — 确定性生成算法
- `src/buddy/sprites.ts` — ASCII 精灵图
- `src/buddy/prompt.ts` — Claude 生成灵魂
- `src/buddy/useBuddyNotification.tsx` — 气泡通知
- `src/commands/buddy/buddy.ts` — `/buddy` 命令

**核心设计决策**

Buddy 的精妙在于**确定性生成**：

```
hash(userId) → seed → Mulberry32 PRNG
  → 稀有度（加权随机：common 60%, legendary 1%）
  → 物种（18种：duck/cat/dragon/axolotl...）
  → 眼睛样式（6种：·✦×◉@°）
  → 帽子（8种：crown/wizard/tinyduck...）
  → 5项属性（DEBUGGING/PATIENCE/CHAOS/WISDOM/SNARK）
```

**存储策略**：只存 `{name, personality, hatchedAt}`，
骨架（外观）每次从 hash 重新生成，确保用户无法通过编辑配置文件刷稀有度。

**灵魂（Soul）由 Claude 生成**：第一次 `/buddy hatch` 时，
调用 Claude API 生成伴侣的名字和性格，存入配置文件永久保存。

**气泡通知**：在 Claude 思考/工具执行时，Buddy 会根据当前状态说话，
性格和台词由 Claude 实时生成。

**Python 实现目标**
```python
# buddy/companion.py — 确定性生成
# buddy/sprites.py  — ASCII 精灵图（rich 渲染）
# buddy/soul.py     — Claude 生成名字和性格
# buddy/bubble.py   — 气泡通知（在工具执行时出现）
# commands/buddy.py — /buddy 命令
```

---

## 实施顺序建议

| 优先级 | 模块 | 理由 |
|--------|------|------|
| ① | **流式输出**（模块二简化版） | 体验差距最大，学到 SSE 协议 |
| ② | **Hook 系统**（模块四） | 最实用，架构最清晰，独立性强 |
| ③ | **权限规则引擎**（模块七） | 当前 permissions.py 过于简单 |
| ④ | **工具基类重构**（模块一） | 为后续模块打地基 |
| ⑤ | **Context 管理三策略**（模块三） | 生产环境必须 |
| ⑥ | **Buddy**（模块九） | 最有趣，综合运用前面所有模块 |
| ⑦ | **Multi-Agent**（模块六） | 最复杂，放最后 |
| ⑧ | **MCP**（模块五） | 有官方 Python SDK 可用 |
| ⑨ | **Textual UI**（模块八） | 可选，当前 rich 已够用 |

---

## 各模块对应原版文件速查

| Python 模块 | 原版文件 |
|------------|----------|
| `tools/base.py` | `src/Tool.ts`, `src/tools/*/` |
| `services/streaming.py` | `src/services/tools/StreamingToolExecutor.ts` |
| `services/compact_v2.py` | `src/services/compact/*.ts` |
| `services/hooks.py` | `src/utils/hooks.ts`, `src/utils/hooks/` |
| `services/mcp/` | `src/services/mcp/`, `src/tools/MCPTool/` |
| `tools/agent_tool.py` | `src/tools/AgentTool/`, `src/utils/forkedAgent.ts` |
| `permissions/rule_engine.py` | `src/utils/permissions/`, `src/types/permissions.ts` |
| `ui/app.py` | `src/screens/REPL.tsx`, `src/ink/` |
| `buddy/` | `src/buddy/`, `src/commands/buddy/` |
