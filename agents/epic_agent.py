from __future__ import annotations

from agents.base import JSON_ONLY, BaseAgent, example
from models.base import PriorityLike, ProposalModel, StrList, Text


class EpicProposal(ProposalModel):
    name: Text
    description: Text = ""
    priority: PriorityLike = "medium"
    requirement_ids: StrList = []


class EpicsOutput(ProposalModel):
    epics: list[EpicProposal]


class EpicAgent(BaseAgent):
    name = "Epic Planner"
    role = "Epic Planner"
    goal = "Group requirements into a small set of coherent delivery epics."
    backstory = "An agile coach who structures MVP scope into 5-7 epics covering foundation, features, quality and release."
    list_key = "epics"

    def output_model(self, ctx):
        return EpicsOutput

    def build_prompt(self, ctx):
        reqs = "\n".join(f"{r['id']} {r['title']} ({r['kind']}): {r['description']}" for r in ctx["requirements"])
        return (f"Group the requirements of this project into epics.\nPROJECT: {ctx['summary']}\n\nREQUIREMENTS:\n{reqs}\n\n"
                f"Rules: 5 to {ctx['max_epics']} epics; EVERY requirement id listed above must appear in exactly one epic; "
                "group by business area (not by technical layer) and keep related rules together, for example all refund rules "
                "in one epic; non-functional requirements may share one quality/platform epic; "
                "add epics for foundation (setup, database, authentication), quality assurance and release/deployment "
                "when the requirements call for them; requirement_ids must come ONLY from the list above; "
                "name max 6 words; description max 20 words.\n"
                "Return exactly this shape: " + example({"epics": [
                    {"name": "...", "description": "...", "priority": "high", "requirement_ids": ["REQ-001"]}]}) + "\n" + JSON_ONLY)
