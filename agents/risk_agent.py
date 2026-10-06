from __future__ import annotations

from agents.base import JSON_ONLY, BaseAgent, example
from models.base import LevelLike, ProposalModel, StrList, Text


class RiskProposal(ProposalModel):
    title: Text
    description: Text = ""
    likelihood: LevelLike = "medium"
    impact: LevelLike = "medium"
    mitigation: Text = ""
    epic_ids: StrList = []


class RisksOutput(ProposalModel):
    risks: list[RiskProposal]


class RiskAgent(BaseAgent):
    name = "Risk Analyst"
    role = "Risk Analyst"
    goal = "Identify delivery risks and practical mitigations."
    backstory = "A risk manager focused on schedule, integration, quality and scope risks of short MVP projects."
    list_key = "risks"

    def output_model(self, ctx):
        return RisksOutput

    def build_prompt(self, ctx):
        epics = "\n".join(f"{e['id']} {e['name']}" for e in ctx["epics"])
        return (f"Identify the main delivery risks of this project.\nPROJECT: {ctx['summary']}\n\n"
                f"RISK AND DEPENDENCY NOTES FROM THE DOCUMENT:\n{ctx['text']}\n\nEPICS:\n{epics}\n\n"
                "Rules: 5 to 8 risks; likelihood and impact are low|medium|high; mitigation max 20 words; "
                "epic_ids ONLY from the list above.\n"
                "Return exactly this shape: " + example({"risks": [
                    {"title": "...", "description": "...", "likelihood": "medium", "impact": "high",
                     "mitigation": "...", "epic_ids": ["EPIC-001"]}]}) + "\n" + JSON_ONLY)
