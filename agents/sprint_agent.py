from __future__ import annotations

from agents.base import JSON_ONLY, BaseAgent, example
from models.base import IntLike, ProposalModel, Text


class SprintGoal(ProposalModel):
    number: IntLike
    goal: Text
    milestone: Text = ""


class EpicStart(ProposalModel):
    epic_id: Text
    sprint: IntLike


class SprintPlanOutput(ProposalModel):
    sprints: list[SprintGoal]
    epic_start: list[EpicStart] = []


class SprintAgent(BaseAgent):
    name = "Sprint Planner"
    role = "Sprint Planner"
    goal = "Define sprint goals, milestones and when each epic should start."
    backstory = "A scrum master who sequences foundation first, features next, hardening and release last."
    list_key = "sprints"

    def output_model(self, ctx):
        return SprintPlanOutput

    def build_prompt(self, ctx):
        epics = "\n".join(f"{e['id']} {e['name']} [{e['priority']}] {e['tasks']} tasks, {e['hours']:g}h" for e in ctx["epics"])
        return (f"Plan {ctx['n']} one-week sprints for a {ctx['weeks']}-week MVP.\nTIMELINE FROM THE DOCUMENT:\n{ctx['timeline']}\n\n"
                f"EPICS:\n{epics}\n\n"
                f"Give every sprint number 1..{ctx['n']} a goal (max 15 words) and a milestone name. Also say in which sprint "
                "each epic should START (foundation first; testing and release in the last sprints). Follow the TIMELINE text literally: "
                "an epic must start no later than the sprint where the timeline says its work happens. Use ONLY the epic ids above.\n"
                "Return exactly this shape: " + example({
                    "sprints": [{"number": 1, "goal": "...", "milestone": "..."}],
                    "epic_start": [{"epic_id": "EPIC-001", "sprint": 1}]}) + "\n" + JSON_ONLY)
