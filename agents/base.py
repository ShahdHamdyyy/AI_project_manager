"""Base class for the specialised agents.

An agent = CrewAI persona (role/goal/backstory) + prompt builder + strict output schema.
Agents never touch the project state: they receive a small context dict and return a validated proposal.
"""
from __future__ import annotations

import json

from services.errors import AgentOutputError
from services.json_tools import extract_json
from services.logging_setup import log

JSON_ONLY = "Answer with ONE valid JSON object only. No markdown fences, no explanations."


class BaseAgent:
    name = "base"
    role = ""
    goal = ""
    backstory = ""
    list_key: str | None = None

    def __init__(self, runner):
        self.runner = runner

    # -- to override -----------------------------------------------------------------------------
    def output_model(self, ctx: dict):
        raise NotImplementedError

    def build_prompt(self, ctx: dict) -> str:
        raise NotImplementedError

    # -- shared ----------------------------------------------------------------------------------
    def run(self, ctx: dict, feedback: str | None = None):
        prompt = self.build_prompt(ctx)
        if feedback:
            prompt += (f"\n\nYOUR PREVIOUS ANSWER WAS REJECTED: {feedback}\n"
                       "Correct the problem and answer again. " + JSON_ONLY)
        log("AGENT", f"{self.name} started (prompt ~{len(prompt)} chars)")
        raw = self.runner.run(self, prompt)
        data = extract_json(raw)
        data = self._normalise_shape(data, self.list_key_for(ctx))
        try:
            return self.output_model(ctx).model_validate(data)
        except ValueError as exc:  # pydantic.ValidationError is a ValueError
            msg = " ".join(str(exc).split())[:400]
            raise AgentOutputError(f"{self.name}: output violates schema: {msg}") from exc

    def list_key_for(self, ctx: dict):
        return self.list_key

    def _normalise_shape(self, data, key):
        if key is None:
            if isinstance(data, dict):
                return data
            raise AgentOutputError(f"{self.name}: expected a JSON object, got {type(data).__name__}")
        if isinstance(data, list):
            return {key: data}
        if isinstance(data, dict) and key not in data:
            lists = [v for v in data.values() if isinstance(v, list)]
            if len(lists) == 1:
                return {**data, key: lists[0]}
        return data


def example(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
