from __future__ import annotations

import re
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)
from unidiff import PatchSet


CONTRACT_ADDENDUM_HEADING = "### Additional contract requirements"
JUDGE_OUTPUT_FILENAME = "verdict.json"
REPAIR_OUTPUT_FILENAMES = frozenset({"test_patch.patch", "contract_addendum.md"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_REPAIR_CYCLES = 100

Decision = Literal["accept", "repair", "manual_review"]
RepairTarget = Literal["test_patch", "contract_addendum"]
RepairMode = Literal["test_and_addendum", "test_patch_only"]
TestPatchScopeClassification = Literal[
    "test_only",
    "test_support_only",
    "implementation_leakage",
    "uncertain",
]
ConvergenceStatus = Literal["active", "converged", "nonconverged"]
TerminalReason = Literal[
    "accepted",
    "manual_review",
    "max_repair_cycles",
    "repair_agent_failed",
    "repair_extraction_failed",
    "invalid_repair",
    "invalid_validity_evidence",
    "hash_identical_repair",
    "judge_extraction_failed",
    "contract_change_out_of_scope",
]


class RepairError(ValueError):
    pass


class InvalidRepairError(RepairError):
    pass


class NoOpRepairError(InvalidRepairError):
    pass


class InstallConfigInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    base_image_name: StrictStr
    test_cmd: StrictStr | list[StrictStr]

    @field_validator("base_image_name")
    @classmethod
    def validate_base_image_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("base_image_name must contain non-whitespace text")
        return value

    @field_validator("test_cmd")
    @classmethod
    def validate_test_cmd(cls, value: str | list[str]) -> str | list[str]:
        commands = [value] if isinstance(value, str) else value
        if not commands or any(not command.strip() for command in commands):
            raise ValueError("test_cmd must contain at least one nonempty command")
        return value


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    instance_id: StrictStr
    repo: StrictStr
    base_commit: StrictStr
    patch: StrictStr
    test_patch: StrictStr
    problem_statement: StrictStr
    install_config: InstallConfigInput
    FAIL_TO_PASS: list[StrictStr] = Field(default_factory=list)
    PASS_TO_PASS: list[StrictStr] = Field(default_factory=list)

    @field_validator("repo", "base_commit", "problem_statement")
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")
        return value

    @field_validator("instance_id")
    @classmethod
    def validate_instance_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instance_id must contain non-whitespace text")
        if value in {".", ".."} or any(character in value for character in "/\\\0"):
            raise ValueError("instance_id must be safe for artifact paths")
        return value

    @field_validator("patch", "test_patch")
    @classmethod
    def validate_patch(cls, value: str) -> str:
        if not is_nonempty_git_patch(value):
            raise ValueError("value must be a nonempty unified Git patch")
        return value

    @field_validator("FAIL_TO_PASS", "PASS_TO_PASS")
    @classmethod
    def validate_bucket(cls, value: list[str]) -> list[str]:
        if any(not test_name.strip() for test_name in value):
            raise ValueError("test bucket entries must contain non-whitespace text")
        if len(value) != len(set(value)):
            raise ValueError("test bucket entries must be unique")
        return value

    @model_validator(mode="after")
    def validate_disjoint_buckets(self) -> Self:
        overlap = set(self.FAIL_TO_PASS) & set(self.PASS_TO_PASS)
        if overlap:
            raise ValueError(f"test buckets overlap: {sorted(overlap)}")
        return self


class EvidenceBackedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: StrictStr
    evidence: list[StrictStr] = Field(min_length=1)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must contain non-whitespace text")
        return value

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("evidence must contain non-whitespace text")
        return value


class TestPatchScopeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: TestPatchScopeClassification
    reviewed_paths: list[StrictStr] = Field(min_length=1)
    evidence: list[StrictStr] = Field(min_length=1)

    @field_validator("reviewed_paths", "evidence")
    @classmethod
    def validate_nonempty_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError(
                "scope assessment entries must contain non-whitespace text"
            )
        if len(value) != len(set(value)):
            raise ValueError("scope assessment entries must be unique")
        return value


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: StrictStr
    revision: int = Field(ge=0, strict=True)
    fairness: Literal["fair", "unfair", "uncertain"]
    coverage_sufficiency: Literal["sufficient", "insufficient", "uncertain"]
    model_patch_assessment: StrictStr
    test_patch_scope_assessment: TestPatchScopeAssessment
    decision: Decision
    repair_targets: list[RepairTarget]
    findings: list[EvidenceBackedFinding] = Field(min_length=1)
    private_repair_feedback: StrictStr

    @field_validator("instance_id", "model_patch_assessment")
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")
        return value

    @field_validator("repair_targets")
    @classmethod
    def validate_unique_targets(cls, value: list[RepairTarget]) -> list[RepairTarget]:
        if len(value) != len(set(value)):
            raise ValueError("repair_targets must be unique")
        return value

    @model_validator(mode="after")
    def validate_decision_fields(self) -> Self:
        if self.decision == "repair":
            if not self.repair_targets:
                raise ValueError("repair requires at least one repair target")
            if not self.private_repair_feedback.strip():
                raise ValueError("repair requires private repair feedback")
        elif self.repair_targets or self.private_repair_feedback:
            raise ValueError(
                "non-repair verdicts cannot contain repair targets or private feedback"
            )
        if self.decision == "accept" and (
            self.fairness != "fair" or self.coverage_sufficiency != "sufficient"
        ):
            raise ValueError("accept requires fair and sufficient test coverage")
        if (
            self.decision == "accept"
            and self.test_patch_scope_assessment.classification
            in {"implementation_leakage", "uncertain"}
        ):
            raise ValueError("accept requires a safe test patch scope assessment")
        if (
            self.test_patch_scope_assessment.classification == "implementation_leakage"
            and (self.decision != "repair" or "test_patch" not in self.repair_targets)
        ):
            raise ValueError("implementation leakage requires repair of the test patch")
        return self


class RepairSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_patch: StrictStr
    contract_addendum: StrictStr

    @field_validator("test_patch")
    @classmethod
    def validate_test_patch(cls, value: str) -> str:
        if not is_nonempty_git_patch(value):
            raise ValueError("test_patch must be a nonempty unified Git patch")
        return value

    @field_validator("contract_addendum")
    @classmethod
    def validate_contract_addendum(cls, value: str) -> str:
        if value and not value.strip():
            raise ValueError("contract_addendum must be empty or contain text")
        if CONTRACT_ADDENDUM_HEADING in value:
            raise ValueError("contract_addendum must not include its rendered heading")
        return value


class GoldenPatchValidityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: StrictStr
    source_revision: int = Field(ge=0, strict=True)
    test_patch_hash: StrictStr
    intended_base_failure: StrictBool
    complete_golden_success: StrictBool
    fail_to_pass: list[StrictStr]
    pass_to_pass: list[StrictStr]
    fail_to_fail: list[StrictStr]
    pass_to_fail: list[StrictStr]
    evidence_path: StrictStr | None = None

    @field_validator("fail_to_pass", "pass_to_pass", "fail_to_fail", "pass_to_fail")
    @classmethod
    def validate_bucket(cls, value: list[str]) -> list[str]:
        if any(not test_name.strip() for test_name in value):
            raise ValueError("test bucket entries must contain non-whitespace text")
        if len(value) != len(set(value)):
            raise ValueError("test bucket entries must be unique")
        return value

    @field_validator("evidence_path")
    @classmethod
    def validate_evidence_path(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("evidence_path must contain non-whitespace text")
        return value

    @field_validator("test_patch_hash")
    @classmethod
    def validate_test_patch_hash(cls, value: str) -> str:
        if SHA256_RE.fullmatch(value) is None:
            raise ValueError("test_patch_hash must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_disjoint_buckets(self) -> Self:
        buckets = [
            self.fail_to_pass,
            self.pass_to_pass,
            self.fail_to_fail,
            self.pass_to_fail,
        ]
        seen: set[str] = set()
        for bucket in buckets:
            overlap = seen & set(bucket)
            if overlap:
                raise ValueError(
                    f"validity evidence buckets overlap: {sorted(overlap)}"
                )
            seen.update(bucket)
        return self

    def is_valid(self) -> bool:
        return (
            self.intended_base_failure
            and self.complete_golden_success
            and bool(self.fail_to_pass)
            and not self.fail_to_fail
            and not self.pass_to_fail
        )


class ImmutableTaskHashes(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original_task: str
    base_problem_statement: str
    install_config: str
    golden_patch: str

    @field_validator(
        "original_task", "base_problem_statement", "install_config", "golden_patch"
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if SHA256_RE.fullmatch(value) is None:
            raise ValueError("value must be a lowercase SHA-256 digest")
        return value


class TaskRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = Field(ge=0, strict=True)
    test_patch: StrictStr
    contract_addendum: StrictStr
    effective_problem_statement: StrictStr
    fail_to_pass: list[StrictStr]
    pass_to_pass: list[StrictStr]
    test_patch_hash: StrictStr
    contract_addendum_hash: StrictStr
    effective_problem_statement_hash: StrictStr
    task_hash: StrictStr
    revision_hash: StrictStr

    @field_validator("test_patch")
    @classmethod
    def validate_test_patch(cls, value: str) -> str:
        if not is_nonempty_git_patch(value):
            raise ValueError("test_patch must be a nonempty unified Git patch")
        return value

    @field_validator("contract_addendum")
    @classmethod
    def validate_contract_addendum(cls, value: str) -> str:
        if value and not value.strip():
            raise ValueError("contract_addendum must be empty or contain text")
        if CONTRACT_ADDENDUM_HEADING in value:
            raise ValueError("contract_addendum must not include its rendered heading")
        return value

    @field_validator("fail_to_pass", "pass_to_pass")
    @classmethod
    def validate_bucket(cls, value: list[str]) -> list[str]:
        if any(not test_name.strip() for test_name in value):
            raise ValueError("test bucket entries must contain non-whitespace text")
        if len(value) != len(set(value)):
            raise ValueError("test bucket entries must be unique")
        return value

    @field_validator(
        "test_patch_hash",
        "contract_addendum_hash",
        "effective_problem_statement_hash",
        "task_hash",
        "revision_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if SHA256_RE.fullmatch(value) is None:
            raise ValueError("value must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_disjoint_buckets(self) -> Self:
        overlap = set(self.fail_to_pass) & set(self.pass_to_pass)
        if overlap:
            raise ValueError(f"test buckets overlap: {sorted(overlap)}")
        return self


class ModelAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_index: int = Field(ge=0, strict=True)
    generated_revision: int = Field(ge=0, strict=True)
    prediction: dict[str, Any]
    trajectory_path: StrictStr | None = None

    @field_validator("trajectory_path")
    @classmethod
    def validate_trajectory_path(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("trajectory_path must contain non-whitespace text")
        return value


class RowRepairState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instance_id: StrictStr
    original_task: dict[str, Any]
    immutable_hashes: ImmutableTaskHashes
    current_revision: TaskRevision
    repair_cycles: int = Field(ge=0, strict=True)
    repair_cycle_limit: int | None = Field(
        default=None,
        ge=0,
        le=MAX_REPAIR_CYCLES,
        strict=True,
    )
    needs_solver: StrictBool
    evaluated: StrictBool
    model_attempts: list[ModelAttempt]
    convergence_status: ConvergenceStatus
    terminal_reason: TerminalReason | None = None

    @model_validator(mode="after")
    def validate_repair_cycle_limit(self) -> Self:
        if (
            self.repair_cycle_limit is not None
            and self.repair_cycle_limit < self.repair_cycles
        ):
            raise ValueError("repair_cycle_limit cannot precede the current revision")
        return self

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.repair_cycles != self.current_revision.revision:
            raise ValueError("repair_cycles must match the current revision")
        run_indices = [attempt.run_index for attempt in self.model_attempts]
        if len(run_indices) != len(set(run_indices)):
            raise ValueError("model attempt run indices must be unique")
        if any(
            attempt.generated_revision > self.current_revision.revision
            for attempt in self.model_attempts
        ):
            raise ValueError("model attempts cannot come from a future revision")
        if any(
            attempt.prediction.get("instance_id") != self.instance_id
            for attempt in self.model_attempts
        ):
            raise ValueError("model attempt instance_id values must match the row")
        if self.needs_solver and self.model_attempts:
            raise ValueError(
                "revisions needing the solver cannot retain model attempts"
            )
        if (self.evaluated or not self.needs_solver) and not self.model_attempts:
            raise ValueError("evaluated and reused revisions require model attempts")
        if self.convergence_status == "active":
            if self.terminal_reason is not None:
                raise ValueError("active rows cannot have a terminal reason")
        elif not self.evaluated or self.terminal_reason is None:
            raise ValueError("terminal rows must be evaluated and have a reason")
        if self.convergence_status == "converged" and (
            self.terminal_reason != "accepted"
        ):
            raise ValueError("converged rows must have the accepted reason")
        if self.convergence_status == "nonconverged" and (
            self.terminal_reason == "accepted"
        ):
            raise ValueError("nonconverged rows cannot have the accepted reason")
        if self.evaluated and self.needs_solver:
            raise ValueError("evaluated rows cannot still need the solver")
        return self


class StateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    root_run_id: StrictStr
    round_index: int = Field(ge=0, strict=True)
    rows: list[RowRepairState] = Field(min_length=1)

    @field_validator("root_run_id")
    @classmethod
    def validate_root_run_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("root_run_id must contain non-whitespace text")
        return value

    @model_validator(mode="after")
    def validate_rows(self) -> Self:
        instance_ids = [row.instance_id for row in self.rows]
        if len(instance_ids) != len(set(instance_ids)):
            raise ValueError("manifest instance_id values must be unique")
        if any(row.current_revision.revision > self.round_index for row in self.rows):
            raise ValueError("row revisions cannot be ahead of the manifest round")
        return self


class VerdictRoutingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: RowRepairState
    invoke_repairer: StrictBool


def is_nonempty_git_patch(value: str) -> bool:
    if not value.strip():
        return False
    try:
        return len(PatchSet.from_string(value)) > 0
    except Exception:
        return False
