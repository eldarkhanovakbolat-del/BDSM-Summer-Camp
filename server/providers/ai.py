from __future__ import annotations

import json
import os
import socket
import ssl
import threading
from abc import ABC, abstractmethod
from http import HTTPStatus
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """A safe, user-facing provider error without credentials or raw payloads."""


class AIProvider(ABC):
    name = "custom"

    @property
    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str,
        session_id: str,
    ) -> str:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "configured": self.configured}


class OpenAICompatibleProvider(AIProvider):
    """Minimal Chat Completions adapter for self-hosted or hosted gateways."""

    name = "openai_compatible"

    def __init__(self, prefix: str = "AI", fallback_prefix: str | None = None) -> None:
        self.prefix = prefix

        def setting(name: str, default: str = "") -> str:
            value = os.environ.get(f"{prefix}_{name}")
            # Empty optional audience values inherit the main provider.  The
            # key is the exception: never send a main-provider secret to a
            # separately configured audience endpoint by accident.
            if prefix == "AUDIENCE_AI" and name in {
                "API_KEY",
                "EXTRA_HEADERS_JSON",
                "EXTRA_BODY_JSON",
            } and (
                value is None or not value.strip()
            ):
                return default
            if (value is None or not value.strip()) and fallback_prefix:
                value = os.environ.get(f"{fallback_prefix}_{name}")
            return default if value is None else value

        self.base_url = setting("BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
        self.api_key = setting("API_KEY").strip()
        self.model = setting("MODEL").strip()
        self.timeout = int(setting("TIMEOUT_SECONDS", "180"))
        self._semaphore = threading.BoundedSemaphore(int(setting("MAX_CONCURRENT", "2")))
        try:
            headers = json.loads(setting("EXTRA_HEADERS_JSON", "{}"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{prefix}_EXTRA_HEADERS_JSON must be valid JSON") from exc
        if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
            raise RuntimeError(f"{prefix}_EXTRA_HEADERS_JSON must contain string header values")
        self.extra_headers: dict[str, str] = headers
        try:
            extra_body = json.loads(setting("EXTRA_BODY_JSON", "{}"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{prefix}_EXTRA_BODY_JSON must be valid JSON") from exc
        if not isinstance(extra_body, dict):
            raise RuntimeError(f"{prefix}_EXTRA_BODY_JSON must be a JSON object")
        self.extra_body: dict[str, Any] = extra_body

    @property
    def configured(self) -> bool:
        # Local gateways often need no key, but every Chat Completions request needs a model.
        return bool(self.base_url and self.model)

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str,
        session_id: str,
    ) -> str:
        if not self.configured:
            raise ProviderError("AI 后端尚未配置：请填写 AI_BASE_URL 和 AI_MODEL")
        body: dict[str, Any] = {
            **self.extra_body,
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        headers = {
            **self.extra_headers,
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "BDSMSummerCamp/1.0",
            "X-Camp-Purpose": purpose[:32],
            "X-Camp-Session": session_id[:128],
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self._semaphore, urlopen(request, timeout=self.timeout, context=ssl._create_unverified_context()) as response:
                payload = json.loads(response.read(4_000_000).decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
                message = "AI 后端拒绝了密钥，请检查 AI_API_KEY"
            elif exc.code == HTTPStatus.TOO_MANY_REQUESTS:
                message = "AI 后端当前繁忙或额度不足，请稍后再试"
            else:
                message = f"AI 后端返回 HTTP {exc.code}"
            raise ProviderError(message) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise TimeoutError("AI 后端响应超时") from exc
        except (URLError, OSError) as exc:
            raise ProviderError("无法连接 AI 后端，请检查 AI_BASE_URL") from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProviderError("AI 后端返回了无法识别的数据") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("AI 后端响应中没有可用回复") from exc
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
        text = str(content or "").strip()
        if not text:
            raise ProviderError("AI 后端返回了空回复")
        return text[:20_000]


def build_ai_provider() -> AIProvider:
    provider = os.environ.get("AI_PROVIDER", "openai_compatible").strip().lower()
    if provider == "openai_compatible":
        return OpenAICompatibleProvider()
    raise RuntimeError(
        f"Unknown AI_PROVIDER={provider!r}. Add a provider in server/providers/ai.py."
    )


def build_audience_ai_provider(main_provider: AIProvider) -> AIProvider:
    """Use an optional isolated backend for audience calls, or reuse the main one."""
    audience_keys = (
        "AUDIENCE_AI_PROVIDER",
        "AUDIENCE_AI_BASE_URL",
        "AUDIENCE_AI_API_KEY",
        "AUDIENCE_AI_MODEL",
        "AUDIENCE_AI_TIMEOUT_SECONDS",
        "AUDIENCE_AI_MAX_CONCURRENT",
        "AUDIENCE_AI_EXTRA_HEADERS_JSON",
        "AUDIENCE_AI_EXTRA_BODY_JSON",
    )
    if not any(os.environ.get(key, "").strip() for key in audience_keys):
        return main_provider
    provider = (
        os.environ.get("AUDIENCE_AI_PROVIDER", "").strip().lower()
        or "openai_compatible"
    )
    if provider == "openai_compatible":
        return OpenAICompatibleProvider(prefix="AUDIENCE_AI", fallback_prefix="AI")
    raise RuntimeError(
        f"Unknown AUDIENCE_AI_PROVIDER={provider!r}. Add a provider in server/providers/ai.py."
    )
