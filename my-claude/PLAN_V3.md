# PLAN_V3 — my-claude 完整实现规划

> 本文档整合 PLAN_V2_DEEP.md 及其所有补充模块，按**实现顺序**统一编排。
> 每个模块包含：原版 TS 来源、关键常量/数据结构、Python 实现蓝图。
> 代码中 `#` 开头的路径为 my-claude 内的目标文件路径。

---

## 全局架构图

```
my-claude/
├── core/
│   ├── streaming.py       ✅ SSE 事件解析 + ResponseAssembler
│   ├── client.py          ✅ httpx 同步/异步客户端
│   ├── query.py           ✅ 单轮查询函数
│   └── tool_orchestrator.py   asyncio 并发工具执行器
├── utils/
│   ├── messages.py        消息格式化 + token 估算
│   ├── bash_analysis.py   Bash AST 安全分析（正则近似）
│   ├── session_storage.py JSONL 会话持久化
│   └── attachments.py     图片/PDF/文本附件
├── bootstrap/
│   └── state.py           全局单例（sessionId, cwd, totalCostUSD…）
├── config/
│   ├── global_config.py   GlobalConfig（~/.claude/config.json）
│   ├── settings.py        5 层 Settings 合并系统
│   └── skills.py          技能/斜杠命令加载
├── services/
│   ├── hooks.py           Hook 系统（27 事件 × 4 类型）
│   ├── compact.py         Context window 管理（auto/micro/snip）
│   ├── session_memory.py  跨会话记忆（MAX 12000 tokens）
│   └── mcp/
│       ├── client.py      MCP 服务器连接（stdio/SSE）
│       └── registry.py    MCP 工具注册
├── permissions/
│   └── rule_engine.py     权限规则引擎（5 模式 × 8 来源）
├── tools/
│   ├── base.py            BaseTool 抽象类 + buildTool 工厂
│   ├── bash_tool.py       BashTool（最复杂）
│   ├── file_read.py       FileReadTool
│   ├── file_edit.py       FileEditTool
│   ├── file_write.py      FileWriteTool
│   ├── glob_tool.py       GlobTool
│   ├── grep_tool.py       GrepTool
│   ├── agent_tool.py      AgentTool（子 Agent）
│   └── registry.py        工具注册表（56 个工具）
├── tasks/
│   └── types.py           7 种后台任务类型
├── context.py             系统提示构建（7 部分）
├── buddy/
│   ├── companion.py       Mulberry32 + FNV-1a + rollStats
│   ├── sprites.py         ASCII 精灵图数据
│   └── soul.py            Buddy 名字/性格生成
├── cli/
│   └── print_mode.py      Pipe/SDK 模式输出（text/json/stream-json）
├── ui/
│   └── app.py             Textual TUI（可选）
├── providers/
│   └── httpx_provider.py  ✅ Provider 适配器
└── main.py                CLI 入口（argparse）
```

---

## 实施路线图

| 阶段 | 模块 | 文件 | 原版参考 | 状态 |
|------|------|------|---------|------|
| **A** | SSE 流式 + HTTP 客户端 | core/{streaming,client,query}.py | claude.ts | ✅ 完成 |
| **B** | 消息格式化工具 | utils/messages.py | utils/messages.ts | 待实现 |
| **C** | Bootstrap 全局状态 | bootstrap/state.py | bootstrap/state.ts | 待实现 |
| **D** | 会话持久化 | utils/session_storage.py | utils/sessionStorage.ts | 待实现 |
| **E** | 配置系统 | config/{global_config,settings}.py | utils/config.ts + settings/ | 待实现 |
| **F** | 技能/斜杠命令 | config/skills.py | skills/loadSkillsDir.ts | 待实现 |
| **G** | 权限规则引擎 | permissions/rule_engine.py | permissions/*.ts | 待实现 |
| **H** | Hook 系统 | services/hooks.py | utils/hooks.ts + schemas/hooks.ts | 待实现 |
| **I** | 工具基类 + Bash AST | tools/base.py, utils/bash_analysis.py | Tool.ts + utils/bash/ | 待实现 |
| **J** | 内置工具集（核心 7 个）| tools/*.py | tools/ | 待实现 |
| **K** | Context Window 管理 | services/compact.py | services/compact/ | 待实现 |
| **L** | 并发工具执行器 | core/tool_orchestrator.py | StreamingToolExecutor.ts | 待实现 |
| **M** | 系统提示构建 | context.py | context.ts + utils/claudemd.ts | 待实现 |
| **N** | 会话记忆 | services/session_memory.py | services/SessionMemory/ | 待实现 |
| **O** | CLI 打印模式 | cli/print_mode.py | cli/print.ts | 待实现 |
| **P** | MCP 协议 | services/mcp/ | services/mcp/ | 待实现 |
| **Q** | 多 Agent + 任务系统 | tools/agent_tool.py, tasks/ | AgentTool/ + tasks/ | 待实现 |
| **R** | Textual TUI | ui/app.py | screens/REPL.tsx + ink/ | 可选 |
| **S** | Buddy 伴侣系统 | buddy/ | buddy/ | 可选 |
| **T** | Swarm 多 Agent 协调 | utils/swarm/ | utils/swarm/ | 可选 |
| **U** | OAuth 认证 | services/oauth.py | services/oauth/ | 可选 |

---

## 阶段 A：SSE 流式 + HTTP 客户端（✅ 已完成）

**原版文件**：`src/services/api/claude.ts`, `src/query.ts`

已实现文件：
- `core/streaming.py` — SSE 事件数据类 + `ResponseAssembler`
- `core/client.py` — `AnthropicClient`（同步）/ `AsyncAnthropicClient`（异步）
- `core/query.py` — `query_once()` 单轮查询
- `providers/httpx_provider.py` — `HttpxProvider` 适配器

SSE 事件类型：
```
message_start → content_block_start → content_block_delta（text/input_json）
→ content_block_stop → message_delta → message_stop | ping
```

---

## 阶段 B：消息格式化工具

**原版文件**：`src/utils/messages.ts`（~5,556 行）

### 关键函数

| 函数 | 说明 |
|------|------|
| `roughTokenCountEstimation(text)` | `Math.ceil(text.length / 4)`，粗估 token 数 |
| `normalizeMessages(messages)` | 合并相邻同角色消息 |
| `getTokenCountFromMessages(messages)` | 累加所有 content block 的 token 估算 |
| `truncateMessages(messages, maxTokens)` | 从头删除直到在限制内 |
| `userMessageToApiFormat(msg)` | 内部格式 → Anthropic API 格式 |

### Python 实现

```python
# utils/messages.py
import math
from typing import Any

def rough_token_count(text: str) -> int:
    """对应 roughTokenCountEstimation：len / 4 向上取整。"""
    return math.ceil(len(text) / 4)

def get_content_text(content: Any) -> str:
    """从各种 content 格式提取文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get('text', '') or str(block.get('input', '')))
        return ' '.join(parts)
    return str(content)

def get_messages_token_count(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        total += rough_token_count(get_content_text(msg.get('content', '')))
    return total

def normalize_messages(messages: list[dict]) -> list[dict]:
    """合并相邻同角色消息（API 要求 user/assistant 交替）。"""
    if not messages:
        return []
    result: list[dict] = []
    for msg in messages:
        if result and result[-1]['role'] == msg['role']:
            prev = result[-1]
            # 统一转为 list 格式再合并
            prev_content = prev['content']
            if isinstance(prev_content, str):
                prev_content = [{'type': 'text', 'text': prev_content}]
            new_content = msg['content']
            if isinstance(new_content, str):
                new_content = [{'type': 'text', 'text': new_content}]
            prev['content'] = prev_content + new_content
        else:
            result.append({'role': msg['role'], 'content': msg['content']})
    return result

def truncate_messages(messages: list[dict], max_tokens: int) -> list[dict]:
    """删除最旧的消息直到 token 数在限制内（保留最近的消息）。"""
    while messages and get_messages_token_count(messages) > max_tokens:
        messages = messages[1:]
    return messages

def build_tool_result_block(tool_use_id: str, content: str, is_error: bool = False) -> dict:
    return {
        'type': 'tool_result',
        'tool_use_id': tool_use_id,
        'content': content,
        'is_error': is_error,
    }

def build_tool_use_block(tool_id: str, name: str, input_: dict) -> dict:
    return {'type': 'tool_use', 'id': tool_id, 'name': name, 'input': input_}
```

---

## 阶段 C：Bootstrap 全局状态

**原版文件**：`src/bootstrap/state.ts`

### 原版 State 类型

```typescript
type State = {
  sessionId: string            // UUID，每次启动新建
  originalCwd: string          // 启动时的工作目录（不随 cd 变化）
  cwd: string                  // 当前工作目录（可变）
  projectRoot: string | null   // 最近的 .git 所在目录
  totalCostUSD: number         // 本次会话总费用
  totalInputTokens: number
  totalOutputTokens: number
  additionalDirectories: string[]  // 额外允许访问的目录
  customApiKeyName: string | null
  earlyExitMessage: string | null
}
```

关键设计：**模块级单例**（不是 React state），进程内全局共享。

### Python 实现

```python
# bootstrap/state.py
import uuid
import os
from pathlib import Path

class _State:
    session_id: str = ''
    original_cwd: str = ''
    cwd: str = ''
    project_root: str | None = None
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    additional_directories: list[str] = []
    custom_api_key_name: str | None = None
    early_exit_message: str | None = None

_state = _State()

def init_state() -> None:
    _state.session_id = str(uuid.uuid4())
    _state.original_cwd = os.getcwd()
    _state.cwd = os.getcwd()
    _state.project_root = _find_project_root()
    _state.total_cost_usd = 0.0
    _state.total_input_tokens = 0
    _state.total_output_tokens = 0
    _state.additional_directories = []

def _find_project_root() -> str | None:
    """向上查找最近的 .git 目录。"""
    p = Path(_state.cwd)
    for parent in [p] + list(p.parents):
        if (parent / '.git').exists():
            return str(parent)
    return None

# 公开读取函数
def get_session_id() -> str: return _state.session_id
def get_cwd() -> str: return _state.cwd
def get_original_cwd() -> str: return _state.original_cwd
def get_project_root() -> str | None: return _state.project_root
def get_total_cost() -> float: return _state.total_cost_usd

# 费用累计
def add_cost(input_tokens: int, output_tokens: int, model: str) -> None:
    from config.global_config import get_token_cost
    cost = get_token_cost(model, input_tokens, output_tokens)
    _state.total_cost_usd += cost
    _state.total_input_tokens += input_tokens
    _state.total_output_tokens += output_tokens

def set_cwd(new_cwd: str) -> None:
    _state.cwd = new_cwd
    os.chdir(new_cwd)
```

---

## 阶段 D：会话持久化

**原版文件**：`src/utils/sessionStorage.ts`（~5,106 行）

JSONL 格式（每行一条消息），流式追加，支持恢复。

### Python 实现

```python
# utils/session_storage.py
import json
from pathlib import Path
from datetime import datetime

def _sessions_dir() -> Path:
    return Path.home() / '.claude' / 'sessions'

def get_session_path(session_id: str) -> Path:
    return _sessions_dir() / f'{session_id}.jsonl'

def append_message(session_id: str, message: dict) -> None:
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
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return messages

def list_sessions() -> list[dict]:
    d = _sessions_dir()
    if not d.exists():
        return []
    result = []
    for p in sorted(d.glob('*.jsonl'), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = p.stat()
        result.append({
            'session_id': p.stem,
            'path': str(p),
            'size_bytes': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return result

def delete_session(session_id: str) -> bool:
    path = get_session_path(session_id)
    if path.exists():
        path.unlink()
        return True
    return False
```

---

## 阶段 E：配置系统

**原版文件**：`src/utils/config.ts`（GlobalConfig，35+ 字段），`src/utils/settings/`（5 层 Settings）

### 两套配置的区别

| 类型 | 文件 | 内容 |
|------|------|------|
| **GlobalConfig** | `~/.claude/config.json` | 用户账户信息（userId、model、apiKey 等）|
| **Settings** | 分层 JSON 文件 | 权限规则、hooks、MCP 服务器等运行时配置 |

### 5 层 Settings 来源（优先级从低到高）

```
1. userSettings     → ~/.claude/settings.json
2. projectSettings  → <project>/.claude/settings.json
3. localSettings    → <project>/.claude/settings.local.json（不进 git）
4. flagSettings     → 来自 feature flag（已禁用）
5. policySettings   → 企业策略（来自 ~/.claude/claude_policy.json）
```

### GlobalConfig 关键字段

```typescript
type GlobalConfig = {
  userId: string               // 用户唯一 ID（Buddy 系统依赖此字段生成外观）
  primaryApiKey: string        // Anthropic API Key
  hasCompletedOnboarding: boolean
  model: string                // 默认模型（如 'claude-sonnet-4-6'）
  customApiKeyName: string | null
  oauthToken: string | null
  // 35+ 其他字段...
}
```

### Python 实现

```python
# config/global_config.py
import json, os
from pathlib import Path
from dataclasses import dataclass, field, asdict

CONFIG_PATH = Path.home() / '.claude' / 'config.json'

@dataclass
class GlobalConfig:
    user_id: str = ''
    primary_api_key: str = ''
    has_completed_onboarding: bool = False
    model: str = 'claude-sonnet-4-6'
    custom_api_key_name: str | None = None
    oauth_token: str | None = None

_config: GlobalConfig | None = None

def load_config() -> GlobalConfig:
    global _config
    if _config is not None:
        return _config
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        _config = GlobalConfig(
            user_id=data.get('userId', ''),
            primary_api_key=data.get('primaryApiKey', os.environ.get('ANTHROPIC_API_KEY', '')),
            has_completed_onboarding=data.get('hasCompletedOnboarding', False),
            model=data.get('model', 'claude-sonnet-4-6'),
        )
    else:
        _config = GlobalConfig(
            primary_api_key=os.environ.get('ANTHROPIC_API_KEY', ''),
        )
    return _config

def save_config(config: GlobalConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        'userId': config.user_id,
        'primaryApiKey': config.primary_api_key,
        'hasCompletedOnboarding': config.has_completed_onboarding,
        'model': config.model,
    }
    CONFIG_PATH.write_text(json.dumps(data, indent=2))

def get_api_key() -> str:
    return load_config().primary_api_key or os.environ.get('ANTHROPIC_API_KEY', '')

MODEL_COSTS = {
    'claude-opus-4-6':    {'input': 15.0, 'output': 75.0},   # per 1M tokens
    'claude-sonnet-4-6':  {'input': 3.0,  'output': 15.0},
    'claude-haiku-4-5':   {'input': 0.8,  'output': 4.0},
}

def get_token_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    costs = MODEL_COSTS.get(model, {'input': 3.0, 'output': 15.0})
    return (input_tokens * costs['input'] + output_tokens * costs['output']) / 1_000_000
```

```python
# config/settings.py
import json
from pathlib import Path
from dataclasses import dataclass, field

SETTING_SOURCES = [
    'userSettings', 'projectSettings', 'localSettings', 'flagSettings', 'policySettings'
]

SETTINGS_FILES = {
    'userSettings':    lambda: Path.home() / '.claude' / 'settings.json',
    'policySettings':  lambda: Path.home() / '.claude' / 'claude_policy.json',
    'projectSettings': lambda cwd: Path(cwd) / '.claude' / 'settings.json',
    'localSettings':   lambda cwd: Path(cwd) / '.claude' / 'settings.local.json',
}

@dataclass
class Settings:
    permissions_allow: list[str] = field(default_factory=list)
    permissions_deny: list[str] = field(default_factory=list)
    permissions_ask: list[str] = field(default_factory=list)
    default_mode: str = 'default'
    additional_directories: list[str] = field(default_factory=list)
    hooks: dict = field(default_factory=dict)
    mcp_servers: dict = field(default_factory=dict)
    model: str | None = None
    env: dict = field(default_factory=dict)

def _load_json_safe(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}

def load_settings(cwd: str = '.') -> Settings:
    """合并所有来源的 settings，高优先级覆盖低优先级。"""
    merged: dict = {}
    for source in SETTING_SOURCES:
        if source in ('projectSettings', 'localSettings'):
            path = SETTINGS_FILES[source](cwd)
        elif source in ('userSettings', 'policySettings'):
            path = SETTINGS_FILES[source]()
        else:
            continue
        data = _load_json_safe(path)
        _deep_merge(merged, data)
    
    perms = merged.get('permissions', {})
    return Settings(
        permissions_allow=perms.get('allow', []),
        permissions_deny=perms.get('deny', []),
        permissions_ask=perms.get('ask', []),
        default_mode=perms.get('defaultMode', 'default'),
        additional_directories=perms.get('additionalDirectories', []),
        hooks=merged.get('hooks', {}),
        mcp_servers=merged.get('mcpServers', {}),
        model=merged.get('model'),
        env=merged.get('env', {}),
    )

def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        elif k in base and isinstance(base[k], list) and isinstance(v, list):
            base[k] = base[k] + v  # list 合并（不去重）
        else:
            base[k] = v
```

---

## 阶段 F：技能/斜杠命令系统

**原版文件**：`src/skills/loadSkillsDir.ts`（~4,080 行）

### Skill 文件格式（Markdown + Frontmatter）

```markdown
---
description: 提交并推送代码
allowed-tools: Bash
argument-hint: <message>
model: claude-opus-4-6
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
| `description` | string | 在 `/help` 中显示的描述 |
| `allowed-tools` | string/list | 限制可用工具（如 `Bash,file_edit`）|
| `argument-hint` | string | 补全提示（如 `<branch-name>`）|
| `model` | string | 覆盖默认模型 |
| `effort` | low/medium/high | 影响 thinking token budget |
| `shell` | string | 指定 shell（bash/zsh 等）|

### LoadedFrom 来源枚举

```python
# 'skills' | 'bundled' | 'plugin' | 'managed' | 'mcp' | 'commands_DEPRECATED'
```

### Python 实现

```python
# config/skills.py
import re
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class SkillFrontmatter:
    description: str = ''
    allowed_tools: list[str] = field(default_factory=list)
    argument_hint: str = ''
    model: str | None = None
    effort: str = 'medium'
    shell: str = 'bash'

@dataclass
class Skill:
    name: str           # 斜杠命令名（文件名无扩展名）
    content: str        # Markdown 正文（模板，$ARGUMENTS 替换用户输入）
    frontmatter: SkillFrontmatter
    loaded_from: str    # 来源标识
    source_path: Path

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 Markdown frontmatter，返回 (data_dict, body)。"""
    if text.startswith('---'):
        end = text.find('---', 3)
        if end != -1:
            fm_text = text[3:end].strip()
            body = text[end+3:].strip()
            data: dict = {}
            for line in fm_text.splitlines():
                if ':' in line:
                    k, _, v = line.partition(':')
                    data[k.strip()] = v.strip()
            return data, body
    return {}, text

def _parse_skill(path: Path, loaded_from: str) -> Skill:
    text = path.read_text(encoding='utf-8')
    data, body = _parse_frontmatter(text)
    tools_raw = data.get('allowed-tools', '')
    if isinstance(tools_raw, str):
        tools = [t.strip() for t in tools_raw.split(',') if t.strip()]
    else:
        tools = tools_raw
    fm = SkillFrontmatter(
        description=data.get('description', ''),
        allowed_tools=tools,
        argument_hint=data.get('argument-hint', ''),
        model=data.get('model') or None,
        effort=data.get('effort', 'medium'),
        shell=data.get('shell', 'bash'),
    )
    return Skill(
        name=path.stem,
        content=body,
        frontmatter=fm,
        loaded_from=loaded_from,
        source_path=path,
    )

def load_skills_from_dir(directory: Path, loaded_from: str = 'skills') -> list[Skill]:
    if not directory.exists():
        return []
    return [_parse_skill(p, loaded_from) for p in sorted(directory.glob('**/*.md'))]

def get_all_skills(cwd: str = '.') -> list[Skill]:
    """从所有来源加载技能（去重，后加载覆盖先加载的同名技能）。"""
    skills: dict[str, Skill] = {}
    home = Path.home()
    cwd_path = Path(cwd)
    
    # 1. 用户全局技能（最低优先级）
    for skill in load_skills_from_dir(home / '.claude' / 'skills'):
        skills[skill.name] = skill
    
    # 2. 项目技能（从项目根到 cwd 依次加载）
    for d in reversed([cwd_path] + list(cwd_path.parents)):
        proj_skills_dir = d / '.claude' / 'skills'
        for skill in load_skills_from_dir(proj_skills_dir, 'skills'):
            skills[skill.name] = skill
        if d == home:
            break
    
    return list(skills.values())

def expand_skill(skill: Skill, arguments: str) -> str:
    """将 $ARGUMENTS 替换为用户输入。"""
    return skill.content.replace('$ARGUMENTS', arguments)
```

---

## 阶段 G：权限规则引擎

**原版文件**：`src/types/permissions.ts`（248 行），`src/utils/permissions/shellRuleMatching.ts`

### 核心类型

```
PermissionMode（5种用户模式）：
  default      → 每次询问
  acceptEdits  → 自动接受文件编辑，其他询问
  dontAsk      → 全部自动允许
  bypassPermissions → 绕过所有检查（危险）
  plan         → 只读，不允许写操作

PermissionRuleSource（8种来源，优先级从高到低）：
  cliArg → session → localSettings → projectSettings
  → userSettings → flagSettings → policySettings → command

PermissionResult（3种结果）：
  allow  → 附带可选的 updatedInput（规范化路径等）
  ask    → 附带 message + suggestions（建议规则）
  deny   → 附带 message + decisionReason
```

### Shell 规则匹配算法（matchWildcardPattern）

关键特例：末尾 ` *`（单通配符+空格）→ `( .*)?`（可选尾部参数）
- `"git *"` → `^git( .*)?$` → 既匹配 `"git"` 也匹配 `"git add"`

```python
# permissions/rule_engine.py
import re
from dataclasses import dataclass
from enum import Enum

class PermissionMode(str, Enum):
    DEFAULT = 'default'
    ACCEPT_EDITS = 'acceptEdits'
    DONT_ASK = 'dontAsk'
    BYPASS = 'bypassPermissions'
    PLAN = 'plan'

RULE_SOURCE_PRIORITY = [
    'cliArg', 'session', 'localSettings', 'projectSettings',
    'userSettings', 'flagSettings', 'policySettings', 'command',
]

@dataclass
class PermissionRule:
    source: str
    behavior: str      # 'allow' | 'deny' | 'ask'
    tool_name: str
    rule_content: str  # 命令模式（如 "git *"），可为空

@dataclass
class PermissionResult:
    behavior: str      # 'allow' | 'ask' | 'deny'
    message: str = ''
    updated_input: dict | None = None
    suggestions: list | None = None
    decision_reason: str = ''

def match_wildcard_pattern(pattern: str, command: str) -> bool:
    """对应 shellRuleMatching.ts 的 matchWildcardPattern 完整实现。"""
    p = pattern
    # 步骤1: 保护转义序列
    p = p.replace('\\\\', '\x00BS\x00').replace('\\*', '\x00STAR\x00')
    # 步骤2: 统计未转义的 * 数量（用于后续特例判断）
    star_count = p.count('*')
    # 步骤3: 转义 regex 特殊字符（排除 *）
    p = re.sub(r'([.+?^${}()|\[\]\\])', r'\\\1', p)
    # 步骤4: * → .*
    p = p.replace('*', '.*')
    # 步骤5: 还原占位符
    p = p.replace('\x00STAR\x00', '\\*').replace('\x00BS\x00', '\\\\')
    # 步骤6: 特例——末尾 ' .*'（单通配符+前置空格）→ 可选尾部
    if p.endswith(' .*') and star_count == 1:
        p = p[:-3] + '( .*)?'
    return bool(re.match(f'^{p}$', command, re.DOTALL))

def parse_rule_string(rule: str) -> tuple[str, str]:
    """'Bash(git *)' → ('Bash', 'git *')，'file_read' → ('file_read', '')"""
    if '(' in rule and rule.endswith(')'):
        pos = rule.index('(')
        return rule[:pos], rule[pos+1:-1]
    return rule, ''

def match_tool_pattern(tool_name: str, rule_tool: str, rule_content: str,
                        tool_input: dict) -> bool:
    if rule_tool.lower() != tool_name.lower():
        return False
    if not rule_content:
        return True
    command = tool_input.get('command', '') or tool_input.get('path', '')
    return match_wildcard_pattern(rule_content, command)

class RuleEngine:
    def __init__(self, mode: PermissionMode = PermissionMode.DEFAULT):
        self._rules: list[PermissionRule] = []
        self._mode = mode

    def load_from_settings(self, settings) -> None:
        for r in settings.permissions_allow:
            name, content = parse_rule_string(r)
            self._rules.append(PermissionRule('projectSettings', 'allow', name, content))
        for r in settings.permissions_deny:
            name, content = parse_rule_string(r)
            self._rules.append(PermissionRule('projectSettings', 'deny', name, content))
        for r in settings.permissions_ask:
            name, content = parse_rule_string(r)
            self._rules.append(PermissionRule('projectSettings', 'ask', name, content))
        self._mode = PermissionMode(settings.default_mode)

    def add_rule(self, source: str, behavior: str, tool_name: str,
                  rule_content: str = '') -> None:
        # 高优先级来源插到前面
        idx = RULE_SOURCE_PRIORITY.index(source) if source in RULE_SOURCE_PRIORITY else 99
        insert_at = 0
        for i, r in enumerate(self._rules):
            r_idx = RULE_SOURCE_PRIORITY.index(r.source) if r.source in RULE_SOURCE_PRIORITY else 99
            if r_idx <= idx:
                insert_at = i + 1
        self._rules.insert(insert_at,
            PermissionRule(source, behavior, tool_name, rule_content))

    def check(self, tool_name: str, tool_input: dict) -> PermissionResult:
        for rule in self._rules:
            if match_tool_pattern(tool_name, rule.tool_name, rule.rule_content, tool_input):
                return PermissionResult(behavior=rule.behavior)
        # 无匹配规则 → 根据模式默认
        if self._mode in (PermissionMode.BYPASS, PermissionMode.DONT_ASK):
            return PermissionResult(behavior='allow')
        if self._mode == PermissionMode.PLAN:
            return PermissionResult(behavior='deny', message='Plan mode: writes not allowed',
                                     decision_reason='plan_mode')
        return PermissionResult(behavior='ask', message=f'Allow {tool_name}?')
```

---

## 阶段 H：Hook 系统

**原版文件**：`src/utils/hooks.ts`（5,121 行），`src/schemas/hooks.ts`，`src/entrypoints/sdk/coreTypes.ts`

### 27 种 Hook 事件

```python
HOOK_EVENTS = [
    'PreToolUse', 'PostToolUse', 'PostToolUseFailure',
    'Notification', 'UserPromptSubmit',
    'SessionStart', 'SessionEnd',
    'Stop', 'StopFailure',
    'SubagentStart', 'SubagentStop',
    'PreCompact', 'PostCompact',
    'PermissionRequest', 'PermissionDenied',
    'Setup',
    'TeammateIdle', 'TaskCreated', 'TaskCompleted',
    'Elicitation', 'ElicitationResult',
    'ConfigChange',
    'WorktreeCreate', 'WorktreeRemove',
    'InstructionsLoaded', 'CwdChanged', 'FileChanged',
]  # 共 27 种
```

### 4 种 Hook 类型

| 类型 | 字段 | 说明 |
|------|------|------|
| `command` | command, shell, timeout, async_, async_rewake | 最常用，执行 shell 命令 |
| `prompt` | prompt, model, timeout | 用小模型（Haiku）处理 |
| `http` | url, headers, allowed_env_vars, timeout | HTTP 请求 |
| `agent` | prompt, model, timeout | 验证型 agent |

### 关键常量

```python
TOOL_HOOK_TIMEOUT_S = 600        # 10 分钟（工具 hook）
SESSION_END_HOOK_TIMEOUT_S = 1.5 # 仅 1.5 秒！（用户关闭终端时）
# 可通过 CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS 覆盖
```

### asyncRewake 机制

```
exit code 0 → 成功（继续）
exit code 1 → 失败（记录但不阻塞）
exit code 2 → 唤醒模型（将 stderr/stdout 作为系统消息注入对话）
```

### Python 实现

```python
# services/hooks.py
import subprocess, json, os, asyncio
from dataclasses import dataclass, field

TOOL_HOOK_TIMEOUT_S = 600
SESSION_END_HOOK_TIMEOUT_S = 1.5

@dataclass
class HookResult:
    success: bool
    block: bool = False        # 是否阻止工具执行
    rewake_text: str = ''      # asyncRewake 触发时的文本（注入系统消息）

class HookExecutor:
    def __init__(self, hooks_config: dict):
        self._config = hooks_config

    def fire(self, event: str, tool_name: str = '',
              tool_input: dict | None = None,
              tool_result: str = '',
              timeout_override: float | None = None) -> HookResult:
        """同步触发 hook（PreToolUse 可阻止工具执行）。"""
        matchers = self._config.get(event, [])
        for matcher_cfg in matchers:
            matcher = matcher_cfg.get('matcher', '')
            if matcher and not self._check_matcher(matcher, tool_name, tool_input or {}):
                continue
            for hook_def in matcher_cfg.get('hooks', []):
                if hook_def.get('once') and self._was_fired(event, hook_def):
                    continue
                result = self._exec(hook_def, tool_name, tool_input or {},
                                     tool_result, timeout_override)
                if result.block:
                    return result
        return HookResult(success=True)

    def _check_matcher(self, matcher: str, tool_name: str, tool_input: dict) -> bool:
        from permissions.rule_engine import parse_rule_string, match_tool_pattern
        rname, rcontent = parse_rule_string(matcher)
        return match_tool_pattern(tool_name, rname, rcontent, tool_input)

    def _exec(self, hook_def: dict, tool_name: str, tool_input: dict,
               tool_result: str, timeout_override: float | None) -> HookResult:
        hook_type = hook_def.get('type', 'command')
        timeout = timeout_override or hook_def.get('timeout') or TOOL_HOOK_TIMEOUT_S
        env = {
            **os.environ,
            'CLAUDE_TOOL_NAME': tool_name,
            'CLAUDE_TOOL_INPUT': json.dumps(tool_input),
            'CLAUDE_TOOL_RESULT': tool_result,
        }

        if hook_type == 'command':
            is_async_rewake = hook_def.get('asyncRewake', False)
            is_async = hook_def.get('async', False) or is_async_rewake
            cmd = hook_def['command']
            shell = hook_def.get('shell', 'bash')
            try:
                if is_async:
                    # 后台启动，不等结果（asyncRewake 靠退出码 2 唤醒）
                    subprocess.Popen(cmd, shell=True, env=env)
                    return HookResult(success=True)
                proc = subprocess.run(
                    cmd, shell=True, env=env,
                    capture_output=True, text=True, timeout=timeout
                )
                if proc.returncode == 2:
                    text = proc.stderr or proc.stdout
                    return HookResult(success=False, block=True, rewake_text=text)
                if proc.returncode != 0:
                    return HookResult(success=False)
            except subprocess.TimeoutExpired:
                pass  # 超时不阻塞
        
        elif hook_type == 'http':
            import urllib.request
            url = hook_def['url']
            headers = hook_def.get('headers', {})
            body = json.dumps({'event': hook_def, 'tool_name': tool_name,
                                'tool_input': tool_input}).encode()
            req = urllib.request.Request(url, data=body, headers=headers, method='POST')
            try:
                urllib.request.urlopen(req, timeout=timeout)
            except Exception:
                pass

        # prompt/agent hook: 简化实现（调用 Haiku 模型）
        # 完整实现见 Phase Q（多 Agent）完成后

        return HookResult(success=True)

    def _was_fired(self, event: str, hook_def: dict) -> bool:
        # TODO: 记录 once hook 的触发状态
        return False
```

---

## 阶段 I：工具基类 + Bash AST 安全分析

**原版文件**：`src/Tool.ts`（793 行），`src/utils/bash/`（~12,310 行）

### Tool 接口核心方法（buildTool 默认值）

```python
TOOL_DEFAULTS = {
    'is_concurrency_safe': False,    # fail-closed：默认串行
    'is_read_only': False,           # fail-closed：默认非只读
    'is_destructive': False,
    'is_search_or_read': False,
    'max_result_size_chars': None,   # None = 不限制
    'should_defer': False,
}
```

### Python 实现

```python
# tools/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass
class ToolResult:
    content: str | list            # 返回给 Claude 的内容
    is_error: bool = False
    context_modifier: Callable | None = None  # 修改 context（仅非并发工具有效）
    output: Any = None             # 原始输出（渲染用）

class BaseTool(ABC):
    # 子类必须定义
    name: str = ''
    description: str = ''
    input_schema: dict = {}

    # 子类可覆盖的行为标志（对应 TOOL_DEFAULTS）
    is_concurrency_safe: bool = False
    is_read_only: bool = False
    is_destructive: bool = False
    is_search_or_read: bool = False
    max_result_size_chars: int | None = None

    @abstractmethod
    async def call(self, args: dict, context: dict) -> ToolResult:
        """工具的实际执行逻辑。"""
        ...

    def check_permissions(self, args: dict, context: dict) -> str | None:
        """
        工具级权限检查（通用规则引擎之外的补充）。
        返回 None 表示允许，返回字符串表示拒绝原因。
        """
        return None

    def validate_input(self, args: dict) -> str | None:
        """输入验证（失败直接报错，不触发权限询问）。"""
        return None

    def get_activity_description(self, args: dict) -> str:
        return f'Running {self.name}'

    def to_api_definition(self) -> dict:
        return {
            'name': self.name,
            'description': self.description,
            'input_schema': self.input_schema,
        }

def build_tool(cls: type) -> type:
    """工厂函数：设置未覆盖的默认值（对应 buildTool() 的行为）。"""
    for attr, default in {
        'is_concurrency_safe': False,
        'is_read_only': False,
        'is_destructive': False,
        'is_search_or_read': False,
    }.items():
        if not hasattr(cls, attr):
            setattr(cls, attr, default)
    return cls
```

### Bash AST 安全分析

**原版**：tree-sitter NAPI 原生模块，精确 AST 解析。
**Python 版**：正则近似，功能等价但精度略低。

```python
# utils/bash_analysis.py
import re
from dataclasses import dataclass, field

@dataclass
class CompoundStructure:
    has_compound_operators: bool = False  # &&, ||, ;
    has_pipeline: bool = False
    has_subshell: bool = False            # $() 或反引号
    has_command_group: bool = False

@dataclass
class DangerousPatterns:
    has_command_substitution: bool = False  # $() 或反引号
    has_process_substitution: bool = False  # <() 或 >()
    has_parameter_expansion: bool = False   # ${...}
    has_heredoc: bool = False
    has_comment: bool = False

@dataclass
class BashAnalysis:
    unquoted: str                # 去除所有引号内容后的命令文本
    compound: CompoundStructure
    dangerous: DangerousPatterns

    @property
    def is_risky(self) -> bool:
        return (self.dangerous.has_command_substitution
                or self.dangerous.has_process_substitution)

def analyze(cmd: str) -> BashAnalysis:
    # 去除引号内容（近似）
    uq = re.sub(r"'[^']*'|\"[^\"]*\"", '', cmd)
    compound = CompoundStructure(
        has_compound_operators=bool(re.search(r'&&|[|][|]|;', uq)),
        has_pipeline=bool(re.search(r'[^|][|][^|]', uq)),
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
    return BashAnalysis(unquoted=uq, compound=compound, dangerous=dangerous)
```

---

## 阶段 J：内置工具集（核心 7 个）

**原版文件**：`src/tools/`（56 个工具，~51,000 行）

Python 版本优先实现最核心的 7 个工具：

| 工具 | 原版文件 | 说明 |
|------|---------|------|
| `Bash` | `BashTool/` | Shell 命令执行（最复杂） |
| `Read` | `FileReadTool/` | 读取文件内容 |
| `Edit` | `FileEditTool/` | 字符串精确替换 |
| `Write` | `FileWriteTool/` | 写入文件 |
| `Glob` | `GlobTool/` | 文件路径匹配 |
| `Grep` | `GrepTool/` | 内容搜索 |
| `Agent` | `AgentTool/` | 派生子 Agent |

```python
# tools/bash_tool.py
import asyncio, subprocess, os, signal
from tools.base import BaseTool, ToolResult
from utils.bash_analysis import analyze

class BashTool(BaseTool):
    name = 'Bash'
    description = 'Execute shell commands'
    is_concurrency_safe = False   # bash 命令会修改状态，串行执行
    is_read_only = False
    input_schema = {
        'type': 'object',
        'properties': {
            'command': {'type': 'string', 'description': 'Shell command to execute'},
            'timeout': {'type': 'number', 'description': 'Timeout in seconds (max 120)'},
        },
        'required': ['command'],
    }

    async def call(self, args: dict, context: dict) -> ToolResult:
        command = args['command']
        timeout = min(args.get('timeout', 30), 120)

        # 安全分析（记录但不阻止）
        analysis = analyze(command)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=context.get('cwd', '.'),
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(
                    content=f'Command timed out after {timeout}s',
                    is_error=True,
                )
            output = stdout.decode('utf-8', errors='replace')
            if stderr:
                err = stderr.decode('utf-8', errors='replace')
                output += f'\nSTDERR:\n{err}'
            if proc.returncode != 0:
                return ToolResult(content=output or f'Exit code {proc.returncode}',
                                   is_error=True)
            return ToolResult(content=output or '(no output)')
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)

# tools/file_read.py
class FileReadTool(BaseTool):
    name = 'Read'
    description = 'Read file contents'
    is_concurrency_safe = True
    is_read_only = True
    is_search_or_read = True
    input_schema = {
        'type': 'object',
        'properties': {
            'file_path': {'type': 'string'},
            'offset': {'type': 'integer', 'description': 'Start line (1-based)'},
            'limit': {'type': 'integer', 'description': 'Max lines to read'},
        },
        'required': ['file_path'],
    }

    async def call(self, args: dict, context: dict) -> ToolResult:
        path = args['file_path']
        offset = args.get('offset', 0)
        limit = args.get('limit', 2000)
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            if offset:
                lines = lines[offset-1:]
            lines = lines[:limit]
            # 加行号（类似 cat -n 格式）
            numbered = ''.join(f'{i+offset:4d}\t{line}' for i, line in enumerate(lines, 1))
            return ToolResult(content=numbered)
        except FileNotFoundError:
            return ToolResult(content=f'File not found: {path}', is_error=True)
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)
```

工具注册表：

```python
# tools/registry.py
from tools.bash_tool import BashTool
from tools.file_read import FileReadTool
# ... 其他工具

BUILTIN_TOOLS: list[type] = [
    BashTool,
    FileReadTool,
    # FileEditTool, FileWriteTool, GlobTool, GrepTool, AgentTool,
    # TodoReadTool, TodoWriteTool, WebFetchTool, WebSearchTool,
    # ... 56 个工具全部列出
]

def get_all_tools(include_mcp: bool = True) -> list:
    tools = [cls() for cls in BUILTIN_TOOLS]
    # MCP 工具动态添加（Phase P 完成后）
    return tools

def find_tool(name: str, tools: list) -> object | None:
    for tool in tools:
        if tool.name.lower() == name.lower():
            return tool
    return None
```

---

## 阶段 K：Context Window 管理（压缩策略）

**原版文件**：`src/services/compact/`（autoCompact、microCompact、snipCompact）

### 压缩链（降级策略）

```
检测到 token 数接近上限
  ↓
1. snipCompact   → ⚠️ 原版为 STUB（永远 executed=false）
  ↓ 未释放足够空间
2. microCompact  → 替换旧 tool_result 为占位符
  ↓ 仍不足
3. autoCompact   → 全量摘要压缩（发给 Claude 生成摘要）
  ↓ 失败 3 次
4. 熔断器        → 抛出错误，停止对话
```

### 关键常量

```python
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000   # 摘要输出预留
AUTOCOMPACT_BUFFER_TOKENS = 13_000       # 安全缓冲
MAX_CONSECUTIVE_FAILURES = 3             # 熔断阈值

MODEL_CONTEXT_WINDOWS = {
    'claude-opus-4-6':   200_000,
    'claude-sonnet-4-6': 200_000,
    'claude-haiku-4-5':  200_000,
}

# Claude Opus 4.6 的触发阈值：
# effectiveWindow = 200000 - 20000 = 180000
# threshold = 180000 - 13000 = 167000 tokens

COMPACTABLE_TOOLS = {
    'file_read', 'bash', 'grep', 'glob',
    'web_search', 'web_fetch', 'file_edit', 'file_write',
}
MC_CLEARED_MESSAGE = '[Old tool result content cleared]'
IMAGE_MAX_TOKEN_SIZE = 2000  # 图片超过此 token 数也被清除
```

### Python 实现

```python
# services/compact.py
from utils.messages import rough_token_count, get_messages_token_count

MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
AUTOCOMPACT_BUFFER_TOKENS = 13_000
MAX_CONSECUTIVE_FAILURES = 3
MC_CLEARED_MESSAGE = '[Old tool result content cleared]'
COMPACTABLE_TOOLS = {
    'file_read', 'Read', 'bash', 'Bash', 'grep', 'Grep',
    'glob', 'Glob', 'web_search', 'web_fetch',
    'file_edit', 'Edit', 'file_write', 'Write',
}

MODEL_CONTEXT_WINDOWS = {
    'claude-opus-4-6':   200_000,
    'claude-sonnet-4-6': 200_000,
    'claude-haiku-4-5':  200_000,
}

def get_autocompact_threshold(model: str) -> int:
    context_window = MODEL_CONTEXT_WINDOWS.get(model, 200_000)
    effective = context_window - MAX_OUTPUT_TOKENS_FOR_SUMMARY
    return effective - AUTOCOMPACT_BUFFER_TOKENS

def snip_compact(messages: list[dict]) -> tuple[list[dict], bool]:
    """
    snipCompact：在原版中是 STUB，永远返回 executed=False。
    Python 版本同样保持 STUB 行为，以便与原版行为一致。
    """
    return messages, False  # (messages, executed)

def micro_compact(messages: list[dict], keep_recent_turns: int = 10) -> list[dict]:
    """
    microCompact：将旧的 tool_result 内容替换为占位符。
    只替换距末尾超过 keep_recent_turns 轮的结果。
    """
    # 找到所有 user 消息（tool_result 在 user 消息里）
    user_indices = [i for i, m in enumerate(messages) if m['role'] == 'user']
    cutoff = len(user_indices) - keep_recent_turns
    old_user_indices = set(user_indices[:max(0, cutoff)])

    result = []
    for i, msg in enumerate(messages):
        if i in old_user_indices and isinstance(msg.get('content'), list):
            new_content = []
            for block in msg['content']:
                if (isinstance(block, dict)
                        and block.get('type') == 'tool_result'
                        and _tool_is_compactable(block)):
                    new_content.append({**block, 'content': MC_CLEARED_MESSAGE})
                else:
                    new_content.append(block)
            result.append({**msg, 'content': new_content})
        else:
            result.append(msg)
    return result

def _tool_is_compactable(block: dict) -> bool:
    # tool_result block 没有直接的 tool_name，需要从 tool_use_id 追踪
    # 简化：按内容大小判断（超过 IMAGE_MAX_TOKEN_SIZE 也压缩）
    content = block.get('content', '')
    if isinstance(content, str):
        return rough_token_count(content) > 500  # 超过 500 token 的结果才压缩
    return False

async def auto_compact(messages: list[dict], model: str,
                        query_fn) -> tuple[list[dict], bool]:
    """
    autoCompact：调用 Claude 生成摘要，替换整个对话历史。
    query_fn: async (messages, system_prompt) -> str
    """
    summary_prompt = (
        'Please provide a comprehensive summary of our conversation above. '
        'Include: key decisions made, files modified, current state of work, '
        'errors encountered and their fixes, and next steps. '
        'Be detailed but concise.'
    )
    try:
        summary = await query_fn(messages, summary_prompt)
        compacted = [
            {'role': 'user', 'content': f'[Previous conversation summary]\n{summary}'},
            {'role': 'assistant', 'content': 'I understand. I\'ll continue from where we left off.'},
        ]
        return compacted, True
    except Exception:
        return messages, False

class CompactManager:
    def __init__(self, model: str):
        self._model = model
        self._failures = 0
        self._threshold = get_autocompact_threshold(model)

    def needs_compact(self, messages: list[dict]) -> bool:
        return get_messages_token_count(messages) > self._threshold

    async def compact(self, messages: list[dict], query_fn) -> list[dict]:
        if self._failures >= MAX_CONSECUTIVE_FAILURES:
            raise RuntimeError('Compaction failed too many times, stopping.')

        # 1. snip（STUB）
        messages, snipped = snip_compact(messages)

        # 2. micro
        if not snipped:
            messages = micro_compact(messages)

        # 3. auto
        if self.needs_compact(messages):
            messages, ok = await auto_compact(messages, self._model, query_fn)
            if not ok:
                self._failures += 1
            else:
                self._failures = 0

        return messages
```

---

## 阶段 L：并发工具执行器

**原版文件**：`src/services/tools/StreamingToolExecutor.ts`（530 行）

### 并发控制规则

```
isConcurrencySafe=True  → 可与其他 safe 工具并行执行
isConcurrencySafe=False → 独占执行（等所有其他工具完成后才开始）
siblingAbortController → 某个工具出错时，取消所有同组工具（但不取消整轮对话）
```

### 工具状态机

```
queued → executing → completed → yielded
```

### Python 实现

```python
# core/tool_orchestrator.py
import asyncio, json
from dataclasses import dataclass, field
from tools.registry import find_tool
from utils.messages import build_tool_result_block, build_tool_use_block

@dataclass
class TrackedTool:
    index: int
    tool_id: str
    tool_name: str
    input_json: str = ''       # 累积的 input_json_delta
    status: str = 'queued'     # queued → executing → completed
    result: dict | None = None
    task: asyncio.Task | None = None
    is_concurrency_safe: bool = False

async def execute_streaming_turn(stream, tools: list, context: dict,
                                  on_text=None) -> tuple[list, list]:
    """
    消费 SSE 流，并发执行工具，返回 (assistant_content_blocks, tool_results)。
    on_text: 可选回调，实时接收文本 delta。
    """
    tracked: dict[int, TrackedTool] = {}   # index → TrackedTool
    text_blocks: list[dict] = []
    current_text = ''
    current_block_index: int | None = None
    sibling_abort = asyncio.Event()

    async def run_tool(tt: TrackedTool) -> None:
        tt.status = 'executing'
        try:
            tool_cls = find_tool(tt.tool_name, tools)
            if tool_cls is None:
                tt.result = build_tool_result_block(
                    tt.tool_id, f'Unknown tool: {tt.tool_name}', is_error=True)
                return
            args = json.loads(tt.input_json) if tt.input_json else {}
            result = await tool_cls.call(args, context)
            content = result.content if isinstance(result.content, str) else json.dumps(result.content)
            tt.result = build_tool_result_block(tt.tool_id, content, result.is_error)
        except Exception as e:
            tt.result = build_tool_result_block(tt.tool_id, str(e), is_error=True)
        finally:
            tt.status = 'completed'

    async for event in stream:
        etype = event.get('type')

        if etype == 'content_block_start':
            block = event.get('content_block', {})
            idx = event.get('index', 0)
            if block.get('type') == 'tool_use':
                tracked[idx] = TrackedTool(
                    index=idx,
                    tool_id=block.get('id', ''),
                    tool_name=block.get('name', ''),
                )
                tool_obj = find_tool(block.get('name', ''), tools)
                if tool_obj:
                    tracked[idx].is_concurrency_safe = tool_obj.is_concurrency_safe
            elif block.get('type') == 'text':
                current_block_index = idx
                current_text = ''

        elif etype == 'content_block_delta':
            delta = event.get('delta', {})
            idx = event.get('index', 0)
            if delta.get('type') == 'text_delta':
                text = delta.get('text', '')
                current_text += text
                if on_text:
                    on_text(text)
            elif delta.get('type') == 'input_json_delta':
                if idx in tracked:
                    tracked[idx].input_json += delta.get('partial_json', '')

        elif etype == 'content_block_stop':
            idx = event.get('index', 0)
            if current_block_index == idx and current_text:
                text_blocks.append({'type': 'text', 'text': current_text})
                current_text = ''
                current_block_index = None
            if idx in tracked:
                tt = tracked[idx]
                # 区分并发/串行工具
                if tt.is_concurrency_safe:
                    tt.task = asyncio.create_task(run_tool(tt))
                else:
                    # 等所有已有任务完成后再串行执行
                    existing = [t.task for t in tracked.values()
                                 if t.task is not None and not t.task.done()]
                    if existing:
                        await asyncio.gather(*existing)
                    await run_tool(tt)

    # 等待所有并发任务
    pending = [t.task for t in tracked.values()
                if t.task is not None and not t.task.done()]
    if pending:
        await asyncio.gather(*pending)

    # 构造工具调用 content blocks
    tool_use_blocks = [
        build_tool_use_block(tt.tool_id, tt.tool_name,
                              json.loads(tt.input_json) if tt.input_json else {})
        for tt in sorted(tracked.values(), key=lambda x: x.index)
    ]
    tool_results = [tt.result for tt in sorted(tracked.values(), key=lambda x: x.index)
                     if tt.result is not None]

    assistant_content = text_blocks + tool_use_blocks
    return assistant_content, tool_results
```

---

## 阶段 M：系统提示构建

**原版文件**：`src/context.ts`，`src/utils/claudemd.ts`

### 7 部分系统提示

```
1. 日期时间         → "Today's date: 2026-04-06"
2. 工作目录         → "Working directory: /home/user/project"
3. CLAUDE.md 文件   → 从 cwd 向上遍历，找到所有 .claude/CLAUDE.md
4. 内存文件         → ~/.claude/CLAUDE.md（用户全局指令）
5. Git 状态         → 当前分支、未提交变更摘要
6. 工具列表         → 可用工具的描述（供 Claude 选择）
7. 权限信息         → 当前权限模式和规则摘要
```

### CLAUDE.md 发现算法

```
从 cwd 开始向上遍历目录树 → 遇到 .git 停止
每个目录检查：
  - .claude/CLAUDE.md（项目级）
  - CLAUDE.md（项目根）
最终加上 ~/.claude/CLAUDE.md（全局级，最低优先级）
支持 @path/to/file.md 语法（内联引用其他 markdown，安全验证）
```

### Python 实现

```python
# context.py
import os, subprocess
from pathlib import Path
from datetime import date

def build_system_prompt(tools: list, permission_mode: str = 'default',
                         additional_dirs: list[str] | None = None) -> str:
    parts = [
        f"Today's date: {date.today().isoformat()}",
        f"Working directory: {os.getcwd()}",
    ]

    # CLAUDE.md 文件
    for path, content in find_claude_md_files():
        parts.append(f"# Instructions from {path}\n{content}")

    # Git 状态
    git_info = get_git_info()
    if git_info:
        parts.append(git_info)

    # 权限模式提示
    if permission_mode != 'default':
        parts.append(f'Permission mode: {permission_mode}')
    if additional_dirs:
        parts.append(f'Additional allowed directories: {", ".join(additional_dirs)}')

    return '\n\n'.join(parts)

def find_claude_md_files() -> list[tuple[str, str]]:
    """从 cwd 向上查找所有 CLAUDE.md / .claude/CLAUDE.md 文件。"""
    found = []
    cwd = Path.cwd()
    home = Path.home()

    # 全局（最低优先级，先加载）
    global_md = home / '.claude' / 'CLAUDE.md'
    if global_md.exists():
        found.append((str(global_md), global_md.read_text(encoding='utf-8')))

    # 从 cwd 向上到 git root 或 home
    search_dirs = [cwd] + list(cwd.parents)
    for d in reversed(search_dirs):
        for candidate in [d / 'CLAUDE.md', d / '.claude' / 'CLAUDE.md']:
            if candidate.exists() and str(candidate) not in [p for p, _ in found]:
                found.append((str(candidate), candidate.read_text(encoding='utf-8')))
        if (d / '.git').exists() or d == home:
            break

    return found

def get_git_info() -> str:
    """获取当前 git 状态摘要。"""
    try:
        branch = subprocess.check_output(
            ['git', 'branch', '--show-current'],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        status = subprocess.check_output(
            ['git', 'status', '--short'],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        if branch:
            result = f'Git branch: {branch}'
            if status:
                result += f'\nUncommitted changes:\n{status}'
            return result
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return ''
```

---

## 阶段 N：会话记忆

**原版文件**：`src/services/SessionMemory/`（~1,026 行）

### 核心概念

会话结束时，由 Claude 调用 Edit 工具更新笔记文件（`~/.claude/session_memory/<session_id>.md`），新会话开始时将摘要注入系统提示。

### 关键常量

```python
MAX_SECTION_LENGTH = 2000              # 每个 section 最大 token 数
MAX_TOTAL_SESSION_MEMORY_TOKENS = 12000  # 总记忆上限
```

### 10 个固定 Section（不可增删）

```
Session Title / Current State / Task specification / Files and Functions
/ Workflow / Errors & Corrections / Codebase and System Documentation
/ Learnings / Key results / Worklog
```

### Python 实现

```python
# services/session_memory.py
from pathlib import Path
from bootstrap.state import get_session_id

MAX_SECTION_LENGTH = 2000
MAX_TOTAL_SESSION_MEMORY_TOKENS = 12_000

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
_The exact output the user requested._

# Worklog
_Step by step, what was attempted and done?_
"""

def get_memory_path(session_id: str | None = None) -> Path:
    sid = session_id or get_session_id()
    return Path.home() / '.claude' / 'session_memory' / f'{sid}.md'

def init_memory(session_id: str | None = None) -> Path:
    path = get_memory_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(SESSION_MEMORY_TEMPLATE, encoding='utf-8')
    return path

def load_memory(session_id: str | None = None) -> str | None:
    path = get_memory_path(session_id)
    return path.read_text(encoding='utf-8') if path.exists() else None

def build_memory_context(session_id: str | None = None) -> str:
    """将会话记忆注入系统提示的格式。"""
    content = load_memory(session_id)
    if not content:
        return ''
    return f'# Previous Session Memory\n{content}'

def build_update_prompt(notes_path: Path, current_notes: str) -> str:
    """生成让 Claude 更新笔记的 prompt（对应原版 getDefaultUpdatePrompt）。"""
    return (
        f'IMPORTANT: Update the session notes file at {notes_path}.\n'
        f'Current contents:\n{current_notes}\n\n'
        f'Rules:\n'
        f'- Only update content below italic _description_ lines\n'
        f'- Never modify section headers or italic descriptions\n'
        f'- Keep each section under {MAX_SECTION_LENGTH} tokens\n'
        f'- Always update Current State to reflect latest work\n'
        f'Use the Edit tool, then stop.'
    )
```

---

## 阶段 O：CLI 打印模式

**原版文件**：`src/cli/print.ts`（~5,604 行）

### 3 种输出格式

```bash
# text（默认）— 流式输出纯文本
$ echo "hello" | python -m my_claude -p
Hello! ...

# json — 结束时输出一条 JSON
$ echo "hello" | python -m my_claude -p --output-format json
{"type":"result","subtype":"success","result":"Hello!","session_id":"...","cost_usd":0.001}

# stream-json — 每个事件一行 JSON
$ echo "hello" | python -m my_claude -p --output-format stream-json
{"type":"text_delta","text":"Hello"}
{"type":"result","subtype":"success","result":"Hello!"}
```

### Python 实现

```python
# cli/print_mode.py
import sys, json
from dataclasses import dataclass

@dataclass
class PrintConfig:
    output_format: str = 'text'  # 'text' | 'json' | 'stream-json'
    verbose: bool = False
    max_turns: int = 10

class PrintOutput:
    def __init__(self, config: PrintConfig):
        self.config = config
        self._result_text = ''

    def on_text_delta(self, text: str) -> None:
        self._result_text += text
        if self.config.output_format == 'text':
            sys.stdout.write(text)
            sys.stdout.flush()
        elif self.config.output_format == 'stream-json':
            print(json.dumps({'type': 'text_delta', 'text': text}), flush=True)

    def on_tool_use(self, name: str, input_: dict) -> None:
        if self.config.output_format == 'stream-json':
            print(json.dumps({'type': 'tool_use', 'name': name, 'input': input_}), flush=True)

    def on_tool_result(self, tool_use_id: str, content: str) -> None:
        if self.config.output_format == 'stream-json':
            print(json.dumps({'type': 'tool_result', 'tool_use_id': tool_use_id,
                               'content': content[:500]}), flush=True)

    def on_done(self, session_id: str, cost_usd: float, stop_reason: str = 'end_turn') -> None:
        result_obj = {
            'type': 'result',
            'subtype': 'success' if stop_reason != 'error' else 'error',
            'result': self._result_text,
            'session_id': session_id,
            'cost_usd': cost_usd,
        }
        if self.config.output_format == 'text':
            if not self._result_text.endswith('\n'):
                print()  # 确保最后有换行
        elif self.config.output_format in ('json', 'stream-json'):
            print(json.dumps(result_obj))
```

---

## 阶段 P：MCP 协议

**原版文件**：`src/services/mcp/`（~12,242 行），`src/tools/MCPTool/`

### 架构分层

```
Claude API (tool_use blocks)
    ↓
MCPTool（统一适配器：将 MCP 工具包装成内部 BaseTool）
    ↓
MCPClient（连接池，每个服务器一个）
    ↓
transport 层
  stdio → 子进程（本地工具如 github-mcp-server）
  SSE   → HTTP 流（远程 MCP 服务器）
```

### settings.json 配置格式

```json
{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    },
    "remote": {
      "type": "sse",
      "url": "https://my-mcp-server.com/sse",
      "headers": {"Authorization": "Bearer ${TOKEN}"}
    }
  }
}
```

### 工具发现流程

```
startup → for each mcpServer in config:
    client.connect()         # 启动子进程 / 建立 HTTP 连接
    tools = client.list_tools()  # MCP initialize → tools/list
    register(MCPTool(tool, client))  # 包装成 BaseTool
→ MCP 工具与内置工具合并到 tools 列表
```

### Python 实现

```python
# services/mcp/client.py
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tools.base import BaseTool, ToolResult

class MCPClient:
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self._session: ClientSession | None = None

    async def connect(self) -> None:
        if self.config.get('type') == 'stdio':
            params = StdioServerParameters(
                command=self.config['command'],
                args=self.config.get('args', []),
                env={**__import__('os').environ, **self.config.get('env', {})},
            )
            self._cm = stdio_client(params)
            self._read, self._write = await self._cm.__aenter__()
            self._sess_cm = ClientSession(self._read, self._write)
            self._session = await self._sess_cm.__aenter__()
            await self._session.initialize()

    async def list_tools(self) -> list[dict]:
        result = await self._session.list_tools()
        return [{
            'mcp_server': self.name,
            'mcp_name': t.name,
            'full_name': f'mcp__{self.name}__{t.name}',
            'description': t.description or '',
            'input_schema': t.inputSchema or {'type': 'object', 'properties': {}},
        } for t in result.tools]

    async def call_tool(self, tool_name: str, tool_input: dict) -> str:
        result = await self._session.call_tool(tool_name, tool_input)
        return '\n'.join(c.text for c in result.content if hasattr(c, 'text'))

    async def disconnect(self) -> None:
        if self._session:
            await self._sess_cm.__aexit__(None, None, None)
        if hasattr(self, '_cm'):
            await self._cm.__aexit__(None, None, None)

class MCPTool(BaseTool):
    """将 MCP 工具包装为内部 BaseTool。"""
    is_concurrency_safe = True  # MCP 工具默认可并行（服务器自己处理并发）

    def __init__(self, tool_def: dict, client: MCPClient):
        self.name = tool_def['full_name']
        self.description = tool_def['description']
        self.input_schema = tool_def['input_schema']
        self._client = client
        self._mcp_name = tool_def['mcp_name']

    async def call(self, args: dict, context: dict) -> ToolResult:
        try:
            result = await self._client.call_tool(self._mcp_name, args)
            return ToolResult(content=result)
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)

# services/mcp/registry.py
class MCPRegistry:
    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._tools: list[MCPTool] = []

    async def connect_all(self, mcp_servers: dict) -> None:
        for name, config in mcp_servers.items():
            client = MCPClient(name, config)
            try:
                await client.connect()
                tools = await client.list_tools()
                for tool_def in tools:
                    self._tools.append(MCPTool(tool_def, client))
                self._clients[name] = client
            except Exception as e:
                print(f'[MCP] Failed to connect to {name}: {e}')

    def get_tools(self) -> list[MCPTool]:
        return self._tools

    async def disconnect_all(self) -> None:
        for client in self._clients.values():
            await client.disconnect()
```

---

## 阶段 Q：多 Agent + 任务系统

**原版文件**：`src/tools/AgentTool/`，`src/tasks/`（~3,317 行），`src/utils/forkedAgent.ts`

### 4 种 fork 模式

| 模式 | 说明 | 实现方式 |
|------|------|---------|
| `subagent` | 同步等待子任务 | `await run_task(prompt)` |
| `background` | 异步不等结果 | `asyncio.create_task(...)` |
| `worktree` | 独立 git worktree | `git worktree add` + 子进程 |
| `remote` | 远程环境（Bridge）| 暂不实现 |

### 7 种后台任务类型

```python
# tasks/types.py
TaskType = (
    'local_shell'       # 本地 shell 命令
    | 'local_agent'     # 本地 Claude agent 子任务
    | 'remote_agent'    # 远程（Bridge）agent
    | 'in_process'      # 进程内队友（Swarm）
    | 'local_workflow'  # 本地工作流
    | 'monitor_mcp'     # 监控 MCP 服务器
    | 'dream'           # Dream 模式（feature flag 关闭）
)
```

### Python 实现

```python
# tools/agent_tool.py
import asyncio, subprocess, tempfile, os
from tools.base import BaseTool, ToolResult

class AgentTool(BaseTool):
    name = 'Agent'
    description = 'Run a subagent to complete a subtask'
    is_concurrency_safe = True  # 多个子 agent 可并行
    input_schema = {
        'type': 'object',
        'properties': {
            'prompt': {'type': 'string', 'description': 'Task for the subagent'},
            'mode': {
                'type': 'string',
                'enum': ['subagent', 'background', 'worktree'],
                'default': 'subagent',
            },
            'branch_name': {'type': 'string', 'description': 'Branch for worktree mode'},
        },
        'required': ['prompt'],
    }

    async def call(self, args: dict, context: dict) -> ToolResult:
        prompt = args['prompt']
        mode = args.get('mode', 'subagent')

        if mode == 'subagent':
            return await self._run_subagent(prompt, context)
        elif mode == 'background':
            asyncio.create_task(self._run_subagent(prompt, context))
            return ToolResult(content='Subagent started in background')
        elif mode == 'worktree':
            branch = args.get('branch_name', f'agent-{__import__("uuid").uuid4().hex[:8]}')
            return await self._run_worktree(prompt, context, branch)
        return ToolResult(content=f'Unknown mode: {mode}', is_error=True)

    async def _run_subagent(self, prompt: str, context: dict) -> ToolResult:
        from core.query import run_conversation
        try:
            result = await run_conversation(
                initial_prompt=prompt,
                cwd=context.get('cwd', os.getcwd()),
                max_turns=context.get('max_turns', 10),
            )
            return ToolResult(content=result)
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)

    async def _run_worktree(self, prompt: str, context: dict, branch: str) -> ToolResult:
        base_dir = context.get('cwd', os.getcwd())
        worktree_path = tempfile.mkdtemp(prefix=f'claude-wt-{branch}-')
        try:
            subprocess.run(
                ['git', 'worktree', 'add', '-b', branch, worktree_path],
                cwd=base_dir, check=True, capture_output=True
            )
            result = await self._run_subagent(prompt, {**context, 'cwd': worktree_path})
            return result
        except subprocess.CalledProcessError as e:
            return ToolResult(content=f'git worktree failed: {e.stderr}', is_error=True)
        finally:
            subprocess.run(['git', 'worktree', 'remove', '--force', worktree_path],
                           cwd=base_dir, capture_output=True)
```

---

## 阶段 R：Textual TUI（可选）

**原版文件**：`src/screens/REPL.tsx`，`src/ink/`（自定义 Ink 框架），`src/components/`

### 对应关系

| 原版（React/Ink）| Python（Textual）|
|----------------|----------------|
| `REPL.tsx` | `ui/app.py::ClaudeApp` |
| `Messages.tsx` | `ui/app.py::MessageList(RichLog)` |
| `PromptInput/` | `ui/app.py::PromptInput(Input)` |
| `useVirtualScroll` | Textual 内置虚拟滚动 |
| 工具权限弹窗 | `PermissionModal` |

```python
# ui/app.py
from textual.app import App, ComposeResult
from textual.widgets import Input, RichLog, Static, Label
from textual.reactive import reactive
from textual.binding import Binding

class MessageList(RichLog):
    """对应 Messages.tsx，支持 Markdown 和代码高亮。"""
    pass

class StatusBar(Static):
    """底部状态栏：token 用量、费用、模型名。"""
    cost: reactive[float] = reactive(0.0)
    tokens: reactive[int] = reactive(0)

    def render(self) -> str:
        return f'Tokens: {self.tokens} | Cost: ${self.cost:.4f}'

class ClaudeApp(App):
    BINDINGS = [
        Binding('ctrl+c', 'quit', 'Quit'),
        Binding('escape', 'cancel', 'Cancel'),
    ]
    CSS = """
    MessageList { height: 1fr; border: solid $panel; }
    StatusBar { height: 1; background: $panel; }
    Input.prompt { dock: bottom; }
    """

    def compose(self) -> ComposeResult:
        yield MessageList(id='messages', highlight=True, markup=True)
        yield StatusBar(id='status')
        yield Input(placeholder='Message Claude...', classes='prompt')

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_text = event.value.strip()
        if not user_text:
            return
        event.input.clear()
        msgs = self.query_one('#messages', MessageList)
        msgs.write(f'[bold cyan]You:[/] {user_text}')
        await self._run_turn(user_text, msgs)

    async def _run_turn(self, prompt: str, msgs: MessageList) -> None:
        # 调用 core/tool_orchestrator.py 的并发执行器
        msgs.write('[bold green]Claude:[/] ', end='')
        def on_text(text: str):
            msgs.write(text, end='', animate=False)
        # ... 完整实现见 Phase L 集成
```

---

## 阶段 S：Buddy 伴侣系统（可选）

**原版文件**：`src/buddy/`

### 核心算法摘要

```
userId + SALT('friend-2026-401') → FNV-1a hash → Mulberry32 PRNG seed
→ roll_rarity()   → 5 种稀有度（common 60% ... legendary 1%）
→ roll_species()  → 18 种物种（duck, goose, blob, ...）
→ roll_stats()    → 5 种属性（DEBUGGING, PATIENCE, CHAOS, WISDOM, SNARK）
→ roll_shiny()    → 1% 概率闪光
存储：只存 name + personality（外观每次从 hash 重新生成，防止用户刷稀有度）
```

完整代码见 PLAN_V2_DEEP.md 模块九，Python 实现完全对应原版算法。

---

## 阶段 T：Swarm 多 Agent 协调（可选）

**原版文件**：`src/utils/swarm/`（~7,548 行）

基于 tmux 的多 Claude 实例协调：team-lead 控制多个 teammate 并行工作。

关键常量：
```python
TEAM_LEAD_NAME = 'team-lead'
SWARM_SESSION_NAME = 'claude-swarm'
TEAMMATE_COLOR_ENV_VAR = 'CLAUDE_CODE_AGENT_COLOR'
PLAN_MODE_REQUIRED_ENV_VAR = 'CLAUDE_CODE_PLAN_MODE_REQUIRED'
# swarm socket: f'claude-swarm-{os.getpid()}'（每个进程独立）
```

Python 替代方案：用 asyncio 子进程替代 tmux，更简洁但失去终端可视化。

---

## 阶段 U：OAuth 2.0 认证（可选）

**原版文件**：`src/services/oauth/`（~1,077 行）

PKCE 流程：
```
生成 code_verifier → SHA256 → code_challenge
→ 打开浏览器（授权页）
→ 本地 HTTP 监听器接收 authorization_code
→ code + code_verifier 换取 access_token + refresh_token
→ 保存到 ~/.claude/credentials.json（chmod 600）
```

大多数场景直接用 `ANTHROPIC_API_KEY` 环境变量，OAuth 仅用于 Web 登录。

---

## 附件：附件系统

**原版文件**：`src/utils/attachments.ts`（~3,999 行）

```python
# utils/attachments.py
import base64, mimetypes
from pathlib import Path

SUPPORTED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}

def file_to_content_block(path: Path) -> dict:
    mime, _ = mimetypes.guess_type(str(path))
    data = path.read_bytes()
    if mime in SUPPORTED_IMAGE_TYPES:
        return {'type': 'image', 'source': {
            'type': 'base64', 'media_type': mime,
            'data': base64.standard_b64encode(data).decode(),
        }}
    elif mime == 'application/pdf':
        return {'type': 'document', 'source': {
            'type': 'base64', 'media_type': mime,
            'data': base64.standard_b64encode(data).decode(),
        }}
    else:
        text = data.decode('utf-8', errors='replace')
        return {'type': 'text', 'text': f'<file path="{path.name}">\n{text}\n</file>'}
```

---

## 总结：完整覆盖矩阵

| 阶段 | 模块 | 原版代码量 | Python 文件 | 状态 |
|------|------|-----------|------------|------|
| A | SSE + HTTP 客户端 | ~3,000 | core/ | ✅ 完成 |
| B | 消息格式化 | ~5,556 | utils/messages.py | 待实现 |
| C | Bootstrap 全局状态 | ~2,000 | bootstrap/state.py | 待实现 |
| D | 会话持久化（JSONL）| ~5,106 | utils/session_storage.py | 待实现 |
| E | 配置系统（5层 Settings）| ~10,000 | config/ | 待实现 |
| F | 技能/斜杠命令 | ~4,080 | config/skills.py | 待实现 |
| G | 权限规则引擎 | ~3,000 | permissions/rule_engine.py | 待实现 |
| H | Hook 系统（27事件/4类型）| ~5,121 | services/hooks.py | 待实现 |
| I | 工具基类 + Bash AST | ~13,000 | tools/base.py, utils/bash_analysis.py | 待实现 |
| J | 内置工具集（核心7个）| ~51,000（全56个）| tools/*.py | 待实现 |
| K | Context window 管理 | ~8,000 | services/compact.py | 待实现 |
| L | 并发工具执行器 | ~3,000 | core/tool_orchestrator.py | 待实现 |
| M | 系统提示构建 | ~5,000 | context.py | 待实现 |
| N | 会话记忆（MAX 12k tokens）| ~1,026 | services/session_memory.py | 待实现 |
| O | CLI 打印/pipe 模式 | ~5,604 | cli/print_mode.py | 待实现 |
| P | MCP 协议（stdio/SSE）| ~12,242 | services/mcp/ | 待实现 |
| Q | 多 Agent + 任务系统 | ~11,000 | tools/agent_tool.py, tasks/ | 待实现 |
| R | Textual TUI | ~82,000（简化）| ui/app.py | 可选 |
| S | Buddy 伴侣系统 | ~3,000 | buddy/ | 可选 |
| T | Swarm 多 Agent | ~7,548 | utils/swarm/ | 可选 |
| U | OAuth 认证 | ~1,077 | services/oauth.py | 可选 |
| - | 附件系统 | ~3,999 | utils/attachments.py | 随 R 实现 |
| **合计** | **全部模块** | **~150,000** | **~30 个文件** | **规划完成** |

