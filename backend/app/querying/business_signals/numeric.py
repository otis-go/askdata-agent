"""Check numeric metadata or read one canonical cell, without business logic.

No SQL, Schema lookup, Context compatibility, key alignment, unit inference,
formula, rounding of inputs, or identity generation is performed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext
from math import isfinite
import re
from typing import Literal

from ..result_contract import ColumnMetadata, ExecutionData
from ..result_understanding.models import BusinessContext
from .models import Issue, NumericQuality, ObservedValue
from .policies import NumericRules


NumericReadStatus = Literal[
    "ready", "insufficient_evidence", "incompatible_context", "unsupported",
]
RawScalar = str | int | float | bool | None
NumericSourceKind = Literal["decimal_text", "integer", "binary_float"]


@dataclass(frozen=True)
class NumericColumnEligibility:
    """Metadata-only capability result; it never certifies any cell value.

    A ready column still needs value-level NULL, runtime-type, finite, range
    and NumericRules checks when a particular canonical cell is read later.
    """

    status: NumericReadStatus
    code: str | None = None
    message: str | None = None
    source_kind: NumericSourceKind | None = None
    decimal_shape: tuple[int, int] | None = None


@dataclass(frozen=True)
class NumericReadResult:
    """Small in-memory result, not a Signal or a new JSON wire contract.

    work_value is an exact Decimal working representation, never a formula
    result. Known rejected values have no ObservedValue, rather than falsely
    claiming unknown metadata. raw_value is retained for inspection, including
    a rejected nonfinite float; only approved text goes in ObservedValue.
    """

    status: NumericReadStatus
    observed_value: ObservedValue | None
    work_value: Decimal | None
    raw_value: RawScalar
    numeric_quality: NumericQuality
    issues: tuple[Issue, ...] = ()


# Exact producer dtype names, not Schema labels or SQL aliases.
_INTEGER_BITS = {
    "TINYINT": (8, True), "SMALLINT": (16, True), "INTEGER": (32, True),
    "BIGINT": (64, True), "HUGEINT": (128, True),
    "UTINYINT": (8, False), "USMALLINT": (16, False), "UINTEGER": (32, False),
    "UBIGINT": (64, False), "UHUGEINT": (128, False),
}
_DECIMAL_DTYPE = re.compile(r"DECIMAL\(([0-9]{1,2}),\s*([0-9]{1,2})\)", re.ASCII)
_DECIMAL_TEXT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)


def _column_numeric_source(column: ColumnMetadata) -> NumericColumnEligibility:
    """Shared source-metadata checks, before policy or native-cell checks."""
    representation = column.representation_status
    if representation == "unsupported":
        return NumericColumnEligibility("unsupported", "UNSUPPORTED_REPRESENTATION", "Representation is unsupported.")
    if representation == "lossy":
        return NumericColumnEligibility("incompatible_context", "LOSSY_REPRESENTATION", "NumericRules require preserved representation.")
    if representation not in (None, "preserved"):
        raise ValueError("invalid representation_status in column metadata")
    if representation is None or column.dtype is None or column.value_encoding is None:
        return NumericColumnEligibility(
            "insufficient_evidence", "UNKNOWN_NUMERIC_METADATA",
            "dtype, encoding and preserved representation are required.",
        )
    dtype, encoding = column.dtype, column.value_encoding
    if type(dtype) is not str or type(encoding) is not str:
        raise ValueError("dtype and encoding must be strings when supplied")
    if encoding not in ("native_json", "decimal_text"):
        return NumericColumnEligibility("unsupported", "UNSUPPORTED_ENCODING", "This codec has no approved V1 numeric reader.")

    decimal_match = _DECIMAL_DTYPE.fullmatch(dtype)
    decimal_shape: tuple[int, int] | None = None
    if decimal_match is not None:
        precision, scale = (int(part) for part in decimal_match.groups())
        if not 1 <= precision <= 38 or not 0 <= scale <= precision:
            return NumericColumnEligibility("unsupported", "UNSUPPORTED_DTYPE", "DECIMAL precision or scale is unsupported.")
        decimal_shape = precision, scale
        kind: NumericSourceKind = "decimal_text"
        expected_encoding = "decimal_text"
    elif dtype in _INTEGER_BITS:
        kind = "integer"
        expected_encoding = "native_json"
    elif dtype in ("FLOAT", "DOUBLE"):
        kind = "binary_float"
        expected_encoding = "native_json"
    else:
        return NumericColumnEligibility("unsupported", "UNSUPPORTED_DTYPE", "The physical dtype has no approved numeric path.")
    if encoding != expected_encoding:
        return NumericColumnEligibility(
            "unsupported", "CODEC_VALUE_MISMATCH",
            "Physical dtype, encoding and native value type do not agree.",
        )
    return NumericColumnEligibility("ready", source_kind=kind, decimal_shape=decimal_shape)


def _column_numeric_policy(
    column: ColumnMetadata, rules: NumericRules, source: NumericColumnEligibility,
) -> NumericColumnEligibility:
    """Shared policy checks; the reader first checks the native cell type."""
    if column.value_encoding not in rules.accepted_encodings:
        return NumericColumnEligibility(
            "incompatible_context", "ENCODING_NOT_ALLOWED",
            "This otherwise supported encoding is excluded by NumericRules.",
            source.source_kind, source.decimal_shape,
        )
    if source.source_kind == "binary_float" and (
        rules.profile != "reporting_approx_v1" or not rules.allow_binary_float
    ):
        return NumericColumnEligibility(
            "incompatible_context", "BINARY_FLOAT_NOT_ALLOWED",
            "This NumericRules profile does not permit binary floats.",
            source.source_kind, source.decimal_shape,
        )
    return source


def check_numeric_column(
    column: ColumnMetadata, numeric_rules: NumericRules,
) -> NumericColumnEligibility:
    """Check dtype, codec, representation and profile without reading rows.

    This helper accepts only the explicitly selected column's metadata, not a
    Context or a row index. It cannot infer the values of empty or NULL-only
    columns, units, row eligibility, coverage or business compatibility. The
    source and policy checks are shared with read_numeric_value; its earlier
    NULL/nonfinite/native-type checks deliberately remain value-level checks.
    """
    if not isinstance(column, ColumnMetadata):
        raise TypeError("column must be ColumnMetadata")
    if not isinstance(numeric_rules, NumericRules):
        raise TypeError("numeric_rules must be NumericRules")
    rules = NumericRules.model_validate(numeric_rules.model_dump())
    source = _column_numeric_source(column)
    if source.status != "ready":
        return source
    return _column_numeric_policy(column, rules, source)


def _text_argument(value: object, name: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")


def _locate_column(execution: ExecutionData, column_id: str) -> ColumnMetadata | None:
    """Recheck mutable positional structures; never repair or select the first."""
    columns = execution.columns
    if columns is None:
        return None
    if type(columns) is not list:
        raise ValueError("columns must be a positional list")
    ids: list[str] = []
    selected = None
    for position, column in enumerate(columns):
        if not isinstance(column, ColumnMetadata):
            raise ValueError("columns must contain ColumnMetadata")
        if type(column.id) is not str or not column.id or column.id in ids:
            raise ValueError("column IDs must be nonempty and unique")
        if type(column.ordinal) is not int or column.ordinal != position:
            raise ValueError("column ordinals must match their zero-based positions")
        ids.append(column.id)
        if column.id == column_id:
            selected = column
    if selected is None:
        raise ValueError("column_id does not exist in execution.columns")
    return selected


def _validate_rows(execution: ExecutionData, row_index: int) -> None:
    rows = execution.rows
    if rows is None:
        return
    if type(rows) is not list:
        raise ValueError("rows must be a positional list")
    if row_index >= len(rows):
        raise ValueError("row_index is outside the observed result rows")
    expected_width = len(execution.columns) if execution.columns is not None else None
    for row in rows:
        if type(row) is not list:
            raise ValueError("canonical rows must be positional lists")
        if expected_width is None:
            expected_width = len(row)
        if len(row) != expected_width:
            raise ValueError("row widths must match the supplied column structure")


def read_numeric_value(
    context: BusinessContext,
    column_id: str,
    row_index: int,
    numeric_rules: NumericRules,
    *,
    unit_id: str | None = None,
    evidence_id: str | None = None,
) -> NumericReadResult:
    """Read columns[id].ordinal -> rows[row_index][ordinal], without inference.

    TypeError/ValueError reject invalid call/positional structure. Unknown
    payload, NULL, missing metadata and known unsupported or policy-rejected
    numbers return distinct structured failures. ready only certifies numeric
    readability under NumericRules, never business compatibility or a unit.

    Supplied unit_id/evidence_id are copied as caller-owned labels, not verified
    or generated here. No ambient Decimal context is changed or inherited.
    """
    if not isinstance(context, BusinessContext):
        raise TypeError("context must be a BusinessContext")
    if not isinstance(numeric_rules, NumericRules):
        raise TypeError("numeric_rules must be NumericRules")
    _text_argument(column_id, "column_id")
    _text_argument(unit_id, "unit_id", optional=True)
    _text_argument(evidence_id, "evidence_id", optional=True)
    if type(row_index) is not int:
        raise TypeError("row_index must be an integer, not bool or text")
    if row_index < 0:
        raise ValueError("row_index must be nonnegative")

    # The frozen policy still contains a mutable encoding list; validate an
    # independent definition snapshot, including potentially mutated instances.
    rules = NumericRules.model_validate(numeric_rules.model_dump())
    execution = context.execution
    if not isinstance(execution, ExecutionData):
        raise ValueError("context.execution must be ExecutionData")
    column = _locate_column(execution, column_id)
    _validate_rows(execution, row_index)
    raw: RawScalar = None
    location = "execution.rows"
    if column is not None:
        location = f"execution.rows[{row_index}][{column.ordinal}]"

    def reject(
        status: NumericReadStatus,
        code: str,
        message: str,
        *,
        presence: Literal["sql_null", "unknown_payload", "unknown_metadata"] | None = None,
        path: str | None = None,
    ) -> NumericReadResult:
        quality = NumericQuality()
        observed = None if presence is None else ObservedValue(
            presence=presence, unit_id=unit_id, evidence_id=evidence_id,
            source_quality=quality,
        )
        return NumericReadResult(
            status=status, observed_value=observed, work_value=None,
            raw_value=raw, numeric_quality=quality,
            issues=(Issue(
                code=code, stage="numeric", result_id=context.result_id,
                evidence_paths=[path or location],
                severity="warning" if status == "insufficient_evidence" else "error",
                message=message,
            ),),
        )

    if execution.rows is None:
        return reject(
            "insufficient_evidence", "UNKNOWN_PAYLOAD", "Canonical rows were not supplied.",
            presence="unknown_payload", path="execution.rows",
        )
    if column is None:
        return reject(
            "insufficient_evidence", "UNKNOWN_COLUMNS", "Column identity metadata was not supplied.",
            presence="unknown_metadata", path="execution.columns",
        )
    raw = execution.rows[row_index][column.ordinal]
    if type(raw) not in (str, int, float, bool, type(None)):
        raise ValueError("canonical cell must be a native JSON scalar")
    if raw is None:
        return reject(
            "insufficient_evidence", "SQL_NULL", "Observed SQL NULL is not numeric zero.",
            presence="sql_null",
        )
    if type(raw) is float and not isfinite(raw):
        return reject("unsupported", "NONFINITE_VALUE", "Nonfinite floats are not readable numbers.")

    metadata_path = f"execution.columns[{column.ordinal}]"
    source = _column_numeric_source(column)
    if source.status != "ready":
        return reject(
            source.status, source.code, source.message,
            presence="unknown_metadata" if source.status == "insufficient_evidence" else None,
            path=metadata_path,
        )
    dtype = column.dtype
    kind, decimal_shape = source.source_kind, source.decimal_shape
    expected_type = {"decimal_text": str, "integer": int, "binary_float": float}[kind]
    if type(raw) is not expected_type:
        return reject("unsupported", "CODEC_VALUE_MISMATCH", "Physical dtype, encoding and native value type do not agree.", path=metadata_path)
    eligibility = _column_numeric_policy(column, rules, source)
    if eligibility.status != "ready":
        return reject(eligibility.status, eligibility.code, eligibility.message, path=metadata_path)

    if kind == "integer":
        bits, signed = _INTEGER_BITS[dtype]
        lower = -(1 << (bits - 1)) if signed else 0
        upper = (1 << (bits - int(signed))) - 1
        if not lower <= raw <= upper:
            return reject("unsupported", "INTEGER_DTYPE_RANGE", "The integer is outside its physical dtype range.")
        text = str(raw)
    elif kind == "binary_float":
        text = repr(raw)  # Shortest round-trip text of the received Python float.
    else:
        text = raw
        if _DECIMAL_TEXT.fullmatch(text) is None:
            return reject("unsupported", "INVALID_DECIMAL_TEXT", "Expected finite ASCII decimal text, without coercion.")

    # Explicit settings isolate even unusual caller traps, flags and exponent
    # limits. Decimal(text) is exact; there is no unary +, normalize or quantize.
    decimal_context = Context(
        prec=rules.decimal_precision, rounding=rules.rounding,
        Emin=-999999, Emax=999999, capitals=1, clamp=0,
        flags=[], traps=[InvalidOperation, DivisionByZero, Overflow],
    )
    with localcontext(decimal_context):
        try:
            work = Decimal(text)
        except (ArithmeticError, ValueError):
            return reject("unsupported", "INVALID_DECIMAL_TEXT", "Decimal text cannot be represented safely.")
        if not work.is_finite():
            return reject("unsupported", "NONFINITE_VALUE", "A finite Decimal working value is required.")
        digits = work.as_tuple()
        work_scale = max(0, -digits.exponent)
        if decimal_shape is not None:
            precision, scale = decimal_shape
            if work_scale > scale or (not work.is_zero() and work.adjusted() >= precision - scale):
                return reject("unsupported", "DECIMAL_DTYPE_RANGE", "Decimal value exceeds its declared physical precision or scale.")
        if not work.is_zero() and work.adjusted() >= rules.max_abs_exponent:
            return reject("unsupported", "MAGNITUDE_EXCEEDED", "Value must have absolute magnitude below the NumericRules bound.")
        if work_scale > rules.max_input_scale:
            return reject("unsupported", "SCALE_EXCEEDED", "Input scale exceeds NumericRules; no rounding was applied.")
        if len(digits.digits) > rules.decimal_precision:
            return reject("unsupported", "PRECISION_EXCEEDED", "Exact input exceeds the allowed working precision.")
        if rules.negative_inputs == "reject" and work.is_signed() and not work.is_zero():
            return reject("incompatible_context", "NEGATIVE_INPUT_NOT_ALLOWED", "NumericRules reject negative inputs.")

    quality = NumericQuality(
        source_fidelity="approximate" if kind == "binary_float" else "exact",
        source_kind=kind, arithmetic_rounding="exact", scale=work_scale,
    )
    observed = ObservedValue(
        presence="present", value=text, unit_id=unit_id, evidence_id=evidence_id,
        source_quality=quality,
    )
    return NumericReadResult(
        status="ready", observed_value=observed, work_value=work,
        raw_value=raw, numeric_quality=quality,
    )


__all__ = [
    "NumericColumnEligibility", "NumericReadResult", "NumericReadStatus",
    "NumericSourceKind", "check_numeric_column", "read_numeric_value",
]
