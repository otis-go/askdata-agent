"""Generate explanations only from an already projected PromptPackage."""

from __future__ import annotations

from ..model_client import ModelClient
from .explanation.prompt_builder import PromptPackage
from .explanation.response_adapter import (
    adapt_response_input, render_explanation_response, unavailable_explanation,
)
from .explanation.response_models import ExplanationResponse
from .explanation.validator import validate_response


class ResponseGenerator:
    """Language organization cannot change the supplied business facts.

    Both public entry points have the same strict input boundary. There is no
    legacy execution/context overload, row-based fallback or QA skill prompt.
    """

    def __init__(self, model_client: ModelClient) -> None:
        self.model_client = model_client

    def generate_from_prompt_package(self, package: PromptPackage) -> ExplanationResponse:
        if not isinstance(package, PromptPackage):
            raise TypeError("ResponseGenerator requires a PromptPackage")
        package = PromptPackage.model_validate(package)
        if not package.fact_blocks:
            return unavailable_explanation(
                "NO_DISPLAYABLE_FACTS", generation_status="not_requested", package=package,
            )
        call = adapt_response_input(package)
        try:
            # Preserve the raw reply for strict parsing. chat_json's legacy
            # code-fence/prose repair would bypass the adapter's wire contract.
            payload = self.model_client.chat(call.system_message, call.user_message)
        except RuntimeError:
            return unavailable_explanation(
                "LLM_CALL_FAILED", generation_status="failed", package=package,
            )
        try:
            if type(payload) is not str:
                raise TypeError("the model transport must return JSON text")
            candidate = render_explanation_response(package, payload)
        except (ValueError, TypeError, RecursionError):
            return unavailable_explanation(
                "RESPONSE_VALIDATION_FAILED", generation_status="validation_failed", package=package,
            )
        validation = validate_response(candidate, package)
        if validation.status == "validation_failed":
            return unavailable_explanation(
                "RESPONSE_VALIDATION_FAILED", generation_status="validation_failed", package=package,
            )
        return validation.validated_response

    def finalize(self, package: PromptPackage) -> ExplanationResponse:
        return self.generate_from_prompt_package(package)

    def answer_qa(self, package: PromptPackage) -> ExplanationResponse:
        return self.generate_from_prompt_package(package)
