"""Consistency checks that need no Docker and no network."""
import hashlib
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
    assert len(TASKS) == 202 and len(EASY_TASKS) == 296
    assert len(ids) == len(set(ids)) == 498
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


def test_excluded_tasks_are_not_in_the_benchmark():
    excluded = json.loads((ROOT / "data" / "excluded_tasks.json").read_text(encoding="utf-8"))
    assert len(excluded) == 35
    assert len({e["instance_id"] for e in excluded}) == 35
    assert not {e["instance_id"] for e in excluded} & {t["instance_id"] for t in ALL_TASKS}


def test_statement_is_base_plus_addendum():
    for t in ALL_TASKS:
        expected = t["problem_statement_base"]
        if t["contract_addendum"]:
            expected += "\n\n### Additional contract requirements\n\n" + t["contract_addendum"]
        assert t["problem_statement"] == expected, t["instance_id"]


def test_release_manifest_and_retained_content():
    manifest = json.loads((ROOT / "data/release_manifest.json").read_text())
    assert manifest["release_id"] == "longtail-swe-202-v1"
    assert manifest["instance_ids"] == [t["instance_id"] for t in TASKS]
    assert manifest["counts"] == {"hard": 202, "easy": 296, "combined": 498, "excluded": 35, "models": 8, "attempts": 4848}
    for relative, expected in manifest["sha256"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    public_fields = {"instance_id", "repo", "base_commit", "created_at", "language", "license",
                     "problem_statement", "problem_statement_base", "contract_addendum", "patch", "test_patch",
                     "FAIL_TO_PASS", "PASS_TO_PASS", "pr_url", "install_config"}
    for task in TASKS:
        assert set(task) == public_fields
        raw = json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(raw).hexdigest() == manifest["retained_record_sha256"][task["instance_id"]]
        assert not {"image_name", "interface", "longtail_release"} & set(task)
    assert sum(bool(t["contract_addendum"]) for t in TASKS) == 173
    assert manifest["attempt_selection"]["cohorts"] == {"original": 4080, "statement_rerun": 768}


def test_selected_ledger_and_generated_metrics():
    from scripts.summarize_results import aggregate, load_rows, validate_rows

    rows = load_rows(ROOT / "data/selected_results_202.jsonl")
    validate_rows(rows, TASKS)
    metrics = aggregate(rows, TASKS)
    assert metrics == json.loads((ROOT / "data/results_202.json").read_text())
    import csv
    csv_path = ROOT / "data/results_202.csv"
    assert b"\r" not in csv_path.read_bytes()
    with csv_path.open(newline="") as stream:
        assert list(csv.DictReader(stream)) == [{k: str(v) for k, v in m.items()} for m in metrics]
    manifest = json.loads((ROOT / "data/release_manifest.json").read_text())
    assert sum(not r["initial_statement_matches_release"] for r in rows) == 192
    assert sum(r["implementation_patch_partial"] is True for r in rows) == 135
    assert sum(r["replay_candidate_patch_match"] == "crlf_only" for r in rows) == 66
    assert manifest["limitations"]["unresolved_task_questions"] == 26
    expected = {"opus_5_5_high": (169, 161, 164), "sol_high": (158, 151, 150),
                "luna_xhigh": (146, 144, 143), "kimi_k3": (129, 137, 120),
                "deepseek_v4_flash": (112, 119, 109), "glm_5_3_flash": (96, 95, 101),
                "qwen_3_8_27b_262k": (90, 85, 84), "qwen_3_6_27b_262k": (32, 32, 37)}
    for model, counts in expected.items():
        assert tuple(sum(r["resolved"] for r in rows if r["model"] == model and r["run"] == i) for i in range(3)) == counts


def test_ledger_rejects_corrupted_selection():
    import pytest
    from scripts.summarize_results import load_rows, validate_rows

    rows = load_rows(ROOT / "data/selected_results_202.jsonl")
    for broken in (rows[:-1], rows[:-1] + [rows[0]], [{**rows[0], "resolved": 1}] + rows[1:],
                   [{**rows[0], "cohort": "supplementary"}] + rows[1:]):
        with pytest.raises(ValueError):
            validate_rows(broken, TASKS)


def test_all_eight_paper_models_and_observed_run_settings():
    cfg = yaml.safe_load((ROOT / "configs/models.yaml").read_text())
    assert len(cfg["solver"]["evaluation_models"]) == 8
    assert any(m["model"] == "Claude Opus 5.5" for m in cfg["solver"]["evaluation_models"])
    settings = json.loads((ROOT / "configs/evaluation_runs.json").read_text())
    assert len(settings) == len({(s["model_key"], s["cohort"], s["run"]) for s in settings}) == 48
    assert {s["context"] for s in settings if s["model_key"] == "qwen_3_6_27b_262k" and s["cohort"] == "statement_rerun"} == {131072}
    assert {s["params"]["reasoning_effort"] for s in settings if s["model_key"] == "deepseek_v4_flash"} == {"max"}


def test_paper_annotations_reproduce_all_final_tables():
    import collections
    import pytest

    annotations = json.loads((ROOT / "data/annotations_202.json").read_text())["rows"]
    table = json.loads((ROOT / "data/paper_tables_202.json").read_text())
    assert len(annotations) == len({r["instance_id"] for r in annotations}) == 202
    assert {r["instance_id"] for r in annotations} == {t["instance_id"] for t in TASKS}
    assert collections.Counter(r["difficulty"] for r in annotations) == {"easy": 7, "medium": 73, "hard": 122}
    assert collections.Counter(c for r in annotations for c in r["task_type_labels"]) == table["task_types_and_difficulty"]["categories"]
    assert sum(r["original_v2_path"] for r in annotations) == table["funnel"]["original_v2_path"] == 68
    assert sum(r["final_reannotation_code"] == "A" for r in annotations) == table["funnel"]["final_A"] == 196
    assert sum(r["original_v2_path"] and r["final_reannotation_code"] == "A" for r in annotations) == table["funnel"]["original_v2_path_final_A"] == 66
    assert table["funnel"]["ratio_final_A_to_original_path_final_A"] == pytest.approx(196 / 66)
    assert all(table["old_206_reproduction"].values())


def test_dart_parser_reads_glued_progress_lines():
    log = "00:01 +0: /w/test/a_test.dart: first\nsome output00:02 +1: /w/test/a_test.dart: second\n"
    parsed = NAME_TO_PARSER["parse_log_dart_v3"](log)
    assert any("second" in k for k in parsed), parsed
