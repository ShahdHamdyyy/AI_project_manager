from __future__ import annotations

from agents.base import JSON_ONLY, BaseAgent, example
from models.base import ProposalModel, Text


class AssignmentProposal(ProposalModel):
    task_id: Text
    member_id: Text


class AssignmentsOutput(ProposalModel):
    assignments: list[AssignmentProposal]


class AssignmentAgent(BaseAgent):
    name = "Team Assignment Planner"
    role = "Team Assignment Planner"
    goal = "Match tasks to the best-suited team member while balancing workload."
    backstory = "A resource manager who respects roles, skills and weekly capacity and never invents people."
    list_key = "assignments"

    def output_model(self, ctx):
        return AssignmentsOutput

    def build_prompt(self, ctx):
        members = "\n".join(f"{m['id']} {m['name']} [{m['role']}] skills: {', '.join(m['skills'])} "
                            f"(already {m['load']:g}h of {m['capacity']:g}h)" for m in ctx["members"])
        tasks = "\n".join(f"{t['id']} [{t['type']}] {t['title'][:70]} {t['hours']:g}h -> eligible: {', '.join(t['eligible'])}"
                          for t in ctx["tasks"])
        return (f"Assign the tasks of sprint {ctx['sprint']} to team members.\nMEMBERS:\n{members}\n\nTASKS:\n{tasks}\n\n"
                "Rules: choose member_id ONLY from the task's eligible list; use skills to pick the best fit; "
                "spread hours fairly between members of the same role.\n"
                "Return exactly this shape: " + example({"assignments": [{"task_id": "TASK-003", "member_id": "TEAM-002"}]})
                + "\n" + JSON_ONLY)
