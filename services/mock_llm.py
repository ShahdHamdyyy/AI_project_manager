"""Offline stand-in for the LLM (used by `main.py --mock` and the tests).

It reads the same prompts the real agents send and answers with plausible JSON. It deliberately makes
typical small-model mistakes (an EPIC id used as a TASK id, a circular dependency, a missing priority,
an invalid team member id, no design tasks) so the orchestrator's guards are exercised.
"""
from __future__ import annotations

import json
import re

EPICS = [
    ("Foundation and Infrastructure", "Repository, database schema, scaffolding, dev environment", "critical", ["database", "postgres", "rest api", "docker"]),
    ("Authentication and Roles", "Secure login, sessions and role-based access", "critical", ["authentication", "roles", "authorization", "secure"]),
    ("Customer Management", "Customer records and profiles", "high", ["customer"]),
    ("Ticket Management", "Ticket lifecycle, assignment, status, priority and comments", "critical", ["ticket", "comments", "priority", "assign"]),
    ("Search, Filtering and Dashboard", "Finding tickets, dashboard metrics and CSV reporting", "high", ["search", "filter", "dashboard", "reporting"]),
    ("Agent Management", "Support agent accounts", "medium", ["agent management"]),
    ("Quality and Release", "Testing, logging, bug fixing, documentation and deployment", "high", ["tests", "logging", "error", "responsive", "constraint"]),
]

TASKS = {
    "Foundation": [("Design PostgreSQL schema and migrations", "database", 8, "critical"), ("Scaffold REST API project", "backend", 6, "critical"),
                   ("Scaffold React app and routing", "frontend", 6, "high"), ("Configure Docker Compose dev environment", "devops", 8, "high")],
    "Authentication": [("Implement JWT login and password hashing", "backend", 10, "critical"), ("Implement role-based authorization", "backend", 8, "high"),
                       ("Build login screen and session handling", "frontend", 8, "high"), ("Test authentication flows", "qa", 6, "high")],
    "Customer": [("Implement customer CRUD endpoints", "backend", 10, "high"), ("Build customer list and profile pages", "frontend", 12, "high"),
                 ("Test customer management", "qa", 4, "medium")],
    "Ticket": [("Implement ticket CRUD endpoints", "backend", 12, "critical"), ("Implement ticket assignment and status workflow", "backend", 10, "critical"),
               ("Implement ticket comments API", "backend", 8, "high"), ("Build ticket create and detail screens", "frontend", 14, "critical"),
               ("Build status, priority and comments UI", "frontend", 10, "high"), ("Test ticket workflow end to end", "qa", 8, "high")],
    "Search": [("Implement ticket search and filter endpoints", "backend", 10, "high"), ("Implement dashboard metrics endpoint", "backend", 8, "medium"),
               ("Build filter bar and search box", "frontend", 8, "high"), ("Build dashboard charts", "frontend", 12, "medium"),
               ("Implement CSV export", "backend", 6, "low")],
    "Agent": [("Implement agent account endpoints", "backend", 8, "medium"), ("Build agent management screen", "frontend", 8, "medium")],
    "Quality": [("Write regression test suite", "qa", 16, "high"), ("Run end-to-end smoke tests", "qa", 12, "high"),
                ("Prepare production Docker deployment", "devops", 12, "critical"), ("Set up structured logging", "devops", 8, "medium"),
                ("Write user guide", "documentation", 6, "low"), ("Fix frontend bugs from QA", "frontend", 12, "high"), ("Fix backend bugs from QA", "backend", 12, "high")],
}


def _j(obj) -> str:
    return json.dumps(obj)


class MockRunner:
    def __init__(self):
        self.calls = 0
        self._failed_once = set()

    def run(self, agent, prompt: str) -> str:
        self.calls += 1
        p = prompt
        if "Summarise this project document extract" in p:
            return _j({"name": "Customer Support & Service Management Platform",
                       "summary": "Web MVP for support agents to manage customers and tickets within four weeks.",
                       "objective": "Central place for customers, tickets and basic metrics.", "duration_weeks": 4,
                       "actors": ["Support Agent", "Support Lead", "Administrator"],
                       "mvp_scope": ["Customers", "Tickets", "Dashboard"], "out_of_scope": ["AI features", "Mobile app", "CRM integrations"],
                       "assumptions": ["Team works about 30 productive hours per week"],
                       "business_priority": "MVP usable by support agents by the end of week 4"})
        if "Extract EVERY functional requirement" in p:
            names = ["Authentication", "User roles", "Customer management", "Customer profile", "Ticket creation", "Ticket assignment",
                     "Ticket status", "Ticket priority", "Comments", "Search", "Filtering", "Dashboard", "Basic reporting", "Agent management"]
            return _j({"requirements": [{"title": n, "description": f"{n} for support agents", "priority": "high"} for n in names]})
        if "Extract EVERY non-functional requirement" in p:
            nfr = ["Secure authentication", "Basic authorization", "REST API", "Responsive web interface", "PostgreSQL database",
                   "Logging", "Basic error handling", "Automated tests", "Dockerized deployment"]
            con = ["Fixed 4 week duration", "MVP only", "Limited team capacity", "No advanced AI features", "No mobile application",
                   "No complex analytics", "No third-party CRM integrations"]
            return _j({"requirements": [{"kind": "non_functional", "title": n, "priority": "high"} for n in nfr]
                       + [{"kind": "constraint", "title": c, "priority": "medium"} for c in con]})
        if "Group the requirements of this project into epics" in p:
            reqs = re.findall(r"^(REQ-\d+) (.+?) \(", p, re.M)
            out = []
            for name, desc, prio, kws in EPICS:
                ids = [r for r, t in reqs if any(k in t.lower() for k in kws)]
                out.append({"name": name, "description": desc, "priority": prio, "requirement_ids": ids + (["REQ-999"] if name.startswith("Found") else [])})
            return _j({"epics": out})
        if "Plan implementation tasks for ONE epic" in p:
            name = re.search(r"EPIC: (.+?) - ", p).group(1)
            key = next(k for k in TASKS if name.startswith(k))
            # first attempt for one epic returns prose-wrapped JSON with a trailing comma (typical 3B behaviour)
            body = [{"title": t, "type": ty, "description": "as described", "estimated_hours": h, "priority": pr} for t, ty, h, pr in TASKS[key]]
            if key == "Customer" and "customer" not in self._failed_once:
                self._failed_once.add("customer")
                return "Sure! Here you go:\n```json\n" + _j({"tasks": body}).replace("}]}", "},]}") + "\n```"
            return _j({"tasks": body})
        if "The plan has NO tasks of type" in p:
            eid = re.findall(r"^(EPIC-\d+) (.+)$", p, re.M)
            frontend_epics = [e for e, n in eid if "Auth" in n or "Ticket" in n or "Dash" in n]
            types = re.search(r"type: (.+?)\.\n", p).group(1).split(", ")
            tasks = []
            for ty in types:
                for i, e in enumerate(frontend_epics[:3]):
                    tasks.append({"epic_id": e, "title": f"Create {ty} deliverable {i + 1}", "type": ty, "estimated_hours": 6, "priority": "high"})
            return _j({"tasks": tasks})
        if "Define blocking dependencies between TASKS" in p:
            rows = re.findall(r"^(TASK-\d+) \[(\w+)\] .* \((.+)\)$", p, re.M)
            order = ["design", "database", "backend", "frontend", "qa"]
            deps, byepic = [], {}
            for tid, ty, ep in rows:
                byepic.setdefault(ep, []).append((tid, ty))
            for ep, items in byepic.items():
                for tid, ty in items:
                    if ty in order and order.index(ty) > 0:
                        prev = [x for x, t in items if t in order and order.index(t) < order.index(ty)]
                        if prev:
                            deps.append({"task_id": tid, "depends_on": prev[-1], "reason": f"{ty} follows earlier stage"})
            if len(rows) > 3:
                deps.append({"task_id": "EPIC-002", "depends_on": "EPIC-001", "reason": "epics (wrong entity type)"})
                a = deps[0]
                deps.append({"task_id": a["depends_on"], "depends_on": a["task_id"], "reason": "accidental cycle"})
            return _j({"dependencies": deps})
        if "Set a priority for EVERY task" in p:
            rows = re.findall(r"^(TASK-\d+) \[(\w+)\]", p, re.M)
            if len(rows) > 1:
                rows = rows[:-1]  # forget one task -> orchestrator must ask again
            m = {"database": "critical", "backend": "high", "frontend": "high", "qa": "medium", "devops": "medium", "design": "high", "documentation": "low"}
            return _j({"priorities": [{"task_id": t, "priority": m[ty]} for t, ty in rows]})
        if re.search(r"Plan \d+ one-week sprints", p):
            n = int(re.search(r"Plan (\d+) one-week", p).group(1))
            goals = ["Foundation, database and authentication", "Customer and ticket core", "Search, dashboard and integration", "QA, bug fixing and MVP release"]
            eps = re.findall(r"^(EPIC-\d+) (.+?) \[", p, re.M)
            start = {"Foundation": 1, "Authentication": 1, "Customer": 2, "Ticket": 2, "Search": 3, "Agent": 3, "Quality": 3}
            return _j({"sprints": [{"number": i + 1, "goal": goals[i % 4], "milestone": f"M{i + 1}"} for i in range(n)],
                       "epic_start": [{"epic_id": e, "sprint": next(v for k, v in start.items() if name.startswith(k))} for e, name in eps]})
        if "Assign the tasks of sprint" in p:
            rows = re.findall(r"^(TASK-\d+) \[\w+\] .* -> eligible: (.+)$", p, re.M)
            out = [{"task_id": t, "member_id": el.split(", ")[0]} for t, el in rows]  # everything to the first member: unbalanced
            if out:
                out[-1]["member_id"] = "TEAM-099"  # invented person
            return _j({"assignments": out})
        if "Identify the main delivery risks" in p:
            eps = re.findall(r"^(EPIC-\d+) ", p, re.M)
            titles = ["Authentication delays", "Database schema changes", "Frontend/backend integration delays", "QA bottleneck", "Deployment issues", "Scope creep"]
            return _j({"risks": [{"title": t, "description": t, "likelihood": "medium", "impact": "high", "mitigation": "Plan early and review weekly",
                                  "epic_ids": eps[i:i + 1]} for i, t in enumerate(titles)]})
        if "Review this project plan" in p:
            return _j({"verdict": "concerns", "notes": ["Sprint 4 carries most QA work; watch the QA bottleneck."]})
        raise RuntimeError("MockRunner: unrecognised prompt")
