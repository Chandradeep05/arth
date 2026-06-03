"""
Groq LLM client — Primary provider for Phase 1.

Groq provides LLaMA 3.3 70B with extremely fast inference (free tier: 14,400 req/day).
This is the production LLM for Phase 1, solving both the RAM constraint
(no local GPU required) and the deployment problem (works identically in dev and prod).
"""

from __future__ import annotations

import time
from typing import AsyncGenerator, List, Optional

from groq import AsyncGroq

from app.core.logging import get_logger
from app.llm.base import BaseLLMClient, LLMConfig, LLMMessage, LLMResponse

logger = get_logger(__name__)


class GroqClient(BaseLLMClient):
    """Groq API client for fast LLM inference."""

    provider_name = "groq"

    def __init__(self, api_key: str, default_model: str = "llama-3.3-70b-versatile"):
        self._client = AsyncGroq(api_key=api_key)
        self._default_model = default_model

    async def generate(
        self,
        messages: List[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        """Generate a complete response."""
        cfg = config or LLMConfig()
        model = cfg.model or self._default_model

        # Apply ARTH constraints to system prompt
        processed_messages = self._process_messages(messages)

        start_time = time.monotonic()
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": m.role, "content": m.content}
                    for m in processed_messages
                ],
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                top_p=cfg.top_p,
                stop=cfg.stop_sequences or None,
            )
            latency = (time.monotonic() - start_time) * 1000

            content = response.choices[0].message.content or ""
            tokens = response.usage.total_tokens if response.usage else 0

            logger.info(
                "groq_generation_complete",
                model=model,
                tokens=tokens,
                latency_ms=round(latency, 2),
            )

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_name,
                tokens_used=tokens,
                finish_reason=response.choices[0].finish_reason or "stop",
                latency_ms=latency,
            )

        except Exception as e:
            latency = (time.monotonic() - start_time) * 1000
            logger.error(
                "groq_generation_failed",
                model=model,
                error=str(e),
                latency_ms=round(latency, 2),
            )
            raise

    async def stream(
        self,
        messages: List[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens for progressive rendering."""
        cfg = config or LLMConfig()
        model = cfg.model or self._default_model

        processed_messages = self._process_messages(messages)

        try:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": m.role, "content": m.content}
                    for m in processed_messages
                ],
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                top_p=cfg.top_p,
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error("groq_stream_failed", model=model, error=str(e))
            yield f"\n\n[Error: AI generation failed — {str(e)}]"

    async def health_check(self) -> bool:
        """Check if Groq API is reachable."""
        try:
            response = await self._client.chat.completions.create(
                model=self._default_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return True
        except Exception as e:
            logger.warning("groq_health_check_failed", error=str(e))
            return False

    def _process_messages(self, messages: List[LLMMessage]) -> List[LLMMessage]:
        """Apply ARTH constraints to system prompts."""
        processed = []
        for msg in messages:
            if msg.role == "system":
                processed.append(LLMMessage(
                    role="system",
                    content=self._build_system_prompt(msg.content),
                ))
            else:
                processed.append(msg)
        return processed
