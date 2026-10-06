"""Project Manager Orchestrator.

Loop:  inspect state -> decide next action -> select agent -> run agent -> validate output
       -> merge into canonical state (transactionally) -> consistency check -> retry/repair -> repeat
Finally: full deterministic validation gates completion.
"""
from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone

from models.enums import TYPE_TO_ROLE
from orchestrator.decisions import AGENT_FOR_ACTION, Action, PlannedAction, decide_next_action
from orchestrator.planning import assign_sprint, heuristic_dependency_pairs
from orchestrator.state import ProjectState, normalize_id
from services.errors import (AgentFailure, AgentOutputError, LLMError, ModelUnavailableError, OllamaUnavailableError,
                             OrchestrationError, StateUpdateError)
from services.graph import find_cycle
from services.logging_setup import log
from validators.deterministic_validator import DeterministicValidator
from validators.semantic_validator import SemanticValidator

# Steps whose failure makes further planning meaningless.
FATAL_ACTIONS = {Action.ANALYZE_PROJECT, Action.EXTRACT_REQUIREMENTS, Action.CREATE_EPICS}


class Orchestrator:
    def __init__(self, settings, team, agents: dict, store, document):
        self.settings, self.team, self.agents, self.store, self.doc = settings, team, agents, store, document
        self.deterministic = DeterministicValidator(team, settings)
        self.semantic = SemanticValidator(agents["validator"])
        self.state = ProjectState()
        self.exec_log: list[dict] = []
        self.llm_calls = 0
        self.started = time.time()
        self._rounds = Counter()
        self.handlers = {
            Action.ANALYZE_PROJECT: self._analyze, Action.EXTRACT_REQUIREMENTS: self._requirements,
            Action.CREATE_EPICS: self._epics, Action.CREATE_TASKS: self._tasks, Action.DETECT_RISKS: self._risks,
            Action.CREATE_DEPENDENCIES: self._dependencies, Action.SET_PRIORITIES: self._priorities,
            Action.PLAN_SPRINTS: self._sprints, Action.ASSIGN_TASKS: self._assign, Action.VALIDATE: self._validate,
            Action.REPAIR_PLAN: self._repair, Action.SEMANTIC_REVIEW: self._semantic_review,
        }

    # ================================================================== main loop
    def run(self, resume: bool = False) -> ProjectState:
        if resume:
            saved = self.store.load_state()
            if saved:
                self.state = ProjectState.model_validate(saved)
                if self.state.document_hash and self.state.document_hash != self.doc.sha256:
                    raise OrchestrationError("Checkpoint belongs to a different document; run without --resume")
                log("ORCHESTRATOR", f"Resumed from checkpoint (revision {self.state.revision})")
            else:
                log("ORCHESTRATOR", "No checkpoint found; starting fresh")
        else:
            self.store.reset()

        for iteration in range(1, self.settings.max_iterations + 1):
            planned = decide_next_action(self.state, self.team, self.settings)
            self._describe_state()
            log("ORCHESTRATOR", f"Iteration {iteration}: {planned.action.value} <- {planned.reason}")
            if planned.action == Action.FINALIZE:
                self._record(iteration, planned, "ok", 0.0, planned.reason)
                return self._finalize()
            self._rounds[planned.key] += 1
            if self._rounds[planned.key] > self.settings.max_action_rounds:
                raise OrchestrationError(f"Action '{planned.key}' selected {self._rounds[planned.key] - 1} times without "
                                         "progress; aborting to avoid an infinite loop")
            agent_name = AGENT_FOR_ACTION[planned.action]
            if agent_name:
                log("ORCHESTRATOR", f"Selecting {self.agents[agent_name].name}")
            t0 = time.time()
            try:
                detail = self.handlers[planned.action](planned)
                status = "ok"
            except AgentFailure as exc:
                status, detail = "failed", str(exc)
                log("ERROR", f"{planned.key}: {exc}", 40)
                self._on_agent_failure(planned)
            self._record(iteration, planned, status, time.time() - t0, detail)
        raise OrchestrationError(f"Maximum iterations ({self.settings.max_iterations}) reached before the plan was complete")

    # ================================================================== infrastructure
    def _describe_state(self) -> None:
        s = self.state
        log("ORCHESTRATOR", f"State: reqs={len(s.requirements)} epics={len(s.epics)} tasks={len(s.tasks)} deps={len(s.dependencies)} "
                            f"prio={len(s.priorities)} sprints={len(s.sprints)} assign={len(s.assignments)} risks={len(s.risks)} rev={s.revision}")

    def _record(self, iteration, planned, status, seconds, detail) -> None:
        self.exec_log.append({
            "iteration": iteration, "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": planned.action.value, "params": {k: v for k, v in planned.params.items() if k != "task_ids"},
            "reason": planned.reason, "agent": AGENT_FOR_ACTION.get(planned.action), "status": status,
            "seconds": round(seconds, 2), "detail": detail, "state_revision": self.state.revision})
        self.store.save_artifact("execution_log", self._exec_payload())

    def _exec_payload(self) -> dict:
        return {"total_seconds": round(time.time() - self.started, 1), "llm_calls": self.llm_calls,
                "model": self.settings.model, "events": self.exec_log}

    def _commit(self, candidate: ProjectState, bump: bool = True) -> None:
        if bump:
            candidate.bump()
        self.state = candidate
        self.store.save_state(candidate.model_dump(mode="json"))

    def _agent_step(self, planned: PlannedAction, agent_key: str, ctx: dict, apply_fn, bump: bool = True) -> str:
        """Run one agent with retries. Output is merged into a *copy* of the state; the copy is committed only
        if the merge succeeds and the consistency check passes (otherwise retry with feedback)."""
        agent = self.agents[agent_key]
        feedback, last = None, None
        for attempt in range(1, self.settings.max_agent_attempts + 1):
            try:
                self.llm_calls += 1
                output = agent.run(ctx, feedback)
                candidate = self.state.model_copy(deep=True)
                summary = apply_fn(candidate, output)
                report = self.deterministic.validate(candidate, stage="partial")
                if not report.passed:
                    raise StateUpdateError("consistency check failed: " + "; ".join(i.message for i in report.errors[:4]))
                self._commit(candidate, bump)
                return summary
            except (AgentOutputError, StateUpdateError) as exc:
                last, feedback = exc, str(exc)[:500]
                log("RETRY", f"{agent.name} attempt {attempt}/{self.settings.max_agent_attempts} rejected: {feedback[:200]}", 30)
            except (OllamaUnavailableError, ModelUnavailableError):
                raise
            except LLMError as exc:  # includes timeouts
                last, feedback = exc, None
                log("RETRY", f"{agent.name} attempt {attempt}/{self.settings.max_agent_attempts} LLM error: {exc}", 30)
        raise AgentFailure(f"{agent.name} failed after {self.settings.max_agent_attempts} attempts: {last}")

    def _python_step(self, apply_fn) -> str:
        candidate = self.state.model_copy(deep=True)
        summary = apply_fn(candidate)
        report = self.deterministic.validate(candidate, stage="partial")
        if not report.passed:
            raise OrchestrationError("Deterministic step produced an inconsistent state: "
                                     + "; ".join(i.message for i in report.errors[:4]))
        self._commit(candidate)
        return summary

    def _mark(self, key: str, status: str) -> None:
        self.state.step_status[key] = status

    def _on_agent_failure(self, planned: PlannedAction) -> None:
        """Fallback policy per action: fatal, deterministic fallback, or skip."""
        a, p = planned.action, planned.params
        if a in FATAL_ACTIONS:
            raise OrchestrationError(f"{a.value} failed and the plan cannot continue without it. See [ERROR]/[RETRY] logs above.")
        log("ORCHESTRATOR", f"Applying deterministic fallback for {a.value}", 30)
        if a == Action.CREATE_TASKS:
            key = "tasks:gaps" if p["mode"] == "gap" else f"tasks:{p['epic_id']}"
            self._python_step(lambda st: st.step_status.__setitem__(key, "skipped") or f"{key} skipped")
        elif a == Action.DETECT_RISKS:
            self._python_step(lambda st: st.step_status.__setitem__("risks", "skipped") or "risks skipped")
        elif a == Action.CREATE_DEPENDENCIES:
            def fb(st):
                added, _ = st.add_dependency_pairs(heuristic_dependency_pairs(st), self.settings)
                st.recompute_priorities()
                st.step_status["dependencies"] = "fallback"
                return f"{added} heuristic dependencies"
            log("STATE UPDATE", self._python_step(fb))
        elif a == Action.SET_PRIORITIES:
            def fb(st):
                n = st.fill_default_priorities()
                return f"{n} default priorities (from task-level priority)"
            log("STATE UPDATE", self._python_step(fb))
        elif a == Action.PLAN_SPRINTS:
            log("STATE UPDATE", self._python_step(lambda st: self._plan_python_only(st)))
        elif a == Action.ASSIGN_TASKS:
            n = p["sprint"]
            log("STATE UPDATE", self._python_step(lambda st: f"{assign_sprint(st, self.team, n)[0]} tasks auto-assigned (sprint {n})"))
        elif a == Action.SEMANTIC_REVIEW:
            self._python_step(lambda st: st.step_status.__setitem__("semantic", "skipped") or "semantic review skipped")

    # ================================================================== handlers: understanding
    def _ctx_chars(self) -> int:
        return self.settings.max_context_chars

    def _analyze(self, planned):
        text = self.doc.get("project overview", "business problem", "project objectives", "scope", "out of scope",
                            "users", "mvp definition", "timeline", max_chars=self._ctx_chars())
        if not text:
            raise OrchestrationError("Document has none of the expected overview sections")

        def apply(st, out):
            msg = st.set_project(out, self.doc, self.settings)
            st.step_status["project"] = "done"
            return msg
        return self._agent_step(planned, "requirements", {"scope": "project", "text": text}, apply)

    def _requirements(self, planned):
        scope = planned.params["scope"]
        text = (self.doc.get("functional requirements", max_chars=self._ctx_chars()) if scope == "functional" else
                self.doc.get("non-functional requirements", "technical constraints", "constraints", max_chars=self._ctx_chars()))
        if not text:
            raise OrchestrationError(f"Document has no section for '{scope}' requirements")

        def apply(st, out):
            msg = st.add_requirements(out.requirements, scope)
            st.step_status[f"requirements:{scope}"] = "done"
            return msg
        return self._agent_step(planned, "requirements", {"scope": scope, "text": text}, apply)

    def _epics(self, planned):
        ctx = {"summary": self.state.project.summary, "max_epics": self.settings.max_epics,
               "requirements": [{"id": r.id, "title": r.title, "kind": r.kind.value} for r in self.state.requirements]}

        def apply(st, out):
            msg = st.add_epics(out.epics, self.settings)
            st.step_status["epics"] = "done"
            return msg
        return self._agent_step(planned, "epics", ctx, apply)

    # ================================================================== handlers: planning
    def _tasks(self, planned):
        p = planned.params
        if p["mode"] == "gap":
            ctx = {"mode": "gap", "missing_types": p["missing_types"],
                   "epics": [{"id": e.id, "name": e.name} for e in self.state.epics]}

            def apply(st, out):
                msg = st.add_tasks(out.tasks, self.settings)
                st.step_status["tasks:gaps"] = "done"
                return msg
            return self._agent_step(planned, "tasks", ctx, apply)

        epic = next(e for e in self.state.epics if e.id == p["epic_id"])
        req_titles = [r.title for r in self.state.requirements if r.id in epic.requirement_ids]
        capacity = sum(m.capacity_hours_per_sprint for m in self.team.members if m.role.value != "project_manager")
        budget = int(capacity * self.state.project.sprint_count * 0.55 / max(1, len(self.state.epics)))
        ctx = {"mode": "epic", "epic": {"name": epic.name, "description": epic.description}, "weeks": self.state.project.duration_weeks,
               "requirement_titles": req_titles, "min_tasks": 3, "max_tasks": self.settings.max_tasks_per_epic, "hour_budget": budget}

        def apply(st, out):
            msg = st.add_tasks(out.tasks, self.settings, epic_id=epic.id)
            st.step_status[f"tasks:{epic.id}"] = "done"
            return msg
        return self._agent_step(planned, "tasks", ctx, apply)

    def _risks(self, planned):
        text = self.doc.get("risks", "dependencies", max_chars=self._ctx_chars()) or "(no risk section in document)"
        ctx = {"summary": self.state.project.summary, "text": text,
               "epics": [{"id": e.id, "name": e.name} for e in self.state.epics]}

        def apply(st, out):
            msg = st.add_risks(out.risks, self.settings)
            st.step_status["risks"] = "done"
            return msg
        return self._agent_step(planned, "risks", ctx, apply)

    def _dependencies(self, planned):
        epic_name = {e.id: e.name[:25] for e in self.state.epics}
        ctx = {"tasks": [{"id": t.id, "type": t.type.value, "title": t.title, "epic": epic_name.get(t.epic_id, "?")}
                         for t in self.state.tasks]}

        def apply(st, out):
            msg = st.add_dependencies(out.dependencies, self.settings)
            st.step_status["dependencies"] = "done"
            return msg
        return self._agent_step(planned, "dependencies", ctx, apply)

    def _priorities(self, planned):
        rounds = self.state.bump_round("priorities")
        ids = planned.params["task_ids"]
        if rounds > 2:
            log("RETRY", f"{len(ids)} tasks still lack priorities after 2 rounds; using task-level defaults", 30)
            return self._python_step(lambda st: f"{st.fill_default_priorities()} default priorities")
        tasks = [self.state.task(i) for i in ids]
        ctx = {"business_priority": self.state.project.business_priority or "MVP usable by the end of the project",
               "tasks": [{"id": t.id, "type": t.type.value, "title": t.title} for t in tasks]}
        return self._agent_step(planned, "priorities", ctx, lambda st, out: st.set_priorities(out.priorities))

    def _sprint_goal_maps(self, state):
        goals = {s.number: s.goal for s in state.sprints}
        names = {s.number: next((m.name for m in state.milestones if m.sprint_id == s.id), "") for s in state.sprints}
        return goals, names

    def _plan_python_only(self, st) -> str:
        goals, names = self._sprint_goal_maps(st)
        msg = st.plan_sprints(goals, names, st.epic_start, self.team, self.settings)
        st.step_status["sprints"] = "python"
        return msg

    def _sprints(self, planned):
        rounds = self.state.bump_round("sprints")
        if rounds > 1:  # re-plan after changes: keep goals/hints, let Python re-schedule
            log("ORCHESTRATOR", "Re-planning sprints deterministically (goals and hints preserved)")
            return self._python_step(self._plan_python_only)
        n = self.state.project.sprint_count
        hours = {}
        for t in self.state.tasks:
            hours[t.epic_id] = hours.get(t.epic_id, 0.0) + t.estimated_hours
        ctx = {"n": n, "weeks": self.state.project.duration_weeks,
               "timeline": self.doc.get("timeline", "milestones", max_chars=1500) or "(none)",
               "epics": [{"id": e.id, "name": e.name, "priority": e.priority.value,
                          "tasks": len(self.state.tasks_of_epic(e.id)), "hours": hours.get(e.id, 0.0)} for e in self.state.epics]}

        def apply(st, out):
            goals = {g.number: g.goal for g in out.sprints if 1 <= g.number <= n and g.goal.strip()}
            names = {g.number: g.milestone for g in out.sprints if 1 <= g.number <= n and g.milestone.strip()}
            hints, epics = {}, st.epic_ids()
            for h in out.epic_start:
                eid = normalize_id(h.epic_id)
                if eid in epics and 1 <= h.sprint <= n:
                    hints[eid] = h.sprint
                else:
                    log("VALIDATION", f"Sprint hint ignored (epic '{eid}', sprint {h.sprint})")
            if len(goals) < max(1, n // 2):
                raise StateUpdateError(f"provide a goal for each sprint number 1..{n}")
            st.epic_start = hints
            msg = st.plan_sprints(goals, names, hints, self.team, self.settings)
            st.step_status["sprints"] = "done"
            return msg
        return self._agent_step(planned, "sprints", ctx, apply)

    def _assign(self, planned):
        n = planned.params["sprint"]
        rounds = self.state.bump_round(f"assign:{n}")
        sprint = self.state.sprint_by_number(n)
        todo = [self.state.task(i) for i in self.state.unassigned_task_ids(sprint)]
        multi = [t for t in todo if len(self.team.by_role(TYPE_TO_ROLE[t.type])) > 1]
        if not multi or rounds > 1:
            note = "single-member roles only" if not multi else "agent already tried"
            log("ORCHESTRATOR", f"Sprint {n}: deterministic assignment ({note}); no LLM call needed")
            return self._python_step(lambda st: f"{assign_sprint(st, self.team, n)[0]} tasks assigned (sprint {n})")
        loads = self.state.member_loads(sprint.id)
        roles = {TYPE_TO_ROLE[t.type] for t in multi}
        ctx = {"sprint": n,
               "members": [{"id": m.id, "name": m.name, "role": m.role.value, "skills": m.skills,
                            "load": loads.get(m.id, 0.0), "capacity": m.capacity_hours_per_sprint}
                           for m in self.team.members if m.role in roles],
               "tasks": [{"id": t.id, "type": t.type.value, "title": t.title, "hours": t.estimated_hours,
                          "eligible": [m.id for m in self.team.by_role(TYPE_TO_ROLE[t.type])]} for t in multi]}

        def apply(st, out):
            suggestions = {normalize_id(a.task_id): normalize_id(a.member_id) for a in out.assignments}
            if not any(tid in suggestions for tid in (t.id for t in multi)):
                raise StateUpdateError("no assignment referenced a listed TASK id")
            made, _ = assign_sprint(st, self.team, n, suggestions)
            return f"{made} tasks assigned (sprint {n})"
        return self._agent_step(planned, "assignments", ctx, apply)

    # ================================================================== handlers: validation & repair
    def _validate(self, planned):
        report = self.deterministic.validate(self.state, stage="final")
        candidate = self.state.model_copy(deep=True)
        candidate.validation = report
        candidate.validated_revision = candidate.revision
        self._commit(candidate, bump=False)
        return f"{'PASS' if report.passed else 'FAIL'}: {report.error_count} errors, {report.warning_count} warnings"

    def _repair(self, planned):
        codes = {i.code for i in self.state.validation.errors}
        log("ORCHESTRATOR", f"Repair round {self.state.step_rounds.get('repair', 0) + 1}: error codes {sorted(codes)}")

        def apply(st):
            fixed = []
            replan = codes & {"DEPENDENCY_ORDER", "TASK_NOT_IN_SPRINT", "TASK_IN_MULTIPLE_SPRINTS", "SPRINT_CAPACITY",
                              "ROLE_CAPACITY", "PLANNED_HOURS_MISMATCH", "SPRINT_COUNT", "INVALID_SPRINT_REF"}
            ids = st.task_ids()
            if codes & {"INVALID_DEPENDENCY_REF", "SELF_DEPENDENCY", "DUPLICATE_DEPENDENCY", "CIRCULAR_DEPENDENCY"}:
                seen, keep = set(), []
                for d in st.dependencies:
                    if d.task_id in ids and d.depends_on in ids and d.task_id != d.depends_on and (d.task_id, d.depends_on) not in seen:
                        keep.append(d)
                        seen.add((d.task_id, d.depends_on))
                st.dependencies = keep
                while (cyc := find_cycle(ids, st.edges())):
                    edge = (cyc[-2], cyc[-1])  # cyc[-1]==cyc[0]; drop the closing edge (blocker cyc[-2] -> task cyc[-1])
                    st.dependencies = [d for d in st.dependencies if (d.depends_on, d.task_id) != edge]
                fixed.append("dependencies cleaned")
                replan = True
            if codes & {"EPIC_WITHOUT_TASKS", "EPIC_TOO_FEW_TASKS"}:
                for e in st.epics:
                    if len(st.tasks_of_epic(e.id)) < self.settings.min_tasks_per_epic:
                        st.step_status.pop(f"tasks:{e.id}", None)   # let the decision loop re-run the Task Planner
                st.step_status.pop("dependencies", None)           # new tasks need dependency analysis too
                fixed.append("under-filled epics queued for the Task Planner")
            if codes & {"MISSING_PRIORITY", "PRIORITY_MISMATCH", "DUPLICATE_PRIORITY", "INVALID_REFERENCE"}:
                st.priorities = [p for p in st.priorities if p.task_id in ids]
                st.fill_default_priorities()
                fixed.append("priorities rebuilt")
            if replan:
                self._plan_python_only(st)
                for s in st.sprints:
                    assign_sprint(st, self.team, s.number)
                fixed.append("sprints re-scheduled and tasks re-assigned")
            elif codes & {"ROLE_MISMATCH", "ASSIGNMENT_SPRINT_MISMATCH", "INVALID_ASSIGNMENT_TASK", "INVALID_ASSIGNMENT_MEMBER",
                          "DUPLICATE_ASSIGNMENT", "TASK_NOT_ASSIGNED"}:
                sprint_of = {t: s.id for s in st.sprints for t in s.task_ids}
                seen, keep = set(), []
                for a in st.assignments:
                    m, t = self.team.get(a.member_id), st.task(a.task_id)
                    if m and t and m.role == TYPE_TO_ROLE[t.type] and sprint_of.get(t.id) == a.sprint_id and t.id not in seen:
                        keep.append(a)
                        seen.add(t.id)
                st.assignments = keep
                for s in st.sprints:
                    assign_sprint(st, self.team, s.number)
                fixed.append("assignments rebuilt")
            st.bump_round("repair")
            return "; ".join(fixed) or "no automatic repair available for these errors"
        return self._python_step(apply)

    def _semantic_review(self, planned):
        def apply(st, out):
            verdict = "pass" if out.verdict.lower().startswith("pass") else "concerns"
            st.validation.semantic_verdict = verdict
            st.validation.semantic_notes = out.notes[:5]
            st.step_status["semantic"] = "done"
            return f"semantic verdict: {verdict} ({len(out.notes)} notes)"
        ctx = SemanticValidator.build_context(self.state)
        return self._agent_step(planned, "validator", ctx, apply, bump=False)

    # ================================================================== finalisation
    def _finalize(self) -> ProjectState:
        st = self.state
        report = st.validation
        complete = bool(report and report.passed and st.validated_revision == st.revision)
        if not complete:
            log("VALIDATION", "Final validation FAILED: project NOT marked complete", 40)
        st.project.status = "complete" if complete else "failed_validation"
        plan = st.plan_dict(self.team)
        save = self.store.save_artifact
        save("requirements", plan["requirements"])
        save("epics", plan["epics"])
        save("tasks", plan["tasks"])
        save("dependencies", plan["dependencies"])
        save("priorities", plan["priorities"])
        save("sprints", plan["sprints"])
        save("assignments", plan["assignments"])
        save("risks", plan["risks"])
        save("validation", plan["validation"])
        save("final_project_plan" if complete else "draft_project_plan", plan)
        save("execution_log", self._exec_payload())
        self.store.save_state(st.model_dump(mode="json"))
        log("ORCHESTRATOR", "Plan COMPLETE and validated" if complete else "Plan INCOMPLETE (see validation.json)")
        return st
