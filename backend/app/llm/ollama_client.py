"""
Ollama LLM client — Local dev fallback.

Useful for development when you want to avoid API rate limits or
work offline. Uses Qwen2.5:3B by default (upgradeable to LLaMA3:8B+ with RAM).
"""

from __future__ import annotations

import time
from typing import AsyncGenerator, List, Optional

import httpx

from app.core.logging import get_logger
from app.llm.base import BaseLLMClient, LLMConfig, LLMMessage, LLMResponse

logger = get_logger(__name__)


class OllamaClient(BaseLLMClient):
    """Ollama local LLM client."""

    provider_name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", default_model: str = "qwen2.5:3b"):
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    async def generate(
        self,
        messages: List[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        """Generate a complete response from Ollama."""
        cfg = config or LLMConfig()
        model = cfg.model or self._default_model

        processed_messages = self._process_messages(messages)

        # Build the prompt from messages (Ollama chat format)
        start_time = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": model,
                        "messages": [
                            {"role": m.role, "content": m.content}
                            for m in processed_messages
                        ],
                        "stream": False,
                        "options": {
                            "temperature": cfg.temperature,
                            "top_p": cfg.top_p,
                            "num_predict": cfg.max_tokens,
                        },
                    },
                )
                response.raise_for_status()

            data = response.json()
            latency = (time.monotonic() - start_time) * 1000

            content = data.get("message", {}).get("content", "")
            tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)

            logger.info(
                "ollama_generation_complete",
                model=model,
                tokens=tokens,
                latency_ms=round(latency, 2),
            )

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider_name,
                tokens_used=tokens,
                latency_ms=latency,
            )

        except Exception as e:
            latency = (time.monotonic() - start_time) * 1000
            logger.error("ollama_generation_failed", model=model, error=str(e))
            raise

    async def stream(
        self,
        messages: List[LLMMessage],
        config: Optional[LLMConfig] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens from Ollama."""
        cfg = config or LLMConfig()
        model = cfg.model or self._default_model

        processed_messages = self._process_messages(messages)

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/api/chat",
                    json={
                        "model": model,
                        "messages": [
                            {"role": m.role, "content": m.content}
                            for m in processed_messages
                        ],
                        "stream": True,
                        "options": {
                            "temperature": cfg.temperature,
                            "top_p": cfg.top_p,
                            "num_predict": cfg.max_tokens,
                        },
                    },
                ) as response:
                    import json
                    async for line in response.aiter_lines():
                        if line.strip():
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                            if data.get("done", False):
                                break

        except Exception as e:
            logger.error("ollama_stream_failed", model=model, error=str(e))
            yield f"\n\n[Error: Local AI generation failed — {str(e)}]"

    async def health_check(self) -> bool:
        """Check if Ollama server is running."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                return response.status_code == 200
        except Exception:
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
