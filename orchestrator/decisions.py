"""The orchestrator's decision function: inspect canonical state -> choose the next action.

It is a pure function of (state, team, settings). Steps whose preconditions are already satisfied are
skipped, so agents are never run 'just because they are next in a chain'.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from models.enums import ROLE_EXPECTED_TYPES, Role


class Action(str, Enum):
    ANALYZE_PROJECT = "analyze_project"
    EXTRACT_REQUIREMENTS = "extract_requirements"
    CREATE_EPICS = "create_epics"
    CREATE_TASKS = "create_tasks"
    DETECT_RISKS = "detect_risks"
    CREATE_DEPENDENCIES = "create_dependencies"
    SET_PRIORITIES = "set_priorities"
    PLAN_SPRINTS = "plan_sprints"
    ASSIGN_TASKS = "assign_tasks"
    VALIDATE = "validate_plan"
    REPAIR_PLAN = "repair_plan"
    SEMANTIC_REVIEW = "semantic_review"
    FINALIZE = "generate_summary"


# Which specialised agent serves an action (None = pure Python).
AGENT_FOR_ACTION = {
    Action.ANALYZE_PROJECT: "requirements", Action.EXTRACT_REQUIREMENTS: "requirements",
    Action.CREATE_EPICS: "epics", Action.CREATE_TASKS: "tasks", Action.DETECT_RISKS: "risks",
    Action.CREATE_DEPENDENCIES: "dependencies", Action.SET_PRIORITIES: "priorities",
    Action.PLAN_SPRINTS: "sprints", Action.ASSIGN_TASKS: "assignments", Action.SEMANTIC_REVIEW: "validator",
    Action.VALIDATE: None, Action.REPAIR_PLAN: None, Action.FINALIZE: None,
}


@dataclass
class PlannedAction:
    action: Action
    reason: str
    params: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        suffix = ":".join(str(v) for k, v in sorted(self.params.items()) if k in ("scope", "epic_id", "sprint", "kind"))
        return f"{self.action.value}:{suffix}" if suffix else self.action.value


def missing_task_types(state, team) -> list[str]:
    present = {t.type for t in state.tasks}
    roles = {m.role for m in team.members}
    return [ttype.value for role, ttype in ROLE_EXPECTED_TYPES.items()
            if role in roles and ttype not in present and role != Role.PROJECT_MANAGER]


def decide_next_action(state, team, settings) -> PlannedAction:
    ss = state.step_status
    P = PlannedAction

    # 1. understand the project ----------------------------------------------------------------
    if state.project is None:
        return P(Action.ANALYZE_PROJECT, "no project facts yet", {"scope": "project"})
    for scope in ("functional", "nfr_constraints"):
        if f"requirements:{scope}" not in ss:
            return P(Action.EXTRACT_REQUIREMENTS, f"{scope} requirements missing", {"scope": scope})
    if not state.epics:
        return P(Action.CREATE_EPICS, "requirements exist but no epics", {"kind": "epics"})

    # 2. tasks: one call per epic that still has no tasks ---------------------------------------
    for e in state.epics:
        if len(state.tasks_of_epic(e.id)) < settings.min_tasks_per_epic and f"tasks:{e.id}" not in ss:
            return P(Action.CREATE_TASKS, f"{e.id} has too few tasks", {"epic_id": e.id, "mode": "epic"})
    if "tasks:gaps" not in ss:
        gaps = missing_task_types(state, team)
        if gaps:
            return P(Action.CREATE_TASKS, f"no tasks of type {gaps} although the team has these roles",
                     {"kind": "gaps", "mode": "gap", "missing_types": gaps})

    # 3. risks (needs epics only) ---------------------------------------------------------------
    if "risks" not in ss:
        return P(Action.DETECT_RISKS, "risks not analysed yet", {"kind": "risks"})

    # 4. dependencies, priorities ------------------------------------------------------------------
    if len(state.tasks) > 1 and "dependencies" not in ss:
        return P(Action.CREATE_DEPENDENCIES, f"{len(state.tasks)} tasks without dependency analysis", {"kind": "deps"})
    missing = state.tasks_without_priority()
    if missing:
        return P(Action.SET_PRIORITIES, f"{len(missing)} tasks without priority", {"kind": "prio", "task_ids": [t.id for t in missing]})

    # 5. sprints and assignments -----------------------------------------------------------------
    if (not state.sprints or state.unscheduled_tasks()) and state.step_rounds.get("sprints", 0) < 3:
        return P(Action.PLAN_SPRINTS, "tasks are not scheduled into sprints", {"kind": "sprints"})
    for s in state.sprints:
        if state.unassigned_task_ids(s) and state.step_rounds.get(f"assign:{s.number}", 0) < 3:
            return P(Action.ASSIGN_TASKS, f"sprint {s.number} has unassigned tasks", {"sprint": s.number})

    # 6. validation gate ---------------------------------------------------------------------------
    if state.validation is None or state.validated_revision != state.revision:
        return P(Action.VALIDATE, "state changed since the last validation", {"kind": "validate"})
    if not state.validation.passed:
        if state.step_rounds.get("repair", 0) < settings.max_repair_rounds:
            return P(Action.REPAIR_PLAN, f"{state.validation.error_count} validation errors", {"kind": "repair"})
        return P(Action.FINALIZE, "validation failed and repair budget is exhausted", {"kind": "final"})
    if "semantic" not in ss:
        return P(Action.SEMANTIC_REVIEW, "deterministic validation passed; asking for semantic review", {"kind": "semantic"})
    return P(Action.FINALIZE, "plan complete and validated", {"kind": "final"})
