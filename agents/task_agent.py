from __future__ import annotations

from agents.base import JSON_ONLY, BaseAgent, example
from models.base import Hours, PriorityLike, ProposalModel, Text, TaskTypeLike

TYPES = "backend, frontend, database, design, qa, devops, documentation"


class TaskProposal(ProposalModel):
    title: Text
    type: TaskTypeLike
    description: Text = ""
    estimated_hours: Hours
    priority: PriorityLike = "medium"
    epic_id: Text = ""   # only used in gap-fill mode; Python validates it


class TasksOutput(ProposalModel):
    tasks: list[TaskProposal]


class TaskAgent(BaseAgent):
    name = "Task Planner"
    role = "Task Planner"
    goal = "Break an epic into concrete, estimable engineering tasks."
    backstory = "A tech lead who writes small, verifiable tasks with realistic hour estimates."
    list_key = "tasks"

    def output_model(self, ctx):
        return TasksOutput

    def build_prompt(self, ctx):
        shape = example({"tasks": [{"title": "Implement ...", "type": "backend", "description": "max 15 words",
                                     "estimated_hours": 6, "priority": "high"}]})
        if ctx["mode"] == "gap":
            epics = "\n".join(f"{e['id']} {e['name']}" for e in ctx["epics"])
            return (f"The plan has NO tasks of type: {', '.join(ctx['missing_types'])}.\nEPICS:\n{epics}\n\n"
                    f"Add 2 to 4 tasks for each missing type. Each task needs an epic_id chosen ONLY from the list above. "
                    f"type is one of: {TYPES}. Hours between 2 and 16.\n"
                    "Return exactly this shape: " + example({"tasks": [
                        {"epic_id": "EPIC-001", "title": "...", "type": ctx["missing_types"][0], "description": "...",
                         "estimated_hours": 6, "priority": "high"}]}) + "\n" + JSON_ONLY)
        e = ctx["epic"]
        reqs = "\n".join(f"- {t}" for t in ctx["requirement_titles"]) or "- (none linked)"
        return (f"Plan implementation tasks for ONE epic of a {ctx['weeks']}-week MVP.\n"
                f"EPIC: {e['name']} - {e['description']}\nREQUIREMENTS COVERED:\n{reqs}\n\n"
                f"Rules: {ctx['min_tasks']} to {ctx['max_tasks']} tasks; type is one of: {TYPES}; each task 2-16 hours "
                f"(this epic should total about {ctx['hour_budget']} hours); title starts with a verb; "
                "cover backend, frontend and testing/design work only where this epic needs it; no ids in the output.\n"
                "Return exactly this shape: " + shape + "\n" + JSON_ONLY)
