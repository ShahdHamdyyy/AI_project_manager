from __future__ import annotations

from models.base import StrictModel
from models.enums import DependencyType, Priority, TaskStatus, TaskType


class Task(StrictModel):
    id: str
    epic_id: str
    title: str
    type: TaskType
    description: str = ""
    estimated_hours: float
    priority: Priority = Priority.MEDIUM
    status: TaskStatus = TaskStatus.PLANNED


class Dependency(StrictModel):
    task_id: str        # the task that is blocked
    depends_on: str     # the task that must finish first (always a TASK id)
    type: DependencyType = DependencyType.BLOCKS
    reason: str = ""


class PriorityEntry(StrictModel):
    task_id: str
    priority: Priority
    rank: int = 0       # 1 = most urgent; computed by Python, never by the LLM
