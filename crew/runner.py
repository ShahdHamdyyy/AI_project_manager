"""CrewAI execution layer.

Every specialised agent is a CrewAI `Agent` (built once and cached). Each orchestrator call becomes a
single-task `Crew` run: the ORCHESTRATOR (not CrewAI's sequential process) decides what runs and when.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Protocol

from services.errors import LLMError, LLMTimeoutError, PMError
from services.logging_setup import log

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")


class Runner(Protocol):
    def run(self, agent, prompt: str) -> str: ...


class CrewRunner:
    def __init__(self, settings):
        try:
            from crewai import LLM
        except ImportError as exc:  # pragma: no cover - environment problem
            raise PMError("crewai is not installed. Run: pip install -r requirements.txt") from exc
        self.settings = settings
        self.llm = LLM(
            model=f"ollama/{settings.model}",
            base_url=settings.ollama_base_url,
            temperature=settings.temperature,
            timeout=settings.llm_timeout_seconds,
        )
        self._crew_agents: dict = {}
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="crew")

    def _crew_agent(self, spec):
        from crewai import Agent
        if spec.name not in self._crew_agents:
            self._crew_agents[spec.name] = Agent(
                role=spec.role, goal=spec.goal, backstory=spec.backstory, llm=self.llm,
                allow_delegation=False, verbose=False, max_iter=3,
            )
        return self._crew_agents[spec.name]

    def _kickoff(self, spec, prompt: str) -> str:
        from crewai import Crew, Process, Task
        agent = self._crew_agent(spec)
        task = Task(description=prompt,
                    expected_output="One valid JSON object and nothing else.", agent=agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        result = crew.kickoff()
        return getattr(result, "raw", None) or str(result)

    def run(self, spec, prompt: str) -> str:
        started = time.time()
        future = self._pool.submit(self._kickoff, spec, prompt)
        try:
            raw = future.result(timeout=self.settings.llm_timeout_seconds + 30)
        except FutureTimeout as exc:
            future.cancel()
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="crew")  # abandon stuck worker
            raise LLMTimeoutError(
                f"{spec.name}: no answer within {self.settings.llm_timeout_seconds + 30}s") from exc
        except Exception as exc:  # CrewAI/litellm raise many exception types
            text = str(exc)
            if "timed out" in text.lower() or "timeout" in text.lower():
                raise LLMTimeoutError(f"{spec.name}: LLM timeout: {text[:200]}") from exc
            raise LLMError(f"{spec.name}: CrewAI/LLM error: {type(exc).__name__}: {text[:300]}") from exc
        log("AGENT", f"{spec.name} finished in {time.time() - started:.1f}s ({len(raw)} chars)")
        return raw
