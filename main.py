#!/usr/bin/env python3
"""AI Project Manager Orchestrator - entry point.

Exit codes: 0 = plan complete and validated, 1 = runtime/infrastructure error, 2 = validation failed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agents import build_agents  # noqa: E402
from config.settings import load_settings, load_team  # noqa: E402
from orchestrator.orchestrator import Orchestrator  # noqa: E402
from services.document_loader import load_document  # noqa: E402
from services.errors import PMError  # noqa: E402
from services.logging_setup import log, setup_logging  # noqa: E402
from services.storage import JsonFileStore  # noqa: E402

TEST_DOC = ROOT / "data" / "test_project_documentation.md"
EXPECTED_FILES = ["requirements", "epics", "tasks", "dependencies", "priorities", "sprints", "assignments",
                  "risks", "validation", "final_project_plan", "execution_log"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="AI Project Manager Orchestrator (CrewAI + Ollama)")
    p.add_argument("--doc", help="path to the project documentation (markdown with '## ' sections)")
    p.add_argument("--test", action="store_true", help="run on the synthetic test document and verify all outputs")
    p.add_argument("--mock", action="store_true", help="use the offline mock LLM (no Ollama needed; for smoke tests)")
    p.add_argument("--resume", action="store_true", help="continue from outputs/state_checkpoint.json")
    p.add_argument("--model", help="override the Ollama model name")
    p.add_argument("--output-dir", help="override the output directory")
    return p.parse_args(argv)


def print_summary(state, team, orch, seconds: float, out_dir: Path) -> None:
    ok = state.project.status == "complete"
    print("\n" + "=" * 72)
    print(f"PROJECT : {state.project.name}")
    print(f"STATUS  : {'COMPLETE - validation PASSED' if ok else 'INCOMPLETE - validation FAILED'}")
    print(f"RUN     : {len(orch.exec_log)} orchestrator steps, {orch.llm_calls} LLM calls, {seconds:.0f}s, model={orch.settings.model}")
    print(f"PLAN    : {len(state.requirements)} requirements, {len(state.epics)} epics, {len(state.tasks)} tasks, "
          f"{len(state.dependencies)} dependencies, {len(state.risks)} risks")
    print("SPRINTS :")
    for s in state.sprints:
        print(f"  {s.id}  {len(s.task_ids):>2} tasks  {s.planned_hours:>6.1f}h / {s.capacity_hours:g}h  - {s.goal}")
    print("WORKLOAD (hours per sprint):")
    for mid, w in state.workload(team).items():
        per = "  ".join(f"S{i + 1}={h:g}" for i, h in enumerate(w["hours_per_sprint"].values()))
        print(f"  {w['name']:<22} {per}   (cap {w['capacity_hours_per_sprint']:g}/sprint)")
    rep = state.validation
    if rep:
        print(f"VALIDATION: {rep.error_count} errors, {rep.warning_count} warnings")
        for i in rep.issues[:12]:
            print(f"  [{i.severity}] {i.code} {i.entity_id}: {i.message}")
        if rep.semantic_notes:
            print(f"SEMANTIC REVIEW ({rep.semantic_verdict}): " + " | ".join(rep.semantic_notes))
    print(f"OUTPUTS : {out_dir}")
    for f in sorted(out_dir.glob("*.json")):
        print(f"  {f.name}")
    print("=" * 72)


def verify_outputs(out_dir: Path) -> list[str]:
    problems = [f"missing outputs/{n}.json" for n in EXPECTED_FILES if not (out_dir / f"{n}.json").exists()]
    plan = out_dir / "final_project_plan.json"
    if plan.exists():
        data = json.loads(plan.read_text(encoding="utf-8"))
        for key in ("project", "requirements", "epics", "tasks", "dependencies", "priorities", "sprints",
                    "assignments", "risks", "milestones", "validation"):
            if not data.get(key):
                problems.append(f"final_project_plan.json: '{key}' is empty")
    return problems


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        settings, team = load_settings(), load_team()
        if args.model:
            settings.model = args.model
        if args.output_dir:
            settings.output_dir = args.output_dir
        setup_logging(settings.output_path / "run.log")
        doc_path = Path(args.doc) if args.doc and not args.test else TEST_DOC
        doc = load_document(doc_path)
        log("ORCHESTRATOR", f"Document: {doc_path} ({len(doc.raw)} chars, {len(doc.sections)} sections)")

        if args.mock:
            from services.mock_llm import MockRunner
            runner = MockRunner()
            log("ORCHESTRATOR", "MOCK mode: no LLM is used")
        else:
            from crew.runner import CrewRunner
            from services.ollama_service import OllamaService
            ollama = OllamaService(settings.ollama_base_url, settings.model, settings.health_timeout_seconds, settings.keep_alive)
            ollama.check_model()
            ollama.warm_up()
            runner = CrewRunner(settings)

        started = time.time()
        orch = Orchestrator(settings, team, build_agents(runner), JsonFileStore(settings.output_path), doc)
        state = orch.run(resume=args.resume)
        print_summary(state, team, orch, time.time() - started, settings.output_path)

        if state.project.status != "complete":
            return 2
        if args.test:
            problems = verify_outputs(settings.output_path)
            for p in problems:
                log("ERROR", p, 40)
            if problems:
                return 2
            log("ORCHESTRATOR", "TEST PASSED: all outputs present and deterministic validation passed")
        return 0
    except KeyboardInterrupt:
        log("ERROR", "Interrupted by user; use --resume to continue from the last checkpoint", 40)
        return 130
    except PMError as exc:
        log("ERROR", f"{type(exc).__name__}: {exc}", 40)
        return 1
    except Exception as exc:  # unexpected bug: never hide it
        log("ERROR", f"Unexpected {type(exc).__name__}: {exc}\n{traceback.format_exc()}", 40)
        return 1


if __name__ == "__main__":
    sys.exit(main())
