"""
权限系统（对应原版 src/permissions/ + src/types/permissions.ts）

原版有五种模式：
  acceptEdits      - 自动允许文件编辑，bash 仍需确认
  bypassPermissions - 跳过所有确认（危险）
  default          - 默认：只读操作自动允许，bash 和写操作询问
  dontAsk          - 不询问，全部允许（等同 bypass）
  plan             - 计划模式：所有工具执行前都询问

Python 实现简化为三档：
  default  - 只读工具自动允许，bash 询问，文件写/编辑询问
  plan     - 所有工具都询问
  bypass   - 跳过所有询问（YOLO）
"""

# 不需要询问的只读工具
READ_ONLY_TOOLS = {"file_read", "glob", "grep", "web_fetch"}

# 当前权限模式（可在 main.py 启动时通过参数设置）
_mode = "default"


def set_mode(mode: str) -> None:
    global _mode
    valid = {"default", "plan", "bypass"}
    if mode not in valid:
        raise ValueError(f"Invalid permission mode: {mode}. Must be one of {valid}")
    _mode = mode


def get_mode() -> str:
    return _mode


def check_permission(tool_name: str, tool_input: dict) -> bool:
    """
    返回 True 表示允许执行，False 表示用户拒绝。

    对应原版的 PermissionDecision: allow / ask / deny 三态，
    这里简化为：直接允许 True 或 询问后由用户决定。
    """
    if _mode == "bypass":
        return True

    if _mode == "default" and tool_name in READ_ONLY_TOOLS:
        return True

    # plan 模式：所有工具都询问
    # default 模式：非只读工具询问
    return _ask_user(tool_name, tool_input)


def _ask_user(tool_name: str, tool_input: dict) -> bool:
    """打印工具调用详情，让用户确认。"""
    print(f"\n[permission] Tool: {tool_name}")
    _print_input(tool_input)
    while True:
        answer = input("Allow? [y/n/y!] (y!=allow all for this session): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer == "y!":
            # 本次会话永久允许该工具（降级为 bypass 对该工具）
            READ_ONLY_TOOLS.add(tool_name)
            return True
        if answer in ("n", "no", ""):
            return False
        print("Please enter y, n, or y!")


def _print_input(input: dict) -> None:
    for k, v in input.items():
        v_str = str(v)
        if len(v_str) > 200:
            v_str = v_str[:197] + "..."
        print(f"  {k}: {v_str}")
