"""Robust JSON extraction for small-model output (fences, prose, trailing commas, truncation)."""
from __future__ import annotations

import json
import re

from services.errors import AgentOutputError

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _scan(text: str, start: int):
    """Scan from an opening bracket. Returns (end_index_or_None, open_stack, last_closed_positions)."""
    stack, in_str, esc = [], False, False
    closes = []  # (index, stack_snapshot_after_close)
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack.pop() != ch:
                return None, stack, closes
            closes.append((i, list(stack)))
            if not stack:
                return i, stack, closes
    return None, stack, closes


def _loads(candidate: str):
    candidate = candidate.replace("\u201c", '"').replace("\u201d", '"')
    for attempt in (candidate, _TRAILING_COMMA.sub(r"\1", candidate)):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    return None


def extract_json(raw: str):
    """Return the first JSON object/array found in `raw`, repairing safe problems. Raises AgentOutputError."""
    if not raw or not raw.strip():
        raise AgentOutputError("Empty LLM response")
    text = raw.strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise AgentOutputError(f"No JSON found in response: {raw[:120]!r}")
    start = min(starts)
    end, stack, closes = _scan(text, start)
    if end is not None:
        data = _loads(text[start:end + 1])
        if data is not None:
            return data
        raise AgentOutputError(f"Invalid JSON syntax: {text[start:start + 120]!r}")
    # Truncated output: cut back to the last complete element and close open brackets.
    for idx, snapshot in reversed(closes[-6:]):
        repaired = text[start:idx + 1] + "".join(reversed(snapshot))
        data = _loads(repaired)
        if data is not None:
            return data
    raise AgentOutputError("Truncated or malformed JSON that could not be repaired")
