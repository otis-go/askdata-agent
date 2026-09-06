"""Execution-result models only; no query execution or business inference.

Unknown observations are represented by ``None``, including absent rows and
columns. An explicit empty list or zero is a known empty result, not a default.
This module does not generate identifiers, capture timestamps, or encode values.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _native_json_scalar(value: object) -> object:
    """Reject implicit numeric/date encoding, including Decimal-to-float coercion."""
    if type(value) not in (str, int, float, bool, type(None)):
        raise ValueError("row values must be native JSON scalars; encoding is external")
    return value


JsonScalar = Annotated[
    str | int | float | bool | None, BeforeValidator(_native_json_scalar)
]
ValueEncoding = Literal[
    "native_json", "decimal_text", "integer_text", "iso_date", "iso_datetime"
]
# Status is about the canonical representation, not the legacy display codec:
# preserved: dtype/driver/codec evidence verifies the observed value semantics.
# lossy: a known irreversible conversion changed an observed value.
# unsupported: no approved codec exists for the observed dtype/value pair.
# None: fidelity cannot be proved (including ambiguity or no non-NULL samples).
# The string "unknown" is deliberately not a fourth enum value.
RepresentationStatus = Literal["preserved", "lossy", "unsupported"]
Completeness = Literal["complete_query_output", "partial_query_output"]


class _ContractModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class ColumnMetadata(_ContractModel):
    """Column identity is local to a result and independent of its display name."""

    id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    name: str
    dtype: str | None = None
    # An encoding records how to interpret a value; it is not a fidelity claim.
    value_encoding: ValueEncoding | None = None
    # Column-level summary of the supplied non-NULL samples only, not omitted
    # rows or the source table: unsupported > lossy > None > preserved.
    # No non-NULL observations => None. NULL cells never establish preservation.
    # In particular, exact decimal_text may be preserved even when legacy rows
    # use a lossy float, and serializable TIMESTAMP_NS may still be unproven.
    representation_status: RepresentationStatus | None = None


class ExecutionProvenance(_ContractModel):
    """Producer-supplied provenance; missing observations remain unknown.

    ``captured_at`` holds timestamp text supplied by the producer; this model
    neither generates nor normalizes it. A scope reference is not permission,
    and a capture timestamp is not proof of a consistent database snapshot.
    """

    engine: str | None = None
    source_kind: str | None = None
    captured_at: str | None = None
    sql_submitted: bool | None = None
    submitted_sql: str | None = None
    access_scope_ref: str | None = None
    snapshot_ref: str | None = None


class ExecutionData(_ContractModel):
    """Captured execution data, not Schema metadata or an LLM interpretation.

    Rows are positional arrays aligned with ``columns``. ``total_rows`` counts
    the executed SQL's output, not source-table rows or a business population.
    ``truncated`` describes application-level truncation only. Values and
    counts are validated when known, never inferred or overwritten.
    """

    database: str | None = None
    sql: str | None = None
    success: bool | None = None
    error: str | None = None
    columns: list[ColumnMetadata] | None = None
    rows: list[list[JsonScalar]] | None = None
    returned_rows: int | None = Field(default=None, ge=0)
    total_rows: int | None = Field(default=None, ge=0)
    truncated: bool | None = None
    completeness: Completeness | None = None
    provenance: ExecutionProvenance | None = None

    @model_validator(mode="after")
    def validate_known_structure(self) -> ExecutionData:
        if self.rows and any(len(row) != len(self.rows[0]) for row in self.rows):
            raise ValueError("rows must have consistent widths")

        if self.columns is not None:
            ids = [column.id for column in self.columns]
            if len(ids) != len(set(ids)):
                raise ValueError("column ids must be unique within a result")
            if [column.ordinal for column in self.columns] != list(range(len(ids))):
                raise ValueError("column ordinals must match their zero-based positions")
            if self.rows is not None and any(
                len(row) != len(self.columns) for row in self.rows
            ):
                raise ValueError("each row must have one value per column")

        if self.rows is not None and self.returned_rows is not None:
            if self.returned_rows != len(self.rows):
                raise ValueError("returned_rows must equal the number of supplied rows")

        observed_count = len(self.rows) if self.rows is not None else self.returned_rows
        if self.total_rows is not None and observed_count is not None:
            if self.total_rows < observed_count:
                raise ValueError("total_rows cannot be less than returned_rows")
            if self.truncated is True and self.total_rows == observed_count:
                raise ValueError("a truncated result must omit at least one output row")
            if self.truncated is False and self.total_rows != observed_count:
                raise ValueError("an untruncated result cannot omit known output rows")
            if (
                self.completeness == "complete_query_output"
                and self.total_rows != observed_count
            ):
                raise ValueError("complete output must contain all known output rows")
            if (
                self.completeness == "partial_query_output"
                and self.total_rows == observed_count
            ):
                raise ValueError("partial output must omit at least one known output row")

        if self.completeness == "complete_query_output" and self.truncated is True:
            raise ValueError("complete output cannot be marked truncated")
        if self.completeness == "partial_query_output" and self.truncated is False:
            raise ValueError("partial output cannot be marked untruncated")
        return self


class ResultContract(_ContractModel):
    """Versioned execution envelope; identity is supplied, never synthesized."""

    version: Literal["1"] = "1"
    result_id: str = Field(min_length=1)
    execution: ExecutionData


__all__ = ["ColumnMetadata", "ExecutionProvenance", "ExecutionData", "ResultContract"]
