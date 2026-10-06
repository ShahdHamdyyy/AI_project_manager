"""Storage abstraction. The orchestrator only talks to `StateStore`; swap JsonFileStore for a DB later."""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

from services.errors import PMError


class StateStore(ABC):
    @abstractmethod
    def save_state(self, state_dict: dict) -> None: ...

    @abstractmethod
    def load_state(self) -> dict | None: ...

    @abstractmethod
    def save_artifact(self, name: str, payload) -> Path | str: ...

    @abstractmethod
    def reset(self) -> None:
        """Remove artifacts of a previous run."""


class JsonFileStore(StateStore):
    STATE_FILE = "state_checkpoint.json"
    ARTIFACTS = ["requirements", "epics", "tasks", "dependencies", "priorities", "sprints", "assignments",
                 "risks", "validation", "final_project_plan", "draft_project_plan", "execution_log"]

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _write(self, path: Path, payload) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)  # atomic: never leave half-written JSON
        except OSError as exc:
            raise PMError(f"Cannot write {path}: {exc}") from exc

    def save_state(self, state_dict: dict) -> None:
        self._write(self.dir / self.STATE_FILE, state_dict)

    def load_state(self):
        path = self.dir / self.STATE_FILE
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PMError(f"Corrupt checkpoint {path}: {exc}") from exc

    def save_artifact(self, name: str, payload) -> Path:
        path = self.dir / f"{name}.json"
        self._write(path, payload)
        return path

    def reset(self) -> None:
        for name in self.ARTIFACTS:
            (self.dir / f"{name}.json").unlink(missing_ok=True)
        (self.dir / self.STATE_FILE).unlink(missing_ok=True)
