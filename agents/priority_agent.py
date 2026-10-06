from __future__ import annotations

from agents.base import JSON_ONLY, BaseAgent, example
from models.base import PriorityLike, ProposalModel, Text


class PriorityProposal(ProposalModel):
    task_id: Text
    priority: PriorityLike


class PrioritiesOutput(ProposalModel):
    priorities: list[PriorityProposal]


class PriorityAgent(BaseAgent):
    name = "Priority Planner"
    role = "Priority Planner"
    goal = "Rank tasks by business value and delivery risk for an MVP."
    backstory = "A product owner who protects the MVP scope and the business deadline."
    list_key = "priorities"

    def output_model(self, ctx):
        return PrioritiesOutput

    def build_prompt(self, ctx):
        lines = "\n".join(f"{t['id']} [{t['type']}] {t['title'][:70]}" for t in ctx["tasks"])
        return (f"Set a priority for EVERY task listed.\nBUSINESS PRIORITY: {ctx['business_priority']}\n"
                "Levels: critical = MVP cannot work without it or it blocks many tasks; high = core MVP feature; "
                "medium = needed but not blocking; low = polish.\n\nTASKS:\n" + lines + "\n\n"
                "Use ONLY the task ids listed above. Return exactly this shape: "
                + example({"priorities": [{"task_id": "TASK-001", "priority": "high"}]}) + "\n" + JSON_ONLY)
