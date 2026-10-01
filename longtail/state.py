from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from unidiff import PatchSet

from .schemas import (
    CONTRACT_ADDENDUM_HEADING,
    MAX_REPAIR_CYCLES,
    GoldenPatchValidityEvidence,
    ImmutableTaskHashes,
    InvalidRepairError,
    JudgeVerdict,
    TaskInput,
    RepairError,
    ModelAttempt,
    NoOpRepairError,
    RepairMode,
    RepairSubmission,
    RowRepairState,
    StateManifest,
    TaskRevision,
    TerminalReason,
    VerdictRoutingResult,
)


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def hash_json(value: Any) -> str:
    return hash_text(canonical_json(value))


def render_effective_problem_statement(
    base_problem_statement: str,
    contract_addendum: str,
) -> str:
    if not contract_addendum:
        return base_problem_statement
    if CONTRACT_ADDENDUM_HEADING in contract_addendum:
        raise ValueError("contract addendum must not include its rendered heading")
    if base_problem_statement.endswith("\n\n"):
        separator = ""
    elif base_problem_statement.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    return (
        f"{base_problem_statement}{separator}{CONTRACT_ADDENDUM_HEADING}\n\n"
        f"{contract_addendum}"
    )


def validate_task_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise ValueError("task dataset must contain at least one row")
    validated_rows = []
    instance_ids = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"task row at index {index} must be an object")
        validated = TaskInput.model_validate(row)
        validated_rows.append(copy.deepcopy(row))
        instance_ids.append(validated.instance_id)
    seen: set[str] = set()
    duplicates: set[str] = set()
    for instance_id in instance_ids:
        if instance_id in seen:
            duplicates.add(instance_id)
        seen.add(instance_id)
    if duplicates:
        raise ValueError(f"duplicate instance_id values: {sorted(duplicates)}")
    return validated_rows


def initialize_state_manifest(
    rows: list[dict[str, Any]],
    root_run_id: str,
) -> StateManifest:
    validated_rows = validate_task_rows(rows)
    states = [initialize_row_state(row) for row in validated_rows]
    manifest = StateManifest(root_run_id=root_run_id, round_index=0, rows=states)
    assert_manifest_integrity(manifest)
    return manifest


def initialize_row_state(row: dict[str, Any]) -> RowRepairState:
    validated = TaskInput.model_validate(row)
    original_task = copy.deepcopy(row)
    immutable_hashes = _immutable_hashes(original_task)
    revision = _build_revision(
        original_task=original_task,
        revision=0,
        test_patch=validated.test_patch,
        contract_addendum="",
        fail_to_pass=validated.FAIL_TO_PASS,
        pass_to_pass=validated.PASS_TO_PASS,
    )
    state = RowRepairState(
        instance_id=validated.instance_id,
        original_task=original_task,
        immutable_hashes=immutable_hashes,
        current_revision=revision,
        repair_cycles=0,
        needs_solver=True,
        evaluated=False,
        model_attempts=[],
        convergence_status="active",
    )
    assert_state_integrity(state)
    return state


def materialize_task(state: RowRepairState) -> dict[str, Any]:
    assert_state_integrity(state)
    task = _materialize_task(
        original_task=state.original_task,
        test_patch=state.current_revision.test_patch,
        effective_problem_statement=(
            state.current_revision.effective_problem_statement
        ),
        fail_to_pass=state.current_revision.fail_to_pass,
        pass_to_pass=state.current_revision.pass_to_pass,
    )
    if hash_json(task["install_config"]) != state.immutable_hashes.install_config:
        raise RepairError("install_config changed while rendering task")
    return task


def mark_revision_evaluated(
    state: RowRepairState,
    model_attempts: list[ModelAttempt],
) -> RowRepairState:
    assert_state_integrity(state)
    if state.convergence_status != "active":
        raise RepairError("only active rows can be evaluated")
    sorted_attempts = sorted(model_attempts, key=lambda attempt: attempt.run_index)
    if state.evaluated:
        if sorted_attempts == state.model_attempts:
            return state
        raise RepairError(
            "evaluated revision cannot be replaced with different model attempts"
        )
    if not sorted_attempts:
        raise RepairError(
            "an evaluated revision must record at least one model attempt"
        )
    if state.needs_solver and any(
        attempt.generated_revision != state.current_revision.revision
        for attempt in sorted_attempts
    ):
        raise RepairError(
            "new solver attempts must come from the current revision"
        )
    if not state.needs_solver and sorted_attempts != state.model_attempts:
        raise RepairError(
            "test-only revisions must reuse their stored model attempts"
        )
    updated = _replace_state(
        state,
        evaluated=True,
        needs_solver=False,
        model_attempts=sorted_attempts,
    )
    assert_state_integrity(updated)
    return updated


def route_judge_verdict(
    state: RowRepairState,
    verdict: JudgeVerdict,
    max_repair_cycles: int = 5,
    repair_mode: RepairMode = "test_and_addendum",
) -> VerdictRoutingResult:
    assert_state_integrity(state)
    if not 0 <= max_repair_cycles <= MAX_REPAIR_CYCLES:
        raise ValueError(
            f"max_repair_cycles must be between zero and {MAX_REPAIR_CYCLES}"
        )
    if not state.evaluated or state.convergence_status != "active":
        raise RepairError("judge verdict requires an active evaluation")
    if verdict.instance_id != state.instance_id:
        raise RepairError("verdict instance_id does not match row state")
    if verdict.revision != state.current_revision.revision:
        raise RepairError("verdict revision does not match row state")
    if verdict.decision == "accept":
        return VerdictRoutingResult(
            state=_freeze_state(state, "converged", "accepted"),
            invoke_repairer=False,
        )
    if verdict.decision == "manual_review":
        return VerdictRoutingResult(
            state=_freeze_state(state, "nonconverged", "manual_review"),
            invoke_repairer=False,
        )
    if (
        repair_mode == "test_patch_only"
        and "contract_addendum" in verdict.repair_targets
    ):
        return VerdictRoutingResult(
            state=_freeze_state(
                state,
                "nonconverged",
                "contract_change_out_of_scope",
            ),
            invoke_repairer=False,
        )
    repair_cycle_limit = (
        state.repair_cycle_limit
        if state.repair_cycle_limit is not None
        else max_repair_cycles
    )
    if state.repair_cycles >= repair_cycle_limit:
        return VerdictRoutingResult(
            state=_freeze_state(state, "nonconverged", "max_repair_cycles"),
            invoke_repairer=False,
        )
    return VerdictRoutingResult(state=state, invoke_repairer=True)


def apply_validated_repair(
    state: RowRepairState,
    submission: RepairSubmission,
    verdict: JudgeVerdict,
    validity_evidence: GoldenPatchValidityEvidence | None = None,
    max_repair_cycles: int = 5,
    repair_mode: RepairMode = "test_and_addendum",
) -> RowRepairState:
    assert_state_integrity(state)
    route = route_judge_verdict(
        state,
        verdict,
        max_repair_cycles,
        repair_mode,
    )
    if not route.invoke_repairer:
        raise InvalidRepairError("verdict does not permit another repair")

    current = state.current_revision
    test_changed = hash_text(submission.test_patch) != current.test_patch_hash
    addendum_changed = (
        hash_text(submission.contract_addendum) != current.contract_addendum_hash
    )
    if repair_mode == "test_patch_only" and addendum_changed:
        raise InvalidRepairError(
            "contract_addendum is immutable in test_patch_only mode; "
            f"expected_hash={current.contract_addendum_hash} "
            f"submitted_hash={hash_text(submission.contract_addendum)}"
        )
    if not test_changed and not addendum_changed:
        raise NoOpRepairError("repair is hash-identical to the evaluated revision")

    fail_to_pass = current.fail_to_pass
    pass_to_pass = current.pass_to_pass
    if test_changed:
        validate_repair_test_patch_scope(current.test_patch, submission.test_patch)
        if validity_evidence is None:
            raise InvalidRepairError(
                "test changes require golden-patch validity evidence"
            )
        _validate_validity_evidence(state, submission, validity_evidence)
        fail_to_pass = validity_evidence.fail_to_pass
        pass_to_pass = validity_evidence.pass_to_pass
    elif validity_evidence is not None:
        raise InvalidRepairError(
            "golden-patch validity evidence is only valid for test changes"
        )

    next_revision = _build_revision(
        original_task=state.original_task,
        revision=current.revision + 1,
        test_patch=submission.test_patch,
        contract_addendum=submission.contract_addendum,
        fail_to_pass=fail_to_pass,
        pass_to_pass=pass_to_pass,
    )
    updated = _replace_state(
        state,
        current_revision=next_revision,
        repair_cycles=state.repair_cycles + 1,
        needs_solver=addendum_changed,
        evaluated=False,
        model_attempts=[] if addendum_changed else state.model_attempts,
    )
    assert_state_integrity(updated)
    return updated


def terminate_nonconverged(
    state: RowRepairState,
    reason: Literal[
        "repair_agent_failed",
        "repair_extraction_failed",
        "invalid_repair",
        "invalid_validity_evidence",
        "hash_identical_repair",
        "judge_extraction_failed",
        "contract_change_out_of_scope",
    ],
) -> RowRepairState:
    assert_state_integrity(state)
    if not state.evaluated or state.convergence_status != "active":
        raise RepairError(
            "only an active evaluated revision can terminate"
        )
    return _freeze_state(state, "nonconverged", reason)


def validate_repair_test_patch_scope(
    original_test_patch: str,
    replacement_test_patch: str,
) -> None:
    original_paths = _patch_paths(original_test_patch)
    replacement_paths = _patch_paths(replacement_test_patch)
    new_paths = replacement_paths - original_paths
    disallowed_paths = sorted(
        path for path in new_paths if not _is_test_support_path(path)
    )
    if disallowed_paths:
        raise InvalidRepairError(
            "test_patch introduces non-test paths: " + ", ".join(disallowed_paths)
        )
    unsupported_paths = sorted(
        path
        for path in new_paths
        if PurePosixPath(path).suffix.lower() in {".md", ".rst", ".txt"}
    )
    if unsupported_paths:
        raise InvalidRepairError(
            "test_patch introduces paths that the configured evaluator cannot "
            "clean up safely: " + ", ".join(unsupported_paths)
        )


def create_next_round_manifest(
    manifest: StateManifest,
    rows: list[RowRepairState],
) -> StateManifest:
    assert_manifest_integrity(manifest)
    previous_instance_ids = [row.instance_id for row in manifest.rows]
    next_instance_ids = [row.instance_id for row in rows]
    if next_instance_ids != previous_instance_ids:
        raise RepairError(
            "next-round manifest must preserve every row in its original order"
        )
    previous_rows = {row.instance_id: row for row in manifest.rows}
    next_rows = {row.instance_id: row for row in rows}
    for instance_id, row in next_rows.items():
        previous = previous_rows[instance_id]
        if previous.convergence_status != "active" and row != previous:
            raise RepairError("terminal row state cannot change")
        if (
            row.original_task != previous.original_task
            or row.immutable_hashes != previous.immutable_hashes
        ):
            raise RepairError("immutable row state cannot change")
        revision_delta = (
            row.current_revision.revision - previous.current_revision.revision
        )
        if revision_delta not in {0, 1}:
            raise RepairError(
                "a row revision must stay current or advance exactly once"
            )
        if row.convergence_status == "active" and (
            row.evaluated or revision_delta != 1
        ):
            raise RepairError(
                "next-round active rows must be new unevaluated revisions"
            )
    if not any(row.convergence_status == "active" for row in rows):
        raise RepairError(
            "next-round manifest requires at least one repaired active row"
        )
    next_manifest = StateManifest(
        root_run_id=manifest.root_run_id,
        round_index=manifest.round_index + 1,
        rows=rows,
    )
    assert_manifest_integrity(next_manifest)
    return next_manifest


def create_extension_manifest(
    manifest: StateManifest,
    max_repair_cycles: int,
    instance_ids: list[str] | None = None,
    include_manual_review: bool = False,
) -> StateManifest:
    assert_manifest_integrity(manifest)
    if not 0 <= max_repair_cycles <= MAX_REPAIR_CYCLES:
        raise ValueError(
            f"max_repair_cycles must be between zero and {MAX_REPAIR_CYCLES}"
        )
    if any(row.convergence_status == "active" for row in manifest.rows):
        raise RepairError(
            "only a terminal state manifest can be extended"
        )

    requested_ids = list(instance_ids or [])
    if len(requested_ids) != len(set(requested_ids)):
        raise ValueError("extension instance_ids must be unique")
    rows_by_id = {row.instance_id: row for row in manifest.rows}
    unknown_ids = sorted(set(requested_ids) - rows_by_id.keys())
    if unknown_ids:
        raise RepairError(
            "extension instance_ids are missing from the manifest: "
            + ", ".join(unknown_ids)
        )

    if requested_ids:
        selected_rows = [rows_by_id[instance_id] for instance_id in requested_ids]
    else:
        selected_rows = [
            row
            for row in manifest.rows
            if row.convergence_status == "nonconverged"
            and row.terminal_reason != "manual_review"
        ]
    for row in selected_rows:
        if row.convergence_status != "nonconverged":
            raise RepairError(
                f"extension row is not nonconverged: {row.instance_id}"
            )
        if row.terminal_reason == "manual_review" and not include_manual_review:
            raise RepairError(
                "manual-review rows require include_manual_review=true: "
                f"{row.instance_id}"
            )
        if row.repair_cycles >= max_repair_cycles:
            raise RepairError(
                "max_repair_cycles must exceed the current repair cycle for "
                f"{row.instance_id}: {row.repair_cycles}"
            )
    if not selected_rows:
        raise RepairError(
            "extension selected no eligible nonconverged rows"
        )

    selected_ids = {row.instance_id for row in selected_rows}
    extended_rows = [
        _replace_state(
            row,
            convergence_status="active",
            terminal_reason=None,
            repair_cycle_limit=(
                max_repair_cycles
                if row.repair_cycle_limit is not None
                else row.repair_cycle_limit
            ),
        )
        if row.instance_id in selected_ids
        else row
        for row in manifest.rows
    ]
    extended_manifest = StateManifest(
        root_run_id=manifest.root_run_id,
        round_index=manifest.round_index + 1,
        rows=extended_rows,
    )
    assert_manifest_integrity(extended_manifest)
    return extended_manifest


def continuation_run_id(root_run_id: str, round_index: int) -> str:
    if not root_run_id.strip():
        raise ValueError("root_run_id must contain non-whitespace text")
    if round_index < 1:
        raise ValueError("continuation round_index must be at least one")
    return f"{root_run_id}_round-{round_index}"


def write_state_manifest(path: Path, manifest: StateManifest) -> None:
    assert_manifest_integrity(manifest)
    manifest_payload = manifest.model_dump(mode="json")
    for row in manifest_payload["rows"]:
        if row["repair_cycle_limit"] is None:
            del row["repair_cycle_limit"]
    payload = (
        json.dumps(
            manifest_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = payload.encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as output_file:
            temporary_path = Path(output_file.name)
            output_file.write(encoded)
            output_file.flush()
            os.fsync(output_file.fileno())
        temporary_path.chmod(0o644)
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            if path.read_bytes() != encoded:
                raise FileExistsError(
                    f"refusing to replace immutable manifest {path}"
                ) from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_state_manifest(path: Path) -> StateManifest:
    manifest = StateManifest.model_validate_json(path.read_bytes())
    assert_manifest_integrity(manifest)
    return manifest


def assert_manifest_integrity(manifest: StateManifest) -> None:
    for state in manifest.rows:
        assert_state_integrity(state)


def assert_state_integrity(state: RowRepairState) -> None:
    validated = TaskInput.model_validate(state.original_task)
    if validated.instance_id != state.instance_id:
        raise RepairError("state instance_id changed from original task")
    expected_immutable_hashes = _immutable_hashes(state.original_task)
    if expected_immutable_hashes != state.immutable_hashes:
        raise RepairError(
            "immutable task content does not match its hashes"
        )
    current = state.current_revision
    expected_revision = _build_revision(
        original_task=state.original_task,
        revision=current.revision,
        test_patch=current.test_patch,
        contract_addendum=current.contract_addendum,
        fail_to_pass=current.fail_to_pass,
        pass_to_pass=current.pass_to_pass,
    )
    if expected_revision != current:
        raise RepairError(
            "current revision content does not match its hashes"
        )


def _immutable_hashes(original_task: dict[str, Any]) -> ImmutableTaskHashes:
    return ImmutableTaskHashes(
        original_task=hash_json(original_task),
        base_problem_statement=hash_text(original_task["problem_statement"]),
        install_config=hash_json(original_task["install_config"]),
        golden_patch=hash_text(original_task["patch"]),
    )


def _build_revision(
    original_task: dict[str, Any],
    revision: int,
    test_patch: str,
    contract_addendum: str,
    fail_to_pass: list[str],
    pass_to_pass: list[str],
) -> TaskRevision:
    effective_statement = render_effective_problem_statement(
        original_task["problem_statement"], contract_addendum
    )
    task = _materialize_task(
        original_task=original_task,
        test_patch=test_patch,
        effective_problem_statement=effective_statement,
        fail_to_pass=fail_to_pass,
        pass_to_pass=pass_to_pass,
    )
    test_patch_hash = hash_text(test_patch)
    contract_addendum_hash = hash_text(contract_addendum)
    effective_problem_statement_hash = hash_text(effective_statement)
    task_hash = hash_json(task)
    revision_hash = hash_json(
        {
            "instance_id": original_task["instance_id"],
            "revision": revision,
            "test_patch_hash": test_patch_hash,
            "contract_addendum_hash": contract_addendum_hash,
            "effective_problem_statement_hash": (effective_problem_statement_hash),
            "task_hash": task_hash,
        }
    )
    return TaskRevision(
        revision=revision,
        test_patch=test_patch,
        contract_addendum=contract_addendum,
        effective_problem_statement=effective_statement,
        fail_to_pass=list(fail_to_pass),
        pass_to_pass=list(pass_to_pass),
        test_patch_hash=test_patch_hash,
        contract_addendum_hash=contract_addendum_hash,
        effective_problem_statement_hash=effective_problem_statement_hash,
        task_hash=task_hash,
        revision_hash=revision_hash,
    )


def _materialize_task(
    original_task: dict[str, Any],
    test_patch: str,
    effective_problem_statement: str,
    fail_to_pass: list[str],
    pass_to_pass: list[str],
) -> dict[str, Any]:
    task = copy.deepcopy(original_task)
    task["test_patch"] = test_patch
    task["problem_statement"] = effective_problem_statement
    task["FAIL_TO_PASS"] = list(fail_to_pass)
    task["PASS_TO_PASS"] = list(pass_to_pass)
    return task


def _validate_validity_evidence(
    state: RowRepairState,
    submission: RepairSubmission,
    evidence: GoldenPatchValidityEvidence,
) -> None:
    if evidence.instance_id != state.instance_id:
        raise InvalidRepairError("validity evidence instance_id does not match")
    if evidence.source_revision != state.current_revision.revision:
        raise InvalidRepairError("validity evidence source revision does not match")
    if evidence.test_patch_hash != hash_text(submission.test_patch):
        raise InvalidRepairError("validity evidence test patch hash does not match")
    if not evidence.is_valid():
        raise InvalidRepairError("golden-patch validity evidence is insufficient")


def _replace_state(state: RowRepairState, **updates: Any) -> RowRepairState:
    return RowRepairState.model_validate(state.model_dump() | updates)


def _freeze_state(
    state: RowRepairState,
    convergence_status: Literal["converged", "nonconverged"],
    terminal_reason: TerminalReason,
) -> RowRepairState:
    frozen = _replace_state(
        state,
        needs_solver=False,
        convergence_status=convergence_status,
        terminal_reason=terminal_reason,
    )
    assert_state_integrity(frozen)
    return frozen


def _patch_paths(patch: str) -> set[str]:
    try:
        patch_set = PatchSet.from_string(patch)
    except Exception as error:
        raise InvalidRepairError("test_patch is malformed") from error
    paths = set()
    for patched_file in patch_set:
        for raw_path in (patched_file.source_file, patched_file.target_file):
            if raw_path == "/dev/null":
                continue
            path = raw_path[2:] if raw_path.startswith(("a/", "b/")) else raw_path
            parsed = PurePosixPath(path)
            if parsed.is_absolute() or ".." in parsed.parts:
                raise InvalidRepairError(f"test_patch contains an unsafe path: {path}")
            paths.add(path)
    return paths


def _is_test_support_path(path: str) -> bool:
    parsed = PurePosixPath(path)
    lowered_parts = tuple(part.lower() for part in parsed.parts)
    test_directory_tokens = {
        "e2e",
        "fixture",
        "fixtures",
        "spec",
        "specs",
        "test",
        "testing",
        "tests",
    }
    if any(
        test_directory_tokens.intersection(filter(None, re.split(r"[^a-z0-9]+", part)))
        for part in lowered_parts[:-1]
    ):
        return True
    name = parsed.name.lower()
    stem = parsed.stem.lower()
    return (
        name in {"conftest.py", "pytest.ini", "tox.ini"}
        or stem.startswith("test_")
        or stem.endswith("_test")
        or ".test." in name
        or ".spec." in name
    )
