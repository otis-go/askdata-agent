"""Pure, non-mutating checks of the canonical-to-legacy execution projection.

This verifies supplied evidence, not SQL equivalence, database fidelity or result
authenticity. None/missing means unknown. A matching lossy projection does not
prove the original value. No execution, transport or model dependencies belong
here; the model imports below are for type checking only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import copysign, isfinite
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .models import SqlExecution
    from .result_contract import ResultContract


ConsistencyStatus = Literal["consistent", "inconsistent", "insufficient_evidence"]
_MISSING = object()
_ENCODINGS = frozenset({"native_json", "decimal_text", "integer_text", "iso_date", "iso_datetime"})
_STATUSES = frozenset({"preserved", "lossy", "unsupported"})


@dataclass(frozen=True)
class ConsistencyIssue:
    # Paths and fixed reasons only: never include SQL, IDs, column names or values.
    field: str
    reason: str


@dataclass(frozen=True)
class ConsistencyResult:
    status: ConsistencyStatus
    conflicts: tuple[ConsistencyIssue, ...] = ()
    unknowns: tuple[ConsistencyIssue, ...] = ()


class _Checks:
    def __init__(self) -> None:
        self.conflicts: list[ConsistencyIssue] = []
        self.unknowns: list[ConsistencyIssue] = []

    def conflict(self, field: str, reason: str) -> None:
        self.conflicts.append(ConsistencyIssue(field, reason))

    def unknown(self, field: str, reason: str) -> None:
        self.unknowns.append(ConsistencyIssue(field, reason))

    def result(self) -> ConsistencyResult:
        status: ConsistencyStatus = "consistent"
        if self.conflicts:
            status = "inconsistent"
        elif self.unknowns:
            status = "insufficient_evidence"
        return ConsistencyResult(status, tuple(self.conflicts), tuple(self.unknowns))


def _read(source: object, name: str) -> Any:
    return source.get(name, _MISSING) if isinstance(source, Mapping) else getattr(source, name, _MISSING)


def _unknown(value: object) -> bool:
    return value is _MISSING or value is None


def _typed(value: object, kind: type, path: str, checks: _Checks) -> bool:
    if _unknown(value):
        checks.unknown(path, "value is not known")
        return False
    if type(value) is not kind:
        checks.conflict(path, "unexpected type; coercion is not permitted")
        return False
    return True


def _identity(value: object, path: str, checks: _Checks, *, required: bool = False) -> bool:
    if required and _unknown(value):
        checks.conflict(path, "contract identity is required")
        return False
    if not _typed(value, str, path, checks):
        return False
    if not value.strip():
        checks.conflict(path, "identity must not be blank")
        return False
    return True


def _count(value: object, path: str, checks: _Checks) -> bool:
    if not _typed(value, int, path, checks):
        return False
    if value < 0:
        checks.conflict(path, "count must not be negative")
        return False
    return True


def _same_scalar(left: object, right: object) -> bool:
    # Python equality alone incorrectly equates bool/int/float.
    if type(left) is not type(right):
        return False
    if type(left) is float:
        return isfinite(left) and isfinite(right) and left == right and (
            left != 0 or copysign(1, left) == copysign(1, right)
        )
    return left == right


def _project(value: object, encoding: object) -> tuple[object, bool]:
    """Return the old codec's value and whether this observation loses precision.

    None/unsupported encoding is handled by the caller. Invalid declared codecs
    raise ValueError; no stringification, approximate comparisons or type guesses.
    """
    if encoding == "native_json":
        if type(value) not in (str, int, float, bool) or type(value) is float and not isfinite(value):
            raise ValueError("invalid native JSON scalar")
        return value, False
    if type(value) is not str:
        raise ValueError("text codec requires a string")
    if encoding == "decimal_text":
        if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
            raise ValueError("invalid decimal text")
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError("decimal must be finite")
        projected = float(number)
        return projected, not isfinite(projected) or Decimal.from_float(projected) != number
    if encoding == "integer_text":
        if not re.fullmatch(r"[+-]?[0-9]+", value):
            raise ValueError("invalid integer text")
        return int(value), False
    if encoding == "iso_date":
        parsed_date = date.fromisoformat(value)
        if parsed_date.isoformat() != value:
            raise ValueError("date text is not in the producer's ISO format")
        return value, False
    if encoding == "iso_datetime":
        parsed_datetime = datetime.fromisoformat(value)
        if parsed_datetime.isoformat() != value:
            raise ValueError("datetime text is not in the producer's ISO format")
        return value, False
    raise ValueError("unrecognized declared codec")


def _compare_cell(value: object, observed: object, column: object, path: str, checks: _Checks) -> None:
    if value is None:
        if observed is not None:
            checks.conflict(path, "NULL disagrees with the legacy value")
        return
    encoding = _read(column, "value_encoding")
    status = _read(column, "representation_status")
    if status == "unsupported" or _unknown(encoding):
        checks.unknown(path, "no supported declared projection codec")
        return
    try:
        projected, lossy = _project(value, encoding)
    except (ValueError, InvalidOperation, OverflowError):
        checks.conflict(path, "value does not satisfy the declared codec")
        return
    if type(projected) is float and not isfinite(projected):
        # Legacy transports may turn infinity into NULL. Neither form proves
        # the finite Decimal, so do not pretend to verify this unsupported path.
        if observed is None or type(observed) is float and observed == projected:
            checks.unknown(path, "projection overflows the finite legacy numeric range")
        else:
            checks.conflict(path, "legacy value differs from the overflow projection")
        return
    if not _same_scalar(projected, observed):
        checks.conflict(path, "legacy value/type differs from the declared projection")
    elif lossy or status == "lossy":
        checks.unknown(path, "matching projection is not reversible")


def validate_execution_consistency(
    legacy_execution: SqlExecution | Mapping[str, Any],
    result_contract: ResultContract | None,
) -> ConsistencyResult:
    """Compare evidence without changing inputs or synthesizing metadata/IDs.

    Conflicts always take precedence over missing evidence. ``consistent`` is
    scoped to these supplied fields and declared codecs, not physical fidelity.
    A missing contract is compatible but never a positive consistency verdict.
    """
    checks = _Checks()
    legacy_scalars = {
        name: _read(legacy_execution, name)
        for name in ("database", "sql", "success", "error")
    }
    valid_scalars = {
        name: _typed(value, bool if name == "success" else str, f"legacy.{name}", checks)
        for name, value in legacy_scalars.items()
    }
    legacy_id = _read(legacy_execution, "result_id")
    valid_legacy_id = _identity(legacy_id, "legacy.result_id", checks)
    columns = _read(legacy_execution, "columns")
    rows = _read(legacy_execution, "rows")
    valid_columns = _typed(columns, list, "legacy.columns", checks)
    if valid_columns and any(type(name) is not str for name in columns):
        checks.conflict("legacy.columns", "column names must be strings")
        valid_columns = False
    valid_rows = _typed(rows, list, "legacy.rows", checks)
    if valid_rows:
        for index, row in enumerate(rows):
            if type(row) is not dict or any(type(key) is not str for key in row):
                checks.conflict(f"legacy.rows[{index}]", "legacy row must be a string-keyed dict")
                valid_rows = False
            elif valid_columns and set(row) != set(columns):
                checks.conflict(f"legacy.rows[{index}]", "row keys disagree with columns")
                valid_rows = False
    row_count = _read(legacy_execution, "row_count")
    # This optional transport field does not exist on SqlExecution.
    if not _unknown(row_count) and _count(row_count, "legacy.row_count", checks):
        if type(rows) is list and row_count != len(rows):
            checks.conflict("legacy.row_count", "row_count differs from the legacy row count")
    if result_contract is None:
        checks.unknown("result_contract", "no contract was supplied")
        return checks.result()

    if _read(result_contract, "version") != "1":
        checks.conflict("result_contract.version", "unsupported contract version")
    contract_id = _read(result_contract, "result_id")
    valid_contract_id = _identity(contract_id, "result_contract.result_id", checks, required=True)
    if valid_legacy_id and valid_contract_id and legacy_id != contract_id:
        checks.conflict("result_id", "known execution identities disagree")
    data = _read(result_contract, "execution")
    if _unknown(data) or not (
        isinstance(data, Mapping)
        or all(hasattr(data, name) for name in ("sql", "success", "error", "columns", "rows", "returned_rows"))
    ):
        checks.conflict("result_contract.execution", "execution object is required")
        return checks.result()
    for name, legacy_value in legacy_scalars.items():
        value = _read(data, name)
        valid = _typed(value, bool if name == "success" else str, f"execution.{name}", checks)
        if valid and valid_scalars[name] and value != legacy_value:
            checks.conflict(name, "known execution fields disagree")

    metadata = _read(data, "columns")
    canonical_rows = _read(data, "rows")
    valid_metadata = _typed(metadata, list, "execution.columns", checks)
    if valid_metadata:
        ids: set[str] = set()
        for index, column in enumerate(metadata):
            path = f"execution.columns[{index}]"
            column_id, ordinal, name = (_read(column, key) for key in ("id", "ordinal", "name"))
            if not _identity(column_id, f"{path}.id", checks, required=True):
                valid_metadata = False
            elif column_id in ids:
                checks.conflict(f"{path}.id", "column identity is duplicated")
                valid_metadata = False
            else:
                ids.add(column_id)
            if type(ordinal) is not int or ordinal != index:
                checks.conflict(f"{path}.ordinal", "ordinal must match the zero-based position")
                valid_metadata = False
            if type(name) is not str:
                checks.conflict(f"{path}.name", "column name must be a string")
                valid_metadata = False
            # Declared metadata must be valid even for empty/all-NULL results.
            # This checks vocabulary, not the physical fidelity of a valid label.
            for attribute, allowed in (("value_encoding", _ENCODINGS), ("representation_status", _STATUSES)):
                declaration = _read(column, attribute)
                if not _unknown(declaration) and (type(declaration) is not str or declaration not in allowed):
                    checks.conflict(f"{path}.{attribute}", "unrecognized metadata declaration")
                    valid_metadata = False
        if valid_metadata and valid_columns and [_read(column, "name") for column in metadata] != columns:
            checks.conflict("columns", "ordered column names disagree")

    valid_canonical_rows = _typed(canonical_rows, list, "execution.rows", checks)
    if valid_canonical_rows:
        width = len(metadata) if valid_metadata else len(columns) if valid_columns else None
        for index, row in enumerate(canonical_rows):
            if type(row) is not list:
                checks.conflict(f"execution.rows[{index}]", "canonical row must be a positional list")
                valid_canonical_rows = False
                continue
            if width is None:
                width = len(row)
            if len(row) != width:
                checks.conflict(f"execution.rows[{index}]", "row width disagrees with column positions")
                valid_canonical_rows = False
            if any(type(value) not in (str, int, float, bool, type(None)) or type(value) is float and not isfinite(value) for value in row):
                checks.conflict(f"execution.rows[{index}]", "canonical row contains a non-JSON scalar")
                valid_canonical_rows = False
        if type(rows) is list and len(canonical_rows) != len(rows):
            checks.conflict("rows", "canonical and legacy row counts disagree")
    returned_rows = _read(data, "returned_rows")
    if _count(returned_rows, "execution.returned_rows", checks):
        if type(rows) is list and returned_rows != len(rows):
            checks.conflict("execution.returned_rows", "returned_rows differs from the legacy row count")
        if type(canonical_rows) is list and returned_rows != len(canonical_rows):
            checks.conflict("execution.returned_rows", "returned_rows differs from the canonical row count")

    if valid_metadata and valid_canonical_rows and valid_rows:
        last_ordinal = {_read(column, "name"): index for index, column in enumerate(metadata)}
        for row_index, (canonical_row, legacy_row) in enumerate(zip(canonical_rows, rows)):
            for ordinal, column in enumerate(metadata):
                name = _read(column, "name")
                path = f"rows[{row_index}][{ordinal}]"
                if last_ordinal[name] != ordinal:
                    checks.unknown(path, "earlier duplicate-name value is absent from legacy dict")
                elif name not in legacy_row:
                    checks.conflict(path, "projected column is absent from the legacy row")
                else:
                    _compare_cell(canonical_row[ordinal], legacy_row[name], column, path, checks)
    return checks.result()


__all__ = ["ConsistencyIssue", "ConsistencyResult", "validate_execution_consistency"]
