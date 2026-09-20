"""
Groq LLM client — Primary provider with automatic model fallback chain.

Groq provides extremely fast inference (free tier: 14,400 req/day).

Fallback chain: if the primary model fails (429, decommissioned, quota exceeded,
any error), the client automatically tries each fallback model in order.
- generate(): tries each model in the chain, returns first success
- stream(): only swaps models if nothing has been yielded yet — once tokens
  are streaming, a late failure just ends with an error message rather than
  producing a garbled, restarted-mid-sentence response.

# Default chains (configured in config.py):
# - Chat: openai/gpt-oss-20b → openai/gpt-oss-120b
# - Research: openai/gpt-oss-120b → openai/gpt-oss-20b
Configurable via GROQ_FALLBACK_MODELS env var without touching code.

Note on <think> tag stripping: _strip_thinking() runs unconditionally regardless
of model — safe as a no-op on non-reasoning models, so mixed model fallback works.
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
    """Groq API client with automatic model fallback chain."""

    provider_name = "groq"

    def __init__(
        self,
        api_key: str,
        default_model: str,
        fallback_models: Optional[List[str]] = None,
    ):
        self._client = AsyncGroq(api_key=api_key)
        self._default_model = default_model
        self._fallback_models = fallback_models or []

    def _model_chain(self, config_model: Optional[str] = None) -> List[str]:
        """Build ordered model chain: config override / primary → fallbacks."""
        primary = config_model or self._default_model
        chain = [primary]
        for m in self._fallback_models:
            if m != primary and m not in chain:
                chain.append(m)
        return chain

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        """Determine if an error warrants trying the next model in the chain.
        
        Retryable: 429 (rate limit), 500/502/503/504 (server errors), timeouts.
        Non-retryable: 400 (bad request), 401/403 (auth), other client errors.
        """
        error_str = str(error).lower()
        # Groq SDK wraps HTTP errors with status codes in the message
        # Check for retryable status codes
        for code in ('429', '500', '502', '503', '504', 'timeout', 'timed out', 'rate_limit', 'overloaded', 'service_unavailable'):
            if code in error_str:
                return True
        # Check for explicitly non-retryable errors (don't retry auth/validation failures)
        for code in ('400', '401', '403', 'invalid_api_key', 'invalid_request'):
            if code in error_str:
                return False
        # Default: retry (model might be decommissioned, unavailable, etc.)
        return True

    async def generate(
        self,
        messages: List[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        """Generate a complete response, falling through the model chain on failure."""
        cfg = config or LLMConfig()
        chain = self._model_chain(cfg.model)
        processed_messages = self._process_messages(messages)

        last_error = None
        for depth, model in enumerate(chain):
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
                    fallback_depth=depth,
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
                error_str = str(e)
                last_error = error_str
                remaining = len(chain) - depth - 1
                
                if not self._is_retryable_error(e):
                    logger.error(
                        "groq_non_retryable_error",
                        model=model,
                        error=error_str,
                    )
                    raise  # Don't try other models for auth/validation failures
                
                logger.warning(
                    "groq_model_failed",
                    model=model,
                    error=error_str,
                    latency_ms=round(latency, 2),
                    fallback_depth=depth,
                    fallbacks_remaining=remaining,
                )
                # Continue to next model in chain
                continue

        # All models exhausted — return clean error
        logger.error(
            "groq_all_models_exhausted",
            chain=chain,
            last_error=last_error,
        )
        return LLMResponse(
            content="⚠ AI analysis is temporarily unavailable. All models are at capacity — please try again in a minute.",
            model=chain[-1],
            provider=self.provider_name,
            tokens_used=0,
            finish_reason="all_models_exhausted",
            latency_ms=0,
        )

    async def stream(
        self,
        messages: List[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens, falling through models only if nothing yielded yet."""
        cfg = config or LLMConfig()
        chain = self._model_chain(cfg.model)
        processed_messages = self._process_messages(messages)

        for depth, model in enumerate(chain):
            has_yielded = False
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
                            has_yielded = True
                            yield token
                            continue
                            
                        buffer += token
                        
                        if in_thinking_block:
                            end_tag = "</think>"
                            end_idx = buffer.lower().find(end_tag)
                            if end_idx != -1:
                                in_thinking_block = False
                                past_thinking = True
                                remaining = buffer[end_idx + len(end_tag):]
                                if remaining.lstrip():
                                    has_yielded = True
                                    yield remaining.lstrip()
                                buffer = ""
                            elif len(buffer) > 20: 
                                buffer = buffer[-7:]
                            continue
                            
                        start_tag = "<think>"
                        start_idx = buffer.lower().find(start_tag)
                        
                        if start_idx != -1:
                            if start_idx > 0:
                                has_yielded = True
                                yield buffer[:start_idx]
                            in_thinking_block = True
                            buffer = buffer[start_idx + len(start_tag):]
                            continue
                            
                        if len(buffer) >= 8:
                            has_yielded = True
                            yield buffer[:-7]
                            buffer = buffer[-7:]

                # End of stream — flush remaining buffer
                if buffer and not in_thinking_block and not past_thinking:
                    yield buffer
                elif in_thinking_block and not past_thinking:
                    logger.warning("groq_stream_unterminated_think_block", model=model)
                    yield "I need a bit more room to think through that — could you ask again, maybe a little more specifically?"

                if depth > 0:
                    logger.info("groq_stream_fallback_success", model=model, fallback_depth=depth)
                # Success — exit the chain loop
                return

            except Exception as e:
                error_str = str(e)
                remaining = len(chain) - depth - 1
                
                if not self._is_retryable_error(e):
                    logger.error(
                        "groq_non_retryable_error",
                        model=model,
                        error=error_str,
                    )
                    raise  # Don't try other models for auth/validation failures

                logger.warning(
                    "groq_stream_model_failed",
                    model=model,
                    error=error_str,
                    fallback_depth=depth,
                    fallbacks_remaining=remaining,
                    has_yielded=has_yielded,
                )

                if has_yielded:
                    # Already sent tokens — can't switch models mid-response.
                    # Yield clean error and stop.
                    yield "\n\n[Error: AI generation interrupted. Please try again.]"
                    return

                # Nothing yielded yet — try next model
                continue

        # All models exhausted, nothing was yielded
        yield "⚠ AI analysis is temporarily unavailable. All models are at capacity — please try again in a minute."

    async def health_check(self) -> bool:
        """Check if Groq API is reachable with any model in the chain."""
        for model in self._model_chain():
            try:
                await self._client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=5,
                )
                return True
            except Exception as e:
                logger.warning("groq_health_check_failed", model=model, error=str(e))
                continue
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
