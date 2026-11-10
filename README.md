# Longtail-SWE

Longtail-SWE is a benchmark of real-world software-engineering tasks in underrepresented languages
(Clojure, Dart, Elixir, Erlang, F#, Haskell, Julia, Kotlin, Lua, OCaml, R, Scala, Swift). Each task is a GitHub
issue resolved by a merged pull request; hidden tests from the pull request grade the agent's fix. This repository
holds the task data, environment Dockerfiles, evaluator, log parsers and the prompts used to build the benchmark.

- Paper: https://arxiv.org/abs/2611.10304
- Harbor (hard): https://hub.harborframework.com/datasets/longtail-swe/longtail-swe
- Harbor (easy): https://hub.harborframework.com/datasets/longtail-swe/longtail-swe-easy
- Hugging Face: https://huggingface.co/datasets/nebius/Longtail-SWE
- GitHub: https://github.com/SWE-rebench/LongTail-SWE

| Split | Tasks | Languages | File |
| --- | ---: | ---: | --- |
| hard (the benchmark) | 202 | 13 | `data/longtail_tasks.json` |
| easy (companion set) | 269 | 13 | `data/longtail_easy_tasks.json` |

## Run with Harbor

Each Harbor task ships a prebuilt image pinned by digest, the instruction, hidden tests and a grader;
reward 1 means every FAIL_TO_PASS and PASS_TO_PASS test passes.

```bash
# reference solution (oracle) on two tasks
harbor run -d longtail-swe/longtail-swe@latest -a oracle -i '*askonomm__dompa-16' -i '*tg123__myslot-116'
# your agent on the full hard split (easy: longtail-swe/longtail-swe-easy@latest)
harbor run -d longtail-swe/longtail-swe@latest -a <agent> -m <model> -n 8
```

## Data

| Path | Content |
| --- | --- |
| `data/longtail_tasks.json`, `data/longtail_easy_tasks.json` | Task records (schema below). |
| `data/excluded_tasks.json` | Excluded tasks with reasons. |
| `data/release_manifest.json` | Task IDs, counts and file hashes. |
| `data/selected_results_202.jsonl`, `data/results_202.*`, `data/annotations_202.json`, `data/paper_tables_202.json` | Saved model results (8 models × 3 attempts × 202 tasks) and paper annotations. |
| `base_images.yaml`, `base_dockerfiles/`, `combine.Dockerfile.j2` | Environment images: base images and the per-task template. |
| `scripts/`, `lib/`, `prompts/`, `longtail/`, `configs/` | Image builders, evaluator, 22 log parsers; auditor/solver/judge/repairer prompts, schemas, model settings. |

Task fields: `instance_id`, `repo`, `base_commit`, `created_at`, `language`, `license`, `pr_url`;
`problem_statement` (what the agent sees: `problem_statement_base` plus an optional
`### Additional contract requirements` section holding `contract_addendum`); `patch` (reference solution) and
`test_patch` (hidden tests), which must not be shown to the agent; `FAIL_TO_PASS` and `PASS_TO_PASS`;
`install_config` (`base_image_name`, `install`, `test_cmd`, `log_parser`).

## Build and evaluate locally

Requires Docker, Git and Python 3.11+. Building every image needs much disk space and network access.

```bash
pip install -r requirements.txt
python scripts/build_base_images.py --language Clojure   # no flag: all languages
python scripts/build_instance_images.py --instance-ids askonomm__dompa-16
python scripts/eval.py --golden-eval --instance-ids askonomm__dompa-16
pytest tests                                              # offline data consistency checks
```

Scripts default to the hard split (`--json data/longtail_easy_tasks.json` for easy); `--patches patches.json`
grades your own patches. Some base Dockerfiles are reconstructed (`base_images.yaml`); the Harbor images are the validated ones.

## Changes in v1.1

- Hard: grading fixes for 5 tasks (test names, two test commands, a dead download URL, and a one-line hidden-test
  edit in `scottarbeit__grace-136`, whose FAIL_TO_PASS tests passed without any fix). With them the reference
  patch passes and an empty patch fails on all 202 tasks.
- Easy: 99 tasks got repaired hidden tests or test lists; 27 tasks were excluded (296 → 269).
- Saved model results were not regraded. Details per task: [CHANGES_v1.1.md](CHANGES_v1.1.md).

## License

Code, Dockerfiles and prompts: MIT (`LICENSE`); original dataset contributions: CC BY 4.0 (`LICENSE-CC-BY-4.0.txt`).
Third-party material (issues, patches, tests) keeps its source repository's license (`data/LICENSE.md`).

## Citation

Paper: [Longtail-SWE: High-Quality SWE Tasks for Underrepresented Languages](https://arxiv.org/abs/2611.10304)

```bibtex
@misc{dobrovolskii2026longtailswe,
  title         = {Longtail-SWE: High-Quality SWE Tasks for Underrepresented Languages},
  author        = {Dobrovolskii, Vladimir and Badertdinov, Ibragim and Golubev, Alexander},
  year          = {2026},
  eprint        = {2611.10304},
  archivePrefix = {arXiv},
  primaryClass  = {cs.SE},
  url           = {https://arxiv.org/abs/2611.10304}
}
```
