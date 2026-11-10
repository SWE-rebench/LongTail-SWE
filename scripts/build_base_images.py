#!/usr/bin/env python3
"""Build the base images listed in base_images.yaml (parents first).

Examples:
  python scripts/build_base_images.py --dry-run
  python scripts/build_base_images.py --language Haskell
  python scripts/build_base_images.py --tasks data/longtail_tasks.json
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_images(manifest: Path) -> dict[str, dict]:
    images = yaml.safe_load(manifest.read_text(encoding="utf-8"))["images"]
    return {image["tag"]: image for image in images}


def dependencies(image: dict) -> list[str]:
    return [image[key] for key in ("parent", "alias_of") if image.get(key)]


def select(images: dict[str, dict], wanted: set[str]) -> list[str]:
    """Return `wanted` plus all transitive dependencies in build order."""
    order: list[str] = []

    def visit(tag: str) -> None:
        if tag in order:
            return
        if tag not in images:
            raise SystemExit(f"Unknown base image: {tag}")
        for dep in dependencies(images[tag]):
            visit(dep)
        order.append(tag)

    for tag in sorted(wanted):
        visit(tag)
    return order


def commands(image: dict, dockerfiles_dir: Path, platform: str) -> list[list[str]]:
    tag = image["tag"]
    if image.get("alias_of"):
        return [["docker", "tag", image["alias_of"], tag]]
    cmd = ["docker", "build", "--platform", platform, "-f", str(dockerfiles_dir / image["dockerfile"])]
    for name, value in (image.get("build_args") or {}).items():
        cmd += ["--build-arg", f"{name}={value}"]
    return [cmd + ["-t", tag, str(dockerfiles_dir)]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", default=str(ROOT / "base_images.yaml"))
    parser.add_argument("--dockerfiles-dir", default=str(ROOT / "base_dockerfiles"))
    parser.add_argument("--tasks", help="Build only images used by this task JSON.")
    parser.add_argument("--language", action="append", help="Build only task images of this language (repeatable).")
    parser.add_argument("--tag", action="append", help="Build only this tag (repeatable).")
    parser.add_argument("--platform", default="linux/amd64")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args()

    images = load_images(Path(args.manifest))
    wanted = {tag for tag, image in images.items() if image["role"] == "task"}
    if args.tasks:
        used = {t["install_config"]["base_image_name"] for t in json.loads(Path(args.tasks).read_text())}
        missing = used - set(images)
        if missing:
            print(f"Tasks use base images missing from the manifest: {sorted(missing)}", file=sys.stderr)
            return 1
        wanted &= used
    if args.language:
        wanted = {tag for tag in wanted if images[tag]["language"] in set(args.language)}
    if args.tag:
        wanted = set(args.tag)

    failures = 0
    for tag in select(images, wanted):
        for cmd in commands(images[tag], Path(args.dockerfiles_dir), args.platform):
            print(" ".join(cmd), flush=True)
            if args.dry_run:
                continue
            if subprocess.run(cmd).returncode != 0:
                failures += 1
                print(f"Failed: {tag}", file=sys.stderr)
                if not args.keep_going:
                    return 1
                break
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
