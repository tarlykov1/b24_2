from __future__ import annotations

from typing import Any

import httpx


class BitrixClient:
    """Thin REST adapter for Bitrix24 webhook API."""

    def __init__(self, base_url: str, webhook: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._webhook = webhook.strip("/")
        self._client = httpx.Client(timeout=timeout_seconds)

    def call(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}/rest/{self._webhook}/{method}.json"
        response = self._client.post(url, json=payload or {})
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._client.close()
