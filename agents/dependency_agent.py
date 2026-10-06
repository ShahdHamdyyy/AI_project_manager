from __future__ import annotations

from agents.base import JSON_ONLY, BaseAgent, example
from models.base import ProposalModel, Text


class DependencyProposal(ProposalModel):
    task_id: Text
    depends_on: Text
    reason: Text = ""


class DependenciesOutput(ProposalModel):
    dependencies: list[DependencyProposal]


class DependencyAgent(BaseAgent):
    name = "Dependency Planner"
    role = "Dependency Planner"
    goal = "Identify real technical blocking relations between TASKS."
    backstory = "A delivery manager who only records dependencies that truly block work and never links epics."
    list_key = "dependencies"

    def output_model(self, ctx):
        return DependenciesOutput

    def build_prompt(self, ctx):
        lines = "\n".join(f"{t['id']} [{t['type']}] {t['title'][:70]} ({t['epic']})" for t in ctx["tasks"])
        return (f"Define blocking dependencies between TASKS.\nTASKS (id [type] title (epic)):\n{lines}\n\n"
                "Meaning: task_id cannot start until depends_on is finished. Use ONLY the TASK-xxx ids listed above "
                "(never EPIC ids). At most 2 dependencies per task; only real blockers such as: design before frontend, "
                "database schema before backend, backend API before frontend integration, implementation before its QA, "
                "QA before deployment. No cycles.\n"
                "Return exactly this shape: " + example({"dependencies": [
                    {"task_id": "TASK-005", "depends_on": "TASK-002", "reason": "max 10 words"}]}) + "\n" + JSON_ONLY)
