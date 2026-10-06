"""Base model classes and lenient field types for LLM-produced proposals.

Canonical state models use StrictModel (unknown fields are rejected).
Agent proposal models use lenient annotated types that normalise typical small-model sloppiness
(numbers where strings are expected, single strings where lists are expected, priority synonyms...).
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict

from models.enums import (Level, Priority, TaskType, coerce_level, coerce_priority, coerce_task_type)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposalModel(BaseModel):
    """Agent output models: extra keys from the LLM are ignored, never trusted."""
    model_config = ConfigDict(extra="ignore")


def _to_text(v):
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {x}" for k, x in v.items())
    return str(v).strip()


def _to_str_list(v):
    if v is None or v == "":
        return []
    if isinstance(v, str):
        return [s.strip(" -*\t") for s in v.replace("\r", "").split("\n") if s.strip(" -*\t")] or [v]
    if isinstance(v, (list, tuple)):
        return [_to_text(x) for x in v if _to_text(x)]
    return [_to_text(v)]


def _to_hours(v):
    if isinstance(v, str):
        cleaned = "".join(ch for ch in v if ch.isdigit() or ch == ".")
        if not cleaned:
            raise ValueError(f"cannot read hours from {v!r}")
        return float(cleaned)
    if isinstance(v, bool) or v is None:
        raise ValueError("estimated_hours must be a number")
    return float(v)


def _to_int(v):
    if isinstance(v, str):
        cleaned = "".join(ch for ch in v if ch.isdigit())
        if not cleaned:
            raise ValueError(f"cannot read integer from {v!r}")
        return int(cleaned)
    if isinstance(v, bool) or v is None:
        raise ValueError("expected integer")
    return int(round(float(v)))


Text = Annotated[str, BeforeValidator(_to_text)]
StrList = Annotated[list[str], BeforeValidator(_to_str_list)]
Hours = Annotated[float, BeforeValidator(_to_hours)]
IntLike = Annotated[int, BeforeValidator(_to_int)]
PriorityLike = Annotated[Priority, BeforeValidator(coerce_priority)]
LevelLike = Annotated[Level, BeforeValidator(coerce_level)]
TaskTypeLike = Annotated[TaskType, BeforeValidator(coerce_task_type)]
