"""LLM semantic review. Advisory: it can add notes/warnings but can never override Python validation."""
from __future__ import annotations


class SemanticValidator:
    def __init__(self, agent):
        self.agent = agent

    @staticmethod
    def build_context(state) -> dict:
        by_id = {t.id: t for t in state.tasks}
        lines = []
        for s in state.sprints:
            titles = [f"{by_id[i].title[:45]}" for i in s.task_ids[:14] if i in by_id]
            extra = f" (+{len(s.task_ids) - 14} more)" if len(s.task_ids) > 14 else ""
            lines.append(f"Sprint {s.number} goal: {s.goal}\n  tasks: " + "; ".join(titles) + extra)
        p = state.project
        return {"summary": p.summary, "business_priority": p.business_priority or "MVP usable at the end", "digest": "\n".join(lines)}

    def review(self, state, feedback=None):
        out = self.agent.run(self.build_context(state), feedback)
        verdict = "pass" if out.verdict.lower().startswith("pass") else "concerns"
        return verdict, out.notes[:5]
