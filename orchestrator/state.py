"""Canonical ProjectState.

Rules enforced here (not by the LLM):
  * Python generates every ID (EPIC-001, TASK-001, ...).
  * Agent output is only *proposals*; every reference is validated before it enters the state.
  * Dependencies / priorities / sprints / assignments can only reference TASK ids.
"""
from __future__ import annotations

import re
from collections import Counter

from models.base import StrictModel
from models.enums import (PRIORITY_ORDER, Level, Priority, RequirementKind, TaskStatus)
from models.epic import Epic
from models.project import Milestone, Project, Requirement, Risk
from models.sprint import Assignment, Sprint
from models.task import Dependency, PriorityEntry, Task
from models.validation import ValidationReport
from services.errors import StateUpdateError
from services.graph import topo_order, would_create_cycle
from services.logging_setup import log

_ID_RE = re.compile(r"^\s*(EPIC|TASK|REQ|SPRINT|RISK|TEAM|MS)[-_ ]?0*(\d+)\s*$", re.IGNORECASE)


def normalize_id(raw: str) -> str:
    """'task-1' / 'TASK 001' -> 'TASK-001'. Anything else is returned upper-cased and trimmed."""
    m = _ID_RE.match(raw or "")
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2)):03d}"
    return (raw or "").strip().upper()


def _key(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _upd(msg: str) -> None:
    log("STATE UPDATE", msg)


class ProjectState(StrictModel):
    project: Project | None = None
    requirements: list[Requirement] = []
    epics: list[Epic] = []
    tasks: list[Task] = []
    dependencies: list[Dependency] = []
    priorities: list[PriorityEntry] = []
    sprints: list[Sprint] = []
    assignments: list[Assignment] = []
    risks: list[Risk] = []
    milestones: list[Milestone] = []
    validation: ValidationReport | None = None

    # orchestration bookkeeping (part of the checkpoint, not of the business plan)
    id_counters: dict[str, int] = {}
    step_status: dict[str, str] = {}
    step_rounds: dict[str, int] = {}
    revision: int = 0
    validated_revision: int = -1
    document_hash: str = ""
    epic_start: dict[str, int] = {}   # sprint-start hints from the Sprint Planner (validated)

    # ------------------------------------------------------------------ ids / lookups
    def new_id(self, prefix: str) -> str:
        n = self.id_counters.get(prefix, 0) + 1
        self.id_counters[prefix] = n
        return f"{prefix}-{n:03d}"

    def task_ids(self) -> set[str]:
        return {t.id for t in self.tasks}

    def epic_ids(self) -> set[str]:
        return {e.id for e in self.epics}

    def task(self, task_id: str):
        return next((t for t in self.tasks if t.id == task_id), None)

    def sprint_by_number(self, number: int):
        return next((s for s in self.sprints if s.number == number), None)

    def edges(self) -> list[tuple[str, str]]:
        return [(d.task_id, d.depends_on) for d in self.dependencies]

    def tasks_of_epic(self, epic_id: str) -> list[Task]:
        return [t for t in self.tasks if t.epic_id == epic_id]

    def bump(self) -> None:
        self.revision += 1

    def bump_round(self, key: str) -> int:
        self.step_rounds[key] = self.step_rounds.get(key, 0) + 1
        return self.step_rounds[key]

    # ------------------------------------------------------------------ project + requirements
    def set_project(self, analysis, doc, settings) -> str:
        detected = doc.detect_duration_weeks()
        llm_weeks = analysis.duration_weeks if 1 <= analysis.duration_weeks <= 26 else None
        weeks = detected or llm_weeks or settings.default_duration_weeks
        if llm_weeks and detected and llm_weeks != detected:
            log("VALIDATION", f"LLM duration ({llm_weeks}w) disagrees with document ({detected}w); using document")
        sprint_count = max(1, weeks // settings.sprint_length_weeks)
        name = analysis.name.strip() or doc.title or "Untitled project"
        summary = analysis.summary.strip()
        if not summary:
            raise StateUpdateError("project summary is empty; provide a 1-2 sentence summary")
        self.project = Project(
            name=name, summary=summary, objective=analysis.objective, duration_weeks=weeks,
            sprint_count=sprint_count, sprint_length_weeks=settings.sprint_length_weeks,
            actors=analysis.actors, mvp_scope=analysis.mvp_scope, out_of_scope=analysis.out_of_scope,
            assumptions=analysis.assumptions, business_priority=analysis.business_priority)
        self.document_hash = doc.sha256
        msg = f"project '{name}' ({weeks} weeks -> {sprint_count} sprints, {len(analysis.actors)} actors)"
        _upd(msg)
        return msg

    def add_requirements(self, items, scope: str) -> str:
        seen = {_key(r.title) for r in self.requirements}
        added = 0
        for it in items:
            title = it.title.strip()
            if not title or _key(title) in seen:
                continue
            if scope == "functional":
                kind = RequirementKind.FUNCTIONAL
            else:
                kind = RequirementKind.CONSTRAINT if "constraint" in it.kind.lower() else RequirementKind.NON_FUNCTIONAL
            self.requirements.append(Requirement(
                id=self.new_id("REQ"), kind=kind, title=title, description=it.description, priority=it.priority))
            seen.add(_key(title))
            added += 1
        minimum = 4 if scope == "functional" else 3
        if added < minimum:
            raise StateUpdateError(f"only {added} usable requirements; expected at least {minimum}. List every requirement in the text.")
        if scope != "functional" and self.project:
            self.project.constraints = [r.title for r in self.requirements if r.kind == RequirementKind.CONSTRAINT]
        _upd(f"{added} {scope} requirements added")
        return f"{added} requirements ({scope})"

    # ------------------------------------------------------------------ epics / tasks
    def add_epics(self, items, settings) -> str:
        req_ids = {r.id for r in self.requirements}
        seen = {_key(e.name) for e in self.epics}
        added = 0
        for it in items[: settings.max_epics]:
            name = it.name.strip()
            if not name or _key(name) in seen:
                continue
            refs = [normalize_id(x) for x in it.requirement_ids]
            valid = [r for r in dict.fromkeys(refs) if r in req_ids]
            if len(valid) != len(set(refs)):
                log("VALIDATION", f"Epic '{name}': dropped invalid requirement refs {sorted(set(refs) - set(valid))}")
            self.epics.append(Epic(id=self.new_id("EPIC"), name=name, description=it.description,
                                   priority=it.priority, requirement_ids=valid))
            seen.add(_key(name))
            added += 1
        if added < 3:
            raise StateUpdateError(f"only {added} epics; produce between 4 and {settings.max_epics} distinct epics")
        _upd(f"{added} epics added")
        return f"{added} epics"

    def add_tasks(self, items, settings, epic_id: str | None = None) -> str:
        epic_ids = self.epic_ids()
        seen = {_key(t.title) for t in self.tasks}
        added = clamped = 0
        limit = settings.max_tasks_per_epic if epic_id else settings.max_tasks_per_epic * 2
        for it in items[:limit]:
            target = epic_id or normalize_id(getattr(it, "epic_id", ""))
            if target not in epic_ids:
                log("VALIDATION", f"Task '{it.title[:40]}': unknown epic '{target}' -> skipped")
                continue
            title = it.title.strip()
            if not title or _key(title) in seen:
                continue
            hours = min(max(it.estimated_hours, settings.min_estimate_hours), settings.max_estimate_hours)
            hours = round(hours * 2) / 2
            if hours != it.estimated_hours:
                clamped += 1
            self.tasks.append(Task(id=self.new_id("TASK"), epic_id=target, title=title, type=it.type,
                                   description=it.description, estimated_hours=hours, priority=it.priority,
                                   status=TaskStatus.PLANNED))
            seen.add(_key(title))
            added += 1
        need = 1 if not epic_id else 2
        if added < need:
            raise StateUpdateError(f"only {added} valid tasks; produce 3 to {settings.max_tasks_per_epic} tasks")
        if clamped:
            log("VALIDATION", f"{clamped} estimate(s) clamped into [{settings.min_estimate_hours}, {settings.max_estimate_hours}]h")
        _upd(f"{added} tasks added" + (f" to {epic_id}" if epic_id else " (gap fill)"))
        return f"{added} tasks" + (f" for {epic_id}" if epic_id else " (gap fill)")

    # ------------------------------------------------------------------ dependencies
    def add_dependency_pairs(self, pairs, settings, reason_default="") -> tuple[int, list[str]]:
        """pairs: iterable of (task_id, depends_on, reason). Returns (added, rejected_messages)."""
        ids = self.task_ids()
        edges = self.edges()
        per_task = Counter(t for t, _ in edges)
        added, rejected = 0, []
        for t_raw, d_raw, reason in pairs:
            t, d = normalize_id(t_raw), normalize_id(d_raw)
            if t not in ids or d not in ids:
                why = "EPIC id where TASK id expected" if t.startswith("EPIC") or d.startswith("EPIC") else "unknown task id"
                rejected.append(f"{t}<-{d}: {why}")
            elif t == d:
                rejected.append(f"{t}<-{d}: self dependency")
            elif (t, d) in edges:
                continue
            elif per_task[t] >= settings.max_dependencies_per_task:
                rejected.append(f"{t}<-{d}: too many dependencies for one task")
            elif would_create_cycle(ids, edges, (t, d)):
                rejected.append(f"{t}<-{d}: would create a circular dependency")
            else:
                self.dependencies.append(Dependency(task_id=t, depends_on=d, reason=reason or reason_default))
                edges.append((t, d))
                per_task[t] += 1
                added += 1
        for msg in rejected:
            log("VALIDATION", f"Dependency rejected: {msg}")
        return added, rejected

    def add_dependencies(self, items, settings) -> str:
        added, rejected = self.add_dependency_pairs(((i.task_id, i.depends_on, i.reason) for i in items), settings)
        if added == 0:
            raise StateUpdateError("no valid dependencies. Use ONLY task ids (TASK-xxx) from the list; epic ids are not allowed. "
                                   f"Rejected: {rejected[:3]}")
        self.recompute_priorities()
        _upd(f"{added} dependencies added ({len(rejected)} rejected)")
        return f"{added} dependencies ({len(rejected)} rejected)"

    # ------------------------------------------------------------------ priorities
    def set_priorities(self, items) -> str:
        ids = self.task_ids()
        current = {e.task_id: e.priority for e in self.priorities}
        applied = 0
        for it in items:
            tid = normalize_id(it.task_id)
            if tid not in ids:
                log("VALIDATION", f"Priority for unknown id '{tid}' ignored")
                continue
            current[tid] = it.priority
            applied += 1
        if applied == 0:
            raise StateUpdateError("no priority referenced a valid TASK id from the list")
        self.priorities = [PriorityEntry(task_id=t, priority=p) for t, p in current.items()]
        self.recompute_priorities()
        _upd(f"{applied} priorities set")
        return f"{applied} priorities"

    def fill_default_priorities(self) -> int:
        have = {e.task_id for e in self.priorities}
        missing = [t for t in self.tasks if t.id not in have]
        for t in missing:
            self.priorities.append(PriorityEntry(task_id=t.id, priority=t.priority))
        self.recompute_priorities()
        return len(missing)

    def recompute_priorities(self) -> None:
        """Blockers may never rank below the tasks they block; ranks are computed by Python."""
        if not self.priorities:
            return
        prio = {e.task_id: e.priority for e in self.priorities if e.task_id in self.task_ids()}
        order = topo_order([t.id for t in self.tasks], self.edges())
        blockers: dict[str, list[str]] = {}
        for t, d in self.edges():
            blockers.setdefault(t, []).append(d)
        for tid in reversed(order):
            if tid not in prio:
                continue
            for d in blockers.get(tid, []):
                if d in prio and PRIORITY_ORDER[prio[tid]] < PRIORITY_ORDER[prio[d]]:
                    log("VALIDATION", f"Priority of blocker {d} raised {prio[d].value}->{prio[tid].value} (blocks {tid})")
                    prio[d] = prio[tid]
        pos = {tid: i for i, tid in enumerate(order)}
        ranked = sorted(prio, key=lambda x: (PRIORITY_ORDER[prio[x]], pos[x]))
        self.priorities = [PriorityEntry(task_id=t, priority=prio[t], rank=i + 1) for i, t in enumerate(ranked)]
        for t in self.tasks:
            if t.id in prio:
                t.priority = prio[t.id]

    def tasks_without_priority(self) -> list[Task]:
        have = {e.task_id for e in self.priorities}
        return [t for t in self.tasks if t.id not in have]

    # ------------------------------------------------------------------ risks
    def add_risks(self, items, settings) -> str:
        epic_ids = self.epic_ids()
        seen = {_key(r.title) for r in self.risks}
        added = 0
        for it in items[: settings.max_risks]:
            title = it.title.strip()
            if not title or _key(title) in seen:
                continue
            refs = [normalize_id(x) for x in it.epic_ids]
            self.risks.append(Risk(id=self.new_id("RISK"), title=title, description=it.description,
                                   likelihood=it.likelihood, impact=it.impact, mitigation=it.mitigation,
                                   epic_ids=[r for r in dict.fromkeys(refs) if r in epic_ids]))
            seen.add(_key(title))
            added += 1
        if added < 2:
            raise StateUpdateError("fewer than 2 usable risks; list the main delivery risks with mitigations")
        _upd(f"{added} risks added")
        return f"{added} risks"

    # ------------------------------------------------------------------ sprints
    def plan_sprints(self, goals: dict[int, str], milestone_names: dict[int, str], epic_start: dict[str, int],
                     team, settings) -> str:
        from orchestrator.planning import schedule_tasks
        if not self.project:
            raise StateUpdateError("cannot plan sprints before the project is analysed")
        placement = schedule_tasks(self, team, settings, epic_start)
        n = self.project.sprint_count
        self.sprints, self.milestones, self.assignments = [], [], []
        self.id_counters["SPRINT"] = 0
        self.id_counters["MS"] = 0
        by_id = {t.id: t for t in self.tasks}
        for k in range(1, n + 1):
            ids = [t.id for t in self.tasks if placement.get(t.id) == k]
            sprint = Sprint(id=self.new_id("SPRINT"), number=k,
                            goal=goals.get(k) or f"Deliver the planned scope of sprint {k}",
                            task_ids=ids, capacity_hours=team.total_capacity,
                            planned_hours=sum(by_id[i].estimated_hours for i in ids))
            self.sprints.append(sprint)
            self.milestones.append(Milestone(
                id=self.new_id("MS"), name=milestone_names.get(k) or f"End of sprint {k}", sprint_id=sprint.id,
                week=k * self.project.sprint_length_weeks, criteria=sprint.goal))
        summary = ", ".join(f"S{s.number}={s.planned_hours:g}h/{len(s.task_ids)}t" for s in self.sprints)
        _upd(f"sprints planned: {summary}")
        return f"{n} sprints ({summary})"

    def member_loads(self, sprint_id: str) -> dict[str, float]:
        loads: dict[str, float] = {}
        for a in self.assignments:
            if a.sprint_id == sprint_id and (t := self.task(a.task_id)):
                loads[a.member_id] = loads.get(a.member_id, 0.0) + t.estimated_hours
        return loads

    def unassigned_task_ids(self, sprint: Sprint) -> list[str]:
        done = {a.task_id for a in self.assignments}
        return [t for t in sprint.task_ids if t not in done]

    def unscheduled_tasks(self) -> list[Task]:
        placed = {t for s in self.sprints for t in s.task_ids}
        return [t for t in self.tasks if t.id not in placed]

    # ------------------------------------------------------------------ exports
    def workload(self, team) -> dict:
        out: dict = {}
        sprint_num = {s.id: s.number for s in self.sprints}
        for m in team.members:
            per = {s.id: 0.0 for s in self.sprints}
            for a in self.assignments:
                if a.member_id == m.id and (t := self.task(a.task_id)):
                    per[a.sprint_id] = per.get(a.sprint_id, 0.0) + t.estimated_hours
            out[m.id] = {
                "name": m.name, "role": m.role.value, "capacity_hours_per_sprint": m.capacity_hours_per_sprint,
                "hours_per_sprint": {sid: h for sid, h in sorted(per.items(), key=lambda kv: sprint_num.get(kv[0], 0))},
                "total_hours": sum(per.values()),
            }
        return out

    def plan_dict(self, team) -> dict:
        return {
            "project": self.project.model_dump(mode="json") if self.project else None,
            "requirements": [r.model_dump(mode="json") for r in self.requirements],
            "epics": [e.model_dump(mode="json") for e in self.epics],
            "tasks": [t.model_dump(mode="json") for t in self.tasks],
            "dependencies": [d.model_dump(mode="json") for d in self.dependencies],
            "priorities": [p.model_dump(mode="json") for p in self.priorities],
            "sprints": [s.model_dump(mode="json") for s in self.sprints],
            "assignments": [a.model_dump(mode="json") for a in self.assignments],
            "risks": [r.model_dump(mode="json") for r in self.risks],
            "milestones": [m.model_dump(mode="json") for m in self.milestones],
            "validation": self.validation.model_dump(mode="json") if self.validation else None,
            "team": [m.model_dump(mode="json") for m in team.members],
            "workload": self.workload(team),
        }
