"""
Provider 注册表 — 根据配置自动选择 provider

对应原版 src/utils/model/providers.ts 的 selectProvider()
"""

from __future__ import annotations

import os

from providers.base import Provider

# 延迟导入，只有实际用到的 provider 才会初始化
_PROVIDER_FACTORIES = {
    "anthropic": "providers.anthropic_provider:AnthropicProvider",
    "bedrock": "providers.bedrock:BedrockProvider",
    "vertex": "providers.vertex:VertexProvider",
}

_cached_provider: Provider | None = None


def _import_class(dotted: str):
    module_path, class_name = dotted.rsplit(":", 1)
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def detect_provider_name() -> str:
    """
    自动检测应该使用哪个 provider。
    优先级：环境变量 CLAUDE_PROVIDER > 自动检测 > 默认 anthropic
    """
    explicit = os.environ.get("CLAUDE_PROVIDER", "").lower()
    if explicit in _PROVIDER_FACTORIES:
        return explicit

    # 自动检测：有 Bedrock / Vertex 环境变量就用对应 provider
    if os.environ.get("ANTHROPIC_BEDROCK") == "1" or os.environ.get("AWS_PROFILE"):
        return "bedrock"
    if os.environ.get("GOOGLE_CLOUD_PROJECT") and os.environ.get("ANTHROPIC_VERTEX") == "1":
        return "vertex"

    return "anthropic"


def get_provider(name: str | None = None) -> Provider:
    """
    获取 provider 实例（单例缓存）。
    name 为 None 时自动检测。
    """
    global _cached_provider

    if name is None:
        name = detect_provider_name()

    # 如果缓存的 provider 类型不对，重新创建
    if _cached_provider is not None and _cached_provider.name == name:
        return _cached_provider

    if name not in _PROVIDER_FACTORIES:
        raise ValueError(
            f"Unknown provider: {name}. Available: {list(_PROVIDER_FACTORIES.keys())}"
        )

    factory_path = _PROVIDER_FACTORIES[name]
    cls = _import_class(factory_path)

    if name == "anthropic":
        import config
        _cached_provider = cls(
            api_key=config.ANTHROPIC_API_KEY,
            base_url=config.ANTHROPIC_BASE_URL,
        )
    else:
        _cached_provider = cls()

    return _cached_provider


def list_providers() -> list[str]:
    return list(_PROVIDER_FACTORIES.keys())
