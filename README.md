# Longtail-SWE: environments, evaluation, and solver–judge–repair prompts

Minimal replication material for *Longtail-SWE: High Quality SWE Tasks for Underrepresented
Languages* (206 benchmark tasks plus a 296-task easier companion set, 13 languages: Clojure, Dart, Elixir, Erlang, F#, Haskell, Julia,
Kotlin, Lua, OCaml, R, Scala, Swift).

| Path | Content |
| --- | --- |
| `data/longtail_tasks.json` | The 206-task Longtail-SWE benchmark after the post-evaluation audit (statement, reference patch, test patch, F2P/P2P, install/test commands, log parser). |
| `data/excluded_tasks.json` | The 31 tasks of the original 237-task set that the audit removed, with the reason. |
| `data/longtail_easy_tasks.json` | The 296-task easier companion set, same format. |
| `LICENSE`, `data/LICENSE.md`, `LICENSE-CC-BY-4.0.txt` | MIT for code; CC BY 4.0 for original dataset contributions; third-party materials keep their licenses. |
| `base_images.yaml`, `base_dockerfiles/` | The 32 base images used by the two task sets plus the 5 intermediate images they are built from (37 build steps in total). |
| `combine.Dockerfile.j2` | Instance image template: clone at the base commit, run the install commands. |
| `scripts/build_base_images.py` | Builds base images in dependency order. |
| `scripts/build_instance_images.py` | Renders and builds one image per task. |
| `scripts/eval.py` | Applies a solution patch and the test patch in the instance image, runs the test command, parses the log, and checks F2P + P2P. |
| `lib/log_parsers.py` | The 22 log parsers referenced by the tasks. |
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
#   --tasks data/longtail_easy_tasks.json builds only the images of that task set
python scripts/build_instance_images.py --instance-ids askonomm__dompa-16
python scripts/eval.py --golden-eval --instance-ids askonomm__dompa-16
```

A task is `resolved` when every FAIL_TO_PASS and PASS_TO_PASS test passes; the report also records
whether the passing set matches exactly (`exact_match`). `eval.py` discards solver edits to files touched by the test patch before applying the test patch.

`build_base_images.py --dry-run` prints the Docker commands without running them. Images are
tagged locally as `name:tag` exactly as referenced by `install_config.base_image_name`; instance
images are tagged `longtail/<lowercased instance_id>`. Building every image needs substantial
disk space and network access (GitHub, package registries).

All scripts default to `data/longtail_tasks.json`; pass `--json data/longtail_easy_tasks.json` for the easy set.
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

`data/longtail_tasks.json` and `data/longtail_easy_tasks.json` keep only the fields needed to build and evaluate the tasks. Internal
image names, PR descriptions, PR authors, and annotation metadata were removed; `pr_url` is
kept for provenance. `problem_statement` is the statement the solver sees. It equals
`problem_statement_base` (the statement after the initial audit, possibly containing `[HIDDEN]` redactions of
implementation hints) plus, for the tasks repaired with an addendum (177 of 206 in the benchmark, 244 of 296 in the easy set), the `### Additional contract requirements`
section whose text is `contract_addendum` (empty otherwise). `license` is the license of the source repository.

## Post-evaluation audit (current version)

The benchmark first had 237 tasks (git tag `v1.0-237`). A post-evaluation audit (paper, Appendix "Post-evaluation
audit and refinement") corrected the evaluator, checked every stored solver run, and repaired tests and statements.
The current `data/longtail_tasks.json` keeps 206 tasks:

| Group | Tasks |
| --- | --- |
| Accepted by the audit, statement unchanged | 145 |
| Accepted by the audit, statement clarified (models re-run on the new statement) | 32 |
| Repaired, audit pending, statement unchanged | 21 |
| Repaired, audit pending, editorial statement change only | 8 |

Removed (`data/excluded_tasks.json`): 19 tasks without an acceptable repair, 2 unsuitable tasks, and 10 tasks whose
statement gained new requirements. For the repaired tasks, `test_patch`, `FAIL_TO_PASS`/`PASS_TO_PASS` (the tests that
pass in two reference-patch runs), and in 22 tasks `test_cmd` changed. `scripts/eval.py` follows the corrected
evaluator: solution patch, then restore of every test-patch path (renames included), then the test patch; a failed
`git apply` is retried with `--ignore-whitespace`, and a solution patch that still does not apply is applied partially
with `--reject` so the tests still run. The Dart parser also reads progress lines glued to unterminated test output.

## Relation to the paper

This repository contains the 206-task Longtail-SWE benchmark, its executable environments, the evaluation
protocol, and the prompts, schemas, and settings of the auditor, solver, judge, and repairer. The paper's
supplementary archive additionally contains material that is **not** part of this repository: the raw issue texts and original tests, agent trajectories, audit and repair histories (the
intermediate task revisions), and the data-collection code. The scaffold that executes the agents and the repair
validator are also not included.

## License

Code, Dockerfiles, templates, and prompts: MIT (`LICENSE`). Original dataset contributions: CC BY 4.0
(`LICENSE-CC-BY-4.0.txt`). Third-party materials (issue text, reference patches, original tests, repository
content) remain under the license of their source repository; see `data/LICENSE.md`.
