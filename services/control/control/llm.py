"""Client du service modèle compatible OpenAI (vLLM / SGLang), côté serveur uniquement (L15, L16)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx


class LlmError(RuntimeError):
    code = "llm_error"
    retryable = False


class LlmUnavailable(LlmError):
    code = "llm_unavailable"
    retryable = True


class LlmContextError(LlmError):
    code = "llm_context"


class LlmClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        max_concurrency: int = 4,
        timeout_s: float = 180,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # File équitable : aucun raisonnement long ne monopolise le serveur (N13).
        self._sem = asyncio.Semaphore(max_concurrency)
        self.waiting = 0

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        json_mode: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        self.waiting += 1
        try:
            await self._sem.acquire()
        finally:
            self.waiting -= 1
        try:
            resp = await self._client.post("/chat/completions", json=body)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            raise LlmUnavailable(f"service modèle injoignable : {exc}") from exc
        finally:
            self._sem.release()
        if resp.status_code == 400 and "context" in resp.text.lower():
            raise LlmContextError("contexte du modèle dépassé")
        if resp.status_code >= 500:
            raise LlmUnavailable(f"service modèle en erreur ({resp.status_code})")
        if resp.status_code >= 400:
            raise LlmError(f"requête refusée par le modèle ({resp.status_code}) : {resp.text[:500]}")
        data = resp.json()
        return data["choices"][0]["message"] | {"usage": data.get("usage")}

    async def chat_json(self, messages: list[dict[str, Any]], max_tokens: int = 2048) -> dict[str, Any]:
        msg = await self.chat(messages, json_mode=True, max_tokens=max_tokens)
        text = (msg.get("content") or "").strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LlmError(f"réponse JSON invalide : {text[:300]}") from exc

    async def ready(self) -> bool:
        try:
            r = await self._client.get("/models", timeout=5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False
