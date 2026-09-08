"""S2 regional sales change over qualified, aligned monthly input snapshots.

Only this calculator evaluates the two fixed business formulas. Compatibility,
Alignment and Numeric Reader retain their existing responsibilities; Evidence
records their captured facts. No SQL, acquisition, planning or clock is used.
"""

from __future__ import annotations

from decimal import (
    Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow, localcontext,
)

from .alignment_binding import alignment_binding_matches
from .evidence import build_signal_evidence
from .models import (
    AlignmentPair, AlignmentResult, BusinessSignal, ComputationResult,
    ContextCompatibility, ContextRole, EvidenceFormulaRef, InputDeclaration, Issue,
    NumericQuality, SignalEvidence, SignalInput, SignalStatus,
)
from .numeric import NumericReadResult, read_numeric_value
from .policies import SalesChangePolicy
from .receipt_binding import _digest, receipt_binding_matches
from .sales_change_policy import supports_monthly_sales_change_v1


def _issue(code: str, message: str, *, severity="error", stage="computation") -> Issue:
    return Issue(code=code, stage=stage, severity=severity, message=message,
                 evidence_paths=["compute_sales_change"])


def _quality(current: NumericReadResult, baseline: NumericReadResult, *,
             rounding: str, scale: int | None) -> NumericQuality:
    qualities = [current.numeric_quality, baseline.numeric_quality]
    kinds = {item.source_kind for item in qualities}
    return NumericQuality(
        source_fidelity="approximate" if any(item.source_fidelity == "approximate" for item in qualities) else "exact",
        source_kind=("binary_float" if "binary_float" in kinds else
                     next(iter(kinds)) if len(kinds) == 1 else "unknown"),
        arithmetic_rounding=rounding, scale=scale,
    )


def _calculate(current: NumericReadResult, baseline: NumericReadResult,
               policy: SalesChangePolicy, unit_id: str) -> dict[str, ComputationResult]:
    rules = policy.numeric_rules
    arithmetic = Context(
        prec=rules.decimal_precision, rounding=rules.rounding,
        Emin=-999999, Emax=999999, capitals=1, clamp=0, flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )
    with localcontext(arithmetic) as context:
        # Approved operands have magnitude <10**38 and at most 18 decimal
        # places. Their difference fits exactly at precision 80, including
        # declines; the input negative-value rule is not a rule on changes.
        difference = current.work_value - baseline.work_value
        difference_text = format(difference, "f")
        difference_scale = max(0, -difference.as_tuple().exponent)
        difference_rounding = "rounded" if context.flags[Inexact] else "exact"
        context.clear_flags()
        zero_baseline = baseline.work_value.is_zero()
        if zero_baseline:
            rate_text = None
            rate_rounding = "unknown"
        else:
            # Divide the unquantized difference, not a previously rounded
            # amount or current/baseline rounded before subtracting one.
            rate = (difference / baseline.work_value).quantize(
                Decimal((0, (1,), -rules.ratio_scale)),
            )
            rate_text = format(rate, "f")
            rate_rounding = "rounded" if context.flags[Inexact] else "exact"
    formulas = {ref.output_key: ref for ref in policy.formula_refs}
    operand_ids = ["current:metric", "baseline:metric"]
    return {
        "absolute_change": ComputationResult(
            status="computed", value=difference_text, unit_id=unit_id,
            formula_id="absolute_change", formula_version=formulas["absolute_change"].formula_version,
            input_evidence_ids=operand_ids,
            numeric_quality=_quality(current, baseline, rounding=difference_rounding, scale=difference_scale),
        ),
        "change_rate": ComputationResult(
            status="undefined" if zero_baseline else "computed", value=rate_text, unit_id="ratio",
            formula_id="change_rate", formula_version=formulas["change_rate"].formula_version,
            input_evidence_ids=operand_ids,
            numeric_quality=_quality(current, baseline, rounding=rate_rounding,
                                     scale=None if zero_baseline else rules.ratio_scale),
            reason_code="ZERO_BASELINE" if zero_baseline else None,
        ),
    }


class _SalesChange:
    def __init__(self, current, baseline, receipt, alignment, policy):
        self.inputs = {
            "current": SignalInput.model_validate(current.model_dump(mode="python")),
            "baseline": SignalInput.model_validate(baseline.model_dump(mode="python")),
        }
        self.receipt = ContextCompatibility.model_validate(receipt.model_dump(mode="python"))
        self.alignment = AlignmentResult.model_validate(alignment.model_dump(mode="python"))
        self.policy = SalesChangePolicy.model_validate(policy.model_dump(mode="python"))
        self.policy_digest = _digest("compat-policy-v1", self.policy.model_dump(mode="python"))
        self.context_digests = {
            role: _digest("context-v1", supplied.context.model_dump(mode="python"))
            for role, supplied in self.inputs.items()
        }
        self.qualified = False
        self.units: dict[ContextRole, InputDeclaration] = {}
        self.issues = [*self.receipt.issues, *self.alignment.issues, _issue(
            "SIGNAL_IDENTITY_NOT_FROZEN",
            "Signal identity generation is not frozen; signal_id is intentionally unset.",
            severity="info", stage="evidence",
        )]

    def accepted_units(self) -> bool:
        """Resolve the unit declarations already consumed by Compatibility."""
        for role, supplied in self.inputs.items():
            candidates = [declaration for declaration in supplied.declarations
                          if declaration.declaration_type == "unit"
                          and supplied.selection.metric_column_id in declaration.column_ids
                          and any(
                              ref.declaration_id == declaration.declaration_id
                              and ref.declaration_type == "unit"
                              and ref.result_id == supplied.context.result_id == declaration.result_id
                              and ref.context_digest == self.context_digests[role] == declaration.context_digest
                              for ref in self.receipt.declarations_used
                          )]
            candidates = [item for index, item in enumerate(candidates) if item not in candidates[:index]]
            if len(candidates) != 1 or candidates[0].claims.unit is None:
                return False
            self.units[role] = candidates[0]
        return True

    def evidence(self, role: ContextRole, pair: AlignmentPair | None,
                 reading: NumericReadResult | None = None) -> SignalEvidence:
        supplied = self.inputs[role]
        side = "left" if role == "current" else "right"
        row_index = None if pair is None else (
            pair.left_row_index if role == "current" else pair.right_row_index
        )
        return build_signal_evidence(
            context=supplied.context, selection=supplied.selection, context_role=role,
            evidence_id=f"{role}:metric", context_digest=self.context_digests[role],
            row_index=row_index, numeric_result=reading,
            alignment_pair=pair, alignment_side=side if pair is not None else None,
            compatibility=self.receipt if self.qualified else None,
            unit_declaration=self.units.get(role),
            formula_refs=[EvidenceFormulaRef(formula_id=ref.formula_id, formula_version=ref.formula_version)
                          for ref in self.policy.formula_refs],
        )

    def signal(self, status: SignalStatus, reason: str | None, *,
               pair: AlignmentPair | None = None, readings=None,
               computed=None, issues=()) -> BusinessSignal:
        readings = readings or {}
        evidence = [self.evidence(role, pair, readings.get(role)) for role in ("current", "baseline")]
        if computed is None:
            unit = self.units.get("current")
            computed = {ref.output_key: ComputationResult(
                status=status, formula_id=ref.formula_id, formula_version=ref.formula_version,
                unit_id="ratio" if ref.output_key == "change_rate" else (unit.claims.unit.unit_id if unit else None),
                input_evidence_ids=[item.evidence_id for item in evidence], reason_code=reason,
            ) for ref in self.policy.formula_refs}
        return BusinessSignal(
            signal_type="regional_sales_change", scope="business_key" if pair is not None else "context",
            status=status, policy_id=self.policy.policy_id, policy_version=self.policy.version,
            policy_digest=self.policy_digest, calculator_version="1",
            business_key=pair.key if pair else None,
            metric=self.receipt.normalized_metric_refs if self.qualified else [],
            current_value=evidence[0].observed_value, reference_value=evidence[1].observed_value,
            computed_value=computed, evidence=evidence, limitations=[*self.issues, *issues],
        ).model_copy(deep=True)

    def reject(self, status: SignalStatus, code: str, message: str, *, pairs=None):
        issue = _issue(code, message)
        return [self.signal(status, code, pair=pair, issues=[issue]) for pair in pairs or [None]]

    def run(self) -> list[BusinessSignal]:
        receipt, alignment = self.receipt, self.alignment
        if not receipt_binding_matches(receipt, self.inputs, self.policy):
            return self.reject("incompatible_context", "COMPATIBILITY_RECEIPT_MISMATCH",
                               "Compatibility receipt does not belong to the current input snapshot.")
        if not supports_monthly_sales_change_v1(self.policy):
            return self.reject("unsupported", "UNSUPPORTED_SALES_CHANGE_POLICY",
                               "S2 V1 supports the monthly regional paid-sales Policy profile only.")
        if receipt.status != "compatible":
            return self.reject(receipt.status, "COMPATIBILITY_NOT_COMPATIBLE",
                               "Compatibility has not qualified these inputs.")
        if (receipt.operation != "compare" or receipt.context_roles != ["current", "baseline"]
                or alignment.operation != "compare"
                or (alignment.left_role, alignment.right_role) != ("current", "baseline")):
            return self.reject("incompatible_context", "S2_OPERATION_MISMATCH",
                               "S2 requires compare with current and baseline in that role order.")
        if not alignment_binding_matches(alignment, receipt):
            return self.reject("incompatible_context", "ALIGNMENT_RECEIPT_MISMATCH",
                               "Alignment content does not belong to this Compatibility receipt.")
        self.qualified = True
        if not self.accepted_units():
            return self.reject("insufficient_evidence", "UNIT_EVIDENCE_MISSING",
                               "Each operand needs its Compatibility-consumed unit declaration.")
        if alignment.status != "aligned":
            return self.reject(alignment.status, "ALIGNMENT_NOT_ALIGNED",
                               "The entire Alignment must pass before any numeric cell is read.",
                               pairs=alignment.pairs)
        if (any(pair.status != "matched" or pair.broadcast for pair in alignment.pairs)
                or alignment.missing_left_keys or alignment.missing_right_keys or alignment.duplicate_keys
                or alignment.broadcastable or alignment.key_domain != receipt.key_domains):
            return self.reject("incompatible_context", "ALIGNMENT_SHAPE_MISMATCH",
                               "Aligned S2 output must consist only of matched, non-broadcast pairs.")
        if not alignment.pairs:
            return self.reject("insufficient_evidence", "NO_ALIGNED_PAIRS", "No business keys are available.")
        return [self.compute_pair(pair) for pair in alignment.pairs]

    def compute_pair(self, pair: AlignmentPair) -> BusinessSignal:
        readings = {}
        issues = []
        for role, row_index in (("current", pair.left_row_index), ("baseline", pair.right_row_index)):
            supplied = self.inputs[role]
            readings[role] = read_numeric_value(
                supplied.context, supplied.selection.metric_column_id, row_index,
                self.policy.numeric_rules, unit_id=self.units[role].claims.unit.unit_id,
                evidence_id=f"{role}:metric",
            )
            issues.extend(issue.model_copy(update={"context_role": role, "key": pair.key}, deep=True)
                          for issue in readings[role].issues)
        failures = [item for item in readings.values() if item.status != "ready"]
        if failures:
            priority = {"unsupported": 0, "incompatible_context": 1, "insufficient_evidence": 2}
            failure = min(failures, key=lambda item: priority[item.status])
            reason = failure.issues[0].code if failure.issues else "NUMERIC_NOT_READY"
            return self.signal(failure.status, reason, pair=pair, readings=readings, issues=issues)
        current, baseline = readings["current"], readings["baseline"]
        computed = _calculate(current, baseline, self.policy, self.units["current"].claims.unit.unit_id)
        rate = computed["change_rate"]
        if rate.status == "undefined":
            issues.append(_issue("ZERO_BASELINE", "A zero baseline leaves the change rate undefined; the difference is retained."))
        if any(result.numeric_quality.source_fidelity == "approximate" for result in computed.values()):
            issues.append(_issue("APPROXIMATE_INPUT", "A binary floating source retains approximate fidelity.",
                                 severity="warning"))
        if rate.numeric_quality.arithmetic_rounding == "rounded":
            issues.append(_issue("RATIO_ROUNDED", "The change rate is rounded to the Policy output scale.",
                                 severity="info"))
        return self.signal("undefined" if rate.status == "undefined" else "computed", rate.reason_code,
                           pair=pair, readings=readings, computed=computed, issues=issues)


def compute_sales_change(
    current: SignalInput, baseline: SignalInput, compatibility: ContextCompatibility,
    alignment: AlignmentResult, policy: SalesChangePolicy,
) -> list[BusinessSignal]:
    """Compute monthly regional changes, or return typed non-computed Signals.

    Inputs need already-issued Compatibility and Alignment receipts for the
    exact current snapshot. Malformed arguments raise TypeError/ValueError.
    A zero baseline keeps the computed absolute difference while the rate and
    top-level status are undefined. This list is not a SignalBatch.
    """
    for value, expected, name in (
        (current, SignalInput, "current"), (baseline, SignalInput, "baseline"),
        (compatibility, ContextCompatibility, "compatibility"),
        (alignment, AlignmentResult, "alignment"), (policy, SalesChangePolicy, "policy"),
    ):
        if not isinstance(value, expected):
            raise TypeError(f"{name} must be {expected.__name__}")
    return _SalesChange(current, baseline, compatibility, alignment, policy).run()


__all__ = ["compute_sales_change"]
