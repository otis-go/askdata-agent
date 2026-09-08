"""Deterministic current-package validation of controlled explanations.

This boundary compares supplied facts and references. It never computes values,
interprets prose, acquires data, or asks a model to judge another model.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, model_validator

from .prompt_builder import PromptModel, PromptPackage
from .response_models import ExplanationResponse, render_block_text, render_response_text


ValidationCode = Literal[
    "INVALID_PROMPT_PACKAGE", "INVALID_RESPONSE", "PROJECTION_MISMATCH",
    "SIGNAL_REFERENCE_MISMATCH", "FORMULA_REFERENCE_MISMATCH",
    "EVIDENCE_REFERENCE_MISMATCH", "EXPRESSION_MISMATCH", "FACT_MISMATCH",
    "VALUE_MISMATCH", "UNIT_MISMATCH", "UNDEFINED_MISMATCH",
    "CITATION_MISMATCH", "LIMITATION_MISMATCH", "TEXT_MISMATCH",
]
PathField = Literal[
    "package", "response", "source_batch_slot", "source_signal_count", "locale",
    "displayable_signal_indices", "requested_signal_indices", "notice_blocks", "omissions",
    "blocks", "ref", "fact", "facts", "outputs", "value", "unit_id", "status",
    "reason_code", "numeric_quality", "input_evidence_refs", "evidence_refs",
    "citation_refs", "citations", "expression_variant", "text",
]


class ValidationIssue(PromptModel):
    code: ValidationCode
    path: tuple[PathField | int, ...]

    @model_validator(mode="after")
    def safe_path(self) -> Self:
        if not self.path or any(type(item) is int and item < 0 for item in self.path):
            raise ValueError("validation locations require a nonempty structural path")
        return self


class ValidationResult(PromptModel):
    """Contract acceptance is separate from explanation generation success."""

    version: Literal["1"] = "1"
    status: Literal["validated", "validation_failed"]
    validated_response: ExplanationResponse | None
    issues: tuple[ValidationIssue, ...]

    @model_validator(mode="after")
    def result_shape(self) -> Self:
        if self.status == "validated":
            if self.validated_response is None or self.issues:
                raise ValueError("validated results require a response and no issues")
        elif self.validated_response is not None or not self.issues:
            raise ValueError("failed validation retains issues, never candidate facts")
        return self


def _failure(code: ValidationCode, field: PathField) -> ValidationResult:
    return ValidationResult(
        status="validation_failed", validated_response=None,
        issues=(ValidationIssue(code=code, path=(field,)),),
    )


def _check_tree(value: object, ancestors: frozenset[int] = frozenset()) -> None:
    """Check original containers before serialization can discard hidden fields."""
    if isinstance(value, BaseModel):
        fields = type(value).model_fields
        if set(value.__dict__) != set(fields) or value.__pydantic_extra__:
            raise ValueError("undeclared or missing model fields")
        children = tuple(value.__dict__.values())
    elif type(value) in (tuple, list):
        children = value
    elif type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("object keys must be strings")
        children = tuple(value.values())
    elif value is None or type(value) in (str, int, bool):
        return
    else:
        raise TypeError("unsupported value in explanation contract")
    if id(value) in ancestors:
        raise ValueError("cyclic explanation data")
    ancestors = ancestors | {id(value)}
    for child in children:
        _check_tree(child, ancestors)


def _compare(response: ExplanationResponse, package: PromptPackage) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []

    def issue(code: ValidationCode, *path: PathField | int) -> None:
        issues.append(ValidationIssue(code=code, path=("response", *path)))

    expected_metadata = (
        ("source_batch_slot", package.source_batch_slot),
        ("source_signal_count", package.total_signal_count),
        ("locale", package.request_options.locale),
        ("displayable_signal_indices", package.displayable_signal_indices),
        ("requested_signal_indices", tuple(block.ref.signal_index for block in package.fact_blocks)),
    )
    for field, expected in expected_metadata:
        if getattr(response, field) != expected:
            issue("PROJECTION_MISMATCH", field)
    for field in ("notice_blocks", "omissions"):
        if getattr(response, field) != getattr(package, field):
            issue("LIMITATION_MISMATCH", field)

    # Failure models already prohibit facts/citations and arbitrary failure
    # text. Their own generation status must not become a computation verdict.
    if response.generation_status != "generated":
        return tuple(issues)

    if tuple(block.ref for block in response.blocks) != tuple(block.ref for block in package.fact_blocks):
        issue("SIGNAL_REFERENCE_MISMATCH", "blocks")
    expected_by_ref = {block.ref: block for block in package.fact_blocks}
    source_evidence = {item.ref: item for item in package.reference_blocks}
    for index, block in enumerate(response.blocks):
        expected = expected_by_ref.get(block.ref)
        if expected is None:
            issue("SIGNAL_REFERENCE_MISMATCH", "blocks", index, "ref")
            continue
        path = ("blocks", index)
        if block.expression_variant != expected.expression_variant:
            issue("EXPRESSION_MISMATCH", *path, "expression_variant")
        if block.citation_refs != expected.facts.evidence_refs:
            issue("EVIDENCE_REFERENCE_MISMATCH", *path, "citation_refs")
        if block.fact.facts.evidence_refs != expected.facts.evidence_refs:
            issue("EVIDENCE_REFERENCE_MISMATCH", *path, "fact", "facts", "evidence_refs")
        if len(block.fact.facts.outputs) != len(expected.facts.outputs):
            issue("FORMULA_REFERENCE_MISMATCH", *path, "fact", "facts", "outputs")
        for output_index, (observed, source) in enumerate(zip(block.fact.facts.outputs, expected.facts.outputs)):
            output_path = (*path, "fact", "facts", "outputs", output_index)
            if observed.ref != source.ref:
                issue("FORMULA_REFERENCE_MISMATCH", *output_path, "ref")
            if observed.value != source.value:
                issue("VALUE_MISMATCH", *output_path, "value")
            if observed.unit_id != source.unit_id:
                issue("UNIT_MISMATCH", *output_path, "unit_id")
            if observed.status != source.status or observed.reason_code != source.reason_code:
                issue("UNDEFINED_MISMATCH" if source.status == "undefined" else "FACT_MISMATCH",
                      *output_path, "status")
            if observed.input_evidence_refs != source.input_evidence_refs:
                issue("EVIDENCE_REFERENCE_MISMATCH", *output_path, "input_evidence_refs")
            if observed.numeric_quality != source.numeric_quality:
                issue("FACT_MISMATCH", *output_path, "numeric_quality")
        # Full equality also retains policy, key, limitations and every field
        # added to FactBlock later, without interpreting their business meaning.
        if block.fact != expected:
            issue("FACT_MISMATCH", *path, "fact")
        operands = tuple(source_evidence[ref] for ref in expected.facts.evidence_refs)
        if block.text != render_block_text(expected, operands, block.wording, package.request_options.locale):
            issue("TEXT_MISMATCH", *path, "text")

    # Evidence IDs are scoped by SignalRef; never match on the bare evidence_id.
    if tuple(item.ref for item in response.citations) != tuple(item.ref for item in package.reference_blocks):
        issue("EVIDENCE_REFERENCE_MISMATCH", "citations")
    if response.citations != package.reference_blocks:
        issue("CITATION_MISMATCH", "citations")
    if response.text != render_response_text(
        response.blocks, package.notice_blocks, package.omissions, package.request_options.locale,
    ):
        issue("TEXT_MISMATCH", "text")
    return tuple(issues)


def validate_response(response: ExplanationResponse, package: PromptPackage) -> ValidationResult:
    """Return a detached, current-package response or safe deterministic issues.

    Malformed typed inputs (including model_construct/model_copy bypasses) and
    invalid packages return failure. No candidate values or exception text are
    copied to issues; this is a comparison result, not an authenticity receipt.
    """
    try:
        if type(package) is not PromptPackage:
            raise TypeError("package must be PromptPackage")
        _check_tree(package)
        checked_package = PromptPackage.model_validate(package)
        checked_package = PromptPackage.model_validate_json(checked_package.model_dump_json(warnings="error"))
    except Exception:
        return _failure("INVALID_PROMPT_PACKAGE", "package")
    try:
        if type(response) is not ExplanationResponse:
            raise TypeError("response must be ExplanationResponse")
        _check_tree(response)
        checked_response = ExplanationResponse.model_validate(response)
        checked_response = ExplanationResponse.model_validate_json(checked_response.model_dump_json(warnings="error"))
    except Exception:
        return _failure("INVALID_RESPONSE", "response")
    try:
        issues = _compare(checked_response, checked_package)
        if issues:
            return ValidationResult(status="validation_failed", validated_response=None, issues=issues)
        return ValidationResult(status="validated", validated_response=checked_response, issues=())
    except Exception:
        return _failure("INVALID_RESPONSE", "response")


__all__ = ["ValidationIssue", "ValidationResult", "validate_response"]
