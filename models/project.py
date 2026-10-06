from __future__ import annotations

from models.base import StrictModel
from models.enums import Level, Priority, RequirementKind


class Project(StrictModel):
    name: str
    summary: str
    objective: str = ""
    duration_weeks: int
    sprint_count: int
    sprint_length_weeks: int = 1
    actors: list[str] = []
    mvp_scope: list[str] = []
    out_of_scope: list[str] = []
    assumptions: list[str] = []
    constraints: list[str] = []
    business_priority: str = ""
    status: str = "in_progress"  # in_progress | complete | failed_validation


class Requirement(StrictModel):
    id: str
    kind: RequirementKind
    title: str
    description: str = ""
    priority: Priority = Priority.MEDIUM


class Milestone(StrictModel):
    id: str
    name: str
    sprint_id: str
    week: int
    criteria: str = ""


class Risk(StrictModel):
    id: str
    title: str
    description: str = ""
    likelihood: Level = Level.MEDIUM
    impact: Level = Level.MEDIUM
    mitigation: str = ""
    epic_ids: list[str] = []
