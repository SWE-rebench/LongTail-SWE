from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from unidiff import PatchSet

from .schemas import (
    JUDGE_OUTPUT_FILENAME,
    REPAIR_OUTPUT_FILENAMES,
    JudgeVerdict,
    RepairError,
    RepairSubmission,
)


def extract_judge_verdict(
    value: str,
    expected_instance_id: str | None = None,
    expected_revision: int | None = None,
) -> JudgeVerdict:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise RepairError("judge output must be a JSON object") from error
    if not isinstance(payload, dict):
        raise RepairError("judge output must be a JSON object")
    try:
        verdict = JudgeVerdict.model_validate(payload)
    except ValidationError as error:
        raise RepairError(
            f"judge verdict failed validation: {error}"
        ) from error
    if expected_instance_id is not None and verdict.instance_id != expected_instance_id:
        raise RepairError("judge output has an unexpected instance_id")
    if expected_revision is not None and verdict.revision != expected_revision:
        raise RepairError("judge output has an unexpected revision")
    return verdict


def extract_judge_verdict_from_messages(
    messages: list[dict[str, Any]],
    expected_instance_id: str | None = None,
    expected_revision: int | None = None,
) -> JudgeVerdict:
    for message in reversed(messages):
        patch = message.get("patch")
        if isinstance(patch, str) and patch:
            return extract_judge_verdict_from_patch(
                patch,
                expected_instance_id=expected_instance_id,
                expected_revision=expected_revision,
            )
        for key in ("content", "output"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return extract_judge_verdict(
                    value,
                    expected_instance_id=expected_instance_id,
                    expected_revision=expected_revision,
                )
    raise RepairError("judge trajectory has no textual verdict")


def extract_judge_verdict_from_patch(
    patch: str,
    expected_instance_id: str | None = None,
    expected_revision: int | None = None,
) -> JudgeVerdict:
    preamble, blocks = _split_git_patch(patch)
    if preamble.strip() or len(blocks) != 1:
        raise RepairError(
            f"judge patch must add exactly {JUDGE_OUTPUT_FILENAME}"
        )
    block = blocks[0]
    first_line = block.splitlines()[0]
    expected_header = f"diff --git a/{JUDGE_OUTPUT_FILENAME} b/{JUDGE_OUTPUT_FILENAME}"
    if first_line != expected_header:
        raise RepairError(
            f"judge patch must add exactly {JUDGE_OUTPUT_FILENAME}"
        )
    verdict_json = _extract_added_file(block, JUDGE_OUTPUT_FILENAME)
    return extract_judge_verdict(
        verdict_json,
        expected_instance_id=expected_instance_id,
        expected_revision=expected_revision,
    )


def extract_repair_submission_from_directory(path: Path) -> RepairSubmission:
    entries = {entry.name: entry for entry in path.iterdir()}
    if set(entries) != REPAIR_OUTPUT_FILENAMES or not all(
        entry.is_file() for entry in entries.values()
    ):
        raise RepairError(
            "repair directory must contain exactly the two required output files"
        )
    try:
        submission = RepairSubmission(
            test_patch=entries["test_patch.patch"].read_bytes().decode("utf-8"),
            contract_addendum=(
                entries["contract_addendum.md"].read_bytes().decode("utf-8")
            ),
        )
    except (UnicodeDecodeError, ValidationError) as error:
        raise RepairError(
            "repair directory payload failed validation"
        ) from error
    return submission


def extract_repair_submission_from_messages(
    messages: list[dict[str, Any]],
) -> RepairSubmission:
    for message in reversed(messages):
        patch = message.get("patch")
        if isinstance(patch, str) and patch:
            return extract_repair_submission_from_patch(patch)
    raise RepairError("repair trajectory has no submitted patch")


def extract_repair_submission_from_patch(patch: str) -> RepairSubmission:
    preamble, blocks = _split_git_patch(patch)
    if preamble.strip():
        raise RepairError("repair patch cannot contain a preamble")
    files: dict[str, str] = {}
    for block in blocks:
        first_line = block.splitlines()[0]
        match = re.fullmatch(r"diff --git a/([^ ]+) b/([^ ]+)", first_line)
        if match is None or match.group(1) != match.group(2):
            raise RepairError("repair patch has an invalid file header")
        filename = match.group(1)
        if filename not in REPAIR_OUTPUT_FILENAMES or filename in files:
            raise RepairError(
                "repair patch must add exactly the two required output files"
            )
        files[filename] = _extract_added_file(block, filename)
    if set(files) != REPAIR_OUTPUT_FILENAMES:
        raise RepairError(
            "repair patch must add exactly the two required output files"
        )
    try:
        submission = RepairSubmission(
            test_patch=files["test_patch.patch"],
            contract_addendum=files["contract_addendum.md"],
        )
    except ValidationError as error:
        raise RepairError(
            "repair patch payload failed validation"
        ) from error
    return submission


def _split_git_patch(patch: str) -> tuple[str, list[str]]:
    parts = re.split(r"(?m)(?=^diff --git )", patch)
    if len(parts) == 1:
        raise RepairError("repair output is not a Git patch")
    return parts[0], parts[1:]


def _extract_added_file(block: str, filename: str) -> str:
    try:
        patch_set = PatchSet.from_string(block)
    except Exception as error:
        raise RepairError("repair output is malformed") from error
    if len(patch_set) == 1 and patch_set[0].is_added_file:
        if str(patch_set[0].path) != filename:
            raise RepairError("repair output file path changed")
        return _added_file_content(patch_set[0])
    if filename == "contract_addendum.md" and _is_explicit_empty_file(block, filename):
        return ""
    raise RepairError("repair output files must be newly added files")


def _is_explicit_empty_file(block: str, filename: str) -> bool:
    lines = block.splitlines()
    if len(lines) not in {3, 5}:
        return False
    if lines[:2] != [
        f"diff --git a/{filename} b/{filename}",
        "new file mode 100644",
    ]:
        return False
    index_match = re.fullmatch(r"index (0{7,64})\.\.([0-9a-f]{7,64})", lines[2])
    if index_match is None:
        return False
    source_object_id, destination_object_id = index_match.groups()
    if len(source_object_id) != len(destination_object_id):
        return False
    if destination_object_id == "0" * len(destination_object_id):
        return False
    return lines[3:] in ([], ["--- /dev/null", f"+++ b/{filename}"])


def _added_file_content(patched_file: Any) -> str:
    content_lines: list[str] = []
    for hunk in patched_file:
        for line in hunk:
            if line.is_added:
                content_lines.append(line.value)
            elif (
                line.line_type == "\\"
                and line.value.rstrip("\r\n") == " No newline at end of file"
                and content_lines
            ):
                content_lines[-1] = content_lines[-1].removesuffix("\r\n")
                content_lines[-1] = content_lines[-1].removesuffix("\n")
                content_lines[-1] = content_lines[-1].removesuffix("\r")
    return "".join(content_lines)
