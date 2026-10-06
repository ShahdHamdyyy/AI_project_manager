"""Closed vocabularies used across the canonical state."""
from enum import Enum


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


PRIORITY_ORDER = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}


class TaskType(str, Enum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    DATABASE = "database"
    DESIGN = "design"
    QA = "qa"
    DEVOPS = "devops"
    DOCUMENTATION = "documentation"


class TaskStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class DependencyType(str, Enum):
    BLOCKS = "blocks"


class RequirementKind(str, Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    CONSTRAINT = "constraint"


class Level(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Role(str, Enum):
    PROJECT_MANAGER = "project_manager"
    BACKEND_DEVELOPER = "backend_developer"
    FRONTEND_DEVELOPER = "frontend_developer"
    UI_UX_DESIGNER = "ui_ux_designer"
    QA_ENGINEER = "qa_engineer"
    DEVOPS_ENGINEER = "devops_engineer"


# Which team role can execute which task type (used by scheduler, assigner and validator).
TYPE_TO_ROLE = {
    TaskType.BACKEND: Role.BACKEND_DEVELOPER,
    TaskType.DATABASE: Role.BACKEND_DEVELOPER,
    TaskType.FRONTEND: Role.FRONTEND_DEVELOPER,
    TaskType.DESIGN: Role.UI_UX_DESIGNER,
    TaskType.QA: Role.QA_ENGINEER,
    TaskType.DEVOPS: Role.DEVOPS_ENGINEER,
    TaskType.DOCUMENTATION: Role.PROJECT_MANAGER,
}

# Task types that a role is *expected* to have work for (used to detect missing information).
ROLE_EXPECTED_TYPES = {
    Role.UI_UX_DESIGNER: TaskType.DESIGN,
    Role.QA_ENGINEER: TaskType.QA,
    Role.DEVOPS_ENGINEER: TaskType.DEVOPS,
    Role.BACKEND_DEVELOPER: TaskType.BACKEND,
    Role.FRONTEND_DEVELOPER: TaskType.FRONTEND,
}

_PRIORITY_SYN = {
    "urgent": "critical", "blocker": "critical", "p0": "critical", "must": "critical", "highest": "critical",
    "important": "high", "p1": "high", "must-have": "high", "must have": "high",
    "normal": "medium", "med": "medium", "moderate": "medium", "p2": "medium", "should": "medium",
    "minor": "low", "p3": "low", "could": "low", "nice-to-have": "low", "optional": "low", "lowest": "low",
}
_TYPE_SYN = {
    "back-end": "backend", "back end": "backend", "api": "backend", "server": "backend", "development": "backend",
    "front-end": "frontend", "front end": "frontend", "ui": "frontend", "web": "frontend",
    "db": "database", "data": "database", "schema": "database",
    "ux": "design", "ui/ux": "design", "ux design": "design", "ui design": "design", "designer": "design",
    "testing": "qa", "test": "qa", "quality": "qa", "quality assurance": "qa",
    "infrastructure": "devops", "deployment": "devops", "ops": "devops", "ci/cd": "devops", "infra": "devops",
    "docs": "documentation", "management": "documentation", "planning": "documentation", "doc": "documentation",
}
_LEVEL_SYN = {"med": "medium", "moderate": "medium", "critical": "high", "severe": "high", "minor": "low"}
_STATUS_SYN = {"todo": "planned", "to do": "planned", "new": "planned", "open": "planned"}


def _norm(value):
    if isinstance(value, Enum):
        return value.value
    return str(value).strip().lower().replace("_", " ") if value is not None else ""


def coerce_enum(enum_cls, value, synonyms=None, default=None):
    """Map an LLM-provided string onto an enum. Raises ValueError if unknown and no default."""
    text = _norm(value)
    for member in enum_cls:
        if text in (member.value, member.value.replace("_", " ")):
            return member
    syn = (synonyms or {}).get(text)
    if syn:
        return enum_cls(syn)
    if default is not None:
        return default
    raise ValueError(f"'{value}' is not a valid {enum_cls.__name__}; allowed: {[m.value for m in enum_cls]}")


def coerce_priority(value, default=Priority.MEDIUM):
    return coerce_enum(Priority, value, _PRIORITY_SYN, default)


def coerce_task_type(value):
    return coerce_enum(TaskType, value, _TYPE_SYN)


def coerce_level(value, default=Level.MEDIUM):
    return coerce_enum(Level, value, _LEVEL_SYN, default)
