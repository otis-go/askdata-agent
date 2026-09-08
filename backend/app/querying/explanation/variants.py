"""Closed expression vocabulary, not caller-provided template source."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


ExpressionVariantId = Literal[
    "target_attainment_summary_v1", "sales_change_summary_v1", "contribution_summary_v1",
]


@dataclass(frozen=True)
class ExpressionVariant:
    variant_id: ExpressionVariantId
    formula_ids: tuple[str, ...]
    context_roles: tuple[str, str]
    description: str


_VARIANTS = MappingProxyType({
    "monthly_regional_target_attainment": ExpressionVariant(
        "target_attainment_summary_v1", ("attainment_rate",), ("actual", "target"),
        "Describe the supplied attainment rate and operand references without judging whether a target was met.",
    ),
    "regional_sales_change": ExpressionVariant(
        "sales_change_summary_v1", ("absolute_change", "change_rate"), ("current", "baseline"),
        "Describe both supplied outputs independently, preserving an undefined rate and any computed absolute change.",
    ),
    "product_contribution": ExpressionVariant(
        "contribution_summary_v1", ("contribution_rate",), ("parts", "total"),
        "Describe the supplied contribution rate; retain the unkeyed broadcast total and do not rank parts.",
    ),
})


def get_expression_variant(signal_type: str) -> ExpressionVariant:
    """Select only by the already supplied Signal type, never by a question."""
    if type(signal_type) is not str or signal_type not in _VARIANTS:
        raise ValueError("unsupported expression Signal type")
    return _VARIANTS[signal_type]


__all__ = ["ExpressionVariantId", "ExpressionVariant", "get_expression_variant"]
