from agents.assignment_agent import AssignmentAgent
from agents.dependency_agent import DependencyAgent
from agents.epic_agent import EpicAgent
from agents.priority_agent import PriorityAgent
from agents.requirements_agent import RequirementsAgent
from agents.risk_agent import RiskAgent
from agents.sprint_agent import SprintAgent
from agents.task_agent import TaskAgent
from agents.validator_agent import ValidatorAgent


def build_agents(runner) -> dict:
    """One instance per specialised agent (CrewAI Agent objects are cached inside the runner)."""
    return {
        "requirements": RequirementsAgent(runner),
        "epics": EpicAgent(runner),
        "tasks": TaskAgent(runner),
        "dependencies": DependencyAgent(runner),
        "priorities": PriorityAgent(runner),
        "sprints": SprintAgent(runner),
        "assignments": AssignmentAgent(runner),
        "risks": RiskAgent(runner),
        "validator": ValidatorAgent(runner),
    }
