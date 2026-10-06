from __future__ import annotations

from models.base import StrictModel
from models.enums import Priority


class Epic(StrictModel):
    id: str
    name: str
    description: str = ""
    priority: Priority = Priority.MEDIUM
    requirement_ids: list[str] = []
