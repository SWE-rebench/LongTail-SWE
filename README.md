# Longtail-SWE: environments, evaluation, and solver–judge–repair prompts

Minimal replication material for *Longtail-SWE: High Quality SWE Tasks for Underrepresented
Languages* (237 tasks, 13 languages: Clojure, Dart, Elixir, Erlang, F#, Haskell, Julia,
Kotlin, Lua, OCaml, R, Scala, Swift).

| Path | Content |
| --- | --- |
| `data/longtail_tasks.json` | The 237 final tasks (statement, reference patch, test patch, F2P/P2P, install/test commands, log parser). |
| `base_images.yaml`, `base_dockerfiles/` | The 29 base images used by the tasks plus the 5 intermediate images they are built from (34 build steps in total). |
| `combine.Dockerfile.j2` | Instance image template: clone at the base commit, run the install commands. |
| `scripts/build_base_images.py` | Builds base images in dependency order. |
| `scripts/build_instance_images.py` | Renders and builds one image per task. |
| `scripts/eval.py` | Applies a solution patch and the test patch in the instance image, runs the test command, parses the log, and checks F2P + P2P. |
| `lib/log_parsers.py` | The 21 log parsers referenced by the tasks. |
| `prompts/` | Solver, judge, and repairer prompts as Jinja2 templates (no agent-runtime instructions). |
| `longtail/prompts.py` | Renders the templates (`solver_*`, `worker_system_prompt`, `judge_*`, `repair_*`). |
| `longtail/schemas.py`, `artifacts.py`, `state.py` | Judge-verdict and repair-submission schemas, extraction from agent output, revision state, verdict routing, test-patch scope checks. |
| `configs/models.yaml` | Models and loop settings used for the solver, judge, and repairer. |
| `tests/` | Offline consistency tests (`pytest tests`). |

## Quick start

Requires Docker, Git, and Python 3.11+.

```bash
pip install -r requirements.txt
python scripts/build_base_images.py --language Clojure          # or no flag for all languages
python scripts/build_instance_images.py --instance-ids askonomm__dompa-16
python scripts/eval.py --golden-eval --instance-ids askonomm__dompa-16
```

A task is `resolved` when every FAIL_TO_PASS and PASS_TO_PASS test passes; the report also records
whether the passing set matches exactly (`exact_match`). `eval.py` discards solver edits to files touched by the test patch before applying the test patch.

`build_base_images.py --dry-run` prints the Docker commands without running them. Images are
tagged locally as `name:tag` exactly as referenced by `install_config.base_image_name`; instance
images are tagged `longtail/<lowercased instance_id>`. Building every image needs substantial
disk space and network access (GitHub, package registries).

To evaluate your own solutions pass `--patches patches.json`, a list of
`{"instance_id": ..., "patch": ...}` objects, instead of `--golden-eval`.

## Base image provenance

`base_images.yaml` marks how each Dockerfile relates to the images used to create the tasks:

* `exact` – Dockerfile and build arguments of the original build.
* `reconstructed` – the original build file was not preserved. The Dockerfile is rebuilt from the
  recorded image configuration (Scala, Kotlin JDK 21, the minimal Lua image) or from the recorded
  build procedure (the RabbitMQ dependency layer of one Erlang image). Rebuilt images may differ
  in patch-level package versions.
* `alias` / `pull` – retag of another image / of an upstream image.

Dockerfiles pin upstream images by version (several by digest), but some install the newest
release of tools at build time (for example SDKMAN Kotlin/Gradle), so rebuilt images are
functionally, not bit-for-bit, identical. Status of validation: `scripts/eval.py --golden-eval` was
run on one task (Clojure) with the rebuilt image; the other base images and tasks were not re-run
from these Dockerfiles, so run `--golden-eval` on the languages you need before relying on them. The
`reconstructed` images (Scala, Kotlin JDK 21, minimal Lua, two F# SDK cohorts, one Erlang cohort) are the
most likely to differ.

## Solver–judge–repair pipeline

Task construction first uses an **auditor** (`prompts/auditor/system.j2`), which produces the install config, the
test patch, and the redacted issue text. The solver–judge–repair loop then runs three kinds of agents on each
task in its instance image:

1. **Solver** (`prompts/solver/`) attempts the task from the problem statement.
2. **Judge** (`prompts/judge/`, `prompts/worker/system.j2`) reads the task bundle, the solver patches and
   trajectories, and evaluation results, and writes `verdict.json` (`accept`, `repair`, or `manual_review`);
   the schema is `JudgeVerdict`. `retry.j2` is used for one targeted retry after an unparsable verdict.
3. **Repairer** (`prompts/repairer/`, `prompts/worker/system.j2`) receives the private verdict and writes a
   replacement `test_patch.patch` and `contract_addendum.md` (`RepairSubmission`). `retry.j2` is used
   after a failed execution validation.

`longtail/state.py` holds the immutable revision history, the routing of verdicts, the test-patch
scope validation, and the rendering of the public problem statement with the appended
`### Additional contract requirements` section. The templates contain only the task instructions. Agent-runtime instructions of the original scaffold (tool
protocol, persistent-shell rules, the submit command, exit handling) are not included, so the prompts can be
used with any agent framework that provides a shell tool; the judge and repairer outputs are still the files
named in the prompts. The worker system prompt refers to a validator in the repair bundle (`--execute --check-staged`);
that validation tool of the original scaffold is not part of this package. `configs/models.yaml` records the models and loop settings (Appendix A.7). Task image names
and test identifiers that contain `rebench` come from the validation environment of the source repositories
and are left unchanged.

## Data notes

`data/longtail_tasks.json` keeps only the fields needed to build and evaluate the tasks. Internal
image names, PR descriptions, PR authors, and LLM annotation metadata were removed; `pr_url` is
kept for provenance. Problem statements may contain `[HIDDEN]` spans (redactions of solution-revealing
text) and the repaired `### Additional contract requirements` section. Each task keeps the license
of its source repository (`license`).
