from __future__ import annotations

from models.base import StrictModel


class Sprint(StrictModel):
    id: str
    number: int
    goal: str
    task_ids: list[str] = []
    capacity_hours: float
    planned_hours: float = 0.0


class Assignment(StrictModel):
    task_id: str
    member_id: str
    sprint_id: str
    reason: str = ""
