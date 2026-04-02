"""
多 provider 抽象层（对应原版 src/services/api/client.ts + providers.ts）

支持的 provider：
  - anthropic  : 直连 Anthropic API（默认）
  - bedrock    : AWS Bedrock
  - vertex     : Google Vertex AI
"""

from providers.base import Provider, StreamEvent
from providers.registry import get_provider, list_providers

__all__ = ["Provider", "StreamEvent", "get_provider", "list_providers"]
