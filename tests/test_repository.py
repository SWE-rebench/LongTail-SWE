"""Consistency checks that need no Docker and no network."""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.log_parsers import NAME_TO_PARSER  # noqa: E402
from longtail.artifacts import extract_judge_verdict  # noqa: E402
from longtail.prompts import (  # noqa: E402
    auditor_system_prompt,
    solver_system_prompt,
    solver_task_prompt,
    worker_system_prompt,
    judge_issue_description,
    judge_retry_issue_description,
    repair_issue_description,
    repair_retry_issue_description,
)

TASKS = json.loads((ROOT / "data" / "longtail_tasks.json").read_text(encoding="utf-8"))
EASY_TASKS = json.loads((ROOT / "data" / "longtail_easy_tasks.json").read_text(encoding="utf-8"))
ALL_TASKS = TASKS + EASY_TASKS
IMAGES = yaml.safe_load((ROOT / "base_images.yaml").read_text(encoding="utf-8"))["images"]


def test_tasks_are_well_formed():
    ids = [t["instance_id"] for t in ALL_TASKS]
    assert len(TASKS) == 237 and len(EASY_TASKS) == 296
    assert len(ids) == len(set(ids)) == 533
    for t in ALL_TASKS:
        assert t["patch"] and t["test_patch"] and t["FAIL_TO_PASS"]
        assert not set(t["FAIL_TO_PASS"]) & set(t["PASS_TO_PASS"])
        assert t["install_config"]["log_parser"] in NAME_TO_PARSER
        assert isinstance(t["install_config"]["test_cmd"], str)


def test_every_base_image_is_defined_and_buildable():
    by_tag = {i["tag"]: i for i in IMAGES}
    for t in ALL_TASKS:
        assert t["install_config"]["base_image_name"] in by_tag
    for image in IMAGES:
        if "alias_of" in image:
            assert image["alias_of"] in by_tag
        else:
            assert (ROOT / "base_dockerfiles" / image["dockerfile"]).is_file(), image["tag"]
        if "parent" in image:
            assert image["parent"] in by_tag


def test_no_internal_references():
    blob = "".join(p.read_text(errors="ignore") for p in (ROOT / "base_dockerfiles").iterdir())
    blob += (ROOT / "base_images.yaml").read_text()
    for token in ("neb" + "ius", "e00e" + "1t12", "192.168." + "1.29"):
        assert token not in blob


def test_prompts_render():
    bundle = Path("/bundle")
    assert "verdict.json" in judge_issue_description("o__r-1", 0, bundle, 3)
    assert "retry" in judge_retry_issue_description("o__r-1", 0, 3, bundle, Path("/f"), None, 1, 1)
    assert "test_patch.patch" in repair_issue_description(
        "o__r-1", 0, bundle, Path("/v.json"), bundle, bundle, None
    )
    assert "validation retry" in repair_retry_issue_description(
        "o__r-1", 0, bundle, Path("/v.json"), bundle, bundle, bundle, 1, 2
    )


def test_verdict_roundtrip():
    verdict = {
        "instance_id": "o__r-1",
        "revision": 0,
        "fairness": "fair",
        "coverage_sufficiency": "sufficient",
        "model_patch_assessment": "ok",
        "test_patch_scope_assessment": {
            "classification": "test_only",
            "reviewed_paths": ["tests/a_test.py"],
            "evidence": ["bundle/test_patch.patch: only tests"],
        },
        "decision": "accept",
        "repair_targets": [],
        "findings": [{"summary": "fine", "evidence": ["bundle/x"]}],
        "private_repair_feedback": "",
    }
    parsed = extract_judge_verdict(json.dumps(verdict), expected_instance_id="o__r-1", expected_revision=0)
    assert parsed.decision == "accept"


def test_eval_discards_solver_edits_to_test_files():
    from scripts.eval import restore_commands, test_patch_paths

    patch = "diff --git a/old/a_test.py b/new/a_test.py\nrename from old/a_test.py\n+++ b/new/a_test.py\n"
    assert test_patch_paths(patch) == ["old/a_test.py", "new/a_test.py"]
    assert len(restore_commands(patch)) == 2


def test_prompts_have_no_agent_runtime_instructions():
    texts = [p.read_text() for p in (ROOT / "prompts").rglob("*.j2")]
    texts += [auditor_system_prompt(), solver_system_prompt(), solver_task_prompt("issue"), worker_system_prompt()]
    for text in texts:
        for marker in ("tools_info", "bash_terminal", "`submit`", "PERSISTENT BASH", "shell_prompt", "Force-stage"):
            assert marker not in text, marker
    assert "issue" in solver_task_prompt("issue")
    assert "install_config.json" in auditor_system_prompt()


def test_statement_split_and_licenses():
    heading = "### Additional contract requirements"
    allowed = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "Unlicense", "ISC", "CC0-1.0"}
    for t in ALL_TASKS:
        assert t["license"] in allowed
        if t["contract_addendum"]:
            assert heading in t["problem_statement"]
            assert t["problem_statement"].endswith(t["contract_addendum"])
            assert t["problem_statement"].startswith(t["problem_statement_base"])
        else:
            assert t["problem_statement"] == t["problem_statement_base"]
