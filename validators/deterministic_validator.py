"""Authoritative, LLM-free validation of the canonical project state."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from models.enums import (Level, Priority, RequirementKind, Role, TaskStatus, TaskType, DependencyType,
                          TYPE_TO_ROLE)
from models.validation import ValidationIssue, ValidationReport
from services.graph import find_cycle
from services.logging_setup import log

_PREFIX = {"epics": "EPIC", "tasks": "TASK", "requirements": "REQ", "sprints": "SPRINT", "risks": "RISK",
           "milestones": "MS"}


def _val(x):
    return getattr(x, "value", x)


class DeterministicValidator:
    def __init__(self, team, settings):
        self.team = team
        self.settings = settings

    def validate(self, state, stage: str = "final") -> ValidationReport:
        issues: list[ValidationIssue] = []

        def add(code, msg, entity="", severity="error"):
            issues.append(ValidationIssue(code=code, severity=severity, message=msg, entity_id=entity))

        final = stage == "final"
        log("VALIDATION", f"Running deterministic checks (stage={stage}, revision={state.revision})")
        self._ids(state, add)
        self._required_and_enums(state, add)
        self._references(state, add)
        self._dependencies(state, add)
        self._estimates(state, add)
        if state.sprints:
            self._sprints(state, add, final)
        if state.assignments:
            self._assignments(state, add)
        if final:
            self._completeness(state, add)
            self._roundtrip(state, add)

        errors = [i for i in issues if i.severity == "error"]
        report = ValidationReport(
            stage=stage, passed=not errors, error_count=len(errors),
            warning_count=len(issues) - len(errors), issues=issues, checked_revision=state.revision)
        for i in issues[:15]:
            log("VALIDATION", f"{i.severity.upper()} {i.code} {i.entity_id}: {i.message}")
        log("VALIDATION", f"{'PASS' if report.passed else 'FAIL'} ({report.error_count} errors, {report.warning_count} warnings)")
        return report

    # ---------------------------------------------------------------- checks
    def _ids(self, state, add):
        for attr, prefix in _PREFIX.items():
            ids = [getattr(x, "id", "") for x in getattr(state, attr)]
            for i, n in Counter(ids).items():
                if n > 1:
                    add("DUPLICATE_ID", f"{attr}: id {i} appears {n} times", i)
            for i in ids:
                if not i:
                    add("MISSING_ID", f"{attr}: entity without id")
                elif not re.fullmatch(rf"{prefix}-\d{{3,}}", i):
                    add("BAD_ID_FORMAT", f"{attr}: id '{i}' does not match {prefix}-NNN", i)

    def _required_and_enums(self, state, add):
        if state.project is None:
            add("MISSING_PROJECT", "project section missing")
        else:
            for f in ("name", "summary"):
                if not getattr(state.project, f).strip():
                    add("MISSING_FIELD", f"project.{f} is empty")
            if state.project.sprint_count < 1:
                add("BAD_SPRINT_COUNT", "project.sprint_count must be >= 1")
        for e in state.epics:
            if not e.name.strip():
                add("MISSING_FIELD", "epic name empty", e.id)
            if _val(e.priority) not in {p.value for p in Priority}:
                add("INVALID_ENUM", f"epic priority '{_val(e.priority)}'", e.id)
        for t in state.tasks:
            if not t.title.strip():
                add("MISSING_FIELD", "task title empty", t.id)
            if _val(t.priority) not in {p.value for p in Priority}:
                add("INVALID_PRIORITY", f"task priority '{_val(t.priority)}'", t.id)
            if _val(t.type) not in {x.value for x in TaskType}:
                add("INVALID_ENUM", f"task type '{_val(t.type)}'", t.id)
            if _val(t.status) not in {x.value for x in TaskStatus}:
                add("INVALID_STATUS", f"task status '{_val(t.status)}'", t.id)
        for r in state.requirements:
            if _val(r.kind) not in {x.value for x in RequirementKind}:
                add("INVALID_ENUM", f"requirement kind '{_val(r.kind)}'", r.id)
        for r in state.risks:
            for f in ("likelihood", "impact"):
                if _val(getattr(r, f)) not in {x.value for x in Level}:
                    add("INVALID_ENUM", f"risk {f} '{_val(getattr(r, f))}'", r.id)
        for d in state.dependencies:
            if _val(d.type) not in {x.value for x in DependencyType}:
                add("INVALID_ENUM", f"dependency type '{_val(d.type)}'", d.task_id)
        for p in state.priorities:
            if _val(p.priority) not in {x.value for x in Priority}:
                add("INVALID_PRIORITY", f"priority entry '{_val(p.priority)}'", p.task_id)

    def _references(self, state, add):
        epics, tasks = state.epic_ids(), state.task_ids()
        reqs = {r.id for r in state.requirements}
        for t in state.tasks:
            if t.epic_id not in epics:
                code = "ORPHAN_TASK"
                add(code, f"task references non-existing epic '{t.epic_id}'", t.id)
        for e in state.epics:
            for r in e.requirement_ids:
                if r not in reqs:
                    add("INVALID_REFERENCE", f"epic references unknown requirement '{r}'", e.id)
        for p in state.priorities:
            if p.task_id not in tasks:
                add("INVALID_REFERENCE", f"priority references unknown task '{p.task_id}'"
                    + (" (EPIC id used as TASK id)" if p.task_id.startswith("EPIC") else ""), p.task_id)
        for r in state.risks:
            for e in r.epic_ids:
                if e not in epics:
                    add("INVALID_REFERENCE", f"risk references unknown epic '{e}'", r.id)
        for m in state.milestones:
            if m.sprint_id not in {s.id for s in state.sprints}:
                add("INVALID_REFERENCE", f"milestone references unknown sprint '{m.sprint_id}'", m.id)
        counts = Counter(p.task_id for p in state.priorities)
        for t, n in counts.items():
            if n > 1:
                add("DUPLICATE_PRIORITY", f"task has {n} priority entries", t)
        for p in state.priorities:
            t = state.task(p.task_id)
            if t and _val(t.priority) != _val(p.priority):
                add("PRIORITY_MISMATCH", f"task.priority={_val(t.priority)} but priority entry={_val(p.priority)}", t.id)

    def _dependencies(self, state, add):
        tasks = state.task_ids()
        seen = set()
        for d in state.dependencies:
            for f in ("task_id", "depends_on"):
                v = getattr(d, f)
                if v not in tasks:
                    add("INVALID_DEPENDENCY_REF",
                        f"dependency {f}='{v}' is not an existing TASK id" + (" (EPIC id)" if v.startswith("EPIC") else ""), d.task_id)
            if d.task_id == d.depends_on:
                add("SELF_DEPENDENCY", "task depends on itself", d.task_id)
            if (d.task_id, d.depends_on) in seen:
                add("DUPLICATE_DEPENDENCY", f"{d.task_id} <- {d.depends_on} declared twice", d.task_id)
            seen.add((d.task_id, d.depends_on))
        cycle = find_cycle(tasks, state.edges())
        if cycle:
            add("CIRCULAR_DEPENDENCY", "cycle: " + " -> ".join(cycle), cycle[0])

    def _estimates(self, state, add):
        lo, hi = self.settings.min_estimate_hours, self.settings.max_estimate_hours
        for t in state.tasks:
            if not isinstance(t.estimated_hours, (int, float)) or not (lo <= t.estimated_hours <= hi):
                add("INVALID_ESTIMATE", f"estimated_hours={t.estimated_hours} outside [{lo}, {hi}]", t.id)

    def _sprints(self, state, add, final):
        tasks = state.task_ids()
        where = defaultdict(list)
        for s in state.sprints:
            for tid in s.task_ids:
                where[tid].append(s.number)
                if tid not in tasks:
                    add("INVALID_SPRINT_REF", f"sprint references unknown task '{tid}'"
                        + (" (EPIC id used as TASK id)" if tid.startswith("EPIC") else ""), s.id)
        for tid, nums in where.items():
            if len(nums) > 1:
                add("TASK_IN_MULTIPLE_SPRINTS", f"task appears in sprints {nums}", tid)
        for t in state.tasks:
            if t.id not in where:
                add("TASK_NOT_IN_SPRINT", "task is not scheduled in any sprint", t.id)
        for d in state.dependencies:
            a, b = where.get(d.task_id), where.get(d.depends_on)
            if a and b and min(a) < min(b):
                add("DEPENDENCY_ORDER", f"{d.task_id} (sprint {min(a)}) is scheduled before its blocker {d.depends_on} (sprint {min(b)})", d.task_id)
        if state.project and len(state.sprints) != state.project.sprint_count:
            add("SPRINT_COUNT", f"{len(state.sprints)} sprints planned but project needs {state.project.sprint_count}")
        by_id = {t.id: t for t in state.tasks}
        pools = self.team.pool_capacity()
        for s in state.sprints:
            valid = [by_id[i] for i in s.task_ids if i in by_id]
            hours = sum(t.estimated_hours for t in valid)
            if abs(hours - s.planned_hours) > 0.01:
                add("PLANNED_HOURS_MISMATCH", f"planned_hours={s.planned_hours} but tasks sum to {hours}", s.id)
            if final and hours > s.capacity_hours + 1e-9:
                add("SPRINT_CAPACITY", f"{hours:g}h planned > {s.capacity_hours:g}h capacity", s.id)
            per_role = defaultdict(float)
            for t in valid:
                per_role[TYPE_TO_ROLE[t.type]] += t.estimated_hours
            for role, h in per_role.items():
                cap = pools.get(role, 0.0)
                if final and h > cap + 1e-9:
                    add("ROLE_CAPACITY", f"{role.value}: {h:g}h planned > {cap:g}h available", s.id)
            if not valid:
                add("EMPTY_SPRINT", "sprint has no tasks", s.id, "warning")
            if not s.goal.strip():
                add("MISSING_FIELD", "sprint goal empty", s.id)

    def _assignments(self, state, add):
        tasks = state.task_ids()
        sprint_of = {t: s.id for s in state.sprints for t in s.task_ids}
        by_id = {t.id: t for t in state.tasks}
        seen = Counter(a.task_id for a in state.assignments)
        for tid, n in seen.items():
            if n > 1:
                add("DUPLICATE_ASSIGNMENT", f"task assigned {n} times", tid)
        loads = defaultdict(float)
        for a in state.assignments:
            member = self.team.get(a.member_id)
            if a.task_id not in tasks:
                add("INVALID_ASSIGNMENT_TASK", f"assignment references unknown task '{a.task_id}'"
                    + (" (EPIC id)" if a.task_id.startswith("EPIC") else ""), a.task_id)
                continue
            if member is None:
                add("INVALID_ASSIGNMENT_MEMBER", f"unknown team member '{a.member_id}'", a.task_id)
                continue
            t = by_id[a.task_id]
            if member.role != TYPE_TO_ROLE[t.type]:
                add("ROLE_MISMATCH", f"{member.name} ({member.role.value}) cannot do a {t.type.value} task", t.id)
            if sprint_of.get(t.id) != a.sprint_id:
                add("ASSIGNMENT_SPRINT_MISMATCH", f"assignment sprint {a.sprint_id} != task sprint {sprint_of.get(t.id)}", t.id)
            loads[(a.member_id, a.sprint_id)] += t.estimated_hours
        for (mid, sid), h in loads.items():
            cap = self.team.get(mid).capacity_hours_per_sprint
            if h > cap + 1e-9:
                add("MEMBER_OVERLOAD", f"{self.team.get(mid).name} has {h:g}h in {sid} (capacity {cap:g}h)", mid, "warning")

    def _completeness(self, state, add):
        for lst, name in ((state.requirements, "requirements"), (state.epics, "epics"), (state.tasks, "tasks"),
                          (state.sprints, "sprints"), (state.risks, "risks")):
            if not lst:
                add("EMPTY_SECTION", f"{name} is empty")
        for e in state.epics:
            n = len(state.tasks_of_epic(e.id))
            if n == 0:
                add("EPIC_WITHOUT_TASKS", "epic has no tasks", e.id)
            elif n < self.settings.min_tasks_per_epic:
                add("EPIC_TOO_FEW_TASKS", f"epic has {n} task(s); at least {self.settings.min_tasks_per_epic} expected", e.id)
        for t in state.tasks_without_priority():
            add("MISSING_PRIORITY", "task has no priority entry", t.id)
        assigned = {a.task_id for a in state.assignments}
        for t in state.tasks:
            if t.id not in assigned:
                add("TASK_NOT_ASSIGNED", "task has no assignment", t.id)
        covered = {r for e in state.epics for r in e.requirement_ids}
        for r in state.requirements:
            if r.kind == RequirementKind.FUNCTIONAL and r.id not in covered:
                add("REQUIREMENT_UNCOVERED", f"functional requirement '{r.title}' is not linked to any epic", r.id, "warning")

    def _roundtrip(self, state, add):
        from orchestrator.state import ProjectState
        try:
            ProjectState.model_validate(state.model_dump(mode="json"))
        except Exception as exc:  # any schema violation is an error
            add("SCHEMA_ROUNDTRIP", f"state does not satisfy the strict schema: {str(exc)[:200]}")
