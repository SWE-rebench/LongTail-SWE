#!/usr/bin/env python3
"""Run the evaluation protocol for Longtail-SWE tasks in their instance images.

For each task the script resets the repository, applies a solution patch (the
reference patch with --golden-eval, or one from --patches) and the test patch,
runs install_config.test_cmd, parses the log with install_config.log_parser and
checks that every FAIL_TO_PASS and PASS_TO_PASS test passes. Solver edits to files touched by
the test patch are discarded before the test patch is applied.
"""
import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.log_parsers import NAME_TO_PARSER
from lib.naming import instance_image_tag

APPLY = "git apply -v --3way --recount --ignore-space-change --whitespace=nowarn"

# Timing suffixes some runners embed in test names; stripped on both sides.
_TIMING_RES = [
    re.compile(r"\s*\[\s*\d+(?:\.\d+)?\s*(?:ms|s)\s*\]\s*$", re.IGNORECASE),
    re.compile(r"\s+in\s+\d+(?:\.\d+)?\s+(?:msec|sec)\b", re.IGNORECASE),
    re.compile(r"\s*\(\s*\d+(?:\.\d+)?\s*(?:ms|s)\s*\)\s*$", re.IGNORECASE),
]


def normalize(name: str) -> str:
    for pattern in _TIMING_RES:
        name = pattern.sub("", name)
    return name.strip()


def test_patch_paths(test_patch: str) -> list[str]:
    """Paths touched by the test patch (old and new names, renames included)."""
    paths: list[str] = []
    for line in test_patch.splitlines():
        if line.startswith("diff --git "):
            for name in line.split(" ")[2:4]:
                path = name[2:] if name[:2] in ("a/", "b/") else name
                if path not in paths:
                    paths.append(path)
    return paths


def restore_commands(test_patch: str) -> list[str]:
    """Discard solver edits to evaluation-owned files before the test patch is applied."""
    return [
        f"git checkout HEAD -- {q} 2>/dev/null || {{ git rm -rf -q --ignore-unmatch -- {q}; rm -rf -- {q}; }}"
        for q in map(shlex.quote, test_patch_paths(test_patch))
    ]


def evaluate(spec: dict, patch: str, image: str, logs_dir: Path, timeout: int) -> dict:
    instance_id = spec["instance_id"]
    config = spec["install_config"]
    test_cmd = config["test_cmd"]
    test_cmds = [test_cmd] if isinstance(test_cmd, str) else list(test_cmd)
    parser = NAME_TO_PARSER[config["log_parser"]]
    workdir = f"/{spec['repo'].split('/')[1]}"

    with tempfile.TemporaryDirectory(prefix="eval_patches_") as tmp:
        (Path(tmp) / "patch.diff").write_text(patch, encoding="utf-8")
        (Path(tmp) / "test_patch.diff").write_text(spec["test_patch"], encoding="utf-8")
        script = "\n".join(
            ["set -e", "git reset --hard HEAD", f"{APPLY} /patches/patch.diff"]
            + restore_commands(spec["test_patch"])
            + [f"{APPLY} /patches/test_patch.diff", "set +e", "echo ___TESTS_SECTION___"]
            + ["("]
            + test_cmds
            + [")", "status=$?", "echo ___TESTS_SECTION_END___", 'echo "___TESTS_EXIT_CODE___=$status"', 'exit "$status"']
        )
        run = subprocess.run(
            ["docker", "run", "--rm", "--network", "host",
             # task commands prefer IPv6 for Java; hosts without IPv6 need this override
             "-e", "_JAVA_OPTIONS=-Djava.net.preferIPv6Addresses=false", "-v", f"{tmp}:/patches:ro", "-w", workdir,
             image, "/bin/bash", "-c", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False, timeout=timeout,
        )
    output = run.stdout or ""
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / f"{instance_id}.log").write_text(output, encoding="utf-8")

    parsed = {normalize(k): v for k, v in parser(output).items()}
    passed = sorted(k for k, v in parsed.items() if v == "PASSED")
    expected = sorted(normalize(n) for n in spec["FAIL_TO_PASS"] + spec["PASS_TO_PASS"])
    missing = sorted(set(expected) - set(passed))
    return {
        "instance_id": instance_id,
        "exit_code": run.returncode,
        # resolved: every required test passes (extra passing tests are allowed)
        "resolved": not missing,
        "exact_match": passed == expected,
        "missing": missing,
        "unexpected_passed": sorted(set(passed) - set(expected)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=str(ROOT / "data" / "longtail_tasks.json"))
    parser.add_argument("--patches", help="JSON list of {instance_id, patch} solution patches.")
    parser.add_argument("--golden-eval", action="store_true", help="Evaluate the reference patches.")
    parser.add_argument("--instance-ids", default="", help="Comma-separated subset.")
    parser.add_argument("--tag-prefix", default="longtail/")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=3600, help="Per-task container timeout in seconds.")
    parser.add_argument("--logs-dir", default="logs")
    parser.add_argument("--report-json", default="eval_report.json")
    args = parser.parse_args()
    if bool(args.patches) == args.golden_eval:
        parser.error("pass exactly one of --patches or --golden-eval")

    specs = json.loads(Path(args.json).read_text(encoding="utf-8"))
    wanted = {i for i in args.instance_ids.split(",") if i}
    if wanted:
        unknown = wanted - {s["instance_id"] for s in specs}
        if unknown:
            parser.error(f"unknown instance ids: {sorted(unknown)}")
        specs = [s for s in specs if s["instance_id"] in wanted]
    overrides = {}
    if args.patches:
        overrides = {p["instance_id"]: p["patch"] for p in json.loads(Path(args.patches).read_text())}
        specs = [s for s in specs if s["instance_id"] in overrides]

    def run_one(spec: dict) -> dict:
        patch = spec["patch"] if args.golden_eval else overrides[spec["instance_id"]]
        image = instance_image_tag(spec["instance_id"], args.tag_prefix)
        try:
            return evaluate(spec, patch, image, Path(args.logs_dir), args.timeout)
        except Exception as exc:  # report and continue
            return {"instance_id": spec["instance_id"], "resolved": False, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        items = list(pool.map(run_one, specs))

    resolved = sum(1 for item in items if item["resolved"])
    Path(args.report_json).write_text(
        json.dumps({"total": len(items), "resolved": resolved, "items": items}, indent=2), encoding="utf-8"
    )
    exact = sum(1 for item in items if item.get("exact_match"))
    print(f"resolved {resolved}/{len(items)} (exact test-set match {exact}); report: {args.report_json}")
    return 0 if resolved == len(items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
