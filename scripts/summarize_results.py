#!/usr/bin/env python3
"""Validate and aggregate the declared saved-result ledger; never execute tasks."""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_rows(rows, tasks):
    ids = {t["instance_id"] for t in tasks}
    models = {r["model"] for r in rows}
    if len(ids) != 202 or len(models) != 8 or len(rows) != 4848:
        raise ValueError("Expected 202 tasks, eight models and 4,848 selected outcomes")
    expected = {(m, run, iid) for m in models for run in range(3) for iid in ids}
    keys = [(r["model"], r["run"], r["instance_id"]) for r in rows]
    if len(set(keys)) != len(keys) or set(keys) != expected:
        raise ValueError("Duplicate, missing or unexpected attempt keys")
    for r in rows:
        if type(r["resolved"]) is not bool or type(r["run"]) is not int:
            raise ValueError("Outcomes must be Boolean and run indices must be integers")
        if r["cohort"] not in {"original", "statement_rerun"}:
            raise ValueError("Supplementary attempts must not enter the primary denominator")
    reruns = {(r["model"], r["run"]): set() for r in rows}
    for r in rows:
        if r["cohort"] == "statement_rerun":
            reruns[r["model"], r["run"]].add(r["instance_id"])
    if any(len(v) != 32 for v in reruns.values()) or len({tuple(sorted(v)) for v in reruns.values()}) != 1:
        raise ValueError("The same 32 statement-rerun tasks are required in every model/run")


def aggregate(rows, tasks):
    language = {t["instance_id"]: t["language"] for t in tasks}
    groups = collections.defaultdict(list)
    for r in rows:
        groups[r["model"], "ALL"].append(r)
        groups[r["model"], language[r["instance_id"]]].append(r)
    out = []
    for (model, lang), subset in sorted(groups.items()):
        by_task = collections.defaultdict(list)
        successes = collections.Counter()
        for r in subset:
            by_task[r["instance_id"]].append(r["resolved"])
            successes[r["run"]] += r["resolved"]
        n = len(by_task)
        if any(len(v) != 3 for v in by_task.values()):
            raise ValueError("Each task needs exactly three attempts")
        rates = [successes[i] / n * 100 for i in range(3)]
        out.append(dict(model=model, language=lang, tasks=n, attempts=len(subset),
                        resolved_attempts=sum(successes.values()), pass_at_1=statistics.mean(rates),
                        pass_at_1_sem=statistics.stdev(rates) / math.sqrt(3),
                        pass_at_3=sum(any(v) for v in by_task.values()) / n * 100,
                        all_3=sum(all(v) for v in by_task.values()) / n * 100,
                        **{f"run_{i}_resolved": successes[i] for i in range(3)}))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=ROOT / "data/selected_results_202.jsonl")
    parser.add_argument("--tasks", type=Path, default=ROOT / "data/longtail_tasks.json")
    parser.add_argument("--output", type=Path, help="Write overall and per-language CSV; otherwise print JSON")
    args = parser.parse_args()
    tasks = json.loads(args.tasks.read_text(encoding="utf-8"))
    rows = load_rows(args.ledger)
    validate_rows(rows, tasks)
    metrics = aggregate(rows, tasks)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(metrics[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(metrics)
    else:
        print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
