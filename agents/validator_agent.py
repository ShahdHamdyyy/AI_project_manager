from __future__ import annotations

from agents.base import JSON_ONLY, BaseAgent, example
from models.base import ProposalModel, StrList, Text


class SemanticReview(ProposalModel):
    verdict: Text = "pass"
    notes: StrList = []


class ValidatorAgent(BaseAgent):
    """Semantic reviewer. Advisory only: deterministic Python validation is authoritative."""
    name = "Project Validator"
    role = "Project Validator"
    goal = "Spot semantic problems in a project plan that structural checks cannot see."
    backstory = "A PMO reviewer who flags mismatched sprint goals, missing work and unrealistic ordering."

    def output_model(self, ctx):
        return SemanticReview

    def build_prompt(self, ctx):
        return (f"Review this project plan. Structure and references were ALREADY verified by code; look only for "
                f"semantic problems (sprint goal not matching its tasks, missing important work, unrealistic ordering). "
                f"Compare each sprint ONLY with its own goal. Every note must name the sprint number or task title it is about; "
                f"do not report a problem you cannot point to.\n\n"
                f"PROJECT: {ctx['summary']}\nBUSINESS PRIORITY: {ctx['business_priority']}\n\nPLAN:\n{ctx['digest']}\n\n"
                "Return exactly this shape: " + example({"verdict": "pass or concerns", "notes": ["max 5 short notes"]})
                + "\n" + JSON_ONLY)
