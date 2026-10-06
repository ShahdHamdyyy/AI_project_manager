"""Deterministic planning logic: sprint scheduling, assignment, heuristic dependencies.

The LLM only *suggests* (epic start sprints, member preferences). Placement, capacity and
eligibility are always decided here so plans cannot violate hard constraints silently.
"""
from __future__ import annotations

from collections import defaultdict

from models.enums import PRIORITY_ORDER, TYPE_TO_ROLE, Priority, TaskType
from orchestrator.state import normalize_id  # noqa: F401  (re-exported for agents)
from services.logging_setup import log


def schedule_tasks(state, team, settings, epic_start: dict[str, int] | None = None) -> dict[str, int]:
    """Assign every task to exactly one sprint.

    Constraints: dependency sprint <= task sprint; per-role pool capacity (utilisation target first, then
    100 %); QA floor from settings; load levelling so work is spread over all sprints. If nothing fits, the
    task goes to the last sprint and the deterministic validator reports the capacity violation.
    """
    n = state.project.sprint_count
    epic_start = epic_start or {}
    pools = team.pool_capacity()
    util = settings.utilization_target
    tasks = {t.id: t for t in state.tasks}
    blockers: dict[str, set[str]] = defaultdict(set)
    for t, d in state.edges():
        if t in tasks and d in tasks:
            blockers[t].add(d)
    rank = {p.task_id: p.rank for p in state.priorities}
    total = sum(t.estimated_hours for t in tasks.values())
    soft_total = total / n * 1.15
    used_pool = [defaultdict(float) for _ in range(n + 1)]
    used_total = [0.0] * (n + 1)
    placed: dict[str, int] = {}
    remaining = set(tasks)

    def rule_for(t):
        if t.type == TaskType.DESIGN:
            return None
        title = t.title.lower()
        return next((r for r in settings.sprint_rules if any(k in title for k in r["match"])), None)

    def order_key(tid: str):
        t = tasks[tid]
        return (rank.get(tid, 9999), PRIORITY_ORDER[t.priority], epic_start.get(t.epic_id, 1), tid)

    while remaining:
        ready = [x for x in remaining if blockers[x] <= set(placed)]
        if not ready:  # cannot happen if the graph is acyclic; never loop forever
            log("ERROR", "scheduler found no ready task (cycle?); forcing lowest id", 40)
            ready = [min(remaining)]
        tid = min(ready, key=order_key)
        t = tasks[tid]
        role = TYPE_TO_ROLE[t.type]
        h = t.estimated_hours
        rule = rule_for(t)
        start_hint = int(rule.get("min", 1)) if rule else epic_start.get(t.epic_id, 1)   # an explicit rule beats the LLM hint
        earliest = max([1, start_hint, int(settings.type_min_sprint.get(t.type.value, 1))]
                       + [placed[d] for d in blockers[tid] if d in placed])
        earliest = min(earliest, n)
        latest = min(n, int(rule["max"])) if rule and rule.get("max") else n
        cap = pools.get(role, 0.0)

        def fits(s, pool_limit, total_limit):
            return used_pool[s][role] + h <= pool_limit + 1e-9 and (total_limit is None or used_total[s] + h <= total_limit)

        def pick(hi):
            return (next((s for s in range(earliest, hi + 1) if fits(s, cap * util, soft_total)), None)
                    or next((s for s in range(earliest, hi + 1) if fits(s, cap * util, None)), None)
                    or next((s for s in range(earliest, hi + 1) if fits(s, cap, None)), None))

        choice = pick(latest) or (pick(n) if latest < n else None)
        if choice is None:
            choice = n
            log("VALIDATION", f"{tid} ({h:g}h {role.value}) does not fit any sprint >= {earliest}; placed in sprint {n} (over capacity)")
        placed[tid] = choice
        used_pool[choice][role] += h
        used_total[choice] += h
        remaining.discard(tid)
    return placed


def assign_sprint(state, team, sprint_number: int, suggestions: dict[str, str] | None = None) -> tuple[int, list[str]]:
    """Assign all unassigned tasks of a sprint. Honour a suggestion only if the member has the right role
    and enough remaining capacity; otherwise pick the least-loaded eligible member."""
    from models.sprint import Assignment
    suggestions = suggestions or {}
    sprint = state.sprint_by_number(sprint_number)
    loads = defaultdict(float, state.member_loads(sprint.id))
    todo = [state.task(t) for t in state.unassigned_task_ids(sprint)]
    notes: list[str] = []
    made = 0

    def place(task, member, reason):
        nonlocal made
        state.assignments.append(Assignment(task_id=task.id, member_id=member.id, sprint_id=sprint.id, reason=reason))
        loads[member.id] += task.estimated_hours
        made += 1

    leftovers = []
    rank = {p.task_id: p.rank for p in state.priorities}
    for task in sorted(todo, key=lambda t: rank.get(t.id, 9999)):
        eligible = team.by_role(TYPE_TO_ROLE[task.type])
        want = normalize_id(suggestions.get(task.id, ""))
        member = next((m for m in eligible if m.id == want), None)
        least = min((loads[m.id] for m in eligible), default=0.0)
        if (member and loads[member.id] + task.estimated_hours <= member.capacity_hours_per_sprint
                and loads[member.id] - least <= 0.4 * member.capacity_hours_per_sprint):
            place(task, member, "agent choice (role + skills + capacity)")
        else:
            if want and not member:
                notes.append(f"{task.id}: suggested member '{want}' invalid or wrong role -> reassigned")
            elif want:
                notes.append(f"{task.id}: suggested member over capacity or unbalanced -> reassigned")
            leftovers.append(task)
    for task in sorted(leftovers, key=lambda t: -t.estimated_hours):
        eligible = team.by_role(TYPE_TO_ROLE[task.type])
        if not eligible:
            notes.append(f"{task.id}: no team member with role {TYPE_TO_ROLE[task.type].value}")
            continue
        member = min(eligible, key=lambda m: (loads[m.id] / m.capacity_hours_per_sprint, m.id))
        place(task, member, "auto: least-loaded eligible member")
    for msg in notes:
        log("VALIDATION", msg)
    return made, notes


_STAGE = [TaskType.DESIGN, TaskType.DATABASE, TaskType.BACKEND, TaskType.FRONTEND, TaskType.QA, TaskType.DEVOPS,
          TaskType.DOCUMENTATION]


def heuristic_dependency_pairs(state):
    """Documented fallback when the dependency agent fails: within each epic, a task depends on the
    last task of the nearest earlier stage (design -> database -> backend -> frontend -> qa)."""
    pairs = []
    for epic in state.epics:
        by_stage = {s: [t for t in state.tasks_of_epic(epic.id) if t.type == s] for s in _STAGE}
        prev = None
        for stage in _STAGE[:5]:
            group = by_stage[stage]
            if not group:
                continue
            if prev:
                for t in group:
                    pairs.append((t.id, prev[-1].id, f"heuristic: {stage.value} follows {prev[-1].type.value} in the same epic"))
            prev = group
    return pairs
