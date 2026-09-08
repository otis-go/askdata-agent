"""Pure migration boundary from a PromptPackage to a closed LLM call contract.

No legacy context, acquisition, model call or arithmetic belongs here. Invalid
model responses are rejected in full; they are never repaired from old data.
"""

from __future__ import annotations

import json

from .prompt_builder import PromptPackage
from .response_models import (
    DiagnosticCode, ExplanationResponse, GenerationStatus, Locale, ModelPresentation,
    ResponseBlock, ResponseCallInput, render_block_text, render_response_text, unavailable_text,
)


_OUTPUT_CONTRACT = (
    "\nReturn exactly one JSON object with only a blocks array. "
    "Return exactly one block per supplied fact_blocks item, in the same order. "
    "Each block must contain only signal_index (the supplied ref.signal_index integer), "
    "expression_variant (the supplied fixed variant), and wording ('summary' or 'operands'). "
    "Choose a wording identifier to organize the explanation. "
    "Do not return prose, business numeric values, units, statuses, reasons, citations, "
    "additional fields or Markdown. The application renders all facts and references."
)


def _package(package: PromptPackage) -> PromptPackage:
    if not isinstance(package, PromptPackage):
        raise TypeError("package must be PromptPackage")
    return PromptPackage.model_validate(package)


def adapt_response_input(package: PromptPackage) -> ResponseCallInput:
    """Validate an immutable projected package and append only the output schema."""
    package = _package(package)
    return ResponseCallInput(
        system_message=package.system_message + _OUTPUT_CONTRACT,
        user_message=package.user_message,
    )


def _reject_duplicate_keys(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON object keys are not allowed")
        result[key] = value
    return result


def _presentation(payload: dict | str) -> ModelPresentation:
    # The transport has one representation: strict JSON. No code fences,
    # textual repair, default fields, Python coercion or caller template source.
    if type(payload) is str:
        decoded = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    elif type(payload) is dict:
        decoded = payload
    else:
        raise TypeError("model presentation must be a JSON object or JSON text")
    return ModelPresentation.model_validate_json(json.dumps(decoded, allow_nan=False))


def render_explanation_response(package: PromptPackage, payload: dict | str) -> ExplanationResponse:
    """Validate model wording choices and render only the original prompt facts."""
    package = _package(package)
    if not package.fact_blocks:
        raise ValueError("a prompt without facts must not request model generation")
    presentation = _presentation(payload)
    if tuple(item.signal_index for item in presentation.blocks) != tuple(block.ref.signal_index for block in package.fact_blocks):
        raise ValueError("model blocks must preserve every requested Signal and its order")
    references = {item.ref: item for item in package.reference_blocks}
    blocks = []
    for fact, choice in zip(package.fact_blocks, presentation.blocks):
        if choice.expression_variant != fact.expression_variant:
            raise ValueError("model output cannot change the supplied expression variant")
        operands = tuple(references[ref] for ref in fact.facts.evidence_refs)
        blocks.append(ResponseBlock(
            ref=fact.ref, expression_variant=fact.expression_variant, wording=choice.wording,
            fact=fact, citation_refs=fact.facts.evidence_refs,
            text=render_block_text(fact, operands, choice.wording, package.request_options.locale),
        ))
    return ExplanationResponse(
        generation_status="generated",
        presentation_coverage="partial" if any(item.reason != "not_displayable" for item in package.omissions) else "complete",
        locale=package.request_options.locale, source_signal_count=package.total_signal_count,
        displayable_signal_indices=package.displayable_signal_indices,
        requested_signal_indices=tuple(block.ref.signal_index for block in package.fact_blocks),
        blocks=tuple(blocks), citations=package.reference_blocks, notice_blocks=package.notice_blocks,
        omissions=package.omissions, diagnostic_codes=(),
        text=render_response_text(tuple(blocks), package.notice_blocks, package.omissions, package.request_options.locale),
    )


def unavailable_explanation(
    code: DiagnosticCode, *, locale: Locale = "zh-CN", generation_status: GenerationStatus = "unavailable",
    package: PromptPackage | None = None,
) -> ExplanationResponse:
    """Return a fixed presentation failure; never substitute an upstream answer."""
    if package is not None:
        package = _package(package)
        locale = package.request_options.locale
    return ExplanationResponse(
        generation_status=generation_status, presentation_coverage="none", locale=locale,
        source_signal_count=package.total_signal_count if package is not None else 0,
        displayable_signal_indices=package.displayable_signal_indices if package is not None else (),
        requested_signal_indices=tuple(block.ref.signal_index for block in package.fact_blocks) if package is not None else (),
        blocks=(), citations=(), notice_blocks=package.notice_blocks if package is not None else (),
        omissions=package.omissions if package is not None else (), diagnostic_codes=(code,), text=unavailable_text(locale),
    )


def validate_response_for_package(response: ExplanationResponse, package: PromptPackage) -> ExplanationResponse:
    """Compatibility facade; all current-package rules live in the Validator."""
    from .validator import validate_response

    validation = validate_response(response, package)
    if validation.status == "validation_failed":
        raise ValueError("response validation failed: " + ", ".join(item.code for item in validation.issues))
    return validation.validated_response


__all__ = ["adapt_response_input", "render_explanation_response", "unavailable_explanation", "validate_response_for_package"]
