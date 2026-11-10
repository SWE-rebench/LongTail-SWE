"""Consistency checks that need no Docker and no network."""
import json
import re
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.log_parsers import NAME_TO_PARSER  # noqa: E402

TASKS = json.loads((ROOT / "data" / "longtail_tasks.json").read_text(encoding="utf-8"))
EASY_TASKS = json.loads((ROOT / "data" / "longtail_easy_tasks.json").read_text(encoding="utf-8"))
ALL_TASKS = TASKS + EASY_TASKS
IMAGES = yaml.safe_load((ROOT / "base_images.yaml").read_text(encoding="utf-8"))["images"]
FIELDS = {"instance_id", "repo", "base_commit", "created_at", "language", "license", "problem_statement",
          "problem_statement_base", "contract_addendum", "patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS",
          "pr_url", "install_config"}
LANGUAGES = {"Clojure", "Dart", "Elixir", "Erlang", "F#", "Haskell", "Julia", "Kotlin", "Lua", "OCaml", "R",
             "Scala", "Swift"}
ADDENDUM_HEADING = "\n\n### Additional contract requirements\n\n"


def test_tasks_are_well_formed():
    ids = [t["instance_id"] for t in ALL_TASKS]
    assert len(TASKS) == 202 and len(EASY_TASKS) == 269
    assert len(ids) == len(set(ids)) == 471
    for tasks in (TASKS, EASY_TASKS):
        assert {t["language"] for t in tasks} == LANGUAGES
    for t in ALL_TASKS:
        assert set(t) == FIELDS, t["instance_id"]
        assert t["patch"] and t["test_patch"] and t["FAIL_TO_PASS"]
        assert not set(t["FAIL_TO_PASS"]) & set(t["PASS_TO_PASS"])
        assert t["install_config"]["log_parser"] in NAME_TO_PARSER
        assert isinstance(t["install_config"]["test_cmd"], str)


def test_statement_is_base_plus_addendum_and_licenses_are_permissive():
    allowed = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "Unlicense", "ISC", "CC0-1.0"}
    for t in ALL_TASKS:
        assert t["license"] in allowed
        expected = t["problem_statement_base"]
        if t["contract_addendum"]:
            expected += ADDENDUM_HEADING + t["contract_addendum"]
        assert t["problem_statement"] == expected, t["instance_id"]


def test_excluded_tasks_are_not_in_the_benchmark():
    excluded = json.loads((ROOT / "data" / "excluded_tasks.json").read_text(encoding="utf-8"))
    ids = {e["instance_id"] for e in excluded}
    assert len(excluded) == len(ids) == 62
    assert all(e["reason"] for e in excluded)
    assert not ids & {t["instance_id"] for t in ALL_TASKS}


def test_every_base_image_is_defined_buildable_and_used():
    by_tag = {i["tag"]: i for i in IMAGES}
    used = {t["install_config"]["base_image_name"] for t in ALL_TASKS}
    assert used <= set(by_tag)
    for image in IMAGES:
        if "alias_of" in image:
            assert image["alias_of"] in by_tag
        else:
            assert (ROOT / "base_dockerfiles" / image["dockerfile"]).is_file(), image["tag"]
        if "parent" in image:
            assert image["parent"] in by_tag
        if image["role"] == "task":
            assert image["tag"] in used, image["tag"]
    referenced = {i["dockerfile"] for i in IMAGES if "dockerfile" in i}
    assert {p.name for p in (ROOT / "base_dockerfiles").glob("Dockerfile*")} == referenced


def test_no_internal_references():
    """Everything except the task JSON files and tests (third-party task text may mention anything)."""
    dirs = ("base_dockerfiles", "lib", "prompts", "scripts")
    paths = [p for d in dirs for p in (ROOT / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    paths += [p for p in ROOT.iterdir() if p.is_file()] + [ROOT / "data" / "excluded_tasks.json"]
    blob = "".join(p.read_text(errors="ignore") for p in paths)
    for token in ("neb" + "ius.cloud", "e00e" + "1t12", "192.168." + "1.29", "/ho" + "me/", "/mn" + "t/", "yt" + "_val"):
        assert token not in blob, token


def test_solver_prompt_renders():
    env = Environment(loader=FileSystemLoader(str(ROOT / "prompts")), autoescape=False, keep_trailing_newline=True)
    assert env.get_template("solver/system.j2").render().strip()
    assert "the issue text" in env.get_template("solver/task.j2").render(issue_description="the issue text")


def test_instance_dockerfile_renders():
    env = Environment(loader=FileSystemLoader(str(ROOT)), autoescape=False)
    spec = TASKS[0]
    text = env.get_template("combine.Dockerfile.j2").render(spec=spec, base_image_registry="")
    assert f"FROM --platform=linux/amd64 {spec['install_config']['base_image_name']} AS base" in text
    assert spec["base_commit"] in text


def test_eval_discards_solver_edits_to_test_files():
    from scripts.eval import restore_commands, test_patch_paths

    patch = "diff --git a/old/a_test.py b/new/a_test.py\nrename from old/a_test.py\n+++ b/new/a_test.py\n"
    assert test_patch_paths(patch) == ["old/a_test.py", "new/a_test.py"]
    assert len(restore_commands(patch)) == 2


def test_dart_parser_reads_glued_progress_lines():
    log = "00:01 +0: /w/test/a_test.dart: first\nsome output00:02 +1: /w/test/a_test.dart: second\n"
    parsed = NAME_TO_PARSER["parse_log_dart_v3"](log)
    assert any("second" in k for k in parsed), parsed


def test_readme_paths_exist():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for path in re.findall(r"`((?:data|scripts|lib|prompts|tests|base_dockerfiles)/[^`*]*|[A-Za-z_.]+\.(?:yaml|j2|cff))`",
                           readme):
        assert (ROOT / path.split()[0]).exists(), path
