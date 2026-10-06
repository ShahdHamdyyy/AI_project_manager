"""Run with:  python3 -m unittest discover -s tests -v   (no Ollama needed; uses the mock LLM)."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import build_agents  # noqa: E402
from config.settings import load_settings, load_team  # noqa: E402
from models.enums import Priority  # noqa: E402
from models.sprint import Assignment  # noqa: E402
from models.task import Dependency, PriorityEntry  # noqa: E402
from orchestrator.orchestrator import Orchestrator  # noqa: E402
from services.document_loader import load_document  # noqa: E402
from services.errors import AgentOutputError  # noqa: E402
from services.json_tools import extract_json  # noqa: E402
from services.mock_llm import MockRunner  # noqa: E402
from services.storage import JsonFileStore  # noqa: E402
from validators.deterministic_validator import DeterministicValidator  # noqa: E402

DOC = ROOT / "data" / "test_project_documentation.md"


def run_pipeline(runner, out: Path):
    settings, team = load_settings(), load_team()
    settings.output_dir = str(out)
    settings.max_agent_attempts = 2
    orch = Orchestrator(settings, team, build_agents(runner), JsonFileStore(out), load_document(DOC))
    state = orch.run()
    return state, orch, settings, team


class Wrapper:
    """Wraps the mock and lets a test tamper with responses."""
    def __init__(self, fn):
        self.inner, self.fn = MockRunner(), fn

    def run(self, agent, prompt):
        return self.fn(self.inner, agent, prompt)


class PipelineTests(unittest.TestCase):
    def test_full_mock_run_passes_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            state, orch, settings, team = run_pipeline(MockRunner(), Path(d))
            self.assertEqual(state.project.status, "complete")
            self.assertTrue(state.validation.passed)
            for name in ["requirements", "epics", "tasks", "dependencies", "priorities", "sprints", "assignments",
                         "risks", "validation", "final_project_plan", "execution_log"]:
                self.assertTrue((Path(d) / f"{name}.json").exists(), name)
            # every task in exactly one sprint, every task assigned, dependencies are TASK ids
            placed = [t for s in state.sprints for t in s.task_ids]
            self.assertEqual(sorted(placed), sorted(t.id for t in state.tasks))
            self.assertTrue(all(d.task_id.startswith("TASK-") and d.depends_on.startswith("TASK-") for d in state.dependencies))
            self.assertEqual(len(state.assignments), len(state.tasks))
            self.assertEqual(len(state.sprints), 4)

    def test_python_owns_ids(self):
        def tamper(inner, agent, prompt):
            raw = inner.run(agent, prompt)
            data = extract_json(raw)
            for key in ("epics", "tasks"):
                for i, item in enumerate(data.get(key, [])):
                    item["id"] = "EPIC-042" if key == "epics" else "TASK-999"
            return json.dumps(data)
        with tempfile.TemporaryDirectory() as d:
            state, *_ = run_pipeline(Wrapper(tamper), Path(d))
            self.assertEqual([e.id for e in state.epics], [f"EPIC-{i:03d}" for i in range(1, len(state.epics) + 1)])
            self.assertEqual([t.id for t in state.tasks][:3], ["TASK-001", "TASK-002", "TASK-003"])

    def test_epic_without_tasks_fails_safely(self):
        def tamper(inner, agent, prompt):
            if "Plan implementation tasks for ONE epic" in prompt and "Ticket Management" in prompt:
                return "I cannot help with that."   # never valid JSON
            return inner.run(agent, prompt)
        with tempfile.TemporaryDirectory() as d:
            state, *_ = run_pipeline(Wrapper(tamper), Path(d))
            self.assertEqual(state.project.status, "failed_validation")
            self.assertTrue({"EPIC_WITHOUT_TASKS", "EPIC_TOO_FEW_TASKS"} & {i.code for i in state.validation.errors})
            self.assertFalse((Path(d) / "final_project_plan.json").exists())
            self.assertTrue((Path(d) / "draft_project_plan.json").exists())

    def test_dependency_agent_failure_uses_fallback(self):
        def tamper(inner, agent, prompt):
            if "Define blocking dependencies" in prompt:
                return "{not json"
            return inner.run(agent, prompt)
        with tempfile.TemporaryDirectory() as d:
            state, *_ = run_pipeline(Wrapper(tamper), Path(d))
            self.assertEqual(state.step_status["dependencies"], "fallback")
            self.assertEqual(state.project.status, "complete")


class ValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.state, cls.orch, cls.settings, cls.team = run_pipeline(MockRunner(), Path(cls.tmp.name))
        cls.v = DeterministicValidator(cls.team, cls.settings)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def codes(self, mutate):
        st = self.state.model_copy(deep=True)
        mutate(st)
        return {i.code for i in self.v.validate(st).errors}

    def test_baseline_is_valid(self):
        self.assertTrue(self.v.validate(self.state).passed)

    def test_duplicate_id(self):
        self.assertIn("DUPLICATE_ID", self.codes(lambda s: s.tasks.append(s.tasks[0].model_copy(deep=True))))

    def test_epic_id_used_as_task_id_everywhere(self):
        def m(s):
            s.dependencies.append(Dependency(task_id="EPIC-002", depends_on="EPIC-001"))
            s.priorities.append(PriorityEntry(task_id="EPIC-001", priority=Priority.HIGH))
            s.sprints[0].task_ids.append("EPIC-001")
            s.assignments.append(Assignment(task_id="EPIC-001", member_id="TEAM-002", sprint_id="SPRINT-001"))
        c = self.codes(m)
        self.assertTrue({"INVALID_DEPENDENCY_REF", "INVALID_REFERENCE", "INVALID_SPRINT_REF", "INVALID_ASSIGNMENT_TASK"} <= c, c)

    def test_task_with_unknown_epic(self):
        def m(s): s.tasks[0].epic_id = "EPIC-099"
        self.assertIn("ORPHAN_TASK", self.codes(m))

    def test_cycle(self):
        def m(s):
            d = s.dependencies[0]
            s.dependencies.append(Dependency(task_id=d.depends_on, depends_on=d.task_id))
        self.assertIn("CIRCULAR_DEPENDENCY", self.codes(m))

    def test_task_missing_and_duplicated_in_sprints(self):
        def m(s):
            gone = s.sprints[0].task_ids.pop()
            s.sprints[1].task_ids.append(s.sprints[2].task_ids[0])
        c = self.codes(m)
        self.assertIn("TASK_NOT_IN_SPRINT", c)
        self.assertIn("TASK_IN_MULTIPLE_SPRINTS", c)

    def test_dependency_order_violation(self):
        def m(s):
            d = s.dependencies[0]
            for sp in s.sprints:
                if d.task_id in sp.task_ids: sp.task_ids.remove(d.task_id)
                if d.depends_on in sp.task_ids: sp.task_ids.remove(d.depends_on)
            s.sprints[0].task_ids.append(d.task_id)
            s.sprints[3].task_ids.append(d.depends_on)
        self.assertIn("DEPENDENCY_ORDER", self.codes(m))

    def test_capacity_estimate_status_member(self):
        def m(s):
            s.tasks[0].estimated_hours = 500
            s.tasks[1].estimated_hours = 0
            s.assignments[0].member_id = "TEAM-042"
            s.assignments[1].member_id = "TEAM-008" if s.assignments[1].member_id != "TEAM-008" else "TEAM-001"
        c = self.codes(m)
        self.assertTrue({"INVALID_ESTIMATE", "SPRINT_CAPACITY", "INVALID_ASSIGNMENT_MEMBER", "ROLE_MISMATCH"} <= c, c)

    def test_invalid_enum_and_status(self):
        def m(s):
            s.tasks[0].priority = "urgent!!"
            s.tasks[1].status = "sleeping"
        self.assertTrue({"INVALID_PRIORITY", "INVALID_STATUS"} <= self.codes(m))


class JsonToolTests(unittest.TestCase):
    def test_fence_prose_trailing_comma(self):
        self.assertEqual(extract_json('Here:\n```json\n{"a": [1, 2,],}\n```'), {"a": [1, 2]})

    def test_truncated_output_is_repaired(self):
        data = extract_json('{"tasks": [{"t": "a"}, {"t": "b"}, {"t": "c')
        self.assertEqual(data, {"tasks": [{"t": "a"}, {"t": "b"}]})

    def test_garbage_raises(self):
        with self.assertRaises(AgentOutputError):
            extract_json("no json at all")


if __name__ == "__main__":
    unittest.main()
