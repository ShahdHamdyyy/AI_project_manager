"""Direct Ollama health checks (pre-flight). Generation itself goes through CrewAI."""
from __future__ import annotations

import httpx

from services.errors import LLMError, ModelUnavailableError, OllamaUnavailableError
from services.logging_setup import log


class OllamaService:
    def __init__(self, base_url: str, model: str, timeout: float = 5, keep_alive: str = "30m"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.keep_alive = keep_alive

    def check_server(self) -> list[str]:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise OllamaUnavailableError(
                f"Ollama is not reachable at {self.base_url}. Start it with 'ollama serve' "
                f"(or 'systemctl start ollama'). Detail: {exc}") from exc
        except httpx.HTTPError as exc:
            raise OllamaUnavailableError(f"Ollama at {self.base_url} returned an error: {exc}") from exc
        try:
            return [m.get("name", "") for m in resp.json().get("models", [])]
        except ValueError as exc:
            raise OllamaUnavailableError(f"Ollama returned non-JSON from /api/tags: {exc}") from exc

    def check_model(self) -> None:
        names = self.check_server()
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        if wanted not in names:
            raise ModelUnavailableError(
                f"Model '{self.model}' not found in Ollama (available: {names or 'none'}). "
                f"Run: ollama pull {self.model}")
        log("ORCHESTRATOR", f"Ollama OK at {self.base_url}; model '{self.model}' available")

    def warm_up(self, timeout: float = 180) -> None:
        """Load the model into memory once so the first real agent call is not penalised."""
        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat", timeout=timeout,
                json={"model": self.model, "stream": False, "keep_alive": self.keep_alive,
                      "messages": [{"role": "user", "content": "ok"}], "options": {"num_predict": 1}})
            resp.raise_for_status()
            log("ORCHESTRATOR", "Model warmed up")
        except httpx.TimeoutException as exc:
            raise LLMError(f"Model warm-up timed out after {timeout}s: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Model warm-up failed: {exc}") from exc
