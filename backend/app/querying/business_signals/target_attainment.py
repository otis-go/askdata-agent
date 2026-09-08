"""S1 calculation over already qualified and aligned captured inputs.

No SQL, acquisition, Compatibility evaluation or key alignment runs here.
Content bindings prevent stale-result reuse; they do not authenticate callers.
The return value is a list of individual BusinessSignals, not a SignalBatch.
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
from .policies import TargetAttainmentPolicy
from .receipt_binding import _digest, receipt_binding_matches


def _issue(code: str, message: str, *, severity="error", stage="computation") -> Issue:
    return Issue(code=code, stage=stage, severity=severity, message=message,
                 evidence_paths=["compute_target_attainment"])


def _ratio(actual: NumericReadResult, target: NumericReadResult,
           policy: TargetAttainmentPolicy) -> tuple[str, NumericQuality]:
    rules = policy.numeric_rules
    # An explicit Context also isolates traps, flags and exponent bounds from
    # the caller. Neither input is quantized; only the final ratio is rounded.
    arithmetic = Context(
        prec=rules.decimal_precision, rounding=rules.rounding,
        Emin=-999999, Emax=999999, capitals=1, clamp=0, flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )
    with localcontext(arithmetic) as context:
        value = (actual.work_value / target.work_value).quantize(
            Decimal((0, (1,), -rules.ratio_scale)),
        )
        rounded = context.flags[Inexact]
    qualities = [actual.numeric_quality, target.numeric_quality]
    kinds = {item.source_kind for item in qualities}
    approximate = any(item.source_fidelity == "approximate" for item in qualities)
    quality = NumericQuality(
        source_fidelity="approximate" if approximate else "exact",
        source_kind=("binary_float" if "binary_float" in kinds else
                     next(iter(kinds)) if len(kinds) == 1 else "unknown"),
        arithmetic_rounding="rounded" if rounded else "exact", scale=rules.ratio_scale,
    )
    return format(value, "f"), quality


class _TargetAttainment:
    def __init__(self, actual, target, receipt, alignment, policy):
        # Reconstruction validates shallow-frozen containers and detaches all
        # output evidence from caller-owned inputs, receipts and policy lists.
        self.inputs = {
            "actual": SignalInput.model_validate(actual.model_dump(mode="python")),
            "target": SignalInput.model_validate(target.model_dump(mode="python")),
        }
        self.receipt = ContextCompatibility.model_validate(receipt.model_dump(mode="python"))
        self.alignment = AlignmentResult.model_validate(alignment.model_dump(mode="python"))
        self.policy = TargetAttainmentPolicy.model_validate(policy.model_dump(mode="python"))
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
        """Resolve exactly the declarations already consumed by Compatibility.

        This does not reassess issuer, source, scale equality or scope rules.
        The whole receipt and declaration content have already been bound.
        """
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
            # Compatibility permits repeated identical declarations. Preserve
            # receipt multiplicity in its binding, but resolve one content here.
            candidates = [item for index, item in enumerate(candidates) if item not in candidates[:index]]
            if len(candidates) != 1 or candidates[0].claims.unit is None:
                return False
            self.units[role] = candidates[0]
        return True

    def evidence(self, role: ContextRole, pair: AlignmentPair | None,
                 reading: NumericReadResult | None = None) -> SignalEvidence:
        supplied = self.inputs[role]
        side = "left" if role == "actual" else "right"
        row_index = None if pair is None else (
            pair.left_row_index if role == "actual" else pair.right_row_index
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
               pair: AlignmentPair | None = None, readings=None, value=None,
               quality=None, issues=()) -> BusinessSignal:
        readings = readings or {}
        evidence = [self.evidence(role, pair, readings.get(role)) for role in ("actual", "target")]
        formula = self.policy.formula_refs[0]
        return BusinessSignal(
            signal_type="monthly_regional_target_attainment",
            scope="business_key" if pair is not None else "context", status=status,
            policy_id=self.policy.policy_id, policy_version=self.policy.version,
            policy_digest=self.policy_digest, calculator_version="1",
            business_key=pair.key if pair else None,
            metric=self.receipt.normalized_metric_refs if self.qualified else [],
            current_value=evidence[0].observed_value, reference_value=evidence[1].observed_value,
            computed_value={"attainment_rate": ComputationResult(
                status=status, value=value, unit_id="ratio", formula_id=formula.formula_id,
                formula_version=formula.formula_version,
                input_evidence_ids=[item.evidence_id for item in evidence],
                numeric_quality=quality or NumericQuality(), reason_code=reason,
            )}, evidence=evidence, limitations=[*self.issues, *issues],
        ).model_copy(deep=True)

    def reject(self, status: SignalStatus, code: str, message: str, *, pairs=None):
        issue = _issue(code, message)
        return [self.signal(status, code, pair=pair, issues=[issue]) for pair in pairs or [None]]

    def run(self) -> list[BusinessSignal]:
        receipt, alignment = self.receipt, self.alignment
        if not receipt_binding_matches(receipt, self.inputs, self.policy):
            return self.reject("incompatible_context", "COMPATIBILITY_RECEIPT_MISMATCH",
                               "Compatibility receipt does not belong to the current input snapshot.")
        if receipt.status != "compatible":
            return self.reject(receipt.status, "COMPATIBILITY_NOT_COMPATIBLE",
                               "Compatibility has not qualified these inputs.")
        if (receipt.operation != "divide" or receipt.context_roles != ["actual", "target"]
                or alignment.operation != "divide"
                or (alignment.left_role, alignment.right_role) != ("actual", "target")):
            return self.reject("incompatible_context", "S1_OPERATION_MISMATCH",
                               "S1 requires divide with actual and target in that role order.")
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
                               "Aligned S1 output must consist only of matched, non-broadcast pairs.")
        if not alignment.pairs:
            return self.reject("insufficient_evidence", "NO_ALIGNED_PAIRS", "No business keys are available.")
        return [self.compute_pair(pair) for pair in alignment.pairs]

    def compute_pair(self, pair: AlignmentPair) -> BusinessSignal:
        readings = {}
        issues = []
        for role, row_index in (("actual", pair.left_row_index), ("target", pair.right_row_index)):
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
        actual, target = readings["actual"], readings["target"]
        if target.work_value == 0:
            issues.append(_issue("ZERO_DENOMINATOR", "A zero target makes attainment undefined."))
            return self.signal("undefined", "ZERO_DENOMINATOR", pair=pair, readings=readings, issues=issues)
        value, quality = _ratio(actual, target, self.policy)
        if quality.source_fidelity == "approximate":
            issues.append(_issue("APPROXIMATE_INPUT", "A binary floating source retains approximate fidelity.",
                                 severity="warning"))
        if quality.arithmetic_rounding == "rounded":
            issues.append(_issue("RATIO_ROUNDED", "The ratio is rounded to the Policy output scale.",
                                 severity="info"))
        return self.signal("computed", None, pair=pair, readings=readings, value=value,
                           quality=quality, issues=issues)


def compute_target_attainment(
    actual: SignalInput, target: SignalInput, compatibility: ContextCompatibility,
    alignment: AlignmentResult, policy: TargetAttainmentPolicy,
) -> list[BusinessSignal]:
    """Compute S1 per matched key, or return typed non-computed Signals.

    Malformed model arguments raise TypeError/ValueError. Valid but stale or
    unqualified receipts produce non-computed Signals without numeric reads.
    Legacy AlignmentResults without producer bindings cannot authorize S1.
    """
    for value, expected, name in (
        (actual, SignalInput, "actual"), (target, SignalInput, "target"),
        (compatibility, ContextCompatibility, "compatibility"),
        (alignment, AlignmentResult, "alignment"), (policy, TargetAttainmentPolicy, "policy"),
    ):
        if not isinstance(value, expected):
            raise TypeError(f"{name} must be {expected.__name__}")
    return _TargetAttainment(actual, target, compatibility, alignment, policy).run()


__all__ = ["compute_target_attainment"]
