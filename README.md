# Longtail-SWE

Longtail-SWE is a benchmark of real GitHub issues in 13 underrepresented languages: Clojure, Dart, Elixir, Erlang, F#,
Haskell, Julia, Kotlin, Lua, OCaml, R, Scala and Swift. Each task asks an agent to resolve an issue. A task counts as
solved only if every FAIL_TO_PASS and PASS_TO_PASS test from the merged pull request that fixed the issue passes.

[Harbor hard](https://hub.harborframework.com/datasets/longtail-swe/longtail-swe) · [Harbor easy](https://hub.harborframework.com/datasets/longtail-swe/longtail-swe-easy) ·
[Hugging Face](https://huggingface.co/datasets/nebius/Longtail-SWE) · [Paper (arXiv)](https://arxiv.org/abs/2611.10304)

| Split | Tasks | Languages | Harbor dataset | File |
| --- | ---: | ---: | --- | --- |
| hard (the benchmark) | 202 | 13 | `longtail-swe/longtail-swe` | `data/longtail_tasks.json` |
| easy (companion set) | 269 | 13 | `longtail-swe/longtail-swe-easy` | `data/longtail_easy_tasks.json` |

## Quick start (Harbor)

```bash
harbor run -d longtail-swe/longtail-swe@latest -a oracle -i '*askonomm__dompa-16'   # reference solution
harbor run -d longtail-swe/longtail-swe@latest -a <agent> -m <model> -n 8          # full hard split
```

## What is where

| Path | Content |
| --- | --- |
| `data/` | Task records for both splits; `excluded_tasks.json` lists removed task IDs. |
| `base_images.yaml`, `base_dockerfiles/`, `combine.Dockerfile.j2` | Base images and the per-task Dockerfile template. |
| `scripts/`, `lib/`, `prompts/solver/` | Image builders, local evaluator (`scripts/eval.py`), log parsers, solver prompt. |
| `tests/` | Offline consistency checks (`pytest tests`). |

Local run without Harbor (needs Docker): `scripts/build_base_images.py`, then `scripts/build_instance_images.py` and
`scripts/eval.py --golden-eval` (or `--patches patches.json`); for easy, pass `--json data/longtail_easy_tasks.json` to both.

## Task fields

- `instance_id`, `repo`, `base_commit`, `created_at`, `language`, `license`, `pr_url`.
- `problem_statement`: what the agent sees. It is `problem_statement_base`, followed by `contract_addendum` under
  `### Additional contract requirements` when present.
- `patch` (reference solution) and `test_patch` (hidden tests): never show these to the agent.
- `FAIL_TO_PASS`, `PASS_TO_PASS`: the graded tests. `install_config`: `base_image_name`, `install`, `test_cmd`, `log_parser`.

## License

Code, Dockerfiles, templates and prompts: [MIT](LICENSE). Original dataset contributions (task selection, contract addenda,
repaired tests, install configs): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Issue text, patches and
original tests stay under the license of their source repository, recorded in each task's `license` field.

## Citation

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
