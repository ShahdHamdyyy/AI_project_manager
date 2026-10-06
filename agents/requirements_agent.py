from __future__ import annotations

from agents.base import JSON_ONLY, BaseAgent, example
from models.base import IntLike, PriorityLike, ProposalModel, StrList, Text


class ProjectAnalysis(ProposalModel):
    name: Text = ""
    summary: Text = ""
    objective: Text = ""
    duration_weeks: IntLike = 0
    actors: StrList = []
    mvp_scope: StrList = []
    out_of_scope: StrList = []
    assumptions: StrList = []
    business_priority: Text = ""


class RequirementProposal(ProposalModel):
    title: Text
    description: Text = ""
    priority: PriorityLike = "medium"
    kind: Text = ""


class RequirementsOutput(ProposalModel):
    requirements: list[RequirementProposal]


class RequirementsAgent(BaseAgent):
    name = "Requirements Analyst"
    role = "Requirements Analyst"
    goal = "Extract project facts and requirements from documentation, accurately and concisely."
    backstory = "A senior business analyst who never invents requirements that are not in the document."
    list_key = "requirements"

    def output_model(self, ctx):
        return ProjectAnalysis if ctx["scope"] == "project" else RequirementsOutput

    def list_key_for(self, ctx):
        return None if ctx["scope"] == "project" else "requirements"

    def build_prompt(self, ctx):
        scope, text = ctx["scope"], ctx["text"]
        if scope == "project":
            return (f"Summarise this project document extract.\n\nDOCUMENT:\n{text}\n\n"
                    "Rules: actors are user roles only and must include EVERY persona or role named in the document; "
                    "mvp_scope must list EVERY in-scope item of the document (up to 12 items, under 15 words each); "
                    "out_of_scope and other lists have at most 10 items of under 12 words; "
                    "assumptions may be implied by the document; duration_weeks is an integer.\n"
                    f"Return exactly this shape: " + example({
                        "name": "...", "summary": "1-2 sentences", "objective": "...", "duration_weeks": 4,
                        "actors": ["..."], "mvp_scope": ["..."], "out_of_scope": ["..."],
                        "assumptions": ["..."], "business_priority": "..."}) + "\n" + JSON_ONLY)
        if scope == "functional":
            return (f"Extract EVERY functional requirement below as its own item.\n\nTEXT:\n{text}\n\n"
                    "Rules: one requirement per numbered item (FR-xx), same order, none skipped or merged; title max 8 words; "
                    "description max 45 words and it MUST keep every number, percentage, amount, currency, time limit, role and "
                    "named behavior of the item (never replace them by a generic sentence); "
                    "priority = critical|high|medium|low. Do not invent requirements.\n"
                    "Return exactly this shape: " + example({"requirements": [
                        {"title": "...", "description": "...", "priority": "high"}]}) + "\n" + JSON_ONLY)
        return (f"Extract EVERY non-functional requirement and every constraint below as its own item.\n\nTEXT:\n{text}\n\n"
                "Rules: one item per bullet; kind = non_functional or constraint; title max 8 words; description max 45 words and "
                "it MUST keep every number and limit exactly (latency, percentile, connections, uptime, coverage, timeline, hours); "
                "how the application is started or run is a non_functional requirement.\n"
                "Return exactly this shape: " + example({"requirements": [
                    {"kind": "non_functional", "title": "...", "description": "...", "priority": "high"}]}) + "\n" + JSON_ONLY)
