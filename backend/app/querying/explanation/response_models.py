"""Closed explanation output and deterministic, non-calculating presentation.

The model chooses a wording identifier. All displayed facts and citations are
supplied by the validated PromptPackage, never by model-generated prose.
"""

from __future__ import annotations

import json
from typing import Literal, Self

from pydantic import Field, model_validator

from .models import EvidenceRef, EvidenceSummary, SafeLimitation, SignalRef
from .prompt_builder import FactBlock, Omission, PromptModel
from .variants import ExpressionVariantId, get_expression_variant


_NOTICE_WORDING = {
    "ZERO_DENOMINATOR": ("已提供的分母为零，比例未定义。", "The supplied denominator is zero; the ratio is undefined."),
    "ZERO_BASELINE": ("已提供的基期值为零，变化率未定义。", "The supplied baseline is zero; the change rate is undefined."),
    "ZERO_TOTAL": ("已提供的总额为零，贡献率未定义。", "The supplied total is zero; the contribution rate is undefined."),
    "UNKNOWN_REASON": ("该原因尚无受控解释。", "There is no controlled explanation for this reason."),
    "APPROXIMATE_INPUT": ("输入数值为近似值。", "The input numeric source is approximate."),
    "RATIO_ROUNDED": ("已提供的比例记录了运算舍入。", "The supplied ratio records arithmetic rounding."),
    "PARTITION_WITHIN_RELATIVE_TOLERANCE": ("上游分区校验使用了已批准的相对容差。", "The upstream partition check used its approved relative tolerance."),
    "SIGNAL_IDENTITY_NOT_FROZEN": ("本次引用仅在当前输入内有效。", "References are local to this input."),
    "SIGNAL_STATUS_MISMATCH": ("存在未通过状态一致性检查的记录。", "A record did not pass its display status consistency check."),
    "SIGNAL_EVIDENCE_LINK_INVALID": ("存在未通过证据引用检查的记录。", "A record did not pass its Evidence reference check."),
    "SIGNAL_NOT_DISPLAYABLE": ("部分记录仅保留供审计，不能作为解释事实。", "Some records are retained for audit and cannot be used as explanation facts."),
    "INSUFFICIENT_EVIDENCE": ("部分记录的证据不足。", "Some records have insufficient evidence."),
    "INCOMPATIBLE_CONTEXT": ("部分记录的输入不具备该计算的资格。", "Some inputs were not qualified for the calculation."),
    "UNSUPPORTED": ("部分记录超出当前支持的计算范围。", "Some records are outside the supported calculation capability."),
    "UPSTREAM_LIMITATION_PRESENT": ("上游记录保留了限制条件。", "An upstream limitation is retained in the audit record."),
    "UNEXPANDED_LIMITATION": ("已有的限制条件尚无受控解释。", "A retained limitation has no controlled explanation mapping."),
}


def _notice(code: str, locale: str) -> str:
    return _NOTICE_WORDING[code][0 if locale == "zh-CN" else 1]


GenerationStatus = Literal["generated", "not_requested", "unavailable", "failed", "validation_failed"]
DiagnosticCode = Literal[
    "NO_PROMPT_PACKAGE", "INVALID_PROMPT_PACKAGE", "LEGACY_CONTEXT_UNAVAILABLE",
    "NO_DISPLAYABLE_FACTS", "LLM_UNAVAILABLE", "LLM_CALL_FAILED", "INVALID_LLM_RESPONSE",
    "NO_SIGNAL_BATCH", "INVALID_SIGNAL_DELIVERY", "SIGNAL_DELIVERY_FAILED",
    "INVALID_SIGNAL_BATCH", "PROMPT_BUILD_FAILED", "EXECUTION_UNAVAILABLE",
    "RESPONSE_VALIDATION_FAILED",
]
Wording = Literal["summary", "operands"]
Locale = Literal["zh-CN", "en"]


class ResponseChoice(PromptModel):
    signal_index: int = Field(ge=0)
    expression_variant: ExpressionVariantId
    wording: Wording


class ModelPresentation(PromptModel):
    """Only these choices may cross the model output boundary."""

    blocks: tuple[ResponseChoice, ...]


class ResponseCallInput(PromptModel):
    system_message: str = Field(min_length=1)
    user_message: str = Field(min_length=1)


class ResponseBlock(PromptModel):
    ref: SignalRef
    expression_variant: ExpressionVariantId
    wording: Wording
    fact: FactBlock
    citation_refs: tuple[EvidenceRef, ...]
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def original_fact_binding(self) -> Self:
        if self.ref != self.fact.ref or self.expression_variant != self.fact.expression_variant:
            raise ValueError("an explanation block must preserve its source Signal and expression variant")
        if self.citation_refs != self.fact.facts.evidence_refs:
            raise ValueError("a block must cite its complete original operand pair")
        return self


def _literal(value: object) -> str:
    """Quote data without interpreting numbers, markup or embedded commands."""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for original, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), ("`", "\\u0060")):
        text = text.replace(original, escaped)
    return text


def render_block_text(
    fact: FactBlock, citations: tuple[EvidenceSummary, ...], wording: Wording, locale: Locale,
) -> str:
    """Render existing text and safe codes only; never parse a numeric value."""
    titles = {
        "zh-CN": {
            "target_attainment_summary_v1": "目标达成率",
            "sales_change_summary_v1": "区域销售变化",
            "contribution_summary_v1": "产品贡献率",
        },
        "en": {
            "target_attainment_summary_v1": "Target attainment",
            "sales_change_summary_v1": "Regional sales change",
            "contribution_summary_v1": "Product contribution",
        },
    }
    zh = locale == "zh-CN"
    roles = {
        "actual": "实际销售" if zh else "Actual sales", "target": "目标" if zh else "Target",
        "current": "当期销售" if zh else "Current sales", "baseline": "基期销售" if zh else "Baseline sales",
        "parts": "分项" if zh else "Part", "total": "总额" if zh else "Total",
    }
    formula_labels = {
        "attainment_rate": "目标达成率" if zh else "Attainment rate",
        "absolute_change": "销售变化额" if zh else "Absolute sales change",
        "change_rate": "销售变化率" if zh else "Sales change rate",
        "contribution_rate": "贡献率" if zh else "Contribution rate",
    }
    fidelities = {"exact": "精确" if zh else "exact", "approximate": "近似" if zh else "approximate", "unknown": "未知" if zh else "unknown"}
    rounding = {"exact": "精确" if zh else "exact", "rounded": "已舍入" if zh else "rounded", "unknown": "未知" if zh else "unknown"}
    parts = [titles[locale][fact.expression_variant]]
    if fact.facts.business_key is not None:
        for component in fact.facts.business_key.components:
            label = {
                "region": "区域" if zh else "Region", "category": "品类" if zh else "Category",
                "product_id": "产品" if zh else "Product",
            }.get(component.component_id, "业务键" if zh else "Business key")
            parts.append(f"{label}: {_literal(component.normalized_value)}")
    periods = (
        tuple((item.context_role, item.period) for item in fact.facts.business_key.periods)
        if fact.facts.business_key is not None else
        tuple((item.context_role, item.normalized_period) for item in citations if item.normalized_period is not None)
    )
    for role, period in periods:
        lower = "[" if period.lower_inclusive else "("
        upper = "]" if period.upper_inclusive else ")"
        label = "期间" if zh else "period"
        parts.append(f"{roles[role]} {label}: {lower}{_literal(period.lower)}, {_literal(period.upper)}{upper}")
    for output in fact.facts.outputs:
        if output.status == "computed":
            value = _literal(output.value)
        else:
            value = ("未定义。" if zh else "Undefined. ") + _notice(output.reason_code or "UNKNOWN_REASON", locale)
        quality = output.numeric_quality
        unit_label = "单位" if zh else "unit"
        source_label = "来源精度" if zh else "source fidelity"
        rounding_label = "运算精度" if zh else "arithmetic precision"
        parts.append(
            f"{formula_labels[output.ref.formula_id]}: {value}; "
            f"{unit_label}: {_literal(output.unit_id)}; {source_label}: {fidelities[quality.source_fidelity]}; "
            f"{rounding_label}: {rounding[quality.arithmetic_rounding]}"
        )
    for citation in citations:
        for predicate in citation.normalized_filters:
            label = "筛选范围" if zh else "filter scope"
            if predicate.operator == "BETWEEN":
                value = f"{_literal(predicate.lower_bound.value)} AND {_literal(predicate.upper_bound.value)}"
            else:
                value = _literal(predicate.value.value)
            parts.append(f"{roles[citation.context_role]} {label}: {_literal(predicate.source_identity)} {predicate.operator} {value} ({predicate.scope})")
        if citation.unit_scale is not None:
            label = "单位倍率" if zh else "unit scale"
            parts.append(f"{roles[citation.context_role]} {label}: {_literal(citation.unit_scale)}")
    if wording == "operands":
        for citation in citations:
            observation = citation.observed_value
            if observation is None:
                raise ValueError("rendering requires the supplied operand observation")
            parts.append(
                f"{roles[citation.context_role]}: {_literal(observation.value)}; "
                f"{unit_label}: {_literal(observation.unit_id)}; "
                f"{source_label}: {fidelities[observation.numeric_quality.source_fidelity]}"
            )
    return "\n".join(parts)


def unavailable_text(locale: Locale) -> str:
    return "当前无法生成业务解释。" if locale == "zh-CN" else "A business explanation cannot be generated for this request."


def render_response_text(
    blocks: tuple[ResponseBlock, ...], notices: tuple[SafeLimitation, ...],
    omissions: tuple[Omission, ...], locale: Locale,
) -> str:
    """Keep presentation limits visible even for consumers of the text field."""
    sections = [block.text for block in blocks]
    if notices:
        label = "解释限制" if locale == "zh-CN" else "Explanation limitations"
        sections.append(f"{label}: " + " ".join(_notice(code, locale) for code in dict.fromkeys(item.code for item in notices)))
    if omissions:
        hidden = sum(item.reason == "not_displayable" for item in omissions)
        deferred = len(omissions) - hidden
        if deferred:
            sections.append(f"本次仅展示部分结果，另有 {deferred} 条可展示记录未展开。" if locale == "zh-CN"
                            else f"This presentation is partial; {deferred} eligible records are not expanded.")
        if hidden:
            sections.append(f"另有 {hidden} 条记录不能作为解释事实，已保留其审计信息。" if locale == "zh-CN"
                            else f"Another {hidden} records cannot be explanation facts; their audit information is retained.")
    return "\n\n".join(sections)


class ExplanationResponse(PromptModel):
    """Generation state is presentation state, never Signal computation state."""

    version: Literal["1"] = "1"
    source_batch_slot: Literal["input_batch"] = "input_batch"
    generation_status: GenerationStatus
    presentation_coverage: Literal["complete", "partial", "none"]
    locale: Locale = "zh-CN"
    source_signal_count: int = Field(ge=0)
    displayable_signal_indices: tuple[int, ...]
    requested_signal_indices: tuple[int, ...]
    blocks: tuple[ResponseBlock, ...]
    citations: tuple[EvidenceSummary, ...]
    notice_blocks: tuple[SafeLimitation, ...]
    omissions: tuple[Omission, ...]
    diagnostic_codes: tuple[DiagnosticCode, ...]
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def closed_response(self) -> Self:
        displayable = self.displayable_signal_indices
        requested = self.requested_signal_indices
        if displayable != tuple(sorted(set(displayable))) or any(
            type(index) is not int or index < 0 or index >= self.source_signal_count for index in displayable
        ):
            raise ValueError("displayable indices must retain their source scope")
        if requested != tuple(sorted(set(requested))) or any(index not in displayable for index in requested):
            raise ValueError("requested indices must retain an ordered source display subset")
        expected_omitted = tuple(index for index in range(self.source_signal_count) if index not in requested)
        if tuple(item.signal_index for item in self.omissions) != expected_omitted:
            raise ValueError("the original prompt omissions must remain complete and ordered")
        for omission in self.omissions:
            if (omission.reason == "not_displayable") != (omission.signal_index not in displayable):
                raise ValueError("omission reasons must preserve upstream display eligibility")
        notice_refs = {item.ref for item in self.notice_blocks}
        if len(notice_refs) != len(self.notice_blocks):
            raise ValueError("notice references must be unique")
        if any(ref.signal_index is not None and ref.signal_index >= self.source_signal_count for ref in notice_refs):
            raise ValueError("notice references must retain the source Signal scope")
        if self.generation_status != "generated":
            expected_codes = {
                "unavailable": {"NO_PROMPT_PACKAGE", "INVALID_PROMPT_PACKAGE", "LEGACY_CONTEXT_UNAVAILABLE",
                                "NO_SIGNAL_BATCH", "INVALID_SIGNAL_DELIVERY", "SIGNAL_DELIVERY_FAILED",
                                "INVALID_SIGNAL_BATCH", "PROMPT_BUILD_FAILED", "EXECUTION_UNAVAILABLE"},
                "not_requested": {"NO_DISPLAYABLE_FACTS"},
                "failed": {"LLM_UNAVAILABLE", "LLM_CALL_FAILED", "INVALID_LLM_RESPONSE"},
                "validation_failed": {"RESPONSE_VALIDATION_FAILED"},
            }[self.generation_status]
            if (self.blocks or self.citations or self.presentation_coverage != "none"
                    or len(self.diagnostic_codes) != 1 or self.diagnostic_codes[0] not in expected_codes):
                raise ValueError("a generation failure cannot publish facts or fabricated citations")
            if self.generation_status == "not_requested" and requested:
                raise ValueError("not_requested is reserved for a prompt without fact blocks")
            if self.text != unavailable_text(self.locale):
                raise ValueError("unavailable text must be the fixed explanation status message")
            return self
        if not self.blocks or self.diagnostic_codes:
            raise ValueError("generated responses require facts and cannot carry generation failure codes")
        if tuple(block.ref.signal_index for block in self.blocks) != requested:
            raise ValueError("generated responses must explain every requested Signal in original order")
        expected_coverage = "partial" if any(item.reason != "not_displayable" for item in self.omissions) else "complete"
        if self.presentation_coverage != expected_coverage:
            raise ValueError("presentation coverage must account for every original prompt omission")
        expected_refs = tuple(ref for block in self.blocks for ref in block.citation_refs)
        if len(set(expected_refs)) != len(expected_refs) or tuple(item.ref for item in self.citations) != expected_refs:
            raise ValueError("citations must resolve exactly within each source Signal scope")
        citations = {item.ref: item for item in self.citations}
        for block in self.blocks:
            fact = block.fact
            operands = tuple(citations[ref] for ref in block.citation_refs)
            if len(operands) != 2 or tuple(item.context_role for item in operands) != get_expression_variant(fact.signal_type).context_roles:
                raise ValueError("response citations must retain the original ordered operand roles")
            required_notices = (*fact.limitation_refs, *(ref for item in operands for ref in item.limitation_refs))
            if any(ref not in notice_refs for ref in required_notices):
                raise ValueError("response must retain every referenced source limitation")
            for output in fact.facts.outputs:
                if output.input_evidence_refs != block.citation_refs:
                    raise ValueError("each output must retain its own complete operand references")
                for operand in operands:
                    if operand.observed_value is None or operand.observed_value.presence != "present":
                        raise ValueError("output citations must retain the actual observed input pair")
                    if not any(ref.formula_id == output.ref.formula_id and ref.formula_version == output.ref.formula_version
                               for ref in operand.formula_refs):
                        raise ValueError("output formulas must resolve on both source operands")
            if block.text != render_block_text(fact, operands, block.wording, self.locale):
                raise ValueError("block text must render the supplied facts without model-authored values")
        if self.text != render_response_text(self.blocks, self.notice_blocks, self.omissions, self.locale):
            raise ValueError("response text must preserve ordered facts and their presentation limitations")
        return self


__all__ = [
    "ResponseChoice", "ModelPresentation", "ResponseCallInput", "ResponseBlock", "ExplanationResponse",
    "GenerationStatus", "DiagnosticCode", "render_block_text", "render_response_text", "unavailable_text",
]
