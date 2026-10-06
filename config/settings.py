"""Settings loader: config/settings.json + environment overrides."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

from models.team import Team
from services.errors import ConfigError

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


@dataclass
class Settings:
    ollama_base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:7b-instruct"
    temperature: float = 0.1
    llm_timeout_seconds: int = 300
    health_timeout_seconds: int = 5
    keep_alive: str = "30m"
    max_iterations: int = 80
    max_action_rounds: int = 6
    max_agent_attempts: int = 3
    max_repair_rounds: int = 2
    max_context_chars: int = 3500
    default_duration_weeks: int = 4
    sprint_length_weeks: int = 1
    utilization_target: float = 0.9
    max_epics: int = 8
    max_tasks_per_epic: int = 8
    min_tasks_per_epic: int = 2
    max_risks: int = 10
    max_dependencies_per_task: int = 3
    min_estimate_hours: float = 1
    max_estimate_hours: float = 24
    type_min_sprint: dict = field(default_factory=lambda: {"qa": 2})
    output_dir: str = "outputs"

    @property
    def output_path(self) -> Path:
        p = Path(self.output_dir)
        return p if p.is_absolute() else ROOT / p


def load_settings(path: Path | None = None) -> Settings:
    path = path or CONFIG_DIR / "settings.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    known = {f.name for f in fields(Settings)}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"Unknown settings keys in {path}: {sorted(unknown)}")
    s = Settings(**data)
    s.ollama_base_url = os.environ.get("PM_OLLAMA_URL", s.ollama_base_url)
    s.model = os.environ.get("PM_MODEL", s.model)
    return s


def load_team(path: Path | None = None) -> Team:
    path = path or CONFIG_DIR / "team.json"
    try:
        return Team.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot load team file {path}: {exc}") from exc
    except ValueError as exc:  # pydantic.ValidationError subclasses ValueError
        raise ConfigError(f"Invalid team file {path}: {exc}") from exc
