"""S3 calculation over a qualified complete partition and independent total.

Compatibility and Alignment are consumed, never rerun. Numeric Reader owns
all operand reads. The shared Evidence Builder records those existing facts;
it does not acquire data or introduce an Engine/SignalBatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow, localcontext,
)

from .alignment_binding import alignment_binding_matches
from .evidence import build_signal_evidence
from .models import (
    AlignmentPair, AlignmentResult, BusinessSignal, ComputationResult,
    ContextCompatibility, EvidenceFormulaRef, InputDeclaration, Issue, NumericQuality,
    ProductContributionInput, SignalEvidence, SignalOperandReference, SignalStatus,
)
from .numeric import NumericReadResult, read_numeric_value
from .policies import NumericRules, ProductContributionPolicy
from .product_contribution_policy import supports_product_contribution_v1
from .receipt_binding import _digest, receipt_binding_matches


def _issue(code: str, message: str, *, severity="error", stage="computation") -> Issue:
    return Issue(code=code, stage=stage, severity=severity, message=message,
                 evidence_paths=["compute_product_contribution"])


def _arithmetic(rules: NumericRules) -> Context:
    return Context(
        prec=rules.decimal_precision, rounding=rules.rounding,
        Emin=-999999, Emax=999999, capitals=1, clamp=0, flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


@dataclass(frozen=True)
class _PartitionResult:
    status: str
    code: str | None = None
    tolerance_used: bool = False


def _reconcile(parts: list[NumericReadResult], total: NumericReadResult,
               rules: NumericRules) -> _PartitionResult:
    """Check only ready Numeric values; coverage was qualified upstream."""
    with localcontext(_arithmetic(rules)) as context:
        denominator = total.work_value
        if denominator.is_zero():
            if any(part.work_value > 0 for part in parts):
                return _PartitionResult("incompatible_context", "ZERO_TOTAL_WITH_POSITIVE_PART")
            return _PartitionResult("undefined", "ZERO_TOTAL")
        # <=10,000 approved operands at <=18 places need at most 60 digits
        # in their unquantized sum. Do not apply input magnitude limits to it.
        part_sum = sum((part.work_value for part in parts), Decimal(0))
        threshold = (denominator.copy_abs() * Decimal(rules.relative_tolerance)
                     if rules.reconciliation == "relative_tolerance" else Decimal(0))
        residual = (part_sum - denominator).copy_abs()
        excesses = [part.work_value - denominator for part in parts]
        if context.flags[Inexact]:
            return _PartitionResult("unsupported", "PARTITION_PRECISION_LOSS")
        if any(excess > threshold for excess in excesses):
            return _PartitionResult("incompatible_context", "PART_EXCEEDS_TOTAL")
        if residual > threshold:
            return _PartitionResult("incompatible_context", "PARTITION_TOTAL_MISMATCH")
        return _PartitionResult("ready", tolerance_used=(
            not residual.is_zero() or any(excess > 0 for excess in excesses)
        ))


def _ratio(part: NumericReadResult, total: NumericReadResult,
           rules: NumericRules) -> tuple[str, NumericQuality]:
    with localcontext(_arithmetic(rules)) as context:
        value = (part.work_value / total.work_value).quantize(
            Decimal((0, (1,), -rules.ratio_scale)),
        )
        rounded = context.flags[Inexact]
    qualities = [part.numeric_quality, total.numeric_quality]
    kinds = {item.source_kind for item in qualities}
    quality = NumericQuality(
        source_fidelity="approximate" if any(item.source_fidelity == "approximate" for item in qualities) else "exact",
        source_kind=("binary_float" if "binary_float" in kinds else
                     next(iter(kinds)) if len(kinds) == 1 else "unknown"),
        arithmetic_rounding="rounded" if rounded else "exact", scale=rules.ratio_scale,
    )
    return format(value, "f"), quality


def _alignment_shape_matches(alignment: AlignmentResult, receipt: ContextCompatibility,
                             parts_count: int | None) -> bool:
    """Inspect confirmed correspondence, not keys, grain or raw rows.

    The current global-total producer emits matched broadcast pairs. An
    explicitly bound ordinary match is limited to one-to-one consumption;
    it never authorizes reusing the denominator without broadcast flags.
    """
    pairs = alignment.pairs
    if (parts_count is None or parts_count < 1 or len(pairs) != parts_count
            or alignment.key_domain != receipt.key_domains
            or alignment.missing_left_keys or alignment.missing_right_keys or alignment.duplicate_keys):
        return False
    if any(pair.status != "matched" or pair.left_key is None or pair.key != pair.left_key
           or pair.right_key is not None or pair.right_row_index != 0 for pair in pairs):
        return False
    if {pair.left_row_index for pair in pairs} != set(range(parts_count)):
        return False
    if any(pair.broadcast for pair in pairs):
        return (all(pair.broadcast for pair in pairs) and alignment.broadcastable
                and alignment.broadcast_role == "total")
    return (parts_count == 1 and not alignment.broadcastable and alignment.broadcast_role is None)


class _ProductContribution:
    def __init__(self, inputs, compatibility, alignment, policy):
        supplied = ProductContributionInput.model_validate(inputs.model_dump(mode="python"))
        self.inputs = {"parts": supplied.parts, "total": supplied.total}
        self.receipt = ContextCompatibility.model_validate(compatibility.model_dump(mode="python"))
        self.alignment = AlignmentResult.model_validate(alignment.model_dump(mode="python"))
        self.policy = ProductContributionPolicy.model_validate(policy.model_dump(mode="python"))
        self.policy_digest = _digest("compat-policy-v1", self.policy.model_dump(mode="python"))
        self.context_digests = {role: _digest("context-v1", item.context.model_dump(mode="python"))
                                for role, item in self.inputs.items()}
        self.qualified = False
        self.units: dict[str, InputDeclaration] = {}
        self.issues = [*self.receipt.issues, *self.alignment.issues,
                       _issue("SIGNAL_IDENTITY_NOT_FROZEN", "Signal identity remains unset.",
                              severity="info", stage="evidence")]

    def accepted_units(self) -> bool:
        """Resolve declarations already consumed by the verified receipt."""
        for role, supplied in self.inputs.items():
            candidates = [declaration for declaration in supplied.declarations
                          if declaration.declaration_type == "unit"
                          and supplied.selection.metric_column_id in declaration.column_ids
                          and any(
                              ref.declaration_id == declaration.declaration_id
                              and ref.declaration_type == "unit"
                              and ref.result_id == supplied.context.result_id == declaration.result_id
                              and ref.context_digest == self.context_digests[role] == declaration.context_digest
                              for ref in self.receipt.declarations_used)]
            candidates = [item for index, item in enumerate(candidates) if item not in candidates[:index]]
            if len(candidates) != 1 or candidates[0].claims.unit is None:
                return False
            self.units[role] = candidates[0]
        return True

    def reference(self, role: str, pair: AlignmentPair | None) -> SignalOperandReference:
        supplied = self.inputs[role]
        columns = [column for column in supplied.context.execution.columns or []
                   if column.id == supplied.selection.metric_column_id]
        column = columns[0] if len(columns) == 1 else None
        row_index = None if pair is None else (pair.left_row_index if role == "parts" else pair.right_row_index)
        return SignalOperandReference(
            context_role=role, result_id=supplied.context.result_id, context_digest=self.context_digests[role],
            column_id=column.id if column else None, ordinal=column.ordinal if column else None,
            row_index=row_index if column else None,
            alignment_broadcast=pair.broadcast if pair is not None else None,
        )

    def evidence(self, role: str, reading: NumericReadResult | None,
                 pair: AlignmentPair | None) -> SignalEvidence:
        """Record the already read operand and its verified alignment side."""
        supplied = self.inputs[role]
        side = "left" if role == "parts" else "right"
        row_index = None if pair is None else (
            pair.left_row_index if role == "parts" else pair.right_row_index
        )
        return build_signal_evidence(
            context=supplied.context, selection=supplied.selection, context_role=role,
            evidence_id=f"{role}:metric", context_digest=self.context_digests[role],
            row_index=row_index, numeric_result=reading,
            alignment_pair=pair, alignment_side=side if pair is not None else None,
            alignment_broadcast=pair.broadcast if pair is not None and pair.status == "matched" else None,
            compatibility=self.receipt if self.qualified else None,
            unit_declaration=self.units.get(role),
            formula_refs=[EvidenceFormulaRef(formula_id="contribution_rate", formula_version="1")],
        )

    def signal(self, status: SignalStatus, reason: str | None, *, pair=None,
               part=None, total=None, value=None, quality=None, issues=()) -> BusinessSignal:
        evidence = [self.evidence("parts", part, pair), self.evidence("total", total, pair)]
        return BusinessSignal(
            signal_type="product_contribution", scope="business_key" if pair is not None else "context",
            status=status, policy_id=self.policy.policy_id, policy_version=self.policy.version,
            policy_digest=self.policy_digest, calculator_version="1", business_key=pair.key if pair else None,
            metric=self.receipt.normalized_metric_refs if self.qualified else [],
            current_value=evidence[0].observed_value,
            reference_value=evidence[1].observed_value,
            computed_value={"contribution_rate": ComputationResult(
                status=status, value=value, unit_id="ratio", formula_id="contribution_rate",
                formula_version="1", input_evidence_ids=[item.evidence_id for item in evidence], reason_code=reason,
                numeric_quality=quality or NumericQuality(),
            )}, evidence=evidence,
            operand_references=[self.reference(role, pair) for role in ("parts", "total")],
            limitations=[*self.issues, *issues],
        ).model_copy(deep=True)

    def reject(self, status: SignalStatus, code: str, message: str, *, pairs=None):
        issue = _issue(code, message)
        return [self.signal(status, code, pair=pair, issues=[issue]) for pair in pairs or [None]]

    def run(self) -> list[BusinessSignal]:
        receipt, alignment = self.receipt, self.alignment
        if not receipt_binding_matches(receipt, self.inputs, self.policy):
            return self.reject("incompatible_context", "COMPATIBILITY_RECEIPT_MISMATCH",
                               "Compatibility receipt does not belong to the current input snapshot.")
        if not supports_product_contribution_v1(self.policy):
            return self.reject("unsupported", "UNSUPPORTED_PRODUCT_CONTRIBUTION_POLICY",
                               "Only the approved category/product paid-sales profiles are supported.")
        if receipt.status != "compatible":
            return self.reject(receipt.status, "COMPATIBILITY_NOT_COMPATIBLE",
                               "Compatibility has not qualified the complete partition and denominator.")
        if (receipt.operation != "divide" or receipt.context_roles != ["parts", "total"]
                or alignment.operation != "divide"
                or (alignment.left_role, alignment.right_role) != ("parts", "total")):
            return self.reject("incompatible_context", "S3_OPERATION_MISMATCH",
                               "S3 requires divide with parts and total in that role order.")
        if not alignment_binding_matches(alignment, receipt):
            return self.reject("incompatible_context", "ALIGNMENT_RECEIPT_MISMATCH",
                               "Alignment content does not belong to this Compatibility receipt.")
        self.qualified = True
        if not self.accepted_units():
            return self.reject("insufficient_evidence", "UNIT_EVIDENCE_MISSING",
                               "Each operand requires its Compatibility-consumed unit declaration.")
        if alignment.status != "aligned":
            return self.reject(alignment.status, "ALIGNMENT_NOT_ALIGNED",
                               "The entire Alignment must pass before numeric reads.", pairs=alignment.pairs)
        parts_count = self.inputs["parts"].context.execution.returned_rows
        if parts_count is not None and parts_count > self.policy.numeric_rules.max_parts:
            return self.reject("unsupported", "MAX_PARTS_EXCEEDED", "The entire partition exceeds the Policy resource limit.")
        if not alignment.pairs:
            return self.reject("insufficient_evidence", "NO_OBSERVED_PARTS", "No observed product keys are available.")
        if not _alignment_shape_matches(alignment, receipt, parts_count):
            return self.reject("incompatible_context", "ALIGNMENT_SHAPE_MISMATCH",
                               "Confirmed pairs must cover each part once and explicitly authorize any total reuse.")
        return self.compute_partition()

    def compute_partition(self) -> list[BusinessSignal]:
        rules, pairs = self.policy.numeric_rules, self.alignment.pairs
        supplied = self.inputs["total"]
        total = read_numeric_value(
            supplied.context, supplied.selection.metric_column_id, pairs[0].right_row_index,
            rules, unit_id=self.units["total"].claims.unit.unit_id,
        )
        issues = [issue.model_copy(update={"context_role": "total"}, deep=True) for issue in total.issues]
        supplied = self.inputs["parts"]
        parts = []
        for pair in pairs:
            reading = read_numeric_value(
                supplied.context, supplied.selection.metric_column_id, pair.left_row_index,
                rules, unit_id=self.units["parts"].claims.unit.unit_id,
            )
            parts.append(reading)
            issues.extend(issue.model_copy(update={"context_role": "parts", "key": pair.key}, deep=True)
                          for issue in reading.issues)
        failures = [reading for reading in [*parts, total] if reading.status != "ready"]
        if failures:
            priority = {"unsupported": 0, "incompatible_context": 1, "insufficient_evidence": 2}
            failure = min(failures, key=lambda reading: priority[reading.status])
            code = failure.issues[0].code if failure.issues else "NUMERIC_NOT_READY"
            issues.append(_issue("PARTITION_NUMERIC_NOT_READY", "Every operand must be readable before any contribution is computed."))
            return [self.signal(failure.status, code, pair=pair, part=part, total=total, issues=issues)
                    for pair, part in zip(pairs, parts)]
        check = _reconcile(parts, total, rules)
        if check.status != "ready":
            messages = {
                "ZERO_TOTAL": "A complete all-zero partition has undefined contribution rates.",
                "ZERO_TOTAL_WITH_POSITIVE_PART": "A zero denominator contradicts an observed positive part.",
                "PART_EXCEEDS_TOTAL": "A part exceeds the independent total beyond the approved tolerance.",
                "PARTITION_TOTAL_MISMATCH": "The full partition does not reconcile with the independent total.",
                "PARTITION_PRECISION_LOSS": "Partition arithmetic was not exact at the approved precision.",
            }
            issues.append(_issue(check.code, messages[check.code]))
            return [self.signal(check.status, check.code, pair=pair, part=part, total=total, issues=issues)
                    for pair, part in zip(pairs, parts)]
        if check.tolerance_used:
            issues.append(_issue("PARTITION_WITHIN_RELATIVE_TOLERANCE", "The nonzero partition residual or excess is within the explicitly approved relative tolerance.", severity="info"))
        signals = []
        for pair, part in zip(pairs, parts):
            value, quality = _ratio(part, total, rules)
            per_signal = list(issues)
            if quality.source_fidelity == "approximate":
                per_signal.append(_issue("APPROXIMATE_INPUT", "A binary floating source retains approximate fidelity.", severity="warning"))
            if quality.arithmetic_rounding == "rounded":
                per_signal.append(_issue("RATIO_ROUNDED", "The contribution rate is rounded to the Policy output scale.", severity="info"))
            signals.append(self.signal("computed", None, pair=pair, part=part, total=total,
                                       value=value, quality=quality, issues=per_signal))
        return signals


def compute_product_contribution(
    inputs: ProductContributionInput, compatibility: ContextCompatibility,
    alignment: AlignmentResult, policy: ProductContributionPolicy,
) -> list[BusinessSignal]:
    """Compute all qualified parts or reject the complete partition.

    Invalid model arguments raise TypeError/ValueError. Business failures
    retain typed states and two operand Evidence records. Evidence assembly
    consumes the original Numeric results without another read or calculation.
    """
    for value, expected, name in (
        (inputs, ProductContributionInput, "inputs"),
        (compatibility, ContextCompatibility, "compatibility"),
        (alignment, AlignmentResult, "alignment"), (policy, ProductContributionPolicy, "policy"),
    ):
        if not isinstance(value, expected):
            raise TypeError(f"{name} must be {expected.__name__}")
    return _ProductContribution(inputs, compatibility, alignment, policy).run()


__all__ = ["compute_product_contribution"]
