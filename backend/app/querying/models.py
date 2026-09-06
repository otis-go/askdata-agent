from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .result_contract import ResultContract


@dataclass
class SqlExecution:
    sql: str
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # Optional metadata does not change legacy positional construction, equality,
    # or repr. Dataclass reflection/asdict still includes both fields.
    result_contract: ResultContract | None = field(
        default=None, kw_only=True, compare=False, repr=False,
    )
    result_id: str | None = field(
        default=None, kw_only=True, compare=False, repr=False,
    )
