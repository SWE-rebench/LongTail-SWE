#!/usr/bin/env python3
"""Seed exact locked dependency trees and package caches for EV repair 009."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


MANIFEST = Path("/opt/rebench-ev-cache-manifest.json")
SOURCE_ROOT = Path("/opt/rebench-ev-source")
CACHE_ROOT = Path("/opt/rebench-ev-cache")


def run(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True, env={**os.environ, "MIX_ENV": "test"})


def cache_tree(source: Path, target: Path) -> None:
    deps = source / "deps"
    if not deps.is_dir():
        raise RuntimeError(f"dependency fetch did not create {deps}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(deps, target, symlinks=True)


def prefetch_rustler() -> None:
    project = Path("/opt/rebench-rustler")
    project.mkdir(parents=True, exist_ok=True)
    (project / "mix.exs").write_text(
        "defmodule RebenchRustler.MixProject do\n"
        "  use Mix.Project\n"
        "  def project, do: [app: :rebench_rustler, version: \"0.1.0\", deps: [{:rustler, \"~> 0.36\"}]]\n"
        "end\n",
        encoding="utf-8",
    )
    run(["mix", "deps.get"], cwd=project)
    run(["mix", "deps.compile"], cwd=project)


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    report: list[dict[str, object]] = []
    for row in manifest["rows"]:
        instance_id = str(row["instance_id"])
        checkout = SOURCE_ROOT / instance_id
        run(["git", "clone", "--filter=blob:none", "--no-checkout", f"https://github.com/{row['repo']}.git", str(checkout)])
        run(["git", "fetch", "--no-tags", "origin", str(row["base_commit"])], cwd=checkout)
        run(["git", "checkout", "--detach", str(row["base_commit"])], cwd=checkout)
        cached_paths: list[str] = []
        for relative in row["paths"]:
            project = checkout if relative == "." else checkout / relative
            run(["mix", "deps.get"], cwd=project)
            slot = "root" if relative == "." else relative.replace("/", "_")
            cache_tree(project, CACHE_ROOT / instance_id / slot / "deps")
            cached_paths.append(relative)
        npm_path = row.get("npm_path")
        if npm_path:
            run(["npm", "ci", "--no-audit", "--no-fund"], cwd=checkout / str(npm_path))
        if row.get("prefetch_pr_341"):
            run(["git", "fetch", "--no-tags", "origin", "refs/pull/341/head:refs/remotes/origin/rebench-pr-341"], cwd=checkout)
            run(["git", "checkout", "--detach", "refs/remotes/origin/rebench-pr-341"], cwd=checkout)
            run(["mix", "deps.get"], cwd=checkout)
        report.append({"instance_id": instance_id, "paths": cached_paths, "npm": bool(npm_path)})
    prefetch_rustler()
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    (CACHE_ROOT / "prefetch_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cached_rows": len(report), "rustler": "/opt/rebench-rustler"}))


if __name__ == "__main__":
    main()
