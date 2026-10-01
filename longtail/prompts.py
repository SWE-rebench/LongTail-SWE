"""Renderers for the solver, judge, and repairer prompts.

The prompt texts live in the top-level `prompts/` directory as Jinja2 templates; this
module only fills in the variables. Agent-runtime instructions (tool protocol, shell
session rules, submission commands) are intentionally not part of the templates.
"""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .schemas import RepairMode

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=False,
)


def _render(name: str, **variables: object) -> str:
    return _ENV.get_template(name).render(**variables)


def auditor_system_prompt() -> str:
    """Initial task auditor (install config, test patch, redacted issue)."""
    return _render("auditor/system.j2")


def solver_system_prompt() -> str:
    return _render("solver/system.j2")


def solver_task_prompt(issue_description: str) -> str:
    """`issue_description` is the task's problem_statement (with the public addendum, if any)."""
    return _render("solver/task.j2", issue_description=issue_description)


def worker_system_prompt() -> str:
    """System prompt shared by the judge and the repairer."""
    return _render("worker/system.j2")


def _verdict_schema(instance_id: str, revision: int, repair_mode: RepairMode) -> str:
    schema = {
        "instance_id": instance_id,
        "revision": revision,
        "fairness": "unfair",
        "coverage_sufficiency": "insufficient",
        "model_patch_assessment": "Assessment across every model attempt.",
        "test_patch_scope_assessment": {
            "classification": "test_support_only",
            "reviewed_paths": ["path/to/reviewed/test-support-file"],
            "evidence": ["bundle artifact path and observed scope fact"],
        },
        "decision": "repair",
        "repair_targets": (
            ["test_patch"]
            if repair_mode == "test_patch_only"
            else ["test_patch", "contract_addendum"]
        ),
        "findings": [
            {
                "summary": "A concrete finding.",
                "evidence": ["bundle artifact path and observed fact"],
            }
        ],
        "private_repair_feedback": "Concrete private repair instructions.",
    }
    return json.dumps(schema, ensure_ascii=False)


def judge_issue_description(
    instance_id: str,
    revision: int,
    bundle_directory: Path,
    num_runs: int,
    repair_mode: RepairMode = "test_and_addendum",
) -> str:
    return _render(
        "judge/task.j2",
        instance_id=instance_id,
        revision=revision,
        bundle_directory=bundle_directory,
        num_runs=num_runs,
        repair_mode=repair_mode,
        verdict_schema=_verdict_schema(instance_id, revision, repair_mode),
    )


def judge_retry_issue_description(
    instance_id: str,
    revision: int,
    num_runs: int,
    bundle_directory: Path,
    failure_path: Path,
    trajectory_path: Path | None,
    judge_attempt_index: int,
    max_judge_extraction_retries: int,
    repair_mode: RepairMode = "test_and_addendum",
) -> str:
    return _render(
        "judge/retry.j2",
        instance_id=instance_id,
        revision=revision,
        bundle_directory=bundle_directory,
        num_runs=num_runs,
        repair_mode=repair_mode,
        verdict_schema=_verdict_schema(instance_id, revision, repair_mode),
        failure_path=failure_path,
        trajectory_path=trajectory_path,
        judge_attempt_index=judge_attempt_index,
        max_judge_extraction_retries=max_judge_extraction_retries,
    )


def repair_issue_description(
    instance_id: str,
    revision: int,
    bundle_directory: Path,
    verdict_path: Path,
    original_bundle_directory: Path,
    work_in_progress_bundle_directory: Path,
    current_version_directory: Path | None,
    repair_mode: RepairMode = "test_and_addendum",
) -> str:
    return _render(
        "repairer/task.j2",
        instance_id=instance_id,
        revision=revision,
        bundle_directory=bundle_directory,
        verdict_path=verdict_path,
        original_bundle_directory=original_bundle_directory,
        work_in_progress_bundle_directory=work_in_progress_bundle_directory,
        current_version_directory=current_version_directory,
        repair_mode=repair_mode,
    )


def repair_retry_issue_description(
    instance_id: str,
    revision: int,
    bundle_directory: Path,
    verdict_path: Path,
    original_bundle_directory: Path,
    work_in_progress_bundle_directory: Path,
    latest_version_directory: Path,
    repair_attempt_index: int,
    max_validity_repair_retries: int,
    repair_mode: RepairMode = "test_and_addendum",
) -> str:
    return _render(
        "repairer/retry.j2",
        instance_id=instance_id,
        revision=revision,
        bundle_directory=bundle_directory,
        verdict_path=verdict_path,
        original_bundle_directory=original_bundle_directory,
        work_in_progress_bundle_directory=work_in_progress_bundle_directory,
        latest_version_directory=latest_version_directory,
        repair_attempt_index=repair_attempt_index,
        max_validity_repair_retries=max_validity_repair_retries,
        repair_mode=repair_mode,
    )
