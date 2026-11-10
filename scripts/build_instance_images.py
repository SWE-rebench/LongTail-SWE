#!/usr/bin/env python3
"""Render combine.Dockerfile.j2 for each task and build the instance images.

Base images must exist locally first (scripts/build_base_images.py).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.naming import instance_image_tag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=str(ROOT / "data" / "longtail_tasks.json"))
    parser.add_argument("--template", default=str(ROOT / "combine.Dockerfile.j2"))
    parser.add_argument("--output-dir", default="dockerfiles", help="Where rendered Dockerfiles are written.")
    parser.add_argument("--base-image-registry", default="", help="Registry prefix of the base images, if any.")
    parser.add_argument("--tag-prefix", default="longtail/")
    parser.add_argument("--instance-ids", default="", help="Comma-separated subset.")
    parser.add_argument("--dry-run", action="store_true", help="Render Dockerfiles only.")
    args = parser.parse_args()

    template_path = Path(args.template)
    env = Environment(loader=FileSystemLoader(str(template_path.parent)), autoescape=False)
    template = env.get_template(template_path.name)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tasks = json.loads(Path(args.json).read_text(encoding="utf-8"))
    wanted = {i for i in args.instance_ids.split(",") if i}
    for spec in tasks:
        if wanted and spec["instance_id"] not in wanted:
            continue
        dockerfile = output_dir / f"{spec['instance_id']}.Dockerfile"
        dockerfile.write_text(
            template.render(spec=spec, base_image_registry=args.base_image_registry), encoding="utf-8"
        )
        if args.dry_run:
            print(f"Rendered {dockerfile}")
            continue
        tag = instance_image_tag(spec["instance_id"], args.tag_prefix)
        subprocess.run(
            ["docker", "build", "-f", str(dockerfile), "-t", tag, str(output_dir)], check=True
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
