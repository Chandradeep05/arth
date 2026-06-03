"""
Abstract LLM client interface.

All LLM providers (Groq, Ollama, Claude, OpenAI) implement this interface.
This enables seamless switching between providers via the LLM_TIER config
without changing any business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, List, Optional


@dataclass
class LLMMessage:
    """A single message in a conversation."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str
    model: str
    provider: str
    tokens_used: int = 0
    finish_reason: str = "stop"
    latency_ms: float = 0.0


@dataclass
class LLMConfig:
    """Configuration for an LLM request."""
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.3  # Low temperature for financial analysis
    top_p: float = 0.9
    stop_sequences: List[str] = field(default_factory=list)


class BaseLLMClient(ABC):
    """Abstract base class for LLM providers."""

    provider_name: str = "base"

    @abstractmethod
    async def generate(
        self,
        messages: List[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: List[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens from the LLM."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the LLM provider is available."""
        ...

    def _build_system_prompt(self, base_prompt: str) -> str:
        """Wrap any system prompt with ARTH's mandatory constraints."""
        return (
            f"{base_prompt}\n\n"
            "CRITICAL CONSTRAINTS:\n"
            "- Never claim certainty about future market movements\n"
            "- Always use probabilistic language: 'likely', 'suggests', 'approximately'\n"
            "- Never say 'will go up', 'guaranteed', 'certain to'\n"
            "- Always include confidence levels in analysis\n"
            "- All numerical claims must be sourced from provided data, never from memory\n"
            "- End every analysis with a risk disclaimer\n"
        )
