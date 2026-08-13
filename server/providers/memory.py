from __future__ import annotations

import json
import os
import socket
from abc import ABC, abstractmethod
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class MemoryProvider(ABC):
    name = "off"
    enabled = False

    @abstractmethod
    def recall(
        self,
        *,
        namespace: str,
        session_id: str,
        query: str,
        metadata: dict[str, Any],
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def remember(
        self,
        *,
        namespace: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any],
    ) -> None:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "enabled": self.enabled}


class OffMemoryProvider(MemoryProvider):
    def recall(self, **_: Any) -> str:
        return ""

    def remember(self, **_: Any) -> None:
        return None


class HttpMemoryProvider(MemoryProvider):
    """Small neutral HTTP contract; adapt existing memory systems behind it."""

    name = "http"
    enabled = True

    def __init__(self) -> None:
        self.base_url = os.environ.get("MEMORY_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
        self.api_key = os.environ.get("MEMORY_API_KEY", "").strip()
        self.recall_path = os.environ.get("MEMORY_RECALL_PATH", "/recall")
        self.remember_path = os.environ.get("MEMORY_REMEMBER_PATH", "/remember")
        self.timeout = int(os.environ.get("MEMORY_TIMEOUT_SECONDS", "20"))

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read(1_000_000).decode("utf-8"))
        except (HTTPError, URLError, OSError, TimeoutError, socket.timeout, json.JSONDecodeError, UnicodeError) as exc:
            raise RuntimeError("memory provider unavailable") from exc
        return payload if isinstance(payload, dict) else {}

    def recall(
        self,
        *,
        namespace: str,
        session_id: str,
        query: str,
        metadata: dict[str, Any],
    ) -> str:
        payload = self._post(self.recall_path, {
            "namespace": namespace,
            "session_id": session_id,
            "query": query[:3000],
            "limit": 8,
            "metadata": metadata,
        })
        if isinstance(payload.get("text"), str):
            return payload["text"].strip()[:8000]
        memories = payload.get("memories", [])
        if not isinstance(memories, list):
            return ""
        values: list[str] = []
        for item in memories[:8]:
            if isinstance(item, str):
                values.append(item.strip())
            elif isinstance(item, dict):
                values.append(str(item.get("content") or item.get("text") or "").strip())
        return "\n".join(value for value in values if value)[:8000]

    def remember(
        self,
        *,
        namespace: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any],
    ) -> None:
        self._post(self.remember_path, {
            "namespace": namespace,
            "session_id": session_id,
            "user_message": user_message[:5000],
            "assistant_message": assistant_message[:12_000],
            "metadata": metadata,
        })


def build_memory_provider() -> MemoryProvider:
    provider = os.environ.get("MEMORY_PROVIDER", "off").strip().lower()
    if provider in {"", "off", "none", "disabled"}:
        return OffMemoryProvider()
    if provider == "http":
        return HttpMemoryProvider()
    raise RuntimeError(
        f"Unknown MEMORY_PROVIDER={provider!r}. Add an adapter in server/providers/memory.py."
    )
