"""
Groq LLM client — Primary provider for Phase 1.

Groq provides extremely fast inference (free tier: 14,400 req/day).
Note on Qwen reasoning models (e.g., qwen/qwen3.6-27b): These models emit
<think>...</think> blocks natively. We must strip them on the client side
instead of relying on reasoning_format='hidden' to ensure no tags leak.
This is the production LLM for Phase 1, solving both the RAM constraint
(no local GPU required) and the deployment problem (works identically in dev and prod).
"""

from __future__ import annotations

import re
import time
from typing import AsyncGenerator, List, Optional

from groq import AsyncGroq

from app.core.logging import get_logger
from app.llm.base import BaseLLMClient, LLMConfig, LLMMessage, LLMResponse

logger = get_logger(__name__)

# Regex to catch complete <think> blocks
# We strip <think> blocks client-side because certain reasoning models
# (like Qwen) may still leak tags or hit max_tokens mid-thought, making
# reasoning_format='hidden' unreliable as a sole defense.
_THINK_BLOCK_RE = re.compile(r'<think>.*?</think>', re.DOTALL | re.IGNORECASE)

def _strip_thinking(content: str) -> str:
    """
    Removes complete <think>...</think> blocks.
    Handles unterminated <think> blocks (e.g. hit max_tokens mid-thought) by
    dropping everything from <think> onward.
    Returns empty string if content is falsy.
    """
    if not content:
        return ""
    
    # Remove complete blocks
    content = _THINK_BLOCK_RE.sub('', content)
    
    # Handle unterminated <think> block
    lower_content = content.lower()
    start_idx = lower_content.find('<think>')
    if start_idx != -1:
        content = content[:start_idx]
        
    return content.strip()


class GroqClient(BaseLLMClient):
    """Groq API client for fast LLM inference."""

    provider_name = "groq"

    def __init__(self, api_key: str, default_model: str = "qwen-2.5-32b"):
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

            content = _strip_thinking(response.choices[0].message.content or '')
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

            buffer = ""
            in_thinking_block = False
            past_thinking = False

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    
                    if past_thinking:
                        # Once past thinking, yield chunks directly (no latency penalty)
                        yield token
                        continue
                        
                    buffer += token
                    
                    if in_thinking_block:
                        end_tag = "</think>"
                        end_idx = buffer.lower().find(end_tag)
                        if end_idx != -1:
                            in_thinking_block = False
                            past_thinking = True
                            # Yield content after </think>
                            remaining = buffer[end_idx + len(end_tag):]
                            if remaining.lstrip():
                                yield remaining.lstrip()
                            buffer = ""
                        elif len(buffer) > 20: 
                            # Keep a small buffer for sliding window in case of chunked tags
                            buffer = buffer[-7:]
                        continue
                        
                    # Not currently in thinking block, looking for <think>
                    start_tag = "<think>"
                    start_idx = buffer.lower().find(start_tag)
                    
                    if start_idx != -1:
                        if start_idx > 0:
                            yield buffer[:start_idx]
                        in_thinking_block = True
                        buffer = buffer[start_idx + len(start_tag):]
                        continue
                        
                    # Tag not found yet. 
                    # If no <think> appears after 8+ characters of buffer, flush the buffer
                    if len(buffer) >= 8:
                        yield buffer[:-7]
                        buffer = buffer[-7:]

            # At end of stream, flush any remaining non-thinking buffer
            if buffer and not in_thinking_block and not past_thinking:
                yield buffer

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
